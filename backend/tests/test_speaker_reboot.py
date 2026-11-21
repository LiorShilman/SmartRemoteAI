"""Speaker restart: one fixed action, success only when the speaker really went down and came back. No real speaker."""
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services import zeppelin
from app.services.zeppelin import ZeppelinClient
from tests.test_speaker_voice import KID_POLICY
from tests.test_zeppelin import FakeSpeaker, H, MASTER


class RebootSpeaker(FakeSpeaker):
    """down_for: how many requests it ignores after the action (it is restarting); None = never comes back."""

    def __init__(self):
        super().__init__()
        self.values["settings:/ui/disabledReboot"] = {"bool_": False, "type": "bool_"}
        self.actions: list[dict] = []
        self.restarts = True      # False: it accepts the action and keeps running (no restart)
        self.refuse = False       # HTTP 200 with an error object
        self.drop = False         # closes the connection on the action itself (going down at once)
        self.down_for: int | None = 3
        self._down_left: int | None = 0

    def handler(self, request):
        if request.url.path == "/api/setData" and request.method == "POST":
            self.requests.append(request)
            body = json.loads(request.content)
            self.actions.append(body)
            if self.refuse:
                return httpx.Response(200, json={"error": {"message": "Not allowed", "name": "Error"}})
            if self.restarts:
                self._down_left = self.down_for
            if self.drop:
                raise httpx.RemoteProtocolError("connection closed", request=request)
            return httpx.Response(200, json={})
        if self._down_left is None or self._down_left > 0:
            self.requests.append(request)
            if self._down_left is not None:
                self._down_left -= 1
            raise httpx.ConnectError("no route to host", request=request)
        return super().handler(request)


@pytest.fixture
def sp():
    return RebootSpeaker()


@pytest.fixture
def client(sp, monkeypatch):
    monkeypatch.setattr(zeppelin, "REBOOT_POLL_S", 0.01)
    monkeypatch.setattr(zeppelin, "REBOOT_BACK_POLL_S", 0.01)
    monkeypatch.setattr(zeppelin, "REBOOT_DOWN_S", 0.2)
    monkeypatch.setattr(zeppelin, "REBOOT_BACK_S", 0.3)
    app = create_app(Settings(access_token=MASTER, db_path=":memory:", use_mock_adapters=True))
    app.state.speaker = ZeppelinClient("192.168.1.52", transport=httpx.MockTransport(sp.handler))
    with TestClient(app) as c:
        yield c


def wait_phase(client, until=("back", "timeout"), limit=3.0):
    end = time.monotonic() + limit
    while time.monotonic() < end:
        st = client.get("/api/speaker/reboot", headers=H).json()
        if st["phase"] in until:
            return st
        time.sleep(0.02)
    return st


def test_status_is_idle_and_reading_sends_nothing(client, sp):
    assert client.get("/api/speaker/reboot", headers=H).json() == {"phase": "idle", "seconds": None}
    assert sp.actions == [] and sp.requests == []


def test_restart_sends_the_one_action_and_reports_back_only_after_the_speaker_answers(client, sp):
    r = client.post("/api/speaker/reboot", headers=H)
    assert r.status_code == 200 and r.json()["phase"] == "restarting"
    assert sp.actions == [{"path": "powermanager:goReboot", "role": "activate", "value": {}}]
    assert wait_phase(client)["phase"] == "back"
    audit = json.dumps(client.get("/api/audit", headers=H).json(), ensure_ascii=False)
    assert "הרמקול הופעל מחדש" in audit and "חזר לפעול" in audit


def test_speaker_dropping_the_connection_on_the_action_still_counts_once_it_goes_down(client, sp):
    sp.drop = True
    assert client.post("/api/speaker/reboot", headers=H).json()["phase"] == "restarting"
    assert wait_phase(client)["phase"] == "back"


def test_no_false_success_when_it_keeps_running(client, sp):
    sp.restarts = False
    r = client.post("/api/speaker/reboot", headers=H)
    assert r.status_code == 502 and "לא הופעל מחדש" in r.json()["detail"]["message"]
    assert client.get("/api/speaker/reboot", headers=H).json()["phase"] == "idle"


def test_error_inside_http_200_is_a_failure(client, sp):
    sp.refuse = True
    r = client.post("/api/speaker/reboot", headers=H)
    assert r.status_code == 502 and "Not allowed" in r.json()["detail"]["message"]


def test_disabled_by_the_speaker_sends_nothing(client, sp):
    sp.values["settings:/ui/disabledReboot"] = {"bool_": True, "type": "bool_"}
    assert client.post("/api/speaker/reboot", headers=H).status_code == 409
    assert sp.actions == []


def test_unreachable_speaker_is_not_restarted(client, sp):
    sp.unreachable = True
    assert client.post("/api/speaker/reboot", headers=H).status_code == 503
    assert sp.actions == []


def test_never_coming_back_is_reported_as_timeout(client, sp):
    sp.down_for = None
    assert client.post("/api/speaker/reboot", headers=H).status_code == 200
    assert wait_phase(client)["phase"] == "timeout"


def test_writes_and_a_second_restart_are_refused_meanwhile(client, sp):
    sp.down_for = None
    client.post("/api/speaker/reboot", headers=H)
    r = client.post("/api/speaker/volume", json={"value": 20}, headers=H)
    assert r.status_code == 409 and "הפעלה מחדש" in r.json()["detail"]["message"]
    assert client.post("/api/speaker/reboot", headers=H).status_code == 409
    assert len(sp.actions) == 1


def test_requires_auth_and_is_denied_to_kids_codes(client, sp):
    assert client.post("/api/speaker/reboot").status_code == 401
    assert client.get("/api/speaker/reboot").status_code == 401
    t = client.post("/api/tokens", json={"name": "kid", "policy": KID_POLICY}, headers=H).json()["token"]
    assert client.post("/api/speaker/reboot", headers={"Authorization": f"Bearer {t}"}).status_code == 403
    assert sp.actions == []
