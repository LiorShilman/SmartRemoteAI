from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import VERSION, Settings
from app.models.schemas import (
    KEYS_BY_KIND, LG_APPS, Action, AuditOut, ChannelSet, CommandRequest, CommandResponse, DeviceOut, DeviceUpdate,
    ErrorCode, HealthOut, IntentOut, IntentParseRequest, MeOut, NewDevice, PairConfirm, PointerEvent, ScheduleClear,
    ScheduleCreate, ScheduleOut, TokenClear, TokenCreate, TokenCreated, TokenOut,
)
from app.services.intents import build_provider
from app.services.manager import DeviceManager, ManagerError
from app.services.scheduler import Scheduler, ScheduleStore
from app.storage.db import Store
from app.storage.security import AuditStore, TokenRow, TokenStore

# Commands worth a line in the audit log. Navigation, volume and pointer events are far too frequent to keep.
AUDITED_ACTIONS = {Action.POWER_OFF, Action.POWER_ON, Action.SET_INPUT, Action.LAUNCH_APP,
                   Action.DIGITS, Action.CHANNEL_STEP, Action.CHANNEL_LAST}


def _secret_ok(given: str | None, expected: str) -> bool:
    return bool(given) and hmac.compare_digest(given.encode(), expected.encode())


@dataclass(frozen=True)
class Identity:
    kind: Literal["admin", "device"]
    name: str
    ip: str
    token_id: str | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    networks = [ipaddress.ip_network(c, strict=False) for c in settings.allowed_cidrs]  # a typo must fail loudly at start
    store = Store(settings.db_path)
    manager = DeviceManager(store, settings.use_mock_adapters, settings.cert_dir)
    schedules = ScheduleStore(*store.connection)
    scheduler = Scheduler(schedules, manager)
    tokens = TokenStore(*store.connection)
    audit = AuditStore(*store.connection)
    intents = build_provider(settings.llm_api_key, settings.llm_model)
    manager.notify = lambda event, detail: audit.add("server", "אוטומטי", event, detail)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await manager.startup()
        await scheduler.start()
        yield
        await scheduler.stop()
        await manager.shutdown()

    app = FastAPI(title="Smart Remote AI", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.settings, app.state.manager = settings, manager
    app.state.scheduler, app.state.schedules = scheduler, schedules
    app.state.tokens, app.state.audit = tokens, audit

    if settings.allowed_origins:  # explicit origins only; never "*"
        app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
                           allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])

    def err(code: ErrorCode, message: str, http: int) -> JSONResponse:
        return JSONResponse({"detail": {"code": code.value, "message": message}}, status_code=http)

    @app.exception_handler(ManagerError)
    async def _manager_error(_: Request, e: ManagerError):
        return err(e.code, e.message, e.http)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, e: RequestValidationError):
        return err(ErrorCode.INVALID_COMMAND, "הבקשה לא תקינה.", 422)

    def client_ip(request: Request) -> str:
        ip = request.client.host if request.client else "?"
        if settings.trust_proxy and ip in {"127.0.0.1", "::1"}:
            # IIS/ARR appends the real peer as the LAST X-Forwarded-For entry; earlier ones are client-supplied.
            xff = request.headers.get("x-forwarded-for", "")
            ip = xff.split(",")[-1].strip().rsplit(":", 1)[0] if xff else ip
        return ip

    def allowed_ip(ip: str) -> bool:
        if not networks:
            return True
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return addr.is_loopback or any(addr in n for n in networks)

    blocked_logged: dict[str, float] = {}

    def note_blocked(ip: str) -> None:
        now = time.monotonic()
        if now - blocked_logged.get(ip, -1e9) > 300:
            blocked_logged[ip] = now
            audit.add(ip, "—", "blocked_ip", "כתובת מחוץ לרשימת המותרות")

    @app.middleware("http")
    async def network_allowlist(request: Request, call_next):
        ip = client_ip(request)
        if not allowed_ip(ip):
            note_blocked(ip)
            return err(ErrorCode.DENIED, "הגישה מהכתובת הזו לא מורשית.", 403)
        return await call_next(request)

    failures: dict[str, deque[float]] = defaultdict(deque)  # per client IP, for brute-force throttling
    fail_logged: dict[str, float] = {}

    def verify(token: str) -> tuple[str, str, TokenRow | None] | None:
        """(kind, name, token row) for a valid secret, else None. The master token is always accepted."""
        if _secret_ok(token, settings.access_token):
            return "admin", "מנהל", None
        if (row := tokens.find(token)):
            return "device", row.name, row
        return None

    def auth(request: Request, authorization: str | None = Header(default=None)) -> Identity:
        ip = client_ip(request)
        now = time.monotonic()
        q = failures[ip]
        while q and now - q[0] > 300:
            q.popleft()
        if len(q) >= 10:
            raise ManagerError(ErrorCode.DENIED, "יותר מדי ניסיונות כושלים. נסה שוב בעוד כמה דקות.", 429)
        scheme, _, token = (authorization or "").partition(" ")
        who = verify(token) if scheme.lower() == "bearer" else None
        if who is None:
            if authorization:  # a missing header is a client that has no code yet, not a guess
                q.append(now)
                if now - fail_logged.get(ip, -1e9) > 60:  # one audit line per minute per IP, not one per guess
                    fail_logged[ip] = now
                    audit.add(ip, "—", "login_failed", "קוד גישה שגוי")
            raise ManagerError(ErrorCode.DENIED, "אימות נדרש.", 401)
        kind, name, row = who
        if row is not None:
            previous = tokens.touch(row, ip, time.time())
            if previous:
                audit.add(ip, name, "new_ip", f"{previous} ← {ip}")
        return Identity(kind=kind, name=name, ip=ip, token_id=row.id if row else None)  # type: ignore[arg-type]

    def admin(ident: Identity = Depends(auth)) -> Identity:
        if ident.kind != "admin":
            raise ManagerError(ErrorCode.DENIED, "הפעולה זמינה רק למנהל.", 403)
        return ident

    api = APIRouter(prefix="/api", dependencies=[Depends(auth)])

    @api.get("/health", response_model=HealthOut)
    async def health() -> HealthOut:
        return HealthOut(version=VERSION)

    @api.get("/me", response_model=MeOut)
    async def me(ident: Identity = Depends(auth)) -> MeOut:
        return MeOut(kind=ident.kind, name=ident.name)

    # ---- devices: reading and day-to-day control for any valid code; setup and pairing for the admin only
    @api.get("/devices", response_model=list[DeviceOut])
    async def devices() -> list[DeviceOut]:
        return manager.snapshot()

    @api.post("/devices/discover", response_model=list[DeviceOut])
    async def discover(_: Identity = Depends(admin)) -> list[DeviceOut]:
        return await manager.discover()

    @api.post("/devices", response_model=DeviceOut, status_code=201)
    async def add_device(body: NewDevice, ident: Identity = Depends(admin)) -> DeviceOut:
        out = manager.add(body.kind, body.host, body.role, body.name)
        audit.add(ident.ip, ident.name, "device_added", f"{out.name} {body.host}")
        return out

    @api.patch("/devices/{device_id}", response_model=DeviceOut)
    async def update_device(device_id: str, body: DeviceUpdate, ident: Identity = Depends(admin)) -> DeviceOut:
        out = await manager.update(device_id, body.name, body.role, body.host)
        audit.add(ident.ip, ident.name, "device_updated", f"{out.name}" + (f" · {body.host}" if body.host else ""))
        return out

    @api.delete("/devices/{device_id}", status_code=204)
    async def remove_device(device_id: str, ident: Identity = Depends(admin)) -> None:
        name = manager.name_of(device_id)
        await manager.remove(device_id)
        audit.add(ident.ip, ident.name, "device_removed", name)

    @api.post("/devices/{device_id}/pointer", status_code=204)
    async def pointer(device_id: str, body: PointerEvent) -> None:
        await manager.pointer(device_id, body.dx, body.dy, body.scroll_dy, body.click)

    @api.post("/devices/{device_id}/pair/start")
    async def pair_start(device_id: str, _: Identity = Depends(admin)) -> dict:
        await manager.pair_start(device_id)
        return {"status": "started"}

    @api.post("/devices/{device_id}/pair/confirm", response_model=DeviceOut)
    async def pair_confirm(device_id: str, body: PairConfirm, ident: Identity = Depends(admin)) -> DeviceOut:
        out = await manager.pair_confirm(device_id, body.code)
        audit.add(ident.ip, ident.name, "device_paired", out.name)
        return out

    @api.post("/devices/{device_id}/selftest")
    async def selftest(device_id: str, ident: Identity = Depends(auth)) -> dict:
        out = await manager.selftest(device_id)
        audit.add(ident.ip, ident.name, "selftest", f"{manager.name_of(device_id)}: {'תקין' if out.get('ok') else 'לא הגיב' if out.get('ok') is False else 'לא ניתן לאימות'}")
        return out

    @api.post("/devices/{device_id}/channel", response_model=DeviceOut)
    async def set_channel(device_id: str, body: ChannelSet) -> DeviceOut:
        return manager.set_channel(device_id, body.channel)

    @api.post("/devices/{device_id}/commands", response_model=CommandResponse)
    async def command(device_id: str, body: CommandRequest, ident: Identity = Depends(auth)) -> CommandResponse:
        status = await manager.send(device_id, body)
        if status == "sent" and body.action in AUDITED_ACTIONS:
            detail = ", ".join(f"{k}={v}" for k, v in body.params.items() if k in {"digits", "app", "input", "delta"})
            audit.add(ident.ip, ident.name, "command", f"{body.action.value} · {manager.name_of(device_id)}" + (f" · {detail}" if detail else ""))
        return CommandResponse(status=status, request_id=body.request_id)

    @api.get("/devices/{device_id}/diagnostics")
    async def diagnostics(device_id: str) -> dict:
        return manager.diagnostics(device_id)  # no certificates, keys or tokens

    @api.post("/intents/parse", response_model=IntentOut)
    async def parse_intent(body: IntentParseRequest) -> IntentOut:
        # Parsing never executes anything; the UI shows the preview and runs each step through /commands or /schedule.
        return await intents.parse(body.text, body.volume_target)

    @api.get("/schedule", response_model=list[ScheduleOut])
    async def list_schedule() -> list[ScheduleOut]:
        return schedules.list()

    @api.post("/schedule", response_model=ScheduleOut, status_code=201)
    async def create_schedule(body: ScheduleCreate, ident: Identity = Depends(auth)) -> ScheduleOut:
        out = schedules.add(body, time.time())
        if out is None:
            raise ManagerError(ErrorCode.DENIED, "יש יותר מדי פעולות מתוזמנות. בטל חלק מהן.", 429)
        audit.add(ident.ip, ident.name, "schedule_created", body.label or body.action.value)
        return out

    @api.post("/schedule/clear")
    async def clear_schedules(body: ScheduleClear) -> dict:
        return {"removed": schedules.delete(body.ids)}

    @api.delete("/schedule/{schedule_id}", response_model=ScheduleOut)
    async def cancel_schedule(schedule_id: str) -> ScheduleOut:
        if not schedules.set_status(schedule_id, "cancelled", only_if="pending"):
            raise ManagerError(ErrorCode.INVALID_COMMAND, "הפעולה המתוזמנת לא נמצאה או שכבר בוצעה.", 404)
        return schedules.get(schedule_id)  # type: ignore[return-value]

    # ---- access control (admin only)
    def token_out(t: TokenRow) -> TokenOut:
        return TokenOut(id=t.id, name=t.name, prefix=t.prefix, created_at=t.created_at, last_used_at=t.last_used_at,
                        last_ip=t.last_ip, revoked=t.revoked_at is not None)

    @api.get("/tokens", response_model=list[TokenOut])
    async def list_tokens(_: Identity = Depends(admin)) -> list[TokenOut]:
        return [token_out(t) for t in tokens.list()]

    @api.post("/tokens", response_model=TokenCreated, status_code=201)
    async def create_token(body: TokenCreate, ident: Identity = Depends(admin)) -> TokenCreated:
        row, secret = tokens.create(body.name, time.time())
        audit.add(ident.ip, ident.name, "token_created", row.name)
        return TokenCreated(**token_out(row).model_dump(), token=secret)

    @api.post("/tokens/clear")
    async def clear_tokens(body: TokenClear, _: Identity = Depends(admin)) -> dict:
        return {"removed": tokens.purge_revoked(body.ids)}

    @api.delete("/tokens/{token_id}", response_model=TokenOut)
    async def revoke_token(token_id: str, ident: Identity = Depends(admin)) -> TokenOut:
        if not tokens.revoke(token_id, time.time()):
            raise ManagerError(ErrorCode.INVALID_COMMAND, "הקוד לא נמצא או שכבר בוטל.", 404)
        row = tokens.get(token_id)
        audit.add(ident.ip, ident.name, "token_revoked", row.name if row else token_id)
        return token_out(row)  # type: ignore[arg-type]

    @api.get("/audit", response_model=list[AuditOut])
    async def audit_log(limit: int = Query(default=50, ge=1, le=200), _: Identity = Depends(admin)) -> list[AuditOut]:
        return [AuditOut(id=r.id, at=r.at, ip=r.ip, who=r.who, event=r.event, detail=r.detail) for r in audit.recent(limit)]

    @api.get("/capabilities")
    async def capabilities() -> dict:
        return {"intent_provider": intents.name, "actions": [a.value for a in Action],
                "keys": {k: sorted(v) for k, v in KEYS_BY_KIND.items()}, "lg_apps": sorted(LG_APPS)}

    app.include_router(api)

    @app.websocket("/ws/status")
    async def ws_status(ws: WebSocket) -> None:
        # Browsers cannot set WS headers, and tokens in URLs leak into logs: authenticate with the first message.
        await ws.accept()
        try:
            ip = ws.client.host if ws.client else "?"
            if not allowed_ip(ip if not settings.trust_proxy else (ws.headers.get("x-forwarded-for", ip).split(",")[-1].strip() or ip)):
                await ws.close(code=4403)
                return
            first = json.loads(await asyncio.wait_for(ws.receive_text(), 5))
            if verify(str(first.get("token") or "")) is None:
                await ws.close(code=4401)
                return
            last = None
            while True:
                snap = [d.model_dump() for d in manager.snapshot()]
                if snap != last:
                    await ws.send_json({"type": "devices", "devices": snap})
                    last = snap
                await asyncio.sleep(2)
        except (WebSocketDisconnect, TimeoutError, ValueError):
            await ws.close(code=4400)

    return app
