"""OpenRouter client with retries, a fallback model and a concurrency cap.

Never logs user text or IDs. Callers get either a clean reply or LLMUnavailable.
"""

import asyncio
import logging
import random
import re
import time
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    BadRequestError,
    RateLimitError,
)

from . import config

log = logging.getLogger("bot.llm")

BASE_URL = "https://openrouter.ai/api/v1"
RETRY_AFTER_CAP = 10.0
BACKOFF_BASE = 1.0
TEMPERATURE = 0.2
MAX_TOKENS = 500
REASONING_OFF: dict[str, Any] = {"reasoning": {"effort": "none"}}
FINAL_MARKER = "Final answer:"


class LLMUnavailable(Exception):
    """Raised when the primary model and the fallback both fail."""


class _Failed(Exception):
    """One model gave up after its retries. Internal only."""


_client: AsyncOpenAI | None = None
_semaphore: asyncio.Semaphore | None = None
_reasoning_supported = config.LLM_REASONING_OFF


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=BASE_URL,
            api_key=config.require("OPENROUTER_API_KEY"),
            timeout=config.LLM_TIMEOUT,
            max_retries=0,
            default_headers={"HTTP-Referer": config.BASE_URL, "X-Title": "AYLS Summit Bot"},
        )
    return _client


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(config.LLM_CONCURRENCY)
    return _semaphore


def strip_reasoning(text: str) -> str:
    """Remove leaked thinking: <think> blocks, and anything before a final-answer marker."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    if "</think>" in text.lower():
        text = re.split(r"</think>", text, flags=re.IGNORECASE)[-1]
    if "<think>" in text.lower():
        return ""  # unclosed thinking block: nothing usable
    if FINAL_MARKER in text:
        text = text.split(FINAL_MARKER)[-1]
    return text.strip()


def _retry_delay(attempt: int, err: Exception) -> float:
    response = getattr(err, "response", None)
    header = response.headers.get("retry-after") if response is not None else None
    if header:
        try:
            return min(float(header), RETRY_AFTER_CAP)
        except ValueError:
            pass
    return BACKOFF_BASE * (2 ** (attempt - 1)) + random.uniform(0, 0.5)


def _quota_resets_soon(err: Exception) -> bool:
    """False when OpenRouter reports the quota is spent and resets later than the retry cap.

    Daily free-tier caps reset hours away, so retrying them only burns more requests.
    """
    headers = err.response.headers if getattr(err, "response", None) is not None else {}
    if headers.get("x-ratelimit-remaining") != "0":
        return True
    try:
        reset_at = int(headers["x-ratelimit-reset"]) / 1000
    except (KeyError, ValueError):
        return True
    return reset_at - time.time() <= RETRY_AFTER_CAP


def _is_retryable(err: Exception) -> bool:
    if isinstance(err, RateLimitError):
        return _quota_resets_soon(err)
    if isinstance(err, (APITimeoutError, APIConnectionError)):
        return True
    return isinstance(err, APIStatusError) and err.status_code >= 500


async def _create(model: str, system: str, user: str) -> Any:
    global _reasoning_supported
    client = _get_client()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    base: dict[str, Any] = {"model": model, "messages": messages,
                            "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS}
    if not _reasoning_supported:
        return await client.chat.completions.create(**base)
    try:
        return await client.chat.completions.create(**base, extra_body=REASONING_OFF)
    except BadRequestError:
        # Provider rejected the reasoning parameter: stop sending it and retry once.
        _reasoning_supported = False
        log.warning("reasoning parameter rejected; continuing without it")
        return await client.chat.completions.create(**base)


async def _complete_model(model: str, system: str, user: str, retries: int) -> str:
    attempt = 0
    start = time.monotonic()
    while True:
        attempt += 1
        try:
            async with _get_semaphore():
                resp = await _create(model, system, user)
        except Exception as err:
            if _is_retryable(err) and attempt <= retries:
                delay = _retry_delay(attempt, err)
                log.info("llm retry model=%s attempt=%d delay=%.1fs", model, attempt, delay)
                await asyncio.sleep(delay)
                continue
            log.warning("llm failed model=%s attempts=%d error=%s",
                        model, attempt, type(err).__name__)
            raise _Failed from err

        content = resp.choices[0].message.content if resp.choices else None
        text = strip_reasoning(content or "")
        if not text:
            log.warning("llm empty reply model=%s attempts=%d", model, attempt)
            raise _Failed
        log.info("llm ok model=%s attempts=%d latency_ms=%d",
                 model, attempt, int((time.monotonic() - start) * 1000))
        return text


async def complete(system: str, user: str) -> str:
    """Return the model's plain-text reply, or raise LLMUnavailable."""
    try:
        return await _complete_model(config.LLM_MODEL, system, user, config.LLM_MAX_RETRIES)
    except _Failed:
        pass
    if not config.LLM_FALLBACK_MODEL:
        raise LLMUnavailable
    try:
        return await _complete_model(config.LLM_FALLBACK_MODEL, system, user, retries=0)
    except _Failed as err:
        raise LLMUnavailable from err
