"""Public entry point: validate, plan, encode."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .errors import SplitError, fail, stderr_tail
from .naming import apply_names, default_name
from .plan import Segment, build_plan, validate_points_against_duration
from .probe import MediaInfo, ensure_ffmpeg_available, is_mp3, probe
from .timeparse import format_clock, iter_entries, parse_split_points


@dataclass
class SplitOptions:
    """Non-default behaviours the Advanced panel can switch on."""

    stream_copy: bool = False
    keep_temp: bool = False


@dataclass
class SplitResult:
    """Everything the UI needs to describe and deliver one completed split."""

    segments: list[Segment]
    names: list[str]
    paths: list[Path]
    notes: list[str]
    temp_dir: Path
    info: MediaInfo = field(repr=False)

    def make_archive(self) -> Path:
        """Bundle every segment into one ZIP for a single-download handoff.

        Built explicitly from the segment paths rather than by zipping the temp directory,
        which would sweep in a previous ZIP and then include the new one in itself.
        """
        archive = self.temp_dir / "segments.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for name, path in zip(self.names, self.paths):
                bundle.write(path, arcname=name)
        return archive


def split_audio(
    source: Path | None,
    points_text: str,
    names_text: str = "",
    options: SplitOptions | None = None,
    points_ms: list[int] | None = None,
    names: list[str] | None = None,
) -> SplitResult:
    """Split `source` at the points in `points_text`, writing segments to a temp directory.

    Validation happens in full before a single file is written, and a failure at any point
    leaves nothing behind but the (already populated) temp directory.

    `points_ms` and `names` accept input that is already parsed, which is how the
    "time + name per line" UI mode is served: those lines are parsed once by
    `parse_timed_names` and handed straight through, instead of being re-serialised into the
    two textboxes and read back. A name containing a comma or a leading `#` would not
    survive that round trip. When either is given it takes precedence over the
    corresponding text argument.
    """
    options = options or SplitOptions()
    ensure_ffmpeg_available()

    path = _validate_source(source)
    points = points_ms if points_ms is not None else _parse_points(points_text)
    info = probe(path)
    validate_points_against_duration(points, info.duration_ms)

    segments = build_plan(info.duration_ms, points)
    final_names, notes = _resolve_names(names_text, segments, path.stem, names)

    temp_dir = Path(tempfile.mkdtemp(prefix="audio-split-"))
    try:
        paths = [
            _encode_segment(path, temp_dir / name, segment, info, options)
            for segment, name in zip(segments, final_names)
        ]
    except Exception:
        # A partial file set is worse than an error, so a failed run leaves nothing behind
        # unless the user asked to keep the directory for inspection.
        if not options.keep_temp:
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    return SplitResult(
        segments=segments,
        names=final_names,
        paths=paths,
        notes=notes,
        temp_dir=temp_dir,
        info=info,
    )


def _validate_source(source: Path | None) -> Path:
    """Check the upload is exactly one non-empty MP3 and return it as a Path."""
    if source is None:
        raise fail("E_AUDIO_COUNT", count=0)
    if not source.exists():
        raise fail("E_AUDIO_COUNT", count=0)
    if source.stat().st_size == 0:
        raise fail("E_AUDIO_EMPTY", name=source.name)
    if not is_mp3(source):
        raise fail("E_AUDIO_FORMAT", name=source.name, actual="a non-MP3 file")
    return source


def _parse_points(points_text: str) -> list[int]:
    return parse_split_points(points_text or "")


def _resolve_names(
    names_text: str,
    segments: list[Segment],
    stem: str,
    names: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Return the final filename per segment plus any repairs made, defaulting when empty."""
    supplied = names if names is not None else [
        raw for _, raw in iter_entries(names_text or "")
    ]
    starts = [segment.start_ms for segment in segments]
    ends = [segment.end_ms for segment in segments]
    if not supplied:
        return (
            [
                default_name(stem, segment.index, segment.start_ms, segment.end_ms)
                for segment in segments
            ],
            [],
        )
    return apply_names(supplied, len(segments), stem, starts, ends)


def _encode_segment(
    source: Path,
    output: Path,
    segment: Segment,
    info: MediaInfo,
    options: SplitOptions,
) -> Path:
    """Cut one segment out of the source and write it to `output`."""
    start_s = f"{segment.start_ms / 1000:.6f}"
    duration_s = f"{segment.duration_ms / 1000:.6f}"

    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        start_s,
        "-i",
        str(source),
        "-t",
        duration_s,
        "-vn",
    ]
    if options.stream_copy:
        command += ["-c:a", "copy"]
    else:
        command += ["-c:a", "libmp3lame", "-q:a", "2"]
    if info.sample_rate:
        command += ["-ar", str(info.sample_rate)]
    if info.channels:
        command += ["-ac", str(info.channels)]
    command.append(str(output))

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SplitError(
            "E_FFMPEG_FAILED",
            fail(
                "E_FFMPEG_FAILED",
                index=segment.index,
                start=format_clock(segment.start_ms),
                end=format_clock(segment.end_ms),
            ).message,
            index=segment.index,
            detail=stderr_tail(result.stderr),
        )
    return output