"""Zeppelin test lab: originals first, honest results, verified restore. No real speaker is contacted."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.zeppelin import ZeppelinClient
from tests.test_zeppelin import H, MASTER, FakeSpeaker

ORIG = {"bass": 0.0, "brightness": 40, "rgb": {"red": 255, "green": 6, "blue": 126}, "eq_enabled": True,
        "loudness": False, "balance": 0.0}


class LabSpeaker(FakeSpeaker):
    def __init__(self):
        super().__init__()
        self.values.update({
            "settings:/mediaPlayer/bass": {"type": "double_", "double_": 0.0},
            "settings:/ui/ambientLightBrightness": {"type": "i32_", "i32_": 40},
            "settings:/ui/ambientLightRgb": {"type": "formationDownlightRgb", "formationDownlightRgb": {"red": 255, "green": 6, "blue": 126}},
        })
        self.clamp_brightness: int | None = None  # simulates a speaker that silently stores a capped value

    def handler(self, request):
        r = super().handler(request)
        if self.clamp_brightness is not None and request.url.path == "/api/setData":
            v = self.values["settings:/ui/ambientLightBrightness"]
            v["i32_"] = min(v["i32_"], self.clamp_brightness)
        return r


@pytest.fixture
def fake():
    return LabSpeaker()


@pytest.fixture
def client(fake):
    app = create_app(Settings(access_token=MASTER, db_path=":memory:", use_mock_adapters=True))
    app.state.speaker = ZeppelinClient("192.168.1.52", transport=httpx.MockTransport(fake.handler))
    with TestClient(app) as c:
        yield c


def snap(client):
    r = client.post("/api/speaker/lab/snapshot", headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_reading_the_lab_writes_nothing(client, fake):
    r = client.get("/api/speaker/lab", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["current"] == ORIG and body["snapshot"] is None and body["errors"] == {}
    assert fake.sets() == []


def test_admin_only(client):
    t = client.post("/api/tokens", json={"name": "טלפון"}, headers=H).json()["token"]
    dev = {"Authorization": f"Bearer {t}"}
    for method, url, body in [("get", "/api/speaker/lab", None), ("post", "/api/speaker/lab/snapshot", None),
                              ("post", "/api/speaker/lab/bass", {"value": 1}), ("post", "/api/speaker/lab/restore", None)]:
        r = getattr(client, method)(url, headers=dev, **({"json": body} if body else {}))
        assert r.status_code == 403, url


def test_no_test_before_originals_are_saved(client, fake):
    r = client.post("/api/speaker/lab/bass", json={"value": 2}, headers=H)
    assert r.status_code == 409 and "ערכים המקוריים" in r.json()["detail"]["message"]
    assert fake.sets() == []


def test_snapshot_is_saved_and_never_overwritten(client, fake):
    body = snap(client)
    assert body["snapshot"]["values"] == ORIG and body["snapshot"]["host"] == "192.168.1.52"
    assert fake.sets() == []  # saving originals only reads
    client.post("/api/speaker/lab/brightness", json={"value": 10}, headers=H)
    r = client.post("/api/speaker/lab/snapshot", headers=H)
    assert r.status_code == 409
    assert client.get("/api/speaker/lab", headers=H).json()["snapshot"]["values"]["brightness"] == 40


def test_probe_reports_exactly_what_the_speaker_says(client, fake):
    snap(client)
    r = client.post("/api/speaker/lab/bass", json={"value": 3}, headers=H).json()["result"]
    assert r["sent"] == 3.0 and r["before"] == 0.0 and r["after"] == 3.0 and r["stored"] is True and r["speaker_error"] is None
    assert json.loads(fake.sets()[-1]["value"]) == {"type": "double_", "double_": 3.0}
    r = client.post("/api/speaker/lab/rgb", json={"red": 0, "green": 128, "blue": 255}, headers=H).json()["result"]
    assert r["after"] == {"red": 0, "green": 128, "blue": 255} and r["stored"] is True
    assert json.loads(fake.sets()[-1]["value"]) == {"type": "formationDownlightRgb", "formationDownlightRgb": {"red": 0, "green": 128, "blue": 255}}


def test_probe_reveals_a_capped_value_instead_of_guessing_a_range(client, fake):
    snap(client)
    fake.clamp_brightness = 100
    r = client.post("/api/speaker/lab/brightness", json={"value": 500}, headers=H)
    assert r.status_code == 200  # not rejected by us: there is no guessed range
    res = r.json()["result"]
    assert res["sent"] == 500 and res["after"] == 100 and res["stored"] is False


def test_probe_speaker_error_in_http_200_is_reported(client, fake):
    snap(client)
    fake.error_on_set = True
    res = client.post("/api/speaker/lab/bass", json={"value": 99}, headers=H).json()["result"]
    assert res["stored"] is False and "Invalid value" in res["speaker_error"] and res["after"] == 0.0


def test_restore_writes_originals_back_and_clears_only_on_success(client, fake):
    snap(client)
    client.post("/api/speaker/lab/bass", json={"value": 4}, headers=H)
    client.post("/api/speaker/lab/rgb", json={"red": 1, "green": 2, "blue": 3}, headers=H)
    fake.error_on_set = True
    r = client.post("/api/speaker/lab/restore", headers=H).json()
    assert r["restored"] is False and r["snapshot"] is not None  # originals kept for another try
    fake.error_on_set = False
    r = client.post("/api/speaker/lab/restore", headers=H).json()
    assert r["restored"] is True and r["snapshot"] is None and r["current"] == ORIG


def test_discard_keeps_current_values(client, fake):
    snap(client)
    client.post("/api/speaker/lab/brightness", json={"value": 12}, headers=H)
    n = len(fake.sets())
    r = client.delete("/api/speaker/lab/snapshot", headers=H).json()
    assert r["snapshot"] is None and r["current"]["brightness"] == 12 and len(fake.sets()) == n


def test_snapshot_bound_to_its_speaker(client, fake):
    snap(client)
    client.put("/api/speaker/config", json={"host": "192.168.1.60"}, headers=H)
    n = len(fake.sets())
    assert client.post("/api/speaker/lab/restore", headers=H).status_code == 409
    assert client.post("/api/speaker/lab/bass", json={"value": 1}, headers=H).status_code == 409
    assert len(fake.sets()) == n


def test_observations_are_recorded_with_the_tested_value(client, fake):
    snap(client)
    assert client.post("/api/speaker/lab/observation", json={"control": "bass", "result": "changed"}, headers=H).status_code == 409
    client.post("/api/speaker/lab/bass", json={"value": 2}, headers=H)
    obs = client.post("/api/speaker/lab/observation", json={"control": "bass", "result": "no_change", "note": "לא שמעתי"}, headers=H).json()["observations"]
    assert obs[0]["control"] == "bass" and obs[0]["result"] == "no_change" and obs[0]["sent"] == 2.0 and obs[0]["note"] == "לא שמעתי"


def test_saved_snapshot_survives_restart(tmp_path, fake):
    s = Settings(access_token=MASTER, db_path=str(tmp_path / "db.sqlite"), use_mock_adapters=True)
    for _ in range(2):
        app = create_app(s)
        app.state.speaker = ZeppelinClient("192.168.1.52", transport=httpx.MockTransport(fake.handler))
        with TestClient(app) as c:
            if c.get("/api/speaker/lab", headers=H).json()["snapshot"] is None:
                snap(c)
            else:
                assert c.get("/api/speaker/lab", headers=H).json()["snapshot"]["values"] == ORIG


@pytest.mark.parametrize("url,payload", [
    ("/api/speaker/lab/bass", {"value": "3"}), ("/api/speaker/lab/bass", {"value": True}),
    ("/api/speaker/lab/brightness", {"value": 2.5}), ("/api/speaker/lab/brightness", {"value": 2**31}),
    ("/api/speaker/lab/rgb", {"red": 256, "green": 0, "blue": 0}), ("/api/speaker/lab/rgb", {"red": 1, "green": 2}),
    ("/api/speaker/lab/rgb", {"red": 1, "green": 2, "blue": 3, "path": "settings:/x"}),
    ("/api/speaker/lab/observation", {"control": "eq", "result": "changed"}),
])
def test_wrong_types_never_reach_the_speaker(client, fake, url, payload):
    snap(client)
    r = client.post(url, json=payload, headers=H)
    assert r.status_code == 422
    assert fake.sets() == []


def test_loudness_and_balance_live_in_the_lab(client, fake):
    snap(client)
    r = client.post("/api/speaker/lab/loudness", json={"value": True}, headers=H).json()["result"]
    assert r["sent"] is True and r["after"] is True and r["stored"] is True
    assert json.loads(fake.sets()[-1]["value"]) == {"type": "bool_", "bool_": True}
    for v in (6, -1, 0):  # any finite number, no range of ours; 0 is the "centre" button
        r = client.post("/api/speaker/lab/balance", json={"value": v}, headers=H).json()["result"]
        assert r["sent"] == float(v) and r["after"] == float(v)
        assert json.loads(fake.sets()[-1]["value"]) == {"type": "double_", "double_": float(v)}
    assert client.post("/api/speaker/lab/balance", json={"value": "1"}, headers=H).status_code == 422
    r = client.post("/api/speaker/lab/restore", headers=H).json()
    assert r["restored"] is True and r["current"]["loudness"] is False and r["current"]["balance"] == 0.0


def test_old_snapshot_is_completed_without_overwriting(client, fake):
    # saved before loudness/balance/eq_enabled were in the lab, and bass has been changed since
    client.app.state.manager.store.set_state("speaker", "lab_original", json.dumps(
        {"host": "192.168.1.52", "at": 1, "values": {"bass": -3.0, "brightness": 40, "rgb": {"red": 255, "green": 6, "blue": 126}}}))
    assert client.post("/api/speaker/lab/loudness", json={"value": True}, headers=H).status_code == 409  # not saved yet
    fake.values["settings:/mediaPlayer/loudness"]["bool_"] = True  # the user's current loudness
    body = client.post("/api/speaker/lab/snapshot", headers=H).json()
    vals = body["snapshot"]["values"]
    assert vals["bass"] == -3.0  # the saved original survives (the speaker now says 0)
    assert vals["loudness"] is True and vals["balance"] == 0.0 and vals["eq_enabled"] is True
    assert fake.sets() == []  # completing only reads
    assert client.post("/api/speaker/lab/snapshot", headers=H).status_code == 409  # complete now: nothing to add
    assert client.post("/api/speaker/lab/loudness", json={"value": False}, headers=H).status_code == 200


def test_source_gain_is_shown_read_only(client, fake):
    body = client.get("/api/speaker/lab", headers=H).json()
    assert body["source_gain"] == [{"name": "All", "value": 0, "min": -60, "max": 20}]
    assert fake.sets() == []
    snap(client)
    assert "source_gain" not in client.get("/api/speaker/lab", headers=H).json()["snapshot"]["values"]  # never saved/restored
    for url in ("/api/speaker/lab/source_gain", "/api/speaker/lab/sourceGain"):
        assert client.post(url, json={"value": 1}, headers=H).status_code in (404, 405)
    r = client.post("/api/speaker/lab/restore", headers=H).json()
    assert all("sourceGain" not in s["path"] for s in fake.sets())


def test_source_gain_unexpected_shape_is_reported(client, fake):
    fake.values["settings:/mediaPlayer/sourceGain"] = {"type": "sourceGainList", "sourceGainList": [{"name": "All"}]}
    body = client.get("/api/speaker/lab", headers=H).json()
    assert body["source_gain"] is None and "source_gain" in body["errors"]
