"""Automatic ambient-light colour cycling for the B&W Zeppelin, run on the server so it continues with the browser closed.

Rules (each one tested):
- Started only by an explicit request, never at server start. One cycle per speaker: starting twice keeps one task.
- Each step is one ordinary verified colour write (settings:/ui/ambientLightRgb) through the speaker client, whose lock
  serialises it with every other write: no competing writes. Brightness is never written.
- Colours change in one jump, or - with "smooth" - through a few intermediate colours written by the server itself
  along the hue wheel (vivid, no grey middle). The speaker's own fade is not used: it has not been tested.
- A manual colour, turning the light off, or shutting the server down stops the cycle. Stopping keeps the last colour.
- If the speaker stops answering, the cycle stops and says so. No retries, and no catching up on missed colours: the
  next step is always scheduled from "now", never from a backlog.
"""
from __future__ import annotations

import asyncio
import colorsys
import json
import random
import time
from typing import Any, Awaitable, Callable

from app.models.schemas import ErrorCode
from app.services.zeppelin import SpeakerError

DEFAULTS: dict[str, Any] = {
    "interval_s": 10,
    "mode": "palette",  # "palette" (user-defined) | "random"
    "smooth": False,  # gradual transition through intermediate colours
    "palette": [
        {"red": 255, "green": 6, "blue": 126},
        {"red": 120, "green": 80, "blue": 255},
        {"red": 34, "green": 211, "blue": 197},
        {"red": 255, "green": 170, "blue": 90},
    ],
}
INTERVAL_MIN_S, INTERVAL_MAX_S = 3, 3600  # app limits so the speaker is never flooded (not a speaker range)
FADE_STEP_S = 0.35   # time between intermediate colours
FADE_MAX_S = 3.0     # a transition never takes longer than this, nor more than half the interval


def fade_duration(interval_s: float) -> float:
    return min(FADE_MAX_S, interval_s / 2)


def blend(a: dict, b: dict, t: float) -> dict:
    """Colour t of the way from a to b, moving around the hue wheel the short way (saturation/value linear).
    A colour without hue (white/grey/black) takes the other one's hue, so white -> red does not pass through cyan."""
    ha, sa, va = colorsys.rgb_to_hsv(a["red"] / 255, a["green"] / 255, a["blue"] / 255)
    hb, sb, vb = colorsys.rgb_to_hsv(b["red"] / 255, b["green"] / 255, b["blue"] / 255)
    if sa < 0.05:
        ha = hb
    if sb < 0.05:
        hb = ha
    dh = ((hb - ha + 0.5) % 1.0) - 0.5  # shortest way round
    r, g, bl = colorsys.hsv_to_rgb((ha + dh * t) % 1.0, sa + (sb - sa) * t, va + (vb - va) * t)
    return {"red": round(r * 255), "green": round(g * 255), "blue": round(bl * 255)}


def random_colour(rng: random.Random, avoid: dict | None = None) -> dict:
    """A vivid random colour (full saturation and value), not equal to `avoid`."""
    for _ in range(10):
        r, g, b = colorsys.hsv_to_rgb(rng.random(), 1.0, 1.0)
        c = {"red": round(r * 255), "green": round(g * 255), "blue": round(b * 255)}
        if c != avoid:
            return c
    return c


class ColorCycle:
    def __init__(self, get_speaker: Callable[[], Any], store, on_event: Callable[[str], None] | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, rng: random.Random | None = None):
        self._get_speaker = get_speaker  # the current client (its address can change at runtime)
        self._store = store
        self._on_event = on_event or (lambda _msg: None)
        self.sleep = sleep  # tests replace it
        self._rng = rng or random.Random()
        self._task: asyncio.Task | None = None
        self._guard = asyncio.Lock()  # start/stop never interleave
        self.state = "stopped"  # stopped | running | disconnected | error
        self.message: str | None = None
        self.last_colour: dict | None = None
        self.changed_at: float | None = None
        self.steps = 0

    # ---- settings (saved in the project database; the running state is NOT saved, so nothing restarts on boot)
    def config(self) -> dict:
        raw = self._store.get_state("speaker", "colour_cycle")
        cfg = {**DEFAULTS, **(json.loads(raw) if raw else {})}
        return cfg

    def save_config(self, cfg: dict) -> dict:
        self._store.set_state("speaker", "colour_cycle", json.dumps(cfg))
        return self.config()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict:
        return {"running": self.running, "state": self.state, "message": self.message, "last_colour": self.last_colour,
                "changed_at": self.changed_at, "steps": self.steps}

    # ---- control
    async def start(self) -> dict:
        async with self._guard:
            if self.running:
                return self.status()  # one cycle per speaker
            light = await self._get_speaker().read("light")  # raises on a dead link
            if not light:
                raise SpeakerError(ErrorCode.DENIED, "התאורה כבויה. יש להדליק אותה לפני הפעלת החלפת הצבעים.", 409)
            cfg = self.config()
            if cfg["mode"] == "palette" and len(cfg["palette"]) < 2:
                raise SpeakerError(ErrorCode.INVALID_COMMAND, "בפלטה צריכים להיות לפחות שני צבעים.", 422)
            self.state, self.message, self.steps = "running", None, 0
            self._task = asyncio.create_task(self._run(), name="zeppelin-colour-cycle")
            self._on_event("החלפת צבעים אוטומטית הופעלה")
            return self.status()

    async def stop(self, reason: str | None = None) -> dict:
        async with self._guard:
            await self._cancel()
            if self.state == "running":
                self.state = "stopped"
                self.message = reason
                self._on_event("החלפת צבעים אוטומטית נעצרה" + (f": {reason}" if reason else ""))
            return self.status()

    async def stop_if_running(self, reason: str) -> None:
        """Called before a manual colour or turning the light off: the user's action wins, the cycle stops first."""
        if self.running:
            await self.stop(reason)

    async def shutdown(self) -> None:
        await self._cancel()
        if self.state == "running":
            self.state = "stopped"

    async def _cancel(self) -> None:
        t, self._task = self._task, None
        if t and not t.done():
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - the task's own errors are already recorded
                pass

    async def _fade(self, start: dict, target: dict, duration: float) -> float:
        """Write the intermediate colours (not the target). Each waits for the previous write: no backlog, no catch-up.
        Returns the seconds of waiting it planned, which count toward the interval."""
        steps = int(duration / FADE_STEP_S)
        for k in range(1, steps):
            c = blend(start, target, k / steps)
            self.last_colour = await self._get_speaker().write("rgb", c)
            await self.sleep(FADE_STEP_S)
        return max(0, steps - 1) * FADE_STEP_S

    def _next(self, cfg: dict, i: int) -> dict:
        if cfg["mode"] == "random":
            return random_colour(self._rng, self.last_colour)
        pal = cfg["palette"]
        return pal[i % len(pal)]

    async def _run(self) -> None:
        i = 0
        try:
            cfg = self.config()
            cur = await self._get_speaker().read("rgb")
            self.last_colour = cur  # the first smooth transition starts from what is shown now
            if cfg["mode"] == "palette":  # start from the first palette colour that differs from what is shown now
                i = next((k for k, c in enumerate(cfg["palette"]) if c != cur), 0)
            while True:
                cfg = self.config()  # a changed interval/palette/smooth applies from the next step
                colour = self._next(cfg, i)
                spent = 0.0
                if cfg.get("smooth") and self.last_colour and self.last_colour != colour:
                    spent = await self._fade(self.last_colour, colour, fade_duration(cfg["interval_s"]))
                self.last_colour = await self._get_speaker().write("rgb", colour)  # verified write, serialised by the lock
                self.changed_at, self.steps = time.time(), self.steps + 1
                i += 1
                await self.sleep(max(0.0, cfg["interval_s"] - spent))  # from now: missed steps are never made up
        except asyncio.CancelledError:
            raise
        except SpeakerError as e:
            if e.code in (ErrorCode.NOT_CONNECTED, ErrorCode.TIMEOUT):
                self.state, self.message = "disconnected", "נעצר: הרמקול לא זמין."
            else:
                self.state, self.message = "error", f"נעצר: {e.message}"
            self._on_event(self.message)
        except Exception as e:  # noqa: BLE001 - never let the task die silently
            self.state, self.message = "error", f"נעצר: שגיאה לא צפויה ({type(e).__name__})."
            self._on_event(self.message)
