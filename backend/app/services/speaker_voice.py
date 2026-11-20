"""Speaker steps for voice commands and schedules.

A small, closed vocabulary over the speaker's verified controls only (the same ones its own screen writes).
Every step is validated here twice: when it is parsed/scheduled (`check_speaker`) and again when it runs.
Relative steps ("louder", "more bass") read the current value at run time, clamp to the declared range, and every
write goes through `ZeppelinClient.write`, which reads the value back: no success unless the speaker reports it.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

VOLUME_MAX = 50          # player:volume declares 0..50
TONE_MAX = 10            # bass / treble: -10..+10 dB
VOLUME_STEP, TONE_STEP_DB = 3, 2

# Named colours a sentence may ask for. Nothing else: the model or the user cannot pass a raw RGB through here.
COLORS: dict[str, tuple[int, int, int]] = {
    "אדום": (255, 0, 0), "ירוק": (0, 255, 0), "כחול": (0, 0, 255), "לבן": (255, 255, 255),
    "צהוב": (255, 200, 0), "כתום": (255, 100, 0), "סגול": (150, 0, 255), "ורוד": (255, 40, 140),
    "תכלת": (0, 180, 255), "טורקיז": (0, 220, 180),
}


class SpeakerOp(StrEnum):
    VOLUME = "speaker_volume"          # {value: 0..50} or {delta: -20..20}
    MUTE = "speaker_mute"              # {enabled}
    BASS = "speaker_bass"              # {value: -10..10} or {delta: -10..10}
    TREBLE = "speaker_treble"          # same
    LIGHT = "speaker_light"            # {enabled}
    BRIGHTNESS = "speaker_brightness"  # {value: 0..100}
    COLOR = "speaker_color"            # {color: a name from COLORS}
    CYCLE = "speaker_cycle"            # {enabled}
    PROFILE = "speaker_profile"        # {id}


def _int(v: Any, lo: int, hi: int) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def check_speaker(op: SpeakerOp, p: dict) -> None:
    """Exact keys and ranges per op. Raises ValueError."""
    keys = set(p)
    if op in (SpeakerOp.VOLUME, SpeakerOp.BASS, SpeakerOp.TREBLE):
        hi = VOLUME_MAX if op is SpeakerOp.VOLUME else TONE_MAX
        lo = 0 if op is SpeakerOp.VOLUME else -TONE_MAX
        dmax = 20 if op is SpeakerOp.VOLUME else 2 * TONE_MAX
        if keys == {"value"} and _int(p["value"], lo, hi):
            return
        if keys == {"delta"} and _int(p["delta"], -dmax, dmax) and p["delta"] != 0:
            return
        raise ValueError(f"{op.value} requires value {lo}..{hi} or a non-zero delta")
    if op in (SpeakerOp.MUTE, SpeakerOp.LIGHT, SpeakerOp.CYCLE):
        if keys == {"enabled"} and isinstance(p["enabled"], bool):
            return
        raise ValueError(f"{op.value} requires enabled")
    if op is SpeakerOp.BRIGHTNESS:
        if keys == {"value"} and _int(p["value"], 0, 100):
            return
        raise ValueError("speaker_brightness requires value 0..100")
    if op is SpeakerOp.COLOR:
        if keys == {"color"} and p["color"] in COLORS:
            return
        raise ValueError("speaker_color requires a known colour")
    if op is SpeakerOp.PROFILE:
        if keys == {"id"} and isinstance(p["id"], str) and 1 <= len(p["id"]) <= 64 and p["id"].isalnum():
            return
        raise ValueError("speaker_profile requires id")


def _signed(v: int) -> str:
    return f"+{v}" if v > 0 else str(v)


def label(op: SpeakerOp, p: dict, profile_name: str | None = None) -> str:
    if op is SpeakerOp.VOLUME:
        return f"רמקול: עוצמה {p['value']}" if "value" in p else \
            f"רמקול: {'הגברה' if p['delta'] > 0 else 'הנמכה'} ({_signed(p['delta'])})"
    if op in (SpeakerOp.BASS, SpeakerOp.TREBLE):
        what = "באס" if op is SpeakerOp.BASS else "גבוהים"
        return f"רמקול: {what} {p['value']}" if "value" in p else f"רמקול: {what} {_signed(p['delta'])}"
    return {
        SpeakerOp.MUTE: "רמקול: השתקה" if p.get("enabled") else "רמקול: ביטול השתקה",
        SpeakerOp.LIGHT: "רמקול: הדלקת תאורה" if p.get("enabled") else "רמקול: כיבוי תאורה",
        SpeakerOp.BRIGHTNESS: f"רמקול: בהירות {p.get('value')}",
        SpeakerOp.COLOR: f"רמקול: תאורה בצבע {p.get('color')}",
        SpeakerOp.CYCLE: "רמקול: הפעלת החלפת צבעים" if p.get("enabled") else "רמקול: עצירת החלפת צבעים",
        SpeakerOp.PROFILE: f"רמקול: טעינת פרופיל {profile_name or ''}".rstrip(),
    }[op]


def _err(code: str, msg: str, http: int):
    # lazy: schemas imports this module for its validation, so nothing app-level is imported at the top
    from app.models.schemas import ErrorCode
    from app.services.zeppelin import SpeakerError
    return SpeakerError(ErrorCode(code), msg, http)


async def run_step(speaker: Any, cycle: Any, profiles: Any, op: SpeakerOp | str, params: dict) -> str:
    """Execute one validated step. Returns a short Hebrew result. Raises SpeakerError on any failure."""
    op = SpeakerOp(op)
    check_speaker(op, params)
    if profiles.busy:
        raise _err("DENIED", "טעינת פרופיל בתהליך. נסה שוב בעוד רגע.", 409)
    if op in (SpeakerOp.VOLUME, SpeakerOp.BASS, SpeakerOp.TREBLE):
        name = {SpeakerOp.VOLUME: "volume", SpeakerOp.BASS: "bass", SpeakerOp.TREBLE: "treble"}[op]
        lo, hi = (0, VOLUME_MAX) if op is SpeakerOp.VOLUME else (-TONE_MAX, TONE_MAX)
        if "value" in params:
            target = params["value"]
        else:
            cur = await speaker.read(name)
            if not isinstance(cur, (int, float)) or isinstance(cur, bool):
                raise _err("UNSUPPORTED", "לא ניתן לקרוא את הערך הנוכחי של הרמקול.", 502)
            target = min(hi, max(lo, cur + params["delta"]))
        value = int(target) if op is SpeakerOp.VOLUME else float(target)
        now = await speaker.write(name, value)
        return f"{label(op, params)} → {now:g}"
    if op is SpeakerOp.MUTE:
        await speaker.write("mute", params["enabled"])
    elif op is SpeakerOp.LIGHT:
        if not params["enabled"]:
            await cycle.stop_if_running("התאורה כובתה")
        await speaker.write("light", params["enabled"])
    elif op is SpeakerOp.BRIGHTNESS:
        await speaker.write("brightness", params["value"])
    elif op is SpeakerOp.COLOR:
        r, g, b = COLORS[params["color"]]
        await cycle.stop_if_running("נבחר צבע ידני")
        await speaker.write("rgb", {"red": r, "green": g, "blue": b})
    elif op is SpeakerOp.CYCLE:
        if params["enabled"]:
            await cycle.start()
        else:
            await cycle.stop()
    elif op is SpeakerOp.PROFILE:
        p = profiles.profiles.get(params["id"])
        if p is None:
            raise _err("INVALID_COMMAND", "הפרופיל לא נמצא.", 404)
        out = await profiles.load(params["id"])
        if out["status"] != "full":
            failed = ", ".join(s["label"] for s in out["steps"] if not s["ok"])
            raise _err("DENIED", f"הפרופיל {p['name']} נטען חלקית. נכשל: {failed}.", 502)
        return label(op, params, p["name"])
    return label(op, params)
