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
import json
import math
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

# 5-band equalizer: write + read-back verified (2026-11-15); the speaker sends each band's own min/max/step, which are
# the only limits used. Written as the whole band list, keeping every field the speaker sent, with only "value" changed.
EQ = Control("settings:/mediaPlayer/equalizer", "eqBandList")
# Source gain: READ ONLY. The speaker rejects writes ("Setting is not modifiable"), so there is no write path for it at
# all - it is deliberately in neither CONTROLS nor LAB. Units are not verified, so none are shown.
SOURCE_GAIN = Control("settings:/mediaPlayer/sourceGain", "sourceGainList")
EQ_ENABLED = LAB["eq_enabled"]
RGB_KEYS = ("red", "green", "blue")

# Validation ranges for writes. Volume 0..100 and treble -6..+6 match the B&W app's sliders; on the speaker itself
# only volume 23/28 and treble 5/6 have been verified so far.
VOLUME_MIN, VOLUME_MAX = 0, 100
TREBLE_MIN, TREBLE_MAX = -6.0, 6.0
# The speaker stores ANY value (bass -7/7 and brightness 101 were stored as sent), so it cannot tell us its range.
# Chosen by the user: bass like treble in the B&W app, brightness as a percentage. Every edge was stored by the speaker;
# whether values beyond them have an effect was not tested.
BASS_MIN, BASS_MAX = -6.0, 6.0
BRIGHTNESS_MIN, BRIGHTNESS_MAX = 0, 100


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
        async with self._lock:
            now = await self._set_and_read(control, value)
        if not _same(control, now, value):
            raise SpeakerError(ErrorCode.DENIED, f"הרמקול קיבל את הבקשה, אבל הערך לא השתנה (מדווח: {now}).", 502)
        return now

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
