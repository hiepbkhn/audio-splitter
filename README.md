# Audio Splitter

Gradio app that splits an MP3 at user-supplied time points and returns the segments as downloads.

## Requirements

- Python >= 3.10
- `ffmpeg` and `ffprobe` on `PATH` (system binaries, **not** managed by `uv`)

## Setup

```sh
uv sync
```

## Run

```sh
uv run python app.py
```

Then open the local URL Gradio prints.

## Usage

Upload one MP3, enter split points one per line, and optionally one output name per segment.

**Split points** are absolute timestamps measured from the start of the audio, and must
strictly increase. `n` points produce `n + 1` segments; the last one always runs to the end.
Blank lines and lines starting with `#` are ignored, and `,` or `;` may separate several
entries on one line.

| Format | Example |
| --- | --- |
| `HH:MM:SS` | `01:02:03` |
| `MM:SS` | `02:03` (minutes may exceed 59) |
| with milliseconds | `00:12:30.500`, `83.25` |
| bare seconds | `90` |

Unit suffixes are rejected, so `5m` is an error rather than a silent five minutes.
Maximum 99 split points.

**Output names** are optional. Leave them empty and each segment is named
`{stem}_part{NN}_{start}_{end}.mp3`, indexed by its time range. Supplying one `.mp3` name
per segment uses those instead; unsafe characters are stripped and duplicates get a numeric
suffix, and every such change is reported in the result panel rather than applied silently.

**Advanced** exposes two switches:

- *Stream copy* reuses the compressed frames instead of re-encoding — near-instant, but each
  segment may lose up to one MP3 frame (~26 ms) at its start. Off by default.
- *Keep temporary files* leaves the output directory on disk, including after a failure, for
  debugging. Off by default.

## Tests

```sh
uv run pytest -m "not ffmpeg"   # fast; pure logic, no ffmpeg needed
uv run pytest                   # full; includes ffmpeg integration tests
```

See `spec.md` for the specification and `plan.md` for the implementation plan.