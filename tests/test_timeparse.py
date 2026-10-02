import pytest

from splitter.errors import SplitError
from splitter.timeparse import format_clock, format_ms, iter_entries, parse_split_points, parse_time


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00:00:01", 1000),
        ("01:02:03", 3_723_000),
        ("02:03", 123_000),
        ("90:00", 5_400_000),  # MM:SS minutes are unbounded
        ("00:12:30.500", 750_500),
        ("02:03.250", 123_250),
        ("83.25", 83_250),
        ("83", 83_000),
        ("1:02:03.25", 3_723_250),
        ("  00:00:02  ", 2000),
        ("00:12:30.5", 750_500),
        ("00:12:30.55", 750_550),  # truncated, not rounded, to milliseconds
    ],
)
def test_parse_time_accepts_every_documented_form(raw, expected):
    assert parse_time(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["00:70:00", "00:00:60", "5m", "90s", "1e3", "-5", "abc", "", "  ", "1:2:3:4", "00:00:01.5.5"],
)
def test_parse_time_rejects_malformed_input(raw):
    with pytest.raises(SplitError) as exc:
        parse_time(raw)
    assert exc.value.code == "E_TIME_FORMAT"


def test_fractional_digits_beyond_three_are_truncated_not_rounded():
    assert parse_time("00:00:01.9999") == 1999


def test_iter_entries_drops_blanks_and_comments_and_renumbers():
    text = "\n".join(["", "  ", "# a comment", "00:01:00", "00:02:00, 00:03:00", "  # indented comment", "00:04:00;"])
    assert iter_entries(text) == [
        (1, "00:01:00"),
        (2, "00:02:00"),
        (3, "00:03:00"),
        (4, "00:04:00"),
    ]


def test_no_splits_is_reported_when_everything_is_blank_or_commented():
    with pytest.raises(SplitError) as exc:
        parse_split_points("\n\n# nothing here\n   \n")
    assert exc.value.code == "E_NO_SPLITS"


def test_split_points_are_returned_in_milliseconds():
    assert parse_split_points("00:01:00\n00:02:00") == [60_000, 120_000]


def test_format_helpers():
    assert format_ms(3_723_456) == "01-02-03.456"
    assert format_clock(3_723_456) == "01:02:03.456"
    assert format_clock(0) == "00:00:00.000"


def test_multiple_format_errors_are_reported_together():
    with pytest.raises(SplitError) as exc:
        parse_split_points("5m\nnope\n1e3")
    assert exc.value.code == "E_TIME_FORMAT"
    assert len(exc.value.message.splitlines()) == 3
    assert "Split point 1" in exc.value.message
    assert "Split point 3" in exc.value.message


def test_zero_is_rejected_as_a_split_point():
    with pytest.raises(SplitError) as exc:
        parse_split_points("00:00:00\n00:01:00")
    assert exc.value.code == "E_TIME_RANGE"


def test_out_of_order_points_are_rejected_against_their_predecessor():
    with pytest.raises(SplitError) as exc:
        parse_split_points("00:02:00\n00:01:00")
    assert exc.value.code == "E_TIME_ORDER"
    assert "00:02:00" in exc.value.message


def test_equal_consecutive_points_are_rejected():
    with pytest.raises(SplitError) as exc:
        parse_split_points("00:01:00\n00:01:00")
    assert exc.value.code == "E_TIME_ORDER"


def test_more_than_ninety_nine_points_is_rejected():
    text = "\n".join(str(i) for i in range(1, 101))
    with pytest.raises(SplitError) as exc:
        parse_split_points(text)
    assert exc.value.code == "E_SPLIT_COUNT"
    assert "100" in exc.value.message


def test_ninety_nine_points_is_allowed():
    text = "\n".join(str(i) for i in range(1, 100))
    assert len(parse_split_points(text)) == 99