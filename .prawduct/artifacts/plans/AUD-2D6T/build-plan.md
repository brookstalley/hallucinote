---
artifact: build-plan
version: 1
scope: aud-2d6t
depends_on: []
last_validated: null
---

# AUD-2D6T — Build Plan (audio-capture take retention)

Backlog: `AUD-2D6T` (rolling window + pinned takes, `stage: ready`, filed
2026-05-23). This plan supersedes that item's proposed shape — see
§"Departure from the backlog item" below.

**Critic mode:** cumulative at the end (small chunks, one coherent surface).

## Requirements Confidence: **High**

The problem is a measured fact (nothing in the tree deletes a captures dir; the
sizes are computed from the WAVs' own 48 kHz/stereo/float32 headers), the safety
argument is verified by grep (`audio/io.py:load_capture_set` is the sole reader
of a captures dir, and `resolve_baseline` keys on the analysis JSONs), and the
one genuinely open choice — the retention policy, which auto-deletes
multi-gigabyte artifacts — was put to the user and answered before any code was
written.

`scope:` above is the single key `aud-2d6t`, matching what the change-log entry
and the scope rollups use, so the ledger and the views join on one string. It is
deliberately NOT a comma list — nothing splits one, so a list is parsed as a
single opaque key that matches nothing. Note that branch→plan inference cannot
resolve this plan regardless: it requires an unchecked chunk, and every chunk
here is done, so attribution comes from the `active_build_plan` pointer (updated
in the same commit).

**Context (cross-session handoff):** User reported renders reaching ~4 GB each
with no cleanup. Retention policy chosen by the user 2026-08-03: **auto-sweep at
render start, keep the last 2 takes per song, plus a CLI**. This is a
user-approved destructive default, recorded here because auto-deleting
multi-gigabyte artifacts is a decision the product owner must own.

## Problem / success / out-of-scope (Confidence Check)

1. **Problem.** Nothing in the codebase ever deletes a captures dir. Every
   `ableton_render` writes N+R+1 WAVs at 48 kHz / stereo / 32-bit float
   (~23 MB per surface-minute); a 24-surface 5-minute song is ~2.8 GB per take,
   and takes accumulate without bound.
2. **Success.** After a render, `songs/<slug>/captures/` holds at most the
   configured number of takes plus the one just written; pinned takes are never
   removed; `hallucinote captures prune --dry-run` shows exactly what would go.
3. **Out of scope.** Changing the capture audio format (32-bit float is
   load-bearing for the >0 dBFS overshoot measurement in
   `audio/attribution.py`); retention for `analysis/` JSONs (kilobytes — always
   kept); any cross-song or global disk budget.

## Why deleting analyzed takes is safe (the load-bearing fact)

Captures are **write-once, read-once**: `ableton_render` writes them,
`ableton_analysis` reads them once and emits a self-contained MixReport to
`songs/<slug>/analysis/<ts>.json`. Baseline comparison (`compare_to`) resolves
against those **JSONs** — `audio/compare.py:resolve_baseline` globs
`analysis/*.json` and keys on `db_seq` — and never re-opens a WAV. So the only
capability lost when a take's audio is deleted is re-analyzing *that take* with
different parameters. Verified by grep: `audio/io.py:load_capture_set` is the
sole reader of a captures dir.

## Departure from the backlog item

AUD-2D6T proposed a manual `tools/audio-prune --keep N`. A manual tool does not
solve the reported problem — it relies on the operator remembering, which is the
regime that produced the 4 GB takes. The sweep is therefore **automatic in the
render path**, with the CLI retained for on-demand and `--dry-run` inspection.
The `.pinned` marker from the original item is kept as specified.

## Design decisions

**Delete the whole take directory, not just the WAVs.** A WAVs-only sweep that
left `manifest.json` behind would create a footgun: `_latest_captures_dir`
selects the newest dir *that has a manifest*, so a gutted take could be selected
for analysis and then fail deep inside `io.load_capture_set` on missing audio.
Whole-directory removal is both simpler and free of that trap; take provenance
already survives in the MixReport (`captures_dir` + `db_seq`).

**Sweep at render start, not at analysis completion.** Render start is the one
moment when no take is in flight, so the sweep cannot race a running analysis.
Sweeping post-analysis would also destroy the take a caller may want to
re-analyze with different parameters.

**Module lives at `src/hallucinote/takes.py`, not under `hallucinote.audio`.**
`hallucinote.audio.__init__` eagerly imports the numpy/librosa analysis stack;
the MCP server is stdlib-only at startup and must import the sweep on the render
path. Same constraint that put `paths.py` at the package top level. Named for
the domain term the backlog item and the research spike already use ("take
retention", "pin this take"), which also avoids colliding with the existing
`capture.py` (Ableton mix-layout snapshots — a different subject entirely).

**`recency_key` is defined once, here, and imported by the analysis handler.**
The sweep's ordering and `_latest_captures_dir`'s selection must agree: a sweep
that ordered takes differently could delete the take the next analysis would
have picked. That is a correctness coupling, not a DRY preference.

**A song slug is validated before it can reach a delete** (added after Critic
review, which found the hole). `resolve_song_dir` joins the slug straight onto a
songs root, and `pathlib` join semantics make an *absolute* slug replace that
root outright (`Path("songs") / "/etc"` is `/etc`) while `..` segments walk out
of the songs tree — either would aim `execute_sweep` at a directory unrelated to
the song, contradicting this plan's own "never an unrelated directory" claim.
`takes.captures_root_for_slug` is the single choke point: it validates then
resolves, and both slug-taking entry points (the render path and the CLI) go
through it, so validation cannot be forgotten at one of them. `SLUG_RE` /
`validate_slug` moved from `tools/scaffold_song.py` into `workspace.py` — the
module that owns slug→path resolution should own what a valid slug is, so a
caller resolving a slug into a directory it will delete under can't be checking
against a looser copy. (`db/mutations/songs.py` keeps its own looser
`[a-z0-9_-]+` check on a song *name*: that is a DB-column constraint, not a path
guard, and nothing joins it onto a filesystem root — so it is an adjacent rule,
not a second copy of this one.)

**Configuration by environment variable**, matching `HALLUCINOTE_SONGS_ROOT`:
`HALLUCINOTE_CAPTURE_KEEP` (int, default 2) and `HALLUCINOTE_CAPTURE_SWEEP`
(`0` disables the automatic sweep entirely). This repo has no
`project-preferences.md`, and the knob must be readable from both the engine CLI
and the MCP server process.

## Status

- [x] **1 — Retention core** (`src/hallucinote/takes.py`) — take enumeration, keep/sweep classification, pin + in-flight guards, plan/execute split
- [x] **2 — Auto-sweep on the render path** (`hallucinote_mcp/.../server.py`) — sweep the song's captures root before forwarding a render
- [x] **3 — `hallucinote captures` CLI** — `list` / `prune` with `--keep`, `--dry-run`, `--pin`, `--unpin`
- [x] **4 — Docs + backlog close** — workflow docs, skill note, AUD-2D6T closed

## Chunk 1 — Retention core

**Deliverable:** `src/hallucinote/takes.py`, stdlib-only:
- `Take` record: dir path, `captured_at` (from `manifest.json`), manifest mtime,
  byte size, `pinned` flag, `in_flight` flag.
- `recency_key(take_dir)` — the canonical "newest take" ordering, hoisted from
  the analysis handler's `_capture_recency_key`, which now imports it.
- `list_takes(captures_root) -> list[Take]` — newest first; a subdirectory with
  no `manifest.json` is not a take and is never returned (so never swept).
- `plan_sweep(captures_root, *, keep, protect=(), force=False) -> SweepPlan` —
  pure classification; returns kept + swept takes and reclaimable bytes. Never
  touches disk beyond reading.
- `execute_sweep(plan) -> SweepResult` — removes swept dirs; per-take errors are
  collected, not raised, so one locked directory cannot abort the rest.
- Guards: a take is never swept when it carries `PIN_FILENAME` (`.pinned`), when
  its dir is in `protect`, or when its `status.json` reports a non-terminal
  state (a render still writing).

**Acceptance:** unit tests cover — keep-N ordering by manifest recency (not dir
name); pinned take survives past the window and does not consume a keep slot;
a `status.json` `state=running` take is never swept; `protect` excludes the
in-flight output dir; `plan_sweep` writes nothing; `execute_sweep` reports a
per-take failure without aborting the sweep; `keep=0` and empty/absent roots are
handled.

**Done when:** the module imports with no third-party dependency (assert in a
test that it is importable without numpy on the path), and tests pass.

## Chunk 2 — Auto-sweep on the render path

**Deliverable:** in `hallucinote_mcp/src/hallucinote_mcp/server.py`, sweep the
song's canonical captures root immediately before forwarding an
`ableton_render(start)`, protecting the dir this render is about to write.
- Scoped to `resolve_song_dir(song_slug) / "captures"` — never to the parent of
  a caller-supplied `output_dir`, so an explicit path outside the song's
  captures root can never cause a sweep of an unrelated directory.
- Best-effort: a sweep failure logs and lets the render proceed. Disk hygiene
  must never block a capture.
- Honors `HALLUCINOTE_CAPTURE_SWEEP=0` and `HALLUCINOTE_CAPTURE_KEEP`.
- Skipped silently when the `hallucinote` engine is not importable (the uvx
  MCP-only install already has this fallback for `resolve_song_dir`).

**Acceptance:** tests — a render start with 4 existing takes leaves 2 plus the
new dir; the new output dir is never swept even when it already exists; a pinned
take survives; `HALLUCINOTE_CAPTURE_SWEEP=0` sweeps nothing; a raising sweep does
not prevent the render request from being forwarded.

**Done when:** the render-path tests pass and the existing
`test_server.py` output-dir tests still pass unchanged (behavior preservation on
the absolutize contract).

## Chunk 3 — `hallucinote captures` CLI

**Deliverable:** `src/hallucinote/tools/captures_cli.py` + registration in
`cli.py`'s `_SUBCOMMANDS` / `_SUMMARY`:
- `hallucinote captures list [--song SLUG]` — takes with size, age, pinned and
  in-flight flags, plus the total on disk. (An `analyzed` flag was considered
  and dropped: computing it means scanning `analysis/*.json` for a matching
  `captures_dir`, and it informs no decision the sweep makes — pinning is the
  mechanism for "keep this one".)
- `hallucinote captures prune [--song SLUG | --all] [--keep N] [--dry-run]` —
  `--dry-run` prints the plan and exits 0 having written nothing.
- `hallucinote captures pin <take-dir>` / `unpin <take-dir>`.
- Default `--keep` from `HALLUCINOTE_CAPTURE_KEEP` (2).

**Acceptance:** tests — `--dry-run` removes nothing and names every take it
would remove; `prune` honors `--keep`; `--all` walks every song under the
workspace; `pin` then `prune` leaves the pinned take; exit codes are 0 on
success and non-zero on an unknown song.

**Done when:** `hallucinote captures --help` renders, tests pass, and a real
invocation against this repo's `songs/` is exercised in Verify.

## Chunk 4 — Docs + backlog close

**Deliverable:** retention documented where the render lifecycle already is —
`docs/song-workflow.md` (the render/analysis section) and
`skills/render-analyze/SKILL.md` (a line that old takes are swept and how to pin
one). Close AUD-2D6T via `/prawduct:backlog update status=shipped`.

**Acceptance:** docs state the default keep count, the pin mechanism, and both
env vars; no doc claims captures are retained indefinitely.

**Done when:** the backlog item is shipped and `grep` finds no stale
"kept indefinitely" claim.
