# Summit Translate

Thai ↔ English translation web app for the **Asia Youth Leadership Summit** (early December 2026). One-time disposable pilot — optimised for December and a hard **$200** budget cap, not long-term extensibility.

## Status: Round 1 — frontend draft

This repo currently contains only the **frontend UI draft**. Speech-to-text and translation are **simulated** (fixed timers, five hardcoded demo phrases) — there is no backend and no API calls yet. It exists to validate the layout and interaction flow on real phones before wiring live services.

What the draft demonstrates:
- Press-to-talk live-interpretation flow: Listening → Heard → Translating → Translation
- Language direction toggle (EN→TH / TH→EN) with romanisation for Thai output
- Shared-passphrase gate (§5) — **demo-only, client-side**; the real gate must validate server-side
- Graceful-failure path (§7): silent retry once, then a visible "seek the human interpreter" message (toggle "Simulate API failure" in Settings)
- Light / dark mode
- Live-session countdown reflecting the auto-disconnect cap (§10)

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
└── frontend/
    └── index.html        # round 1 UI draft (simulated)
```

Planned additions once the backend is built:
```
├── backend/              # FastAPI service (on-demand + live WebSocket paths)
│   ├── main.py
│   └── requirements.txt
└── Dockerfile            # container for Cloud Run
```

## Preview the draft locally

It's a single static file — open it directly, or serve it:

```bash
cd frontend
python3 -m http.server 8000
# visit http://localhost:8000
```

## Deploying

- **To share the draft with testers now:** any static host (GitHub Pages, Netlify, Vercel) serves `frontend/index.html` for free. No GCP needed while STT/translation are still simulated.
- **Real pilot:** Cloud Run on GCP (§4) — required for the WebSocket live path, Google STT/TTS, and Secret Manager. Containerise once the FastAPI backend exists.

## Budget guardrails (§10)

Hard cap **$200** total. Claude Haiku only; live sessions auto-disconnect after ~12 min; TTS on free-tier voices; spend alerts at $150 (warning) and $180 (hard stop) on both the Anthropic console and GCP billing.