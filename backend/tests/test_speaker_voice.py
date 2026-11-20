"""Voice commands and schedules for the speaker: a closed vocabulary over verified controls, read back, no false success."""
import asyncio
import time

import pytest

from app.services.intents import LLMIntentProvider, RuleBasedIntentProvider
from tests.test_zeppelin import H, FakeSpeaker, client, fake  # noqa: F401 - fixtures

rules = RuleBasedIntentProvider()
KID_POLICY = {"start": "00:00", "end": "23:59", "apps": [], "daily_limit_min": None, "can_power_off": False, "can_schedule": True}


def parse(text, profiles=None):
    return asyncio.run(rules.parse(text, "lg", profiles or []))


def one(text, profiles=None):
    out = parse(text, profiles)
    assert not out.unrecognized and len(out.steps) == 1, (text, out)
    s = out.steps[0]
    return s.target, s.action.value, s.params


@pytest.mark.parametrize("text,expected", [
    ("תגביר את הרמקול", ("speaker", "speaker_volume", {"delta": 3})),
    ("הרמקול חזק יותר ב 5", ("speaker", "speaker_volume", {"delta": 5})),
    ("תנמיך את הרמקול", ("speaker", "speaker_volume", {"delta": -3})),
    ("עוצמה 25 ברמקול", ("speaker", "speaker_volume", {"value": 25})),
    ("השתק את הרמקול", ("speaker", "speaker_mute", {"enabled": True})),
    ("תבטל השתקה ברמקול", ("speaker", "speaker_mute", {"enabled": False})),
    ("יותר בס", ("speaker", "speaker_bass", {"delta": 2})),
    ("פחות בס", ("speaker", "speaker_bass", {"delta": -2})),
    ("בס מינוס 3", ("speaker", "speaker_bass", {"value": -3})),
    ("טרבל 4", ("speaker", "speaker_treble", {"value": 4})),
    ("אור כחול", ("speaker", "speaker_color", {"color": "כחול"})),
    ("שנה את הצבע לאדום", ("speaker", "speaker_color", {"color": "אדום"})),
    ("כבה את האור", ("speaker", "speaker_light", {"enabled": False})),
    ("הדלק תאורה", ("speaker", "speaker_light", {"enabled": True})),
    ("בהירות 50%", ("speaker", "speaker_brightness", {"value": 50})),
    ("מחזור צבעים", ("speaker", "speaker_cycle", {"enabled": True})),
    ("עצור את החלפת הצבעים", ("speaker", "speaker_cycle", {"enabled": False})),
])
def test_speaker_sentences(text, expected):
    assert one(text) == expected


def test_volume_without_the_speaker_still_goes_to_the_tv():
    assert one("תגביר") == ("lg", "volume_up", {})
    assert one("השתק") == ("lg", "mute", {})


def test_out_of_range_or_unknown_is_not_guessed():
    for t in ("עוצמה 80 ברמקול", "בס 15", "אור חום", "בהירות 300", "תפתח את הרמקול", "פרופיל לא קיים"):
        out = parse(t, [("p1", "ערב")])
        assert out.steps == [] and out.unrecognized == [t], t


def test_profile_by_name_and_delay_and_mixed_sentence():
    assert one("פרופיל ערב", [("p1", "ערב")]) == ("speaker", "speaker_profile", {"id": "p1"})
    out = parse("ערוץ 12 ואז השתק את הרמקול בעוד שעה")
    assert [(s.target, s.action.value, s.delay_seconds) for s in out.steps] == [("hot", "digits", 0), ("speaker", "speaker_mute", 3600)]
    assert out.steps[1].label == "רמקול: השתקה (בעוד שעה)"


def test_llm_provider_answers_speaker_sentences_with_the_rules_without_a_call():
    class NoCall:
        class messages:
            @staticmethod
            async def parse(**_):
                raise AssertionError("the model must not be called")
    llm = LLMIntentProvider("k", "m", rules, client=NoCall())
    out = asyncio.run(llm.parse("השתק את הרמקול", "lg", []))
    assert out.provider == "rules" and out.steps[0].action.value == "speaker_mute"


# ---- the endpoint

def vol(fake):
    return fake.values["player:volume"]["i32_"]


def test_parse_endpoint_knows_the_saved_profiles(client, fake):
    pid = client.app.state.profiles.profiles.add("ערב", False, {}, time.time())["id"]
    r = client.post("/api/intents/parse", json={"text": "פרופיל ערב"}, headers=H).json()
    assert r["steps"][0]["target"] == "speaker" and r["steps"][0]["params"] == {"id": pid}


def test_step_relative_volume_reads_clamps_and_reads_back(client, fake):
    r = client.post("/api/speaker/step", json={"op": "speaker_volume", "params": {"delta": 3}}, headers=H)
    assert r.status_code == 200 and r.json()["volume"] == 26 and vol(fake) == 26
    fake.values["player:volume"]["i32_"] = 49
    assert client.post("/api/speaker/step", json={"op": "speaker_volume", "params": {"delta": 5}}, headers=H).json()["volume"] == 50
    assert [s["path"] for s in fake.sets()] == ["player:volume", "player:volume"]


def test_step_colour_bass_mute(client, fake):
    client.post("/api/speaker/step", json={"op": "speaker_color", "params": {"color": "כחול"}}, headers=H)
    assert fake.values["settings:/ui/ambientLightRgb"]["formationDownlightRgb"] == {"red": 0, "green": 0, "blue": 255}
    client.post("/api/speaker/step", json={"op": "speaker_bass", "params": {"delta": -2}}, headers=H)
    assert fake.values["settings:/mediaPlayer/bass"]["double_"] == -3.0
    client.post("/api/speaker/step", json={"op": "speaker_mute", "params": {"enabled": True}}, headers=H)
    assert fake.values["settings:/mediaPlayer/mute"]["bool_"] is True


@pytest.mark.parametrize("body", [
    {"op": "speaker_volume", "params": {"value": 51}},
    {"op": "speaker_volume", "params": {"value": 10, "delta": 2}},
    {"op": "speaker_volume", "params": {"delta": 0}},
    {"op": "speaker_volume", "params": {"value": True}},
    {"op": "speaker_color", "params": {"color": "#ff0000"}},
    {"op": "speaker_color", "params": {"red": 1, "green": 2, "blue": 3}},
    {"op": "speaker_mute", "params": {"enabled": "yes"}},
    {"op": "speaker_profile", "params": {"id": "../x"}},
    {"op": "speaker_path", "params": {"path": "settings:/x"}},
    {"op": "speaker_volume", "params": {"value": 5}, "path": "player:volume"},
])
def test_step_rejects_anything_outside_the_vocabulary(client, fake, body):
    assert client.post("/api/speaker/step", json=body, headers=H).status_code == 422
    assert fake.sets() == []


def test_step_no_false_success(client, fake):
    fake.ignore_set = True
    r = client.post("/api/speaker/step", json={"op": "speaker_volume", "params": {"value": 10}}, headers=H)
    assert r.status_code == 502
    fake.ignore_set, fake.error_on_set = False, True
    assert client.post("/api/speaker/step", json={"op": "speaker_mute", "params": {"enabled": True}}, headers=H).status_code == 502


def test_step_auth_and_kids(client, fake):
    body = {"op": "speaker_mute", "params": {"enabled": True}}
    assert client.post("/api/speaker/step", json=body).status_code == 401
    t = client.post("/api/tokens", json={"name": "kid", "policy": KID_POLICY}, headers=H).json()["token"]
    kid = {"Authorization": f"Bearer {t}"}
    assert client.post("/api/speaker/step", json=body, headers=kid).status_code == 403
    r = client.post("/api/schedule", json={"target": "speaker", "action": "speaker_mute", "params": {"enabled": True},
                                          "delay_seconds": 60}, headers=kid)
    assert r.status_code == 403 and fake.sets() == []


# ---- schedules

def sched(client, action, params, delay=1):
    return client.post("/api/schedule", json={"target": "speaker", "action": action, "params": params,
                                              "delay_seconds": delay, "label": "x"}, headers=H)


def test_scheduled_speaker_step_runs_on_time_and_reads_back(client, fake):
    r = sched(client, "speaker_volume", {"value": 12})
    assert r.status_code == 201, r.text
    assert fake.sets() == []  # nothing before it is due
    asyncio.run(client.app.state.scheduler.tick(time.time() + 2))
    assert vol(fake) == 12
    s = client.get("/api/schedule", headers=H).json()[0]
    assert s["status"] == "done" and s["target"] == "speaker"


def test_scheduled_speaker_failure_is_reported(client, fake):
    sched(client, "speaker_mute", {"enabled": True})
    fake.ignore_set = True
    asyncio.run(client.app.state.scheduler.tick(time.time() + 2))
    s = client.get("/api/schedule", headers=H).json()[0]
    assert s["status"] == "failed" and "הערך לא השתנה" in s["error"]


def test_schedule_mixing_targets_and_ops_is_refused(client, fake):
    assert client.post("/api/schedule", json={"target": "lg", "action": "speaker_mute", "params": {"enabled": True},
                                              "delay_seconds": 60}, headers=H).status_code == 422
    assert client.post("/api/schedule", json={"target": "speaker", "action": "mute", "params": {},
                                              "delay_seconds": 60}, headers=H).status_code == 422
    assert sched(client, "speaker_volume", {"value": 99}).status_code == 422
