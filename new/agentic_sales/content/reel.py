"""Short vertical videos (Reels, Status, TikTok) made from the post's own video script.

Meta has no public video-generation API, so the video is composed: Muse Image makes one picture per beat of the script, and ffmpeg turns the
pictures into a 9:16 clip with a slow zoom, the beat's on-screen text and soft fades between them. The clip is silent (there is no Meta
speech-synthesis model to add a voice-over with); the words are on screen. Nothing here reads or posts anything: it returns an MP4 for the
owner to approve like any other post.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

from ..voice.convert import ffmpeg_path

WIDTH, HEIGHT, FPS = 720, 1280, 25
MAX_BEATS = 6
MIN_SECONDS, MAX_SECONDS = 2.0, 6.0
FONTS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf")


class ReelError(RuntimeError):
    pass


@dataclass(frozen=True)
class Frame:
    image: bytes
    text: str = ""
    seconds: float = 3.0


def beats_of(script: dict | None) -> list[tuple[str, str, float]]:
    """(what to show, text on screen, seconds) for each beat of a video script, bounded."""
    out = []
    for b in (script or {}).get("beats", [])[:MAX_BEATS]:
        if not isinstance(b, dict):
            continue
        seconds = _seconds(str(b.get("t", "")))
        words = " ".join(str(b.get("on_screen_text") or b.get("voiceover") or "").split())
        out.append((str(b.get("visual") or "")[:400], " ".join(words.split(" ")[:10])[:90], seconds))          # the screen shows what the script says
    return out


def _seconds(t: str) -> float:
    """'0-2s' -> 2.0, '3-6s' -> 3.0 (the length of the beat), clamped to a watchable range."""
    nums = [float(x) for x in "".join(c if c.isdigit() or c == "." else " " for c in t).split() if x.replace(".", "", 1).isdigit()]
    span = nums[1] - nums[0] if len(nums) >= 2 and nums[1] > nums[0] else 3.0
    return max(MIN_SECONDS, min(MAX_SECONDS, span))


def _font() -> str | None:
    for f in (os.environ.get("REEL_FONT"), *FONTS):
        if f and Path(f).is_file():
            return f
    return None


def _filter_path(p: str) -> str:
    return p.replace("\\", "/").replace(":", "\\:")


def command(exe: str, frames: list[Frame], names: list[str], texts: list[str | None], out: str, font: str | None) -> list[str]:
    """The ffmpeg command. Pure, so it can be tested without ffmpeg."""
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-y"]
    for n in names:
        cmd += ["-i", n]
    total = sum(f.seconds for f in frames)
    cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    parts = []
    for i, f in enumerate(frames):
        n = int(f.seconds * FPS)
        chain = (f"[{i}:v]scale={WIDTH * 2}:{HEIGHT * 2}:force_original_aspect_ratio=increase,crop={WIDTH * 2}:{HEIGHT * 2},"
                 f"zoompan=z='min(zoom+0.0007,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={WIDTH}x{HEIGHT}:fps={FPS},setsar=1")
        if texts[i] and font:
            chain += (f",drawtext=fontfile='{_filter_path(font)}':textfile='{texts[i]}':fontcolor=white:fontsize=42:line_spacing=4:"
                      f"box=1:boxcolor=black@0.55:boxborderw=20:x=(w-text_w)/2:y=h*0.72")
        chain += f",fade=t=in:st=0:d=0.3,fade=t=out:st={max(0.0, f.seconds - 0.3):.2f}:d=0.3[v{i}]"
        parts.append(chain)
    joined = "".join(f"[v{i}]" for i in range(len(frames)))
    parts.append(f"{joined}concat=n={len(frames)}:v=1:a=0[v]")
    return cmd + ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", f"{len(frames)}:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                  "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", "-shortest", "-movflags", "+faststart", out]


def render(frames: list[Frame], out: Path, timeout: float = 240.0) -> Path:
    exe = ffmpeg_path()
    if exe is None:
        raise ReelError("making videos needs ffmpeg, and it is not installed on the server")
    if not frames:
        raise ReelError("there is nothing to put in the video")
    with tempfile.TemporaryDirectory() as tmp:
        names, texts = [], []
        for i, f in enumerate(frames):
            img = Path(tmp) / f"f{i}.png"
            img.write_bytes(f.image)
            names.append(img.name)
            if f.text.strip():
                t = Path(tmp) / f"t{i}.txt"
                t.write_text("\n".join(textwrap.wrap(f.text, 22)[:4]), encoding="utf-8")
                texts.append(t.name)
            else:
                texts.append(None)
        tmp_out = Path(tmp) / "reel.mp4"
        try:
            done = subprocess.run(command(exe, frames, names, texts, tmp_out.name, _font()), cwd=tmp, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ReelError("making the video took too long") from None
        except OSError as e:
            raise ReelError(f"ffmpeg could not start ({type(e).__name__})") from None
        if done.returncode != 0 or not tmp_out.exists():
            lines = done.stderr.decode("utf-8", "replace").strip().splitlines()
            raise ReelError("ffmpeg could not make the video: " + (lines[-1][:160] if lines else "no details"))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(tmp_out.read_bytes())
    return out
