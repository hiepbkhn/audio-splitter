"""Error type and message templates for the splitter."""

from __future__ import annotations

STDERR_TAIL = 500


def stderr_tail(text: str) -> str:
    """Trim ffmpeg's stderr to its last few characters so errors stay readable."""
    text = (text or "").strip()
    return text[-STDERR_TAIL:] if len(text) > STDERR_TAIL else text


class SplitError(Exception):
    """A validation or encoding failure that can be shown to the user verbatim."""

    def __init__(
        self,
        code: str,
        message: str,
        index: int | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.index = index
        self.detail = detail

    def __str__(self) -> str:
        return self.message


CODES = frozenset(
    {
        "E_AUDIO_COUNT",
        "E_AUDIO_FORMAT",
        "E_AUDIO_EMPTY",
        "E_PROBE_FAILED",
        "E_NO_SPLITS",
        "E_SPLIT_COUNT",
        "E_TIME_FORMAT",
        "E_TIME_RANGE",
        "E_TIME_ORDER",
        "E_TIME_PAST_END",
        "E_NAME_COUNT",
        "E_NAME_EXTENSION",
        "E_FFMPEG_MISSING",
        "E_FFMPEG_FAILED",
    }
)

USER_MESSAGE: dict[str, str] = {
    "E_AUDIO_COUNT": "Upload exactly one MP3 file; got {count}.",
    "E_AUDIO_FORMAT": "'{name}' is not an MP3 file (detected {actual}).",
    "E_AUDIO_EMPTY": "'{name}' is empty.",
    "E_PROBE_FAILED": "Could not read '{name}'.",
    "E_NO_SPLITS": "Enter at least one split point.",
    "E_SPLIT_COUNT": "{count} split points exceeds the maximum of {limit}.",
    "E_TIME_FORMAT": (
        "Split point {index} ('{raw}') is not a time. "
        "Use HH:MM:SS.mmm, MM:SS, or seconds."
    ),
    "E_TIME_RANGE": "Split point {index} ({value}) must be greater than 00:00:00.",
    "E_TIME_ORDER": (
        "Split point {index} ({value}) is not after split point {previous_index} "
        "({previous_value})."
    ),
    "E_TIME_PAST_END": (
        "Split point {index} ({value}) is at or past the end of the audio ({duration})."
    ),
    "E_NAME_COUNT": "Expected {expected} output names for {expected} segments; got {got}.",
    "E_NAME_EXTENSION": "Output name {index} ('{raw}') must end in .mp3, or have no extension.",
    "E_FFMPEG_MISSING": "ffmpeg is required but was not found on PATH.",
    "E_FFMPEG_FAILED": "Failed to encode segment {index} ({start}-{end}).",
}


def fail(code: str, **fields: object) -> SplitError:
    """Build a SplitError with the canonical message for `code` filled in."""
    return SplitError(code, USER_MESSAGE[code].format(**fields))