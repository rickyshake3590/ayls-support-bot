import os

CONTENT_DIR = os.getenv("CONTENT_DIR", "content")
INDEX_DIR = os.getenv("INDEX_DIR", "index")
DB_PATH = os.getenv("DB_PATH", "data/tickets.db")
BASE_URL = "https://youthsummit.salvationarmy.asia"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
MAX_DIST = float(os.getenv("MAX_DIST", "0.39"))   # cosine distance cutoff, tuned in Phase 4
TOP_K = int(os.getenv("TOP_K", "8"))

LLM_MODEL = os.getenv("LLM_MODEL", "google/gemma-4-26b-a4b-it:free")
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "25"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "3"))
USER_MSGS_PER_MIN = int(os.getenv("USER_MSGS_PER_MIN", "8"))
LLM_REASONING_OFF = os.getenv("LLM_REASONING_OFF", "1") == "1"
QUERY_TRANSLATE = os.getenv("QUERY_TRANSLATE", "0") == "1"
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
CACHE_MAX_ENTRIES = int(os.getenv("CACHE_MAX_ENTRIES", "500"))

def require(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing env var {name}")
    return v

def organiser_handles() -> list[str]:
    """Telegram handles participants can message, from ORGANISER_HANDLES=@alice,@bob."""
    handles = [h.strip() for h in require("ORGANISER_HANDLES").split(",") if h.strip()]
    if not handles:
        raise RuntimeError("ORGANISER_HANDLES lists no handles")
    return handles
