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


def parse_timed_names(text: str) -> tuple[list[int], list[str]]:
    """Parse "start time + segment name" lines into split points and output names.

    Each line is a time followed by the name of the segment starting there, separated by a
    space or a tab, as in::

        00:00 Đàn Gà Trong Sân
        03:12 Con Cò Bé Bé

    Because the times mark where each *segment starts*, the first line's time is
    informational only — the audio always begins at zero, so it cannot be a cut. Only the
    remaining lines contribute split points, which is what lets a list begin with the
    natural ``00:00`` marker instead of tripping the "a point must be greater than zero"
    rule that the separate-points mode enforces.

    ``n`` lines therefore produce ``n`` named segments, the last running to the end of the
    audio. Every line must carry a name: a bare time is rejected rather than accepted as an
    unnamed segment, because in this mode the names are the point of the list.

    Returns the split points and one raw name per segment, in order. Sanitising and
    de-duplicating the names is `apply_names`' job.
    """
    rows = _timed_name_rows(text or "")
    if not rows:
        raise fail("E_NO_SPLITS")

    errors: list[SplitError] = []
    starts: list[int] = []
    names: list[str] = []

    for index, (_, raw_time, name) in enumerate(rows, start=1):
        if not name:
            errors.append(fail("E_TIME_FORMAT", index=index, raw=raw_time))
            continue
        try:
            starts.append(parse_time(raw_time))
        except SplitError:
            errors.append(fail("E_TIME_FORMAT", index=index, raw=raw_time))
            continue
        names.append(name)

    if errors:
        raise _combined(errors)

    # The first row starts the audio rather than cutting it, so its time is dropped. Any
    # first-row value is accepted, since listing from a chapter that does not begin the
    # recording is a normal thing to do and the value is only a label in this mode.
    points = starts[1:]

    if len(points) > MAX_SPLIT_POINTS:
        errors.append(fail("E_SPLIT_COUNT", count=len(points), limit=MAX_SPLIT_POINTS))

    for position, value in enumerate(points):
        if value <= 0:
            # Unreachable via the ordering check below, since a zero is never strictly
            # greater than its predecessor. Checked anyway so a repeated "00:00" is
            # reported as the out-of-range value it is, matching parse_split_points.
            errors.append(
                fail("E_TIME_RANGE", index=position + 2, value=format_clock(value))
            )
        elif value <= starts[position]:
            errors.append(
                fail(
                    "E_TIME_ORDER",
                    index=position + 2,
                    value=format_clock(value),
                    previous_index=position + 1,
                    previous_value=format_clock(starts[position]),
                )
            )

    if errors:
        raise _combined(errors)

    return points, names


def _timed_name_rows(text: str) -> list[tuple[int, str, str]]:
    """Split paired lines into (line number, time, name), dropping blanks and comments.

    The time is taken as the first whitespace-delimited token, so a list aligned with tabs
    or padded columns parses the same as one separated by single spaces.
    """
    rows: list[tuple[int, str, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(maxsplit=1)
        rows.append((number, parts[0], parts[1].strip() if len(parts) > 1 else ""))
    return rows


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