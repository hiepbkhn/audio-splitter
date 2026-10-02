"""Hardening: concurrency, temp hygiene, and shell-injection safety."""

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from splitter.errors import SplitError
from splitter.split import SplitOptions, split_audio

from conftest import requires_ffmpeg

pytestmark = requires_ffmpeg


def test_two_concurrent_splits_do_not_share_state(tone_mp3, marker_mp3):
    """Runs must be independent: no module-level state, no shared temp directory."""
    results: dict[str, object] = {}
    errors: list[BaseException] = []

    def run(key: str, source: Path, points: str) -> None:
        try:
            results[key] = split_audio(source, points)
        except BaseException as exc:  # noqa: BLE001 - re-raised after the join
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=("a", tone_mp3, "00:03")),
        threading.Thread(target=run, args=("b", marker_mp3, "00:02\n00:04")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"concurrent split raised: {errors}"
    assert results["a"].temp_dir != results["b"].temp_dir
    assert len(results["a"].paths) == 2
    assert len(results["b"].paths) == 3
    assert all(p.name.startswith("tone_part") for p in results["a"].paths)
    assert all(p.name.startswith("marker_part") for p in results["b"].paths)


def test_a_failed_run_leaves_no_files_behind(tone_mp3):
    """A validation failure happens before any encoding, so nothing is written at all."""
    before = set(Path("/tmp").glob("audio-split-*"))
    with pytest.raises(SplitError):
        split_audio(tone_mp3, "00:30:00")
    assert set(Path("/tmp").glob("audio-split-*")) == before


def test_keep_temp_preserves_the_directory_on_failure(tone_mp3, monkeypatch):
    """With keep_temp the directory survives an encoding failure, for inspection."""
    import splitter.split as split_module

    def explode(*args, **kwargs):
        raise split_module.SplitError("E_FFMPEG_FAILED", "synthetic failure")

    before = set(Path("/tmp").glob("audio-split-*"))
    monkeypatch.setattr(split_module, "_encode_segment", explode)
    with pytest.raises(SplitError):
        split_audio(tone_mp3, "00:03", options=SplitOptions(keep_temp=True))

    created = set(Path("/tmp").glob("audio-split-*")) - before
    try:
        assert len(created) == 1, "keep_temp should have left the directory"
    finally:
        for directory in created:
            shutil.rmtree(directory, ignore_errors=True)


def test_a_shell_metacharacter_in_a_name_cannot_run_a_command(tone_mp3, tmp_path):
    """Names go to ffmpeg via an argument list, so $(...) is just text in a filename."""
    canary = tmp_path / "canary"
    canary.mkdir()
    result = split_audio(tone_mp3, "00:05", f"$(touch {canary}/pwned).mp3\nx.mp3")
    assert not (canary / "pwned").exists()
    assert all(p.exists() for p in result.paths)


def test_a_filename_with_spaces_and_quotes_survives_intact(tone_mp3):
    result = split_audio(tone_mp3, "00:05", "my song (final).mp3\nother one.mp3")
    assert result.names == ["my song (final).mp3", "other one.mp3"]
    assert all(p.exists() for p in result.paths)


def test_the_source_survives_repeated_runs_unchanged(tone_mp3):
    before = tone_mp3.read_bytes()
    for _ in range(3):
        split_audio(tone_mp3, "00:02\n00:04\n00:06")
    assert tone_mp3.read_bytes() == before


def test_a_corrupt_truncated_mp3_fails_cleanly(tmp_path):
    """A file that sniffs as MP3 but cannot be decoded must not crash the caller."""
    from conftest import make_tone

    good = tmp_path / "good.mp3"
    make_tone(good, 2.0)
    corrupt = tmp_path / "corrupt.mp3"
    corrupt.write_bytes(good.read_bytes()[:200])

    with pytest.raises(SplitError) as exc:
        split_audio(corrupt, "00:01")
    assert exc.value.code in {"E_PROBE_FAILED", "E_FFMPEG_FAILED"}


def test_ffmpeg_receives_no_shell(tmp_path):
    """Guard the invocation shape itself: no shell, no string interpolation."""
    import inspect

    import splitter.split as split_module

    source = inspect.getsource(split_module)
    assert "shell=True" not in source
    assert "subprocess.run(f" not in source
    assert "subprocess.run(command" in source, "ffmpeg must be invoked with an argument list"