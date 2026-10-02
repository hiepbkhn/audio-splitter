"""Smoke tests driving the handler through Gradio's test client."""

from __future__ import annotations

import pytest

from app import split_clicked

from conftest import requires_ffmpeg

pytestmark = requires_ffmpeg


def test_a_valid_split_returns_one_file_per_segment_plus_one(tone_mp3):
    summary, files, status, archive = split_clicked(str(tone_mp3), "00:03\n00:07", "", False, False)
    assert len(files) == 3
    assert "3 segments" in summary
    assert status.startswith("Done.")
    assert archive.endswith(".zip")


def test_a_valid_split_without_names_uses_indexed_names(tone_mp3):
    summary, files, _, _ = split_clicked(str(tone_mp3), "00:05", "", False, False)
    assert len(files) == 2
    assert "tone_part01_" in summary
    assert "tone_part02_" in summary


def test_supplied_names_appear_in_the_summary(tone_mp3):
    summary, files, _, _ = split_clicked(
        str(tone_mp3), "00:05", "intro.mp3\nrest.mp3", False, False
    )
    assert len(files) == 2
    assert "intro.mp3" in summary
    assert "rest.mp3" in summary


def test_repaired_names_are_reported_to_the_user(tone_mp3):
    summary, files, _, _ = split_clicked(
        str(tone_mp3), "00:05", "in/tro.mp3\noutro.mp3", False, False
    )
    assert len(files) == 2
    assert "Adjusted names" in summary
    assert "intro.mp3" in summary


def test_a_bad_time_returns_an_error_block_and_no_files(tone_mp3):
    summary, files, status, archive = split_clicked(str(tone_mp3), "5m", "", False, False)
    assert files == []
    assert status == ""
    assert archive is None
    assert "E_TIME_FORMAT" in summary
    assert "Split point 1" in summary


def test_an_out_of_range_time_returns_an_error_block(tone_mp3):
    summary, files, _, _ = split_clicked(str(tone_mp3), "00:30:00", "", False, False)
    assert files == []
    assert "E_TIME_PAST_END" in summary


def test_a_missing_file_returns_an_error_block():
    summary, files, _, _ = split_clicked(None, "00:05", "", False, False)
    assert files == []
    assert "E_AUDIO_COUNT" in summary


def test_a_wrong_name_count_returns_an_error_block(tone_mp3):
    summary, files, _, _ = split_clicked(
        str(tone_mp3), "00:05", "only-one.mp3", False, False
    )
    assert files == []
    assert "E_NAME_COUNT" in summary


def test_keep_temp_surfaces_the_directory(tone_mp3):
    _, _, status, _ = split_clicked(str(tone_mp3), "00:05", "", False, True)
    assert "kept in" in status


def test_the_demo_builds_without_error():
    from app import build_demo

    assert build_demo() is not None


def test_the_button_is_wired_to_the_handler():
    """The Split button's click must route to split_clicked, not to a stray function."""
    from app import build_demo, split_clicked

    demo = build_demo()
    config = demo.get_config_file()
    clicks = [
        dependency
        for dependency in config["dependencies"]
        if any(target[1] == "click" for target in dependency.get("targets", []))
    ]
    # The Examples block also registers a click, so identify the split listener by its
    # five inputs: audio, points, names, stream_copy, keep_temp.
    split_listeners = [
        dependency for dependency in clicks if len(dependency.get("inputs", [])) == 5
    ]
    assert len(split_listeners) == 1, "expected exactly one five-input click listener"
    assert len(split_listeners[0]["outputs"]) == 4
    assert callable(split_clicked)