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

## Retrieval and answers

- Content chunks come from the site repo's `content/` folder (`python -m bot.ingest`).
- Each question retrieves the top `TOP_K` chunks (default 8) whose cosine distance is at most `MAX_DIST`.
- The LLM answers only from those chunks and replies `NO_ANSWER` when they don't cover the question.
- If the LLM is unavailable, the best chunk is returned verbatim (extractive mode).

### Distance cutoff (`MAX_DIST`, default 0.39)

Measured on `tests/eval_questions.yaml` (37 positives, 10 negatives), with the index built from site content on 23 Oct 2026:

- Every positive that retrieves its expected text scores at most 0.379.
- The nearest off-topic question scores at least 0.395.

0.39 sits between these two. The margin is narrow (about 0.016), so re-run `pytest tests/test_retrieval.py` after any content or model change and retune if a question crosses over.

### Retrieval depth

`TOP_K` is 8. At 4, two positives ("Who organises the summit?", "Can I stay on after the summit?") ranked 5th and 6th, inside the distance cutoff but outside the top 4. `MAX_DIST` still gates off-topic questions, so the larger `TOP_K` adds no false positives.

### Known gap: extractive mode

When the LLM is down, extractive mode returns the single best chunk. For "Who organises the summit?" that chunk is still the wrap-up schedule item, not the organiser line. The human-assistance button is shown with it. The LLM path is not affected.

### Running the evals

- `pytest`: retrieval and LLM fallback tests. Needs a built index. Retrieval tests skip if there is no index. No network calls.
- `SITE_CONTENT_DIR=<path>/content pytest tests/test_loader.py`: loads the real site content.
- `python -m scripts.eval_answers`: runs the questions against the live model. Needs `OPENROUTER_API_KEY`. Not run in CI.
