# Asia Youth Leadership Summit 2026 - Telegram Bot

Answers participant questions about the Asia Youth Leadership Summit 2026
(Chiang Mai, Thailand, 4-6 December 2026) from official summit content only,
and hands off to a human organiser on request.

Status: Phase 5 code complete (Telegram Q&A and handoff by organiser handles). The live
Telegram test below is pending.

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

## Event-day model switch (4-6 December 2026)

The bot runs on the free model by default. The free route is rate limited and its upstream provider is sometimes congested, so on event days the bot switches to the paid variant of the same model.

| | Model ID | Price |
|---|---|---|
| Default | `google/gemma-4-26b-a4b-it:free` | free, shared rate limits |
| Event days | `google/gemma-4-26b-a4b-it` | $0.09 per million input tokens, $0.30 per million output tokens |

At the paid rate, expect well under a few US dollars for the three event days. This is an estimate from the per-token prices, not a measured cost. Check the OpenRouter usage page after day one.

Switch on the morning of 4 December, once the Fly app exists (Phase 6):

```
fly secrets set LLM_MODEL=google/gemma-4-26b-a4b-it
```

Switch back after the summit ends on 6 December:

```
fly secrets unset LLM_MODEL
```

Fly restarts the machine on each change. Check the startup log for `model=google/gemma-4-26b-a4b-it` after the switch. Do not use the `:free` suffix on event days.

## Telegram setup (one time)

1. In Telegram, message @BotFather, send `/newbot`, and save the token. Set the commands `start` and `human`.
2. Decide which organisers participants can message. Each needs a Telegram username.
3. Put the settings in `.env`, or pass them as environment variables. Never commit them:
   ```
   TELEGRAM_TOKEN=...
   ORGANISER_HANDLES=@alice,@bob
   ```

The bot won't start without `ORGANISER_HANDLES`. Run it with `python -m bot.main`. Only one instance may poll a token at a time.

Handoff is direct: the bot lists the handles, and the participant messages an organiser on Telegram. The bot keeps no handoff records.

## Manual Telegram test

Work through this list in a private chat with the bot, after the index is built:

1. Ask three summit questions (for example "What is the registration fee?"). Each answer shows a `Source:` link and the human button.
2. Ask an off-topic question ("Best pizza in Rome?"). The reply lists the organiser handles.
3. Tap the human button. The reply lists the organiser handles.
4. Ask "I need a refund". The reply gives the handles and the emergency line.
5. Ask another summit question. The bot answers again.
