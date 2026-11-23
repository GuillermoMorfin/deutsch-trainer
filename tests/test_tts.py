from pathlib import Path

import pytest

from app import tts

REAL_VOICES = Path(__file__).resolve().parent.parent / "data" / "voices"


def test_no_voices_installed_means_empty_list_and_404(client):
    assert client.get("/api/tts/voices").json() == []
    assert client.get("/api/tts", params={"text": "Hallo", "voice": "thorsten"}).status_code == 404


@pytest.mark.skipif(not (REAL_VOICES / "de_DE-thorsten-high.onnx").exists(), reason="Piper voice not downloaded")
def test_synthesis_with_real_voice_is_cached(client, monkeypatch):
    monkeypatch.setattr(tts, "voices_dir", lambda: REAL_VOICES)
    assert [v["id"] for v in client.get("/api/tts/voices").json()][:1] == ["thorsten"]
    r = client.get("/api/tts", params={"text": "Hallo Marco, wie geht es dir?", "voice": "thorsten", "rate": 0.9})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content[:4] == b"RIFF"
    assert "immutable" in r.headers["cache-control"]
    files = list(tts.cache_dir().glob("*.wav"))
    client.get("/api/tts", params={"text": "Hallo Marco, wie geht es dir?", "voice": "thorsten", "rate": 0.9})
    assert list(tts.cache_dir().glob("*.wav")) == files          # second request served from the cache
    # Piper varies a little from run to run, so compare clearly different speeds
    slow = tts.synthesize("Hallo Marco, wie geht es dir?", "thorsten", 0.65)
    fast = tts.synthesize("Hallo Marco, wie geht es dir?", "thorsten", 1.25)
    assert slow.stat().st_size > fast.stat().st_size * 1.3       # slower speech = longer audio
