"""Parsing and validation of user-supplied split points."""

from __future__ import annotations

import re

from .errors import SplitError, fail

MAX_SPLIT_POINTS = 99

# HH:MM:SS(.mmm) with optional leading hours; MM:SS(.mmm) is the same pattern without them.
_TIME_RE = re.compile(
    r"^(?:(?P<h>\d{1,3}):)?(?P<m>\d{1,3}):(?P<s>\d{1,2})(?:\.(?P<f>\d+))?$"
)
# bare seconds, e.g. 83 or 83.25
_SECONDS_RE = re.compile(r"^(?P<s>\d+)(?:\.(?P<f>\d+))?$")


def _fraction_ms(fraction: str | None) -> int:
    """Interpret a fractional-second string as milliseconds, truncating beyond 3 digits."""
    if not fraction:
        return 0
    return int(fraction[:3].ljust(3, "0"))


def parse_time(raw: str) -> int:
    """Parse one time entry into milliseconds.

    Raises SplitError with code E_TIME_FORMAT; the caller supplies the entry index.
    """
    text = raw.strip()

    match = _TIME_RE.match(text)
    if match:
        seconds = int(match["s"])
        if seconds > 59:
            raise SplitError("E_TIME_FORMAT", f"{raw!r} is not a time.")
        hours = int(match["h"] or 0)
        minutes = int(match["m"])
        # When an hours field is written out the minute field must stay below 60, so
        # "00:70:00" is rejected. In MM:SS form there is no hours field and minutes are
        # unbounded, so "90:00" reads as ninety minutes.
        if match["h"] is not None and minutes > 59:
            raise SplitError("E_TIME_FORMAT", f"{raw!r} is not a time.")
        return ((hours * 60 + minutes) * 60 + seconds) * 1000 + _fraction_ms(match["f"])

    match = _SECONDS_RE.match(text)
    if match:
        return int(match["s"]) * 1000 + _fraction_ms(match["f"])

    raise SplitError("E_TIME_FORMAT", f"{raw!r} is not a time.")


def iter_entries(text: str) -> list[tuple[int, str]]:
    """Split raw textbox text into 1-based-indexed entries, dropping blanks and comments."""
    entries: list[tuple[int, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for piece in stripped.replace(";", ",").split(","):
            piece = piece.strip()
            if piece:
                entries.append((len(entries) + 1, piece))
    return entries


def parse_split_points(text: str) -> list[int]:
    """Parse and validate split point text, reporting every problem found."""
    entries = iter_entries(text)
    if not entries:
        raise fail("E_NO_SPLITS")

    errors: list[SplitError] = []
    values: list[int] = []

    for index, raw in entries:
        try:
            values.append(parse_time(raw))
        except SplitError:
            errors.append(fail("E_TIME_FORMAT", index=index, raw=raw))

    if errors:
        raise _combined(errors)

    if len(values) > MAX_SPLIT_POINTS:
        errors.append(fail("E_SPLIT_COUNT", count=len(values), limit=MAX_SPLIT_POINTS))

    for position, value in enumerate(values):
        index = position + 1
        if value <= 0:
            errors.append(fail("E_TIME_RANGE", index=index, value=format_clock(value)))
        elif position > 0 and value <= values[position - 1]:
            errors.append(
                fail(
                    "E_TIME_ORDER",
                    index=index,
                    value=format_clock(value),
                    previous_index=position,
                    previous_value=format_clock(values[position - 1]),
                )
            )

    if errors:
        raise _combined(errors)

    return values


def _combined(errors: list[SplitError]) -> SplitError:
    """Fold several validation failures into one SplitError carrying every message."""
    return SplitError(
        errors[0].code,
        "\n".join(error.message for error in errors),
        index=errors[0].index,
    )


def format_ms(ms: int) -> str:
    """Render milliseconds as HH-MM-SS.mmm, for use inside filenames."""
    return _format(ms, sep="-")


def format_clock(ms: int) -> str:
    """Render milliseconds as HH:MM:SS.mmm, for display and error messages."""
    return _format(ms, sep=":")


def _format(ms: int, sep: str) -> str:
    ms = max(ms, 0)
    total_seconds, millis = divmod(ms, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}{sep}{minutes:02d}{sep}{seconds:02d}.{millis:03d}"