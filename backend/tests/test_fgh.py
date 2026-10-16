"""Steps F/G/H: server-side digit sequences, Hebrew intent parsing, LLM provider guardrails, scheduler."""
import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models.schemas import ScheduleCreate
from app.services.intents import LLMIntentProvider, LlmOut, LlmStep, RuleBasedIntentProvider, build_provider

TOKEN = "test-token-123"
H = {"Authorization": f"Bearer {TOKEN}"}
rules = RuleBasedIntentProvider()


@pytest.fixture
def client():
    with TestClient(create_app(Settings(access_token=TOKEN, db_path=":memory:", use_mock_adapters=True))) as c:
        yield c


def paired(client, kind):
    d = client.post("/api/devices", json={"kind": kind, "host": "192.168.1.30" if kind == "hot" else "192.168.1.31"}, headers=H).json()
    client.post(f"/api/devices/{d['id']}/pair/confirm", json={"code": "123456"}, headers=H)
    return d["id"]


# ------------------------------------------------------------------ F: digits
def test_digits_sent_as_one_ordered_sequence_with_enter(client):
    did = paired(client, "hot")
    body = {"target": did, "action": "digits", "request_id": "req-digits-1",
            "params": {"digits": "12", "delay_ms": 50, "enter": True}}
    assert client.post(f"/api/devices/{did}/commands", json=body, headers=H).json()["status"] == "sent"
    sent = client.app.state.manager.adapters[did].sent
    assert [p["key"] for _, p in sent] == ["KEYCODE_1", "KEYCODE_2", "DPAD_CENTER"]


@pytest.mark.parametrize("params", [{"digits": "12345"}, {"digits": "ab"}, {"digits": "1", "delay_ms": 5},
                                    {"digits": "1", "delay_ms": 99999}, {"digits": "1", "enter": "yes"}, {}])
def test_digits_validation(client, params):
    did = paired(client, "hot")
    body = {"target": did, "action": "digits", "request_id": "req-digits-bad", "params": params}
    assert client.post(f"/api/devices/{did}/commands", json=body, headers=H).status_code == 422


def test_digits_rejected_on_lg(client):
    did = paired(client, "lg")
    body = {"target": did, "action": "digits", "request_id": "req-digits-lg", "params": {"digits": "1"}}
    assert client.post(f"/api/devices/{did}/commands", json=body, headers=H).json()["detail"]["code"] == "UNSUPPORTED"


def test_digit_failure_stops_the_sequence(client):
    did = paired(client, "hot")
    ad = client.app.state.manager.adapters[did]
    orig = ad.execute
    calls = []

    async def flaky(action, params):
        calls.append(params["key"])
        if len(calls) == 2:
            from app.adapters.base import AdapterError
            from app.models.schemas import ErrorCode
            raise AdapterError(ErrorCode.NOT_CONNECTED, "נפל")
        await orig(action, params)

    ad.execute = flaky
    body = {"target": did, "action": "digits", "request_id": "req-digits-f", "params": {"digits": "123", "delay_ms": 50}}
    r = client.post(f"/api/devices/{did}/commands", json=body, headers=H)
    assert r.status_code == 409 and calls == ["KEYCODE_1", "KEYCODE_2"]  # 3 never sent


# ------------------------------------------------------------------ G: rules provider
async def test_rules_basic_commands():
    r = await rules.parse("ערוץ 12", "lg")
    assert (r.steps[0].target, r.steps[0].action, r.steps[0].params) == ("hot", "digits", {"digits": "12"})
    assert (await rules.parse("תגביר", "lg")).steps[0].target == "lg"
    assert (await rules.parse("תגביר", "hot")).steps[0].target == "hot"
    assert (await rules.parse("תעבור ל-HDMI 2", "lg")).steps[0].params == {"input": "HDMI_2"}
    assert (await rules.parse("פתח יוטיוב", "lg")).steps[0].params == {"app": "youtube"}


async def test_rules_sequence_and_unknown_parts():
    r = await rules.parse("שים ערוץ 12 ואז תנמיך", "lg")
    assert [s.action.value for s in r.steps] == ["digits", "volume_down"] and not r.unrecognized
    r = await rules.parse("השתק ואז ספר לי בדיחה", "lg")
    assert len(r.steps) == 1 and r.unrecognized == ["ספר לי בדיחה"]
    r = await rules.parse("מצא לי סרט מצחיק", "lg")
    assert not r.steps and r.unrecognized


@pytest.mark.parametrize("text,seconds", [("כבה את הטלוויזיה בעוד שעה", 3600), ("כבה את הטלוויזיה בעוד חצי שעה", 1800),
                                          ("בעוד 20 דקות כבה את הטלוויזיה", 1200), ("כבה את הטלוויזיה בעוד שעתיים", 7200),
                                          ("תנמיך בעוד 5 דקות", 300)])
async def test_rules_delays(text, seconds):
    r = await rules.parse(text, "lg")
    assert len(r.steps) == 1 and r.steps[0].delay_seconds == seconds and not r.unrecognized
    assert "בעוד" in r.steps[0].label


async def test_rules_conjunction_prefix():
    r = await rules.parse("ערוץ 12, ותנמיך, וכבה את הטלוויזיה בעוד שעה", "lg")
    assert [(s.action.value, s.delay_seconds) for s in r.steps] == [("digits", 0), ("volume_down", 0), ("power_off", 3600)]


async def test_rules_too_long_delay_is_rejected():
    r = await rules.parse("כבה את הטלוויזיה בעוד 99 שעות", "lg")
    assert not r.steps and r.unrecognized


# ------------------------------------------------------------------ H: LLM provider guardrails
class FakeAnthropic:
    def __init__(self, out=None, exc=None, stop="end_turn"):
        self.out, self.exc, self.stop, self.calls = out, exc, stop, []
        self.messages = SimpleNamespace(parse=self._parse)

    async def _parse(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return SimpleNamespace(parsed_output=self.out, stop_reason=self.stop)


def llm(client):
    return LLMIntentProvider("k", "claude-opus-5-5", rules, client=client)


async def test_llm_valid_output_becomes_validated_steps():
    fake = FakeAnthropic(LlmOut(steps=[LlmStep(target="hot", action="digits", digits="12"),
                                       LlmStep(target="lg", action="volume_down"),
                                       LlmStep(target="lg", action="power_off", delay_minutes=60)], unrecognized=[]))
    r = await llm(fake).parse("שים ערוץ 12 ואז תנמיך ובעוד שעה תכבה", "lg")
    assert r.provider == "llm" and [s.action.value for s in r.steps] == ["digits", "volume_down", "power_off"]
    assert r.steps[2].delay_seconds == 3600
    assert fake.calls[0]["model"] == "claude-opus-5-5" and fake.calls[0]["output_format"] is LlmOut


async def test_llm_cannot_smuggle_disallowed_commands():
    out = LlmOut(steps=[LlmStep(target="hot", action="key_press", key="POWER"),            # key not allowlisted
                        LlmStep(target="hot", action="power_off"),                          # LG-only action on HOT
                        LlmStep(target="lg", action="set_input", input="HDMI_9"),           # bad input
                        LlmStep(target="lg", action="launch_app", app="evil"),              # unknown app
                        LlmStep(target="hot", action="digits", digits="123456"),            # too long
                        LlmStep(target="lg", action="power_off", delay_minutes=99999)],     # beyond 12h
                 unrecognized=[])
    r = await llm(FakeAnthropic(out)).parse("whatever", "lg")
    assert r.steps == [] and len(r.unrecognized) == 6  # all shown to the user as not executed


async def test_llm_failures_fall_back_to_rules():
    for fake in (FakeAnthropic(exc=RuntimeError("down")), FakeAnthropic(None), FakeAnthropic(LlmOut(steps=[], unrecognized=[]), stop="refusal")):
        r = await llm(fake).parse("ערוץ 5", "lg")
        assert r.provider == "rules" and r.steps[0].params == {"digits": "5"}


async def test_llm_call_budget_falls_back():
    p = llm(FakeAnthropic(LlmOut(steps=[LlmStep(target="lg", action="mute")], unrecognized=[])))
    p.MAX_PER_WINDOW = 2
    assert [(await p.parse("השתק", "lg")).provider for _ in range(3)] == ["llm", "llm", "rules"]


def test_provider_selection_without_key_is_rules():
    assert build_provider("", "m").name == "rules"
    assert build_provider("sk-test", "m").name == "llm"


# ------------------------------------------------------------------ API + scheduler
def test_parse_endpoint_and_capabilities(client):
    r = client.post("/api/intents/parse", json={"text": "ערוץ 12 ואז תגביר"}, headers=H).json()
    assert r["provider"] == "rules" and [s["action"] for s in r["steps"]] == ["digits", "volume_up"]
    assert client.get("/api/capabilities", headers=H).json()["intent_provider"] == "rules"
    assert client.post("/api/intents/parse", json={"text": ""}, headers=H).status_code == 422
    assert client.post("/api/intents/parse", json={"text": "x" * 301}, headers=H).status_code == 422
    assert client.post("/api/intents/parse", json={"text": "ערוץ 1"}).status_code == 401


def test_schedule_create_list_cancel(client):
    body = {"target": "lg", "action": "power_off", "params": {}, "delay_seconds": 3600, "label": "כיבוי LG"}
    s = client.post("/api/schedule", json=body, headers=H).json()
    assert s["status"] == "pending" and s["run_at"] > time.time() + 3000
    assert [x["id"] for x in client.get("/api/schedule", headers=H).json()] == [s["id"]]
    assert client.delete(f"/api/schedule/{s['id']}", headers=H).json()["status"] == "cancelled"
    assert client.delete(f"/api/schedule/{s['id']}", headers=H).status_code == 404  # already cancelled


@pytest.mark.parametrize("bad", [
    {"target": "lg", "action": "power_off", "delay_seconds": 0},
    {"target": "lg", "action": "power_off", "delay_seconds": 12 * 3600 + 1},
    {"target": "hot", "action": "power_off", "delay_seconds": 60},
    {"target": "lg", "action": "key_press", "params": {"key": "KEYCODE_1"}, "delay_seconds": 60},
])
def test_schedule_validation(client, bad):
    assert client.post("/api/schedule", json=bad, headers=H).status_code == 422


def test_schedule_pending_cap(client):
    body = {"target": "lg", "action": "mute", "delay_seconds": 600}
    codes = [client.post("/api/schedule", json=body, headers=H).status_code for _ in range(22)]
    assert codes.count(201) == 20 and codes[-1] == 429


async def test_scheduler_runs_due_skips_cancelled_and_marks_missed():
    app = create_app(Settings(access_token=TOKEN, db_path=":memory:", use_mock_adapters=True))
    mgr, store, sch = app.state.manager, app.state.schedules, app.state.scheduler
    row = mgr.add("lg", "192.168.1.40")
    await mgr.pair_confirm(row.id, "")
    now = time.time()
    mk = lambda action, delay=1, **p: store.add(ScheduleCreate(target="lg", action=action, params=p, delay_seconds=delay, label=""), now)
    due, cancelled, old = mk("mute"), mk("volume_up"), mk("volume_down")
    store.set_status(cancelled.id, "cancelled", only_if="pending")
    await sch.tick(now + 0.5)  # nothing due yet
    assert store.get(due.id).status == "pending"
    await sch.tick(now + 2)
    assert store.get(due.id).status == "done" and store.get(cancelled.id).status == "cancelled"
    await sch.tick(now + 2)  # a second tick must not re-run anything
    sent_actions = [a for a, _ in mgr.adapters[row.id].sent]
    assert sent_actions.count("mute") == 1 and "volume_up" not in sent_actions
    # server was down past the grace window -> missed, not fired late
    late = mk("mute", delay=1)
    await sch.tick(now + 10_000)
    assert store.get(late.id).status == "missed"
    assert store.get(old.id).status == "done"  # was due at the same tick as `due`


async def test_scheduler_failure_is_recorded_not_hidden():
    app = create_app(Settings(access_token=TOKEN, db_path=":memory:", use_mock_adapters=True))
    store, sch = app.state.schedules, app.state.scheduler
    now = time.time()
    s = store.add(ScheduleCreate(target="lg", action="mute", params={}, delay_seconds=1, label=""), now)
    await sch.tick(now + 2)  # no LG device exists
    got = store.get(s.id)
    assert got.status == "failed" and got.error
    await asyncio.sleep(0)


# ------------------------------------------------------------------ emulated channel +/- and "last" (box ignores CHANNEL keys)
def send(client, did, action, rid, **params):
    body = {"target": did, "action": action, "request_id": rid, "params": {"delay_ms": 50, **params}}
    return client.post(f"/api/devices/{did}/commands", json=body, headers=H)


def keys(client, did):
    return [p["key"] for _, p in client.app.state.manager.adapters[did].sent]


def chan(client, did):
    return next(d for d in client.get("/api/devices", headers=H).json() if d["id"] == did)


def test_step_up_down_uses_the_channel_we_last_typed(client):
    did = paired(client, "hot")
    assert send(client, did, "digits", "req-ch-0001", digits="11").status_code == 200
    assert chan(client, did)["channel"] == "11"
    assert send(client, did, "channel_step", "req-ch-0002", delta=1).status_code == 200
    assert keys(client, did)[-2:] == ["KEYCODE_1", "KEYCODE_2"]  # 12
    assert chan(client, did)["channel"] == "12" and chan(client, did)["previous_channel"] == "11"
    send(client, did, "channel_step", "req-ch-0003", delta=-1)
    send(client, did, "channel_step", "req-ch-0004", delta=-1)
    assert keys(client, did)[-2:] == ["KEYCODE_1", "KEYCODE_0"] and chan(client, did)["channel"] == "10"


def test_last_channel_toggles(client):
    did = paired(client, "hot")
    send(client, did, "digits", "req-ch-0010", digits="12")
    send(client, did, "digits", "req-ch-0011", digits="5")
    assert send(client, did, "channel_last", "req-ch-0012").status_code == 200
    assert keys(client, did)[-2:] == ["KEYCODE_1", "KEYCODE_2"] and chan(client, did)["channel"] == "12"
    send(client, did, "channel_last", "req-ch-0013")
    assert chan(client, did)["channel"] == "5"


def test_unknown_current_channel_is_an_explicit_error_not_a_guess(client):
    did = paired(client, "hot")
    r = send(client, did, "channel_step", "req-ch-0020", delta=1)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "UNSUPPORTED"
    assert client.app.state.manager.adapters[did].sent == []  # nothing was typed
    assert send(client, did, "channel_last", "req-ch-0021").status_code == 409


def test_manual_set_channel_sends_nothing(client):
    did = paired(client, "hot")
    r = client.post(f"/api/devices/{did}/channel", json={"channel": "007"}, headers=H)
    assert r.status_code == 200 and r.json()["channel"] == "7"
    assert client.app.state.manager.adapters[did].sent == []
    assert send(client, did, "channel_step", "req-ch-0030", delta=1).status_code == 200
    assert keys(client, did) == ["KEYCODE_8"]
    assert client.post(f"/api/devices/{did}/channel", json={"channel": "12a"}, headers=H).status_code == 422


def test_step_bounds_and_validation(client):
    did = paired(client, "hot")
    client.post(f"/api/devices/{did}/channel", json={"channel": "1"}, headers=H)
    assert send(client, did, "channel_step", "req-ch-0040", delta=-1).status_code == 422  # would be 0
    assert send(client, did, "channel_step", "req-ch-0041", delta=2).status_code == 422
    assert send(client, did, "channel_step", "req-ch-0042").status_code == 422


def test_failed_sequence_does_not_update_tracked_channel(client):
    from app.adapters.base import AdapterError
    from app.models.schemas import ErrorCode
    did = paired(client, "hot")
    send(client, did, "digits", "req-ch-0050", digits="20")
    ad = client.app.state.manager.adapters[did]

    async def boom(action, params):
        raise AdapterError(ErrorCode.NOT_CONNECTED, "נפל")

    ad.execute = boom
    assert send(client, did, "channel_step", "req-ch-0051", delta=1).status_code == 409
    assert chan(client, did)["channel"] == "20"  # unchanged: we never finished typing 21


def test_channel_actions_rejected_on_lg(client):
    did = paired(client, "lg")
    assert send(client, did, "channel_step", "req-ch-0060", delta=1).json()["detail"]["code"] == "UNSUPPORTED"


async def test_rules_open_apps_on_either_device():
    for text, app, target in [("פתח נטפליקס", "netflix", "lg"), ("פתח ספוטיפיי", "spotify", "lg"),
                              ("פתח נטפליקס בממיר", "netflix", "hot"), ("תפתח ספוטיפי על הממיר", "spotify", "hot"),
                              ("הפעל יוטיוב בטלוויזיה", "youtube", "lg")]:
        r = await rules.parse(text, "lg")
        assert [(s.target, s.params) for s in r.steps] == [(target, {"app": app})], text


def test_launch_app_allowed_on_hot_but_unknown_apps_rejected(client):
    did = paired(client, "hot")
    ok = {"target": did, "action": "launch_app", "request_id": "req-app-0001", "params": {"app": "netflix"}}
    assert client.post(f"/api/devices/{did}/commands", json=ok, headers=H).status_code == 200
    bad = {**ok, "request_id": "req-app-0002", "params": {"app": "https://evil.example"}}
    assert client.post(f"/api/devices/{did}/commands", json=bad, headers=H).status_code == 422


# ------------------------------------------------------------------ roles, rename, remove, pointer
def add(client, kind, host, **extra):
    return client.post("/api/devices", json={"kind": kind, "host": host, **extra}, headers=H)


def test_role_defaults_follow_the_driver_and_can_be_chosen(client):
    a = add(client, "lg", "192.168.1.70").json()
    b = add(client, "hot", "192.168.1.71").json()
    c = add(client, "hot", "192.168.1.72", role="tv", name="  טלוויזיית חדר ילדים ").json()  # Android TV used as a TV
    assert (a["role"], b["role"], c["role"]) == ("tv", "box", "tv") and c["name"] == "טלוויזיית חדר ילדים"
    assert add(client, "lg", "192.168.1.73", role="fridge").status_code == 422


def test_rename_and_change_role(client):
    d = add(client, "hot", "192.168.1.74").json()
    r = client.patch(f"/api/devices/{d['id']}", json={"name": "ממיר סלון", "role": "tv"}, headers=H).json()
    assert (r["name"], r["role"]) == ("ממיר סלון", "tv")
    r = client.patch(f"/api/devices/{d['id']}", json={"name": "חדש"}, headers=H).json()
    assert (r["name"], r["role"]) == ("חדש", "tv")  # role untouched when omitted
    assert client.patch(f"/api/devices/{d['id']}", json={"name": ""}, headers=H).status_code == 422
    assert client.patch("/api/devices/nope", json={"name": "x"}, headers=H).status_code == 404


def test_remove_device_deletes_it_and_its_credentials(client, tmp_path):
    mgr = client.app.state.manager
    mgr.cert_dir = tmp_path / "certs"
    mgr.cert_dir.mkdir()
    (tmp_path / "lg_keys").mkdir()
    d = add(client, "lg", "192.168.1.75").json()
    (mgr.cert_dir / f"{d['id']}.cert.pem").write_text("x")
    (tmp_path / "lg_keys" / f"{d['id']}.lgkey").write_text("secret")
    assert client.delete(f"/api/devices/{d['id']}", headers=H).status_code == 204
    assert client.get("/api/devices", headers=H).json() == []
    assert not list(mgr.cert_dir.glob("*")) and not list((tmp_path / "lg_keys").glob("*"))
    assert client.delete(f"/api/devices/{d['id']}", headers=H).status_code == 404


def test_pointer_events_reach_a_paired_tv(client):
    did = paired(client, "lg")
    r = client.post(f"/api/devices/{did}/pointer", json={"dx": 12, "dy": -7, "scroll_dy": 2, "click": True}, headers=H)
    assert r.status_code == 204
    assert client.app.state.manager.adapters[did].pointer_events == [(12, -7, 2, True)]


def test_pointer_is_bounded_and_not_available_on_android_tv(client):
    tv, box = paired(client, "lg"), paired(client, "hot")
    for bad in ({"dx": 500}, {"dy": -201}, {"scroll_dy": 99}, {"dx": "a"}, {"evil": 1}):
        assert client.post(f"/api/devices/{tv}/pointer", json=bad, headers=H).status_code == 422
    r = client.post(f"/api/devices/{box}/pointer", json={"dx": 5}, headers=H)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "UNSUPPORTED"
    assert client.post(f"/api/devices/{tv}/pointer", json={"dx": 1}).status_code == 401


def test_pointer_has_its_own_higher_rate_limit(client):
    did = paired(client, "lg")
    codes = [client.post(f"/api/devices/{did}/pointer", json={"dx": 1}, headers=H).status_code for _ in range(110)]
    assert codes[:100] == [204] * 100 and 429 in codes
    # ... and it does not eat the normal command budget
    body = {"target": did, "action": "mute", "request_id": "req-ptr-0001", "params": {}}
    assert client.post(f"/api/devices/{did}/commands", json=body, headers=H).status_code == 200


def test_old_database_without_role_column_is_migrated(tmp_path):
    import sqlite3
    from app.storage.db import Store
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE devices (id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, host TEXT, UNIQUE(kind, host))")
    db.execute("INSERT INTO devices VALUES ('a1','lg','LG webOS','192.168.1.60')")
    db.commit(); db.close()
    s = Store(path)
    rows = s.list()
    assert [(r.id, r.kind, r.role) for r in rows] == [("a1", "lg", None)]  # None -> derived at read time
    assert s.update("a1", None, "box") and s.list()[0].role == "box"



# ------------------------------------------------------------------ clearing schedule history (single, multi-select, tidy-up)
def make_schedule(client, delay=3600):
    return client.post("/api/schedule", json={"target": "lg", "action": "mute", "delay_seconds": delay}, headers=H).json()["id"]


def clear(client, **body):
    return client.post("/api/schedule/clear", json=body, headers=H)


def test_clear_selected_ids_only(client):
    a, b, c = make_schedule(client), make_schedule(client), make_schedule(client)
    assert clear(client, ids=[a, c]).json() == {"removed": 2}
    assert [s["id"] for s in client.get("/api/schedule", headers=H).json()] == [b]


def test_tidy_up_keeps_pending_and_removes_finished(client):
    pending, done1, done2 = make_schedule(client), make_schedule(client), make_schedule(client)
    store = client.app.state.schedules
    store.set_status(done1, "done"); store.set_status(done2, "cancelled")
    assert clear(client).json() == {"removed": 2}
    assert [s["id"] for s in client.get("/api/schedule", headers=H).json()] == [pending]


def test_deleting_a_pending_schedule_cancels_it_for_good(client):
    import asyncio
    sid = make_schedule(client, delay=1)
    assert clear(client, ids=[sid]).json() == {"removed": 1}
    mgr = client.app.state.manager
    row = mgr.add("lg", "192.168.1.90")
    asyncio.run(mgr.pair_confirm(row.id, ""))
    asyncio.run(client.app.state.scheduler.tick(time.time() + 5))  # it is overdue, but gone
    assert mgr.adapters[row.id].sent == []


def test_clear_validation_and_auth(client):
    assert clear(client, ids=["x"] * 51).status_code == 422
    assert clear(client, ids=[]).json() == {"removed": 0}
    assert clear(client, ids=["nope"]).json() == {"removed": 0}
    assert client.post("/api/schedule/clear", json={}).status_code == 401
    assert clear(client, evil=1).status_code == 422


def test_selftest_endpoint(client):
    did = paired(client, "hot")
    r = client.post(f"/api/devices/{did}/selftest", headers=H)
    assert r.status_code == 200 and r.json()["ok"] is True
    client.app.state.manager.adapters[did].selftest_ok = False
    assert client.post(f"/api/devices/{did}/selftest", headers=H).json()["ok"] is False
    assert client.post("/api/devices/nope/selftest", headers=H).status_code == 404
    assert client.post(f"/api/devices/{did}/selftest").status_code == 401
    unpaired = client.post("/api/devices", json={"kind": "lg", "host": "192.168.1.98"}, headers=H).json()["id"]
    assert client.post(f"/api/devices/{unpaired}/selftest", headers=H).json()["detail"]["code"] == "NOT_PAIRED"



# ------------------------------------------------------------------ devices that change address (DHCP)
class LostStub:
    """A paired device that cannot be reached."""
    kind = "lg"
    paired = True
    connection = "disconnected"
    capabilities: dict = {}
    last_error = None

    def __init__(self): self.closed = False
    async def close(self): self.closed = True
    async def start(self): pass


def lost_manager(kind="lg", host="192.168.1.60"):
    client = TestClient(create_app(Settings(access_token=TOKEN, db_path=":memory:", use_mock_adapters=True)))
    mgr = client.app.state.manager
    d = mgr.add(kind, host)
    stub = LostStub(); stub.kind = kind
    mgr.adapters[d.id] = stub
    return client, mgr, d, stub


async def test_lost_device_moves_to_its_new_address_after_a_grace_period():
    client, mgr, d, stub = lost_manager()
    seen = []
    mgr.notify = lambda e, det: seen.append((e, det))

    async def found(): return ["192.168.1.61"]
    mgr.find_lg = found
    assert await mgr.relocate_once(now=0) == []            # just noticed it is lost: wait
    assert await mgr.relocate_once(now=30) == []           # still within the grace period
    assert await mgr.relocate_once(now=100) == [d.id]      # lost long enough: found at a new address
    assert mgr._row(d.id).host == "192.168.1.61" and stub.closed  # old connection dropped, new one built
    assert seen and seen[0][0] == "device_moved" and "192.168.1.60" in seen[0][1] and "192.168.1.61" in seen[0][1]


async def test_relocation_is_conservative():
    # nothing found / the same address / several candidates -> never guess
    for found_hosts in ([], ["192.168.1.60"], ["192.168.1.61", "192.168.1.62"]):
        client, mgr, d, _ = lost_manager()

        async def found(h=found_hosts): return h
        mgr.find_lg = found
        await mgr.relocate_once(now=0)
        assert await mgr.relocate_once(now=100) == []
        assert mgr._row(d.id).host == "192.168.1.60"


async def test_relocation_skips_when_there_are_two_devices_of_the_kind():
    client, mgr, d, _ = lost_manager()
    mgr.add("lg", "192.168.1.70")                          # a second TV: ambiguous, so never auto-move

    async def found(): return ["192.168.1.61"]
    mgr.find_lg = found
    await mgr.relocate_once(now=0)
    assert await mgr.relocate_once(now=100) == []


async def test_connected_device_is_never_scanned_for():
    client, mgr, d, stub = lost_manager()
    stub.connection = "connected"
    calls = []

    async def found(): calls.append(1); return ["192.168.1.61"]
    mgr.find_lg = found
    await mgr.relocate_once(now=0)
    assert await mgr.relocate_once(now=1000) == [] and calls == []


def test_edit_device_address_validates_and_rebuilds(client):
    d = client.post("/api/devices", json={"kind": "lg", "host": "192.168.1.80"}, headers=H).json()
    first = client.app.state.manager.adapters[d["id"]]
    r = client.patch(f"/api/devices/{d['id']}", json={"host": "192.168.1.81"}, headers=H)
    assert r.status_code == 200 and r.json()["host"] == "192.168.1.81"
    assert client.app.state.manager.adapters[d["id"]] is not first      # a fresh adapter for the new address
    for bad in ("8.8.8.8", "127.0.0.1", "nope", "192.168.1"):
        assert client.patch(f"/api/devices/{d['id']}", json={"host": bad}, headers=H).status_code == 422
    other = client.post("/api/devices", json={"kind": "lg", "host": "192.168.1.82"}, headers=H).json()
    assert client.patch(f"/api/devices/{other['id']}", json={"host": "192.168.1.81"}, headers=H).status_code == 409  # taken
