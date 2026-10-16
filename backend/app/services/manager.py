from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from collections import OrderedDict, deque

from app.adapters.android_tv import AndroidTVAdapter
from app.adapters.base import AdapterError, DeviceAdapter
from app.adapters.lg_webos import LgWebOsAdapter
from app.adapters.mock import MockAdapter
from app.models.schemas import (
    Action, CommandRequest, DeviceOut, ErrorCode, check_kind,
)
from app.services.discovery import discover_android_tv
from app.services.ssdp import discover_lg
from app.storage.db import DeviceRow, Store

DEFAULT_ROLE = {"lg": "tv", "hot": "box"}  # unknown role falls back to what that driver usually is
POINTER_PER_SECOND = 100
RELOCATE_EVERY_S = 30.0
RELOCATE_AFTER_S = 90.0  # unreachable this long before we go looking for it

COMMAND_TIMEOUT_S = 8.0
DIGITS_TIMEOUT_S = 20.0
RATE_LIMIT = 60  # commands ...
RATE_WINDOW_S = 5.0  # ... per window
DEDUPE_SIZE = 256


class ManagerError(Exception):
    def __init__(self, code: ErrorCode, message: str, http: int):
        super().__init__(message)
        self.code, self.message, self.http = code, message, http


class DeviceManager:
    def __init__(self, store: Store, use_mock: bool, cert_dir: str | Path = "data/certs"):
        self.store = store
        self.use_mock = use_mock
        self.cert_dir = Path(cert_dir)
        self.adapters: dict[str, DeviceAdapter] = {}
        self._locks: dict[str, asyncio.Lock] = {}  # serial command queue per device
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._hits: deque[float] = deque()
        self._pointer_hits: deque[float] = deque()
        self._lost_since: dict[str, float] = {}
        self._relocator: asyncio.Task | None = None
        self.notify = None  # optional callback(event, detail), set by the app to write the audit log
        for row in store.list():
            self._adapter_for(row)

    def _adapter_for(self, row: DeviceRow) -> DeviceAdapter:
        if row.id not in self.adapters:
            if self.use_mock:
                adapter: DeviceAdapter = MockAdapter(row.kind, row.host)
            elif row.kind == "hot":
                adapter = AndroidTVAdapter(row.id, row.host, self.cert_dir)
            else:
                adapter = LgWebOsAdapter(row.id, row.host, self.cert_dir.parent / "lg_keys")
            self.adapters[row.id] = adapter
            self._locks[row.id] = asyncio.Lock()
        return self.adapters[row.id]

    def name_of(self, device_id: str) -> str:
        return self._row(device_id).name

    def _row(self, device_id: str) -> DeviceRow:
        for r in self.store.list():
            if r.id == device_id:
                return r
        raise ManagerError(ErrorCode.INVALID_COMMAND, "מכשיר לא נמצא.", 404)

    def snapshot(self) -> list[DeviceOut]:
        out = []
        for r in self.store.list():
            a = self._adapter_for(r)
            out.append(DeviceOut(id=r.id, kind=r.kind, name=r.name, host=r.host, role=r.role or DEFAULT_ROLE[r.kind],
                                 channel=self.store.get_state(r.id, "channel"),
                                 previous_channel=self.store.get_state(r.id, "previous_channel"),
                                 connection=a.connection, capabilities=a.capabilities,
                                 last_error=getattr(a, "last_error", None)))
        return out

    def add(self, kind: str, host: str, role: str | None = None, name: str | None = None) -> DeviceOut:
        role = role or DEFAULT_ROLE[kind]
        label = name.strip() if name and name.strip() else ("טלוויזיה" if role == "tv" else "ממיר")
        row = DeviceRow(id=uuid.uuid4().hex[:12], kind=kind, host=host, name=label, role=role)
        if not self.store.add(row):
            raise ManagerError(ErrorCode.INVALID_COMMAND, "המכשיר כבר קיים.", 409)
        self._adapter_for(row)
        return next(d for d in self.snapshot() if d.id == row.id)

    async def update(self, device_id: str, name: str | None, role: str | None, host: str | None = None) -> DeviceOut:
        row = self._row(device_id)
        if host is not None and host == row.host:
            host = None
        if not self.store.update(device_id, name.strip() if name else None, role, host):
            raise ManagerError(ErrorCode.INVALID_COMMAND, "כתובת זו כבר בשימוש במכשיר אחר.", 409)
        if host is not None:
            await self._rebuild(device_id)  # new address -> new connection; the pairing credentials stay (same device)
        return next(d for d in self.snapshot() if d.id == device_id)

    async def _rebuild(self, device_id: str) -> None:
        old = self.adapters.pop(device_id, None)
        if old is not None:
            await old.close()
        adapter = self._adapter_for(self._row(device_id))
        if isinstance(adapter, (AndroidTVAdapter, LgWebOsAdapter)):
            asyncio.ensure_future(adapter.start())

    # -- a paired device that stays unreachable may simply have a new DHCP address
    async def relocate_once(self, now: float | None = None) -> list[str]:
        """Find paired-but-lost devices again by scanning the network. Conservative on purpose: it only moves a device
        when it is the ONLY device of its kind and exactly ONE such device is found at a different address."""
        now = time.monotonic() if now is None else now
        moved: list[str] = []
        for kind, finder in (("lg", self.find_lg), ("hot", self.find_android)):
            rows = [r for r in self.store.list() if r.kind == kind]
            if len(rows) != 1:
                self._lost_since.pop(rows[0].id if rows else "", None)
                continue
            row = rows[0]
            a = self._adapter_for(row)
            if not getattr(a, "paired", False) or a.connection != "disconnected":
                self._lost_since.pop(row.id, None)
                continue
            since = self._lost_since.setdefault(row.id, now)
            if now - since < RELOCATE_AFTER_S:
                continue
            found = [h for h in await finder() if h != row.host]
            self._lost_since[row.id] = now  # next attempt after another full interval
            if len(found) == 1 and self.store.update(row.id, None, None, found[0]):
                old = row.host
                await self._rebuild(row.id)
                moved.append(row.id)
                if self.notify:
                    self.notify("device_moved", f"{row.name}: {old} ← {found[0]}")
        return moved

    async def find_lg(self) -> list[str]:
        return [t.host for t in await discover_lg(3.0)]

    async def find_android(self) -> list[str]:
        return [f.host for f in await discover_android_tv(3.0)]

    async def _relocate_loop(self) -> None:
        while True:
            await asyncio.sleep(RELOCATE_EVERY_S)
            try:
                await self.relocate_once()
            except Exception:  # noqa: BLE001 - a scan problem must never stop the loop
                pass

    async def remove(self, device_id: str) -> None:
        """Forget a device: stop its connection and delete its pairing credentials."""
        self._row(device_id)
        adapter = self.adapters.pop(device_id, None)
        self._locks.pop(device_id, None)
        if adapter is not None:
            await adapter.close()
        self.store.remove(device_id)
        for f in (*self.cert_dir.glob(f"{device_id}.*"), *(self.cert_dir.parent / "lg_keys").glob(f"{device_id}.*")):
            f.unlink(missing_ok=True)

    async def selftest(self, device_id: str) -> dict:
        row = self._row(device_id)
        async with self._locks[row.id]:  # do not interleave with a user's own key presses
            return await self._call(self._adapter_for(row).selftest(), 12.0)

    async def pointer(self, device_id: str, dx: int, dy: int, scroll_dy: int, click: bool) -> None:
        """Touchpad events. Own, higher rate limit; deliberately not serialized behind slow commands."""
        row = self._row(device_id)
        now = time.monotonic()
        while self._pointer_hits and now - self._pointer_hits[0] > 1.0:
            self._pointer_hits.popleft()
        if len(self._pointer_hits) >= POINTER_PER_SECOND:
            raise ManagerError(ErrorCode.DENIED, "יותר מדי תנועות עכבר.", 429)
        self._pointer_hits.append(now)
        await self._call(self._adapter_for(row).pointer(dx, dy, scroll_dy, click), 3.0)

    async def startup(self) -> None:
        """Reconnect paired devices in the background; never blocks or fails server start."""
        for a in self.adapters.values():
            if isinstance(a, (AndroidTVAdapter, LgWebOsAdapter)):
                asyncio.ensure_future(a.start())
        if not self.use_mock:
            self._relocator = asyncio.create_task(self._relocate_loop())

    async def shutdown(self) -> None:
        if self._relocator:
            self._relocator.cancel()
            await asyncio.gather(self._relocator, return_exceptions=True)
        for a in self.adapters.values():
            await a.close()

    async def discover(self) -> list[DeviceOut]:
        """mDNS scan for Android TV Remote v2 devices; new ones are saved as unpaired HOT devices.
        Not every Android TV on the LAN is the HOT box: pick by IP."""
        if self.use_mock:
            return []
        known = {(r.kind, r.host) for r in self.store.list()}
        hot, lg = await asyncio.gather(discover_android_tv(), discover_lg(), return_exceptions=True)
        for f in hot if isinstance(hot, list) else []:
            if ("hot", f.host) not in known:
                self.store.add(DeviceRow(id=uuid.uuid4().hex[:12], kind="hot", host=f.host,
                                         name=f.name, role="box"))
        for t in lg if isinstance(lg, list) else []:
            if ("lg", t.host) not in known:
                self.store.add(DeviceRow(id=uuid.uuid4().hex[:12], kind="lg", host=t.host,
                                         name="LG webOS", role="tv"))
        for r in self.store.list():
            self._adapter_for(r)
        return self.snapshot()

    def diagnostics(self, device_id: str) -> dict:
        row = self._row(device_id)
        a = self._adapter_for(row)
        base = {"id": row.id, "kind": row.kind, "host": row.host, "connection": a.connection}
        return base | (a.diagnostics() if isinstance(a, (AndroidTVAdapter, LgWebOsAdapter)) else {})

    async def pair_start(self, device_id: str) -> None:
        a = self._adapter_for(self._row(device_id))
        await self._call(a.pair_start())

    async def pair_confirm(self, device_id: str, code: str) -> DeviceOut:
        a = self._adapter_for(self._row(device_id))
        await self._call(a.pair_confirm(code))
        return next(d for d in self.snapshot() if d.id == device_id)

    async def send(self, device_id: str, req: CommandRequest) -> str:
        row = self._row(device_id)
        self._validate(row, req)
        if req.request_id in self._seen:
            return "duplicate"  # same request must never reach the device twice
        self._rate_check()
        adapter = self._adapter_for(row)
        async with self._locks[row.id]:
            if req.action in (Action.DIGITS, Action.CHANNEL_STEP, Action.CHANNEL_LAST):
                await self._call(self._send_channel(row.id, adapter, req), DIGITS_TIMEOUT_S)
            elif req.action is Action.LAUNCH_APP:  # confirming an app opened can take a few seconds
                await self._call(adapter.execute(req.action.value, req.params), DIGITS_TIMEOUT_S)
            else:
                await self._call(adapter.execute(req.action.value, req.params))
        self._seen[req.request_id] = None
        while len(self._seen) > DEDUPE_SIZE:
            self._seen.popitem(last=False)
        return "sent"

    def _remember_channel(self, device_id: str, new: str) -> None:
        cur = self.store.get_state(device_id, "channel")
        if cur != new:
            self.store.set_state(device_id, "previous_channel", cur)
            self.store.set_state(device_id, "channel", new)

    def set_channel(self, device_id: str, channel: str) -> DeviceOut:
        """Tell the server which channel the box is on (e.g. after using the physical remote). Sends nothing."""
        self._row(device_id)
        self._remember_channel(device_id, str(int(channel)))
        return next(d for d in self.snapshot() if d.id == device_id)

    async def _send_channel(self, device_id: str, adapter: DeviceAdapter, req: CommandRequest) -> None:
        """digits / channel_step / channel_last. Channel +/- and "last" are emulated with digits because
        this box ignores CHANNEL_UP/DOWN; the target is computed from the channel WE last typed."""
        p = dict(req.params)
        if req.action is Action.DIGITS:
            target = str(int(p["digits"]))
            p["digits"] = p["digits"]  # type exactly what was asked (leading zeros included)
        else:
            cur = self.store.get_state(device_id, "channel")
            if req.action is Action.CHANNEL_STEP:
                if cur is None:
                    raise ManagerError(ErrorCode.UNSUPPORTED, "הערוץ הנוכחי לא ידוע. הקלד מספר ערוץ פעם אחת (או קבע אותו ידנית) ואז אפשר לעלות ולרדת.", 409)
                n = int(cur) + int(p["delta"])
                if not 1 <= n <= 9999:
                    raise ManagerError(ErrorCode.INVALID_COMMAND, "מספר הערוץ מחוץ לטווח.", 422)
                target = str(n)
            else:
                prev = self.store.get_state(device_id, "previous_channel")
                if prev is None:
                    raise ManagerError(ErrorCode.UNSUPPORTED, "אין ערוץ קודם שמור. עבר לערוץ דרך האתר קודם.", 409)
                target = prev
            p["digits"] = target
        await self._send_digits(adapter, p)
        self._remember_channel(device_id, target)  # only after the whole number went out

    @staticmethod
    async def _send_digits(adapter: DeviceAdapter, p: dict) -> None:
        """One channel number = one atomic, ordered key sequence under the device lock.
        Stops at the first failure so a half-typed number is reported, never hidden."""
        delay = p.get("delay_ms", 350) / 1000
        keys = [f"KEYCODE_{d}" for d in str(p["digits"])]
        if p.get("enter"):
            keys.append("DPAD_CENTER")
        for i, key in enumerate(keys):
            if i:
                await asyncio.sleep(delay)
            await adapter.execute("key_press", {"key": key})

    @staticmethod
    def _validate(row: DeviceRow, req: CommandRequest) -> None:
        if (e := check_kind(row.kind, req.action, req.params)):
            code = ErrorCode.INVALID_COMMAND if req.action is Action.KEY_PRESS else ErrorCode.UNSUPPORTED
            raise ManagerError(code, e, 422)

    async def send_to_kind(self, kind: str, action: str, params: dict) -> None:
        """Used by the scheduler: pick the (connected) device of this kind and run the command."""
        rows = [r for r in self.store.list() if r.kind == kind]
        if not rows:
            raise ManagerError(ErrorCode.NOT_PAIRED, "אין מכשיר מהסוג הזה.", 409)
        rows.sort(key=lambda r: self._adapter_for(r).connection != "connected")
        req = CommandRequest(target=rows[0].id, action=Action(action), params=params, request_id=uuid.uuid4().hex)
        await self.send(rows[0].id, req)

    def _rate_check(self) -> None:
        now = time.monotonic()
        while self._hits and now - self._hits[0] > RATE_WINDOW_S:
            self._hits.popleft()
        if len(self._hits) >= RATE_LIMIT:
            raise ManagerError(ErrorCode.DENIED, "יותר מדי פקודות. נסה שוב בעוד רגע.", 429)
        self._hits.append(now)

    @staticmethod
    async def _call(coro, timeout: float = COMMAND_TIMEOUT_S):
        try:
            return await asyncio.wait_for(coro, timeout)
        except TimeoutError:
            raise ManagerError(ErrorCode.TIMEOUT, "המכשיר לא הגיב בזמן.", 504) from None
        except AdapterError as e:
            http = {ErrorCode.NOT_PAIRED: 409, ErrorCode.NOT_CONNECTED: 409}.get(e.code, 422)
            raise ManagerError(e.code, e.message, http) from e
