import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models.schemas import ErrorCode

TOKEN = "test-token-123"
H = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client():
    s = Settings(access_token=TOKEN, db_path=":memory:", use_mock_adapters=True)
    with TestClient(create_app(s)) as c:
        yield c


def cmd(rid, action="key_press", **params):
    return {"target": "x", "action": action, "params": params, "request_id": rid}


def add_paired(client, kind="lg"):
    d = client.post("/api/devices", json={"kind": kind, "host": "192.168.1.20"}, headers=H).json()
    code = "123456" if kind == "hot" else ""
    assert client.post(f"/api/devices/{d['id']}/pair/confirm", json={"code": code}, headers=H).status_code == 200
    return d["id"]


def test_requires_auth(client):
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/health", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/health", headers=H).json()["ok"] is True


def test_add_validates_host(client):
    r = client.post("/api/devices", json={"kind": "hot", "host": "not-an-ip; rm -rf"}, headers=H)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_COMMAND"
    assert client.post("/api/devices", json={"kind": "hot", "host": "192.168.1.5"}, headers=H).status_code == 201
    assert client.post("/api/devices", json={"kind": "hot", "host": "192.168.1.5"}, headers=H).status_code == 409


def test_unpaired_rejects_commands(client):
    d = client.post("/api/devices", json={"kind": "lg", "host": "192.168.1.9"}, headers=H).json()
    assert d["connection"] == "unpaired"
    r = client.post(f"/api/devices/{d['id']}/commands", json=cmd("req-00000001", key="HOME"), headers=H)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NOT_PAIRED"


def test_wrong_pair_code_denied(client):
    d = client.post("/api/devices", json={"kind": "hot", "host": "192.168.1.7"}, headers=H).json()
    r = client.post(f"/api/devices/{d['id']}/pair/confirm", json={"code": "000000"}, headers=H)
    assert r.json()["detail"]["code"] == "DENIED"


def test_command_sent_and_deduped(client):
    did = add_paired(client, "hot")
    body = cmd("req-00000002", key="KEYCODE_1")
    assert client.post(f"/api/devices/{did}/commands", json=body, headers=H).json()["status"] == "sent"
    assert client.post(f"/api/devices/{did}/commands", json=body, headers=H).json()["status"] == "duplicate"
    adapter = client.app.state.manager.adapters[did]
    assert adapter.sent == [("key_press", {"key": "KEYCODE_1"})]


def test_key_allowlist_per_kind(client):
    did = add_paired(client, "lg")
    r = client.post(f"/api/devices/{did}/commands", json=cmd("req-00000003", key="KEYCODE_1"), headers=H)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_COMMAND"
    r = client.post(f"/api/devices/{did}/commands", json=cmd("req-00000004", key="rm -rf"), headers=H)
    assert r.status_code == 422


def test_lg_only_actions_on_hot_are_unsupported(client):
    did = add_paired(client, "hot")
    r = client.post(f"/api/devices/{did}/commands", json=cmd("req-00000005", "power_off"), headers=H)
    assert r.json()["detail"]["code"] == "UNSUPPORTED"


def test_param_validation(client):
    did = add_paired(client, "lg")
    for body in (cmd("req-00000006", "set_input", input="HDMI_9"), cmd("req-00000007", "launch_app", app="evil"),
                 cmd("req-00000008", "key_press")):
        assert client.post(f"/api/devices/{did}/commands", json=body, headers=H).status_code == 422
    ok = client.post(f"/api/devices/{did}/commands", json=cmd("req-00000009", "set_input", input="HDMI_2"), headers=H)
    assert ok.status_code == 200


def test_adapter_failure_not_reported_as_success(client):
    did = add_paired(client, "lg")
    client.app.state.manager.adapters[did].fail_with = ErrorCode.TIMEOUT
    r = client.post(f"/api/devices/{did}/commands", json=cmd("req-0000000a", "mute"), headers=H)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "TIMEOUT"


def test_real_adapters_never_fake_success():
    s = Settings(access_token=TOKEN, db_path=":memory:", use_mock_adapters=False)
    with TestClient(create_app(s)) as c:
        d = c.post("/api/devices", json={"kind": "hot", "host": "192.168.1.30"}, headers=H).json()
        assert d["connection"] == "unpaired"
        r = c.post(f"/api/devices/{d['id']}/commands", json=cmd("req-0000000b", key="HOME"), headers=H)
        assert r.json()["detail"]["code"] == "NOT_PAIRED"


def test_rate_limit(client):
    did = add_paired(client, "lg")
    codes = [client.post(f"/api/devices/{did}/commands", json=cmd(f"req-rl{i:06d}", "mute"), headers=H).status_code
             for i in range(65)]
    assert 429 in codes and codes[0] == 200


def test_websocket_auth(client):
    with client.websocket_connect("/ws/status") as ws:
        ws.send_text('{"token": "bad"}')
        with pytest.raises(Exception):
            ws.receive_text()
    with client.websocket_connect("/ws/status") as ws:
        ws.send_text(f'{{"token": "{TOKEN}"}}')
        assert ws.receive_json()["type"] == "devices"


def test_add_rejects_non_lan_hosts(client):
    for host in ("8.8.8.8", "127.0.0.1", "0.0.0.0"):
        assert client.post("/api/devices", json={"kind": "hot", "host": host}, headers=H).status_code == 422


def test_diagnostics_endpoint(client):
    did = add_paired(client, "hot")
    r = client.get(f"/api/devices/{did}/diagnostics", headers=H)
    assert r.status_code == 200 and r.json()["connection"] == "connected"
    assert client.get("/api/devices/nope/diagnostics", headers=H).status_code == 404


def test_missing_token_is_not_counted_as_a_guess(client):
    codes = [client.get("/api/health").status_code for _ in range(30)]
    assert set(codes) == {401}  # never escalates to 429
    assert client.get("/api/health", headers=H).status_code == 200  # the real owner is not locked out


def test_auth_bruteforce_throttle(client):
    codes = [client.get("/api/health", headers={"Authorization": f"Bearer bad{i}"}).status_code for i in range(12)]
    assert codes[:10] == [401] * 10 and codes[10] == 429
    assert client.get("/api/health", headers=H).status_code == 429  # even the right token waits out the window


def test_throttle_uses_real_client_ip_behind_proxy():
    s = Settings(access_token=TOKEN, db_path=":memory:", use_mock_adapters=True, trust_proxy=True)
    with TestClient(create_app(s), client=("127.0.0.1", 50000)) as c:  # the IIS proxy is the direct peer
        for i in range(10):
            c.get("/api/health", headers={"Authorization": "Bearer bad", "X-Forwarded-For": f"1.1.1.1, 9.9.9.{i}"})
        # distinct real IPs (last entry) must not share one bucket: an owner on another IP is not locked out
        assert c.get("/api/health", headers={**H, "X-Forwarded-For": "5.5.5.5"}).status_code == 200


def test_menu_keys_accepted_per_device_type_and_not_across(client):
    tv, box = add_paired(client, "lg"), None
    d = client.post("/api/devices", json={"kind": "hot", "host": "192.168.1.88"}, headers=H).json()
    client.post(f"/api/devices/{d['id']}/pair/confirm", json={"code": "123456"}, headers=H)
    box = d["id"]
    ok = lambda did, k, n: client.post(f"/api/devices/{did}/commands", json={"target": did, "action": "key_press", "params": {"key": k}, "request_id": f"req-menu-{n:04d}"}, headers=H).status_code
    assert ok(tv, "MENU", 1) == 200 and ok(tv, "QMENU", 2) == 200 and ok(tv, "EXIT", 3) == 200
    assert ok(box, "SETTINGS", 4) == 200 and ok(box, "GUIDE", 5) == 200
    assert ok(tv, "SETTINGS", 6) == 422 and ok(box, "QMENU", 7) == 422  # each device only accepts its own keys
