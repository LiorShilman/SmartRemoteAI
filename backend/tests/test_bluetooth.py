"""Bluetooth pairing: one fixed action, sent only when not visible, success only when the speaker reports it."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services import zeppelin
from app.services.zeppelin import ZeppelinClient
from tests.test_zeppelin import FakeSpeaker, H, MASTER


class BtSpeaker(FakeSpeaker):
    def __init__(self):
        super().__init__()
        self.bt = {"discoverable": False, "address": "b0:67:2f:51:dc:63", "connected": True, "name": "Living Room",
                   "activeDevice": "9c:9e:d5:75:1c:91", "discovering": False, "pairable": False,
                   "pairedDevices": [{"address": "9c:9e:d5:75:1c:91", "name": "POCO X7 Pro", "btClass": 7936, "rssi": 0}],
                   "connectedDevice": {"address": "9c:9e:d5:75:1c:91", "name": "POCO X7 Pro", "btClass": 7936, "rssi": 0}}
        self.activations: list[dict] = []
        self.activate_works = True
        self.activate_error = False

    def handler(self, request):
        if self.unreachable:
            return super().handler(request)
        if request.url.path == "/api/getData" and request.url.params.get("path") == "bluetooth:state":
            self.requests.append(request)
            return httpx.Response(200, json=[{"type": "bluetoothState", "bluetoothState": self.bt}])
        if request.method == "POST" and request.url.path == "/api/setData":
            self.requests.append(request)
            body = json.loads(request.content)
            self.activations.append(body)
            if self.activate_error:
                return httpx.Response(200, json={"error": {"message": "Action failed"}})
            if self.activate_works and body["path"] == "bluetooth:deviceList/discoverable":
                self.bt = {**self.bt, "discoverable": True, "pairable": True}
            return httpx.Response(200, content=b"null")
        return super().handler(request)


@pytest.fixture
def fake():
    return BtSpeaker()


@pytest.fixture
def client(fake, monkeypatch):
    monkeypatch.setattr(zeppelin, "BT_CONFIRM_S", 1.0)
    app = create_app(Settings(access_token=MASTER, db_path=":memory:", use_mock_adapters=True))
    app.state.speaker = ZeppelinClient("192.168.1.52", transport=httpx.MockTransport(fake.handler))
    with TestClient(app) as c:
        yield c


def test_reading_state_sends_nothing(client, fake):
    r = client.get("/api/speaker/bluetooth", headers=H)
    assert r.status_code == 200
    assert r.json() == {"name": "Living Room", "discoverable": False, "pairable": False, "connected_device": "POCO X7 Pro",
                        "paired": ["POCO X7 Pro"], "sent": None}
    assert fake.activations == [] and fake.sets() == []


def test_open_pairing_sends_the_verified_action_and_confirms(client, fake):
    r = client.post("/api/speaker/bluetooth/pairing", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["discoverable"] is True and r.json()["sent"] is True
    assert fake.activations == [{"path": "bluetooth:deviceList/discoverable", "role": "activate", "value": {}}]


def test_already_visible_sends_nothing(client, fake):
    fake.bt["discoverable"] = True
    r = client.post("/api/speaker/bluetooth/pairing", headers=H)
    assert r.status_code == 200 and r.json()["sent"] is False and r.json()["discoverable"] is True
    assert fake.activations == []


def test_no_false_success(client, fake):
    fake.activate_works = False  # HTTP 200 null, but the speaker never becomes visible
    r = client.post("/api/speaker/bluetooth/pairing", headers=H)
    assert r.status_code == 502 and "לא דיווח" in r.json()["detail"]["message"]
    fake.activate_error = True  # HTTP 200 with an error body
    r = client.post("/api/speaker/bluetooth/pairing", headers=H)
    assert r.status_code == 502 and "Action failed" in r.json()["detail"]["message"]


def test_auth_kids_and_unreachable(client, fake):
    assert client.post("/api/speaker/bluetooth/pairing").status_code == 401
    policy = {"start": "00:00", "end": "23:59", "apps": [], "daily_limit_min": None, "can_power_off": False, "can_schedule": False}
    t = client.post("/api/tokens", json={"name": "ילד", "policy": policy}, headers=H).json()["token"]
    assert client.post("/api/speaker/bluetooth/pairing", headers={"Authorization": f"Bearer {t}"}).status_code == 403
    assert fake.activations == []
    fake.unreachable = True
    assert client.post("/api/speaker/bluetooth/pairing", headers=H).status_code == 503
