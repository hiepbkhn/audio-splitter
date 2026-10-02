"""MP3 sniffing and ffprobe-based media inspection."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import SplitError, fail, stderr_tail


@dataclass(frozen=True)
class MediaInfo:
    """What the splitter needs to know about the source before cutting it."""

    duration_ms: int
    sample_rate: int
    channels: int


def is_mp3(path: Path) -> bool:
    """Sniff the container: an ID3 tag or an MPEG frame sync, ignoring the extension."""
    try:
        with path.open("rb") as handle:
            header = handle.read(3)
            if header == b"ID3":
                return True
            handle.seek(0)
            head = handle.read(2)
    except OSError:
        return False
    if len(head) < 2 or head[0] != 0xFF:
        return False
    return (head[1] & 0b1110_0000) == 0x1110_0000


def probe(path: Path) -> MediaInfo:
    """Read duration, sample rate and channel count via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SplitError(
            "E_PROBE_FAILED",
            fail("E_PROBE_FAILED", name=path.name).message,
            detail=stderr_tail(result.stderr),
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SplitError(
            "E_PROBE_FAILED",
            fail("E_PROBE_FAILED", name=path.name).message,
            detail=str(exc),
        ) from exc

    duration_s = payload.get("format", {}).get("duration")
    if duration_s is None:
        raise SplitError(
            "E_PROBE_FAILED",
            fail("E_PROBE_FAILED", name=path.name).message,
            detail="ffprobe reported no duration",
        )

    duration_ms = int(float(duration_s) * 1000)
    if duration_ms <= 0:
        raise SplitError(
            "E_PROBE_FAILED",
            fail("E_PROBE_FAILED", name=path.name).message,
            detail="ffprobe reported a non-positive duration",
        )

    audio = next(
        (s for s in payload.get("streams", []) if s.get("codec_type") == "audio"), None
    )
    if audio is None:
        raise SplitError(
            "E_PROBE_FAILED",
            fail("E_PROBE_FAILED", name=path.name).message,
            detail="no audio stream found",
        )

    return MediaInfo(
        duration_ms=duration_ms,
        sample_rate=int(audio.get("sample_rate", 0)),
        channels=int(audio.get("channels", 0)),
    )


def ensure_ffmpeg_available() -> None:
    """Fail fast at startup if ffmpeg or ffprobe is not on PATH."""
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            raise fail("E_FFMPEG_MISSING")