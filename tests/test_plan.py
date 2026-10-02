import pytest

from splitter.errors import SplitError
from splitter.plan import build_plan, validate_points_against_duration


def test_no_points_yields_one_segment_covering_the_whole_source():
    segments = build_plan(5000, [])
    assert [(s.start_ms, s.end_ms) for s in segments] == [(0, 5000)]
    assert segments[0].index == 1


def test_single_point_yields_two_segments():
    segments = build_plan(10_000, [3_000])
    assert [(s.start_ms, s.end_ms) for s in segments] == [(0, 3_000), (3_000, 10_000)]
    assert [s.duration_ms for s in segments] == [3_000, 7_000]


def test_three_points_yield_four_segments():
    segments = build_plan(600_000, [300_000, 750_000, 1_800_000])
    assert [(s.start_ms, s.end_ms) for s in segments] == [
        (0, 300_000),
        (300_000, 750_000),
        (750_000, 1_800_000),
        (1_800_000, 600_000),
    ]


def test_last_segment_runs_to_the_end():
    segments = build_plan(10_000, [9_950])
    assert segments[-1].start_ms == 9_950
    assert segments[-1].end_ms == 10_000


def test_segment_durations_sum_to_the_source_duration():
    segments = build_plan(612_345, [1_000, 61_000, 333_333])
    assert sum(s.duration_ms for s in segments) == 612_345


def test_segments_are_half_open_so_no_boundary_is_shared():
    segments = build_plan(10_000, [3_000, 6_000])
    for earlier, later in zip(segments, segments[1:]):
        assert earlier.end_ms == later.start_ms


def test_segment_index_is_one_based_and_sequential():
    segments = build_plan(10_000, [3_000, 6_000])
    assert [s.index for s in segments] == [1, 2, 3]


def test_point_at_or_past_the_end_is_rejected():
    with pytest.raises(SplitError) as exc:
        validate_points_against_duration([5_000, 10_000], 10_000)
    assert exc.value.code == "E_TIME_PAST_END"


def test_all_out_of_range_points_are_reported_together():
    with pytest.raises(SplitError) as exc:
        validate_points_against_duration([20_000, 30_000], 10_000)
    assert len(exc.value.message.splitlines()) == 2


def test_point_just_before_the_end_is_allowed():
    validate_points_against_duration([9_950], 10_000)  # must not raise