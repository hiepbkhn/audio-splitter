# Audio Splitter — Implementation Plan

Derived from `spec.md`. Sequenced so that each task is independently verifiable and the pure logic lands before anything that needs ffmpeg.

---

## 0. Ground rules

- **Tasks are ordered by dependency, not by importance.** Task 1–4 need no ffmpeg and no Gradio; they can be built and proven in isolation.
- **Every task ends with a runnable check** (a test command or a manual invocation). A task is not done until that check passes.
- **Module boundaries from §11 of the spec are load-bearing.** `timeparse`, `naming`, and `plan` stay pure; nothing in them may `import subprocess` or `gradio`. If that starts happening, the boundary is wrong.
- **Vertical slice first, polish second.** Task 8 produces a working end-to-end app; everything after it is hardening.

## 1. Dependency chain

```
T1 scaffold ─┬─> T2 timeparse ─> T5 plan
             ├─> T3 naming ────┘
             ├─> T4 errors
             └─> T6 probe ─> T7 split ─> T8 app ─┬─> T9 integration tests
                                                └─> T10 hardening
```

T2, T3, T4 and T6 are independent of each other and can proceed in any order or in parallel.

## 2. Tasks

### T1 — Project scaffold and environment

**Depends on:** nothing.

- Create `splitter/__init__.py` (empty, re-exports nothing yet — add exports as they stabilise).
- Create `tests/__init__.py`? Not needed; pytest rootdir handles it. Skip.
- Create `pyproject.toml` with `[project] name = "audio-splitter"`, `requires-python = ">=3.10"`, dependencies `gradio>=5.0`, and `[dependency-groups] dev = ["pytest"]`. Chosen over `requirements.txt` because `uv` is the project tool and it makes the venv reproducible.
- `.gitignore`: `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `dist/`, `outputs/`.
- `README.md`: three lines — what it does, `uv run python app.py`, the local URL. Not a manual; the spec is the manual.

**Verify**: `uv sync` completes; `uv run python -c "import gradio"` exits 0.

**Note**: ffmpeg is a system binary and is *not* managed by `uv`. Record in the README that it must be on `PATH`.

### T2 — `splitter/errors.py`

**Depends on**: T1.

- `class SplitError(Exception)` with fields `code: str`, `message: str`, `index: int | None = None`, `detail: str | None = None`.
- `__str__` returns `message`, so raising and stringifying stay equivalent.
- A `CODES` frozenset of every code in §9 of the spec. Tests assert every code in the table exists here — a spec/code drift check.
- A `USER_MESSAGE: dict[str, str]` template map keyed by code, with `{placeholders}` filled by the raise sites. Centralising templates keeps wording identical across call sites.

**Verify**: `uv run pytest` collects 0 tests but exits without import errors.

### T3 — `splitter/timeparse.py`

**Depends on**: T1, T2.

- `parse_time(raw: str) -> int` — one entry to milliseconds. Returns `int`, raises `SplitError(code="E_TIME_FORMAT")` otherwise.
- `parse_split_points(text: str) -> list[int]` — strips blanks and `#` comments, splits each line on `,` and `;`, parses in order, applies the validation ladder from §7.2 (`E_NO_SPLITS`, `E_SPLIT_COUNT`, `E_TIME_RANGE`, `E_TIME_ORDER`) and reports **all** failures, not the first.
- Fractional handling: `re` captures `(?:\.(\d{1,3}))?`; digits beyond three are truncated. `00:12:30.5` → 750 s → `750000` ms; `00:12:30.55` → `75500`, not `55000` and not rounded to `.56`.
- Minutes must be `< 60` when hours are present; `00:70:00` is `E_TIME_FORMAT`, not silently 70 minutes. In `MM:SS` form the minute field is unbounded per §7.2.
- Bare-seconds form must require a decimal point or be all digits — `1e3` is rejected, so no float parsing sneaks in.
- Reject unit suffixes outright: a trailing alphabetic character after a valid parse is a format error, so `5m` fails rather than reading as `5`.

**Verify**: `tests/test_timeparse.py` covers each accepted form, each rejection, multi-entry lines, comment/blank lines, the truncation case, and the `00:70:00` case.

### T4 — `splitter/naming.py`

**Depends on**: T1, T2.

- `sanitize_name(raw: str, fallback: str) -> str` — implements the full §7.3 repair pipeline: strip separators and `..`, drop control chars and `<>:"|?*`, trim whitespace and dots, prefix reserved Windows device names, fall back when the result is empty, truncate to fit 255 bytes on a UTF-8 boundary (never mid-codepoint).
- `default_name(stem: str, index: int, start_ms: int, end_ms: int) -> str` — emits `{stem}_part{i:02d}_{start}_{end}.mp3` with `HH-MM-SS.mmm` time fields, exactly as §8.2.
- `format_ms(ms: int) -> str` — single implementation of the `HH-MM-SS.mmm` format, shared with `default_name`. Not duplicated here or in `plan.py`.
- `apply_names(raw_names: list[str], segments: list[Segment], stem: str) -> list[str]` — validates the count (`E_NAME_COUNT`), enforces `.mp3` (`E_NAME_EXTENSION`), sanitises each, and de-duplicates by appending `_2`, `_3`, … It returns `(names, notes)` where `notes` lists repairs so the UI can tell the user a name was changed rather than silently renaming.
- Cap: 99 split points means 100 segments, so `part{i:02d}` is always two digits in v1 — no wider-field case is needed, and none should be written.

**Verify**: `tests/test_naming.py` covers separators, `..`, each reserved device name, trailing dots, empty-after-clean fallback, duplicate disambiguation, multibyte truncation, and the exact `default_name` output for a known duration.

### T5 — `splitter/plan.py`

**Depends on**: T3, T4.

- `@dataclass(frozen=True) class Segment: index: int; start_ms: int; end_ms: int` with a `duration_ms` property.
- `build_plan(duration_ms: int, points_ms: list[int]) -> list[Segment]` — pure derivation of the `n + 1` half-open segments in §8.1.
- `validate_points_against_duration(points_ms: list[int], duration_ms: int) -> None` — `E_TIME_PAST_END`, collected across all points. Separate from `build_plan` because it is the one check that needs the probe, and `build_plan` should stay usable in tests without one.
- Durations are checked to sum to `duration_ms` exactly — assert this in tests, since it is the invariant that catches off-by-one errors in the loop.

**Verify**: `tests/test_plan.py` covers the single-point case, two points, a point 50 ms from the end, the sum invariant, and that segments are half-open (no boundary is in two segments).

### T6 — `splitter/probe.py`

**Depends on**: T1, T2.

- `is_mp3(path: Path) -> bool` — reads the first bytes; `ID3` at offset 0, or an MPEG frame sync `0xFF` followed by a byte whose top three bits are `0b111`. The spec requires sniffing rather than trusting the extension, so this function must not look at the filename.
- `probe(path: Path) -> MediaInfo` — runs `ffprobe -v error -print_format json -show_format -show_streams`, parses out `duration` (ms, from `format.duration`), `sample_rate`, and `channels` from the first audio stream. Raises `E_PROBE_FAILED` with the stderr tail on non-zero exit.
- A duration of `None` or `≤ 0` is `E_PROBE_FAILED` — a container with no parsed duration cannot produce a valid final segment.
- `ensure_ffmpeg_available()` — called once at app load per §12, raises `E_FFMPEG_MISSING`.

**Verify**: `tests/test_probe.py` generates a 2 s MP3 with ffmpeg and asserts duration ≈ 2000 ms, correct sample rate, and `is_mp3` accepting it while rejecting a WAV written to a `.mp3` filename.

### T7 — `splitter/split.py`

**Depends on**: T2, T5, T6.

- `split_audio(source: Path, points_ms: list[int], names_raw: list[str], options: SplitOptions) -> SplitResult`
- `SplitOptions`: `stream_copy: bool = False`, `keep_temp: bool = False`.
- `SplitResult`: `segments: list[Segment]`, `names: list[str]`, `paths: list[Path]`, `notes: list[str]`, `temp_dir: Path`.
- Order of operations, per §9: validate split points → probe → validate against duration → validate names → build plan → encode. Validation is fully separated from encoding so nothing is written until every check passes.
- Encoding, via `subprocess.run([...])` with an argument list and no shell (spec §11):
  - default: `-nostdin -hide_banner -loglevel error -y -ss {start} -i {source} -t {dur} -vn -c:a libmp3lame -q:a 2 -ar {rate} -ac {channels} {out}`
  - `stream_copy`: swap `-c:a libmp3lame -q:a 2` for `-c copy` and drop `-ar`/`-ac`.
  - Timestamps are formatted to 6 decimal places — ffmpeg parses microseconds, and `1250` would be read as 1250 *seconds*.
- One temp dir per run via `tempfile.mkdtemp`. Output paths use the final sanitised names, so a name collision would clobber — the de-duplication in T4 is what prevents that, and it must run before encoding, not after.
- A non-zero ffmpeg exit raises `E_FFMPEG_FAILED` naming the segment index and range, with stderr truncated to the last 500 characters.
- `keep_temp=True` skips cleanup so the Advanced checkbox is meaningful.

**Verify**: `tests/test_split.py` runs under `@pytest.mark.ffmpeg` — described in T9.

### T8 — `app.py` (end-to-end vertical slice)

**Depends on**: T7.

This is the first task where the app actually works. Get it running before any polish.

- `Blocks(title="Audio Splitter", theme=...)` with the row order from §10.
- The handler takes `(audio_path, points_text, names_text, stream_copy, keep_temp)` and returns `(result_md, files, status_md, zip_file)`. It never raises — every failure path renders the error block.
- Validation error rendering: a `Markdown` block listing `message` per line, with the error code in a `code` span so it is greppable in tests.
- Success rendering: segment count, each segment's duration and actual filename, plus the `notes` from T4 when names were repaired.
- ZIP: written into the same temp dir, built from the segment paths, returned as a single extra `File` for one-shot download.
- `demo.launch()` with `show_error=True`.

**Verify**: launch, drag in an MP3, type `00:02` and `00:04`, click Split, confirm three files of ≈ 2 s each and a working ZIP link.

### T9 — Test suite completion

**Depends on**: T8.

Fixtures in `tests/conftest.py`, all synthesised by ffmpeg so no binary audio is committed:

- `tone_mp3` — 10 s sine at 440 Hz, 44.1 kHz mono.
- `silent_mp3` — 3 s of silence, for the "constant energy gives no cue" control case.
- `marker_mp3` — 1 s of 440 Hz, then 1 s of 880 Hz, repeated 5 times: each boundary has a known position *and* a known frequency, so a cut can be verified for landing in the right place rather than merely the right length.
- A session-scoped `ffmpeg_available` fixture that `pytest.skip`s the integration tests when ffmpeg is missing, per §11.
- `pytest.ini` / `[tool.pytest.ini_options]` registering the `ffmpeg` marker to keep the run warning-free.

Test cases per §13: segment counts and durations; concatenation duration matching the source within one frame; the `marker_mp3` frequency check; default naming matching the §8.2 pattern exactly; supplied names surviving sanitisation; every error code reachable from the public entry point; and `test_app.py` driving the handler through Gradio's test client for both a success and a failure run.

**Verify**: `uv run pytest` green; `uv run pytest -m "not ffmpeg"` green with no ffmpeg present.

### T10 — Hardening and spec conformance

**Depends on**: T9.

- **Concurrency**: the handler holds no module-level state. Verify by firing two differing splits through the test client and asserting the file lists do not cross-contaminate.
- **Temp hygiene**: confirm no output lands beside the upload, and that `keep_temp` is the only path that retains a directory.
- **Upload safety**: assert a filename containing `; rm -rf /` and one containing spaces are handled as literal filenames — the argument-list invocation should make this a non-issue, but it is worth a regression test given the spec calls it out.
- **Message audit**: read every rendered error against the §9 table and confirm the wording still matches.
- **`examples=`** entry per §10 so the input format is discoverable without an upload.
- README: document accepted time formats, the 99-split-point cap, and the stream-copy caveat.

**Verify**: `uv run pytest` green, and a manual pass over the §5 user stories US-1 through US-4.

## 3. Verification ladder

Run after every task that touches existing code:

```
uv run pytest -m "not ffmpeg"    # fast; pure logic only
uv run pytest                    # full; needs ffmpeg on PATH
uv run python app.py             # manual; only for T8 and T10
```

No linter or formatter is configured in v1. The codebase is small and single-purpose; if it grows, add `ruff` in a separate change rather than folding it into this build.

## 4. Sequencing summary

| Task | Deliverable | Needs ffmpeg | Needs Gradio |
| --- | --- | --- | --- |
| T1 | Scaffold, venv, README | no | no |
| T2 | Error types and message templates | no | no |
| T3 | Time parsing | no | no |
| T4 | Name sanitisation and defaults | no | no |
| T5 | Segment plan | no | no |
| T6 | MP3 sniffing and ffprobe | yes | no |
| T7 | ffmpeg encoding | yes | no |
| T8 | Working Gradio app | yes | yes |
| T9 | Full test suite | yes | yes |
| T10 | Hardening, concurrency, docs | yes | yes |

Nine of the ten tasks need neither ffmpeg nor a browser. That is the payoff of the §11 module split, and it is the reason to hold the boundary.

## 5. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| `-ss` before `-i` interacts badly with some sources | Cuts land early or audio desyncs | Verified by the `marker_mp3` frequency test in T9, not by duration alone |
| Name sanitisation changes what the user typed | User confusion | `notes` surface every repair in the result panel (T8) |
| Long splits give zero feedback | User assumes a hang | Accepted for v1; §14.6 lists a progress bar as the follow-up |
| Temp dirs accumulate when `keep_temp` is used | Disk growth | Documented in the README; the checkbox is off by default |
| Gradio 5 API drift | `Audio`/`File` signatures change | Pin `gradio>=5.0` and smoke-test in T8 before building on it |
| Encoding is the slow part of a 60-minute file | Long wait | Accepted; `stream_copy` exists as the escape hatch and is honestly labelled |

## 6. Deferred, tracked from §14 of the spec

Not built here, recorded so they are not lost:

1. Non-MP3 input formats, driven by ffprobe rather than an extension check.
2. Waveform-scrub UI — a `plan`-module client only, since it already takes a plain list of points.
3. Equal-length presets — derivable from the source duration alone.
4. Per-segment encode settings and boundary fades.
5. S3 output for large sources.
6. Progress reporting via a job plus a poll endpoint.
