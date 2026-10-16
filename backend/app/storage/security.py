"""Per-device access tokens, the audit log, screen-time usage and "more time" requests.

Tokens are random 256-bit secrets shown once at creation; only their SHA-256 is stored, so a leaked database
or backup cannot be used to log in. The master ACCESS_TOKEN from .env stays the admin/recovery credential and
is the only one that can manage tokens.

A token may carry a *policy* (kids mode): allowed hours, allowed apps, daily screen-time limit... The policy is
data here; it is enforced on the server in app/services/policy.py, never only in the UI.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass

TOUCH_EVERY_S = 30  # do not write to the database on every single request
AUDIT_KEEP = 2000
USAGE_KEEP_DAYS = 60


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
    policy: dict | None = None


_COLS = "id, name, prefix, created_at, last_used_at, last_ip, revoked_at, policy"


def _token(r) -> TokenRow:
    return TokenRow(*r[:7], json.loads(r[7]) if r[7] else None)


class TokenStore:
    def __init__(self, db: sqlite3.Connection, lock: threading.Lock):
        self._db, self._lock = db, lock
        with lock:
            db.execute("CREATE TABLE IF NOT EXISTS tokens (id TEXT PRIMARY KEY, name TEXT NOT NULL, hash TEXT NOT NULL UNIQUE,"
                       " prefix TEXT NOT NULL, created_at REAL NOT NULL, last_used_at REAL, last_ip TEXT, revoked_at REAL, policy TEXT)")
            if "policy" not in {r[1] for r in db.execute("PRAGMA table_info(tokens)")}:  # databases from before kids mode
                db.execute("ALTER TABLE tokens ADD COLUMN policy TEXT")
            db.commit()

    def create(self, name: str, now: float, policy: dict | None = None) -> tuple[TokenRow, str]:
        token = "sr_" + secrets.token_urlsafe(32)
        tid = uuid.uuid4().hex[:12]
        with self._lock:
            self._db.execute("INSERT INTO tokens (id, name, hash, prefix, created_at, policy) VALUES (?,?,?,?,?,?)",
                             (tid, name, _hash(token), token[:7], now, json.dumps(policy) if policy else None))
            self._db.commit()
        return self.get(tid), token  # type: ignore[return-value]

    def get(self, tid: str) -> TokenRow | None:
        with self._lock:
            r = self._db.execute(f"SELECT {_COLS} FROM tokens WHERE id=?", (tid,)).fetchone()
        return _token(r) if r else None

    def find(self, token: str) -> TokenRow | None:
        """The active (not revoked) token row for this secret, or None."""
        with self._lock:
            r = self._db.execute(f"SELECT {_COLS} FROM tokens WHERE hash=? AND revoked_at IS NULL", (_hash(token),)).fetchone()
        return _token(r) if r else None

    def set_policy(self, tid: str, policy: dict | None) -> bool:
        with self._lock:
            n = self._db.execute("UPDATE tokens SET policy=? WHERE id=? AND revoked_at IS NULL",
                                 (json.dumps(policy) if policy else None, tid)).rowcount
            self._db.commit()
        return bool(n)

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
        return [_token(r) for r in rows]

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


class UsageStore:
    """Seconds of screen time per day / device / app, sampled by the server. The row (device '*', app 'ALL') counts a
    sample once when ANY device was showing content, so a TV that displays the box is not double counted."""

    TOTAL = ("*", "ALL")

    def __init__(self, db: sqlite3.Connection, lock: threading.Lock):
        self._db, self._lock = db, lock
        with lock:
            db.execute("CREATE TABLE IF NOT EXISTS usage (day TEXT NOT NULL, device_id TEXT NOT NULL, app TEXT NOT NULL,"
                       " seconds INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, device_id, app))")
            db.commit()

    def add(self, day: str, device_id: str, app: str, seconds: int) -> None:
        with self._lock:
            self._db.execute("INSERT INTO usage VALUES (?,?,?,?) ON CONFLICT(day, device_id, app) DO UPDATE SET seconds = seconds + excluded.seconds",
                             (day, device_id, app, seconds))
            self._db.commit()

    def total_seconds(self, day: str) -> int:
        with self._lock:
            r = self._db.execute("SELECT seconds FROM usage WHERE day=? AND device_id=? AND app=?", (day, *self.TOTAL)).fetchone()
        return r[0] if r else 0

    def by_day(self, since_day: str) -> dict[str, dict]:
        """{day: {"total": seconds, "apps": {app: seconds}}} for days >= since_day (apps summed over devices)."""
        out: dict[str, dict] = {}
        with self._lock:
            rows = self._db.execute("SELECT day, device_id, app, seconds FROM usage WHERE day >= ? ORDER BY day", (since_day,)).fetchall()
        for day, device_id, app, seconds in rows:
            d = out.setdefault(day, {"total": 0, "apps": {}})
            if (device_id, app) == self.TOTAL:
                d["total"] = seconds
            else:
                d["apps"][app] = d["apps"].get(app, 0) + seconds
        return out

    def prune(self, before_day: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM usage WHERE day < ?", (before_day,))
            self._db.commit()


@dataclass(frozen=True)
class TimeRequest:
    id: str
    token_id: str
    token_name: str
    minutes: int
    status: str  # pending | approved | denied
    created_at: float
    decided_at: float | None
    granted_minutes: int


class TimeStore:
    """Kids' "give me more time" requests and the minutes a parent granted for a given day."""

    MAX_PENDING = 3

    def __init__(self, db: sqlite3.Connection, lock: threading.Lock):
        self._db, self._lock = db, lock
        with lock:
            db.execute("CREATE TABLE IF NOT EXISTS time_requests (id TEXT PRIMARY KEY, token_id TEXT NOT NULL, token_name TEXT NOT NULL,"
                       " minutes INTEGER NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL, decided_at REAL, granted INTEGER NOT NULL DEFAULT 0)")
            db.execute("CREATE TABLE IF NOT EXISTS time_grants (id INTEGER PRIMARY KEY AUTOINCREMENT, token_id TEXT NOT NULL,"
                       " day TEXT NOT NULL, minutes INTEGER NOT NULL)")
            db.commit()

    @staticmethod
    def _req(r) -> TimeRequest:
        return TimeRequest(*r)

    _REQ = "id, token_id, token_name, minutes, status, created_at, decided_at, granted"

    def create(self, token_id: str, token_name: str, minutes: int, now: float) -> TimeRequest | None:
        with self._lock:
            pending = self._db.execute("SELECT COUNT(*) FROM time_requests WHERE token_id=? AND status='pending'", (token_id,)).fetchone()[0]
            if pending >= self.MAX_PENDING:
                return None
            rid = uuid.uuid4().hex[:12]
            self._db.execute("INSERT INTO time_requests (id, token_id, token_name, minutes, status, created_at) VALUES (?,?,?,?,'pending',?)",
                             (rid, token_id, token_name, minutes, now))
            self._db.commit()
        return self.get(rid)

    def get(self, rid: str) -> TimeRequest | None:
        with self._lock:
            r = self._db.execute(f"SELECT {self._REQ} FROM time_requests WHERE id=?", (rid,)).fetchone()
        return self._req(r) if r else None

    def list(self, limit: int = 20) -> list[TimeRequest]:
        with self._lock:
            rows = self._db.execute(f"SELECT {self._REQ} FROM time_requests ORDER BY (status='pending') DESC, created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._req(r) for r in rows]

    def pending_count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM time_requests WHERE status='pending'").fetchone()[0]

    def latest_for(self, token_id: str) -> TimeRequest | None:
        with self._lock:
            r = self._db.execute(f"SELECT {self._REQ} FROM time_requests WHERE token_id=? ORDER BY created_at DESC LIMIT 1", (token_id,)).fetchone()
        return self._req(r) if r else None

    def decide(self, rid: str, approve: bool, minutes: int, day: str, now: float) -> TimeRequest | None:
        """Decide a pending request exactly once; an approval records the granted minutes for `day`."""
        with self._lock:
            row = self._db.execute("SELECT token_id FROM time_requests WHERE id=? AND status='pending'", (rid,)).fetchone()
            if row is None:
                return None
            self._db.execute("UPDATE time_requests SET status=?, decided_at=?, granted=? WHERE id=?",
                             ("approved" if approve else "denied", now, minutes if approve else 0, rid))
            if approve:
                self._db.execute("INSERT INTO time_grants (token_id, day, minutes) VALUES (?,?,?)", (row[0], day, minutes))
            self._db.commit()
        return self.get(rid)

    def extra_minutes(self, token_id: str, day: str) -> int:
        with self._lock:
            return self._db.execute("SELECT COALESCE(SUM(minutes), 0) FROM time_grants WHERE token_id=? AND day=?", (token_id, day)).fetchone()[0]
