"""Natural German voices with Piper (open-source neural TTS, runs locally and offline).

Voices live in data/voices (downloaded with:  uv run python -m piper.download_voices
--download-dir data/voices de_DE-thorsten-high de_DE-kerstin-low). Each sentence is synthesised once
and cached as a WAV in data/tts_cache, so re-listening is instant.
"""

from __future__ import annotations

import hashlib
import io
import threading
import wave
from functools import lru_cache
from pathlib import Path

from .db import db_path

VOICES = {   # short name -> (model file, label)
    "thorsten": ("de_DE-thorsten-high", "Thorsten · natürlich (männlich)"),
    "kerstin": ("de_DE-kerstin-low", "Kerstin · natürlich (weiblich)"),
}
_lock = threading.Lock()


def voices_dir() -> Path:
    return db_path().parent / "voices"


def cache_dir() -> Path:
    d = db_path().parent / "tts_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def available() -> list[dict]:
    try:
        import piper  # noqa: F401
    except ImportError:
        return []
    return [{"id": k, "label": label} for k, (model, label) in VOICES.items()
            if (voices_dir() / f"{model}.onnx").exists()]


@lru_cache(maxsize=4)
def _voice(name: str):
    from piper import PiperVoice
    model, _ = VOICES[name]
    return PiperVoice.load(voices_dir() / f"{model}.onnx")


def synthesize(text: str, voice: str = "thorsten", rate: float = 0.9) -> Path:
    """WAV file for one sentence. rate < 1 speaks slower (Piper length_scale = 1 / rate)."""
    if voice not in VOICES:
        raise KeyError(voice)
    text = " ".join(text.split())[:600]
    rate = min(1.3, max(0.6, rate))
    key = hashlib.sha1(f"{voice}|{rate:.2f}|{text}".encode()).hexdigest()
    path = cache_dir() / f"{key}.wav"
    if path.exists():
        return path
    from piper import SynthesisConfig
    buf = io.BytesIO()
    with _lock:   # one synthesis at a time keeps CPU use calm
        with wave.open(buf, "wb") as wav:
            _voice(voice).synthesize_wav(text, wav, syn_config=SynthesisConfig(length_scale=1 / rate))
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(buf.getvalue())
    tmp.rename(path)
    return path
