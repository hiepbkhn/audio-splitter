"""Gradio UI for the audio splitter."""

from __future__ import annotations

from pathlib import Path

import gradio as gr

from splitter.errors import SplitError
from splitter.probe import ensure_ffmpeg_available
from splitter.split import SplitOptions, SplitResult, split_audio
from splitter.timeparse import format_clock, parse_timed_names

SPLIT_POINTS_PLACEHOLDER = "00:05:00\n00:12:30\n00:30:00"
NAMES_PLACEHOLDER = "intro.mp3\nverse.mp3\nchorus.mp3\noutro.mp3"
PAIRS_PLACEHOLDER = (
    "00:00 Đàn Gà Trong Sân\n"
    "03:12 Con Cò Bé Bé\n"
    "06:18 Chị Ong Nâu Và Em Bé"
)

# Mode identifiers. These are strings rather than ints because Gradio's Radio round-trips
# its value through JSON, where a plain int is ambiguous with a component index; a string
# keeps "mode 1" meaning exactly one thing on both sides of the wire.
MODE_POINTS = "points"
MODE_POINTS_AND_NAMES = "points_and_names"
MODE_TIMED_NAMES = "timed_names"

MODE_CHOICES = [
    ("Time points only", MODE_POINTS),
    ("Time points + separate names", MODE_POINTS_AND_NAMES),
    ("Time + name per line", MODE_TIMED_NAMES),
]


def split_clicked(
    audio_path: str | None,
    points_text: str,
    names_text: str,
    stream_copy: bool,
    keep_temp: bool,
    mode: str = MODE_POINTS_AND_NAMES,
    pairs_text: str = "",
) -> tuple[str, list[str], str, str | None]:
    """Run one split and render the outcome for the four output components."""
    points_ms: list[int] | None = None
    names: list[str] | None = None

    try:
        if mode == MODE_TIMED_NAMES:
            points_ms, names = parse_timed_names(pairs_text or "")
        result = split_audio(
            Path(audio_path) if audio_path else None,
            points_text,
            names_text,
            SplitOptions(stream_copy=bool(stream_copy), keep_temp=bool(keep_temp)),
            points_ms=points_ms,
            names=names,
        )
    except SplitError as error:
        return _render_error(error), [], "", None
    except Exception as error:  # noqa: BLE001 - the UI must never show a traceback
        return _render_error(
            SplitError("E_FFMPEG_FAILED", f"Split failed unexpectedly: {error}")
        ), [], "", None

    return (
        _render_summary(result),
        [str(path) for path in result.paths],
        _render_status(result, keep_temp),
        str(result.make_archive()),
    )


def _render_summary(result: SplitResult) -> str:
    lines = [f"**{len(result.segments)} segments** from {format_clock(result.info.duration_ms)} of audio"]
    for segment, name in zip(result.segments, result.names):
        lines.append(
            f"| {segment.index} | {format_clock(segment.start_ms)} | "
            f"{format_clock(segment.end_ms)} | {format_clock(segment.duration_ms)} | `{name}` |"
        )
    table = "\n".join(lines)
    if result.notes:
        notes = "\n".join(f"- {note}" for note in result.notes)
        table += f"\n\n**Adjusted names**\n{notes}"
    return table


def _render_status(result: SplitResult, keep_temp: bool) -> str:
    message = "Done."
    if keep_temp:
        message += f" Segments kept in `{result.temp_dir}`."
    return message


def _render_error(error: SplitError) -> str:
    lines = [f"`{error.code}`", "", error.message]
    if error.detail:
        lines += ["", f"```\n{error.detail}\n```"]
    return "\n".join(lines)


def mode_changed(selected: str) -> tuple[dict, dict, dict]:
    """Show only the inputs the selected mode actually reads.

    Each mode leaves one of the three textboxes unused, so hiding the rest keeps a pasted
    value in one box from silently being ignored.
    """
    paired = selected == MODE_TIMED_NAMES
    named = selected == MODE_POINTS_AND_NAMES
    return (
        gr.update(visible=not paired),
        gr.update(visible=named),
        gr.update(visible=paired),
    )


def build_demo() -> gr.Blocks:
    """Assemble the Blocks layout described in the spec."""
    with gr.Blocks(title="Audio Splitter") as demo:
        gr.Markdown("# Audio Splitter\nUpload one MP3, enter the times to split at, and get the segments back.")

        source = gr.Audio(label="Source MP3", type="filepath")
        mode = gr.Radio(
            choices=MODE_CHOICES,
            value=MODE_POINTS_AND_NAMES,
            label="Input format",
            info="Pick how to describe the segments.",
        )
        points = gr.Textbox(
            label="Split points",
            lines=8,
            placeholder=SPLIT_POINTS_PLACEHOLDER,
            info="One per line: HH:MM:SS.mmm, MM:SS, or bare seconds. Blank lines and # comments are ignored.",
        )
        names = gr.Textbox(
            label="Output names (optional)",
            lines=6,
            placeholder=NAMES_PLACEHOLDER,
            info="One name per segment, in order. '.mp3' is added for you. Leave empty for indexed names.",
        )
        pairs = gr.Textbox(
            label="Times and names",
            lines=10,
            placeholder=PAIRS_PLACEHOLDER,
            info="One 'start time + segment name' per line, e.g. '03:12 Con Cò Bé Bé'.",
        )
        with gr.Accordion("Advanced", open=False):
            stream_copy = gr.Checkbox(
                label="Stream copy (fast, cuts on frame boundaries only)",
                info="Near-instant, but each segment may lose up to one frame at its start.",
            )
            keep_temp = gr.Checkbox(
                label="Keep temporary files",
                info="Leave the segments on disk instead of relying on the temp cleaner.",
            )

        split_button = gr.Button("Split", variant="primary")
        summary = gr.Markdown()
        status = gr.Markdown()
        segments = gr.File(label="Segments", file_count="multiple")
        archive = gr.File(label="All segments (zip)")

        mode.change(
            fn=mode_changed,
            inputs=[mode],
            outputs=[points, names, pairs],
        )

        split_button.click(
            fn=split_clicked,
            inputs=[source, points, names, stream_copy, keep_temp, mode, pairs],
            outputs=[summary, segments, status, archive],
        )

        gr.Examples(
            examples=[
                ["00:05:00\n00:12:30\n00:30:00", ""],
                ["02:03\n83.25\n120", "intro.mp3\nverse.mp3\nchorus.mp3\noutro.mp3"],
                ["# cut on the chorus\n00:01:00", ""],
            ],
            inputs=[points, names],
            label="Split point formats",
        )
    return demo


demo = build_demo()

if __name__ == "__main__":
    ensure_ffmpeg_available()
    demo.launch(show_error=True)