"""Standby timeout (a choice from the speaker's own list) and the read-only audio source list."""
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.zeppelin import ZeppelinClient
from tests.test_zeppelin import FakeSpeaker, H, MASTER

IDLE = "settings:/system/maxIdleTime"
# rows exactly as the real speaker returned them for roles=title,value,path,type,disabled
IDLE_ROWS = [["Off", {"type": "i32_", "i32_": 0}, "settings:/system/maxIdleTimeValues/01-off", "value", None],
             ["5 minutes", {"type": "i32_", "i32_": 300}, "settings:/system/maxIdleTimeValues/02-5min", "value", None],
             ["10 minutes", {"type": "i32_", "i32_": 600}, "settings:/system/maxIdleTimeValues/03-10min", "value", None],
             ["15 minutes", {"type": "i32_", "i32_": 900}, "settings:/system/maxIdleTimeValues/04-15min", "value", None],
             ["30 minutes", {"type": "i32_", "i32_": 1800}, "settings:/system/maxIdleTimeValues/05-30min", "value", None]]


def src(title, path, active, plugged, disabled, **extra):
    inp = {"arc": "none", "autoSwitch": False, "active": active, "plugged": plugged, "audioFormat": "unknown", **extra}
    return [title, {"bwAudioInput": inp, "type": "bwAudioInput"}, path, "action", disabled]


BW_ROWS = [src("SPDIF", "bw:spdif", False, False, True),
           src("AirPlay", "bw:airplay", True, True, None),
           src("Bluetooth", "bw:bluetooth", False, False, True, deviceName="POCO X7 Pro", deviceMac="9c:9e:d5:75:1c:91")]


class ListSpeaker(FakeSpeaker):
    def __init__(self):
        super().__init__()
        self.values[IDLE] = {"type": "i32_", "i32_": 1200}
        self.lists = {"settings:/system/maxIdleTimeValues": IDLE_ROWS, "ui:/bw": BW_ROWS}

    def handler(self, request):
        if not self.unreachable and request.url.path == "/api/getRows":
            self.requests.append(request)
            q = {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}
            rows = self.lists.get(q["path"])
            if rows is None:
                return httpx.Response(200, json={"error": {"message": "invalid path"}})
            lo, hi = int(q["from"]), int(q["to"])
            return httpx.Response(200, json={"rowsVersion": 0, "rows": rows[lo:hi + 1], "rowsCount": len(rows)})
        return super().handler(request)


@pytest.fixture
def fake():
    return ListSpeaker()


@pytest.fixture
def client(fake):
    app = create_app(Settings(access_token=MASTER, db_path=":memory:", use_mock_adapters=True))
    app.state.speaker = ZeppelinClient("192.168.1.52", transport=httpx.MockTransport(fake.handler))
    with TestClient(app) as c:
        yield c


def kid_headers(client):
    policy = {"start": "00:00", "end": "23:59", "apps": [], "daily_limit_min": None, "can_power_off": False, "can_schedule": False}
    t = client.post("/api/tokens", json={"name": "ילד", "policy": policy}, headers=H).json()["token"]
    return {"Authorization": f"Bearer {t}"}


def test_reading_standby_sends_nothing_and_keeps_an_unlisted_current_value(client, fake):
    r = client.get("/api/speaker/standby", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["seconds"] == 1200  # the factory value is not one of the listed options; reported as is
    assert [o["seconds"] for o in body["options"]] == [0, 300, 600, 900, 1800]
    assert body["options"][-1]["title"] == "30 minutes"
    assert fake.sets() == []


def test_standby_write_reads_back(client, fake):
    r = client.post("/api/speaker/standby", json={"seconds": 1800}, headers=H)
    assert r.status_code == 200 and r.json()["seconds"] == 1800
    assert [json.loads(s["value"]) for s in fake.sets()] == [{"type": "i32_", "i32_": 1800}]
    assert [s["path"] for s in fake.sets()] == [IDLE]


@pytest.mark.parametrize("payload", [{"seconds": 1200}, {"seconds": 1234}, {"seconds": -1}, {"seconds": "1800"},
                                     {"seconds": True}, {"seconds": 1800, "path": "settings:/system/maxIdlePlayTime"}, {}])
def test_standby_only_from_the_speaker_list(client, fake, payload):
    r = client.post("/api/speaker/standby", json=payload, headers=H)
    assert r.status_code == 422
    assert fake.sets() == []


def test_standby_no_false_success(client, fake):
    fake.ignore_set = True  # HTTP 200, but the value stays
    r = client.post("/api/speaker/standby", json={"seconds": 300}, headers=H)
    assert r.status_code == 502
    fake.ignore_set, fake.error_on_set = False, True  # error object inside HTTP 200
    r = client.post("/api/speaker/standby", json={"seconds": 300}, headers=H)
    assert r.status_code == 502


def test_standby_auth_kids_unreachable(client, fake):
    assert client.post("/api/speaker/standby", json={"seconds": 300}).status_code == 401
    assert client.post("/api/speaker/standby", json={"seconds": 300}, headers=kid_headers(client)).status_code == 403
    assert fake.sets() == []
    fake.unreachable = True
    assert client.post("/api/speaker/standby", json={"seconds": 300}, headers=H).status_code == 503


def test_sources_read_only_without_device_details(client, fake):
    r = client.get("/api/speaker/sources", headers=H)
    assert r.status_code == 200
    assert r.json()["sources"] == [
        {"id": "spdif", "title": "SPDIF", "active": False, "plugged": False, "available": False},
        {"id": "airplay", "title": "AirPlay", "active": True, "plugged": True, "available": True},
        {"id": "bluetooth", "title": "Bluetooth", "active": False, "plugged": False, "available": False},
    ]
    assert "9c:9e" not in r.text and "POCO" not in r.text
    assert fake.sets() == [] and all(q.method == "GET" for q in fake.requests)


def test_unexpected_list_shape_is_an_error_not_a_crash(client, fake):
    fake.lists["ui:/bw"] = [{"title": "x"}]
    assert client.get("/api/speaker/sources", headers=H).status_code == 502
    fake.lists["settings:/system/maxIdleTimeValues"] = []
    assert client.get("/api/speaker/standby", headers=H).status_code == 502
