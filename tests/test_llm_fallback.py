"""LLM resilience: retries, fallback model, extractive answer, empty and leaked replies.

The OpenAI client is replaced with a scripted fake, so these tests make no network calls.
"""

import time
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APIStatusError, AuthenticationError, BadRequestError, RateLimitError

from bot import config, llm, rag
from bot.llm import LLMUnavailable
from bot.rag import Hit

URL = "https://openrouter.ai/api/v1/chat/completions"


def _response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, headers=headers, request=httpx.Request("POST", URL))


def reply(text: str | None) -> Any:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class FakeCompletions:
    """Each call pops the next scripted outcome: an exception to raise, or a reply."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, script: list[Any]) -> None:
        self.completions = FakeCompletions(script)
        self.chat = SimpleNamespace(completions=self.completions)


@pytest.fixture(autouse=True)
def clean_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.setattr(llm, "_semaphore", None)
    monkeypatch.setattr(llm, "_reasoning_supported", True)
    monkeypatch.setattr(llm, "BACKOFF_BASE", 0.0)
    monkeypatch.setattr(config, "LLM_MAX_RETRIES", 2)
    monkeypatch.setattr(config, "LLM_FALLBACK_MODEL", "")
    monkeypatch.setattr(config, "QUERY_TRANSLATE", False)
    rag.cache._items.clear()


def use(monkeypatch: pytest.MonkeyPatch, script: list[Any]) -> FakeClient:
    client = FakeClient(script)
    monkeypatch.setattr(llm, "_client", client)
    return client


def rate_limited() -> RateLimitError:
    return RateLimitError("slow down", response=_response(429), body=None)


def server_error() -> APIStatusError:
    return APIStatusError("boom", response=_response(500), body=None)


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    client = use(monkeypatch, [rate_limited(), reply("The fee is SGD 300.")])
    assert await llm.complete("sys", "user") == "The fee is SGD 300."
    assert len(client.completions.calls) == 2


@pytest.mark.asyncio
async def test_fallback_model_used_after_primary_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "LLM_MAX_RETRIES", 0)
    monkeypatch.setattr(config, "LLM_FALLBACK_MODEL", "backup/model:free")
    client = use(monkeypatch, [server_error(), reply("Fallback answer.")])
    assert await llm.complete("sys", "user") == "Fallback answer."
    models = [c["model"] for c in client.completions.calls]
    assert models == [config.LLM_MODEL, "backup/model:free"]


@pytest.mark.asyncio
async def test_unavailable_after_retries_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    client = use(monkeypatch, [rate_limited(), rate_limited(), rate_limited()])
    with pytest.raises(LLMUnavailable):
        await llm.complete("sys", "user")
    assert len(client.completions.calls) == 3  # 1 try + LLM_MAX_RETRIES (2)


@pytest.mark.asyncio
async def test_spent_daily_quota_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_ms = int((time.time() + 6 * 3600) * 1000)  # daily cap resets in six hours
    headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset_ms)}
    spent = RateLimitError("daily cap", response=_response(429, headers), body=None)
    client = use(monkeypatch, [spent, reply("should not be reached")])
    with pytest.raises(LLMUnavailable):
        await llm.complete("sys", "user")
    assert len(client.completions.calls) == 1


@pytest.mark.asyncio
async def test_client_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = AuthenticationError("bad key", response=_response(401), body=None)
    client = use(monkeypatch, [auth])
    with pytest.raises(LLMUnavailable):
        await llm.complete("sys", "user")
    assert len(client.completions.calls) == 1


@pytest.mark.asyncio
async def test_none_content_is_failure_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    client = use(monkeypatch, [reply(None)])
    with pytest.raises(LLMUnavailable):
        await llm.complete("sys", "user")
    assert len(client.completions.calls) == 1


@pytest.mark.asyncio
async def test_reasoning_text_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, [reply("<think>secret scratch work</think>\nThe fee is SGD 300.")])
    assert await llm.complete("sys", "user") == "The fee is SGD 300."


@pytest.mark.asyncio
async def test_pre_answer_scratch_text_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, [reply("Let me think about the venue...\nFinal answer: Yes.")])
    assert await llm.complete("sys", "user") == "Yes."


@pytest.mark.asyncio
async def test_unclosed_think_block_is_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, [reply("<think>still thinking")])
    with pytest.raises(LLMUnavailable):
        await llm.complete("sys", "user")


@pytest.mark.asyncio
async def test_reasoning_param_dropped_when_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = BadRequestError("unknown param", response=_response(400), body=None)
    client = use(monkeypatch, [bad, reply("Ok."), reply("Ok again.")])
    assert await llm.complete("sys", "user") == "Ok."
    assert "extra_body" in client.completions.calls[0]
    assert "extra_body" not in client.completions.calls[1]
    assert await llm.complete("sys", "user") == "Ok again."
    assert "extra_body" not in client.completions.calls[2]


@pytest.mark.asyncio
async def test_extractive_answer_when_llm_down(monkeypatch: pytest.MonkeyPatch) -> None:
    hit = Hit(text="Question: Is food provided?\nAnswer: Food is provided.",
              url=f"{config.BASE_URL}/", source="faq", dist=0.2)
    monkeypatch.setattr(rag, "retrieve_sync", lambda q: [hit])
    use(monkeypatch, [server_error(), server_error(), server_error()])
    answer = await rag.answer("Is food provided?")
    assert answer is not None
    assert answer.mode == "extractive"
    assert answer.text == hit.text
    assert answer.url == hit.url


@pytest.mark.asyncio
async def test_no_answer_sentinel_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    hit = Hit(text="Some unrelated chunk", url=f"{config.BASE_URL}/", source="faq", dist=0.2)
    monkeypatch.setattr(rag, "retrieve_sync", lambda q: [hit])
    use(monkeypatch, [reply("NO_ANSWER")])
    assert await rag.answer("Anything?") is None


@pytest.mark.asyncio
async def test_extractive_answers_are_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    hit = Hit(text="Some chunk", url=f"{config.BASE_URL}/", source="faq", dist=0.2)
    monkeypatch.setattr(rag, "retrieve_sync", lambda q: [hit])
    use(monkeypatch, [server_error(), server_error(), server_error(), reply("Fresh answer.")])
    assert (await rag.answer("Q?")).mode == "extractive"  # type: ignore[union-attr]
    assert (await rag.answer("Q?")).text == "Fresh answer."  # type: ignore[union-attr]
