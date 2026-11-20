"""Spoken replies: bounded text in, MP3 out; no network in tests."""
import asyncio

import pytest

from app.services.tts import Tts
from tests.test_zeppelin import H, client, fake  # noqa: F401 - fixtures


class FakeSynth:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def __call__(self, text, voice):
        self.calls.append((text, voice))
        if self.fail:
            raise OSError("no network")
        return b"ID3fake-mp3"


@pytest.fixture
def synth(client):
    s = FakeSynth()
    client.app.state.tts = Tts(synth=s)
    return s


def test_reply_is_mp3_with_the_hebrew_voice(client, synth):
    r = client.post("/api/tts", json={"text": "הרמקול על 25"}, headers=H)
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content == b"ID3fake-mp3"
    assert synth.calls == [("הרמקול על 25", "he-IL-HilaNeural")]
    client.post("/api/tts", json={"text": "הרמקול על 25"}, headers=H)
    assert len(synth.calls) == 1  # cached


@pytest.mark.parametrize("body", [{"text": ""}, {"text": "   "}, {"text": "x" * 301}, {"text": "a\nb"},
                                  {"text": "שלום", "voice": "en-US-GuyNeural"}, {"text": "שלום", "ssml": "<x/>"}])
def test_bad_input_is_refused_without_a_call(client, synth, body):
    assert client.post("/api/tts", json=body, headers=H).status_code == 422
    assert synth.calls == []


def test_requires_auth(client, synth):
    assert client.post("/api/tts", json={"text": "שלום"}).status_code == 401


def test_service_down_is_a_clear_error(client):
    client.app.state.tts = Tts(synth=FakeSynth(fail=True))
    r = client.post("/api/tts", json={"text": "שלום"}, headers=H)
    assert r.status_code == 503 and "לא זמין" in r.json()["detail"]["message"]


def test_budget():
    t = Tts(synth=FakeSynth())
    t.MAX_PER_WINDOW = 2
    asyncio.run(t.speak("א"))
    asyncio.run(t.speak("ב"))
    with pytest.raises(Exception, match="יותר מדי"):
        asyncio.run(t.speak("ג"))
