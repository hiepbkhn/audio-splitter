"""Derivation of the segment plan from a duration and a list of split points."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import SplitError, fail
from .timeparse import format_clock


@dataclass(frozen=True)
class Segment:
    """A half-open time range [start_ms, end_ms) of the source audio."""

    index: int
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def build_plan(duration_ms: int, points_ms: list[int]) -> list[Segment]:
    """Split [0, duration_ms] at each point, producing len(points) + 1 segments."""
    boundaries = [0, *points_ms, duration_ms]
    return [
        Segment(position + 1, boundaries[position], boundaries[position + 1])
        for position in range(len(boundaries) - 1)
    ]


def validate_points_against_duration(points_ms: list[int], duration_ms: int) -> None:
    """Reject points at or past the end of the audio, reporting all of them."""
    errors = [
        fail(
            "E_TIME_PAST_END",
            index=position + 1,
            value=format_clock(value),
            duration=format_clock(duration_ms),
        )
        for position, value in enumerate(points_ms)
        if value >= duration_ms
    ]
    if errors:
        raise SplitError(
            errors[0].code, "\n".join(error.message for error in errors)
        )