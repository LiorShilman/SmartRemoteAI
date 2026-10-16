"""LG webOS adapter on top of aiowebostv (SSAP over WebSocket).

Not yet run against a real LG TV. `execute` returning means the TV accepted the request on the
socket, not that the visible result was verified.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Callable

from aiohttp import ClientError
from aiowebostv import WebOsClient, WebOsTvCommandError, WebOsTvPairError
from aiowebostv.exceptions import WebOsTvCommandTimeoutError

from app.adapters.base import AdapterError, DeviceAdapter
from app.models.schemas import CapabilityState, Connection, ErrorCode

log = logging.getLogger("smart_remote.lg_webos")

BUTTON_MAP = {
    "DPAD_UP": "UP", "DPAD_DOWN": "DOWN", "DPAD_LEFT": "LEFT", "DPAD_RIGHT": "RIGHT",
    "DPAD_CENTER": "ENTER", "BACK": "BACK", "HOME": "HOME",
    # menu-style keys map to the webOS button of the same name
    **{k: k for k in ("MENU", "QMENU", "EXIT", "INFO", "GUIDE", "INPUT_HUB", "RED", "GREEN", "YELLOW", "BLUE")},
}
APP_IDS = {"youtube": "youtube.leanback.v4", "netflix": "netflix", "spotify": "spotify-beehive"}
AUDIO_ACTIONS = {"volume_up", "volume_down", "mute"}
SOUND_OUTPUT_HE = {
    "external_optical": "מערכת חיצונית בחיבור אופטי",
    "external_arc": "מערכת חיצונית ב-ARC",
    "lineout": "יציאת קו", "headphone": "אוזניות", "bt_soundbar": "סאונדבר בבלוטות'",
}

PAIR_DEADLINE_S = 60.0   # the TV prompt times out after ~10s per attempt; we re-prompt until this deadline
PAIR_WAIT_S = 6.0        # how long pair_confirm waits before telling the user to approve and retry
BACKOFF_MIN_S, BACKOFF_MAX_S = 2.0, 60.0

ClientFactory = Callable[[str, "str | None"], Any]
_NET_ERRORS = (OSError, ClientError, TimeoutError)


def _default_factory(host: str, key: str | None) -> WebOsClient:
    return WebOsClient(host, client_key=key)


class LgWebOsAdapter(DeviceAdapter):
    kind = "lg"

    def __init__(self, device_id: str, host: str | None, key_dir: Path, factory: ClientFactory = _default_factory):
        super().__init__(host)
        self.device_id = device_id
        self._keyfile = key_dir / f"{device_id}.lgkey"
        self._factory = factory
        self._client: Any | None = None
        self._pair_task: asyncio.Task | None = None
        self._run_task: asyncio.Task | None = None
        self._available = False
        self.last_error: str | None = None
        self.last_command_at: float | None = None
        self._audio_blocked: str | None = None  # sound output that refuses TV volume control
        self._key: str | None = self._keyfile.read_text(encoding="utf-8").strip() or None if self._keyfile.is_file() else None

    @property
    def paired(self) -> bool:
        return self._key is not None

    @property
    def connection(self) -> Connection:
        if not self.paired:
            return "unpaired"
        return "connected" if self._available else "disconnected"

    @property
    def capabilities(self) -> dict[str, CapabilityState]:
        # Unknown until a human sees the TV react. Wake-on-LAN is not implemented at all.
        caps: dict[str, CapabilityState] = {k: "unknown" for k in ("nav", "volume", "mute", "power_off", "inputs", "apps")}
        caps["wol"] = "unsupported"
        return caps

    def diagnostics(self) -> dict:
        return {"adapter": "aiowebostv", "paired": self.paired, "available": self._available,
                "last_error": self.last_error, "last_command_at": self.last_command_at,
                "audio_blocked_output": self._audio_blocked}

    # -- pairing: the TV shows an approval prompt on screen; no code is typed
    async def pair_start(self) -> None:
        if not self.host:
            raise AdapterError(ErrorCode.NOT_CONNECTED, "לא הוגדרה כתובת IP למכשיר.")
        await self._stop_tasks()
        self.last_error = None
        client = self._factory(self.host, None)
        self._pair_task = asyncio.create_task(self._pair_loop(client))

    async def _pair_loop(self, client: Any) -> None:
        deadline = time.monotonic() + PAIR_DEADLINE_S
        while time.monotonic() < deadline:
            try:
                await client.connect()
            except TimeoutError:
                continue  # prompt expired unanswered: show it again
            except WebOsTvPairError:
                self.last_error = "הבקשה נדחתה או שלא אושרה בטלוויזיה."
                return
            except _NET_ERRORS as e:
                self.last_error = "לא ניתן להתחבר לטלוויזיה (בדוק IP, שהיא דלוקה ובאותה רשת)."
                log.warning("lg %s pairing connect failed: %s", self.device_id, type(e).__name__)
                return
            if client.client_key:
                self._save_key(client.client_key)
                self._client, self._available, self.last_error = client, True, None
                self._run_task = asyncio.create_task(self._run(client))
                return
        self.last_error = "פג הזמן: הבקשה לא אושרה על מסך הטלוויזיה."

    async def pair_confirm(self, code: str) -> None:
        task = self._pair_task
        if task is None:
            if self.paired:
                return
            raise AdapterError(ErrorCode.NOT_PAIRED, "יש להתחיל צימוד לפני אישור.")
        await asyncio.wait({task}, timeout=PAIR_WAIT_S)
        if not task.done():
            raise AdapterError(ErrorCode.TIMEOUT, "ממתין לאישור על מסך הטלוויזיה. אשר שם ולחץ שוב.")
        self._pair_task = None
        if not self.paired:
            raise AdapterError(ErrorCode.DENIED, self.last_error or "הצימוד נכשל.")

    def _save_key(self, key: str) -> None:
        self._keyfile.parent.mkdir(parents=True, exist_ok=True)
        self._keyfile.write_text(key, encoding="utf-8")
        self._key = key

    # -- connection supervision (aiowebostv has no auto-reconnect)
    async def start(self) -> None:
        if not self.paired or not self.host:
            return
        self._client = self._factory(self.host, self._key)
        self._run_task = asyncio.create_task(self._run(self._client))

    async def _run(self, client: Any) -> None:
        backoff = BACKOFF_MIN_S
        while True:
            if client.is_connected():
                self._available, backoff = True, BACKOFF_MIN_S
                await asyncio.sleep(3)
                continue
            self._available = False
            try:
                await asyncio.wait_for(client.connect(), 15)
                self._available, self.last_error, backoff = True, None, BACKOFF_MIN_S
                continue
            except WebOsTvPairError:
                self._key = None
                self._keyfile.unlink(missing_ok=True)
                self.last_error = "הטלוויזיה ביטלה את הצימוד. צמד מחדש."
                return
            except _NET_ERRORS:
                self.last_error = "הטלוויזיה לא זמינה (כבויה או מנותקת). השרת ממשיך לנסות."
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - supervisor must survive library surprises
                self.last_error = "שגיאה בחיבור לטלוויזיה."
                log.warning("lg %s reconnect error: %r", self.device_id, e)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)

    # -- commands
    async def execute(self, action: str, params: dict) -> None:
        if not self.paired:
            raise AdapterError(ErrorCode.NOT_PAIRED, "המכשיר לא מצומד.")
        c = self._client
        if c is None or not self._available or not c.is_connected():
            raise AdapterError(ErrorCode.NOT_CONNECTED, "השרת לא מחובר לטלוויזיה (ייתכן שהיא כבויה).")
        try:
            await self._dispatch(c, action, params)
            if action in AUDIO_ACTIONS:
                self._audio_blocked = None
        except WebOsTvCommandTimeoutError as e:
            raise AdapterError(ErrorCode.TIMEOUT, "הטלוויזיה לא הגיבה בזמן.") from e
        except WebOsTvCommandError as e:
            log.warning("lg %s rejected %s: %s", self.device_id, action, e)
            if action in AUDIO_ACTIONS:
                raise await self._audio_error(c, e) from e
            self.last_error = "הטלוויזיה דחתה את הפקודה."
            raise AdapterError(ErrorCode.DENIED, self.last_error) from e
        except TimeoutError as e:
            raise AdapterError(ErrorCode.TIMEOUT, "הטלוויזיה לא הגיבה בזמן.") from e
        except _NET_ERRORS as e:
            self._available = False
            raise AdapterError(ErrorCode.NOT_CONNECTED, "החיבור לטלוויזיה נפל.") from e
        self.last_command_at = time.time()

    async def _audio_error(self, c: Any, cause: Exception) -> AdapterError:
        """The TV rejects volume/mute when sound goes to an external system. Say so instead of a generic denial."""
        try:
            out = await c.get_sound_output()
        except Exception:  # noqa: BLE001 - diagnostics only
            out = None
        if out and out != "tv_speaker":
            self._audio_blocked = str(out)
            where = SOUND_OUTPUT_HE.get(str(out), str(out))
            msg = (f"הטלוויזיה לא שולטת בעוצמה כי הקול יוצא ל{where}. שלוט בעוצמה במערכת הסאונד, "
                   "או שנה בטלוויזיה את יציאת הקול (הגדרות ← צליל ← יציאת קול).")
            self.last_error = msg
            return AdapterError(ErrorCode.UNSUPPORTED, msg)
        self.last_error = "הטלוויזיה דחתה את פקודת העוצמה."
        return AdapterError(ErrorCode.DENIED, self.last_error)

    async def selftest(self) -> dict:
        if not self.paired:
            raise AdapterError(ErrorCode.NOT_PAIRED, "המכשיר לא מצומד.")
        c = self._client
        if c is None or not self._available or not c.is_connected():
            raise AdapterError(ErrorCode.NOT_CONNECTED, "השרת לא מחובר לטלוויזיה (ייתכן שהיא כבויה).")
        t0 = time.monotonic()
        try:
            await c.get_current_app()  # a request the TV must answer
        except (WebOsTvCommandError, *_NET_ERRORS):
            return {"ok": False, "healed": False, "detail": "הטלוויזיה לא ענתה לבקשה."}
        return {"ok": True, "healed": False, "detail": f"הטלוויזיה מגיבה (תוך {int((time.monotonic() - t0) * 1000)}ms)."}

    async def pointer(self, dx: int, dy: int, scroll_dy: int, click: bool) -> None:
        if not self.paired:
            raise AdapterError(ErrorCode.NOT_PAIRED, "המכשיר לא מצומד.")
        c = self._client
        if c is None or not self._available or not c.is_connected():
            raise AdapterError(ErrorCode.NOT_CONNECTED, "השרת לא מחובר לטלוויזיה (ייתכן שהיא כבויה).")
        try:
            if dx or dy:
                await c.move(dx, dy)
            if scroll_dy:
                await c.scroll(0, scroll_dy)
            if click:
                await c.click()
        except WebOsTvCommandError as e:
            raise AdapterError(ErrorCode.DENIED, "הטלוויזיה דחתה את פקודת העכבר.") from e
        except _NET_ERRORS as e:
            self._available = False
            raise AdapterError(ErrorCode.NOT_CONNECTED, "החיבור לטלוויזיה נפל.") from e

    async def _dispatch(self, c: Any, action: str, params: dict) -> None:
        if action == "key_press":
            button = BUTTON_MAP.get(str(params.get("key")))
            if button is None:
                raise AdapterError(ErrorCode.UNSUPPORTED, "המקש לא נתמך ב-LG.")
            await c.button(button)
        elif action == "volume_up":
            await c.volume_up()
        elif action == "volume_down":
            await c.volume_down()
        elif action == "mute":
            muted = await c.get_muted()
            if muted is None:
                await c.button("MUTE")  # state unavailable: fall back to the toggle key
            else:
                await c.set_mute(not muted)
        elif action == "power_off":
            await c.power_off()
        elif action == "power_on":
            raise AdapterError(ErrorCode.UNSUPPORTED, "הפעלה מרחוק (Wake-on-LAN) עדיין לא מוגדרת.")
        elif action == "set_input":
            wanted = str(params["input"])
            inputs = await c.get_inputs() or []
            ids = {i.get("id") for i in inputs if isinstance(i, dict)}
            if wanted not in ids:
                raise AdapterError(ErrorCode.UNSUPPORTED, f"הכניסה {wanted} לא מופיעה ברשימת הטלוויזיה.")
            await c.set_input(wanted)
        elif action == "launch_app":
            await c.launch_app(APP_IDS[str(params["app"])])
        else:
            raise AdapterError(ErrorCode.UNSUPPORTED, "הפעולה לא נתמכת ב-LG.")

    async def _stop_tasks(self) -> None:
        for t in (self._pair_task, self._run_task):
            if t and not t.done():
                t.cancel()
                await asyncio.gather(t, return_exceptions=True)
        self._pair_task = self._run_task = None
        self._available = False
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001 - best effort
                pass
            self._client = None

    async def close(self) -> None:
        await self._stop_tasks()
