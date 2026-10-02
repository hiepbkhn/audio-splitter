"""Gradio UI for the audio splitter."""

from __future__ import annotations

from pathlib import Path

import gradio as gr

from splitter.errors import SplitError
from splitter.probe import ensure_ffmpeg_available
from splitter.split import SplitOptions, SplitResult, split_audio
from splitter.timeparse import format_clock

SPLIT_POINTS_PLACEHOLDER = "00:05:00\n00:12:30\n00:30:00"
NAMES_PLACEHOLDER = "intro.mp3\nverse.mp3\nchorus.mp3\noutro.mp3"


def split_clicked(
    audio_path: str | None,
    points_text: str,
    names_text: str,
    stream_copy: bool,
    keep_temp: bool,
) -> tuple[str, list[str], str, str | None]:
    """Run one split and render the outcome for the four output components."""
    try:
        result = split_audio(
            Path(audio_path) if audio_path else None,
            points_text,
            names_text,
            SplitOptions(stream_copy=bool(stream_copy), keep_temp=bool(keep_temp)),
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


def build_demo() -> gr.Blocks:
    """Assemble the Blocks layout described in the spec."""
    with gr.Blocks(title="Audio Splitter") as demo:
        gr.Markdown("# Audio Splitter\nUpload one MP3, enter the times to split at, and get the segments back.")

        source = gr.Audio(label="Source MP3", type="filepath")
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
            info="One .mp3 name per segment, in order. Leave empty for indexed names.",
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

        split_button.click(
            fn=split_clicked,
            inputs=[source, points, names, stream_copy, keep_temp],
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