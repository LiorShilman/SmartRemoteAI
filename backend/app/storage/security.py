"""Per-device access tokens and the audit log.

Tokens are random 256-bit secrets shown once at creation; only their SHA-256 is stored, so a leaked database
or backup cannot be used to log in. The master ACCESS_TOKEN from .env stays the admin/recovery credential and
is the only one that can manage tokens.
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass

TOUCH_EVERY_S = 30  # do not write to the database on every single request
AUDIT_KEEP = 2000


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TokenRow:
    id: str
    name: str
    prefix: str
    created_at: float
    last_used_at: float | None
    last_ip: str | None
    revoked_at: float | None


_COLS = "id, name, prefix, created_at, last_used_at, last_ip, revoked_at"


class TokenStore:
    def __init__(self, db: sqlite3.Connection, lock: threading.Lock):
        self._db, self._lock = db, lock
        with lock:
            db.execute("CREATE TABLE IF NOT EXISTS tokens (id TEXT PRIMARY KEY, name TEXT NOT NULL, hash TEXT NOT NULL UNIQUE,"
                       " prefix TEXT NOT NULL, created_at REAL NOT NULL, last_used_at REAL, last_ip TEXT, revoked_at REAL)")
            db.commit()

    def create(self, name: str, now: float) -> tuple[TokenRow, str]:
        token = "sr_" + secrets.token_urlsafe(32)
        tid = uuid.uuid4().hex[:12]
        with self._lock:
            self._db.execute("INSERT INTO tokens (id, name, hash, prefix, created_at) VALUES (?,?,?,?,?)",
                             (tid, name, _hash(token), token[:7], now))
            self._db.commit()
        return self.get(tid), token  # type: ignore[return-value]

    def get(self, tid: str) -> TokenRow | None:
        with self._lock:
            r = self._db.execute(f"SELECT {_COLS} FROM tokens WHERE id=?", (tid,)).fetchone()
        return TokenRow(*r) if r else None

    def find(self, token: str) -> TokenRow | None:
        """The active (not revoked) token row for this secret, or None."""
        with self._lock:
            r = self._db.execute(f"SELECT {_COLS} FROM tokens WHERE hash=? AND revoked_at IS NULL", (_hash(token),)).fetchone()
        return TokenRow(*r) if r else None

    def touch(self, row: TokenRow, ip: str, now: float) -> str | None:
        """Record use. Returns the previous IP when it changed (so the caller can audit "new location")."""
        changed = row.last_ip if row.last_ip and row.last_ip != ip else None
        if changed or row.last_used_at is None or now - row.last_used_at >= TOUCH_EVERY_S:
            with self._lock:
                self._db.execute("UPDATE tokens SET last_used_at=?, last_ip=? WHERE id=?", (now, ip, row.id))
                self._db.commit()
        return changed

    def list(self) -> list[TokenRow]:
        with self._lock:
            rows = self._db.execute(f"SELECT {_COLS} FROM tokens ORDER BY (revoked_at IS NOT NULL), created_at DESC").fetchall()
        return [TokenRow(*r) for r in rows]

    def purge_revoked(self, ids: list[str] | None) -> int:
        """Remove revoked tokens from the list. Active tokens are never touched."""
        with self._lock:
            if ids is None:
                n = self._db.execute("DELETE FROM tokens WHERE revoked_at IS NOT NULL").rowcount
            elif ids:
                n = self._db.execute(f"DELETE FROM tokens WHERE revoked_at IS NOT NULL AND id IN ({','.join('?' * len(ids))})", ids).rowcount
            else:
                n = 0
            self._db.commit()
        return n

    def revoke(self, tid: str, now: float) -> bool:
        with self._lock:
            n = self._db.execute("UPDATE tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (now, tid)).rowcount
            self._db.commit()
        return bool(n)


@dataclass(frozen=True)
class AuditRow:
    id: int
    at: float
    ip: str
    who: str
    event: str
    detail: str


class AuditStore:
    def __init__(self, db: sqlite3.Connection, lock: threading.Lock):
        self._db, self._lock = db, lock
        with lock:
            db.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, ip TEXT NOT NULL,"
                       " who TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '')")
            db.commit()

    def add(self, ip: str, who: str, event: str, detail: str = "", now: float | None = None) -> None:
        with self._lock:
            self._db.execute("INSERT INTO audit (at, ip, who, event, detail) VALUES (?,?,?,?,?)",
                             (now if now is not None else time.time(), ip, who, event, detail[:200]))
            # bounded: keep the newest AUDIT_KEEP rows
            self._db.execute("DELETE FROM audit WHERE id <= (SELECT MAX(id) FROM audit) - ?", (AUDIT_KEEP,))
            self._db.commit()

    def recent(self, limit: int = 50) -> list[AuditRow]:
        with self._lock:
            rows = self._db.execute("SELECT id, at, ip, who, event, detail FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [AuditRow(*r) for r in rows]
