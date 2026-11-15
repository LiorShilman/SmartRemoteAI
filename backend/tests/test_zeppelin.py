"""B&W Zeppelin speaker: verified controls only, strict parsing, no false success. No real speaker is contacted."""
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.zeppelin import SpeakerError, ZeppelinClient

MASTER = "master-token-123"
H = {"Authorization": f"Bearer {MASTER}"}


class FakeSpeaker:
    """Answers like the real speaker. Knobs simulate its failure modes."""

    def __init__(self):
        self.values = {
            "player:volume": {"type": "i32_", "i32_": 23},
            "settings:/mediaPlayer/treble": {"type": "double_", "double_": 5.0},
            "settings:/ui/ambientLightEnabled": {"type": "bool_", "bool_": True},
            "settings:/mediaPlayer/bass": {"type": "double_", "double_": -1.0},
            "settings:/ui/ambientLightBrightness": {"type": "i32_", "i32_": 100},
            "settings:/ui/ambientLightRgb": {"type": "formationDownlightRgb", "formationDownlightRgb": {"red": 255, "green": 6, "blue": 126}},
            # exactly the shape the real speaker returned
            "settings:/mediaPlayer/equalizer": {"type": "eqBandList", "eqBandList": [
                {"min": -6, "max": 6, "band": b, "step": 0.5, "value": 0} for b in ("60", "250", "1000", "3500", "12000")]},
            "settings:/mediaPlayer/equalizerOnOff": {"type": "bool_", "bool_": True},
            "settings:/mediaPlayer/loudness": {"bool_": False, "type": "bool_"},  # key order as the speaker sends it
            "settings:/mediaPlayer/mute": {"type": "bool_", "bool_": False},
            # exactly as the real speaker returned it
            "settings:/mediaPlayer/sourceGain": {"type": "sourceGainList", "sourceGainList": [
                {"sources": [], "alsaMixer": "", "min": -60, "max": 20, "path": "", "name": "All", "value": 0}]},
            "settings:/mediaPlayer/balance": {"type": "double_", "double_": 0},
        }
        self.requests: list[httpx.Request] = []
        self.error_on_set = False      # HTTP 200 with an error object
        self.ignore_set = False        # HTTP 200, no error, but the value does not change (like attenuation)
        self.unreachable = False
        self.slow = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.unreachable:
            raise httpx.ConnectError("no route to host", request=request)
        if self.slow:
            raise httpx.ReadTimeout("timed out", request=request)
        q = {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}
        path = q.get("path")
        if path not in self.values:
            return httpx.Response(200, json={"error": {"message": "path not found", "name": "NotFound"}})
        if request.url.path == "/api/getData":
            return httpx.Response(200, json=[self.values[path]])
        if request.url.path == "/api/setData":
            if self.error_on_set:
                return httpx.Response(200, json={"error": {"message": "Invalid value", "name": "Error"}})
            if not self.ignore_set:
                self.values[path] = json.loads(q["value"])
            return httpx.Response(200, json={})
        return httpx.Response(404)

    def sets(self) -> list[dict]:
        out = []
        for r in self.requests:
            if r.url.path == "/api/setData":
                out.append({k: v[0] for k, v in parse_qs(urlsplit(str(r.url)).query).items()})
        return out


@pytest.fixture
def fake():
    return FakeSpeaker()


@pytest.fixture
def client(fake):
    app = create_app(Settings(access_token=MASTER, db_path=":memory:", use_mock_adapters=True))
    app.state.speaker = ZeppelinClient("192.168.1.52", transport=httpx.MockTransport(fake.handler))
    with TestClient(app) as c:
        yield c


def test_requires_auth(client):
    assert client.get("/api/speaker").status_code == 401
    assert client.post("/api/speaker/volume", json={"value": 20}).status_code == 401
    assert client.get("/api/speaker", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_read_state_never_writes(client, fake):
    r = client.get("/api/speaker", headers=H)
    assert r.status_code == 200
    assert r.json() == {"host": "192.168.1.52", "reachable": True, "volume": 23, "treble": 5.0, "light": True,
                        "bass": -1.0, "brightness": 100, "rgb": {"red": 255, "green": 6, "blue": 126}, "mute": False, "loudness": False, "balance": 0.0, "errors": {}}
    assert fake.sets() == []
    assert all(rq.url.path == "/api/getData" for rq in fake.requests)
    q = parse_qs(urlsplit(str(fake.requests[0].url)).query)
    assert q == {"path": ["player:volume"], "roles": ["value"]}


def test_volume_write_is_encoded_and_verified(client, fake):
    r = client.post("/api/speaker/volume", json={"value": 28}, headers=H)
    assert r.status_code == 200 and r.json()["volume"] == 28
    s = fake.sets()
    assert len(s) == 1
    assert s[0]["path"] == "player:volume" and s[0]["role"] == "value"
    assert json.loads(s[0]["value"]) == {"type": "i32_", "i32_": 28}
    raw = str(fake.requests[0].url)  # the colon, braces and quotes travel percent-encoded, built by httpx
    assert "%7B" in raw and '"' not in raw and " " not in raw


def test_treble_and_light(client, fake):
    r = client.post("/api/speaker/treble", json={"value": 6}, headers=H)
    assert r.status_code == 200 and r.json()["treble"] == 6.0
    assert json.loads(fake.sets()[-1]["value"]) == {"type": "double_", "double_": 6.0}
    r = client.post("/api/speaker/light", json={"enabled": False}, headers=H)
    assert r.status_code == 200 and r.json()["light"] is False
    assert json.loads(fake.sets()[-1]["value"]) == {"type": "bool_", "bool_": False}
    events = [a["event"] for a in client.get("/api/audit", headers=H).json()]
    assert events.count("speaker") == 2


def test_error_inside_http_200_is_not_success(client, fake):
    fake.error_on_set = True
    r = client.post("/api/speaker/volume", json={"value": 30}, headers=H)
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "DENIED" and "Invalid value" in r.json()["detail"]["message"]
    assert fake.values["player:volume"]["i32_"] == 23


def test_accepted_but_unchanged_is_not_success(client, fake):
    fake.ignore_set = True  # what attenuation did: 200, no error, nothing changed
    r = client.post("/api/speaker/treble", json={"value": 2}, headers=H)
    assert r.status_code == 502 and "לא השתנה" in r.json()["detail"]["message"]


def test_unreachable_and_timeout(client, fake):
    fake.unreachable = True
    r = client.get("/api/speaker", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["reachable"] is False and body["volume"] is None and body["light"] is None
    assert len(fake.requests) == 1  # stops after the first failure instead of waiting on every path
    r = client.post("/api/speaker/volume", json={"value": 20}, headers=H)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "NOT_CONNECTED"
    fake.unreachable, fake.slow = False, True
    r = client.post("/api/speaker/light", json={"enabled": True}, headers=H)
    assert r.status_code == 504 and r.json()["detail"]["code"] == "TIMEOUT"


def test_unexpected_type_is_rejected(client, fake):
    fake.values["player:volume"] = {"type": "string_", "string_": "loud"}
    body = client.get("/api/speaker", headers=H).json()
    assert body["volume"] is None and "volume" in body["errors"] and body["reachable"] is True
    assert body["treble"] == 5.0


@pytest.mark.parametrize("url,payload", [
    ("/api/speaker/volume", {"value": 51}),
    ("/api/speaker/volume", {"value": -1}),
    ("/api/speaker/volume", {"value": 20.5}),
    ("/api/speaker/volume", {"value": "20"}),
    ("/api/speaker/volume", {"value": True}),
    ("/api/speaker/treble", {"value": 10.5}), ("/api/speaker/treble", {"value": -11}), ("/api/speaker/treble", {"value": 7.25}),
    ("/api/speaker/treble", {"value": "5"}),
    ("/api/speaker/light", {"enabled": "true"}),
    ("/api/speaker/light", {"enabled": 1}),
    ("/api/speaker/volume", {"value": 20, "path": "settings:/mediaPlayer/attenuation"}),
    ("/api/speaker/bass", {"value": 11}), ("/api/speaker/bass", {"value": -10.5}), ("/api/speaker/bass", {"value": 2.3}),
    ("/api/speaker/bass", {"value": "2"}),
    ("/api/speaker/brightness", {"value": 101}), ("/api/speaker/brightness", {"value": -1}), ("/api/speaker/brightness", {"value": 50.5}),
    ("/api/speaker/rgb", {"red": 256, "green": 0, "blue": 0}), ("/api/speaker/rgb", {"red": 1, "green": 2}),
    ("/api/speaker/rgb", {"red": True, "green": 0, "blue": 0}),
    ("/api/speaker/mute", {"enabled": "true"}), ("/api/speaker/mute", {"enabled": 0}),
    ("/api/speaker/loudness", {"enabled": "true"}), ("/api/speaker/loudness", {"enabled": 1}), ("/api/speaker/loudness", {"value": True}),
    ("/api/speaker/balance", {"value": "1"}), ("/api/speaker/balance", {"value": True}), ("/api/speaker/balance", {}),
])
def test_invalid_values_never_reach_the_speaker(client, fake, url, payload):
    r = client.post(url, json=payload, headers=H)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_COMMAND"
    assert fake.requests == []


@pytest.mark.parametrize("method,url", [
    ("post", "/api/speaker/attenuation"), ("post", "/api/speaker/set"), ("post", "/api/speaker/path"),
    ("post", "/api/speaker/sourceGain"), ("post", "/api/speaker/source_gain"), ("put", "/api/speaker/sourceGain"),  # speaker: "Setting is not modifiable"
    ("post", "/api/speaker/eq_raw"), ("get", "/api/speaker/raw?path=player:volume"),
])
def test_no_generic_or_unverified_path_endpoint(client, fake, method, url):
    kw = {"json": {"value": 1, "path": "settings:/mediaPlayer/bass"}} if method == "post" else {}
    r = getattr(client, method)(url, headers=H, **kw)
    assert r.status_code in (404, 405)
    assert fake.sets() == []


def test_host_change_is_admin_only_validated_and_saved(client, fake):
    t = client.post("/api/tokens", json={"name": "טלפון"}, headers=H).json()["token"]
    assert client.put("/api/speaker/config", json={"host": "192.168.1.60"}, headers={"Authorization": f"Bearer {t}"}).status_code == 403
    for bad in ("8.8.8.8", "127.0.0.1", "speaker.local", "192.168.1.5/admin"):
        assert client.put("/api/speaker/config", json={"host": bad}, headers=H).status_code == 422
    r = client.put("/api/speaker/config", json={"host": "192.168.1.60"}, headers=H)
    assert r.status_code == 200 and r.json()["host"] == "192.168.1.60"
    assert fake.requests[-1].url.host == "192.168.1.60"
    assert fake.sets() == []  # changing the address writes nothing to the speaker
    assert client.app.state.manager.store.get_state("speaker", "host") == "192.168.1.60"


def test_saved_host_survives_restart(tmp_path):
    s = Settings(access_token=MASTER, db_path=str(tmp_path / "db.sqlite"), use_mock_adapters=True)
    app = create_app(s)
    app.state.manager.store.set_state("speaker", "host", "192.168.1.77")
    assert create_app(s).state.speaker.host == "192.168.1.77"


def test_env_host_is_validated():
    with pytest.raises(ValueError):
        create_app(Settings(access_token=MASTER, db_path=":memory:", use_mock_adapters=True, zeppelin_host="1.2.3.4"))


def test_kids_code_can_read_but_not_change(client, fake):
    policy = {"start": "00:00", "end": "23:59", "apps": [], "daily_limit_min": None, "can_power_off": False, "can_schedule": False}
    t = client.post("/api/tokens", json={"name": "ילד", "policy": policy}, headers=H).json()["token"]
    kid = {"Authorization": f"Bearer {t}"}
    assert client.get("/api/speaker", headers=kid).status_code == 200
    r = client.post("/api/speaker/volume", json={"value": 60}, headers=kid)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "DENIED"
    assert fake.sets() == []


@pytest.mark.parametrize("name,value", [("treble", 7), ("treble", 10), ("treble", -10), ("treble", 6.5),
                                        ("bass", -10), ("bass", 10), ("bass", 7.5), ("bass", -6.5)])
def test_tone_full_declared_range_in_half_steps(client, fake, name, value):
    """Both nodes declare -10..+10 step 0.5; the reply is the value read back from the speaker."""
    r = client.post(f"/api/speaker/{name}", json={"value": value}, headers=H)
    assert r.status_code == 200 and r.json()[name] == float(value)
    assert json.loads(fake.sets()[-1]["value"]) == {"type": "double_", "double_": float(value)}


async def test_client_refuses_tone_outside_range_or_step(fake):
    """The client checks again, so a stored profile with a bad value can never reach the speaker either."""
    sp = ZeppelinClient(transport=httpx.MockTransport(fake.handler))
    for name, bad in (("treble", 10.5), ("bass", -11), ("bass", 1.25), ("treble", True), ("bass", "3")):
        with pytest.raises(SpeakerError) as e:
            await sp.write(name, bad)
        assert e.value.http == 422
    assert fake.sets() == []
    await sp.aclose()


def test_bass_brightness_and_colour(client, fake):
    r = client.post("/api/speaker/bass", json={"value": -6}, headers=H)
    assert r.status_code == 200 and r.json()["bass"] == -6.0
    assert json.loads(fake.sets()[-1]["value"]) == {"type": "double_", "double_": -6.0}
    r = client.post("/api/speaker/brightness", json={"value": 0}, headers=H)
    assert r.status_code == 200 and r.json()["brightness"] == 0
    assert json.loads(fake.sets()[-1]["value"]) == {"type": "i32_", "i32_": 0}
    r = client.post("/api/speaker/rgb", json={"red": 24, "green": 69, "blue": 129}, headers=H)
    assert r.status_code == 200 and r.json()["rgb"] == {"red": 24, "green": 69, "blue": 129}
    assert json.loads(fake.sets()[-1]["value"]) == {"type": "formationDownlightRgb", "formationDownlightRgb": {"red": 24, "green": 69, "blue": 129}}
    assert [s["path"] for s in fake.sets()] == ["settings:/mediaPlayer/bass", "settings:/ui/ambientLightBrightness", "settings:/ui/ambientLightRgb"]


def test_new_controls_report_no_false_success(client, fake):
    fake.ignore_set = True
    assert client.post("/api/speaker/rgb", json={"red": 1, "green": 2, "blue": 3}, headers=H).status_code == 502
    fake.ignore_set, fake.error_on_set = False, True
    assert client.post("/api/speaker/brightness", json={"value": 30}, headers=H).status_code == 502


def test_kids_cannot_change_new_controls(client, fake):
    policy = {"start": "00:00", "end": "23:59", "apps": [], "daily_limit_min": None, "can_power_off": False, "can_schedule": False}
    t = client.post("/api/tokens", json={"name": "ילד", "policy": policy}, headers=H).json()["token"]
    kid = {"Authorization": f"Bearer {t}"}
    for url, body in [("/api/speaker/bass", {"value": 1}), ("/api/speaker/brightness", {"value": 10}), ("/api/speaker/rgb", {"red": 0, "green": 0, "blue": 0})]:
        assert client.post(url, json=body, headers=kid).status_code == 403
    assert fake.sets() == []


def test_mute_on_off_read_back(client, fake):
    r = client.post("/api/speaker/mute", json={"enabled": True}, headers=H)
    assert r.status_code == 200 and r.json()["mute"] is True
    assert json.loads(fake.sets()[-1]["value"]) == {"type": "bool_", "bool_": True}
    r = client.post("/api/speaker/mute", json={"enabled": False}, headers=H)
    assert r.status_code == 200 and r.json()["mute"] is False
    assert {x["path"] for x in fake.sets()} == {"settings:/mediaPlayer/mute"}  # nothing else touched


def test_mute_no_false_success(client, fake):
    fake.error_on_set = True
    assert client.post("/api/speaker/mute", json={"enabled": True}, headers=H).status_code == 502
    fake.error_on_set, fake.ignore_set = False, True
    r = client.post("/api/speaker/mute", json={"enabled": True}, headers=H)
    assert r.status_code == 502 and "לא השתנה" in r.json()["detail"]["message"]


def test_kids_cannot_mute(client, fake):
    policy = {"start": "00:00", "end": "23:59", "apps": [], "daily_limit_min": None, "can_power_off": False, "can_schedule": False}
    t = client.post("/api/tokens", json={"name": "ילד", "policy": policy}, headers=H).json()["token"]
    kid = {"Authorization": f"Bearer {t}"}
    assert client.post("/api/speaker/mute", json={"enabled": True}, headers=kid).status_code == 403
    assert fake.sets() == []


def test_loudness_on_off_is_encoded_and_read_back(client, fake):
    r = client.post("/api/speaker/loudness", json={"enabled": True}, headers=H)
    assert r.status_code == 200 and r.json()["loudness"] is True
    assert json.loads(fake.sets()[-1]["value"]) == {"type": "bool_", "bool_": True}
    r = client.post("/api/speaker/loudness", json={"enabled": False}, headers=H)
    assert r.status_code == 200 and r.json()["loudness"] is False
    assert {x["path"] for x in fake.sets()} == {"settings:/mediaPlayer/loudness"}  # nothing else touched


def test_loudness_no_false_success(client, fake):
    fake.error_on_set = True
    r = client.post("/api/speaker/loudness", json={"enabled": True}, headers=H)
    assert r.status_code == 502 and "Invalid value" in r.json()["detail"]["message"]
    fake.error_on_set, fake.ignore_set = False, True
    assert client.post("/api/speaker/loudness", json={"enabled": True}, headers=H).status_code == 502
    assert client.get("/api/speaker", headers=H).json()["loudness"] is False


def test_balance_in_the_chosen_range(client, fake):
    for v in (1, 6, -6, -1, 0):  # values tried on the real speaker, the edges, and centre
        r = client.post("/api/speaker/balance", json={"value": v}, headers=H)
        assert r.status_code == 200 and r.json()["balance"] == float(v)
        assert json.loads(fake.sets()[-1]["value"]) == {"type": "double_", "double_": float(v)}
    n = len(fake.sets())
    for v in (6.5, -7, 37.5):  # outside -6..+6: refused here (the lab still accepts any number)
        assert client.post("/api/speaker/balance", json={"value": v}, headers=H).status_code == 422
    assert len(fake.sets()) == n
    r = client.post("/api/speaker/balance", content='{"value": NaN}', headers={**H, "Content-Type": "application/json"})
    assert r.status_code == 422
    assert {x["path"] for x in fake.sets()} == {"settings:/mediaPlayer/balance"}


def test_balance_no_false_success(client, fake):
    fake.ignore_set = True
    r = client.post("/api/speaker/balance", json={"value": 1}, headers=H)
    assert r.status_code == 502 and "לא השתנה" in r.json()["detail"]["message"]


def test_kids_cannot_change_loudness_or_balance(client, fake):
    policy = {"start": "00:00", "end": "23:59", "apps": [], "daily_limit_min": None, "can_power_off": False, "can_schedule": False}
    t = client.post("/api/tokens", json={"name": "ילד", "policy": policy}, headers=H).json()["token"]
    kid = {"Authorization": f"Bearer {t}"}
    assert client.post("/api/speaker/loudness", json={"enabled": True}, headers=kid).status_code == 403
    assert client.post("/api/speaker/balance", json={"value": 1}, headers=kid).status_code == 403
    assert fake.sets() == []
