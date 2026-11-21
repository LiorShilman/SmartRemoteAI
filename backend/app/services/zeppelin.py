"""Bowers & Wilkins Zeppelin Pro Edition: a small, fixed set of verified controls over the speaker's local HTTP API.

The speaker answers   GET /api/getData?path=<path>&roles=value          -> [ {"type": "i32_", "i32_": 23} ]
and accepts           GET /api/setData?path=<path>&role=value&value=<JSON>

Only the paths in CONTROLS can ever be read or written: there is deliberately no way to pass an arbitrary path from
the API. Query strings are encoded by httpx and the value JSON by json.dumps, never assembled by hand.

The speaker may answer HTTP 200 with an error object in the body, so a 200 is never taken as success on its own:
every write is followed by a read-back, and success is reported only when the speaker reports the requested value.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import re
import secrets
from dataclasses import dataclass
from typing import Any

import httpx

from app.models.schemas import ErrorCode

DEFAULT_HOST = "192.168.1.52"
TIMEOUT_S = 4.0
READBACK_RETRY_S = 0.4


@dataclass(frozen=True)
class Control:
    path: str
    type: str  # the speaker's value type tag: i32_ | double_ | bool_ | formationDownlightRgb | eqBandList


# Verified on the real speaker (value changes were heard / seen / synced with the B&W app).
# bass, brightness and rgb were promoted from the test lab on 2026-11-15 after physical observation.
# NOT here on purpose: settings:/mediaPlayer/attenuation (accepted writes but did not change the level) and the
# internal 5-band EQ (write effect not verified).
CONTROLS: dict[str, Control] = {
    "volume": Control("player:volume", "i32_"),
    "treble": Control("settings:/mediaPlayer/treble", "double_"),
    "light": Control("settings:/ui/ambientLightEnabled", "bool_"),
    "bass": Control("settings:/mediaPlayer/bass", "double_"),
    "brightness": Control("settings:/ui/ambientLightBrightness", "i32_"),
    "rgb": Control("settings:/ui/ambientLightRgb", "formationDownlightRgb"),
    # Mute: on/off verified by listening (2026-11-15).
    "mute": Control("settings:/mediaPlayer/mute", "bool_"),
    # Loudness: on/off write + read-back verified 2026-11-15; no clear audible difference heard (also in the lab).
    "loudness": Control("settings:/mediaPlayer/loudness", "bool_"),
    # Balance: written values read back; the speaker stores any value, so -6..+6 was chosen by the user. Which sign is
    # left/right is unknown, so there are no left/right labels (also in the lab, where any finite number is accepted).
    "balance": Control("settings:/mediaPlayer/balance", "double_"),
}

# Readable, write effect NOT verified yet. Reachable only through the admin "test lab": the original values must be
# saved first, every test reports exactly what the speaker read back, and the user records what physically happened.
# No ranges are assumed here: the speaker's own answer is how the range gets discovered.
LAB: dict[str, Control] = {
    "bass": Control("settings:/mediaPlayer/bass", "double_"),
    "brightness": Control("settings:/ui/ambientLightBrightness", "i32_"),
    "rgb": Control("settings:/ui/ambientLightRgb", "formationDownlightRgb"),
    # Equalizer on/off: reading verified, writing not yet. Shown read-only on the EQ card until verified here.
    "eq_enabled": Control("settings:/mediaPlayer/equalizerOnOff", "bool_"),
    # Loudness: on/off write + read-back verified 2026-11-15, but no clear audible difference -> lab only.
    "loudness": Control("settings:/mediaPlayer/loudness", "bool_"),
    # Balance: -1, 1 and 6 were written and 1/6 read back, but no audible effect was found; the range and which sign is
    # left or right are unknown -> lab only, any finite number, no left/right labels.
    "balance": Control("settings:/mediaPlayer/balance", "double_"),
}

# Bluetooth pairing (2026-11-15): the speaker's own menu (ui:/bluetooth) offers this action; the B&W app's
# "Pair new device" was seen to flip exactly bluetooth:state, and one user-approved test of
# POST /api/setData {"path": BT_PAIRING_ACTION, "role": "activate", "value": {}} made the speaker visible within 0.5 s.
# Fixed paths only. What a second activation does while visible is NOT verified, so it is never sent then.
BT_STATE = Control("bluetooth:state", "bluetoothState")
BT_PAIRING_ACTION = "bluetooth:deviceList/discoverable"
BT_CONFIRM_S = 3.0  # how long to wait for the speaker to report that it became visible
BT_PAIRING_TIMEOUT = Control("settings:/bluetooth/bluetoothPairingTimeout", "i32_")  # read only (300 s seen)
# Paired devices, as the speaker's own menu lists them (ui:/bluetooth): a header row per section, then one container per
# device "bluetooth:devices/<address>/sectionN". section1 = "Inputs", section2 = "Speakers" (both paired);
# section3 = "New devices" (seen nearby, NOT paired) is ignored. Unpair = the device container's own "Unpair" action
# row, used exactly as the speaker lists it; verified 2026-11-16 (one user-approved unpair: the device left the menu).
BT_MENU = "ui:/bluetooth"
BT_PAIRED_SECTIONS = {"section1": "input", "section2": "speaker"}
_BT_DEVICE = re.compile(r"^bluetooth:devices/([0-9A-Za-z_:]{1,40})/(section\d+)$")
BT_UNPAIR_CONFIRM_S = 3.0
# Standby timeout: the value the speaker's own menu shows as "Standby Timeout" (ui:/settings/powerManagement/idleTime).
# A write is accepted only if it is one of the options the speaker lists under its enumPath, read fresh each time.
# Verified 2026-11-16: 1200 -> 1800 written and read back, then restored to 1200.
STANDBY = Control("settings:/system/maxIdleTime", "i32_")
STANDBY_OPTIONS = "settings:/system/maxIdleTimeValues"
# Audio sources: the speaker's own "B&W Audio Sources" menu. Read only (switching is not verified).
SOURCES_MENU = "ui:/bw"
ROW_ROLES = "title,value,path,type,disabled"  # getRows then returns each row as a list in exactly this order

# 5-band equalizer: write + read-back verified (2026-11-15); the speaker sends each band's own min/max/step, which are
# the only limits used. Written as the whole band list, keeping every field the speaker sent, with only "value" changed.
EQ = Control("settings:/mediaPlayer/equalizer", "eqBandList")
# Source gain: READ ONLY. The speaker rejects writes ("Setting is not modifiable"), so there is no write path for it at
# all - it is deliberately in neither CONTROLS nor LAB. Units are not verified, so none are shown.
SOURCE_GAIN = Control("settings:/mediaPlayer/sourceGain", "sourceGainList")
EQ_ENABLED = LAB["eq_enabled"]
RGB_KEYS = ("red", "green", "blue")

# Validation ranges for writes. Volume is in the speaker's own units: player:volume declares edit {min 0, max 50, step 1}
# and volumeMap has 51 entries (-120..0 dB); values above 50 are rejected by the speaker. The UI shows the same 0..50.
# Bass and treble: both nodes declare edit {min -10, max 10, step 0.5, slider} (double_, dB). Treble 7 was written and
# read back, and 11 came back clamped to 10 (user test); whether values beyond 6 change the sound is not verified yet.
# The bass range rests on the metadata alone. The 5 EQ bands keep their own -6..+6 (declared per band).
VOLUME_MIN, VOLUME_MAX = 0, 50
TREBLE_MIN, TREBLE_MAX = -10.0, 10.0
BASS_MIN, BASS_MAX = -10.0, 10.0
TONE_STEP = 0.5
# The speaker stores ANY brightness (101 was stored as sent); 0..100 chosen by the user as a percentage.
BRIGHTNESS_MIN, BRIGHTNESS_MAX = 0, 100

TONE_RANGE = {"bass": (BASS_MIN, BASS_MAX), "treble": (TREBLE_MIN, TREBLE_MAX)}


class SpeakerError(Exception):
    def __init__(self, code: ErrorCode, message: str, http: int):
        super().__init__(message)
        self.code, self.message, self.http = code, message, http


def _error_in(body: Any) -> str | None:
    """The speaker's error text if the body is (or contains) an error object, else None."""
    items = body if isinstance(body, list) else [body]
    for it in items:
        if isinstance(it, dict) and "error" in it:
            e = it["error"]
            if isinstance(e, dict):
                return str(e.get("message") or e.get("name") or e)[:120]
            return str(e)[:120]
    return None


def _typed(control: Control, value: Any) -> dict:
    return {"type": control.type, control.type: value}


def _unwrap(control: Control, body: Any) -> Any:
    """[{"type": T, T: v}] -> v, strictly checking the type tag and the Python type."""
    if isinstance(body, list) and len(body) == 1:
        body = body[0]
    if not isinstance(body, dict) or body.get("type") != control.type or control.type not in body:
        raise SpeakerError(ErrorCode.UNSUPPORTED, "הרמקול החזיר תשובה בפורמט לא צפוי.", 502)
    v = body[control.type]
    if control.type == "eqBandList":
        return _eq_bands(v)
    if control.type == "sourceGainList":
        return _gains(v)
    if control.type == "formationDownlightRgb":
        if not isinstance(v, dict) or not all(isinstance(v.get(k), int) and not isinstance(v.get(k), bool) for k in RGB_KEYS):
            raise SpeakerError(ErrorCode.UNSUPPORTED, "הרמקול החזיר צבע בפורמט לא צפוי.", 502)
        return {k: v[k] for k in RGB_KEYS}
    ok = {
        "bool_": isinstance(v, bool),
        "i32_": isinstance(v, int) and not isinstance(v, bool),
        "double_": isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v),
    }[control.type]
    if not ok:
        raise SpeakerError(ErrorCode.UNSUPPORTED, "הרמקול החזיר ערך מסוג לא צפוי.", 502)
    return float(v) if control.type == "double_" else v


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _eq_bands(v: Any) -> list[dict]:
    """Validate the speaker's band list; returns copies of the band objects with every field kept."""
    if not isinstance(v, list) or not v:
        raise SpeakerError(ErrorCode.UNSUPPORTED, "הרמקול החזיר אקולייזר בפורמט לא צפוי.", 502)
    out = []
    for b in v:
        ok = (isinstance(b, dict) and isinstance(b.get("band"), str) and all(_num(b.get(k)) for k in ("min", "max", "step", "value"))
              and b["step"] > 0 and b["min"] <= b["max"])
        if not ok:
            raise SpeakerError(ErrorCode.UNSUPPORTED, "הרמקול החזיר תחום אקולייזר בפורמט לא צפוי.", 502)
        out.append(dict(b))
    if len({b["band"] for b in out}) != len(out):
        raise SpeakerError(ErrorCode.UNSUPPORTED, "הרמקול החזיר תחומי אקולייזר כפולים.", 502)
    return out


def _gains(v: Any) -> list[dict]:
    """[{name, value, min, max}] from the speaker's source gain list (only what the display needs)."""
    if not isinstance(v, list):
        raise SpeakerError(ErrorCode.UNSUPPORTED, "הרמקול החזיר Source Gain בפורמט לא צפוי.", 502)
    out = []
    for g in v:
        if not (isinstance(g, dict) and isinstance(g.get("name"), str) and all(_num(g.get(k)) for k in ("value", "min", "max"))):
            raise SpeakerError(ErrorCode.UNSUPPORTED, "הרמקול החזיר Source Gain בפורמט לא צפוי.", 502)
        out.append({"name": g["name"], "value": g["value"], "min": g["min"], "max": g["max"]})
    return out


# Power state, read only. With network standby the speaker keeps answering on the network while "off", so
# "reachable" alone cannot tell on from off. Seen on the real speaker: {"powerTarget": {"target": "networkStandby",
# "reason": "idleTimer", ...}, "type": "powerTarget"}; "online" when playing / awake.
POWER_PATH = "powermanager:target"
# Restart: the speaker's own action node (getData roles=@all -> {"type": "action", "path": "powermanager:goReboot"},
# found 2026-11-20). It also publishes settings:/ui/disabledReboot (false) for its own reboot button; when true, nothing
# is sent. Expected to equal a short press of the small reset button on the speaker, which on 2026-11-20 restarted it
# and kept pairings and settings. There is no read-back for a restart: success = it stopped answering, then answered.
REBOOT_ACTION = "powermanager:goReboot"
REBOOT_DISABLED = Control("settings:/ui/disabledReboot", "bool_")
REBOOT_DOWN_S = 20.0    # it must stop answering within this, or the restart did not happen
REBOOT_BACK_S = 180.0   # then it must answer again within this
REBOOT_POLL_S, REBOOT_BACK_POLL_S = 0.5, 3.0  # how often it is asked meanwhile (tests shorten these)
_WORD = re.compile(r"^[A-Za-z]{1,32}$")


def _power(body: Any) -> tuple[str | None, str | None]:
    """(target, reason) from a powerTarget reply; None for anything not in the expected shape."""
    v = body[0] if isinstance(body, list) and body else body
    t = v.get("powerTarget") if isinstance(v, dict) else None
    if not isinstance(t, dict):
        return None, None
    word = lambda x: x if isinstance(x, str) and _WORD.match(x) else None  # noqa: E731
    return word(t.get("target")), word(t.get("reason"))


def on_step(value: float, lo: float, hi: float, step: float) -> bool:
    """value is inside [lo, hi] and lands on lo + k*step (with float tolerance)."""
    if not (lo - 1e-9 <= value <= hi + 1e-9):
        return False
    k = (value - lo) / step
    return abs(k - round(k)) < 1e-6


def _same(control: Control, a: Any, b: Any) -> bool:
    if control.type == "eqBandList":
        return (isinstance(a, list) and isinstance(b, list) and len(a) == len(b)
                and all(x["band"] == y["band"] and abs(x["value"] - y["value"]) < 0.01 for x, y in zip(a, b)))
    return abs(a - b) < 0.01 if control.type == "double_" else a == b


def _encode(control: Control, value: Any) -> str:
    return json.dumps(_typed(control, value), separators=(",", ":"))


class ZeppelinClient:
    def __init__(self, host: str = DEFAULT_HOST, transport: httpx.AsyncBaseTransport | None = None):
        self.host = host
        self._http = httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport, follow_redirects=False)
        self._lock = asyncio.Lock()  # one request at a time: a write and its read-back never interleave with others
        self._id_key = secrets.token_bytes(16)  # opaque device ids: the Bluetooth address never leaves the server

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _call(self, endpoint: str, params: dict[str, str]) -> Any:
        url = f"http://{self.host}/api/{endpoint}"
        try:
            r = await self._http.get(url, params=params)
        except httpx.TimeoutException:
            raise SpeakerError(ErrorCode.TIMEOUT, "הרמקול לא הגיב בזמן.", 504) from None
        except httpx.HTTPError:
            raise SpeakerError(ErrorCode.NOT_CONNECTED, f"אין חיבור לרמקול בכתובת {self.host}.", 503) from None
        try:
            body = r.json() if r.content else None
        except ValueError:
            body = None
        if (msg := _error_in(body)) is not None:
            raise SpeakerError(ErrorCode.DENIED, f"הרמקול החזיר שגיאה: {msg}", 502)
        if r.status_code != 200:
            raise SpeakerError(ErrorCode.DENIED, f"הרמקול החזיר קוד {r.status_code}.", 502)
        return body

    async def _activate(self, path: str) -> None:
        """Invoke an action node, in the exact form that was verified: POST JSON (encoded by httpx), empty value."""
        url = f"http://{self.host}/api/setData"
        try:
            r = await self._http.post(url, json={"path": path, "role": "activate", "value": {}})
        except httpx.TimeoutException:
            raise SpeakerError(ErrorCode.TIMEOUT, "הרמקול לא הגיב בזמן.", 504) from None
        except httpx.HTTPError:
            raise SpeakerError(ErrorCode.NOT_CONNECTED, f"אין חיבור לרמקול בכתובת {self.host}.", 503) from None
        try:
            body = r.json() if r.content else None
        except ValueError:
            body = None
        if (msg := _error_in(body)) is not None:
            raise SpeakerError(ErrorCode.DENIED, f"הרמקול החזיר שגיאה: {msg}", 502)
        if r.status_code != 200:
            raise SpeakerError(ErrorCode.DENIED, f"הרמקול החזיר קוד {r.status_code}.", 502)

    async def _read(self, control: Control) -> Any:
        return _unwrap(control, await self._call("getData", {"path": control.path, "roles": "value"}))

    async def read(self, name: str) -> Any:
        async with self._lock:
            return await self._read(CONTROLS[name])

    async def state(self) -> dict:
        """Every control, read independently: one failing path does not hide the others."""
        out: dict[str, Any] = {"host": self.host, "reachable": False, "errors": {}}
        for name in CONTROLS:
            try:
                out[name] = await self.read(name)
                out["reachable"] = True
            except SpeakerError as e:
                out[name] = None
                out["errors"][name] = e.message
                if e.code in (ErrorCode.NOT_CONNECTED, ErrorCode.TIMEOUT) and not out["reachable"]:
                    # nothing answered at all: do not wait for the same timeout on every other path
                    for rest in CONTROLS:
                        if rest not in out:
                            out[rest] = None
                    break
        out["power"], out["power_reason"] = None, None
        if out["reachable"]:
            try:
                async with self._lock:
                    out["power"], out["power_reason"] = _power(await self._call("getData", {"path": POWER_PATH, "roles": "value"}))
            except SpeakerError as e:
                out["errors"]["power"] = e.message
        return out

    async def _set_and_read(self, control: Control, value: Any) -> Any:
        """setData, then the value the speaker reports (one retry: some settings apply a moment later). Lock held."""
        await self._call("setData", {"path": control.path, "role": "value", "value": _encode(control, value)})
        now = await self._read(control)
        if not _same(control, now, value):
            await asyncio.sleep(READBACK_RETRY_S)
            now = await self._read(control)
        return now

    async def write(self, name: str, value: Any) -> Any:
        """Write one verified control, then read it back. Returns the value the speaker now reports."""
        control = CONTROLS[name]
        if name in TONE_RANGE and not (isinstance(value, (int, float)) and not isinstance(value, bool)
                                       and on_step(float(value), *TONE_RANGE[name], TONE_STEP)):
            lo, hi = TONE_RANGE[name]
            raise SpeakerError(ErrorCode.INVALID_COMMAND, f"ערך לא תקין: {value} (מותר {lo:g} עד {hi:g} בצעד {TONE_STEP:g}).", 422)
        async with self._lock:
            now = await self._set_and_read(control, value)
        if not _same(control, now, value):
            raise SpeakerError(ErrorCode.DENIED, f"הרמקול קיבל את הבקשה, אבל הערך לא השתנה (מדווח: {now}).", 502)
        return now

    # ---- Bluetooth pairing
    async def _bt(self) -> dict:
        body = await self._call("getData", {"path": BT_STATE.path, "roles": "value"})
        if isinstance(body, list) and len(body) == 1:
            body = body[0]
        st = body.get(BT_STATE.type) if isinstance(body, dict) and body.get("type") == BT_STATE.type else None
        if not isinstance(st, dict) or not isinstance(st.get("discoverable"), bool):
            raise SpeakerError(ErrorCode.UNSUPPORTED, "הרמקול החזיר מצב Bluetooth בפורמט לא צפוי.", 502)
        dev = st.get("connectedDevice") if st.get("connected") is True else None
        return {"name": str(st.get("name") or ""), "discoverable": st["discoverable"], "pairable": st.get("pairable") is True,
                "connected_device": str(dev.get("name") or "") if isinstance(dev, dict) else None,
                "paired": [str(d.get("name") or "") for d in st.get("pairedDevices") or [] if isinstance(d, dict)]}

    def _dev_id(self, address: str) -> str:
        return hmac.new(self._id_key, address.encode(), hashlib.sha256).hexdigest()[:12]

    async def _bt_devices(self) -> list[dict]:
        """Paired devices from the speaker's menu: [{id, name, roles, _address, _container}] (underscored = server only)."""
        out: dict[str, dict] = {}
        for title, _value, path, kind, _disabled in await self._rows(BT_MENU):
            m = _BT_DEVICE.match(path) if kind == "container" and isinstance(path, str) else None
            role = BT_PAIRED_SECTIONS.get(m.group(2)) if m else None
            if not role:
                continue
            d = out.setdefault(m.group(1), {"id": self._dev_id(m.group(1)), "name": str(title or ""), "roles": [],
                                            "_address": m.group(1), "_container": path})
            if role not in d["roles"]:
                d["roles"].append(role)
        return list(out.values())

    async def _bt_full(self) -> dict:
        """Bluetooth state plus the paired list and pairing window; the extras are optional (None when unreadable)."""
        st = await self._bt()
        try:
            st["devices"] = [{k: v for k, v in d.items() if not k.startswith("_")} for d in await self._bt_devices()]
        except SpeakerError:
            st["devices"] = None
        try:
            t = await self._read(BT_PAIRING_TIMEOUT)
            st["pairing_seconds"] = t if isinstance(t, int) and not isinstance(t, bool) and 0 < t <= 3600 else None
        except SpeakerError:
            st["pairing_seconds"] = None
        return st

    async def bluetooth(self) -> dict:
        async with self._lock:
            return await self._bt_full()

    async def unpair(self, device_id: str) -> dict:
        """Unpair one paired device, by its opaque id from the list just read. Success only once the device is gone from
        the speaker's paired sections. Returns the Bluetooth state afterwards plus the name that was unpaired."""
        async with self._lock:
            dev = next((d for d in await self._bt_devices() if d["id"] == device_id), None)
            if dev is None:
                raise SpeakerError(ErrorCode.INVALID_COMMAND, "המכשיר לא נמצא ברשימת המצומדים של הרמקול. רענן ונסה שוב.", 404)
            prefix = f"bluetooth:devices/{dev['_address']}/"
            acts = [r for r in await self._rows(dev["_container"])
                    if r[3] == "action" and r[2] == prefix + "unpair" and r[4] is not True]
            if len(acts) != 1:
                raise SpeakerError(ErrorCode.UNSUPPORTED, "הרמקול לא מציע ביטול צימוד למכשיר הזה.", 502)
            await self._activate(acts[0][2])
            waited = 0.0
            while True:
                gone = all(d["id"] != device_id for d in await self._bt_devices())
                if gone or waited >= BT_UNPAIR_CONFIRM_S:
                    break
                await asyncio.sleep(0.5)
                waited += 0.5
            if not gone:
                raise SpeakerError(ErrorCode.DENIED, "הרמקול קיבל את הבקשה, אבל המכשיר עדיין מופיע כמצומד.", 502)
            return {**await self._bt_full(), "unpaired": dev["name"]}

    async def open_pairing(self) -> dict:
        """Make the speaker visible for pairing. Already visible: nothing is sent (a second activation is not verified).
        Success only once the speaker itself reports discoverable=true. Returns the state plus whether it was sent."""
        async with self._lock:
            before = await self._bt()
            if before["discoverable"]:
                return {**await self._bt_full(), "sent": False}
            await self._activate(BT_PAIRING_ACTION)
            waited = 0.0
            while True:
                now = await self._bt()
                if now["discoverable"] or waited >= BT_CONFIRM_S:
                    break
                await asyncio.sleep(0.5)
                waited += 0.5
            if now["discoverable"]:
                now = await self._bt_full()
        if not now["discoverable"]:
            raise SpeakerError(ErrorCode.DENIED, "הרמקול קיבל את הבקשה, אבל לא דיווח שנכנס למצב צימוד.", 502)
        return {**now, "sent": True}

    # ---- restart
    async def _answers(self) -> bool:
        """True if the speaker answers at all (an error reply is still an answer). Lock held."""
        try:
            await self._call("getData", {"path": POWER_PATH, "roles": "value"})
        except SpeakerError as e:
            return e.code not in (ErrorCode.NOT_CONNECTED, ErrorCode.TIMEOUT)
        return True

    async def reboot(self) -> None:
        """Restart the speaker. Returns only once it has stopped answering (the restart began); raises otherwise."""
        async with self._lock:
            if await self._read(REBOOT_DISABLED):
                raise SpeakerError(ErrorCode.DENIED, "הרמקול לא מאפשר כרגע הפעלה מחדש.", 409)
            try:
                await self._activate(REBOOT_ACTION)
            except SpeakerError as e:
                if e.code not in (ErrorCode.NOT_CONNECTED, ErrorCode.TIMEOUT):
                    raise  # a refusal inside the reply: nothing restarts
                # it may drop the connection while going down: decided below by whether it still answers
            waited = 0.0
            while waited < REBOOT_DOWN_S:
                if not await self._answers():
                    return
                await asyncio.sleep(REBOOT_POLL_S)
                waited += REBOOT_POLL_S
        raise SpeakerError(ErrorCode.DENIED, "הרמקול קיבל את הבקשה, אבל לא הופעל מחדש.", 502)

    async def wait_back(self) -> bool:
        """After reboot(): True as soon as the speaker answers again, False if it did not within REBOOT_BACK_S."""
        waited = 0.0
        while waited < REBOOT_BACK_S:
            await asyncio.sleep(REBOOT_BACK_POLL_S)
            waited += REBOOT_BACK_POLL_S
            async with self._lock:
                if await self._answers():
                    return True
        return False

    # ---- lists the speaker publishes (getRows; read only)
    async def _rows(self, path: str) -> list[list]:
        out: list[list] = []
        while True:
            body = await self._call("getRows", {"path": path, "roles": ROW_ROLES, "from": str(len(out)), "to": str(len(out) + 49)})
            rows = body.get("rows") if isinstance(body, dict) else None
            total = body.get("rowsCount") if isinstance(body, dict) else None
            if not isinstance(rows, list) or not isinstance(total, int) or not all(isinstance(r, list) and len(r) == 5 for r in rows):
                raise SpeakerError(ErrorCode.UNSUPPORTED, "הרמקול החזיר רשימה בפורמט לא צפוי.", 502)
            out.extend(rows)
            if not rows or len(out) >= total:
                return out

    async def _standby_options(self) -> list[dict]:
        opts = []
        for title, value, _path, kind, _disabled in await self._rows(STANDBY_OPTIONS):
            if kind == "value" and isinstance(value, dict) and value.get("type") == "i32_":
                sec = value.get("i32_")
                if isinstance(sec, int) and not isinstance(sec, bool) and sec >= 0:
                    opts.append({"seconds": sec, "title": str(title or "")})
        if not opts:
            raise SpeakerError(ErrorCode.UNSUPPORTED, "הרמקול לא החזיר את רשימת זמני הכיבוי.", 502)
        return opts

    async def standby(self) -> dict:
        async with self._lock:
            return {"seconds": await self._read(STANDBY), "options": await self._standby_options()}

    async def write_standby(self, seconds: int) -> dict:
        """Only an option the speaker itself lists right now; then read back like every other write."""
        async with self._lock:
            options = await self._standby_options()
            if seconds not in {o["seconds"] for o in options}:
                raise SpeakerError(ErrorCode.INVALID_COMMAND, "יש לבחור זמן כיבוי מתוך הרשימה שהרמקול מציג.", 422)
            now = await self._set_and_read(STANDBY, seconds)
        if now != seconds:
            raise SpeakerError(ErrorCode.DENIED, f"הרמקול קיבל את הבקשה, אבל הערך לא השתנה (מדווח: {now}).", 502)
        return {"seconds": now, "options": options}

    async def sources(self) -> list[dict]:
        """The speaker's source list with its own flags. Device names/addresses inside the value are not passed on."""
        async with self._lock:
            rows = await self._rows(SOURCES_MENU)
        out = []
        for title, value, path, kind, disabled in rows:
            inp = value.get("bwAudioInput") if isinstance(value, dict) and value.get("type") == "bwAudioInput" else None
            if kind != "action" or not isinstance(path, str) or not path.startswith("bw:") or not isinstance(inp, dict):
                continue
            out.append({"id": path[3:], "title": str(title or path[3:]), "active": inp.get("active") is True,
                        "plugged": inp.get("plugged") is True, "available": disabled is not True})
        return out

    # ---- 5-band equalizer
    async def read_eq(self) -> list[dict]:
        async with self._lock:
            return await self._read(EQ)

    async def read_eq_enabled(self) -> bool:
        async with self._lock:
            return await self._read(EQ_ENABLED)

    async def read_source_gain(self) -> list[dict]:
        """Read only. There is intentionally no write counterpart."""
        async with self._lock:
            return await self._read(SOURCE_GAIN)

    async def write_eq(self, values: dict[str, float]) -> list[dict]:
        """Set all bands at once. `values` must name exactly the speaker's bands; each value is checked against that
        band's own min/max/step as the speaker reports them. Returns the band list the speaker reports afterwards."""
        async with self._lock:
            current = await self._read(EQ)
            if sorted(values) != sorted(b["band"] for b in current):
                raise SpeakerError(ErrorCode.INVALID_COMMAND, "התחומים שנשלחו לא תואמים את התחומים של הרמקול.", 422)
            wanted = []
            for b in current:
                v = values[b["band"]]
                if not on_step(v, b["min"], b["max"], b["step"]):
                    raise SpeakerError(ErrorCode.INVALID_COMMAND,
                                       f"ערך {v:g} לא תקין לתחום {b['band']} (טווח {b['min']:g}…{b['max']:g}, צעד {b['step']:g}).", 422)
                wanted.append({**b, "value": int(v) if float(v).is_integer() else v})  # every other field as the speaker sent it
            now = await self._set_and_read(EQ, wanted)
        if not _same(EQ, now, wanted):
            got = ", ".join(f"{b['band']}={b['value']:g}" for b in now)
            raise SpeakerError(ErrorCode.DENIED, f"הרמקול קיבל את הבקשה, אבל הערכים לא תואמים ({got}).", 502)
        return now

    # ---- test lab (unverified controls). Callers must have saved the originals first (enforced in the API layer).
    async def lab_read(self) -> tuple[dict[str, Any], dict[str, str]]:
        """(values, errors) for every lab control; an unreadable one is None with its error."""
        values: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for name, control in LAB.items():
            try:
                async with self._lock:
                    values[name] = await self._read(control)
            except SpeakerError as e:
                if e.code in (ErrorCode.NOT_CONNECTED, ErrorCode.TIMEOUT):
                    raise
                values[name], errors[name] = None, e.message
        return values, errors

    async def probe(self, name: str, value: Any) -> dict:
        """One test write. Never claims the effect worked: it reports what was sent, what the speaker said and what it
        now reports. A speaker error (even inside HTTP 200) is a result here, not an exception; a dead link still raises."""
        control = LAB[name]
        async with self._lock:
            before = await self._read(control)
            try:
                after = await self._set_and_read(control, value)
            except SpeakerError as e:
                if e.code in (ErrorCode.NOT_CONNECTED, ErrorCode.TIMEOUT):
                    raise
                try:
                    after = await self._read(control)
                except SpeakerError:
                    after = None
                return {"control": name, "sent": value, "before": before, "after": after, "speaker_error": e.message, "stored": False}
        return {"control": name, "sent": value, "before": before, "after": after, "speaker_error": None,
                "stored": _same(control, after, value)}

    async def restore(self, originals: dict[str, Any]) -> dict[str, dict]:
        """Write the saved originals back. Per control: {"ok": bool, "now": value, "error": str | None}."""
        out: dict[str, dict] = {}
        for name, value in originals.items():
            control = LAB[name]
            try:
                async with self._lock:
                    now = await self._set_and_read(control, value)
                out[name] = {"ok": _same(control, now, value), "now": now, "error": None}
            except SpeakerError as e:
                out[name] = {"ok": False, "now": None, "error": e.message}
        return out
