from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import VERSION, Settings
from app.models.schemas import CycleConfig, ProfileCreate, ProfileName, EqBand, EqOut, EqWrite, LabBass, LabBool, LabBrightness, LabObservation, LabRgb, SpeakerBalance, SpeakerBass, SpeakerBluetooth, SpeakerStepRequest, SpeakerUnpair, SpeakerSources, SpeakerStandby, SpeakerStandbySet, SpeakerBrightness, SpeakerLoudness, SpeakerMute, SpeakerRgb, check_host
from app.models.schemas import (
    KEYS_BY_KIND, LG_APPS, Action, AuditOut, ChannelSet, CommandRequest, CommandResponse, DeviceOut, DeviceUpdate,
    ErrorCode, HealthOut, IntentOut, IntentParseRequest, MeOut, NewDevice, PairConfirm, PointerEvent, ScheduleClear,
    ScheduleCreate, ScheduleOut, SpeakerConfig, SpeakerLight, SpeakerState, SpeakerTreble, SpeakerVolume, TimeDecide, TimeRequestCreate, TimeRequestOut, TokenClear, TokenCreate, TokenCreated, TokenOut,
    TokenPolicy, UsageDay, UsageOut,
)
from app.services.intents import build_provider
from app.services.policy import deny_reason, over_limit, remaining_min, schedule_denied, window_open
from app.services.manager import DeviceManager, ManagerError
from app.services.scheduler import Scheduler, ScheduleStore
from app.services.colorcycle import ColorCycle
from app.services.profiles import ProfileService, ProfileStore
from app.services.speaker_voice import run_step as run_speaker_step
from app.services.zeppelin import LAB as LAB_CONTROLS, SpeakerError, ZeppelinClient
from app.storage.db import Store
from app.storage.security import AuditStore, TimeStore, TokenRow, TokenStore, UsageStore

# Commands worth a line in the audit log. Navigation, volume and pointer events are far too frequent to keep.
AUDITED_ACTIONS = {Action.POWER_OFF, Action.POWER_ON, Action.SET_INPUT, Action.LAUNCH_APP, Action.SEARCH,
                   Action.DIGITS, Action.CHANNEL_STEP, Action.CHANNEL_LAST}


def _secret_ok(given: str | None, expected: str) -> bool:
    return bool(given) and hmac.compare_digest(given.encode(), expected.encode())


@dataclass(frozen=True)
class Identity:
    kind: Literal["admin", "device"]
    name: str
    ip: str
    token_id: str | None = None
    policy: dict | None = None  # kids mode; None = unrestricted


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    networks = [ipaddress.ip_network(c, strict=False) for c in settings.allowed_cidrs]  # a typo must fail loudly at start
    store = Store(settings.db_path)
    manager = DeviceManager(store, settings.use_mock_adapters, settings.cert_dir)
    schedules = ScheduleStore(*store.connection)
    scheduler = Scheduler(schedules, manager)
    tokens = TokenStore(*store.connection)
    audit = AuditStore(*store.connection)
    usage = UsageStore(*store.connection)
    times = TimeStore(*store.connection)
    manager.usage = usage
    intents = build_provider(settings.llm_api_key, settings.llm_model)
    manager.notify = lambda event, detail: audit.add("server", "אוטומטי", event, detail)
    speaker_host = store.get_state("speaker", "host") or check_host(settings.zeppelin_host)  # saved by the admin wins; a bad .env value fails at start

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await manager.startup()
        await scheduler.start()
        yield
        await scheduler.stop()
        await manager.shutdown()
        await app.state.cycle.shutdown()  # stop and clear the colour task before the speaker client closes
        await app.state.speaker.aclose()

    app = FastAPI(title="Smart Remote AI", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.settings, app.state.manager = settings, manager
    app.state.scheduler, app.state.schedules = scheduler, schedules
    app.state.tokens, app.state.audit = tokens, audit
    app.state.usage, app.state.times = usage, times
    app.state.clock = datetime.now  # tests replace it to control the time of day
    app.state.speaker = ZeppelinClient(speaker_host)  # tests replace it with one on a mock transport
    # One colour cycle per speaker. It is never started here: only an explicit request starts it.
    app.state.cycle = ColorCycle(lambda: app.state.speaker, store, on_event=lambda msg: audit.add("server", "אוטומטי", "speaker_cycle", msg))
    # Personal profiles: never loaded automatically. While one loads, every other speaker write is refused.
    app.state.profiles = ProfileService(lambda: app.state.speaker, app.state.cycle, store, ProfileStore(*store.connection))

    async def speaker_step(op: str, params: dict) -> str:
        """One step of the closed voice vocabulary, on whatever speaker is current. Read back inside; raises on failure."""
        return await run_speaker_step(app.state.speaker, app.state.cycle, app.state.profiles, op, params)

    async def scheduled_speaker_step(op: str, params: dict) -> None:
        audit.add("server", "אוטומטי", "speaker", f"מתוזמן: {await speaker_step(op, params)}")

    scheduler.speaker_runner = scheduled_speaker_step

    if settings.allowed_origins:  # explicit origins only; never "*"
        app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
                           allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])

    def err(code: ErrorCode, message: str, http: int) -> JSONResponse:
        return JSONResponse({"detail": {"code": code.value, "message": message}}, status_code=http)

    @app.exception_handler(ManagerError)
    async def _manager_error(_: Request, e: ManagerError):
        return err(e.code, e.message, e.http)

    @app.exception_handler(SpeakerError)
    async def _speaker_error(_: Request, e: SpeakerError):
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
        return Identity(kind=kind, name=name, ip=ip, token_id=row.id if row else None, policy=row.policy if row else None)  # type: ignore[arg-type]

    def admin(ident: Identity = Depends(auth)) -> Identity:
        if ident.kind != "admin":
            raise ManagerError(ErrorCode.DENIED, "הפעולה זמינה רק למנהל.", 403)
        return ident

    denied_logged: dict[tuple[str, str], float] = {}

    def kids_state(ident: Identity) -> dict:
        """Today's numbers for a restricted code: minutes used, extra minutes granted, window and limit."""
        now = app.state.clock()
        day = now.strftime("%Y-%m-%d")
        extra = times.extra_minutes(ident.token_id, day) if ident.token_id else 0
        used = usage.total_seconds(day) / 60
        p = ident.policy or {}
        return {"now": now, "day": day, "extra": extra, "used": used,
                "open": window_open(p, now, extra) if p else None, "over": over_limit(p, used, extra) if p else False}

    def deny(ident: Identity, reason: str) -> None:
        key = (ident.token_id or "", reason)
        t = time.monotonic()
        if t - denied_logged.get(key, -1e9) > 60:  # one audit line per minute per reason
            denied_logged[key] = t
            audit.add(ident.ip, ident.name, "policy_denied", reason)
        raise ManagerError(ErrorCode.DENIED, reason, 403)

    def enforce(ident: Identity, action: Action, params: dict) -> None:
        """Kids mode: the server decides, whatever the UI shows. The admin code is never restricted."""
        if not ident.policy:
            return
        k = kids_state(ident)
        if (reason := deny_reason(ident.policy, action, params, k["now"], k["used"], k["extra"])):
            deny(ident, reason)

    def enforce_schedule(ident: Identity, action: Action | None = None, params: dict | None = None, delay_s: int = 0) -> None:
        if not ident.policy:
            return
        if (reason := schedule_denied(ident.policy)):
            deny(ident, reason)
        if action is not None:  # the action must be allowed at the moment it will run, too
            run_at = app.state.clock() + timedelta(seconds=delay_s)
            if (reason := deny_reason(ident.policy, action, params or {}, run_at, 0, 0)):
                deny(ident, reason)

    api = APIRouter(prefix="/api", dependencies=[Depends(auth)])

    @api.get("/health", response_model=HealthOut)
    async def health() -> HealthOut:
        return HealthOut(version=VERSION)

    @api.get("/me", response_model=MeOut)
    async def me(ident: Identity = Depends(auth)) -> MeOut:
        if ident.kind == "admin":
            return MeOut(kind="admin", name=ident.name, pending_requests=times.pending_count())
        if not ident.policy:
            return MeOut(kind="device", name=ident.name)
        k = kids_state(ident)
        req = times.latest_for(ident.token_id) if ident.token_id else None
        fresh = req is not None and datetime.fromtimestamp(req.created_at).strftime("%Y-%m-%d") == k["day"]
        return MeOut(kind="device", name=ident.name, policy=ident.policy, used_min=int(k["used"]),
                     remaining_min=remaining_min(ident.policy, k["used"], k["extra"]), extra_min=k["extra"],
                     window_open=k["open"], request_status=req.status if fresh and req else None)

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
    async def pointer(device_id: str, body: PointerEvent, ident: Identity = Depends(auth)) -> None:
        enforce(ident, Action.KEY_PRESS, {})  # the pointer is navigation: subject to hours and the daily limit
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
        enforce(ident, body.action, body.params)
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
        profiles = [(p["id"], p["name"]) for p in app.state.profiles.profiles.list()]  # names only; "פרופיל ערב"
        return await intents.parse(body.text, body.volume_target, profiles)

    @api.get("/schedule", response_model=list[ScheduleOut])
    async def list_schedule() -> list[ScheduleOut]:
        return schedules.list()

    @api.post("/schedule", response_model=ScheduleOut, status_code=201)
    async def create_schedule(body: ScheduleCreate, ident: Identity = Depends(auth)) -> ScheduleOut:
        if body.target == "speaker":
            if ident.policy:  # kids-mode codes may not change the speaker, now or later
                deny(ident, "אין הרשאה לשנות את הרמקול בקוד הזה.")
            enforce_schedule(ident)
        else:
            enforce_schedule(ident, body.action, body.params, body.delay_seconds)
        out = schedules.add(body, time.time())
        if out is None:
            raise ManagerError(ErrorCode.DENIED, "יש יותר מדי פעולות מתוזמנות. בטל חלק מהן.", 429)
        audit.add(ident.ip, ident.name, "schedule_created", body.label or body.action.value)
        return out

    @api.post("/schedule/clear")
    async def clear_schedules(body: ScheduleClear, ident: Identity = Depends(auth)) -> dict:
        enforce_schedule(ident)
        return {"removed": schedules.delete(body.ids)}

    @api.delete("/schedule/{schedule_id}", response_model=ScheduleOut)
    async def cancel_schedule(schedule_id: str, ident: Identity = Depends(auth)) -> ScheduleOut:
        enforce_schedule(ident)
        if not schedules.set_status(schedule_id, "cancelled", only_if="pending"):
            raise ManagerError(ErrorCode.INVALID_COMMAND, "הפעולה המתוזמנת לא נמצאה או שכבר בוצעה.", 404)
        return schedules.get(schedule_id)  # type: ignore[return-value]

    # ---- access control (admin only)
    def token_out(t: TokenRow) -> TokenOut:
        return TokenOut(id=t.id, name=t.name, prefix=t.prefix, created_at=t.created_at, last_used_at=t.last_used_at,
                        last_ip=t.last_ip, revoked=t.revoked_at is not None, policy=t.policy)

    @api.get("/tokens", response_model=list[TokenOut])
    async def list_tokens(_: Identity = Depends(admin)) -> list[TokenOut]:
        return [token_out(t) for t in tokens.list()]

    @api.post("/tokens", response_model=TokenCreated, status_code=201)
    async def create_token(body: TokenCreate, ident: Identity = Depends(admin)) -> TokenCreated:
        row, secret = tokens.create(body.name, time.time(), body.policy.model_dump() if body.policy else None)
        audit.add(ident.ip, ident.name, "token_created", row.name + (" · מצב ילדים" if body.policy else ""))
        return TokenCreated(**token_out(row).model_dump(), token=secret)

    @api.patch("/tokens/{token_id}", response_model=TokenOut)
    async def set_token_policy(token_id: str, body: TokenPolicy, ident: Identity = Depends(admin)) -> TokenOut:
        if not tokens.set_policy(token_id, body.policy.model_dump() if body.policy else None):
            raise ManagerError(ErrorCode.INVALID_COMMAND, "הקוד לא נמצא או שכבר בוטל.", 404)
        row = tokens.get(token_id)
        audit.add(ident.ip, ident.name, "token_policy", f"{row.name}: " + ("מצב ילדים עודכן" if body.policy else "ההגבלות הוסרו"))  # type: ignore[union-attr]
        return token_out(row)  # type: ignore[arg-type]

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

    # ---- kids: ask for more time; parents decide
    def req_out(r) -> TimeRequestOut:
        return TimeRequestOut(id=r.id, token_id=r.token_id, token_name=r.token_name, minutes=r.minutes, status=r.status,
                              created_at=r.created_at, decided_at=r.decided_at, granted_minutes=r.granted_minutes)

    @api.post("/requests", response_model=TimeRequestOut, status_code=201)
    async def ask_for_time(body: TimeRequestCreate, ident: Identity = Depends(auth)) -> TimeRequestOut:
        if ident.kind != "device" or not ident.policy or not ident.token_id:
            raise ManagerError(ErrorCode.INVALID_COMMAND, "בקשת זמן רלוונטית רק לקוד במצב ילדים.", 422)
        # The app clock, like /me that compares this timestamp to "today" (the same as time.time() in production)
        r = times.create(ident.token_id, ident.name, body.minutes, app.state.clock().timestamp())
        if r is None:
            raise ManagerError(ErrorCode.DENIED, "כבר יש כמה בקשות שממתינות לאישור.", 429)
        audit.add(ident.ip, ident.name, "time_requested", f"{body.minutes} דקות")
        return req_out(r)

    @api.get("/requests", response_model=list[TimeRequestOut])
    async def list_requests(_: Identity = Depends(admin)) -> list[TimeRequestOut]:
        return [req_out(r) for r in times.list()]

    @api.post("/requests/{request_id}/decide", response_model=TimeRequestOut)
    async def decide_request(request_id: str, body: TimeDecide, ident: Identity = Depends(admin)) -> TimeRequestOut:
        r0 = times.get(request_id)
        if r0 is None or r0.status != "pending":
            raise ManagerError(ErrorCode.INVALID_COMMAND, "הבקשה לא נמצאה או שכבר טופלה.", 404)
        minutes = body.minutes or r0.minutes
        r = times.decide(request_id, body.approve, minutes, app.state.clock().strftime("%Y-%m-%d"), time.time())
        audit.add(ident.ip, ident.name, "time_granted" if body.approve else "time_denied", f"{r0.token_name}: {minutes if body.approve else 0} דקות")
        return req_out(r)  # type: ignore[arg-type]

    @api.get("/usage", response_model=UsageOut)
    async def usage_report(days: int = Query(default=7, ge=1, le=30), _: Identity = Depends(admin)) -> UsageOut:
        today = app.state.clock().date()
        data = usage.by_day((today - timedelta(days=days - 1)).strftime("%Y-%m-%d"))
        out = []
        for i in range(days - 1, -1, -1):  # always return every day, oldest first, so the chart has no gaps
            d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            e = data.get(d, {"total": 0, "apps": {}})
            out.append(UsageDay(day=d, total_min=round(e["total"] / 60), apps={a: round(s / 60) for a, s in e["apps"].items() if s >= 30}))
        return UsageOut(today_min=out[-1].total_min, days=out)

    @api.get("/capabilities")
    async def capabilities() -> dict:
        return {"intent_provider": intents.name, "actions": [a.value for a in Action],
                "keys": {k: sorted(v) for k, v in KEYS_BY_KIND.items()}, "lg_apps": sorted(LG_APPS)}

    # ---- B&W Zeppelin speaker. Only the verified controls below exist; there is no generic read/write of a path.
    def not_loading() -> None:
        if app.state.profiles.busy:  # a profile is being applied: nothing may compete with its writes
            raise ManagerError(ErrorCode.DENIED, "טעינת פרופיל בתהליך. נסה שוב בעוד רגע.", 409)

    def speaker_writer(ident: Identity = Depends(auth)) -> Identity:
        if ident.policy:  # kids-mode codes control the screens they were given, not the speaker
            deny(ident, "אין הרשאה לשנות את הרמקול בקוד הזה.")
        not_loading()
        return ident

    @api.get("/speaker", response_model=SpeakerState)
    async def speaker_state() -> SpeakerState:
        return SpeakerState(**await app.state.speaker.state())  # read only: never writes anything

    @api.post("/speaker/volume", response_model=SpeakerState)
    async def speaker_volume(body: SpeakerVolume, _: Identity = Depends(speaker_writer)) -> SpeakerState:
        await app.state.speaker.write("volume", body.value)
        return SpeakerState(**await app.state.speaker.state())

    @api.post("/speaker/treble", response_model=SpeakerState)
    async def speaker_treble(body: SpeakerTreble, ident: Identity = Depends(speaker_writer)) -> SpeakerState:
        await app.state.speaker.write("treble", float(body.value))
        audit.add(ident.ip, ident.name, "speaker", f"גבוהים {body.value:g}")
        return SpeakerState(**await app.state.speaker.state())

    @api.post("/speaker/light", response_model=SpeakerState)
    async def speaker_light(body: SpeakerLight, ident: Identity = Depends(speaker_writer)) -> SpeakerState:
        if not body.enabled:
            await app.state.cycle.stop_if_running("התאורה כובתה")
        await app.state.speaker.write("light", body.enabled)
        audit.add(ident.ip, ident.name, "speaker", "תאורה " + ("הודלקה" if body.enabled else "כובתה"))
        return SpeakerState(**await app.state.speaker.state())

    @api.post("/speaker/bass", response_model=SpeakerState)
    async def speaker_bass(body: SpeakerBass, ident: Identity = Depends(speaker_writer)) -> SpeakerState:
        await app.state.speaker.write("bass", float(body.value))
        audit.add(ident.ip, ident.name, "speaker", f"באס {body.value:g}")
        return SpeakerState(**await app.state.speaker.state())

    @api.post("/speaker/brightness", response_model=SpeakerState)
    async def speaker_brightness(body: SpeakerBrightness, _: Identity = Depends(speaker_writer)) -> SpeakerState:
        await app.state.speaker.write("brightness", body.value)  # not audited: a slider, like volume
        return SpeakerState(**await app.state.speaker.state())

    @api.post("/speaker/mute", response_model=SpeakerState)
    async def speaker_mute(body: SpeakerMute, ident: Identity = Depends(speaker_writer)) -> SpeakerState:
        await app.state.speaker.write("mute", body.enabled)  # read back and compared inside write()
        audit.add(ident.ip, ident.name, "speaker", "השתקה " + ("הופעלה" if body.enabled else "בוטלה"))
        return SpeakerState(**await app.state.speaker.state())

    @api.post("/speaker/loudness", response_model=SpeakerState)
    async def speaker_loudness(body: SpeakerLoudness, ident: Identity = Depends(speaker_writer)) -> SpeakerState:
        await app.state.speaker.write("loudness", body.enabled)  # read back and compared inside write()
        audit.add(ident.ip, ident.name, "speaker", "Loudness " + ("הופעל" if body.enabled else "כובה"))
        return SpeakerState(**await app.state.speaker.state())

    @api.post("/speaker/step", response_model=SpeakerState)
    async def speaker_voice_step(body: SpeakerStepRequest, ident: Identity = Depends(speaker_writer)) -> SpeakerState:
        """A voice-command step: a closed list of ops over the verified controls (no paths). Success = read back."""
        done = await speaker_step(body.op.value, body.params)
        audit.add(ident.ip, ident.name, "speaker", f"קול: {done}")
        return SpeakerState(**await app.state.speaker.state())

    @api.get("/speaker/bluetooth", response_model=SpeakerBluetooth)
    async def speaker_bluetooth() -> SpeakerBluetooth:
        return SpeakerBluetooth(**await app.state.speaker.bluetooth())  # read only

    @api.post("/speaker/bluetooth/pairing", response_model=SpeakerBluetooth)
    async def speaker_pairing(ident: Identity = Depends(speaker_writer)) -> SpeakerBluetooth:
        """Open Bluetooth pairing (one fixed, verified action). Nothing is sent if the speaker is already visible."""
        out = await app.state.speaker.open_pairing()  # success only when the speaker reports discoverable=true
        if out["sent"]:
            audit.add(ident.ip, ident.name, "speaker", "מצב צימוד Bluetooth נפתח")
        return SpeakerBluetooth(**out)

    @api.post("/speaker/bluetooth/unpair", response_model=SpeakerBluetooth)
    async def speaker_unpair(body: SpeakerUnpair, ident: Identity = Depends(speaker_writer)) -> SpeakerBluetooth:
        """Unpair one paired device (opaque id from GET /speaker/bluetooth) through the speaker's own Unpair action;
        success only once the speaker no longer lists it as paired."""
        out = await app.state.speaker.unpair(body.id)
        audit.add(ident.ip, ident.name, "speaker", f"בוטל צימוד Bluetooth: {out['unpaired']}")
        return SpeakerBluetooth(**out)

    @api.get("/speaker/standby", response_model=SpeakerStandby)
    async def speaker_standby() -> SpeakerStandby:
        return SpeakerStandby(**await app.state.speaker.standby())  # read only

    @api.post("/speaker/standby", response_model=SpeakerStandby)
    async def speaker_standby_set(body: SpeakerStandbySet, ident: Identity = Depends(speaker_writer)) -> SpeakerStandby:
        out = await app.state.speaker.write_standby(body.seconds)  # only an option the speaker lists; read back
        label = next((o["title"] for o in out["options"] if o["seconds"] == out["seconds"]), f"{out['seconds']} שניות")
        audit.add(ident.ip, ident.name, "speaker", f"כיבוי אוטומטי: {label}")
        return SpeakerStandby(**out)

    @api.get("/speaker/sources", response_model=SpeakerSources)
    async def speaker_sources() -> SpeakerSources:
        return SpeakerSources(sources=await app.state.speaker.sources())  # read only: switching is not verified

    @api.post("/speaker/balance", response_model=SpeakerState)
    async def speaker_balance(body: SpeakerBalance, ident: Identity = Depends(speaker_writer)) -> SpeakerState:
        await app.state.speaker.write("balance", float(body.value))
        audit.add(ident.ip, ident.name, "speaker", f"איזון {body.value:g}")
        return SpeakerState(**await app.state.speaker.state())

    @api.post("/speaker/rgb", response_model=SpeakerState)
    async def speaker_rgb(body: SpeakerRgb, ident: Identity = Depends(speaker_writer)) -> SpeakerState:
        await app.state.cycle.stop_if_running("נבחר צבע ידני")
        await app.state.speaker.write("rgb", body.model_dump())
        audit.add(ident.ip, ident.name, "speaker", f"צבע תאורה {body.red},{body.green},{body.blue}")
        return SpeakerState(**await app.state.speaker.state())

    async def eq_out() -> EqOut:
        bands, enabled, errors = None, None, {}
        try:
            bands = [EqBand(**{k: b[k] for k in ("band", "min", "max", "step", "value")}) for b in await app.state.speaker.read_eq()]
        except SpeakerError as e:
            if e.code in (ErrorCode.NOT_CONNECTED, ErrorCode.TIMEOUT):
                raise
            errors["bands"] = e.message
        try:
            enabled = await app.state.speaker.read_eq_enabled()
        except SpeakerError as e:
            errors["enabled"] = e.message
        return EqOut(bands=bands, enabled=enabled, errors=errors)

    @api.get("/speaker/eq", response_model=EqOut)
    async def speaker_eq() -> EqOut:
        return await eq_out()  # read only

    @api.post("/speaker/eq", response_model=EqOut)
    async def speaker_eq_set(body: EqWrite, ident: Identity = Depends(speaker_writer)) -> EqOut:
        values = {b.band: b.value for b in body.bands}
        await app.state.speaker.write_eq(values)
        audit.add(ident.ip, ident.name, "speaker", "אקולייזר " + " ".join(f"{k}:{v:g}" for k, v in values.items()))
        return await eq_out()

    # ---- automatic colour cycling
    def cycle_out() -> dict:
        return {"config": app.state.cycle.config(), "status": app.state.cycle.status()}

    @api.get("/speaker/cycle")
    async def cycle_get() -> dict:
        return cycle_out()  # no speaker request at all

    @api.put("/speaker/cycle/config")
    async def cycle_config(body: CycleConfig, ident: Identity = Depends(speaker_writer)) -> dict:
        app.state.cycle.save_config(body.model_dump())  # applies from the next step if running
        audit.add(ident.ip, ident.name, "speaker_cycle", f"הגדרות: כל {body.interval_s} שנ׳, " + ("אקראי" if body.mode == "random" else f"פלטה של {len(body.palette)}"))
        return cycle_out()

    @api.post("/speaker/cycle/start")
    async def cycle_start(ident: Identity = Depends(speaker_writer)) -> dict:
        await app.state.cycle.start()
        return cycle_out()

    @api.post("/speaker/cycle/stop")
    async def cycle_stop(ident: Identity = Depends(speaker_writer)) -> dict:
        await app.state.cycle.stop()  # the last colour stays on the speaker
        return cycle_out()

    # ---- personal profiles
    def profiles_out() -> dict:
        ps = app.state.profiles
        return {"profiles": ps.profiles.list(), "loaded_id": ps.loaded_id(), "undo": ps.undo_info(), "loading": ps.busy}

    def profile_exists(pid: str) -> dict:
        p = app.state.profiles.profiles.get(pid)
        if p is None:
            raise ManagerError(ErrorCode.INVALID_COMMAND, "הפרופיל לא נמצא.", 404)
        return p

    @api.get("/speaker/profiles")
    async def profiles_list() -> dict:
        return profiles_out()  # no speaker request

    @api.post("/speaker/profiles", status_code=201)
    async def profile_save(body: ProfileCreate, ident: Identity = Depends(speaker_writer)) -> dict:
        ps = app.state.profiles
        if ps.profiles.name_taken(body.name):
            raise ManagerError(ErrorCode.INVALID_COMMAND, "כבר יש פרופיל בשם הזה.", 409)
        data = await ps.capture(body.include_volume)  # fresh values from the speaker; refuses a partial capture
        p = ps.profiles.add(body.name, body.include_volume, data, time.time())
        if p is None:
            raise ManagerError(ErrorCode.DENIED, "יש יותר מדי פרופילים. מחק חלק מהם.", 429)
        store.set_state("speaker", "profile_loaded", p["id"])  # it matches the speaker right now
        audit.add(ident.ip, ident.name, "speaker_profile", f"נשמר: {p['name']}" + (" (כולל עוצמה)" if body.include_volume else ""))
        return {"created": p, **profiles_out()}

    @api.patch("/speaker/profiles/{pid}")
    async def profile_rename(pid: str, body: ProfileName, ident: Identity = Depends(speaker_writer)) -> dict:
        old = profile_exists(pid)
        if app.state.profiles.profiles.name_taken(body.name, except_id=pid):
            raise ManagerError(ErrorCode.INVALID_COMMAND, "כבר יש פרופיל בשם הזה.", 409)
        app.state.profiles.profiles.rename(pid, body.name, time.time())
        audit.add(ident.ip, ident.name, "speaker_profile", f"שם שונה: {old['name']} ← {body.name}")
        return profiles_out()

    @api.post("/speaker/profiles/{pid}/update")
    async def profile_update(pid: str, ident: Identity = Depends(speaker_writer)) -> dict:
        """Overwrite a profile with the speaker's current values (read fresh; a partial capture is refused). Writes nothing
        to the speaker. Volume is captured only if the profile already includes it."""
        not_loading()
        old = profile_exists(pid)
        data = await app.state.profiles.capture(old["include_volume"])
        p = app.state.profiles.profiles.replace_data(pid, data, time.time())
        if p is None:  # deleted meanwhile
            raise ManagerError(ErrorCode.INVALID_COMMAND, "הפרופיל לא נמצא.", 404)
        store.set_state("speaker", "profile_loaded", pid)  # it matches the speaker right now
        audit.add(ident.ip, ident.name, "speaker_profile", f"עודכן למצב הנוכחי: {p['name']}")
        return {"updated": p, **profiles_out()}

    @api.delete("/speaker/profiles/{pid}")
    async def profile_delete(pid: str, ident: Identity = Depends(speaker_writer)) -> dict:
        old = profile_exists(pid)
        app.state.profiles.profiles.delete(pid)
        if store.get_state("speaker", "profile_loaded") == pid:
            store.set_state("speaker", "profile_loaded", None)
        audit.add(ident.ip, ident.name, "speaker_profile", f"נמחק: {old['name']}")
        return profiles_out()

    def load_audit(ident: Identity, what: str, out: dict) -> None:
        word = {"full": "נטען במלואו", "partial": "נטען חלקית", "failed": "לא נטען"}[out["status"]]
        failed = ", ".join(s["label"] for s in out["steps"] if not s["ok"])
        audit.add(ident.ip, ident.name, "speaker_profile", f"{what}: {word}" + (f" (נכשל: {failed})" if failed else ""))

    @api.post("/speaker/profiles/undo")
    async def profile_undo(ident: Identity = Depends(speaker_writer)) -> dict:
        out = await app.state.profiles.undo()
        load_audit(ident, "חזרה למצב הקודם", out)
        return {**out, **profiles_out()}

    @api.post("/speaker/profiles/{pid}/load")
    async def profile_load(pid: str, ident: Identity = Depends(speaker_writer)) -> dict:
        p = profile_exists(pid)
        out = await app.state.profiles.load(pid)
        load_audit(ident, f"טעינת {p['name']}", out)
        return {**out, **profiles_out()}

    @api.put("/speaker/config", response_model=SpeakerState)
    async def speaker_config(body: SpeakerConfig, ident: Identity = Depends(admin)) -> SpeakerState:
        not_loading()
        # Only the address changes; nothing is sent to the speaker except the read that follows.
        await app.state.cycle.stop_if_running("כתובת הרמקול שונתה")
        store.set_state("speaker", "host", body.host)
        app.state.speaker.host = body.host
        audit.add(ident.ip, ident.name, "speaker_host", body.host)
        return SpeakerState(**await app.state.speaker.state())

    # ---- Zeppelin test lab (admin only): bass, light brightness and colour, whose write effect is not verified yet.
    # Rules, enforced here: originals are read and saved before any test; a saved snapshot is never overwritten; tests
    # and restore go only to the speaker the snapshot was taken from; results are reported, never declared "working".
    def lab_get(key: str, default):
        v = store.get_state("speaker", key)
        return json.loads(v) if v else default

    def lab_set(key: str, value) -> None:
        store.set_state("speaker", key, json.dumps(value, ensure_ascii=False) if value is not None else None)

    def lab_snapshot_for_tests(name: str | None = None) -> dict:
        snap = lab_get("lab_original", None)
        if not snap:
            raise ManagerError(ErrorCode.DENIED, "קודם שמור את הערכים המקוריים, ורק אחר כך בדוק.", 409)
        if name is not None and name not in snap["values"]:  # a snapshot from before this control existed
            raise ManagerError(ErrorCode.DENIED, "השמירה הקיימת לא כוללת את הפקד הזה. שחזר או בטל אותה, ושמור מחדש.", 409)
        if snap["host"] != app.state.speaker.host:
            raise ManagerError(ErrorCode.DENIED, f"הערכים המקוריים נשמרו מרמקול בכתובת {snap['host']}, לא מהכתובת הנוכחית.", 409)
        return snap

    async def lab_out() -> dict:
        current, errors = await app.state.speaker.lab_read()
        try:  # read-only status: the speaker refuses to change it, so it is shown but never written
            gain = await app.state.speaker.read_source_gain()
        except SpeakerError as e:
            if e.code in (ErrorCode.NOT_CONNECTED, ErrorCode.TIMEOUT):
                raise
            gain, errors = None, {**errors, "source_gain": e.message}
        return {"host": app.state.speaker.host, "snapshot": lab_get("lab_original", None), "current": current, "errors": errors,
                "source_gain": gain, "last": lab_get("lab_last", {}), "observations": lab_get("lab_obs", [])}

    @api.get("/speaker/lab")
    async def lab_state(_: Identity = Depends(admin)) -> dict:
        return await lab_out()  # read only

    @api.post("/speaker/lab/snapshot")
    async def lab_snapshot(ident: Identity = Depends(admin)) -> dict:
        snap = lab_get("lab_original", None)
        if snap:
            # Complete an older snapshot with controls added to the lab since: only the MISSING ones are read and saved.
            # A value already saved is never overwritten (it may be the only record of the original).
            missing = [k for k in LAB_CONTROLS if k not in snap["values"]]
            if not missing:
                raise ManagerError(ErrorCode.DENIED, "כבר שמורים ערכים מקוריים. שחזר אותם או בטל את השמירה לפני שמירה חדשה.", 409)
            if snap["host"] != app.state.speaker.host:
                raise ManagerError(ErrorCode.DENIED, f"הערכים המקוריים נשמרו מרמקול בכתובת {snap['host']}, לא מהכתובת הנוכחית.", 409)
            values, errors = await app.state.speaker.lab_read()
            bad = {k: v for k, v in errors.items() if k in missing}
            if bad:
                raise ManagerError(ErrorCode.UNSUPPORTED, "לא ניתן לקרוא את כל הערכים, ולכן לא נשמרו: " + "; ".join(f"{k}: {v}" for k, v in bad.items()), 502)
            added = {k: values[k] for k in missing}
            snap["values"].update(added)
            lab_set("lab_original", snap)
            audit.add(ident.ip, ident.name, "speaker_lab", "השמירה הושלמה: " + json.dumps(added, ensure_ascii=False))
            return await lab_out()
        values, errors = await app.state.speaker.lab_read()
        if errors:
            raise ManagerError(ErrorCode.UNSUPPORTED, "לא ניתן לקרוא את כל הערכים, ולכן לא נשמרו: " + "; ".join(f"{k}: {v}" for k, v in errors.items()), 502)
        lab_set("lab_original", {"host": app.state.speaker.host, "at": time.time(), "values": values})
        audit.add(ident.ip, ident.name, "speaker_lab", "נשמרו ערכים מקוריים: " + json.dumps(values, ensure_ascii=False))
        return await lab_out()

    @api.delete("/speaker/lab/snapshot")
    async def lab_discard(ident: Identity = Depends(admin)) -> dict:
        lab_set("lab_original", None)  # the speaker keeps its current values
        audit.add(ident.ip, ident.name, "speaker_lab", "השמירה בוטלה בלי שחזור")
        return await lab_out()

    async def lab_test(ident: Identity, name: str, value) -> dict:
        not_loading()
        lab_snapshot_for_tests(name)
        r = await app.state.speaker.probe(name, value)
        r["at"] = time.time()
        last = lab_get("lab_last", {})
        last[name] = r
        lab_set("lab_last", last)
        audit.add(ident.ip, ident.name, "speaker_lab", f"בדיקה {name}: נשלח {value}, מדווח {r['after']}" + (f", שגיאה: {r['speaker_error']}" if r["speaker_error"] else ""))
        return {"result": r, **await lab_out()}

    @api.post("/speaker/lab/bass")
    async def lab_bass(body: LabBass, ident: Identity = Depends(admin)) -> dict:
        return await lab_test(ident, "bass", float(body.value))

    @api.post("/speaker/lab/brightness")
    async def lab_brightness(body: LabBrightness, ident: Identity = Depends(admin)) -> dict:
        return await lab_test(ident, "brightness", body.value)

    @api.post("/speaker/lab/rgb")
    async def lab_rgb(body: LabRgb, ident: Identity = Depends(admin)) -> dict:
        await app.state.cycle.stop_if_running("נבחר צבע ידני (מעבדה)")
        return await lab_test(ident, "rgb", body.model_dump())

    @api.post("/speaker/lab/eq_enabled")
    async def lab_eq_enabled(body: LabBool, ident: Identity = Depends(admin)) -> dict:
        return await lab_test(ident, "eq_enabled", body.value)

    @api.post("/speaker/lab/loudness")
    async def lab_loudness(body: LabBool, ident: Identity = Depends(admin)) -> dict:
        return await lab_test(ident, "loudness", body.value)

    @api.post("/speaker/lab/balance")
    async def lab_balance(body: LabBass, ident: Identity = Depends(admin)) -> dict:
        return await lab_test(ident, "balance", float(body.value))  # any finite number: range and direction unknown

    @api.post("/speaker/lab/restore")
    async def lab_restore(ident: Identity = Depends(admin)) -> dict:
        not_loading()
        snap = lab_snapshot_for_tests()
        results = await app.state.speaker.restore(snap["values"])
        ok = all(r["ok"] for r in results.values())
        if ok:  # keep the originals until every one of them is confirmed back on the speaker
            lab_set("lab_original", None)
        audit.add(ident.ip, ident.name, "speaker_lab", "שחזור " + ("הושלם" if ok else "חלקי: " + ", ".join(k for k, r in results.items() if not r["ok"])))
        return {"restored": ok, "results": results, **await lab_out()}

    @api.post("/speaker/lab/observation")
    async def lab_observation(body: LabObservation, ident: Identity = Depends(admin)) -> dict:
        last = lab_get("lab_last", {}).get(body.control)
        if not last:
            raise ManagerError(ErrorCode.INVALID_COMMAND, "אין בדיקה אחרונה לפקד הזה.", 409)
        obs = lab_get("lab_obs", [])
        obs.insert(0, {"control": body.control, "result": body.result, "note": body.note, "sent": last["sent"],
                       "after": last["after"], "speaker_error": last["speaker_error"], "at": time.time(), "who": ident.name})
        lab_set("lab_obs", obs[:100])
        word = {"changed": "נראה/נשמע שינוי", "no_change": "לא השתנה דבר", "unsure": "לא בטוח"}[body.result]
        audit.add(ident.ip, ident.name, "speaker_lab", f"תצפית {body.control} ({last['sent']}): {word}")
        return await lab_out()

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
