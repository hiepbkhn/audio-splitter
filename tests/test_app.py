"""Smoke tests driving the handler through Gradio's test client."""

from __future__ import annotations

import pytest

from app import MODE_POINTS, MODE_POINTS_AND_NAMES, MODE_TIMED_NAMES, split_clicked

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
    # Identifying the listener by its handler rather than its input count keeps this test
    # from breaking every time the handler grows an input.
    split_listeners = [
        dependency
        for dependency in clicks
        if (dependency.get("api_name") or "").endswith("split_clicked")
    ]
    assert len(split_listeners) == 1, "expected exactly one split_clicked listener"
    # audio, points, names, stream_copy, keep_temp, mode, pairs
    assert len(split_listeners[0]["inputs"]) == 7
    assert len(split_listeners[0]["outputs"]) == 4
    assert callable(split_clicked)


def test_the_paired_mode_names_every_segment(tone_mp3):
    summary, files, _, _ = split_clicked(
        str(tone_mp3), "", "", False, False, MODE_TIMED_NAMES,
        "00:00 Đàn Gà Trong Sân\n00:03 Con Cò Bé Bé\n00:07 Bụi Phấn",
    )
    # Three lines -> three named segments, the last running to the end.
    assert len(files) == 3
    assert "Đàn Gà Trong Sân.mp3" in summary
    assert "Con Cò Bé Bé.mp3" in summary
    assert "Bụi Phấn.mp3" in summary
    assert "3 segments" in summary


def test_the_paired_mode_ignores_the_separate_textboxes(tone_mp3):
    """Points and names typed in the other boxes must not leak into paired mode."""
    _, files, _, _ = split_clicked(
        str(tone_mp3), "00:08", "ignored.mp3\nalso-ignored.mp3", False, False,
        MODE_TIMED_NAMES, "00:00 One\n00:03 Two",
    )
    assert len(files) == 2


def test_the_paired_mode_reports_a_bad_time(tone_mp3):
    summary, files, _, _ = split_clicked(
        str(tone_mp3), "", "", False, False, MODE_TIMED_NAMES, "00:00 One\n5m Two"
    )
    assert files == []
    assert "E_TIME_FORMAT" in summary


def test_the_paired_mode_reports_out_of_order_times(tone_mp3):
    summary, files, _, _ = split_clicked(
        str(tone_mp3), "", "", False, False, MODE_TIMED_NAMES,
        "00:00 One\n00:05 Later\n00:02 Earlier",
    )
    assert files == []
    assert "E_TIME_ORDER" in summary


def test_the_paired_mode_requires_at_least_one_line(tone_mp3):
    summary, files, _, _ = split_clicked(
        str(tone_mp3), "", "", False, False, MODE_TIMED_NAMES, "# nothing\n\n"
    )
    assert files == []
    assert "E_NO_SPLITS" in summary


def test_the_points_mode_still_works_without_names(tone_mp3):
    summary, files, _, _ = split_clicked(
        str(tone_mp3), "00:03\n00:07", "", False, False, MODE_POINTS
    )
    assert len(files) == 3
    assert "tone_part01_" in summary


def test_the_default_mode_is_still_points_plus_names(tone_mp3):
    """A handler call with no mode argument must behave as it did before the new mode."""
    summary, files, _, _ = split_clicked(
        str(tone_mp3), "00:05", "intro.mp3\nrest.mp3", False, False
    )
    assert len(files) == 2
    assert "intro.mp3" in summary


def test_mode_changed_shows_only_the_relevant_textboxes():
    from app import build_demo, mode_changed

    assert build_demo() is not None
    points, names, pairs = mode_changed(MODE_TIMED_NAMES)
    assert points["visible"] is False
    assert names["visible"] is False
    assert pairs["visible"] is True

    points, names, pairs = mode_changed(MODE_POINTS)
    assert points["visible"] is True
    assert names["visible"] is False
    assert pairs["visible"] is False

    points, names, pairs = mode_changed(MODE_POINTS_AND_NAMES)
    assert points["visible"] is True
    assert names["visible"] is True
    assert pairs["visible"] is False