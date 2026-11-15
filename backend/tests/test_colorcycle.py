"""Automatic colour cycling on the server: explicit start only, one task, verified writes, clean stops. No real speaker."""
import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.colorcycle import FADE_MAX_S, FADE_STEP_S, blend
from app.services.zeppelin import ZeppelinClient
from tests.test_zeppelin import H, MASTER, FakeSpeaker

RGB = "settings:/ui/ambientLightRgb"
PALETTE = [{"red": 255, "green": 0, "blue": 0}, {"red": 0, "green": 255, "blue": 0}, {"red": 0, "green": 0, "blue": 255}]


async def fast_sleep(_seconds: float) -> None:
    await asyncio.sleep(0.02)  # the real interval is seconds; the behaviour under test is the same


def wait_until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def rgb_sets(fake):
    return [json.loads(s["value"])["formationDownlightRgb"] for s in fake.sets() if s["path"] == RGB]


@pytest.fixture
def fake():
    return FakeSpeaker()


@pytest.fixture
def client(fake):
    app = create_app(Settings(access_token=MASTER, db_path=":memory:", use_mock_adapters=True))
    app.state.speaker = ZeppelinClient("192.168.1.52", transport=httpx.MockTransport(fake.handler))
    app.state.cycle.sleep = fast_sleep
    with TestClient(app) as c:
        c.put("/api/speaker/cycle/config", json={"interval_s": 10, "mode": "palette", "palette": PALETTE}, headers=H)
        yield c


def test_defaults_and_never_started_at_boot(client, fake):
    body = client.get("/api/speaker/cycle", headers=H).json()
    assert body["status"]["running"] is False and body["status"]["state"] == "stopped"
    assert body["config"]["interval_s"] == 10
    assert fake.sets() == []


def test_saved_config_does_not_start_anything_after_restart(tmp_path, fake):
    s = Settings(access_token=MASTER, db_path=str(tmp_path / "db.sqlite"), use_mock_adapters=True)
    for _ in range(2):
        app = create_app(s)
        app.state.speaker = ZeppelinClient("192.168.1.52", transport=httpx.MockTransport(fake.handler))
        with TestClient(app) as c:
            c.put("/api/speaker/cycle/config", json={"interval_s": 5, "mode": "random", "palette": []}, headers=H)
            body = c.get("/api/speaker/cycle", headers=H).json()
            assert body["config"]["interval_s"] == 5 and body["status"]["running"] is False
    assert fake.sets() == []


def test_light_off_refuses_to_start(client, fake):
    fake.values["settings:/ui/ambientLightEnabled"]["bool_"] = False
    r = client.post("/api/speaker/cycle/start", headers=H)
    assert r.status_code == 409 and "להדליק" in r.json()["detail"]["message"]
    assert fake.sets() == []


def test_cycles_through_the_palette_writing_only_the_colour(client, fake):
    fake.values[RGB]["formationDownlightRgb"] = dict(PALETTE[0])  # already showing the first colour: start from the next
    assert client.post("/api/speaker/cycle/start", headers=H).json()["status"]["running"] is True
    assert wait_until(lambda: len(rgb_sets(fake)) >= 4)
    client.post("/api/speaker/cycle/stop", headers=H)
    seq = rgb_sets(fake)
    assert seq[:4] == [PALETTE[1], PALETTE[2], PALETTE[0], PALETTE[1]]
    assert {s["path"] for s in fake.sets()} == {RGB}  # brightness and everything else untouched


def test_one_cycle_per_speaker(client, fake):
    client.post("/api/speaker/cycle/start", headers=H)
    task = client.app.state.cycle._task
    for _ in range(3):
        client.post("/api/speaker/cycle/start", headers=H)
    assert client.app.state.cycle._task is task
    tasks = client.portal.call(lambda: asyncio.sleep(0, [t for t in asyncio.all_tasks() if t.get_name() == "zeppelin-colour-cycle"]))
    assert len(tasks) == 1
    client.post("/api/speaker/cycle/stop", headers=H)


def test_stop_keeps_the_last_colour_and_writes_nothing_more(client, fake):
    client.post("/api/speaker/cycle/start", headers=H)
    assert wait_until(lambda: len(rgb_sets(fake)) >= 2)
    body = client.post("/api/speaker/cycle/stop", headers=H).json()
    assert body["status"]["running"] is False and body["status"]["state"] == "stopped"
    n = len(fake.sets())
    time.sleep(0.2)
    assert len(fake.sets()) == n  # nothing after stop, and no "restore" write
    assert fake.values[RGB]["formationDownlightRgb"] == body["status"]["last_colour"]


def test_manual_colour_stops_the_cycle(client, fake):
    client.post("/api/speaker/cycle/start", headers=H)
    assert wait_until(lambda: len(rgb_sets(fake)) >= 1)
    r = client.post("/api/speaker/rgb", json={"red": 9, "green": 9, "blue": 9}, headers=H)
    assert r.status_code == 200
    st = client.get("/api/speaker/cycle", headers=H).json()["status"]
    assert st["running"] is False and "ידני" in st["message"]
    time.sleep(0.2)
    assert fake.values[RGB]["formationDownlightRgb"] == {"red": 9, "green": 9, "blue": 9}  # the manual colour stays


def test_light_off_stops_the_cycle(client, fake):
    client.post("/api/speaker/cycle/start", headers=H)
    assert wait_until(lambda: len(rgb_sets(fake)) >= 1)
    client.post("/api/speaker/light", json={"enabled": False}, headers=H)
    st = client.get("/api/speaker/cycle", headers=H).json()["status"]
    assert st["running"] is False and "כובתה" in st["message"]


def test_disconnect_stops_without_retries_or_catch_up(client, fake):
    client.post("/api/speaker/cycle/start", headers=H)
    assert wait_until(lambda: len(rgb_sets(fake)) >= 2)
    fake.unreachable = True
    assert wait_until(lambda: client.get("/api/speaker/cycle", headers=H).json()["status"]["state"] == "disconnected")
    n = len(fake.requests)
    time.sleep(0.3)
    assert len(fake.requests) == n  # no flood of retries
    st = client.get("/api/speaker/cycle", headers=H).json()["status"]
    assert st["running"] is False and "לא זמין" in st["message"]
    fake.unreachable = False
    time.sleep(0.2)
    assert len(fake.requests) == n  # nothing resumes or makes up missed colours on its own


def test_speaker_error_stops_with_a_message(client, fake):
    client.post("/api/speaker/cycle/start", headers=H)
    assert wait_until(lambda: len(rgb_sets(fake)) >= 1)
    fake.error_on_set = True
    assert wait_until(lambda: client.get("/api/speaker/cycle", headers=H).json()["status"]["state"] == "error")


def test_random_mode_changes_colour_every_step(client, fake):
    client.put("/api/speaker/cycle/config", json={"interval_s": 10, "mode": "random", "palette": []}, headers=H)
    client.post("/api/speaker/cycle/start", headers=H)
    assert wait_until(lambda: len(rgb_sets(fake)) >= 5)
    client.post("/api/speaker/cycle/stop", headers=H)
    seq = rgb_sets(fake)
    assert all(a != b for a, b in zip(seq, seq[1:]))
    assert all(0 <= c[k] <= 255 for c in seq for k in ("red", "green", "blue"))


def test_palette_needs_two_colours(client, fake):
    client.put("/api/speaker/cycle/config", json={"interval_s": 10, "mode": "palette", "palette": PALETTE[:1]}, headers=H)
    assert client.post("/api/speaker/cycle/start", headers=H).status_code == 422
    assert fake.sets() == []


@pytest.mark.parametrize("cfg", [
    {"interval_s": 2, "mode": "palette", "palette": PALETTE},
    {"interval_s": 3601, "mode": "palette", "palette": PALETTE},
    {"interval_s": 10.5, "mode": "palette", "palette": PALETTE},
    {"interval_s": 10, "mode": "rainbow", "palette": PALETTE},
    {"interval_s": 10, "mode": "palette", "palette": PALETTE * 5},
    {"interval_s": 10, "mode": "palette", "palette": [{"red": 300, "green": 0, "blue": 0}]},
    {"interval_s": 10, "mode": "palette", "palette": PALETTE, "brightness": 50},
])
def test_invalid_config_rejected(client, cfg):
    assert client.put("/api/speaker/cycle/config", json=cfg, headers=H).status_code == 422


def test_kids_cannot_start(client, fake):
    policy = {"start": "00:00", "end": "23:59", "apps": [], "daily_limit_min": None, "can_power_off": False, "can_schedule": False}
    t = client.post("/api/tokens", json={"name": "ילד", "policy": policy}, headers=H).json()["token"]
    assert client.post("/api/speaker/cycle/start", headers={"Authorization": f"Bearer {t}"}).status_code == 403
    assert fake.sets() == []


def test_shutdown_stops_and_clears_the_task(fake):
    app = create_app(Settings(access_token=MASTER, db_path=":memory:", use_mock_adapters=True))
    app.state.speaker = ZeppelinClient("192.168.1.52", transport=httpx.MockTransport(fake.handler))
    app.state.cycle.sleep = fast_sleep
    with TestClient(app) as c:
        c.put("/api/speaker/cycle/config", json={"interval_s": 10, "mode": "palette", "palette": PALETTE}, headers=H)
        c.post("/api/speaker/cycle/start", headers=H)
        assert wait_until(lambda: len(rgb_sets(fake)) >= 1)
    assert app.state.cycle._task is None and app.state.cycle.running is False
    n = len(fake.sets())
    time.sleep(0.2)
    assert len(fake.sets()) == n


def test_blend_goes_round_the_hue_wheel_not_through_grey():
    red, blue = {"red": 255, "green": 0, "blue": 0}, {"red": 0, "green": 0, "blue": 255}
    mid = blend(red, blue, 0.5)
    assert mid == {"red": 255, "green": 0, "blue": 255}  # magenta (the short way), vivid - not the RGB midpoint (128,0,128)
    assert blend(red, blue, 0) == red and blend(red, blue, 1) == blue
    white = {"red": 255, "green": 255, "blue": 255}
    m = blend(white, red, 0.5)
    assert m["red"] == 255 and m["green"] == m["blue"]  # a lighter red, no stray hue


def test_smooth_writes_intermediate_colours_then_the_exact_target(client, fake):
    fake.values[RGB]["formationDownlightRgb"] = dict(PALETTE[0])
    client.put("/api/speaker/cycle/config", json={"interval_s": 10, "mode": "palette", "palette": PALETTE, "smooth": True}, headers=H)
    client.post("/api/speaker/cycle/start", headers=H)
    per_fade = int(FADE_MAX_S / FADE_STEP_S)  # steps for a 10 s interval (3 s transition)
    assert wait_until(lambda: len(rgb_sets(fake)) >= per_fade * 2)
    client.post("/api/speaker/cycle/stop", headers=H)
    seq = rgb_sets(fake)
    first = seq[:per_fade]
    assert first[-1] == PALETTE[1]  # ends exactly on the palette colour
    assert len(first) == per_fade and all(c not in (PALETTE[0], PALETTE[1]) for c in first[:-1])  # in-between colours
    assert first[per_fade // 2 - 1] == {"red": 255, "green": 255, "blue": 0}  # halfway red -> green is pure yellow
    assert {s["path"] for s in fake.sets()} == {RGB}  # brightness untouched


def test_smooth_transition_is_bounded_and_stops_mid_fade(client, fake):
    client.put("/api/speaker/cycle/config", json={"interval_s": 3, "mode": "random", "palette": [], "smooth": True}, headers=H)
    client.post("/api/speaker/cycle/start", headers=H)
    assert wait_until(lambda: len(rgb_sets(fake)) >= 2)
    client.post("/api/speaker/cycle/stop", headers=H)
    n = len(fake.sets())
    time.sleep(0.2)
    assert len(fake.sets()) == n  # stopping inside a transition stops at once
    assert int(min(FADE_MAX_S, 3 / 2) / FADE_STEP_S) <= 5  # a 3 s interval fades in at most a few writes


def test_old_saved_config_without_smooth_still_works(client, fake):
    client.app.state.manager.store.set_state("speaker", "colour_cycle", json.dumps({"interval_s": 10, "mode": "palette", "palette": PALETTE}))
    assert client.get("/api/speaker/cycle", headers=H).json()["config"]["smooth"] is False
