"""Zeppelin 5-band equalizer: speaker-provided limits, whole-list writes that keep the structure, honest read-back."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.zeppelin import ZeppelinClient, on_step
from tests.test_zeppelin import H, MASTER, FakeSpeaker

EQ = "settings:/mediaPlayer/equalizer"
BANDS = ["60", "250", "1000", "3500", "12000"]


@pytest.fixture
def fake():
    return FakeSpeaker()


@pytest.fixture
def client(fake):
    app = create_app(Settings(access_token=MASTER, db_path=":memory:", use_mock_adapters=True))
    app.state.speaker = ZeppelinClient("192.168.1.52", transport=httpx.MockTransport(fake.handler))
    with TestClient(app) as c:
        yield c


def body(*values):
    return {"bands": [{"band": b, "value": v} for b, v in zip(BANDS, values)]}


def test_read_eq_never_writes(client, fake):
    r = client.get("/api/speaker/eq", headers=H)
    assert r.status_code == 200
    out = r.json()
    assert [b["band"] for b in out["bands"]] == BANDS
    assert out["bands"][0] == {"band": "60", "min": -6, "max": 6, "step": 0.5, "value": 0}
    assert out["enabled"] is True and out["errors"] == {}
    assert fake.sets() == []
    assert {r.url.params["path"] for r in fake.requests} == {EQ, "settings:/mediaPlayer/equalizerOnOff"}


def test_requires_auth(client):
    assert client.get("/api/speaker/eq").status_code == 401
    assert client.post("/api/speaker/eq", json=body(0, 0, 0, 0, 0)).status_code == 401


def test_write_sends_all_bands_and_keeps_the_structure(client, fake):
    r = client.post("/api/speaker/eq", json=body(1.5, -2, 0, 3.5, -6), headers=H)
    assert r.status_code == 200, r.text
    assert [b["value"] for b in r.json()["bands"]] == [1.5, -2, 0, 3.5, -6]
    sets = fake.sets()
    assert len(sets) == 1 and sets[0]["path"] == EQ and sets[0]["role"] == "value"
    sent = json.loads(sets[0]["value"])
    assert sent == {"type": "eqBandList", "eqBandList": [
        {"min": -6, "max": 6, "band": "60", "step": 0.5, "value": 1.5},
        {"min": -6, "max": 6, "band": "250", "step": 0.5, "value": -2},
        {"min": -6, "max": 6, "band": "1000", "step": 0.5, "value": 0},
        {"min": -6, "max": 6, "band": "3500", "step": 0.5, "value": 3.5},
        {"min": -6, "max": 6, "band": "12000", "step": 0.5, "value": -6},
    ]}
    assert "%7B" in str(fake.requests[1].url)  # encoded by httpx, not by hand
    assert any(a["event"] == "speaker" and "אקולייזר" in a["detail"] for a in client.get("/api/audit", headers=H).json())


def test_unknown_fields_from_the_speaker_are_kept(client, fake):
    for b in fake.values[EQ]["eqBandList"]:
        b["label"] = f"band-{b['band']}"
    client.post("/api/speaker/eq", json=body(1, 1, 1, 1, 1), headers=H)
    sent = json.loads(fake.sets()[0]["value"])["eqBandList"]
    assert all(b["label"] == f"band-{b['band']}" for b in sent)


def test_limits_come_from_the_speaker(client, fake):
    fake.values[EQ]["eqBandList"][0].update(min=-12, max=12, step=1)  # a band with other limits
    assert client.post("/api/speaker/eq", json=body(10, 0, 0, 0, 0), headers=H).status_code == 200
    r = client.post("/api/speaker/eq", json=body(0.5, 0, 0, 0, 0), headers=H)  # off its step of 1
    assert r.status_code == 422 and "צעד" in r.json()["detail"]["message"]
    r = client.post("/api/speaker/eq", json=body(0, 6.5, 0, 0, 0), headers=H)  # beyond that band's own max
    assert r.status_code == 422


@pytest.mark.parametrize("payload", [
    body(0.25, 0, 0, 0, 0),                                   # off the 0.5 step
    body(7, 0, 0, 0, 0),                                      # beyond max 6
    body(0, 0, 0, 0),                                         # a band missing
    {"bands": [{"band": b, "value": 0} for b in BANDS] + [{"band": "8000", "value": 0}]},  # an extra band
    {"bands": [{"band": "60", "value": 0}] * 5},              # duplicates
    {"bands": [{"band": "60;rm", "value": 0}]},
    {"bands": [{"band": "60", "value": "1"}]},
    {"bands": [{"band": "60", "value": True}]},
    {"path": EQ, "bands": []},
])
def test_invalid_eq_never_reaches_the_speaker(client, fake, payload):
    r = client.post("/api/speaker/eq", json=payload, headers=H)
    assert r.status_code == 422
    assert fake.sets() == []


def test_error_inside_http_200_is_not_success(client, fake):
    fake.error_on_set = True
    r = client.post("/api/speaker/eq", json=body(1, 0, 0, 0, 0), headers=H)
    assert r.status_code == 502 and "Invalid value" in r.json()["detail"]["message"]


def test_readback_mismatch_is_not_success(client, fake):
    fake.ignore_set = True
    r = client.post("/api/speaker/eq", json=body(1, 0, 0, 0, 0), headers=H)
    assert r.status_code == 502 and "60=0" in r.json()["detail"]["message"]


def test_unexpected_shape_is_rejected(client, fake):
    fake.values[EQ] = {"type": "eqBandList", "eqBandList": [{"band": "60", "value": "loud"}]}
    out = client.get("/api/speaker/eq", headers=H).json()
    assert out["bands"] is None and "bands" in out["errors"]


def test_unreachable(client, fake):
    fake.unreachable = True
    assert client.get("/api/speaker/eq", headers=H).status_code == 503
    assert client.post("/api/speaker/eq", json=body(0, 0, 0, 0, 0), headers=H).status_code == 503


def test_kids_can_read_not_write(client, fake):
    policy = {"start": "00:00", "end": "23:59", "apps": [], "daily_limit_min": None, "can_power_off": False, "can_schedule": False}
    t = client.post("/api/tokens", json={"name": "ילד", "policy": policy}, headers=H).json()["token"]
    kid = {"Authorization": f"Bearer {t}"}
    assert client.get("/api/speaker/eq", headers=kid).status_code == 200
    assert client.post("/api/speaker/eq", json=body(1, 0, 0, 0, 0), headers=kid).status_code == 403
    assert fake.sets() == []


def test_eq_switch_is_not_a_regular_control(client, fake):
    for url in ("/api/speaker/eq/enabled", "/api/speaker/equalizerOnOff", "/api/speaker/eq_enabled"):
        assert client.post(url, json={"value": False}, headers=H).status_code in (404, 405)
    assert fake.sets() == []


def test_eq_switch_lab_needs_a_snapshot_that_includes_it(client, fake):
    # a snapshot saved before the switch existed in the lab cannot restore it -> testing it is refused
    client.app.state.manager.store.set_state("speaker", "lab_original", json.dumps(
        {"host": "192.168.1.52", "at": 1, "values": {"bass": 0.0, "brightness": 40, "rgb": {"red": 1, "green": 2, "blue": 3}}}))
    r = client.post("/api/speaker/lab/eq_enabled", json={"value": False}, headers=H)
    assert r.status_code == 409 and "לא כוללת" in r.json()["detail"]["message"]
    assert fake.sets() == []
    client.delete("/api/speaker/lab/snapshot", headers=H)
    assert client.post("/api/speaker/lab/snapshot", headers=H).json()["snapshot"]["values"]["eq_enabled"] is True
    res = client.post("/api/speaker/lab/eq_enabled", json={"value": False}, headers=H).json()["result"]
    assert res["sent"] is False and res["after"] is False and res["stored"] is True
    assert json.loads(fake.sets()[-1]["value"]) == {"type": "bool_", "bool_": False}
    r = client.post("/api/speaker/lab/restore", headers=H).json()
    assert r["restored"] is True and r["current"]["eq_enabled"] is True


def test_on_step():
    assert on_step(1.5, -6, 6, 0.5) and on_step(-6, -6, 6, 0.5) and on_step(6, -6, 6, 0.5)
    assert not on_step(1.25, -6, 6, 0.5) and not on_step(6.5, -6, 6, 0.5)
    assert on_step(0.3, 0, 1, 0.1)  # float tolerance
