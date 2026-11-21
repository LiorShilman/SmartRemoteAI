"""LG sound status in the device list: read from the TV's pushed state only, never a request."""
import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.adapters.lg_webos import LgWebOsAdapter
from app.config import Settings
from app.main import create_app
from tests.test_lg_webos import FakeTv, make, pair

TOKEN = "t" * 32
H = {"Authorization": f"Bearer {TOKEN}"}


class StateTv(FakeTv):
    """FakeTv plus aiowebostv's tv_state; any request would land in .calls."""
    def __init__(self, host, key):
        super().__init__(host, key)
        self.tv_state = SimpleNamespace(sound_output=None, volume=None, muted=None)


async def connected(tmp_path, **state):
    a = make(tmp_path, StateTv)
    await pair(a)
    for k, v in state.items():
        setattr(StateTv.last.tv_state, k, v)
    return a


async def test_unpaired_tv_has_no_audio(tmp_path):
    assert make(tmp_path, StateTv).audio_status() is None


async def test_paired_but_disconnected_is_offline(tmp_path):
    a = await connected(tmp_path, sound_output="tv_speaker", volume=12, muted=False)
    StateTv.last.connected = False  # dropped: the last values may be stale, so none are shown
    s = a.audio_status()
    assert s.state == "offline" and s.output is None and s.tv_volume is None and s.tv_muted is None


async def test_connected_before_first_update_is_pending(tmp_path):
    s = (await connected(tmp_path)).audio_status()
    assert s.state == "pending" and s.output is None and s.tv_volume is None


async def test_tv_speakers(tmp_path):
    s = (await connected(tmp_path, sound_output="tv_speaker", volume=12, muted=False)).audio_status()
    assert s.model_dump() == {"state": "ready", "output": "tv_speaker", "output_kind": "tv_speaker",
                              "output_label": "רמקולי הטלוויזיה", "tv_volume": 12, "tv_muted": False}


async def test_bluetooth_is_just_bluetooth_not_the_zeppelin(tmp_path):
    s = (await connected(tmp_path, sound_output="bt_soundbar", volume=None, muted=False)).audio_status()
    assert s.state == "ready" and s.output_kind == "bluetooth" and s.output == "bt_soundbar"
    assert s.tv_volume is None  # no volume pushed for this output: unknown, not 0
    assert "zeppelin" not in s.model_dump_json().lower()


async def test_unknown_output_is_not_guessed(tmp_path):
    s = (await connected(tmp_path, sound_output="tv_speaker_bluetooth", volume=7, muted=True)).audio_status()
    assert s.output_kind == "other" and s.output_label == "tv_speaker_bluetooth" and s.tv_muted is True


async def test_bad_values_are_dropped(tmp_path):
    s = (await connected(tmp_path, sound_output="", volume=True, muted="no")).audio_status()
    assert s.state == "pending"


async def test_reading_sends_nothing_to_the_tv(tmp_path):
    a = await connected(tmp_path, sound_output="tv_speaker", volume=5, muted=False)
    for _ in range(5):
        a.audio_status()
    assert StateTv.last.calls == []


async def test_reconnect_shows_fresh_values(tmp_path):
    a = await connected(tmp_path, sound_output="tv_speaker", volume=12, muted=False)
    tv = StateTv.last
    tv.connected = False
    tv.tv_state = SimpleNamespace(sound_output=None, volume=None, muted=None)  # aiowebostv clears on close
    assert a.audio_status().state == "offline"
    tv.connected = True
    assert a.audio_status().state == "pending"
    tv.tv_state.sound_output, tv.tv_state.volume = "bt_soundbar", 3
    s = a.audio_status()
    assert s.state == "ready" and s.output_kind == "bluetooth" and s.tv_volume == 3


async def test_device_list_carries_audio_for_lg_only(tmp_path):
    client = TestClient(create_app(Settings(access_token=TOKEN, db_path=":memory:", use_mock_adapters=True)))
    mgr = client.app.state.manager
    lg = mgr.add("lg", "192.168.1.65")
    hot = mgr.add("hot", "192.168.1.53")
    a = LgWebOsAdapter(lg.id, lg.host, tmp_path, StateTv)
    await pair(a)
    StateTv.last.tv_state.sound_output, StateTv.last.tv_state.volume, StateTv.last.tv_state.muted = "bt_soundbar", 9, False
    mgr.adapters[lg.id] = a
    rows = {d["id"]: d for d in client.get("/api/devices", headers=H).json()}
    assert rows[lg.id]["audio"] == {"state": "ready", "output": "bt_soundbar", "output_kind": "bluetooth",
                                    "output_label": "סאונדבר בבלוטות'", "tv_volume": 9, "tv_muted": False}
    assert rows[hot.id]["audio"] is None
    # existing fields unchanged
    assert {"connection", "capabilities", "last_error", "channel"} <= rows[lg.id].keys()
    await a.close()
