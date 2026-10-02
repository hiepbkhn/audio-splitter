"""Shared fixtures; audio is synthesised by ffmpeg so no binaries are committed."""

from __future__ import annotations

import shutil
import subprocess

import pytest

BLOCK_SECONDS = 2
BLOCK_FREQUENCIES = [440, 880] * 5  # strict alternation, 20 s total


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


# Marks a test as needing ffmpeg. `-m 'not ffmpeg'` deselects these for a fast run;
# pytest_collection_modifyitems below turns the marker into an actual skip when the
# binaries are genuinely absent.
requires_ffmpeg = pytest.mark.ffmpeg

FFMPEG_FIXTURES = {"tone_mp3", "marker_mp3", "silent_mp3", "real_wav"}


def run_ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args],
        check=True,
        capture_output=True,
    )


def make_tone(path, seconds: float, freq: int = 440, rate: int = 44100, channels: int = 1):
    run_ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={freq}:sample_rate={rate}:duration={seconds}",
        "-ac",
        str(channels),
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(path),
    )


@pytest.fixture(scope="session")
def tone_mp3(tmp_path_factory):
    """A 10 s 440 Hz mono tone."""
    path = tmp_path_factory.mktemp("audio") / "tone.mp3"
    make_tone(path, 10.0)
    return path


@pytest.fixture(scope="session")
def silent_mp3(tmp_path_factory):
    """3 s of silence: a control case where no tone test can apply."""
    path = tmp_path_factory.mktemp("audio") / "silent.mp3"
    run_ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=mono",
        "-t",
        "3",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(path),
    )
    return path


@pytest.fixture(scope="session")
def marker_mp3(tmp_path_factory):
    """Ten 2 s blocks strictly alternating 440 Hz and 880 Hz, for 20 s total.

    Built by concatenating ten discrete single-tone files with the concat filter. Gating
    two sines inside one aevalsrc expression makes them beat against each other, producing
    blocks that are no longer clean tones and boundaries that cannot be located reliably.
    Every cut boundary therefore falls between two different pitches, so a test can assert
    which block a segment came from rather than only checking durations.
    """
    work = tmp_path_factory.mktemp("marker")
    blocks = []
    for position, frequency in enumerate(BLOCK_FREQUENCIES):
        block = work / f"block{position}.wav"
        run_ffmpeg(
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate=44100:duration={BLOCK_SECONDS}",
            "-ac",
            "1",
            str(block),
        )
        blocks.append(block)

    inputs: list[str] = []
    for block in blocks:
        inputs += ["-i", str(block)]
    chain = "".join(f"[{i}:a]" for i in range(len(blocks)))
    path = tmp_path_factory.mktemp("audio") / "marker.mp3"
    run_ffmpeg(
        *inputs,
        "-filter_complex",
        f"{chain}concat=n={len(blocks)}:v=0:a=1[out]",
        "-map",
        "[out]",
        "-ac",
        "1",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(path),
    )
    return path


@pytest.fixture(scope="session")
def real_wav(tmp_path_factory):
    """A genuine WAV file, used to prove sniffing ignores the file extension."""
    path = tmp_path_factory.mktemp("audio") / "tone.wav"
    make_tone(path, 1.0)
    return path


def pytest_collection_modifyitems(config, items):
    """Apply the `ffmpeg` marker and skip anything that needs ffmpeg when it is absent.

    A test cannot declare the marker itself if it only reaches ffmpeg through a fixture
    that synthesises its own audio, so fixture users are caught here too.
    """
    available = ffmpeg_available()
    for item in items:
        if FFMPEG_FIXTURES & set(item.fixturenames):
            item.add_marker("ffmpeg")
        if not available and (
            item.get_closest_marker("ffmpeg") or FFMPEG_FIXTURES & set(item.fixturenames)
        ):
            item.add_marker(pytest.mark.skip(reason="ffmpeg/ffprobe not on PATH"))