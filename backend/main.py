"""
Summit Translate — FastAPI backend

Two paths share this one service (spec §3):
  - on-demand : POST /translate           (request/response, text in -> text out)
  - live      : WS   /ws/live             (WebSocket session; STT/TTS wiring is TODO)

Secrets are read via a hybrid resolver (see get_config):
  - On Cloud Run  -> GCP Secret Manager
  - Local dev     -> environment variables loaded from .env

Nothing here persists conversation content. log_usage_event() is deliberately
built so it CANNOT receive translation text or audio (spec §8).
"""

import os
import json
import time
import hmac
import base64
import hashlib
import asyncio
import logging
from functools import lru_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("summit")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Config resolver  —  Secret Manager (prod) / .env (local)
# ─────────────────────────────────────────────────────────────────────────────
# Cloud Run sets K_SERVICE. Use its presence to decide where secrets come from.
RUNNING_ON_CLOUD_RUN = bool(os.getenv("K_SERVICE"))

# Local dev only: pull values from backend/.env if python-dotenv is installed.
if not RUNNING_ON_CLOUD_RUN:
    try:
        from pathlib import Path
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).with_name(".env"))  # loads backend/.env regardless of cwd
    except ImportError:
        pass


def _access_secret_manager(secret_id: str) -> str:
    """Read the latest version of a secret from GCP Secret Manager."""
    from google.cloud import secretmanager
    # GCP_PROJECT_ID must be a plain env var, NOT a secret — you need the project
    # id *before* you can address Secret Manager (bootstrap chicken-and-egg).
    project_id = os.environ["GCP_PROJECT_ID"]
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    resp = client.access_secret_version(request={"name": name})
    return resp.payload.data.decode("utf-8")


@lru_cache(maxsize=None)
def get_config(secret_id: str, env_var: str, *, required: bool = True,
               default: str | None = None) -> str | None:
    """
    Resolve one config value, cached for the process lifetime.

      secret_id : name in Secret Manager  (e.g. "anthropic-api-key")
      env_var   : name in the environment (e.g. "ANTHROPIC_API_KEY")

    On Cloud Run reads Secret Manager; locally reads the env var (from .env).
    """
    if RUNNING_ON_CLOUD_RUN:
        try:
            return _access_secret_manager(secret_id)
        except Exception as exc:
            if required:
                raise RuntimeError(f"Could not read secret '{secret_id}': {exc}") from exc
            return default

    value = os.getenv(env_var, default)
    if required and not value:
        raise RuntimeError(
            f"Missing required config '{env_var}'. Set it in backend/.env for local dev."
        )
    return value


class Config:
    """Loaded once at startup."""
    def __init__(self) -> None:
        # Secrets (Secret Manager id, .env var name)
        self.anthropic_api_key = get_config("anthropic-api-key", "ANTHROPIC_API_KEY")
        self.app_passphrase    = get_config("app-passphrase",    "APP_PASSPHRASE")
        self.signing_secret    = get_config("app-signing-secret", "APP_SIGNING_SECRET")

        # Non-secret runtime settings (plain env vars, with sane defaults)
        self.model           = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")  # Haiku only (§10)
        self.session_minutes = int(os.getenv("LIVE_SESSION_MINUTES", "12"))               # auto-disconnect (§10)
        self.allowed_origin  = os.getenv("ALLOWED_ORIGIN", "*")                            # frontend origin for CORS


config = Config()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Static event glossary (spec §6)  —  injected into the prompt, not a database
# ─────────────────────────────────────────────────────────────────────────────
# Starter terms for the summit's themes. Edit freely up to event day.
# Keys are English; values are the preferred Thai rendering.
GLOSSARY: dict[str, str] = {
    "human trafficking":        "การค้ามนุษย์",
    "survivor":                 "ผู้รอดชีวิต",
    "social entrepreneurship":  "ผู้ประกอบการเพื่อสังคม",
    "social enterprise":        "วิสาหกิจเพื่อสังคม",
    "stakeholder":              "ผู้มีส่วนได้ส่วนเสีย",
    "grassroots":               "ระดับรากหญ้า",
    "sustainability":           "ความยั่งยืน",
    "NGO":                      "องค์กรพัฒนาเอกชน",
}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Usage logging (spec §8)  —  metadata only, structurally content-free
# ─────────────────────────────────────────────────────────────────────────────
def log_usage_event(*, mode: str, direction: str, status: str,
                    failure_type: str | None = None,
                    session_duration_s: float | None = None) -> None:
    """
    Log that an interaction happened — never what was said.

    There is deliberately NO parameter for source text, translated text, or
    audio. Do not add one. This enforces §8 in the code's shape, not in a
    comment someone has to remember.
    """
    event = {
        "ts": round(time.time(), 3),
        "mode": mode,            # "on_demand" | "live"
        "direction": direction,  # "en-th" | "th-en"
        "status": status,        # "success" | "failure"
    }
    if failure_type is not None:
        event["failure_type"] = failure_type
    if session_duration_s is not None:
        event["session_duration_s"] = round(session_duration_s, 1)
    logger.info("usage_event %s", json.dumps(event))


# ─────────────────────────────────────────────────────────────────────────────
# 4. Auth  —  stateless HMAC-signed passphrase token (works across instances)
# ─────────────────────────────────────────────────────────────────────────────
# No Redis / DB (spec §3). A signed token is verifiable by any Cloud Run instance
# using the shared signing secret, so horizontal scaling doesn't break sessions.
TOKEN_TTL_SECONDS = 8 * 3600  # covers a full event day


def _sign(payload: str) -> str:
    digest = hmac.new(config.signing_secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def issue_token(ttl: int = TOKEN_TTL_SECONDS) -> str:
    expiry = str(int(time.time()) + ttl)
    return f"{expiry}.{_sign(expiry)}"


def verify_token(token: str) -> bool:
    try:
        expiry, sig = token.split(".", 1)
    except ValueError:
        return False
    if not hmac.compare_digest(sig, _sign(expiry)):  # constant-time
        return False
    return int(expiry) > int(time.time())


def check_passphrase(candidate: str) -> bool:
    return hmac.compare_digest(candidate.strip(), config.app_passphrase.strip())


# ─────────────────────────────────────────────────────────────────────────────
# 5. Translation  —  Claude Haiku with Thai-aware prompt + glossary injection
# ─────────────────────────────────────────────────────────────────────────────
from anthropic import Anthropic

_anthropic = Anthropic(api_key=config.anthropic_api_key)


def _system_prompt(direction: str) -> str:
    source, target = ("Thai", "English") if direction == "th-en" else ("English", "Thai")
    glossary = "\n".join(f"- {en} = {th}" for en, th in GLOSSARY.items())
    # Thai-specific reasoning baked into the instructions:
    #  - Thai is written with no spaces between words; segment by context.
    #  - Thai verbs are not inflected for tense; infer tense from context/time words
    #    and render natural {target} tense.
    #  - Politeness particles (ครับ/ค่ะ) are gendered and speaker-dependent. Speaker
    #    gender is unknown here, so use a polite, gender-neutral register and only
    #    carry a particle across if it is present in the source.
    #  - Topics include sensitive subjects (trafficking, survivor accounts):
    #    translate with accuracy and dignity; do not soften, embellish, or omit.
    return (
        f"You are a translation engine for the Asia Youth Leadership Summit.\n"
        f"Translate the user's message from {source} to {target}.\n\n"
        f"Guidance:\n"
        f"- Thai has no spaces between words; segment by context.\n"
        f"- Thai verbs carry no tense; infer tense from context and render natural {target}.\n"
        f"- Use a polite, gender-neutral register. Only include a Thai politeness "
        f"particle (ครับ/ค่ะ) if one appears in the source.\n"
        f"- Some content is sensitive (human trafficking, survivor stories). "
        f"Translate accurately and with dignity; never soften or embellish.\n\n"
        f"Preferred terminology for this event (use these exact renderings):\n"
        f"{glossary}\n\n"
        f"Respond with ONLY the translated text — no quotes, no notes, no romanization."
    )


def translate(text: str, direction: str) -> str:
    """Blocking call to Claude Haiku. Returns the translated text only."""
    msg = _anthropic.messages.create(
        model=config.model,
        max_tokens=400,
        system=_system_prompt(direction),
        messages=[{"role": "user", "content": text}],
    )
    return "".join(b.text for b in msg.content if b.type == "text").strip()


# ─────────────────────────────────────────────────────────────────────────────
# 6. FastAPI app + routes
# ─────────────────────────────────────────────────────────────────────────────
from fastapi import (FastAPI, WebSocket, WebSocketDisconnect, HTTPException,
                     Header, Depends)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Summit Translate")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.allowed_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

VALID_DIRECTIONS = {"en-th", "th-en"}


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Dependency: reject requests without a valid Bearer token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    if not verify_token(authorization[len("Bearer "):]):
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@app.get("/healthz")
def healthz():
    return {"ok": True}


class AuthRequest(BaseModel):
    passphrase: str


@app.post("/auth")
def auth(req: AuthRequest):
    """Server-side passphrase gate (§5). Returns a signed token on success."""
    if not check_passphrase(req.passphrase):
        raise HTTPException(status_code=401, detail="Incorrect passphrase")
    return {"token": issue_token()}


class TranslateRequest(BaseModel):
    text: str
    direction: str  # "en-th" | "th-en"


@app.post("/translate", dependencies=[Depends(require_token)])
def translate_route(req: TranslateRequest):
    """On-demand path (§3)."""
    if req.direction not in VALID_DIRECTIONS:
        raise HTTPException(status_code=400, detail="Invalid direction")
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")
    try:
        result = translate(req.text, req.direction)
        log_usage_event(mode="on_demand", direction=req.direction, status="success")
        return {"translation": result}
    except Exception as exc:
        # §7: caller retries once silently, then surfaces the human-interpreter message.
        log_usage_event(mode="on_demand", direction=req.direction,
                        status="failure", failure_type=type(exc).__name__)
        logger.exception("translation failed")
        raise HTTPException(status_code=502, detail="Translation service unavailable")


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket, token: str = "", direction: str = "en-th"):
    """
    Live path (§3). Auth is via a ?token= query param (browsers can't set custom
    WebSocket headers). Session context stays in memory for this connection only
    and the socket auto-closes after config.session_minutes (§10).

    STT/TTS are NOT wired yet. For early testing this accepts {"type":"text"}
    messages and returns translations, so you can exercise the live loop before
    Google streaming STT/TTS is integrated.
    """
    if direction not in VALID_DIRECTIONS or not verify_token(token):
        await ws.close(code=4401)
        return

    await ws.accept()
    started = time.monotonic()
    deadline = started + config.session_minutes * 60
    status = "success"

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                await ws.send_json({"type": "session_end", "reason": "time_limit"})
                break
            try:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=remaining)
            except asyncio.TimeoutError:
                await ws.send_json({"type": "session_end", "reason": "time_limit"})
                break

            # ── Interim scaffold: text in -> translation out ───────────────────
            # TODO: replace with the real pipeline:
            #   1. receive binary audio frames from the browser mic
            #   2. stream them to Google Speech-to-Text (streaming_recognize)
            #   3. translate interim/final transcripts with translate()
            #   4. synthesize target audio with Google Text-to-Speech and stream back
            if msg.get("type") == "text" and msg.get("text"):
                translated = await asyncio.to_thread(translate, msg["text"], direction)
                await ws.send_json({"type": "translation", "text": translated})
            else:
                await ws.send_json({"type": "error", "detail": "unsupported message"})

    except WebSocketDisconnect:
        pass
    except Exception:
        status = "failure"
        logger.exception("live session error")
    finally:
        log_usage_event(mode="live", direction=direction, status=status,
                        session_duration_s=time.monotonic() - started)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Local entrypoint
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    # Cloud Run injects PORT; default to 8080 for local runs.
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")))