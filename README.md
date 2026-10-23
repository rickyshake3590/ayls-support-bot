# Asia Youth Leadership Summit 2026 - Telegram Bot

Answers participant questions about the Asia Youth Leadership Summit 2026
(Chiang Mai, Thailand, 4-6 December 2026) from official summit content only,
and hands off to a human organiser on request.

Status: Phase 2 (scaffold). Ingestion, retrieval, LLM, and Telegram handling
are added in later phases.

## Local setup

```
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
```

Tests and imports need no secrets. `bot/config.py` reads environment variables
lazily; secrets (`TELEGRAM_TOKEN`, `OPENROUTER_API_KEY`, `ORGANISER_GROUP_ID`)
are only required when the bot runs.
