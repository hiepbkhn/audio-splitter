"""Sanitisation and default generation of output filenames."""

from __future__ import annotations

import re

from .errors import SplitError, fail
from .timeparse import format_ms

MAX_NAME_BYTES = 255

_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
_ILLEGAL_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


def sanitize_name(raw: str, fallback: str) -> str:
    """Turn user input into a safe filename, falling back when nothing survives."""
    name = _ILLEGAL_CHARS_RE.sub("", raw)
    name = name.replace("..", "").strip(" .\t\r\n")
    if not name:
        return fallback
    if name.split(".")[0].upper() in _RESERVED_NAMES:
        name = f"_{name}"
    return _truncate_bytes(name, MAX_NAME_BYTES)


def _truncate_bytes(name: str, limit: int) -> str:
    """Shorten `name` so its UTF-8 encoding fits in `limit` bytes, never splitting a character."""
    encoded = name.encode("utf-8")
    if len(encoded) <= limit:
        return name
    return encoded[:limit].decode("utf-8", errors="ignore")


def default_name(stem: str, index: int, start_ms: int, end_ms: int) -> str:
    """Build the indexed default filename for a segment."""
    return f"{sanitize_name(stem, 'audio')}_part{index:02d}_{format_ms(start_ms)}_{format_ms(end_ms)}.mp3"


def apply_names(
    raw_names: list[str],
    count: int,
    stem: str,
    starts: list[int],
    ends: list[int],
) -> tuple[list[str], list[str]]:
    """Validate, sanitise and de-duplicate user-supplied names.

    Returns the final names in segment order plus notes describing any repair made, so the
    UI can tell the user a name changed instead of silently renaming.
    """
    if len(raw_names) != count:
        raise fail("E_NAME_COUNT", expected=count, got=len(raw_names))

    names: list[str] = []
    notes: list[str] = []
    errors: list[SplitError] = []
    used: dict[str, int] = {}

    for position, raw in enumerate(raw_names):
        index = position + 1
        fallback = default_name(stem, index, starts[position], ends[position])
        # A blank entry is a "use the default" signal, not a missing extension.
        name = fallback if not raw.strip() else sanitize_name(raw.strip(), fallback)

        if name != raw.strip():
            notes.append(f"Output name {index}: '{raw.strip()}' -> '{name}'.")
        elif not name.lower().endswith(".mp3"):
            errors.append(fail("E_NAME_EXTENSION", index=index, raw=raw.strip()))
            continue

        seen = used.get(name.lower(), 0) + 1
        used[name.lower()] = seen
        if seen > 1:
            name = _with_suffix(name, seen)
            notes.append(f"Output name {index}: duplicate name, saved as '{name}'.")

        names.append(name)

    if errors:
        raise SplitError(errors[0].code, "\n".join(e.message for e in errors))

    return names, notes


def _with_suffix(name: str, seen: int) -> str:
    stem, dot, extension = name.rpartition(".")
    if not dot:
        return f"{name}_{seen}"
    return f"{stem}_{seen}{dot}{extension}"