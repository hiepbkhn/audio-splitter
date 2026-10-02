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

Upload one MP3, then pick how to describe the segments. Three input formats are available:

- **Time points only** — one timestamp per line, optional names left blank.
- **Time points + separate names** — timestamps in one box, names in another.
- **Time + name per line** — one `start time  segment name` per line, e.g. a chapter list.

### Time points

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
`{stem}_part{NN}_{start}_{end}.mp3`, indexed by its time range. Supplying one name per
segment uses those instead; `.mp3` is appended when you leave the extension off, unsafe
characters are stripped and duplicates get a numeric suffix, and every such change is
reported in the result panel rather than applied silently.

### Time + name per line

For a chapter-style list, paste one segment start time and its name per line:

```
00:00 Đàn Gà Trong Sân
03:12 Con Cò Bé Bé
06:18 Chị Ong Nâu Và Em Bé
28:49 Bụi Phấn
```

A space or a tab separates the time from the name, so a list pasted from a table works as
is. Each line names the segment **starting** at that time, so `n` lines produce `n` segments
and the last one runs to the end of the audio.

The first line's time is only a label: the audio always begins at zero, so it is never a cut.
That is what lets the list start with the natural `00:00` marker — in the time-points modes
a `00:00` entry is rejected, since it would produce an empty first segment. The remaining
times must still strictly increase.

Names may contain commas, semicolons and spaces; they are not split on separators the way the
time-points boxes are. Every line needs a name — a bare timestamp is an error.

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