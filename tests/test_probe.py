import pytest

from splitter.errors import CODES, SplitError, fail

from conftest import requires_ffmpeg

SPEC_CODES = {
    "E_AUDIO_COUNT",
    "E_AUDIO_FORMAT",
    "E_AUDIO_EMPTY",
    "E_PROBE_FAILED",
    "E_NO_SPLITS",
    "E_SPLIT_COUNT",
    "E_TIME_FORMAT",
    "E_TIME_RANGE",
    "E_TIME_ORDER",
    "E_TIME_PAST_END",
    "E_NAME_COUNT",
    "E_NAME_EXTENSION",
    "E_FFMPEG_MISSING",
    "E_FFMPEG_FAILED",
}


def test_every_spec_error_code_exists():
    assert SPEC_CODES == CODES


def test_fail_fills_the_canonical_template():
    error = fail("E_TIME_RANGE", index=3, value="00:00:00.000")
    assert isinstance(error, SplitError)
    assert error.message == "Split point 3 (00:00:00.000) must be greater than 00:00:00."
    assert str(error) == error.message


def test_ensure_ffmpeg_available_passes_on_this_machine():
    from splitter.probe import ensure_ffmpeg_available

    ensure_ffmpeg_available()  # must not raise


@requires_ffmpeg
def test_probe_reads_duration_sample_rate_and_channels(tone_mp3):
    from splitter.probe import probe

    info = probe(tone_mp3)
    assert abs(info.duration_ms - 10_000) < 200
    assert info.sample_rate == 44100
    assert info.channels == 1


@requires_ffmpeg
def test_is_mp3_accepts_a_real_mp3(tone_mp3):
    from splitter.probe import is_mp3

    assert is_mp3(tone_mp3) is True


@requires_ffmpeg
def test_is_mp3_rejects_a_wav_disguised_with_an_mp3_extension(tmp_path, real_wav):
    from splitter.probe import is_mp3

    disguised = tmp_path / "actually_a_wav.mp3"
    disguised.write_bytes(real_wav.read_bytes())
    assert is_mp3(disguised) is False


@requires_ffmpeg
def test_is_mp3_accepts_a_real_mp3_renamed_to_wav(tone_mp3, tmp_path):
    from splitter.probe import is_mp3

    renamed = tmp_path / "actually_an_mp3.wav"
    renamed.write_bytes(tone_mp3.read_bytes())
    assert is_mp3(renamed) is True


@requires_ffmpeg
def test_is_mp3_rejects_an_empty_file(tmp_path):
    from splitter.probe import is_mp3

    empty = tmp_path / "empty.mp3"
    empty.write_bytes(b"")
    assert is_mp3(empty) is False


@requires_ffmpeg
def test_probe_on_a_non_audio_file_reports_probe_failed(tmp_path):
    from splitter.probe import probe

    junk = tmp_path / "junk.mp3"
    junk.write_bytes(b"\xff\xfbnot really an mp3")
    with pytest.raises(SplitError) as exc:
        probe(junk)
    assert exc.value.code == "E_PROBE_FAILED"
    assert exc.value.detail


def test_every_error_code_is_reachable(tone_mp3, real_wav, tmp_path):
    """Each code in the spec table must be raisable from a public entry point.

    A code that nothing raises is documentation of a path that does not exist, which is
    worse than an honest gap because the user is promised a precise message they never see.
    """
    import splitter.probe as probe_module
    import splitter.split as split_module
    from splitter.naming import apply_names
    from splitter.plan import validate_points_against_duration
    from splitter.probe import ensure_ffmpeg_available, probe
    from splitter.split import split_audio
    from splitter.timeparse import parse_split_points

    good = tone_mp3
    corrupt = tmp_path / "corrupt.mp3"
    corrupt.write_bytes(good.read_bytes()[:200])

    def capture(code, call):
        try:
            call()
        except SplitError as error:
            assert error.code == code, f"expected {code}, got {error.code}"
            return
        raise AssertionError(f"{code} was never raised")

    capture("E_AUDIO_COUNT", lambda: split_audio(None, "00:01"))
    capture("E_AUDIO_EMPTY", lambda: split_audio(_empty(tmp_path), "00:01"))
    capture("E_AUDIO_FORMAT", lambda: split_audio(real_wav, "00:01"))
    capture("E_PROBE_FAILED", lambda: probe(corrupt))
    capture("E_NO_SPLITS", lambda: parse_split_points("# nothing\n\n"))
    capture("E_SPLIT_COUNT", lambda: parse_split_points("\n".join(str(i) for i in range(1, 101))))
    capture("E_TIME_FORMAT", lambda: parse_split_points("5m"))
    capture("E_TIME_RANGE", lambda: parse_split_points("00:00:00"))
    capture("E_TIME_ORDER", lambda: parse_split_points("00:02\n00:01"))
    capture(
        "E_TIME_PAST_END",
        lambda: validate_points_against_duration([60_000], 10_000),
    )
    capture("E_NAME_COUNT", lambda: apply_names(["a.mp3"], 3, "s", [0], [1000]))
    capture("E_NAME_EXTENSION", lambda: apply_names(["a.wav"], 1, "s", [0], [1000]))

    original_encode = split_module._encode_segment

    def explode(*args, **kwargs):
        raise SplitError("E_FFMPEG_FAILED", "synthetic encoding failure")

    split_module._encode_segment = explode
    try:
        capture("E_FFMPEG_FAILED", lambda: split_audio(good, "00:01"))
    finally:
        split_module._encode_segment = original_encode

    original_which = probe_module.shutil.which
    probe_module.shutil.which = lambda name: None
    try:
        capture("E_FFMPEG_MISSING", ensure_ffmpeg_available)
    finally:
        probe_module.shutil.which = original_which


def _empty(tmp_path):
    empty = tmp_path / "empty_for_codes.mp3"
    empty.write_bytes(b"")
    return empty