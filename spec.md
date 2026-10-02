# Audio Splitter — Specification

Gradio app that splits an uploaded MP3 at user-supplied time points and returns the resulting files.

---

## 1. Overview

A single-page Gradio application takes three inputs:

1. one MP3 audio file,
2. an ordered list of time points to split at,
3. an optional list of output file names.

It writes one audio file per resulting segment and returns them to the browser as downloads. When no output names are given, segments are named after their source file and indexed by the time range they cover.

## 2. Goals

- Split an MP3 at arbitrary time points, sample-accurate to within one MP3 frame (~26 ms at 44.1 kHz).
- Return every segment as a downloadable file from one interaction.
- Fail loudly and specifically: the user always learns which input was wrong and what was expected.
- Never mutate the uploaded source file.
- Work with no persistent server state — one request is self-contained.

## 3. Non-goals

- Formats other than MP3 (M4A, WAV, FLAC, OGG) — see §14.
- Overlapping, repeating, or cross-fading segments.
- Re-joining segments, trimming, fades, loudness normalisation, or any other DSP.
- Batch processing of many files in one run.
- Persisting a history of splits or user preferences beyond the browser session.

## 4. Terminology

| Term | Meaning |
| --- | --- |
| Source | The uploaded MP3 file. Never written to. |
| Split point | A timestamp marking where one segment ends and the next begins. |
| Segment | The audio between two consecutive split points; the first starts at `00:00:00`, the last runs to end of source. |
| Plan | The ordered list of segments derived from the source duration and the split points. |
| Frame | One MP3 audio frame, the smallest unit the codec can cut on. |

With `n` split points the output always contains exactly `n + 1` segments.

## 5. User stories

- **US-1** — As a user, I upload a 40-minute MP3 and give split points `5:00`, `12:30`, `30:00`; I receive four files covering `[0, 5:00)`, `[5:00, 12:30)`, `[12:30, 30:00)`, `[30:00, end)`.
- **US-2** — As a user, I supply four names so I get `intro.mp3`, `verse.mp3`, `chorus.mp3`, `outro.mp3` instead of the default indexed names.
- **US-3** — As a user, I mistype a split point as `5:70`; I get an error naming the offending entry and telling me a minute value must be below 60.
- **US-4** — As a user, I hand back files that together play identically to the source, with no audible click at the boundaries beyond MP3 frame granularity.

## 6. Functional requirements

| ID | Requirement |
| --- | --- |
| FR-1 | Accept exactly one MP3 file per run. |
| FR-2 | Parse a list of split points into ordered milliseconds. |
| FR-3 | Reject split points that are unparseable, non-strictly increasing, non-positive, or at/after the source duration. |
| FR-4 | Accept an optional list of output names; when absent, generate names from the source stem and segment time range. |
| FR-5 | Require the name count to equal `n + 1` when names are provided. |
| FR-6 | Sanitise user-supplied names so the result is a safe, unique filename. |
| FR-7 | Encode each segment to MP3 via ffmpeg, preserving the source sample rate and channel count. |
| FR-8 | Write all segments into one temporary directory and return every file. |
| FR-9 | Surface every validation failure in one message, not one per run. |
| FR-10 | Leave the source file untouched and delete nothing the user owns. |

## 7. Input specification

### 7.1 Audio input

| Property | Rule |
| --- | --- |
| Formats | MP3 only (MIME `audio/mpeg`, or extension `.mp3`). |
| Count | Exactly one. A second file is a validation error (`E_AUDIO_COUNT`). |
| Container sniffing | Check magic bytes for `ID3` or an MPEG frame sync (`0xFF 0xEx/0xFx`) — do not trust the extension alone. |
| Empty file | Reject (`E_AUDIO_EMPTY`). |
| Duration | Read via `ffprobe`. Required, because the final segment's end is defined by it. |
| Unreadable / corrupt | Reject (`E_PROBE_FAILED`) with ffmpeg's stderr tail attached. |

### 7.2 Split points

**Encoding.** One entry per line in a Gradio `Textbox`. Blank lines and lines starting with `#` are ignored, so a pasted list with comments works. Entries are separated by newlines; commas and semicolons in a line are also treated as separators.

**Accepted formats**, per entry:

| Form | Example | Notes |
| --- | --- | --- |
| `HH:MM:SS` | `01:02:03` | Minutes must be below 60 when an hours field is present, so `00:70:00` is rejected. |
| `MM:SS` | `02:03` | Minutes may exceed 59 here, since no hours field is present. |
| `HH:MM:SS.mmm` | `00:12:30.500` | One or more fractional digits, right-padded or truncated to milliseconds. `.5` is 500 ms, `.55` is 550 ms, `.5555` truncates to 555 ms — digits beyond three are never rounded up. |
| `MM:SS.mmm` | `02:03.250` | |
| Bare seconds | `83.25` | Decimal point optional. |

No unit suffixes (`5m`, `90s`) are accepted — they are rejected rather than guessed at, so `5m` is an error and not a silent `5` minutes.

**Validation rules**, applied in this order and all collected before reporting:

| Rule | Error code |
| --- | --- |
| Every entry parses | `E_TIME_FORMAT` |
| At least one entry remains after stripping blanks/comments | `E_NO_SPLITS` |
| 1 ≤ count ≤ 99 | `E_SPLIT_COUNT` |
| Each value > 0 | `E_TIME_RANGE` |
| Strictly increasing | `E_TIME_ORDER` |
| Each value < source duration | `E_TIME_PAST_END` |

**Semantics.** Split points are absolute timestamps measured from the start of the source, not durations. `[5:00, 5:30]` means "cut at five minutes and at five minutes thirty" and yields three segments. A point equal to `0` is rejected: it would produce an empty first segment.

**Last segment.** The final segment always runs from the last split point to the end of the source. A trailing point near the duration (`duration − 0.05 s`) is legal and produces a very short final segment; ffmpeg encodes it rather than dropping it.

### 7.3 Output names

Optional `Textbox`, same line/blank/comment rules as split points.

- If empty or absent → default naming (§8.2).
- If present → exactly `n + 1` entries, else `E_NAME_COUNT`.
- Each name is used as a **base name**; a `.mp3` extension is appended if the user did not include one. A name with any other extension is rejected outright (`E_NAME_EXTENSION`) rather than silently producing an MP3 called `foo.wav`.
- A **blank** entry is a "use the default for this segment" signal, not a missing extension, so it falls back to §8.2 naming rather than erroring.
- Sanitisation (`E_NAME_UNSAFE` is not raised; unsafe input is repaired silently, because the user's intent is unambiguous):
  - path separators (`/`, `\`) and `..` are stripped — names are files in a temp dir, never paths,
  - control characters and `<>:"|?*` are removed,
  - leading/trailing whitespace and dots are trimmed (Windows rejects trailing dots),
  - Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`) get a `_` prefix,
  - empty result after cleaning falls back to the default name for that index,
  - the name is truncated so the full filename fits in 255 bytes on a UTF-8 filesystem.

- Duplicates are repaired by appending `_2`, `_3`, … before the extension (`intro.mp3`, `intro_2.mp3`). User-visible as a note, not an error.

## 8. Output specification

### 8.1 Plan derivation

Given duration `D` (ms) and split points `[p₁ … pₙ]`:

```
segments[0]  = (0,     p₁)
segments[i]  = (pᵢ,    pᵢ₊₁)   for 1 ≤ i < n
segments[n]  = (pₙ,    D)
```

Segment count is `n + 1`. Every segment is `[start, end)` — half-open, so adjacent segments never both contain the boundary instant.

### 8.2 Naming

**Default (no names supplied).** Segment `i` (1-based) of `stem` is named:

```
{stem}_part{i:02d}_{start}_{end}.mp3
```

where `start` and `end` are `HH-MM-SS.mmm`, joined by an underscore. Dots and dashes keep the name valid on every filesystem while remaining sortable and readable. Example, for the §5 US-1 split:

```
song_part01_00-00-00.000_00-05-00.000.mp3
song_part02_00-05-00.000_00-12-30.000.mp3
song_part03_00-12-30.000_00-30-00.000.mp3
song_part04_00-30-00.000_00-40-12.700.mp3
```

Parts are zero-padded to two digits so lexical order matches playback order; beyond 99 segments the field widens (`part100`), which the 99-split-point cap in §7.2 prevents.

**Supplied names.** Position `i` uses entry `i`, after sanitisation. Sanitisation can append a numeric suffix for duplicates, so the returned filenames may not be character-identical to what was typed; the Gradio file list shows the actual names used.

### 8.3 Delivery

- All segments are written to a single temporary directory per run.
- The Gradio `File` component uses `file_count="multiple"` and returns the paths in plan order.
- The source's own directory and the temp directory are unrelated; nothing is written next to the upload.
- A **failed** run removes its temp directory, so a partial file set is never left on disk. Ticking "Keep temporary files" suppresses that cleanup, which is what makes the checkbox useful for debugging a failure.

### 8.4 Encoding

```
ffmpeg -nostdin -hide_banner -loglevel error -y \
       -ss {start_s} -i {source} -t {duration_s} \
       -vn -c:a libmp3lame -q:a 2 \
       -ar {source_rate} -ac {source_channels} \
       {output}
```

- `-ss` before `-i` seeks, then ffmpeg decodes from the preceding keyframe and discards the samples before `start`, so cuts are frame-accurate rather than keyframe-accurate.
- `-q:a 2` is libmp3lame VBR (~190 kbps), a good default for split segments where source bitrate is often unknown or high.
- Sample rate and channel count are probed from the source and preserved, so segments concatenate without a resample in the listener's player.
- Video streams are dropped (`-vn`); MP3 has none, but containers renamed to `.mp3` sometimes do.

**Advanced mode (optional, off by default).** An "Advanced" expander exposes `-c copy` (stream copy, near-instant, but cuts only on frame boundaries *and* the first ~26 ms of each segment may be a partial frame). Off by default because silent truncation is worse than a slower encode.

## 9. Validation and error handling

Every failure is a `SplitError` carrying a code, a human-readable message, and the offending 1-based entry index where one applies. The UI renders these as a Gradio `Error` string, one line per problem.

| Code | Trigger | Message shape |
| --- | --- | --- |
| `E_AUDIO_COUNT` | Zero or more than one file | "Upload exactly one MP3 file; got N." |
| `E_AUDIO_FORMAT` | Not MP3 by magic bytes | "'{name}' is not an MP3 file (detected {actual})." |
| `E_AUDIO_EMPTY` | Zero bytes | "'{name}' is empty." |
| `E_PROBE_FAILED` | ffprobe non-zero | "Could not read '{name}': {stderr tail}" |
| `E_NO_SPLITS` | No split points after stripping | "Enter at least one split point." |
| `E_SPLIT_COUNT` | > 99 points | "{n} split points exceeds the maximum of 99." |
| `E_TIME_FORMAT` | Unparseable entry | "Split point {i} ('{raw}') is not a time. Use HH:MM:SS.mmm, MM:SS, or seconds." |
| `E_TIME_RANGE` | Value ≤ 0 | "Split point {i} ({value}) must be greater than 00:00:00." |
| `E_TIME_ORDER` | Not strictly increasing | "Split point {i} ({value}) is not after split point {i−1} ({prev})." |
| `E_TIME_PAST_END` | Value ≥ duration | "Split point {i} ({value}) is at or past the end of the audio ({duration})." |
| `E_NAME_COUNT` | Names ≠ n+1 | "Expected {expected} output names for {expected} segments; got {got}." |
| `E_NAME_EXTENSION` | Extension not `.mp3` | "Output name {i} ('{raw}') must end in .mp3." |
| `E_FFMPEG_MISSING` | ffmpeg/ffprobe not on PATH | "ffmpeg is required but was not found on PATH." |
| `E_FFMPEG_FAILED` | Any segment encode fails | "Failed to encode segment {i} ({start}–{end}): {stderr tail}" |

**Ordering.** Split-point format errors are reported without probing the file, so a typo'd time does not require an upload to surface. Time-vs-duration checks run after the probe. Name checks run after the plan exists, since the expected count depends on it.

**Partial failure.** If segment 3 of 5 fails to encode, the whole run fails with `E_FFMPEG_FAILED`; no partial file set is returned. Half a song is worse than an error.

**ffmpeg invocation.** `-nostdin` and `-y` are always passed, so a stray prompt or an existing file in the temp dir can never hang the server.

## 10. User interface

Gradio `Blocks`, vertical layout, `title="Audio Splitter"`.

| Row | Component | Type | Notes |
| --- | --- | --- | --- |
| 1 | Source audio | `Audio` | `type="filepath"`, `label="Source MP3"`. Shows duration and lets the user scrub before splitting. |
| 2 | Split points | `Textbox` | `lines=8`, monospace, placeholder `00:05:00\n00:12:30\n00:30:00`. |
| 3 | Output names | `Textbox` | `lines=6`, optional, placeholder `intro\nverse\nchorus\noutro`. |
| 4 | Advanced | `Expander` | Checkbox "Stream copy (fast, frame-aligned only)"; checkbox "Keep temporary files for inspection". |
| 5 | Split | `Button` | `variant="primary"`. |
| 6 | Result | `Markdown` | Preview: segment count, each segment's duration, actual filename, and any repaired names. |
| 7 | Files | `File` | `file_count="multiple"`, `label="Segments"`. |
| 8 | Archive | `File` | Optional ZIP of all segments, for one-shot download of a many-segment split. |
| 9 | Status | `Markdown` | Success or the error block. |

Behaviour:

- Clicking **Split** with a non-MP3 or no file is rejected client-side by `Audio`'s own `type` constraint before hitting the handler.
- The handler never raises; every failure path returns a rendered error block and leaves previously returned files untouched.
- `gr.Examples` provides three demo cases so the accepted time formats are discoverable without an upload.
- No global state; the function takes only its inputs, so concurrent sessions cannot interfere.

## 11. Architecture

```
audio-splitter/
├── spec.md
├── plan.md
├── app.py                 # Gradio Blocks wiring, calls splitter.split_audio
├── splitter/
│   ├── __init__.py
│   ├── errors.py          # SplitError, error codes, message templates, stderr_tail
│   ├── timeparse.py       # parse_split_points -> list[int] (ms), format helpers
│   ├── naming.py          # sanitize_name, default_name, apply_names
│   ├── probe.py           # is_mp3, probe -> MediaInfo, ensure_ffmpeg_available
│   ├── plan.py            # build_plan(duration_ms, points_ms) -> [Segment]
│   └── split.py           # validate, encode per segment, temp dir, return paths
└── tests/
    ├── conftest.py        # ffmpeg-generated fixtures + the `ffmpeg` marker hook
    ├── test_timeparse.py
    ├── test_naming.py
    ├── test_plan.py
    ├── test_probe.py      # includes the "every error code is reachable" check
    ├── test_split.py      # integration
    ├── test_app.py        # handler + Blocks wiring
    └── test_hardening.py  # concurrency, temp hygiene, injection safety
```

Separation of concerns: `timeparse`, `naming`, and `plan` are pure functions over ints and strings — fully unit-testable with no ffmpeg. `probe` and `split` are the only ffmpeg-touching modules, so integration tests carry `@pytest.mark.ffmpeg` and `-m "not ffmpeg"` runs the fast lane.

FFmpeg is invoked through `subprocess.run([...])` with an argument list, never a shell string, so filenames containing spaces or quotes cannot inject arguments. stderr is captured and truncated to the last ~500 characters before being shown.

## 12. Dependencies and environment

| Dependency | Purpose | Version |
| --- | --- | --- |
| `gradio` | UI | ≥ 5.0 (developed against 6.x) |
| `ffmpeg` / `ffprobe` | decode, encode, duration probe | system binary, ≥ 5.0 |

`ffmpeg` must be on `PATH`; a missing binary surfaces as `E_FFMPEG_MISSING` at startup, checked once when the app loads so the failure is visible before an upload.

Local setup uses `uv`, with a project `.venv`:

```
uv sync
uv run python app.py
```

## 13. Testing

Two lanes, both from `uv run pytest`:

```
uv run pytest -m "not ffmpeg"    # fast; pure logic only
uv run pytest                    # full; needs ffmpeg on PATH
```

Unit tests (no ffmpeg): time parsing across every accepted format and each rejection; name sanitisation for separators, reserved names, duplicates, length, empty-after-clean; plan derivation including the single-point case, the point-at-duration-adjacent case, and segment durations summing to the source duration exactly.

Integration tests (`@pytest.mark.ffmpeg`), using fixtures synthesised by ffmpeg so the suite needs no checked-in audio:

- split a 10 s tone at `[3s]` → 2 files, durations ≈ 3 s and ≈ 7 s,
- concatenating all segments yields a stream whose duration matches the source within one frame,
- **placement**, not just length: a marker file of ten 2 s blocks alternating 440/880 Hz is cut on its boundaries, and each output segment's pitch is measured with a Goertzel filter. This is the check that would fail if `-ss` seeked imprecisely — a duration-only test cannot distinguish a correct cut from one landing a second early.
- names supplied → filenames match after sanitisation; names omitted → default indexed names match the §8.2 pattern,
- every error code in §9 is raised from a public entry point, so no documented code is unreachable,
- hardening: two concurrent splits share no state, a failed run leaves nothing on disk, and a filename containing `$(...)` cannot execute.

`test_app.py` drives the handler and asserts the Blocks graph wires the Split button to it: a valid run returns `len(points) + 1` files, an invalid run returns an error block containing the expected code.

## 14. Out of scope for v1

Deferred, in rough priority order:

1. **Other input formats** — driven by `ffprobe`'s reported codec rather than an extension check; MP3 output stays fixed.
2. **Two-step UI** — the user scrubs the waveform and clicks to add split points instead of typing them. The `plan` module already accepts the points as a plain list, so this is a UI-only change.
3. **Split-point presets** — equal-length division (split into `k` equal parts), which is derivable from `D` and needs no new UI concepts beyond a count field.
4. **Per-segment re-encode settings** — bitrate/quality, fade-in/out at boundaries to remove the frame-level click.
5. **S3-backed output** for large sources where passing every segment through the Gradio file component is wasteful.
6. **Progress reporting** — a long split currently shows nothing until it finishes; a generator-backed progress bar would need the handler split into a job plus a poll endpoint.

## 15. Open questions

| # | Question | Assumption taken |
| --- | --- | --- |
| 1 | Are split points timestamps or durations? | Timestamps. `[5:00]` cuts once, at five minutes. Durations would make `[5:00, 5:00]` a meaningful pair; timestamps make it an order error. |
| 2 | Should other input formats be accepted in v1? | No — MP3 only, matching the stated requirement. |
| 3 | Re-encode or stream copy? | Re-encode by default; stream copy is opt-in behind Advanced, because copy can silently drop up to one frame at each boundary. |
| 4 | Are output names positional? | Yes, one per segment in order. Names are a convenience, not an identifier — nothing downstream reorders segments. |
| 5 | Should the source be modified in place? | No. The upload is read-only; every output is a new file in a temp directory. |
