"""SQLite device registry. Credentials for real adapters will live in a separate server-only table (Steps D/E)."""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DeviceRow:
    id: str
    kind: str
    name: str
    host: str | None
    role: str | None = None  # 'tv' | 'box'; None = derived from kind (lg -> tv, hot -> box)


class Store:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, kind TEXT NOT NULL,"
            " name TEXT NOT NULL, host TEXT, role TEXT, UNIQUE(kind, host))"
        )
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(devices)")}
        if "role" not in cols:  # databases created before roles existed
            self._db.execute("ALTER TABLE devices ADD COLUMN role TEXT")
        self._db.execute("CREATE TABLE IF NOT EXISTS device_state (device_id TEXT NOT NULL, k TEXT NOT NULL, v TEXT, PRIMARY KEY (device_id, k))")
        self._db.commit()

    def get_state(self, device_id: str, key: str) -> str | None:
        with self._lock:
            r = self._db.execute("SELECT v FROM device_state WHERE device_id=? AND k=?", (device_id, key)).fetchone()
        return r[0] if r else None

    def set_state(self, device_id: str, key: str, value: str | None) -> None:
        with self._lock:
            self._db.execute("INSERT INTO device_state VALUES (?,?,?) ON CONFLICT(device_id,k) DO UPDATE SET v=excluded.v",
                             (device_id, key, value))
            self._db.commit()

    @property
    def connection(self) -> tuple[sqlite3.Connection, threading.Lock]:
        return self._db, self._lock

    def list(self) -> list[DeviceRow]:
        with self._lock:
            rows = self._db.execute("SELECT id, kind, name, host, role FROM devices ORDER BY kind, name").fetchall()
        return [DeviceRow(*r) for r in rows]

    def add(self, row: DeviceRow) -> bool:
        """Returns False if a device with the same kind+host already exists."""
        with self._lock:
            try:
                self._db.execute("INSERT INTO devices (id, kind, name, host, role) VALUES (?,?,?,?,?)", (row.id, row.kind, row.name, row.host, row.role))
                self._db.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def update(self, device_id: str, name: str | None, role: str | None, host: str | None = None) -> bool:
        with self._lock:
            try:
                n = self._db.execute("UPDATE devices SET name=COALESCE(?, name), role=COALESCE(?, role), host=COALESCE(?, host) WHERE id=?",
                                     (name, role, host, device_id)).rowcount
            except sqlite3.IntegrityError:  # another device of this kind already uses that address
                return False
            self._db.commit()
        return bool(n)

    def remove(self, device_id: str) -> bool:
        with self._lock:
            n = self._db.execute("DELETE FROM devices WHERE id=?", (device_id,)).rowcount
            self._db.execute("DELETE FROM device_state WHERE device_id=?", (device_id,))
            self._db.commit()
        return bool(n)
