# Summit Translate

Thai ↔ English translation web app for the **Asia Youth Leadership Summit** (early December 2026). One-time disposable pilot — optimised for December and a hard **$200** budget cap, not long-term extensibility.

## Status: Round 3 — live streaming + face-to-face

The frontend talks to a live FastAPI backend (the simulation is gone). The backend serves the frontend, gates on the shared passphrase, and runs both translation paths against real services. Translation now appears **as you speak or type**, not only when you finish.

### Two tabs

- **Quick** — type a phrase (translated live as you type, debounced) **or** tap-to-talk a short utterance. A source→translation pair builds up in place and freezes when you press Enter/stop.
- **Conversation** — continuous 1:1 interpretation over a WebSocket session, with an auto-disconnect countdown (§10). Includes **face-to-face (flip) mode**: the screen splits in two and the top half rotates 180°, so the person across the table reads their language right-side up. Each side has its own mic and speaks its own language — the speaker sees their words on their side, the listener sees the translation on theirs, both updating live.

### What works end-to-end

- **Live "as you speak" (§3):** the mic streams over the WebSocket → Google streaming STT → Claude Haiku → streamed TTS back. Interim transcripts are translated on a throttle (`LIVE_PARTIAL_INTERVAL_MS`, see below) so words appear mid-sentence without a Haiku call per syllable; the final sentence is always translated + spoken.
- **Live "as you type" (§3):** the Quick text box calls `POST /translate` on a short debounce, showing a live translation that finalizes on Enter.
- **Turn-aware WebSocket:** each speaking turn carries its own direction (`start_turn`/`end_turn`), which is what lets flip mode alternate languages per side within one session.
- **Server-side passphrase gate (§5):** `POST /auth` issues a short-lived HMAC-signed token; every call is verified against it.
- **Content-free usage logging (§8):** `log_usage_event()` cannot accept translation text or audio by construction — only metadata. Quick-tab voice streams over the same socket but is still logged as `on_demand`, not `live`.
- **Graceful-failure path (§7):** one silent retry, then the "seek the human interpreter" message (toggle "Simulate API failure" in Settings).
- Language direction toggle (EN→TH / TH→EN), light/dark mode.

**Fallback for local dogfooding without GCP:** if Google credentials aren't set, the WebSocket still accepts `{"type":"text"}` messages and returns translations, so both tabs' text paths are exercisable with only an Anthropic key. (Voice needs GCP.)

### Tuning the live cadence (`LIVE_PARTIAL_INTERVAL_MS`)

Live "as you speak" translates partial sentences, which costs more Haiku calls than translating only finished ones. This knob (milliseconds, default `900`) caps how often a partial is translated per turn:

- **Lower** (e.g. `500`) → snappier live feel, more API calls.
- **Higher** (e.g. `2000`) → cheaper, translations lag the speaker a little more.
- **Very high** → effectively translate only finished sentences (cheapest; closest to the original spec's request/response shape).

It's a plain env var — tune it against the $200 cap (§10) without touching code.

## Run it locally

```bash
cp .env.example backend/.env      # then fill in ANTHROPIC_API_KEY + APP_* values
cd backend
pip install -r requirements.txt
python main.py                    # serves API + frontend at http://localhost:8080
```

Voice paths additionally need `GOOGLE_APPLICATION_CREDENTIALS` pointing at a service-account key with Speech-to-Text and Text-to-Speech access.

## Confirmed stack (target build)

| Concern            | Choice                                                        |
|--------------------|---------------------------------------------------------------|
| Compute            | GCP Cloud Run (serverless, WebSockets, scales to zero)        |
| Backend            | FastAPI                                                       |
| Translation        | Claude Haiku (both paths — not Sonnet)                        |
| Speech             | Google streaming STT + TTS (WaveNet/Standard only)           |
| Secrets            | GCP Secret Manager (Anthropic key + GCP creds)               |
| Glossary           | Small static list injected into the prompt — no database     |
| Auth               | Single shared event passphrase — no accounts                 |
| Persistence        | None. Usage metadata only; translation content never logged (§8) |

## Repo structure

```
summit-translate/
├── README.md
├── .gitignore
├── .env.example          # config contract (placeholders only)
├── Dockerfile            # container for Cloud Run (ships backend + frontend)
├── backend/
│   ├── main.py           # FastAPI: /auth /translate /stt /tts /ws/live + serves frontend
│   ├── speech.py         # Google STT (clip + streaming) and TTS
│   └── requirements.txt
└── frontend/
    ├── index.html        # UI markup
    ├── styles.css
    ├── config.js         # same-origin API/WS URL helpers
    └── app.js            # tabs, live-as-you-type, turn-based streaming, flip mode, TTS
```

## Deploying

- **Real pilot:** Cloud Run on GCP (§4) — required for the WebSocket live path, Google STT/TTS, and Secret Manager. Build the image from the `Dockerfile` (it bundles the frontend and serves it from the same service), then deploy to Cloud Run with the env vars/secrets from `.env.example` wired up.

## Budget guardrails (§10)

Hard cap **$200** total. Claude Haiku only; live sessions auto-disconnect after ~12 min; TTS on free-tier voices; live partial-translation throttled by `LIVE_PARTIAL_INTERVAL_MS` (raise it to spend less); spend alerts at $150 (warning) and $180 (hard stop) on both the Anthropic console and GCP billing.