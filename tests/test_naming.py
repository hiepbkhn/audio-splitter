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


def test_apply_names_appends_mp3_to_a_name_written_without_an_extension():
    """Spec 7.3: '.mp3' is appended when the user did not include one."""
    names, notes = apply_names(["intro", "verse"], 2, "song", [0, 1000], [1000, 2000])
    assert names == ["intro.mp3", "verse.mp3"]
    # Appending the documented extension is not a repair worth reporting.
    assert notes == []


def test_apply_names_rejects_a_non_mp3_extension():
    with pytest.raises(SplitError) as exc:
        apply_names(["intro.wav", "verse.mp3"], 2, "song", [0, 1000], [1000, 2000])
    assert exc.value.code == "E_NAME_EXTENSION"


def test_apply_names_appends_mp3_to_non_ascii_names():
    names, _ = apply_names(["Đàn Gà Trong Sân"], 1, "song", [0], [1000])
    assert names == ["Đàn Gà Trong Sân.mp3"]


def test_apply_names_accepts_a_name_that_is_already_mp3():
    names, notes = apply_names(["intro.mp3"], 1, "song", [0], [1000])
    assert names == ["intro.mp3"]
    assert notes == []


def test_apply_names_accepts_an_uppercase_mp3_extension():
    names, _ = apply_names(["intro.MP3"], 1, "song", [0], [1000])
    assert names == ["intro.MP3"]


def test_apply_names_rejects_a_forbidden_extension_hidden_behind_a_separator():
    """'in/tro.wav' must not slip through just because sanitising strips the '/'."""
    with pytest.raises(SplitError) as exc:
        apply_names(["in/tro.wav"], 1, "song", [0], [1000])
    assert exc.value.code == "E_NAME_EXTENSION"


def test_apply_names_keeps_a_dot_that_is_not_an_extension():
    names, _ = apply_names(["vol. one"], 1, "song", [0], [1000])
    assert names == ["vol. one.mp3"]


@pytest.mark.parametrize("raw", [".mp3", "...", "/", ".."])
def test_a_name_that_sanitises_to_nothing_falls_back_to_the_default(raw):
    """Appending '.mp3' must not leave an extensionless file behind."""
    names, notes = apply_names([raw], 1, "song", [0], [1000])
    assert names == ["song_part01_00-00-00.000_00-00-01.000.mp3"]
    assert notes, "falling back to the default name is a change the user must see"


def test_every_produced_name_is_an_mp3():
    """The contract: whatever the user types, the output is an MP3 or an error."""
    raw = [".mp3", "bare", "with.mp3", "in/tro", "vol. one", "Con", "#1", "Đàn Gà"]
    names, _ = apply_names(raw, len(raw), "song", [0] * len(raw), [1000] * len(raw))
    assert all(name.lower().endswith(".mp3") for name in names)


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