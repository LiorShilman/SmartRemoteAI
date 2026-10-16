"""Kids mode: server-enforced policy on an access code, screen-time usage, and "more time" requests."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

MASTER = "master-token-123"
H = {"Authorization": f"Bearer {MASTER}"}
POLICY = {"start": "07:00", "end": "21:00", "apps": ["youtube", "spotify"], "can_power_off": False,
          "can_schedule": False, "daily_limit_min": 60}


def at(h, m=0):
    return datetime(2026, 10, 16, h, m)


@pytest.fixture
def client():
    with TestClient(create_app(Settings(access_token=MASTER, db_path=":memory:", use_mock_adapters=True))) as c:
        c.app.state.clock = lambda: at(15)
        yield c


def kid(client, policy=None, name="נועה"):
    r = client.post("/api/tokens", json={"name": name, "policy": POLICY if policy is None else policy}, headers=H)
    assert r.status_code == 201, r.text
    t = r.json()
    return {"Authorization": f"Bearer {t['token']}"}, t


def devices(client):
    ids = {}
    for kind, host in (("lg", "192.168.1.40"), ("hot", "192.168.1.41")):
        d = client.post("/api/devices", json={"kind": kind, "host": host}, headers=H).json()
        client.post(f"/api/devices/{d['id']}/pair/confirm", json={"code": "123456"}, headers=H)
        ids[kind] = d["id"]
    return ids


_n = 0


def cmd(client, hdr, did, action, **params):
    global _n
    _n += 1
    return client.post(f"/api/devices/{did}/commands", json={"target": did, "action": action, "params": params, "request_id": f"req-kid-{_n:06d}"}, headers=hdr)


def reason(r):
    return r.json()["detail"]["message"]


# ------------------------------------------------------------------ hours
def test_commands_only_inside_the_allowed_window(client):
    ids = devices(client)
    hdr, _ = kid(client)
    assert cmd(client, hdr, ids["lg"], "volume_up").status_code == 200
    client.app.state.clock = lambda: at(6, 59)
    r = cmd(client, hdr, ids["lg"], "volume_up")
    assert r.status_code == 403 and "07:00–21:00" in reason(r) and r.json()["detail"]["code"] == "DENIED"
    client.app.state.clock = lambda: at(21, 0)
    assert cmd(client, hdr, ids["lg"], "mute").status_code == 403
    client.app.state.clock = lambda: at(20, 59)
    assert cmd(client, hdr, ids["lg"], "mute").status_code == 200


def test_the_admin_code_is_never_restricted(client):
    ids = devices(client)
    client.app.state.clock = lambda: at(3)
    assert cmd(client, H, ids["lg"], "power_off").status_code == 200


# ------------------------------------------------------------------ what a kid may do
def test_only_allowed_apps_can_be_opened_or_searched(client):
    ids = devices(client)
    hdr, _ = kid(client)
    assert cmd(client, hdr, ids["hot"], "launch_app", app="youtube").status_code == 200
    r = cmd(client, hdr, ids["hot"], "launch_app", app="netflix")
    assert r.status_code == 403 and "Netflix" in reason(r)
    assert cmd(client, hdr, ids["hot"], "search", app="netflix", query="x").status_code == 403
    assert cmd(client, hdr, ids["hot"], "search", app="youtube", query="x").status_code == 200


def test_power_and_scheduling_need_explicit_permission(client):
    ids = devices(client)
    hdr, t = kid(client)
    assert cmd(client, hdr, ids["lg"], "power_off").status_code == 403
    body = {"target": "lg", "action": "mute", "delay_seconds": 600}
    assert client.post("/api/schedule", json=body, headers=hdr).status_code == 403
    assert client.post("/api/schedule/clear", json={}, headers=hdr).status_code == 403
    client.patch(f"/api/tokens/{t['id']}", json={"policy": {**POLICY, "can_power_off": True, "can_schedule": True}}, headers=H)
    assert cmd(client, hdr, ids["lg"], "power_off").status_code == 200
    assert client.post("/api/schedule", json=body, headers=hdr).status_code == 201


def test_a_scheduled_action_must_also_be_allowed_when_it_will_run(client):
    ids = devices(client)
    hdr, t = kid(client, {**POLICY, "can_schedule": True})
    client.app.state.clock = lambda: at(20, 30)
    ok = client.post("/api/schedule", json={"target": "lg", "action": "mute", "delay_seconds": 600}, headers=hdr)
    late = client.post("/api/schedule", json={"target": "lg", "action": "mute", "delay_seconds": 3600}, headers=hdr)  # 21:30
    assert ok.status_code == 201 and late.status_code == 403


def test_pointer_is_navigation_and_follows_the_same_rules(client):
    ids = devices(client)
    hdr, _ = kid(client)
    assert client.post(f"/api/devices/{ids['lg']}/pointer", json={"dx": 3}, headers=hdr).status_code == 204
    client.app.state.clock = lambda: at(23)
    assert client.post(f"/api/devices/{ids['lg']}/pointer", json={"dx": 3}, headers=hdr).status_code == 403


def test_management_stays_admin_only_for_restricted_codes(client):
    hdr, _ = kid(client)
    assert client.post("/api/devices", json={"kind": "lg", "host": "192.168.1.9"}, headers=hdr).status_code == 403
    assert client.get("/api/tokens", headers=hdr).status_code == 403
    assert client.get("/api/usage", headers=hdr).status_code == 403


# ------------------------------------------------------------------ daily limit and screen time
def test_daily_limit_blocks_everything_except_turning_it_down_or_off(client):
    ids = devices(client)
    hdr, _ = kid(client, {**POLICY, "can_power_off": False})
    client.app.state.usage.add("2026-10-16", "*", "ALL", 61 * 60)  # 61 minutes watched today
    r = cmd(client, hdr, ids["hot"], "launch_app", app="youtube")
    assert r.status_code == 403 and "מכסת הזמן" in reason(r)
    assert cmd(client, hdr, ids["lg"], "volume_up").status_code == 403
    assert cmd(client, hdr, ids["lg"], "volume_down").status_code == 200
    assert cmd(client, hdr, ids["lg"], "mute").status_code == 200
    assert cmd(client, hdr, ids["lg"], "power_off").status_code == 200  # ending the session is always allowed


def test_usage_is_sampled_per_app_and_counted_once_per_sample(client):
    import asyncio
    ids = devices(client)
    mgr = client.app.state.manager
    mgr.adapters[ids["lg"]].foreground_app = "YouTube"
    mgr.adapters[ids["hot"]].foreground_app = "Netflix"   # both screens "on": still one sample of screen time
    asyncio.run(mgr.sample_usage("2026-10-16"))
    asyncio.run(mgr.sample_usage("2026-10-16"))
    mgr.adapters[ids["hot"]].foreground_app = None        # box idle, TV still on
    asyncio.run(mgr.sample_usage("2026-10-16"))
    u = client.get("/api/usage?days=1", headers=H).json()
    assert u["today_min"] == 2  # 3 samples x 30s = 90s = 1.5 min, rounded
    assert client.app.state.usage.total_seconds("2026-10-16") == 90
    day = client.app.state.usage.by_day("2026-10-16")["2026-10-16"]
    assert day["apps"] == {"YouTube": 90, "Netflix": 60} and day["total"] == 90


def test_usage_report_returns_every_day_oldest_first(client):
    client.app.state.usage.add("2026-10-14", "*", "ALL", 1800)
    client.app.state.usage.add("2026-10-14", "d1", "Netflix", 1800)
    u = client.get("/api/usage?days=3", headers=H).json()
    assert [d["day"] for d in u["days"]] == ["2026-10-14", "2026-10-15", "2026-10-16"]
    assert u["days"][0]["total_min"] == 30 and u["days"][0]["apps"] == {"Netflix": 30} and u["days"][1]["total_min"] == 0


# ------------------------------------------------------------------ asking for more time
def test_request_approve_extends_both_the_window_and_the_limit(client):
    ids = devices(client)
    hdr, t = kid(client)
    client.app.state.clock = lambda: at(20, 55)
    client.app.state.usage.add("2026-10-16", "*", "ALL", 60 * 60)           # limit used up
    assert cmd(client, hdr, ids["hot"], "launch_app", app="youtube").status_code == 403
    r = client.post("/api/requests", json={"minutes": 30}, headers=hdr)
    assert r.status_code == 201 and r.json()["status"] == "pending"
    assert client.get("/api/me", headers=hdr).json()["request_status"] == "pending"
    assert client.get("/api/me", headers=H).json()["pending_requests"] == 1
    rid = r.json()["id"]
    d = client.post(f"/api/requests/{rid}/decide", json={"approve": True}, headers=H).json()
    assert d["status"] == "approved" and d["granted_minutes"] == 30
    client.app.state.clock = lambda: at(21, 20)                              # past 21:00, but 30 extra minutes were granted
    assert cmd(client, hdr, ids["hot"], "launch_app", app="youtube").status_code == 200
    client.app.state.clock = lambda: at(21, 31)                              # extra time is over
    assert cmd(client, hdr, ids["hot"], "launch_app", app="youtube").status_code == 403
    me = client.get("/api/me", headers=hdr).json()
    assert me["extra_min"] == 30 and me["request_status"] == "approved"


def test_a_parent_can_grant_a_different_amount_or_deny(client):
    hdr, _ = kid(client)
    a = client.post("/api/requests", json={"minutes": 60}, headers=hdr).json()
    assert client.post(f"/api/requests/{a['id']}/decide", json={"approve": True, "minutes": 15}, headers=H).json()["granted_minutes"] == 15
    b = client.post("/api/requests", json={"minutes": 30}, headers=hdr).json()
    d = client.post(f"/api/requests/{b['id']}/decide", json={"approve": False}, headers=H).json()
    assert d["status"] == "denied" and d["granted_minutes"] == 0
    assert client.get("/api/me", headers=hdr).json()["extra_min"] == 15
    # a decision is final: it cannot be decided twice
    assert client.post(f"/api/requests/{b['id']}/decide", json={"approve": True}, headers=H).status_code == 404


def test_request_rules(client):
    hdr, _ = kid(client)
    assert client.post("/api/requests", json={"minutes": 45}, headers=hdr).status_code == 422       # fixed choices only
    for _ in range(3):
        assert client.post("/api/requests", json={"minutes": 15}, headers=hdr).status_code == 201
    assert client.post("/api/requests", json={"minutes": 15}, headers=hdr).status_code == 429       # no spamming
    assert client.post("/api/requests", json={"minutes": 15}, headers=H).status_code == 422         # admin has no limits to lift
    plain = client.post("/api/tokens", json={"name": "מבוגר"}, headers=H).json()["token"]
    assert client.post("/api/requests", json={"minutes": 15}, headers={"Authorization": f"Bearer {plain}"}).status_code == 422
    assert client.get("/api/requests", headers=hdr).status_code == 403                                # kids cannot read or decide
    rid = client.get("/api/requests", headers=H).json()[0]["id"]
    assert client.post(f"/api/requests/{rid}/decide", json={"approve": True}, headers=hdr).status_code == 403


# ------------------------------------------------------------------ policy management and audit
def test_policy_validation(client):
    bad = [{**POLICY, "start": "9:00"}, {**POLICY, "start": "21:00", "end": "07:00"}, {**POLICY, "end": "25:00"},
           {**POLICY, "apps": ["tiktok"]}, {**POLICY, "daily_limit_min": 5}, {**POLICY, "daily_limit_min": 5000}, {**POLICY, "evil": True}]
    for p in bad:
        assert client.post("/api/tokens", json={"name": "x", "policy": p}, headers=H).status_code == 422, p


def test_policy_can_be_changed_and_removed_and_applies_immediately(client):
    ids = devices(client)
    hdr, t = kid(client)
    assert cmd(client, hdr, ids["hot"], "launch_app", app="netflix").status_code == 403
    client.patch(f"/api/tokens/{t['id']}", json={"policy": {**POLICY, "apps": ["netflix"]}}, headers=H)
    assert cmd(client, hdr, ids["hot"], "launch_app", app="netflix").status_code == 200
    out = client.patch(f"/api/tokens/{t['id']}", json={"policy": None}, headers=H).json()
    assert out["policy"] is None
    client.app.state.clock = lambda: at(3)
    assert cmd(client, hdr, ids["lg"], "volume_up").status_code == 200                                # unrestricted now
    assert client.patch("/api/tokens/nope", json={"policy": None}, headers=H).status_code == 404


def test_denials_and_requests_are_audited_once_per_minute(client):
    ids = devices(client)
    hdr, _ = kid(client)
    for _ in range(5):
        cmd(client, hdr, ids["hot"], "launch_app", app="netflix")
    client.post("/api/requests", json={"minutes": 15}, headers=hdr)
    ev = [(a["event"]) for a in client.get("/api/audit", headers=H).json()]
    assert ev.count("policy_denied") == 1 and "time_requested" in ev and "token_created" in ev


def test_me_describes_the_kids_day(client):
    hdr, _ = kid(client)
    client.app.state.usage.add("2026-10-16", "*", "ALL", 25 * 60)
    me = client.get("/api/me", headers=hdr).json()
    assert me["kind"] == "device" and me["policy"]["end"] == "21:00"
    assert me["used_min"] == 25 and me["remaining_min"] == 35 and me["window_open"] is True and me["pending_requests"] is None
    client.app.state.clock = lambda: at(22)
    assert client.get("/api/me", headers=hdr).json()["window_open"] is False


def test_old_database_without_a_policy_column_is_migrated(tmp_path):
    import sqlite3
    from app.storage.security import TokenStore
    db = sqlite3.connect(tmp_path / "old.db", check_same_thread=False)
    db.execute("CREATE TABLE tokens (id TEXT PRIMARY KEY, name TEXT NOT NULL, hash TEXT NOT NULL UNIQUE, prefix TEXT NOT NULL,"
               " created_at REAL NOT NULL, last_used_at REAL, last_ip TEXT, revoked_at REAL)")
    db.execute("INSERT INTO tokens VALUES ('a','old','h','sr_x',1,NULL,NULL,NULL)")
    db.commit()
    import threading
    s = TokenStore(db, threading.Lock())
    assert s.get("a").policy is None and s.set_policy("a", {"start": "07:00"}) and s.get("a").policy == {"start": "07:00"}
