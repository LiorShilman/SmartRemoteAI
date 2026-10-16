"""LgWebOsAdapter against a fake client (no network, no TV)."""
import asyncio

import pytest
from aiowebostv import WebOsTvCommandError, WebOsTvPairError

from app.adapters import lg_webos
from app.adapters.base import AdapterError
from app.adapters.lg_webos import LgWebOsAdapter
from app.models.schemas import ErrorCode


class FakeTv:
    def __init__(self, host, key):
        self.host, self.client_key = host, key
        self.connected = False
        self.calls: list[tuple] = []
        self.approve_after = 0  # connect() attempts that time out before the user approves
        self.muted: bool | None = False
        self.inputs = [{"id": "HDMI_1"}, {"id": "HDMI_2"}]
        self.cmd_exc: Exception | None = None
        FakeTv.last = self

    async def connect(self):
        if self.client_key is None:
            if self.approve_after > 0:
                self.approve_after -= 1
                raise TimeoutError
            self.client_key = "KEY123"
        self.connected = True
        return True

    def is_connected(self):
        return self.connected

    async def disconnect(self):
        self.connected = False

    async def _rec(self, *a):
        if self.cmd_exc:
            raise self.cmd_exc
        self.calls.append(a)

    async def button(self, n): await self._rec("button", n)
    async def volume_up(self): await self._rec("volume_up")
    async def volume_down(self): await self._rec("volume_down")
    async def power_off(self): await self._rec("power_off")
    async def get_muted(self): return self.muted
    async def set_mute(self, m): await self._rec("set_mute", m)
    async def get_inputs(self): return self.inputs
    async def set_input(self, i): await self._rec("set_input", i)
    async def launch_app(self, a): await self._rec("launch_app", a)


def make(tmp_path, factory=FakeTv, device_id="lg1"):
    return LgWebOsAdapter(device_id, "192.168.1.60", tmp_path, factory)


async def pair(a):
    await a.pair_start()
    await a.pair_confirm("")


async def test_unpaired_refuses(tmp_path):
    a = make(tmp_path)
    assert a.connection == "unpaired"
    with pytest.raises(AdapterError) as e:
        await a.execute("volume_up", {})
    assert e.value.code is ErrorCode.NOT_PAIRED


async def test_pairing_saves_key_and_connects(tmp_path):
    a = make(tmp_path)
    await pair(a)
    assert a.connection == "connected"
    assert (tmp_path / "lg1.lgkey").read_text() == "KEY123"
    await a.close()


async def test_prompt_is_retried_until_approved(tmp_path):
    def factory(h, k):
        tv = FakeTv(h, k)
        tv.approve_after = 2
        return tv

    a = make(tmp_path, factory)
    await pair(a)
    assert a.connection == "connected"
    await a.close()


async def test_rejected_pairing_is_denied(tmp_path):
    class Rejecting(FakeTv):
        async def connect(self):
            raise WebOsTvPairError("denied")

    a = make(tmp_path, Rejecting)
    await a.pair_start()
    with pytest.raises(AdapterError) as e:
        await a.pair_confirm("")
    assert e.value.code is ErrorCode.DENIED and a.connection == "unpaired"


async def test_pending_approval_times_out_politely(tmp_path, monkeypatch):
    monkeypatch.setattr(lg_webos, "PAIR_WAIT_S", 0.1)

    class Slow(FakeTv):
        async def connect(self):
            await asyncio.sleep(5)

    a = make(tmp_path, Slow)
    await a.pair_start()
    with pytest.raises(AdapterError) as e:
        await a.pair_confirm("")
    assert e.value.code is ErrorCode.TIMEOUT
    await a.close()


async def test_unreachable_tv(tmp_path):
    class Down(FakeTv):
        async def connect(self):
            raise OSError("no route")

    a = make(tmp_path, Down)
    await a.pair_start()
    with pytest.raises(AdapterError) as e:
        await a.pair_confirm("")
    assert e.value.code is ErrorCode.DENIED and a.connection == "unpaired" and a.last_error


async def test_commands_map_to_webos(tmp_path):
    a = make(tmp_path)
    await pair(a)
    tv = FakeTv.last
    await a.execute("key_press", {"key": "DPAD_CENTER"})
    await a.execute("volume_up", {})
    await a.execute("mute", {})
    await a.execute("set_input", {"input": "HDMI_2"})
    await a.execute("launch_app", {"app": "youtube"})
    await a.execute("power_off", {})
    assert tv.calls == [("button", "ENTER"), ("volume_up",), ("set_mute", True), ("set_input", "HDMI_2"),
                        ("launch_app", "youtube.leanback.v4"), ("power_off",)]
    await a.close()


async def test_unlisted_input_is_unsupported_not_sent(tmp_path):
    a = make(tmp_path)
    await pair(a)
    with pytest.raises(AdapterError) as e:
        await a.execute("set_input", {"input": "HDMI_4"})
    assert e.value.code is ErrorCode.UNSUPPORTED and FakeTv.last.calls == []
    await a.close()


async def test_power_on_not_faked(tmp_path):
    a = make(tmp_path)
    await pair(a)
    with pytest.raises(AdapterError) as e:
        await a.execute("power_on", {})
    assert e.value.code is ErrorCode.UNSUPPORTED
    assert a.capabilities["wol"] == "unsupported"
    await a.close()


async def test_tv_error_not_reported_as_success(tmp_path):
    a = make(tmp_path)
    await pair(a)
    FakeTv.last.cmd_exc = WebOsTvCommandError("nope")
    with pytest.raises(AdapterError) as e:
        await a.execute("volume_down", {})
    assert e.value.code is ErrorCode.DENIED
    await a.close()


async def test_restart_reconnects_with_saved_key(tmp_path):
    a1 = make(tmp_path, device_id="lg5")
    await pair(a1)
    await a1.close()
    a2 = make(tmp_path, device_id="lg5")
    assert a2.connection == "disconnected"
    await a2.start()
    await asyncio.sleep(0.05)
    assert a2.connection == "connected" and FakeTv.last.client_key == "KEY123"
    await a2.close()


async def test_revoked_key_unpairs(tmp_path):
    a1 = make(tmp_path, device_id="lg6")
    await pair(a1)
    await a1.close()

    class Revoked(FakeTv):
        async def connect(self):
            raise WebOsTvPairError("revoked")

    a2 = make(tmp_path, Revoked, device_id="lg6")
    await a2.start()
    await asyncio.sleep(0.05)
    assert a2.connection == "unpaired" and not (tmp_path / "lg6.lgkey").exists()
    await a2.close()


def test_diagnostics_has_no_secrets(tmp_path):
    d = make(tmp_path).diagnostics()
    assert not any(k in d for k in ("key", "client_key", "token"))


async def test_volume_rejected_for_external_sound_output_explains_why(tmp_path):
    from aiowebostv.exceptions import WebOsTvResponseTypeError

    class Optical(FakeTv):
        async def volume_up(self):
            raise WebOsTvResponseTypeError("19 Invalid volumeUp Parameters requested")

        async def get_sound_output(self):
            return "external_optical"

    a = make(tmp_path, Optical)
    await pair(a)
    with pytest.raises(AdapterError) as e:
        await a.execute("volume_up", {})
    assert e.value.code is ErrorCode.UNSUPPORTED
    assert "אופטי" in e.value.message and "יציאת קול" in e.value.message
    assert a.diagnostics()["audio_blocked_output"] == "external_optical"
    await a.execute("key_press", {"key": "HOME"})  # non-audio commands are unaffected
    await a.close()


async def test_command_timeout_maps_to_timeout(tmp_path):
    from aiowebostv.exceptions import WebOsTvCommandTimeoutError

    class Slow(FakeTv):
        async def power_off(self):
            raise WebOsTvCommandTimeoutError("t")

    a = make(tmp_path, Slow)
    await pair(a)
    with pytest.raises(AdapterError) as e:
        await a.execute("power_off", {})
    assert e.value.code is ErrorCode.TIMEOUT
    await a.close()


async def test_spotify_uses_its_webos_app_id(tmp_path):
    a = make(tmp_path)
    await pair(a)
    await a.execute("launch_app", {"app": "spotify"})
    assert FakeTv.last.calls[-1] == ("launch_app", "spotify-beehive")
    await a.close()


async def test_menu_style_keys_map_to_webos_buttons(tmp_path):
    a = make(tmp_path)
    await pair(a)
    for k in ("MENU", "QMENU", "EXIT", "INFO", "GUIDE", "RED"):
        await a.execute("key_press", {"key": k})
    assert [c for c in FakeTv.last.calls] == [("button", k) for k in ("MENU", "QMENU", "EXIT", "INFO", "GUIDE", "RED")]
    await a.close()
