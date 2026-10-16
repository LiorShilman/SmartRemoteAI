"""AndroidTVAdapter against a fake remote (no network, no hardware)."""
import pytest
from androidtvremote2 import CannotConnect, ConnectionClosed, InvalidAuth

from app.adapters.android_tv import AndroidTVAdapter
from app.adapters.base import AdapterError
from app.models.schemas import ErrorCode


class FakeRemote:
    opens: dict = {}
    current_app = None

    def __init__(self, name, cert, key, host):
        self.cert, self.key, self.host = cert, key, host
        self.keys: list[str] = []
        self.callbacks = []
        self.connect_error: Exception | None = None
        self.start_error: Exception | None = None
        self.finish_error: Exception | None = None
        self.send_error: Exception | None = None
        self.reconnect_armed = False
        FakeRemote.last = self

    async def async_generate_cert_if_missing(self):
        open(self.cert, "w").close(); open(self.key, "w").close()
        return True

    async def async_start_pairing(self):
        if self.start_error: raise self.start_error

    async def async_finish_pairing(self, code):
        if self.finish_error or code != "ABCD12": raise self.finish_error or InvalidAuth()

    async def async_connect(self):
        if self.connect_error: raise self.connect_error
        for cb in self.callbacks: cb(True)

    def add_is_available_updated_callback(self, cb): self.callbacks.append(cb)
    def send_launch_app_command(self, link):
        if self.send_error: raise self.send_error
        self.launched = getattr(self, 'launched', []) + [link]
        pkg = FakeRemote.opens.get(link)  # link -> package that comes to the foreground (None = nothing happens)
        if pkg:
            self.current_app = pkg
    def keep_reconnecting(self, cb=None): self.reconnect_armed = True
    def send_key_command(self, key, direction=None):
        if self.send_error: raise self.send_error
        self.keys.append(key)
        if self.respond_to_volume and key == "KEYCODE_VOLUME_DOWN":
            self.volume_info = {**self.volume_info, "level": self.volume_info["level"] - 1}
        if self.respond_to_volume and key == "KEYCODE_VOLUME_UP":
            self.volume_info = {**self.volume_info, "level": self.volume_info["level"] + 1}
    volume_info = {"level": 10, "max": 15, "muted": False}
    respond_to_volume = True

    def disconnect(self): pass


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeRemote.opens = {}
    FakeRemote.current_app = None


@pytest.fixture
def adapter(tmp_path):
    return AndroidTVAdapter("dev1", "192.168.1.20", tmp_path, FakeRemote)


async def paired(adapter):
    await adapter.pair_start()
    await adapter.pair_confirm("ABCD12")


async def test_starts_unpaired_and_refuses_commands(adapter):
    assert adapter.connection == "unpaired"
    with pytest.raises(AdapterError) as e:
        await adapter.execute("key_press", {"key": "HOME"})
    assert e.value.code is ErrorCode.NOT_PAIRED


async def test_pairing_then_key_mapping(adapter):
    await paired(adapter)
    assert adapter.connection == "connected" and FakeRemote.last.reconnect_armed
    await adapter.execute("key_press", {"key": "DPAD_CENTER"})
    await adapter.execute("key_press", {"key": "KEYCODE_1"})
    await adapter.execute("volume_up", {})
    assert FakeRemote.last.keys == ["KEYCODE_DPAD_CENTER", "KEYCODE_1", "KEYCODE_VOLUME_UP"]
    assert adapter.last_command_at is not None


async def test_wrong_code_denied_and_not_marked_paired(adapter):
    await adapter.pair_start()
    with pytest.raises(AdapterError) as e:
        await adapter.pair_confirm("WRONG1")
    assert e.value.code is ErrorCode.DENIED and adapter.connection == "unpaired"
    with pytest.raises(AdapterError):  # session invalidated: must restart pairing
        await adapter.pair_confirm("ABCD12")


async def test_confirm_without_start(adapter):
    with pytest.raises(AdapterError) as e:
        await adapter.pair_confirm("ABCD12")
    assert e.value.code is ErrorCode.NOT_PAIRED


async def test_unreachable_box_reports_not_connected(tmp_path):
    a = AndroidTVAdapter("dev2", "192.168.1.21", tmp_path, FakeRemote)
    await a.pair_start()
    FakeRemote.last.connect_error = CannotConnect()
    with pytest.raises(AdapterError) as e:
        await a.pair_confirm("ABCD12")
    assert e.value.code is ErrorCode.NOT_CONNECTED
    assert a.connection == "disconnected" and FakeRemote.last.reconnect_armed  # paired, will keep retrying
    with pytest.raises(AdapterError) as e:
        await a.execute("key_press", {"key": "HOME"})
    assert e.value.code is ErrorCode.NOT_CONNECTED


async def test_pair_start_connection_failure(tmp_path):
    class Unreachable(FakeRemote):
        async def async_start_pairing(self): raise CannotConnect()
    a = AndroidTVAdapter("dev3", "192.168.1.22", tmp_path, Unreachable)
    with pytest.raises(AdapterError) as e:
        await a.pair_start()
    assert e.value.code is ErrorCode.NOT_CONNECTED and a.last_error


async def test_connection_closed_marks_disconnected(adapter):
    await paired(adapter)
    FakeRemote.last.send_error = ConnectionClosed()
    with pytest.raises(AdapterError):
        await adapter.execute("key_press", {"key": "HOME"})
    assert adapter.connection == "disconnected"


async def test_restart_reconnects_when_marker_exists(tmp_path):
    a1 = AndroidTVAdapter("dev4", "192.168.1.23", tmp_path, FakeRemote)
    await paired(a1)
    a2 = AndroidTVAdapter("dev4", "192.168.1.23", tmp_path, FakeRemote)  # simulated server restart
    assert a2.connection == "disconnected"
    await a2.start()
    assert a2.connection == "connected"


async def test_invalid_auth_on_reconnect_unpairs(tmp_path):
    a1 = AndroidTVAdapter("dev5", "192.168.1.24", tmp_path, FakeRemote)
    await paired(a1)
    class Revoked(FakeRemote):
        async def async_connect(self): raise InvalidAuth()
    a2 = AndroidTVAdapter("dev5", "192.168.1.24", tmp_path, Revoked)
    await a2.start()
    assert a2.connection == "unpaired" and "צמד מחדש" in a2.last_error


async def test_alternate_channel_keys_are_mapped(adapter):
    await paired(adapter)
    for k in ("PAGE_UP", "PAGE_DOWN", "CHANNEL_UP", "DPAD_UP"):
        await adapter.execute("key_press", {"key": k})
    assert FakeRemote.last.keys == ["KEYCODE_PAGE_UP", "KEYCODE_PAGE_DOWN", "KEYCODE_CHANNEL_UP", "KEYCODE_DPAD_UP"]


async def test_unknown_key_unsupported(adapter):
    await paired(adapter)
    with pytest.raises(AdapterError) as e:
        await adapter.execute("key_press", {"key": "NOPE"})
    assert e.value.code is ErrorCode.UNSUPPORTED


def test_diagnostics_has_no_secrets(adapter):
    d = adapter.diagnostics()
    assert not any(k in d for k in ("cert", "key", "token"))


async def test_launch_app_uses_https_links_and_confirms_foreground_app(adapter, monkeypatch):
    from app.adapters import android_tv
    monkeypatch.setattr(android_tv, "APP_WAIT_S", 0.2)
    FakeRemote.opens = {"https://www.netflix.com/title": "com.netflix.ninja", "https://www.youtube.com/tv": "com.google.android.youtube.tv"}
    await paired(adapter)
    await adapter.execute("launch_app", {"app": "netflix"})
    await adapter.execute("launch_app", {"app": "youtube"})
    assert FakeRemote.last.launched == ["https://www.netflix.com/title", "https://www.youtube.com/tv"]


async def test_app_not_installed_opens_store_and_says_so(adapter, monkeypatch):
    from app.adapters import android_tv
    monkeypatch.setattr(android_tv, "APP_WAIT_S", 0.2)
    FakeRemote.opens = {"market://details?id=com.spotify.tv.android": "com.android.vending"}
    await paired(adapter)
    with pytest.raises(AdapterError) as e:
        await adapter.execute("launch_app", {"app": "spotify"})
    assert e.value.code is ErrorCode.UNSUPPORTED and "לא מותקנת" in e.value.message
    assert FakeRemote.last.launched == ["https://open.spotify.com", "market://details?id=com.spotify.tv.android"]


async def test_launch_unknown_app_rejected(adapter):
    await paired(adapter)
    with pytest.raises(AdapterError) as e:
        await adapter.execute("launch_app", {"app": "tiktok"})
    assert e.value.code is ErrorCode.UNSUPPORTED


async def test_launch_app_connection_closed_marks_disconnected(adapter):
    await paired(adapter)
    FakeRemote.opens = {}
    FakeRemote.last.send_error = ConnectionClosed()
    with pytest.raises(AdapterError):
        await adapter.execute("launch_app", {"app": "netflix"})
    assert adapter.connection == "disconnected"


async def test_settings_guide_info_keys(adapter):
    await paired(adapter)
    for k in ("SETTINGS", "GUIDE", "INFO", "MENU"):
        await adapter.execute("key_press", {"key": k})
    assert FakeRemote.last.keys == ["KEYCODE_SETTINGS", "KEYCODE_GUIDE", "KEYCODE_INFO", "KEYCODE_MENU"]


async def test_selftest_confirms_a_responsive_box_and_restores_the_volume(adapter, monkeypatch):
    from app.adapters import android_tv
    await paired(adapter)
    out = await adapter.selftest()
    assert out["ok"] is True and out["healed"] is False
    assert FakeRemote.last.keys[-2:] == ["KEYCODE_VOLUME_DOWN", "KEYCODE_VOLUME_UP"]
    assert FakeRemote.last.volume_info["level"] == 10  # left exactly as found


async def test_selftest_detects_a_silent_zombie_connection_and_reconnects(tmp_path, monkeypatch):
    class Zombie(FakeRemote):
        respond_to_volume = False
    created = []

    def factory(*a):
        r = Zombie(*a) if not created else FakeRemote(*a)  # the reconnect gets a healthy remote
        created.append(r)
        return r

    a = AndroidTVAdapter("zz", "192.168.1.99", tmp_path, factory)
    await a.pair_start(); await a.pair_confirm("ABCD12")
    monkeypatch.setattr(AndroidTVAdapter, "_wait_volume", lambda self, pred, timeout=2.0: _never())
    out = await a.selftest()
    assert out["ok"] is False and out["healed"] is True and len(created) == 2
    assert a.connection == "connected"


async def _never():
    return False


async def test_selftest_requires_a_connection(adapter):
    with pytest.raises(AdapterError) as e:
        await adapter.selftest()
    assert e.value.code is ErrorCode.NOT_PAIRED
