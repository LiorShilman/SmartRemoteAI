"""Per-device access tokens, audit log, and the optional network allowlist."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

MASTER = "master-token-123"
H = {"Authorization": f"Bearer {MASTER}"}


def make(**kw):
    return create_app(Settings(access_token=MASTER, db_path=":memory:", use_mock_adapters=True, **kw))


@pytest.fixture
def client():
    with TestClient(make()) as c:
        yield c


def new_token(client, name="הטלפון של דנה"):
    r = client.post("/api/tokens", json={"name": name}, headers=H)
    assert r.status_code == 201
    return r.json()


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def events(client):
    return [(a["event"], a["who"]) for a in client.get("/api/audit", headers=H).json()]


def test_device_token_works_and_is_returned_only_once(client):
    t = new_token(client)
    assert t["token"].startswith("sr_") and len(t["token"]) > 40 and t["prefix"] == t["token"][:7]
    assert client.get("/api/health", headers=bearer(t["token"])).status_code == 200
    listed = client.get("/api/tokens", headers=H).json()
    assert listed[0]["id"] == t["id"] and "token" not in listed[0] and listed[0]["revoked"] is False


def test_secret_is_stored_only_as_a_hash(client):
    t = new_token(client)
    db: sqlite3.Connection = client.app.state.tokens._db
    stored = db.execute("SELECT hash, prefix FROM tokens").fetchone()
    assert t["token"] not in stored[0] and stored[0] != t["token"] and len(stored[0]) == 64
    assert not any(t["token"] in str(row) for row in db.execute("SELECT * FROM tokens"))


def test_revoked_token_stops_working_immediately(client):
    t = new_token(client)
    assert client.get("/api/health", headers=bearer(t["token"])).status_code == 200
    assert client.delete(f"/api/tokens/{t['id']}", headers=H).json()["revoked"] is True
    assert client.get("/api/health", headers=bearer(t["token"])).status_code == 401
    assert client.delete(f"/api/tokens/{t['id']}", headers=H).status_code == 404  # already revoked
    assert client.get("/api/health", headers=H).status_code == 200  # master unaffected


def test_device_token_cannot_manage_access_or_devices(client):
    t = bearer(new_token(client)["token"])
    for method, path, body in [("get", "/api/tokens", None), ("post", "/api/tokens", {"name": "x"}),
                               ("get", "/api/audit", None), ("post", "/api/devices", {"kind": "lg", "host": "192.168.1.5"}),
                               ("post", "/api/devices/discover", None)]:
        r = client.request(method, path, json=body, headers=t)
        assert r.status_code == 403, (path, r.status_code)
        assert r.json()["detail"]["code"] == "DENIED"
    assert client.get("/api/devices", headers=t).status_code == 200       # but day-to-day use works
    assert client.get("/api/schedule", headers=t).status_code == 200
    assert client.get("/api/me", headers=t).json() == {"kind": "device", "name": "הטלפון של דנה"}
    assert client.get("/api/me", headers=H).json()["kind"] == "admin"


def test_device_token_can_send_commands_but_not_pair(client):
    did = client.post("/api/devices", json={"kind": "lg", "host": "192.168.1.5"}, headers=H).json()["id"]
    client.post(f"/api/devices/{did}/pair/confirm", json={"code": ""}, headers=H)
    t = bearer(new_token(client)["token"])
    body = {"target": did, "action": "mute", "request_id": "req-sec-0001", "params": {}}
    assert client.post(f"/api/devices/{did}/commands", json=body, headers=t).status_code == 200
    assert client.post(f"/api/devices/{did}/pair/start", headers=t).status_code == 403
    assert client.delete(f"/api/devices/{did}", headers=t).status_code == 403


def test_last_use_and_new_location_are_tracked(client):
    t = new_token(client)
    client.get("/api/health", headers=bearer(t["token"]))
    row = client.get("/api/tokens", headers=H).json()[0]
    assert row["last_used_at"] is not None and row["last_ip"] == "testclient"
    # same token from another place -> flagged
    app = client.app
    with TestClient(app, client=("203.0.113.9", 4000)) as other:
        other.get("/api/health", headers=bearer(t["token"]))
    assert client.get("/api/tokens", headers=H).json()[0]["last_ip"] == "203.0.113.9"
    assert any(e == "new_ip" and w == "הטלפון של דנה" for e, w in events(client))


def test_audit_log_records_security_relevant_events_only(client):
    t = new_token(client)
    client.delete(f"/api/tokens/{t['id']}", headers=H)
    client.get("/api/health", headers=bearer("wrong"))
    did = client.post("/api/devices", json={"kind": "hot", "host": "192.168.1.6"}, headers=H).json()["id"]
    client.post(f"/api/devices/{did}/pair/confirm", json={"code": "123456"}, headers=H)
    for i, (action, params) in enumerate([("key_press", {"key": "HOME"}), ("volume_up", {}), ("digits", {"digits": "12", "delay_ms": 50})]):
        client.post(f"/api/devices/{did}/commands", json={"target": did, "action": action, "params": params, "request_id": f"req-aud-{i:04d}"}, headers=H)
    names = [e for e, _ in events(client)]
    assert {"token_created", "token_revoked", "login_failed", "device_added", "device_paired"} <= set(names)
    assert names.count("command") == 1  # only the channel change; navigation and volume are not logged
    assert not any("sr_" in a["detail"] for a in client.get("/api/audit", headers=H).json())  # never a secret


def test_login_failures_are_audited_once_per_minute_per_ip(client):
    for i in range(6):
        client.get("/api/health", headers=bearer(f"wrong{i}"))
    assert [e for e, _ in events(client)].count("login_failed") == 1


def test_audit_is_bounded():
    from app.storage import security
    with TestClient(make()) as c:
        a = c.app.state.audit
        for i in range(security.AUDIT_KEEP + 50):
            a.add("1.1.1.1", "x", "command", str(i))
        rows = c.get("/api/audit?limit=200", headers=H).json()
        assert len(rows) == 200 and rows[0]["detail"] == str(security.AUDIT_KEEP + 49)
        assert c.app.state.audit._db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] <= security.AUDIT_KEEP + 1


def test_token_name_validation(client):
    assert client.post("/api/tokens", json={"name": "   "}, headers=H).status_code == 422
    assert client.post("/api/tokens", json={"name": "x" * 41}, headers=H).status_code == 422
    assert client.post("/api/tokens", json={"name": "ok", "role": "admin"}, headers=H).status_code == 422


def test_throttle_still_blocks_guessing_even_for_valid_tokens(client):
    t = new_token(client)["token"]
    for i in range(10):
        client.get("/api/health", headers=bearer(f"nope{i}"))
    assert client.get("/api/health", headers=bearer(t)).status_code == 429


# ------------------------------------------------------------------ optional network allowlist
def test_allowlist_blocks_other_networks_and_audits_it():
    app = make(allowed_cidrs=["192.168.1.0/24", "10.0.0.0/8"])
    with TestClient(app, client=("192.168.1.77", 1)) as inside:
        assert inside.get("/api/health", headers=H).status_code == 200
    with TestClient(app, client=("8.8.8.8", 1)) as outside:
        r = outside.get("/api/health", headers=H)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "DENIED"
        assert outside.get("/api/health").status_code == 403  # blocked before authentication, even without a code
    with TestClient(app, client=("127.0.0.1", 1)) as local:  # loopback (the IIS proxy / local admin) is never locked out
        assert local.get("/api/health", headers=H).status_code == 200
        assert any(a["event"] == "blocked_ip" for a in local.get("/api/audit", headers=H).json())


def test_allowlist_uses_the_real_client_ip_behind_the_proxy():
    app = make(allowed_cidrs=["192.168.1.0/24"], trust_proxy=True)
    with TestClient(app, client=("127.0.0.1", 1)) as proxy:
        assert proxy.get("/api/health", headers={**H, "X-Forwarded-For": "192.168.1.20"}).status_code == 200
        assert proxy.get("/api/health", headers={**H, "X-Forwarded-For": "8.8.8.8"}).status_code == 403
        # a forged first entry cannot smuggle a blocked address in: only the proxy-appended LAST entry counts
        assert proxy.get("/api/health", headers={**H, "X-Forwarded-For": "192.168.1.20, 8.8.8.8"}).status_code == 403


def test_bad_cidr_fails_at_startup():
    with pytest.raises(ValueError):
        make(allowed_cidrs=["not-a-network"])


def test_websocket_accepts_device_tokens_and_rejects_revoked(client):
    t = new_token(client)
    with client.websocket_connect("/ws/status") as ws:
        ws.send_text(f'{{"token": "{t["token"]}"}}')
        assert ws.receive_json()["type"] == "devices"
    client.delete(f"/api/tokens/{t['id']}", headers=H)
    with client.websocket_connect("/ws/status") as ws:
        ws.send_text(f'{{"token": "{t["token"]}"}}')
        with pytest.raises(Exception):
            ws.receive_text()


def test_purge_removes_only_revoked_tokens(client):
    keep, gone1, gone2 = new_token(client, "פעיל"), new_token(client, "ישן 1"), new_token(client, "ישן 2")
    for t in (gone1, gone2):
        client.delete(f"/api/tokens/{t['id']}", headers=H)
    # exactly the selected revoked one; an active id in the list is ignored
    assert client.post("/api/tokens/clear", json={"ids": [gone1["id"], keep["id"]]}, headers=H).json() == {"removed": 1}
    assert {t["name"] for t in client.get("/api/tokens", headers=H).json()} == {"פעיל", "ישן 2"}
    assert client.post("/api/tokens/clear", json={}, headers=H).json() == {"removed": 1}
    assert [t["name"] for t in client.get("/api/tokens", headers=H).json()] == ["פעיל"]
    assert client.get("/api/health", headers=bearer(keep["token"])).status_code == 200  # still works
    assert client.post("/api/tokens/clear", json={"ids": ["x"] * 51}, headers=H).status_code == 422
    assert client.post("/api/tokens/clear", json={}, headers=bearer(keep["token"])).status_code == 403  # admin only


