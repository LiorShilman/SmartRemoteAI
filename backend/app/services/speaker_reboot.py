"""Restart the speaker from the app, like a short press of its small reset button.

Started only by an explicit request. The request returns once the speaker has stopped answering (the restart began);
a background watch then waits for it to answer again and records the result, which GET /api/speaker/reboot reports.
"Back" is reported only after the speaker itself answered again; nothing is assumed from the request alone.
"""
from __future__ import annotations

import asyncio
import time
from typing import Callable, Literal

Phase = Literal["idle", "restarting", "back", "timeout"]


class SpeakerReboot:
    def __init__(self, speaker: Callable[[], object], cycle, on_event: Callable[[str], None]):
        self._speaker, self._cycle, self._on_event = speaker, cycle, on_event
        self.phase: Phase = "idle"
        self._started: float | None = None
        self._ended: float | None = None
        self._task: asyncio.Task | None = None
        self._guard = asyncio.Lock()

    @property
    def restarting(self) -> bool:
        return self.phase == "restarting"

    def status(self) -> dict:
        if self._started is None:
            return {"phase": self.phase, "seconds": None}
        end = self._ended if self._ended is not None else time.monotonic()
        return {"phase": self.phase, "seconds": round(end - self._started)}

    async def start(self) -> dict:
        from app.models.schemas import ErrorCode
        from app.services.zeppelin import SpeakerError

        async with self._guard:
            if self.restarting:
                raise SpeakerError(ErrorCode.DENIED, "הרמקול כבר בהפעלה מחדש.", 409)
            # the colour cycle would only fail against a speaker that is down: stop it first, keeping the last colour
            await self._cycle.stop_if_running("הרמקול מופעל מחדש")
            sp = self._speaker()
            await sp.reboot()  # raises unless the speaker actually stopped answering
            self.phase, self._started, self._ended = "restarting", time.monotonic(), None
            self._task = asyncio.create_task(self._watch(sp), name="zeppelin-reboot-watch")
            return self.status()

    async def _watch(self, sp) -> None:
        try:
            back = await sp.wait_back()
        except Exception:  # noqa: BLE001 - a watch must never leave the phase stuck on "restarting"
            back = False
        self.phase, self._ended = ("back" if back else "timeout"), time.monotonic()
        self._on_event("הרמקול חזר לפעול אחרי הפעלה מחדש" if back else "הרמקול לא חזר לענות אחרי הפעלה מחדש")

    async def shutdown(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
