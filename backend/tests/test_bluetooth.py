"""Bluetooth pairing: one fixed action, sent only when not visible, success only when the speaker reports it."""
import json
import re
from urllib.parse import parse_qs, urlsplit

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
        self.values["settings:/bluetooth/bluetoothPairingTimeout"] = {"type": "i32_", "i32_": 300}
        # paired devices by address -> (name, sections); plus one only seen nearby ("New devices", not paired)
        self.devs = {"44_f7_9f_f5_f3_98": ("DESKTOP-TM1E1QQ", ["section1", "section2"]),
                     "24_e8_53_85_c8_7d": ("LG TV[TV]", ["section1"]),
                     "9c_9e_d5_75_1c_91": ("POCO X7 Pro", ["section1"])}
        self.nearby = {"aa_bb_cc_dd_ee_ff": "POCO X7 Pro"}
        self.unpair_works = True

    def menu(self):
        """ui:/bluetooth rows exactly in the shape the real speaker returned (title, value, path, type, disabled)."""
        rows = [["Visible to other devices", None, "bluetooth:deviceList/discoverable", "action", None],
                ["Scan for other Bluetooth devices", None, "bluetooth:deviceList/discovery", "action", None]]
        for sec, head in (("section1", "Inputs"), ("section2", "Speakers")):
            rows.append([head, None, f"bluetooth:deviceList/{sec}", "header", None])
            rows += [[n, None, f"bluetooth:devices/{a}/{sec}", "container", None]
                     for a, (n, secs) in self.devs.items() if sec in secs]
        rows.append(["New devices", None, "bluetooth:deviceList/section3", "header", None])
        rows += [[n, None, f"bluetooth:devices/{a}/section3", "container", None] for a, n in self.nearby.items()]
        return rows

    def rows_for(self, path):
        if path == "ui:/bluetooth":
            return self.menu()
        m = re.match(r"^bluetooth:devices/([^/]+)/section(\d)$", path or "")
        if m and (m.group(1) in self.devs or m.group(1) in self.nearby):
            a = m.group(1)
            first = (["Pair", None, f"bluetooth:devices/{a}/pair", "action", None] if m.group(2) == "3"
                     else ["Play", None, f"bluetooth:devices/{a}/play", "action", None])
            return [first, ["Disconnect", None, f"bluetooth:devices/{a}/disconnect", "action", True],
                    ["Unpair", None, f"bluetooth:devices/{a}/unpair", "action", None]]
        return None

    def handler(self, request):
        if self.unreachable:
            return super().handler(request)
        if request.url.path == "/api/getRows":
            self.requests.append(request)
            q = {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}
            rows = self.rows_for(q["path"])
            if rows is None:
                return httpx.Response(200, json={"error": {"message": "invalid path"}})
            lo, hi = int(q["from"]), int(q["to"])
            return httpx.Response(200, json={"roles": [], "rows": rows[lo:hi + 1], "rowsVersion": 0, "rowsCount": len(rows)})
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
            m = re.match(r"^bluetooth:devices/([^/]+)/unpair$", body["path"])
            if m and self.unpair_works:
                if m.group(1) not in self.devs:
                    return httpx.Response(500, json={"error": {"message": "not paired"}})
                del self.devs[m.group(1)]
                return httpx.Response(200, json={"events": [{"path": f"bluetooth:devices/{m.group(1)}", "rowsType": "remove"}]})
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
    d = r.json()
    assert {k: d[k] for k in ("name", "discoverable", "pairable", "connected_device", "paired", "pairing_seconds", "sent")} == {
        "name": "Living Room", "discoverable": False, "pairable": False, "connected_device": "POCO X7 Pro",
        "paired": ["POCO X7 Pro"], "pairing_seconds": 300, "sent": None}
    # paired devices from the speaker's menu; the device seen only nearby ("New devices") is not listed
    assert [(x["name"], x["roles"]) for x in d["devices"]] == [
        ("DESKTOP-TM1E1QQ", ["input", "speaker"]), ("LG TV[TV]", ["input"]), ("POCO X7 Pro", ["input"])]
    assert all(re.fullmatch(r"[0-9a-f]{12}", x["id"]) for x in d["devices"])
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


ADDR = re.compile(r"([0-9a-fA-F]{2}[:_-]){5}[0-9a-fA-F]{2}")
KID_POLICY = {"start": "00:00", "end": "23:59", "apps": [], "daily_limit_min": None, "can_power_off": False, "can_schedule": False}


def devices(client):
    return {x["name"]: x["id"] for x in client.get("/api/speaker/bluetooth", headers=H).json()["devices"]}


def test_no_bluetooth_address_reaches_the_browser(client, fake):
    r = client.get("/api/speaker/bluetooth", headers=H)
    assert not ADDR.search(r.text) and "9c_9e" not in r.text


def test_unpair_one_device_via_its_own_action_and_confirm(client, fake):
    ids = devices(client)
    r = client.post("/api/speaker/bluetooth/unpair", json={"id": ids["POCO X7 Pro"]}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["unpaired"] == "POCO X7 Pro"
    assert [x["name"] for x in r.json()["devices"]] == ["DESKTOP-TM1E1QQ", "LG TV[TV]"]
    assert fake.activations == [{"path": "bluetooth:devices/9c_9e_d5_75_1c_91/unpair", "role": "activate", "value": {}}]
    assert not ADDR.search(r.text)


def test_unpair_unknown_or_malformed_id_sends_nothing(client, fake):
    assert client.post("/api/speaker/bluetooth/unpair", json={"id": "0123456789ab"}, headers=H).status_code == 404
    for bad in ({"id": "9c_9e_d5_75_1c_91"}, {"id": "bluetooth:devices/x/unpair"}, {"id": "ABCDEF012345"}, {},
                {"id": "0123456789ab", "path": "settings:/x"}):
        assert client.post("/api/speaker/bluetooth/unpair", json=bad, headers=H).status_code == 422, bad
    assert fake.activations == []


def test_unpair_no_false_success(client, fake):
    ids = devices(client)
    fake.unpair_works = False  # HTTP 200, no error, but the device stays paired
    r = client.post("/api/speaker/bluetooth/unpair", json={"id": ids["LG TV[TV]"]}, headers=H)
    assert r.status_code == 502 and "\u05e2\u05d3\u05d9\u05d9\u05df" in r.json()["detail"]["message"]
    fake.activate_error = True  # HTTP 200 with an error body
    r = client.post("/api/speaker/bluetooth/unpair", json={"id": ids["LG TV[TV]"]}, headers=H)
    assert r.status_code == 502 and "Action failed" in r.json()["detail"]["message"]


def test_unpair_auth_and_kids(client, fake):
    ids = devices(client)
    assert client.post("/api/speaker/bluetooth/unpair", json={"id": ids["LG TV[TV]"]}).status_code == 401
    t = client.post("/api/tokens", json={"name": "kid", "policy": KID_POLICY}, headers=H).json()["token"]
    r = client.post("/api/speaker/bluetooth/unpair", json={"id": ids["LG TV[TV]"]}, headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 403 and fake.activations == []


def test_menu_unreadable_keeps_state(client, fake):
    fake.rows_for = lambda path: None
    d = client.get("/api/speaker/bluetooth", headers=H).json()
    assert d["devices"] is None and d["connected_device"] == "POCO X7 Pro"
