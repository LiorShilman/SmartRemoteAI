"""Speaker profiles: fresh capture, controlled load with per-step results, undo, no competing writes. No real speaker."""
import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.zeppelin import ZeppelinClient
from tests.test_zeppelin import H, MASTER, FakeSpeaker

EQ = "settings:/mediaPlayer/equalizer"
NEVER = {"settings:/mediaPlayer/mute", "settings:/mediaPlayer/balance", "settings:/mediaPlayer/sourceGain",
         "settings:/ui/ambientLightEnabled"}


class ProfileSpeaker(FakeSpeaker):
    def __init__(self):
        super().__init__()
        self.fail_set_paths: set[str] = set()  # setData on these answers HTTP 200 + error

    def handler(self, request):
        if request.url.path == "/api/setData" and request.url.params.get("path") in self.fail_set_paths:
            self.requests.append(request)
            return httpx.Response(200, json={"error": {"message": "Setting is not modifiable"}})
        return super().handler(request)


async def fast_sleep(_s):
    await asyncio.sleep(0.02)


def val(fake, path):
    v = fake.values[path]
    return v[v["type"]]


def set_paths(fake):
    return [s["path"] for s in fake.sets()]


def wait_until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def fake():
    return ProfileSpeaker()


@pytest.fixture
def client(fake):
    app = create_app(Settings(access_token=MASTER, db_path=":memory:", use_mock_adapters=True))
    app.state.speaker = ZeppelinClient("192.168.1.52", transport=httpx.MockTransport(fake.handler))
    app.state.cycle.sleep = fast_sleep
    with TestClient(app) as c:
        yield c


def save(client, name="ערב", include_volume=False):
    r = client.post("/api/speaker/profiles", json={"name": name, "include_volume": include_volume}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()["created"]


def change_everything(fake):
    for b in fake.values[EQ]["eqBandList"]:
        b["value"] = 3
    fake.values["settings:/mediaPlayer/bass"]["double_"] = 5.0
    fake.values["settings:/mediaPlayer/treble"]["double_"] = -4.0
    fake.values["settings:/mediaPlayer/loudness"]["bool_"] = True
    fake.values["settings:/ui/ambientLightBrightness"]["i32_"] = 20
    fake.values["settings:/ui/ambientLightRgb"]["formationDownlightRgb"] = {"red": 1, "green": 2, "blue": 3}
    fake.values["player:volume"]["i32_"] = 40


def test_save_reads_fresh_values_and_writes_nothing(client, fake):
    p = save(client)
    d = p["data"]
    assert d["eq"] == {"60": 0, "250": 0, "1000": 0, "3500": 0, "12000": 0}
    assert d["bass"] == -1.0 and d["treble"] == 5.0 and d["loudness"] is False and d["brightness"] == 100
    assert d["rgb"] == {"red": 255, "green": 6, "blue": 126}
    assert d["cycle"]["running"] is False and d["cycle"]["config"]["interval_s"] == 10
    assert "volume" not in d and p["include_volume"] is False
    assert not ({"mute", "balance", "source_gain", "light"} & set(d))  # never saved
    assert fake.sets() == []


def test_volume_only_when_chosen(client, fake):
    assert save(client, "עם עוצמה", include_volume=True)["data"]["volume"] == 23


def test_list_rename_delete_and_names(client, fake):
    p = save(client, "ערב")
    assert client.post("/api/speaker/profiles", json={"name": "ערב"}, headers=H).status_code == 409  # same name
    assert client.post("/api/speaker/profiles", json={"name": "ERB"}, headers=H).status_code == 201
    assert client.post("/api/speaker/profiles", json={"name": "   "}, headers=H).status_code == 422
    assert client.post("/api/speaker/profiles", json={"name": "a\nb"}, headers=H).status_code == 422
    assert client.post("/api/speaker/profiles", json={"name": "x" * 41}, headers=H).status_code == 422
    assert client.patch(f"/api/speaker/profiles/{p['id']}", json={"name": "erb"}, headers=H).status_code == 409  # taken (case-insensitive)
    body = client.patch(f"/api/speaker/profiles/{p['id']}", json={"name": "לילה"}, headers=H).json()
    assert [x["name"] for x in body["profiles"]] == ["לילה", "ERB"]
    body = client.delete(f"/api/speaker/profiles/{p['id']}", headers=H).json()
    assert [x["name"] for x in body["profiles"]] == ["ERB"]
    assert client.delete(f"/api/speaker/profiles/{p['id']}", headers=H).status_code == 404
    assert fake.sets() == []


def test_never_loaded_automatically(tmp_path, fake):
    s = Settings(access_token=MASTER, db_path=str(tmp_path / "db.sqlite"), use_mock_adapters=True)
    for i in range(2):
        app = create_app(s)
        app.state.speaker = ZeppelinClient("192.168.1.52", transport=httpx.MockTransport(fake.handler))
        with TestClient(app) as c:
            if i == 0:
                save(c)
            body = c.get("/api/speaker/profiles", headers=H).json()
            assert len(body["profiles"]) == 1  # available after a restart (and from any browser)
    assert fake.sets() == []


def test_full_load_writes_every_setting_reads_back_and_offers_undo(client, fake):
    p = save(client)
    change_everything(fake)
    r = client.post(f"/api/speaker/profiles/{p['id']}/load", headers=H).json()
    assert r["status"] == "full" and all(s["ok"] for s in r["steps"])
    assert [s["step"] for s in r["steps"]] == ["cycle_stop", "eq", "bass", "treble", "loudness", "brightness", "rgb", "cycle_config"]
    assert [b["value"] for b in fake.values[EQ]["eqBandList"]] == [0, 0, 0, 0, 0]
    assert val(fake, "settings:/mediaPlayer/bass") == -1.0 and val(fake, "settings:/ui/ambientLightBrightness") == 100
    assert val(fake, "player:volume") == 40  # profile without volume: volume untouched
    assert not (NEVER & set(set_paths(fake))) and "player:volume" not in set_paths(fake)
    assert r["loaded_id"] == p["id"] and r["undo"] is not None


def test_load_with_volume(client, fake):
    p = save(client, include_volume=True)
    change_everything(fake)
    r = client.post(f"/api/speaker/profiles/{p['id']}/load", headers=H).json()
    assert r["status"] == "full" and val(fake, "player:volume") == 23


def test_wide_tone_range_saves_and_loads(client, fake):
    """Bass/treble beyond the old -6..+6 (the nodes declare -10..+10 step 0.5) round-trip through a profile."""
    fake.values["settings:/mediaPlayer/treble"]["double_"] = 8.0
    fake.values["settings:/mediaPlayer/bass"]["double_"] = -9.5
    p = save(client)
    assert p["data"]["treble"] == 8.0 and p["data"]["bass"] == -9.5
    change_everything(fake)
    r = client.post(f"/api/speaker/profiles/{p['id']}/load", headers=H).json()
    assert r["status"] == "full"
    assert val(fake, "settings:/mediaPlayer/treble") == 8.0 and val(fake, "settings:/mediaPlayer/bass") == -9.5


def test_partial_load_is_reported_as_partial(client, fake):
    p = save(client)
    change_everything(fake)
    fake.fail_set_paths = {"settings:/mediaPlayer/treble"}
    r = client.post(f"/api/speaker/profiles/{p['id']}/load", headers=H).json()
    assert r["status"] == "partial"
    bad = [s for s in r["steps"] if not s["ok"]]
    assert [s["step"] for s in bad] == ["treble"] and "not modifiable" in bad[0]["error"]
    assert val(fake, "settings:/mediaPlayer/bass") == -1.0  # the other steps still ran
    assert r["loaded_id"] is None  # never shown as "loaded" when it is not


def test_disconnect_stops_the_sequence(client, fake):
    p = save(client)
    change_everything(fake)
    orig = fake.handler

    def dies_after_eq(request):
        if request.url.path == "/api/setData" and request.url.params.get("path") == "settings:/mediaPlayer/bass":
            fake.unreachable = True
        return orig(request)
    client.app.state.speaker = ZeppelinClient("192.168.1.52", transport=httpx.MockTransport(dies_after_eq))
    r = client.post(f"/api/speaker/profiles/{p['id']}/load", headers=H).json()
    assert r["status"] == "partial"
    by = {s["step"]: s for s in r["steps"]}
    assert by["eq"]["ok"] and not by["bass"]["ok"]
    assert all(by[k]["error"].startswith("לא בוצע") for k in ("treble", "loudness", "brightness", "rgb"))
    n = len(fake.requests)
    time.sleep(0.2)
    assert len(fake.requests) == n  # no retries


def test_undo_restores_the_previous_state(client, fake):
    p = save(client)
    change_everything(fake)
    client.post(f"/api/speaker/profiles/{p['id']}/load", headers=H)
    r = client.post("/api/speaker/profiles/undo", headers=H).json()
    assert r["status"] == "full" and r["undo"] is None
    assert [b["value"] for b in fake.values[EQ]["eqBandList"]] == [3, 3, 3, 3, 3]
    assert val(fake, "settings:/mediaPlayer/bass") == 5.0 and val(fake, "settings:/ui/ambientLightRgb") == {"red": 1, "green": 2, "blue": 3}
    assert client.post("/api/speaker/profiles/undo", headers=H).status_code == 409  # nothing left to undo


def test_cycle_is_stopped_during_load_and_restarted_if_the_profile_had_it(client, fake):
    pal = [{"red": 255, "green": 0, "blue": 0}, {"red": 0, "green": 0, "blue": 255}]
    client.put("/api/speaker/cycle/config", json={"interval_s": 7, "mode": "palette", "palette": pal, "smooth": False}, headers=H)
    client.post("/api/speaker/cycle/start", headers=H)
    p = save(client, "צבעוני")
    assert p["data"]["cycle"]["running"] is True and p["data"]["cycle"]["config"]["interval_s"] == 7
    client.post("/api/speaker/cycle/stop", headers=H)
    client.put("/api/speaker/cycle/config", json={"interval_s": 30, "mode": "random", "palette": [], "smooth": True}, headers=H)
    r = client.post(f"/api/speaker/profiles/{p['id']}/load", headers=H).json()
    assert r["status"] == "full" and r["steps"][-1]["step"] == "cycle_start"
    st = client.get("/api/speaker/cycle", headers=H).json()
    assert st["status"]["running"] is True and st["config"]["interval_s"] == 7 and st["config"]["mode"] == "palette"
    client.post("/api/speaker/cycle/stop", headers=H)


def test_running_cycle_is_stopped_before_writing(client, fake):
    p = save(client)  # no cycle in this profile
    pal = [{"red": 255, "green": 0, "blue": 0}, {"red": 0, "green": 0, "blue": 255}]
    client.put("/api/speaker/cycle/config", json={"interval_s": 10, "mode": "palette", "palette": pal}, headers=H)
    client.post("/api/speaker/cycle/start", headers=H)
    r = client.post(f"/api/speaker/profiles/{p['id']}/load", headers=H).json()
    assert r["status"] == "full" and client.get("/api/speaker/cycle", headers=H).json()["status"]["running"] is False
    n = len(fake.sets())
    time.sleep(0.2)
    assert len(fake.sets()) == n  # the cycle no longer writes after the load


def test_light_off_makes_cycle_start_fail_clearly(client, fake):
    pal = [{"red": 255, "green": 0, "blue": 0}, {"red": 0, "green": 0, "blue": 255}]
    client.put("/api/speaker/cycle/config", json={"interval_s": 10, "mode": "palette", "palette": pal}, headers=H)
    client.post("/api/speaker/cycle/start", headers=H)
    p = save(client)
    client.post("/api/speaker/cycle/stop", headers=H)
    fake.values["settings:/ui/ambientLightEnabled"]["bool_"] = False
    r = client.post(f"/api/speaker/profiles/{p['id']}/load", headers=H).json()
    assert r["status"] == "partial"
    last = r["steps"][-1]
    assert last["step"] == "cycle_start" and not last["ok"] and "להדליק" in last["error"]


def test_other_writes_are_refused_while_a_profile_loads(client, fake):
    client.app.state.profiles.busy = True
    for url, body in [("/api/speaker/volume", {"value": 30}), ("/api/speaker/rgb", {"red": 1, "green": 1, "blue": 1}),
                      ("/api/speaker/eq", {"bands": [{"band": b, "value": 0} for b in ("60", "250", "1000", "3500", "12000")]})]:
        r = client.post(url, json=body, headers=H)
        assert r.status_code == 409 and "פרופיל" in r.json()["detail"]["message"]
    assert client.post("/api/speaker/cycle/start", headers=H).status_code == 409
    client.app.state.profiles.busy = False
    assert fake.sets() == []


def test_kids_cannot_save_or_load(client, fake):
    p = save(client)
    policy = {"start": "00:00", "end": "23:59", "apps": [], "daily_limit_min": None, "can_power_off": False, "can_schedule": False}
    t = client.post("/api/tokens", json={"name": "ילד", "policy": policy}, headers=H).json()["token"]
    kid = {"Authorization": f"Bearer {t}"}
    assert client.get("/api/speaker/profiles", headers=kid).status_code == 200
    assert client.post(f"/api/speaker/profiles/{p['id']}/load", headers=kid).status_code == 403
    assert client.post("/api/speaker/profiles", json={"name": "x"}, headers=kid).status_code == 403
    assert fake.sets() == []


def test_unreadable_value_refuses_to_save(client, fake):
    fake.values["settings:/mediaPlayer/loudness"] = {"type": "string_", "string_": "?"}
    r = client.post("/api/speaker/profiles", json={"name": "חלקי"}, headers=H)
    assert r.status_code == 502 and "Loudness" in r.json()["detail"]["message"]
    assert client.get("/api/speaker/profiles", headers=H).json()["profiles"] == []


def test_update_overwrites_with_current_values_and_writes_nothing(client, fake):
    p = save(client, "ערב")
    other = save(client, "בוקר", include_volume=True)
    change_everything(fake)
    r = client.post(f"/api/speaker/profiles/{p['id']}/update", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    u = body["updated"]
    assert u["id"] == p["id"] and u["name"] == "ערב" and u["include_volume"] is False
    d = u["data"]
    assert d["eq"] == {"60": 3, "250": 3, "1000": 3, "3500": 3, "12000": 3}
    assert d["bass"] == 5.0 and d["treble"] == -4.0 and d["loudness"] is True and d["brightness"] == 20
    assert d["rgb"] == {"red": 1, "green": 2, "blue": 3} and "volume" not in d  # volume stays out
    assert body["loaded_id"] == p["id"]
    assert [x["name"] for x in body["profiles"]] == ["ערב", "בוקר"]  # order and the other profile unchanged
    assert next(x for x in body["profiles"] if x["id"] == other["id"])["data"]["bass"] == -1.0
    # a profile that includes volume keeps including it
    assert client.post(f"/api/speaker/profiles/{other['id']}/update", headers=H).json()["updated"]["data"]["volume"] == 40
    assert client.post("/api/speaker/profiles/nope/update", headers=H).status_code == 404
    assert fake.sets() == []


def test_update_refuses_partial_capture_and_kids(client, fake):
    p = save(client)
    fake.values["settings:/mediaPlayer/loudness"] = {"type": "string_", "string_": "?"}
    fake.values["settings:/mediaPlayer/bass"]["double_"] = 5.0
    assert client.post(f"/api/speaker/profiles/{p['id']}/update", headers=H).status_code == 502
    assert client.get("/api/speaker/profiles", headers=H).json()["profiles"][0]["data"]["bass"] == -1.0  # unchanged
    policy = {"start": "00:00", "end": "23:59", "apps": [], "daily_limit_min": None, "can_power_off": False, "can_schedule": False}
    t = client.post("/api/tokens", json={"name": "ילד", "policy": policy}, headers=H).json()["token"]
    assert client.post(f"/api/speaker/profiles/{p['id']}/update", headers={"Authorization": f"Bearer {t}"}).status_code == 403
    client.app.state.profiles.busy = True
    assert client.post(f"/api/speaker/profiles/{p['id']}/update", headers=H).status_code == 409
    client.app.state.profiles.busy = False
    assert fake.sets() == []
