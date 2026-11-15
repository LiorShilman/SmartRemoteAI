"""Personal speaker profiles for the B&W Zeppelin, stored on the server (available from any browser).

A profile holds: the 5 EQ band values, bass, treble, loudness, the light's colour and brightness, and the colour cycle
(running or not, palette, interval, smooth). Volume only when the user explicitly includes it. Mute, balance and source
gain are never saved or changed, and neither is the light's on/off switch.

Saving reads fresh values from the speaker (and the cycle settings from the server). Loading is a controlled sequence:
an undo snapshot first, then the cycle is stopped, then one verified write per setting, then the cycle is started again
if the profile had it running, then everything is read back. While a load runs, every other speaker write is refused
(see `busy`), so nothing competes with it. Each step reports its own result; a partial load is reported as partial.
Nothing is ever loaded automatically.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
import uuid
from typing import Any

from app.models.schemas import ErrorCode
from app.services.zeppelin import SpeakerError

MAX_PROFILES = 30
STEP_LABEL = {
    "cycle_stop": "עצירת החלפת הצבעים", "eq": "אקולייזר", "bass": "באס", "treble": "גבוהים", "loudness": "Loudness",
    "brightness": "בהירות", "rgb": "צבע", "cycle_config": "הגדרות החלפת צבעים", "volume": "עוצמה", "cycle_start": "הפעלת החלפת הצבעים",
}


class ProfileStore:
    def __init__(self, db: sqlite3.Connection, lock: threading.Lock):
        self._db, self._lock = db, lock
        with lock:
            db.execute("CREATE TABLE IF NOT EXISTS speaker_profiles (id TEXT PRIMARY KEY, name TEXT NOT NULL, include_volume INTEGER NOT NULL,"
                       " data TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL)")
            db.commit()

    @staticmethod
    def _row(r) -> dict:
        return {"id": r[0], "name": r[1], "include_volume": bool(r[2]), "data": json.loads(r[3]), "created_at": r[4], "updated_at": r[5]}

    def list(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT id, name, include_volume, data, created_at, updated_at FROM speaker_profiles ORDER BY created_at").fetchall()
        return [self._row(r) for r in rows]

    def get(self, pid: str) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT id, name, include_volume, data, created_at, updated_at FROM speaker_profiles WHERE id=?", (pid,)).fetchone()
        return self._row(r) if r else None

    def name_taken(self, name: str, except_id: str | None = None) -> bool:
        return any(p["name"].casefold() == name.casefold() and p["id"] != except_id for p in self.list())

    def add(self, name: str, include_volume: bool, data: dict, now: float) -> dict | None:
        with self._lock:
            if self._db.execute("SELECT COUNT(*) FROM speaker_profiles").fetchone()[0] >= MAX_PROFILES:
                return None
            pid = uuid.uuid4().hex[:12]
            self._db.execute("INSERT INTO speaker_profiles VALUES (?,?,?,?,?,?)", (pid, name, int(include_volume), json.dumps(data), now, now))
            self._db.commit()
        return self.get(pid)

    def rename(self, pid: str, name: str, now: float) -> dict | None:
        with self._lock:
            n = self._db.execute("UPDATE speaker_profiles SET name=?, updated_at=? WHERE id=?", (name, now, pid)).rowcount
            self._db.commit()
        return self.get(pid) if n else None

    def replace_data(self, pid: str, data: dict, now: float) -> dict | None:
        """Overwrite a profile's saved values (name and include_volume stay)."""
        with self._lock:
            n = self._db.execute("UPDATE speaker_profiles SET data=?, updated_at=? WHERE id=?", (json.dumps(data), now, pid)).rowcount
            self._db.commit()
        return self.get(pid) if n else None

    def delete(self, pid: str) -> bool:
        with self._lock:
            n = self._db.execute("DELETE FROM speaker_profiles WHERE id=?", (pid,)).rowcount
            self._db.commit()
        return bool(n)


class ProfileService:
    def __init__(self, get_speaker, cycle, store, profiles: ProfileStore):
        self._get_speaker = get_speaker
        self._cycle = cycle
        self._store = store  # device_state: "profile_loaded", "profile_undo"
        self.profiles = profiles
        self._lock = asyncio.Lock()
        self.busy = False  # True while a load/undo runs: other speaker writes are refused

    # ---- current state
    async def capture(self, include_volume: bool) -> dict:
        """Fresh values from the speaker plus the cycle settings from the server. Refuses a partial capture."""
        sp = self._get_speaker()
        data: dict[str, Any] = {}
        errors: dict[str, str] = {}
        try:
            data["eq"] = {b["band"]: b["value"] for b in await sp.read_eq()}
        except SpeakerError as e:
            if e.code in (ErrorCode.NOT_CONNECTED, ErrorCode.TIMEOUT):
                raise
            errors["eq"] = e.message
        for name in ("bass", "treble", "loudness", "rgb", "brightness") + (("volume",) if include_volume else ()):
            try:
                data[name] = await sp.read(name)
            except SpeakerError as e:
                if e.code in (ErrorCode.NOT_CONNECTED, ErrorCode.TIMEOUT):
                    raise
                errors[name] = e.message
        if errors:
            raise SpeakerError(ErrorCode.UNSUPPORTED, "לא ניתן לקרוא את כל הערכים, ולכן המצב לא נשמר: "
                               + "; ".join(f"{STEP_LABEL.get(k, k)}: {v}" for k, v in errors.items()), 502)
        data["cycle"] = {"running": self._cycle.running, "config": self._cycle.config()}
        return data

    def loaded_id(self) -> str | None:
        return self._store.get_state("speaker", "profile_loaded")

    def undo_info(self) -> dict | None:
        raw = self._store.get_state("speaker", "profile_undo")
        if not raw:
            return None
        u = json.loads(raw)
        return {"at": u["at"], "from_profile": u.get("profile_name")}

    # ---- loading
    async def load(self, pid: str) -> dict:
        p = self.profiles.get(pid)
        if p is None:
            raise SpeakerError(ErrorCode.INVALID_COMMAND, "הפרופיל לא נמצא.", 404)
        return await self._run(p["data"], include_volume=p["include_volume"], undo_name=p["name"], loaded=pid)

    async def undo(self) -> dict:
        raw = self._store.get_state("speaker", "profile_undo")
        if not raw:
            raise SpeakerError(ErrorCode.INVALID_COMMAND, "אין מצב קודם לחזור אליו.", 409)
        u = json.loads(raw)
        out = await self._run(u["data"], include_volume="volume" in u["data"], undo_name=None, loaded=u.get("loaded_before"))
        if out["status"] == "full":  # keep the snapshot until it has been fully restored
            self._store.set_state("speaker", "profile_undo", None)
        return out

    async def _run(self, data: dict, include_volume: bool, undo_name: str | None, loaded: str | None) -> dict:
        if self._lock.locked():
            raise SpeakerError(ErrorCode.DENIED, "טעינת פרופיל כבר מתבצעת.", 409)
        async with self._lock:
            self.busy = True
            try:
                if undo_name is not None:  # loading a profile: remember what was there, first (cycle state included)
                    before = await self.capture(include_volume)
                    self._store.set_state("speaker", "profile_undo", json.dumps(
                        {"at": time.time(), "data": before, "profile_name": undo_name, "loaded_before": self.loaded_id()}))
                steps = await self._apply(data, include_volume)
                ok = [s for s in steps if s["ok"]]
                status = "full" if len(ok) == len(steps) else "partial" if ok else "failed"
                if status == "full":
                    self._store.set_state("speaker", "profile_loaded", loaded)
                else:  # what is on the speaker matches no profile exactly
                    self._store.set_state("speaker", "profile_loaded", None)
                return {"status": status, "steps": steps}
            finally:
                self.busy = False

    async def _apply(self, data: dict, include_volume: bool) -> list[dict]:
        sp = self._get_speaker()
        cyc = data.get("cycle") or {}
        plan: list[tuple[str, Any]] = [("cycle_stop", None), ("eq", data["eq"]), ("bass", data["bass"]), ("treble", data["treble"]),
                                       ("loudness", data["loudness"]), ("brightness", data["brightness"]), ("rgb", data["rgb"]),
                                       ("cycle_config", cyc.get("config"))]
        if include_volume and "volume" in data:
            plan.append(("volume", data["volume"]))
        if cyc.get("running"):
            plan.append(("cycle_start", None))
        steps: list[dict] = []
        dead: str | None = None
        for name, value in plan:
            step = {"step": name, "label": STEP_LABEL[name], "ok": False, "error": None}
            if dead:
                step["error"] = "לא בוצע: " + dead
                steps.append(step)
                continue
            try:
                if name == "cycle_stop":
                    await self._cycle.stop_if_running("נטען פרופיל")
                elif name == "eq":
                    await sp.write_eq({str(k): float(v) for k, v in value.items()})
                elif name == "cycle_config":
                    if value:
                        self._cycle.save_config(value)
                elif name == "cycle_start":
                    await self._cycle.start()
                else:
                    await sp.write(name, value)
                step["ok"] = True
            except SpeakerError as e:
                step["error"] = e.message
                if e.code in (ErrorCode.NOT_CONNECTED, ErrorCode.TIMEOUT):
                    dead = "הרמקול לא זמין."
            steps.append(step)
        return steps
