// config.js  ── gitignored, never committed
// ─────────────────────────────────────────────────────────────────────────────
// The frontend is served by FastAPI (StaticFiles), so location.origin IS the
// API origin on every target:
//   • Cloud Run   → https://your-service.run.app
//   • Codespaces  → https://<slug>-8000.app.github.dev   (port must be Public)
//   • Custom domain → https://translate.example.com
//
// Relative paths work everywhere — backendOrigin stays null in normal use.
// Only set it if you're running frontend and backend on *different* origins,
// which is non-standard for this architecture.
// ─────────────────────────────────────────────────────────────────────────────

window.APP_CONFIG = {
  backendOrigin: null,
  // Override example (paste your current Codespaces slug if needed):
  // backendOrigin: "https://crispy-acorn-p55gx7g55rqh7g47-8000.app.github.dev",
};

// const API_BASE_URL = ""; 
const API_BASE_URL = "https://crispy-acorn-p55gx7g55rqh7g47-8000.app.github.dev";
const WS_BASE_URL  = "wss://crispy-acorn-p55gx7g55rqh7g47-8000.app.github.dev";

// ── URL helpers ──────────────────────────────────────────────────────────────
// Read override once; falls back to same-origin (empty string = relative path).
const _backendOrigin = window.APP_CONFIG?.backendOrigin ?? "";

/** REST path → full URL or relative path, depending on config. */
function apiUrl(path) {
  return `${_backendOrigin}${path}`;
  // apiUrl("/translate") → "/translate"  (relative, same-origin)
  // apiUrl("/translate") → "https://host/translate"  (if override is set)
}

/** WS path → ws:// or wss:// URL, derived from current page protocol. */
function wsUrl(path) {
  if (_backendOrigin) {
    // If an override origin is set, swap http→ws / https→wss
    return _backendOrigin.replace(/^http/, "ws") + path;
  }
  // No override: derive from the current page (works on any host automatically)
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}${path}`;
}

// ── Usage (called from your event handlers, not at top level) ────────────────
// const ws = new WebSocket(wsUrl("/ws"));
// await fetch(apiUrl("/translate"), { method: "POST", body: ... });