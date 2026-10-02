import pytest

from splitter.errors import SplitError
from splitter.naming import apply_names, default_name, sanitize_name


def test_default_name_matches_the_documented_pattern():
    assert (
        default_name("song", 3, 750_000, 1_800_000)
        == "song_part03_00-12-30.000_00-30-00.000.mp3"
    )


def test_default_name_pads_part_numbers_to_two_digits():
    assert default_name("song", 1, 0, 1000).startswith("song_part01_")
    assert default_name("song", 12, 0, 1000).startswith("song_part12_")


@pytest.mark.parametrize(
    "raw",
    ["a/b", "a\\b", "../../etc/passwd", "..", "..\\..\\windows", "a\x00b", "a:b", 'a"b', "a|b", "a?b", "a*b", "a<b", "a>b"],
)
def test_path_separators_and_illegal_characters_are_stripped(raw):
    cleaned = sanitize_name(raw, "fallback")
    assert "/" not in cleaned
    assert "\\" not in cleaned
    assert ".." not in cleaned
    assert ":" not in cleaned


@pytest.mark.parametrize("reserved", ["CON", "con", "PRN", "AUX", "NUL", "COM1", "LPT9", "com9"])
def test_windows_reserved_device_names_are_prefixed(reserved):
    assert sanitize_name(reserved, "fallback") == f"_{reserved}"


def test_reserved_name_with_extension_is_also_prefixed():
    assert sanitize_name("CON.mp3", "fallback") == "_CON.mp3"


def test_trailing_dots_and_whitespace_are_trimmed():
    assert sanitize_name("name...  ", "fallback") == "name"


def test_empty_after_cleaning_falls_back():
    assert sanitize_name("   ", "fallback.mp3") == "fallback.mp3"
    assert sanitize_name("..", "fallback.mp3") == "fallback.mp3"


def test_long_names_are_truncated_to_the_byte_limit_without_splitting_characters():
    cleaned = sanitize_name("é" * 300, "fallback")
    assert len(cleaned.encode("utf-8")) <= 255
    assert "�" not in cleaned


def test_apply_names_uses_supplied_names_in_order():
    names, notes = apply_names(["intro.mp3", "verse.mp3", "outro.mp3"], 3, "song", [0, 1000, 2000], [1000, 2000, 3000])
    assert names == ["intro.mp3", "verse.mp3", "outro.mp3"]
    assert notes == []


def test_apply_names_rejects_a_mismatched_count():
    with pytest.raises(SplitError) as exc:
        apply_names(["a.mp3", "b.mp3"], 3, "song", [0, 1000], [1000, 2000])
    assert exc.value.code == "E_NAME_COUNT"
    assert "Expected 3" in exc.value.message


def test_apply_names_rejects_a_non_mp3_extension():
    with pytest.raises(SplitError) as exc:
        apply_names(["intro.wav", "verse.mp3"], 2, "song", [0, 1000], [1000, 2000])
    assert exc.value.code == "E_NAME_EXTENSION"


def test_apply_names_reports_every_bad_extension_at_once():
    with pytest.raises(SplitError) as exc:
        apply_names(["a.wav", "b.wav"], 2, "song", [0, 1000], [1000, 2000])
    assert len(exc.value.message.splitlines()) == 2


def test_duplicate_names_are_disambiguated_and_reported():
    names, notes = apply_names(["intro.mp3", "intro.mp3", "intro.mp3"], 3, "song", [0, 1000, 2000], [1000, 2000, 3000])
    assert names == ["intro.mp3", "intro_2.mp3", "intro_3.mp3"]
    assert len(notes) == 2


def test_unsafe_names_are_repaired_and_reported():
    names, notes = apply_names(["in/tro.mp3"], 1, "song", [0], [1000])
    assert names == ["intro.mp3"]
    assert "-> 'intro.mp3'" in notes[0]


def test_empty_name_falls_back_to_the_default():
    names, notes = apply_names(["   "], 1, "song", [0], [1000])
    assert names == ["song_part01_00-00-00.000_00-00-01.000.mp3"]