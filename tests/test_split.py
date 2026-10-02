"""Integration tests; every one shells out to ffmpeg."""

from __future__ import annotations

import array
import math
import subprocess

import pytest

from splitter.errors import SplitError
from splitter.split import SplitOptions, split_audio

from conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

TOLERANCE_MS = 200  # an MP3 frame is ~26 ms; 200 ms absorbs encoder padding
ANALYSIS_RATE = 8000


def duration_ms(path) -> int:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(float(result.stdout.strip()) * 1000)


def samples_of(path, start_s: float = 0.0, span_s: float = 1.0):
    """Decode `span_s` of a file starting at `start_s` to mono 16-bit at ANALYSIS_RATE."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start_s:.6f}",
            "-i",
            str(path),
            "-t",
            f"{span_s:.6f}",
            "-ac",
            "1",
            "-ar",
            str(ANALYSIS_RATE),
            "-f",
            "s16le",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    decoded = array.array("h")
    decoded.frombytes(result.stdout)
    return decoded


def goertzel_energy(samples, frequency: float) -> float:
    """Energy at one exact frequency.

    A pure tone puts all its energy in a single bin, so this separates 440 Hz from 880 Hz
    exactly. Earlier attempts at a general pitch estimator failed: zero-crossing counting was
    too coarse once encoder padding shifted the window, and autocorrelation locked onto
    subharmonics. Asking about one known frequency sidesteps both.
    """
    n = len(samples)
    if n == 0:
        return 0.0
    k = int(0.5 + (n * frequency) / ANALYSIS_RATE)
    omega = 2.0 * math.pi * k / n
    coefficient = 2.0 * math.cos(omega)
    previous, previous2 = 0.0, 0.0
    for sample in samples:
        current = sample + coefficient * previous - previous2
        previous2, previous = previous, current
    return previous2**2 + previous**2 - coefficient * previous * previous2


def test_split_yields_one_segment_per_point_plus_one(tone_mp3):
    result = split_audio(tone_mp3, "00:03\n00:07")
    assert len(result.paths) == 3
    assert [p.exists() for p in result.paths] == [True, True, True]


def test_segment_durations_match_the_requested_split(tone_mp3):
    result = split_audio(tone_mp3, "00:03")
    first, second = result.paths
    assert abs(duration_ms(first) - 3000) < TOLERANCE_MS
    assert abs(duration_ms(second) - 7000) < TOLERANCE_MS


def test_concatenating_the_segments_reproduces_the_source_duration(tone_mp3):
    result = split_audio(tone_mp3, "00:01\n00:02\n00:03\n00:04\n00:05\n00:06\n00:07\n00:08\n00:09")
    joined = result.temp_dir / "joined.mp3"
    with open(joined, "wb") as handle:
        for path in result.paths:
            handle.write(path.read_bytes())
    assert abs(duration_ms(joined) - 10_000) < TOLERANCE_MS * len(result.paths)


def block_pitch(path, offset_s: float = 0.5, span_s: float = 1.0) -> int:
    """Pitch of a window starting `offset_s` into the segment.

    The window is kept inside the segment deliberately: a window straddling a 440/880
    boundary mixes both tones and reports neither reliably.
    """
    samples = samples_of(path, offset_s, span_s)
    if goertzel_energy(samples, 440.0) > goertzel_energy(samples, 880.0):
        return 440
    return 880


def test_each_segment_lands_in_the_right_tone_block(marker_mp3):
    """Marker blocks strictly alternate 440/880 Hz every 2 s.

    Cutting exactly on the 2 s boundaries must leave segment k opening inside block k. A
    cut drifting by a whole MP3 frame would pull in the neighbouring block's pitch.
    """
    result = split_audio(marker_mp3, "00:02\n00:04\n00:06\n00:08")
    assert len(result.paths) == 5
    assert [block_pitch(path) for path in result.paths] == [440, 880, 440, 880, 440]


def test_a_cut_inside_a_block_keeps_that_blocks_pitch(marker_mp3):
    """A segment opening mid-block reports the pitch of the block it starts in."""
    result = split_audio(marker_mp3, "00:02.5")
    # [0, 2.5) opens in block [0, 2) -> 440 Hz.
    assert block_pitch(result.paths[0], 0.5) == 440
    # [2.5, end) opens inside block [2, 4) -> 880 Hz.
    assert block_pitch(result.paths[1], 0.2) == 880


def test_a_short_leading_segment_is_still_pitched_correctly(marker_mp3):
    """A 0.4 s segment is shorter than the analysis window, so shrink the window too."""
    result = split_audio(marker_mp3, "00:00.4")
    assert block_pitch(result.paths[0], 0.05, 0.3) == 440
    # The remainder opens mid-block [0, 2), which is 440 Hz.
    assert block_pitch(result.paths[1], 0.05, 0.3) == 440


def test_cut_lands_within_one_frame_of_the_requested_offset(marker_mp3):
    """A cut 3 ms early must not bleed into the previous block."""
    result = split_audio(marker_mp3, "00:02.003", options=SplitOptions(stream_copy=True))
    assert len(result.paths) == 2
    assert abs(duration_ms(result.paths[0]) - 2003) < 100


def test_default_names_are_indexed_by_time(tone_mp3):
    result = split_audio(tone_mp3, "00:03\n00:07")
    assert result.names[0].startswith("tone_part01_00-00-00.000_00-00-03.000.mp3")
    assert result.names[1].startswith("tone_part02_00-00-03.000_00-00-07.000.mp3")
    assert result.names[2].startswith("tone_part03_00-00-07.000_")


def test_supplied_names_are_used_verbatim(tone_mp3):
    result = split_audio(tone_mp3, "00:05", "intro.mp3\nrest.mp3")
    assert result.names == ["intro.mp3", "rest.mp3"]
    assert [p.name for p in result.paths] == ["intro.mp3", "rest.mp3"]


def test_sample_rate_and_channel_count_are_preserved(tmp_path):
    from conftest import make_tone

    stereo = tmp_path / "stereo.mp3"
    make_tone(stereo, 4.0, freq=440, rate=22050, channels=2)
    result = split_audio(stereo, "00:02")
    for path in result.paths:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate,channels",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert probe.stdout.strip() == "22050,2"


def test_source_file_is_never_modified(tone_mp3):
    before = tone_mp3.read_bytes()
    split_audio(tone_mp3, "00:03\n00:06")
    assert tone_mp3.read_bytes() == before


def test_output_lands_in_a_temp_dir_not_beside_the_source(tone_mp3):
    result = split_audio(tone_mp3, "00:05")
    assert result.temp_dir != tone_mp3.parent
    for path in result.paths:
        assert path.parent == result.temp_dir


def test_archive_bundles_every_segment(tone_mp3):
    import zipfile

    result = split_audio(tone_mp3, "00:03\n00:06")
    archive = result.make_archive()
    with zipfile.ZipFile(archive) as bundle:
        bundled = set(bundle.namelist())
    assert bundled == set(result.names)


def test_archive_contains_only_the_segments_not_itself(tone_mp3):
    """Archiving the temp directory wholesale would sweep in the ZIP."""
    import zipfile

    result = split_audio(tone_mp3, "00:03\n00:06")
    archive = result.make_archive()
    with zipfile.ZipFile(archive) as bundle:
        assert "segments.zip" not in bundle.namelist()


def test_building_the_archive_twice_is_stable(tone_mp3):
    """A second call must not pull the first ZIP into the new one."""
    import zipfile

    result = split_audio(tone_mp3, "00:03\n00:06")
    result.make_archive()
    second = result.make_archive()
    with zipfile.ZipFile(second) as bundle:
        assert set(bundle.namelist()) == set(result.names)


@pytest.mark.parametrize(
    ("points_text", "expected_code"),
    [
        ("5m", "E_TIME_FORMAT"),
        ("", "E_NO_SPLITS"),
        ("00:00:00", "E_TIME_RANGE"),
        ("00:05\n00:03", "E_TIME_ORDER"),
        ("00:30:00", "E_TIME_PAST_END"),
    ],
)
def test_bad_split_points_raise_the_expected_code(tone_mp3, points_text, expected_code):
    with pytest.raises(SplitError) as exc:
        split_audio(tone_mp3, points_text)
    assert exc.value.code == expected_code


def test_wrong_name_count_is_rejected(tone_mp3):
    with pytest.raises(SplitError) as exc:
        split_audio(tone_mp3, "00:03\n00:07", "a.mp3\nb.mp3\nc.mp3\nd.mp3")
    assert exc.value.code == "E_NAME_COUNT"
    assert "Expected 3" in exc.value.message


def test_non_mp3_upload_is_rejected(tmp_path, real_wav):
    with pytest.raises(SplitError) as exc:
        split_audio(real_wav, "00:00:01")
    assert exc.value.code == "E_AUDIO_FORMAT"


def test_empty_upload_is_rejected(tmp_path):
    empty = tmp_path / "empty.mp3"
    empty.write_bytes(b"")
    with pytest.raises(SplitError) as exc:
        split_audio(empty, "00:00:01")
    assert exc.value.code == "E_AUDIO_EMPTY"


def test_missing_upload_is_rejected():
    with pytest.raises(SplitError) as exc:
        split_audio(None, "00:00:01")
    assert exc.value.code == "E_AUDIO_COUNT"


def test_unsafe_filename_is_treated_as_a_literal_name(tone_mp3):
    """Names reach ffmpeg through an argument list, so shell metacharacters stay inert."""
    result = split_audio(tone_mp3, "00:05", "a b.mp3\nc$(whoami).mp3")
    assert result.names == ["a b.mp3", "c$(whoami).mp3"]
    assert all(p.exists() for p in result.paths)


def test_names_containing_a_semicolon_are_split_as_separators(tone_mp3):
    """`;` is a documented entry separator, so it is never part of a name."""
    result = split_audio(tone_mp3, "00:05", "a.mp3; b.mp3")
    assert result.names == ["a.mp3", "b.mp3"]


def test_stream_copy_is_faster_and_still_correct(tone_mp3):
    copied = split_audio(tone_mp3, "00:03", options=SplitOptions(stream_copy=True))
    assert len(copied.paths) == 2
    assert abs(duration_ms(copied.paths[0]) - 3000) < 200


def test_very_short_final_segment_is_encoded_rather_than_dropped(tone_mp3):
    result = split_audio(tone_mp3, "00:00:09.95")
    assert len(result.paths) == 2
    assert result.paths[1].exists()
    assert result.paths[1].stat().st_size > 0