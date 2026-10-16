"""Server-side scheduled commands ("turn off the TV in an hour").

Persisted in SQLite so schedules survive a restart, executed by one asyncio loop, and cancellable.
A schedule that came due while the server was down is marked "missed" instead of firing late and
surprising the user (the grace window is short on purpose)."""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import time
import uuid

from app.models.schemas import ScheduleCreate, ScheduleOut
from app.services.manager import DeviceManager, ManagerError

log = logging.getLogger("smart_remote.scheduler")
MAX_PENDING = 20
GRACE_S = 120  # fire at most this late; otherwise "missed"


class ScheduleStore:
    def __init__(self, db: sqlite3.Connection, lock: threading.Lock):
        self._db, self._lock = db, lock
        with lock:
            db.execute("CREATE TABLE IF NOT EXISTS schedules (id TEXT PRIMARY KEY, run_at REAL NOT NULL, target TEXT NOT NULL,"
                       " action TEXT NOT NULL, params TEXT NOT NULL, label TEXT NOT NULL, status TEXT NOT NULL, error TEXT)")
            db.commit()

    def add(self, c: ScheduleCreate, now: float) -> ScheduleOut | None:
        with self._lock:
            n = self._db.execute("SELECT COUNT(*) FROM schedules WHERE status='pending'").fetchone()[0]
            if n >= MAX_PENDING:
                return None
            sid = uuid.uuid4().hex[:12]
            self._db.execute("INSERT INTO schedules VALUES (?,?,?,?,?,?,?,NULL)",
                             (sid, now + c.delay_seconds, c.target, c.action.value, json.dumps(c.params), c.label, "pending"))
            self._db.commit()
        return self.get(sid)

    def get(self, sid: str) -> ScheduleOut | None:
        with self._lock:
            r = self._db.execute("SELECT id,run_at,target,action,params,label,status,error FROM schedules WHERE id=?", (sid,)).fetchone()
        return self._out(r) if r else None

    def list(self) -> list[ScheduleOut]:
        with self._lock:
            rows = self._db.execute("SELECT id,run_at,target,action,params,label,status,error FROM schedules"
                                    " ORDER BY (status='pending') DESC, run_at DESC LIMIT 30").fetchall()
        return [self._out(r) for r in rows]

    def due(self, now: float) -> list[ScheduleOut]:
        with self._lock:
            rows = self._db.execute("SELECT id,run_at,target,action,params,label,status,error FROM schedules"
                                    " WHERE status='pending' AND run_at<=?", (now,)).fetchall()
        return [self._out(r) for r in rows]

    def delete(self, ids: list[str] | None) -> int:
        """Remove schedules. Deleting a pending one is a cancel: the scheduler claims rows with
        `UPDATE ... WHERE status='pending'`, which then matches nothing, so it can never fire."""
        with self._lock:
            if ids is None:
                n = self._db.execute("DELETE FROM schedules WHERE status != 'pending'").rowcount
            elif ids:
                n = self._db.execute(f"DELETE FROM schedules WHERE id IN ({','.join('?' * len(ids))})", ids).rowcount
            else:
                n = 0
            self._db.commit()
        return n

    def set_status(self, sid: str, status: str, error: str | None = None, only_if: str | None = None) -> bool:
        with self._lock:
            q, a = "UPDATE schedules SET status=?, error=? WHERE id=?", [status, error, sid]
            if only_if:
                q, a = q + " AND status=?", [*a, only_if]
            changed = self._db.execute(q, a).rowcount
            self._db.commit()
        return bool(changed)

    @staticmethod
    def _out(r) -> ScheduleOut:
        return ScheduleOut(id=r[0], run_at=r[1], target=r[2], action=r[3], params=json.loads(r[4]),
                           label=r[5], status=r[6], error=r[7])


class Scheduler:
    def __init__(self, store: ScheduleStore, manager: DeviceManager):
        self.store, self.manager = store, manager
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick(time.time())
            except Exception:  # noqa: BLE001 - the loop must survive anything
                log.exception("scheduler tick failed")
            await asyncio.sleep(1)

    async def tick(self, now: float) -> None:
        for s in self.store.due(now):
            if now - s.run_at > GRACE_S:
                self.store.set_status(s.id, "missed", "השרת לא היה פעיל בזמן הביצוע.", only_if="pending")
                continue
            if not self.store.set_status(s.id, "done", only_if="pending"):  # claim it; cancelled meanwhile -> skip
                continue
            try:
                await self.manager.send_to_kind(s.target, s.action.value, s.params)
            except ManagerError as e:
                self.store.set_status(s.id, "failed", e.message)
            except Exception as e:  # noqa: BLE001
                log.warning("scheduled %s failed: %r", s.id, e)
                self.store.set_status(s.id, "failed", "הפעולה המתוזמנת נכשלה.")
