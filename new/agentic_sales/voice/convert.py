"""Voice-note audio -> the one format Muse Voice Transcribe accepts.

Measured against the live API: the `audio` part must be mono 16-bit PCM WAV at 16 or 24 kHz; every other encoding (including the
OGG/Opus that WhatsApp voice notes use) is rejected as "Malformed request". So anything that is not already that WAV is converted
with ffmpeg first. ffmpeg is installed in the server image; FFMPEG_PATH points at a specific binary when it is not on PATH.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from ..models.base import ModelError

ACCEPTED_RATES = (16000, 24000)
MAX_BYTES = 25 * 1024 * 1024


def is_accepted_wav(audio: bytes) -> bool:
    try:
        with wave.open(io.BytesIO(audio)) as w:
            return w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getframerate() in ACCEPTED_RATES and w.getcomptype() == "NONE"
    except (wave.Error, EOFError):
        return False


def ffmpeg_path() -> str | None:
    return os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg")


def to_wav(audio: bytes, timeout: float = 30.0) -> bytes:
    """The audio as mono 16-bit 16 kHz WAV. Already-correct WAV passes through untouched. Raises ModelError (key-safe) on any failure."""
    if not audio:
        raise ModelError("Meta transcribe: empty audio")
    if len(audio) > MAX_BYTES:
        raise ModelError("the voice note is too large to transcribe")
    if is_accepted_wav(audio):
        return audio
    exe = ffmpeg_path()
    if exe is None:
        raise ModelError("voice notes need ffmpeg to convert the audio, and it is not installed")
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.bin", Path(tmp) / "out.wav"       # a file, not a pipe: a piped WAV has no length in its header
        src.write_bytes(audio)
        cmd = [exe, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", str(dst)]
        try:
            done = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise ModelError("converting the voice note took too long") from None
        except OSError:
            raise ModelError("voice notes need ffmpeg to convert the audio, and it could not be started") from None
        out = dst.read_bytes() if dst.exists() else b""
    if done.returncode != 0 or not is_accepted_wav(out):
        raise ModelError("could not convert the voice note to WAV (unsupported or damaged audio)")
    return out
