"""HOT / Android TV adapter on top of tronikos/androidtvremote2 (Android TV Remote v2).

Nothing here has been run against real HOT hardware yet. `execute` returning means the key was
handed to the library's send buffer, NOT that the box reacted.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

from androidtvremote2 import AndroidTVRemote, CannotConnect, ConnectionClosed, InvalidAuth

from app.adapters.base import AdapterError, DeviceAdapter
from app.models.schemas import CapabilityState, Connection, ErrorCode

log = logging.getLogger("smart_remote.android_tv")

CLIENT_NAME = "Smart Remote AI"

# Our allowlisted key names -> RemoteKeyCode names in androidtvremote2.
KEY_MAP: dict[str, str] = {
    "DPAD_UP": "KEYCODE_DPAD_UP", "DPAD_DOWN": "KEYCODE_DPAD_DOWN",
    "DPAD_LEFT": "KEYCODE_DPAD_LEFT", "DPAD_RIGHT": "KEYCODE_DPAD_RIGHT",
    "DPAD_CENTER": "KEYCODE_DPAD_CENTER", "BACK": "KEYCODE_BACK", "HOME": "KEYCODE_HOME",
    "MENU": "KEYCODE_MENU", "SETTINGS": "KEYCODE_SETTINGS", "GUIDE": "KEYCODE_GUIDE", "INFO": "KEYCODE_INFO", "MEDIA_PLAY_PAUSE": "KEYCODE_MEDIA_PLAY_PAUSE",
    "MEDIA_REWIND": "KEYCODE_MEDIA_REWIND", "MEDIA_FAST_FORWARD": "KEYCODE_MEDIA_FAST_FORWARD",
    "CHANNEL_UP": "KEYCODE_CHANNEL_UP", "CHANNEL_DOWN": "KEYCODE_CHANNEL_DOWN",
    "LAST_CHANNEL": "KEYCODE_LAST_CHANNEL", "PAGE_UP": "KEYCODE_PAGE_UP", "PAGE_DOWN": "KEYCODE_PAGE_DOWN",
    **{f"KEYCODE_{d}": f"KEYCODE_{d}" for d in range(10)},
}
# Measured on the HOT Streamer (SDMC, Android TV): the box answers `market://launch?id=<package>` with an error,
# but opens apps from https links. Per app: (expected foreground package, links to try in order).
HOT_APPS: dict[str, tuple[str, list[str]]] = {
    "netflix": ("com.netflix.ninja", ["https://www.netflix.com/title"]),
    "youtube": ("com.google.android.youtube.tv", ["https://www.youtube.com/tv"]),
    "spotify": ("com.spotify.tv.android", ["https://open.spotify.com"]),
}
STORE_PAGE = "market://details?id={package}"
STORE_PACKAGE = "com.android.vending"
APP_WAIT_S = 3.0
ACTION_KEYS = {"volume_up": "KEYCODE_VOLUME_UP", "volume_down": "KEYCODE_VOLUME_DOWN", "mute": "KEYCODE_VOLUME_MUTE"}

RemoteFactory = Callable[[str, str, str, str], Any]


def _default_factory(name: str, certfile: str, keyfile: str, host: str) -> AndroidTVRemote:
    return AndroidTVRemote(name, certfile, keyfile, host)


class AndroidTVAdapter(DeviceAdapter):
    kind = "hot"

    def __init__(self, device_id: str, host: str | None, cert_dir: Path, factory: RemoteFactory = _default_factory):
        super().__init__(host)
        self.device_id = device_id
        self._dir = cert_dir
        self._factory = factory
        self._remote: Any | None = None
        self._available = False
        self.last_error: str | None = None
        self.last_command_at: float | None = None

    # -- persistence of "paired": the certificate alone is not proof, the marker is written after finish_pairing
    @property
    def _cert(self) -> str:
        return str(self._dir / f"{self.device_id}.cert.pem")

    @property
    def _key(self) -> str:
        return str(self._dir / f"{self.device_id}.key.pem")

    @property
    def _marker(self) -> Path:
        return self._dir / f"{self.device_id}.paired"

    @property
    def paired(self) -> bool:
        return self._marker.is_file()

    @property
    def connection(self) -> Connection:
        if not self.paired:
            return "unpaired"
        return "connected" if self._available else "disconnected"

    @property
    def capabilities(self) -> dict[str, CapabilityState]:
        # Everything stays "unknown" until a human observes the box reacting.
        return {k: "unknown" for k in ("nav", "channel_step", "digits", "media", "volume", "mute", "apps")}

    def diagnostics(self) -> dict:
        return {"adapter": "androidtvremote2", "paired": self.paired, "available": self._available,
                "last_error": self.last_error, "last_command_at": self.last_command_at}

    # -- pairing
    def _new_remote(self) -> Any:
        if not self.host:
            raise AdapterError(ErrorCode.NOT_CONNECTED, "לא הוגדרה כתובת IP למכשיר.")
        self._dir.mkdir(parents=True, exist_ok=True)
        return self._factory(CLIENT_NAME, self._cert, self._key, self.host)

    async def pair_start(self) -> None:
        self._drop_remote()
        remote = self._new_remote()
        try:
            await remote.async_generate_cert_if_missing()
            _restrict(self._cert), _restrict(self._key)
            await remote.async_start_pairing()  # the box now shows a code on screen
        except CannotConnect as e:
            self._fail("לא ניתן להתחבר לממיר (בדוק IP, שהוא דלוק ובאותה רשת)", e)
        except InvalidAuth as e:
            self._fail("הממיר דחה את בקשת הצימוד", e, ErrorCode.DENIED)
        self._remote = remote
        self.last_error = None

    async def pair_confirm(self, code: str) -> None:
        if self._remote is None:
            raise AdapterError(ErrorCode.NOT_PAIRED, "יש להתחיל צימוד לפני הזנת קוד.")
        try:
            await self._remote.async_finish_pairing(code.strip())
        except InvalidAuth as e:
            self._remote = None  # a failed code invalidates the pairing session; user must restart
            self._fail("קוד הצימוד שגוי. התחל צימוד מחדש.", e, ErrorCode.DENIED)
        except CannotConnect as e:
            self._fail("החיבור לממיר נפל בזמן הצימוד", e)
        self._marker.write_text("1", encoding="utf-8")
        await self._connect()

    # -- connection lifecycle
    async def start(self) -> None:
        """Called on server start for already paired devices. Failures leave the device 'disconnected'."""
        if not self.paired:
            return
        try:
            self._remote = self._new_remote()
            await self._connect()
        except AdapterError:
            pass  # recorded in last_error; _connect already armed keep_reconnecting for CannotConnect

    async def _connect(self) -> None:
        remote = self._remote
        remote.add_is_available_updated_callback(self._on_available)
        try:
            await remote.async_connect()
            self._available = True
            self.last_error = None
        except InvalidAuth as e:
            self._unpair()
            self._fail("הצימוד נדחה. צמד מחדש.", e, ErrorCode.NOT_PAIRED)
        except CannotConnect as e:
            self._available = False
            remote.keep_reconnecting(self._unpair)  # backoff handled by the library
            self._fail("הממיר לא זמין כרגע. השרת ימשיך לנסות להתחבר.", e, ErrorCode.NOT_CONNECTED)
        else:
            remote.keep_reconnecting(self._unpair)

    def _on_available(self, available: bool) -> None:
        self._available = available

    def _unpair(self) -> None:
        self._marker.unlink(missing_ok=True)
        self._available = False
        self.last_error = "הצימוד בוטל על ידי הממיר. צמד מחדש."

    def _drop_remote(self) -> None:
        if self._remote is not None:
            try:
                self._remote.disconnect()
            except Exception:  # noqa: BLE001 - best effort cleanup
                pass
            self._remote = None
        self._available = False

    def _fail(self, message: str, cause: Exception, code: ErrorCode = ErrorCode.NOT_CONNECTED) -> None:
        self.last_error = message
        log.warning("android_tv %s: %s (%s)", self.device_id, message, type(cause).__name__)
        raise AdapterError(code, message) from cause

    # -- commands
    async def execute(self, action: str, params: dict) -> None:
        if not self.paired:
            raise AdapterError(ErrorCode.NOT_PAIRED, "המכשיר לא מצומד.")
        if self._remote is None or not self._available:
            raise AdapterError(ErrorCode.NOT_CONNECTED, "השרת לא מחובר לממיר כרגע.")
        if action == "launch_app":
            await self._launch_app(str(params.get("app")))
            self.last_command_at = time.time()
            return
        code = ACTION_KEYS.get(action) or (KEY_MAP.get(str(params.get("key"))) if action == "key_press" else None)
        if code is None:
            raise AdapterError(ErrorCode.UNSUPPORTED, "הפעולה לא נתמכת ב-HOT.")
        try:
            self._remote.send_key_command(code)
        except ConnectionClosed as e:
            self._available = False
            self._fail("החיבור לממיר נסגר", e)
        except ValueError as e:
            self._fail("המקש לא מוכר לספרייה", e, ErrorCode.UNSUPPORTED)
        self.last_command_at = time.time()

    async def selftest(self) -> dict:
        """Round trip through the volume keys: the box reports its own volume level, so a level change proves it
        received the key. A volume down + up leaves the level unchanged. If the box stays silent the connection is
        a zombie (socket open, device not listening): drop it and reconnect."""
        if not self.paired:
            raise AdapterError(ErrorCode.NOT_PAIRED, "המכשיר לא מצומד.")
        if self._remote is None or not self._available:
            raise AdapterError(ErrorCode.NOT_CONNECTED, "השרת לא מחובר לממיר כרגע.")
        vi = getattr(self._remote, "volume_info", None)
        if not vi or "level" not in vi:
            return {"ok": None, "healed": False, "detail": "הממיר לא מדווח עוצמה, ולכן אי אפשר לאמת שהוא מגיב."}
        before = vi["level"]
        first, second = (("KEYCODE_VOLUME_DOWN", "KEYCODE_VOLUME_UP") if before > 0 else ("KEYCODE_VOLUME_UP", "KEYCODE_VOLUME_DOWN"))
        t0 = time.monotonic()
        try:
            self._remote.send_key_command(first)
            moved = await self._wait_volume(lambda lv: lv != before)
            self._remote.send_key_command(second)  # always put it back
            await self._wait_volume(lambda lv: lv == before)
        except ConnectionClosed as e:
            self._available = False
            self._fail("החיבור לממיר נסגר", e)
        ms = int((time.monotonic() - t0) * 1000)
        if moved:
            return {"ok": True, "healed": False, "detail": f"הממיר מגיב למקשים (תוך {ms}ms)."}
        # silent: reconnect from scratch
        self._drop_remote()
        try:
            self._remote = self._new_remote()
            await self._connect()
            healed = self._available
        except AdapterError:
            healed = False
        return {"ok": False, "healed": healed, "detail": "הממיר לא הגיב למקשים. החיבור אותחל מחדש" + (" ומחובר. נסה שוב." if healed else ", אך עדיין לא מחובר.")}

    async def _wait_volume(self, pred, timeout: float = 2.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            vi = getattr(self._remote, "volume_info", None)
            if vi and pred(vi.get("level")):
                return True
            await asyncio.sleep(0.1)
        return False

    async def _launch_app(self, app: str) -> None:
        """Open an app and confirm it by the foreground package the box reports.
        If it never comes up, open its Play Store page and say it is probably not installed."""
        entry = HOT_APPS.get(app)
        if entry is None:
            raise AdapterError(ErrorCode.UNSUPPORTED, "האפליקציה לא נתמכת בממיר.")
        package, links = entry
        try:
            for link in links:
                self._remote.send_launch_app_command(link)
                if await self._foreground_becomes(package):
                    return
            self._remote.send_launch_app_command(STORE_PAGE.format(package=package))
            store = await self._foreground_becomes(STORE_PACKAGE)
        except ConnectionClosed as e:
            self._available = False
            self._fail("החיבור לממיר נסגר", e)
        name = app.capitalize()
        msg = (f"{name} לא נפתחה בממיר. כנראה שהיא לא מותקנת בו. נפתח דף ההתקנה שלה ב-Play Store."
               if store else f"{name} לא נפתחה בממיר (האפליקציה לא הגיבה).")
        self.last_error = msg
        raise AdapterError(ErrorCode.UNSUPPORTED, msg)

    async def _foreground_becomes(self, package: str) -> bool:
        end = time.monotonic() + APP_WAIT_S
        while time.monotonic() < end:
            if getattr(self._remote, "current_app", None) == package:
                return True
            await asyncio.sleep(0.25)
        return getattr(self._remote, "current_app", None) == package

    async def close(self) -> None:
        self._drop_remote()


def _restrict(path: str) -> None:
    """Best effort: owner-only permissions (effective on POSIX; Windows relies on the data dir ACL)."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
