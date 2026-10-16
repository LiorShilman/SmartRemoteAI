# Architecture (Steps A+B)

Browser (React/Vite PWA) → `/api`, `/ws` → FastAPI backend (Step C) → HOT (Android TV Remote v2) / LG (webOS SSAP).

Frontend layers:
- `services/api.ts` – typed REST client; maps failures to error codes (`BACKEND_OFFLINE`, `NOT_PAIRED`, …).
- `hooks/useSend.ts` – the only path that sends commands. Expands `digits` into timed key presses, stops a sequence on first failure, logs every outcome.
- `demo/demoEngine.ts` – synthetic devices and `simulated` results, used only in Demo mode.
- `app/store.ts` – settings, favorites, user-verified capabilities (live caps persisted, demo caps session-only).
- `services/intentParser.ts` – deterministic Hebrew grammar; separate from speech-to-text.

Command outcome vocabulary: `simulated` (demo), `sent` (backend transmitted), or an error code. No state means "device reacted".
