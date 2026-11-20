"""Spoken replies: short Hebrew text -> MP3, made on the server so every browser and phone gets the same voice.

Uses Microsoft's online neural voices (the ones Edge reads aloud with) via `edge-tts`. Only the reply text leaves
the server, no key or account. Bounded: short printable text only, a small cache, and a per-window budget.
Nothing is logged except failures (never the text).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections import OrderedDict, deque

log = logging.getLogger("smart_remote.tts")

VOICES = {"hila": "he-IL-HilaNeural", "avri": "he-IL-AvriNeural"}
MAX_TEXT = 300
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class TtsError(Exception):
    pass


class Tts:
    MAX_PER_WINDOW, WINDOW_S, CACHE = 60, 300.0, 64

    def __init__(self, synth=None, timeout_s: float = 12.0):
        self._synth = synth or self._edge  # tests replace it
        self._timeout = timeout_s
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._calls: deque[float] = deque()

    @staticmethod
    async def _edge(text: str, voice: str) -> bytes:
        import edge_tts  # lazy: the server runs without it; then replies are simply unavailable

        out = bytearray()
        async for chunk in edge_tts.Communicate(text, voice).stream():
            if chunk["type"] == "audio":
                out += chunk["data"]
        return bytes(out)

    def _budget_ok(self) -> bool:
        now = time.monotonic()
        while self._calls and now - self._calls[0] > self.WINDOW_S:
            self._calls.popleft()
        if len(self._calls) >= self.MAX_PER_WINDOW:
            return False
        self._calls.append(now)
        return True

    async def speak(self, text: str, voice: str = "hila") -> bytes:
        text = text.strip()
        if not text or len(text) > MAX_TEXT or CONTROL.search(text) or voice not in VOICES:
            raise ValueError("bad text or voice")
        key = hashlib.sha256(f"{voice}\x00{text}".encode()).hexdigest()
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        if not self._budget_ok():
            raise TtsError("יותר מדי בקשות הקראה. נסה שוב בעוד כמה דקות.")
        try:
            audio = await asyncio.wait_for(self._synth(text, VOICES[voice]), self._timeout)
        except Exception as e:  # noqa: BLE001 - network, service or missing package: one clear error
            log.warning("tts failed (%s)", type(e).__name__)
            raise TtsError("שירות ההקראה לא זמין כרגע.") from e
        if not audio:
            raise TtsError("שירות ההקראה החזיר תשובה ריקה.")
        self._cache[key] = audio
        if len(self._cache) > self.CACHE:
            self._cache.popitem(last=False)
        return audio
