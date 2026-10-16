# Backend (Step C: API, auth, mock adapters)

Python 3.11+ (venv built with 3.13), FastAPI, Uvicorn, SQLite. Real HOT/LG adapters arrive in Steps D/E;
until then real devices report `unpaired` and commands fail with `NOT_PAIRED`/`UNSUPPORTED` (never fake success).

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python run.py            # http://127.0.0.1:8787
.\.venv\Scripts\python -m pytest -q
```

- `ACCESS_TOKEN` in `.env` (or env). If unset, a random one is printed at startup. Enter it in the app: Settings → Live mode.
- `USE_MOCK_ADAPTERS=true` gives in-memory fake devices for testing (HOT pair code `123456`). Not hardware.
- Listens on 127.0.0.1 by default. Set `ALLOWED_ORIGINS` for CORS (no wildcard).
- Commands are allowlisted per device kind, deduplicated by `request_id`, queued per device, rate-limited, 8s timeout.
- `/ws/status` authenticates with a first message `{"token": "..."}`.
