<!-- Build Plan — SMP-6V2K wave 2 (hear it, keep it, play it). Tier 1 (Source of Truth).
     WHAT to build. For HOW (governance, test discipline, Critic), read
     /prawduct:methodology building. Requirements: ../SMP-6V2K/requirements.md (authoritative
     on scope). Design decisions D1–D7: ../SMP-6V2K/design.md. Decisions D8–D15 this plan adds
     are under "Design decisions this plan adds" below. -->
---
artifact: build-plan
version: 1
scope: SMP-6V2K-W2
branch: plan/smp-6v2k-w2
depends_on:
  - artifact: requirements
    path: .prawduct/artifacts/plans/SMP-6V2K/requirements.md
  - artifact: design
    path: .prawduct/artifacts/plans/SMP-6V2K/design.md
  - artifact: build-plan
    path: .prawduct/artifacts/plans/SMP-6V2K/build-plan.md
  - artifact: data-model
  - artifact: architecture
  - artifact: api-contract
  - artifact: security-model
  - artifact: nonfunctional-requirements
  - artifact: sync-boundary-contract
  - artifact: authorship-model
    path: .prawduct/artifacts/authorship-model.md
  - artifact: masking-analyzer-spec
    path: .prawduct/artifacts/masking-analyzer-spec.md
governed_by:
  - artifact: data-model
    dispositions:
      - "the DB is materialized state, never source of truth → conforms, and it decides a shape: this wave adds NO table. The asset manifest and every recipe are source in git (new `assets/manifest.json`, `build.py`); derived audio is a committed cache keyed by content; the DB keeps referencing files by path through `clips.audio_file` / `devices.audio_file` exactly as today (D8)"
      - "all writes go through mutators, one event each → conforms: chunk 08's pull-side link is written through `link_db_to_ableton`; chunk 00's slot floor is a mutator validation plus a schema CHECK; nothing else in this wave writes the DB"
      - "an existing song DB is opened through `init_db` → conforms: no new open path; chunk 03 reads notes through `src/hallucinote/db/queries` (reads may `conn.execute`)"
  - artifact: architecture
    dispositions:
      - "`_FINGERPRINT_PATHS` names exactly the code vendored into and executed in Live → engaged, not departed: chunk 07 edits `hallucinote_mcp/src/hallucinote_mcp/actions/device.py` and `hallucinote_mcp/src/hallucinote_mcp/handlers/device.py`, both fingerprint-bearing, so the wave carries ONE re-vendor + Live restart (chunk 17) and says so at every hand-off. No other chunk touches the fingerprint set"
      - "server-side-only code lives in `server_side/` → inapplicable because no DSP enters the MCP server at all: every analysis, field, transform and generator in this wave is engine-side under `src/hallucinote/`, per the api-contract norm that timing/audio transforms stay in the engine"
      - "every MCP handler is async and dispatches through anyio.to_thread → conforms: chunk 07's `assign_sample` handler follows `load_handler`'s shape"
      - "push is idempotent and diff-reconciling → conforms: chunk 07 diffs `devices.audio_file` against the read-back live sample path and emits nothing when equal; chunk 14 resolves `reverse=1` to a content-addressed derived file, so an unchanged song plans no work"
  - artifact: api-contract
    dispositions:
      - "errors teach; refuse-and-teach over silent wrong behaviour → conforms: `audio_file` on a non-sampler, a missing source, a checksum mismatch, a field that cannot be aligned (R3.6), a bass carve below the achievable resolution (R3.8) — each refuses with a recovery hint rather than approximating"
      - "no compatibility shims for consumers that cannot exist → conforms: chunk 14 REPLACES the `reverse=1` refusal in `src/hallucinote/sync/push/clips.py`; chunk 07 replaces nothing but adds an action beside `load` rather than overloading it"
      - "the MCP tool surface stays inside the tool-selection band → conforms: one new action (`assign_sample`) on the existing `ableton_device` tool, no new tool"
      - "timing transforms stay in the engine and off the MCP → conforms, and generalized: the whole spectral / feature / transform family is engine-only"
  - artifact: security-model
    dispositions:
      - "parsing must never be executing → conforms: the manifest and every derived-asset record are JSON read with `json.loads`; recipes live in `build.py`, which is already the accepted executable composition; MP3 decode invokes `ffmpeg` as a list-argument subprocess with no shell, and the input path is never interpolated into a command string"
      - "dependencies are locked and CI gates `uv lock --check` → conforms: the two optional-extras groups (`audio-separation`, `audio-stretch-ab`) land in chunk 00 with one re-lock; delegates never edit `pyproject.toml` or `uv.lock`"
  - artifact: nonfunctional-requirements
    dispositions:
      - "the MCP server is stdlib-only at import time → conforms: chunk 07 adds no import to the server; `soundfile`, `librosa`, `scipy` are imported only under `src/hallucinote/`"
      - "the full test suite runs with no path argument → conforms: that run is the coordinator's, at every integration merge; delegates run their own new test files only (the ratified `Delegate verification` ceiling)"
  - artifact: project-preferences
    dispositions:
      - "generators are pure (no db / mcp imports under `src/hallucinote/generators/`) → conforms: chunk 09's `src/hallucinote/generators/follow.py` consumes a `FeatureStream` value object from `src/hallucinote/features/types.py`, which chunk 00 locks db-free and mcp-free with an import-graph test of the same shape as `test_generators_package_imports_no_database_code`"
      - "sync planners produce plans and never send → conforms: chunk 07 and chunk 14 add planner rows and apply-side handling only"
      - "delegation pre-approved for independent chunks; ownership disjoint by construction and stated per delegate; delegates never govern → conforms: see Delegation"
      - "committed media stays small; the repo is public → conforms: no audio file is committed to this repo; every audio test uses `tests/unit/audio/fixtures.py`'s synthesized signals, and the reference song's sources live in the private songs workspace"
partition: |
  Two waves on a file-disjoint partition, integrated on `plan/smp-6v2k-w2` by the
  coordinator in the primary checkout (the wave-1 shape).
  .
  Chunk 00 is coordinator-only and lands the three shared TYPE modules every delegate
  consumes, the two optional-extras groups, and the slot-floor fix — the contract half
  that must exist before any brief is written.
  .
  Wave A, in parallel: **eleven delegates, eleven isolated worktrees** (01–10 and 12;
  11 is deferred — see Scope boundary), each owning new modules plus its own new test files. The only edits to EXISTING modules are
  07 (`hallucinote_mcp/src/hallucinote_mcp/actions/device.py`, `hallucinote_mcp/src/hallucinote_mcp/handlers/device.py`, `src/hallucinote/sync/push/devices.py`, `src/hallucinote/capture.py`),
  08 (`src/hallucinote/sync/pull/clips.py`) and 06 (`src/hallucinote/audio/report.py`, `src/hallucinote/audio/analyze.py`), and no two
  delegates share one — ownership is in the Delegation table. `src/hallucinote/cli.py`, `pyproject.toml`,
  `uv.lock`, docs, skills and every governance surface are coordinator-only.
  .
  Wave B, in parallel once A is merged: **three delegates** (13, 14, 15) whose work
  composes A's outputs. Then 16 (docs, cumulative) and 17 (the Live session), both
  coordinator-owned.
last_validated: 2026-09-09
critic_mode: null
---

# Build plan — SMP-6V2K wave 2: hear it, keep it, play it

> **Scope.** Everything `../SMP-6V2K/requirements.md` asks for that wave 1 did not deliver
> and that can be built without a decision only the user's ears can make. The design's
> waves 2, 3 and 4 are collapsed into one plan because the reason they were serial was
> session count, not dependency — and this plan is built in parallel. Requirements in:
> **R1.3, R1.5 (materialization), R1.6, R1.7, R2.1, R2.2, R2.3, R2.4 (behind an extra),
> R2.5, R2.6, R3.1–R3.8, R4.1, R4.2, R4.4 (the record of which route), R4.5 (declared
> order), R4.6, R5.3 (measurement only), R6.1, R6.3, R6.4, R6.5** — plus the three wave-1
> leftovers with a decision in them (#507, #473, the #509 probe). What is left out is
> named under *Scope boundary*, each with its reason and its home.

Backlog: **#510** (asset store, provenance, reproducible derived audio — R1.6/R1.7),
**#511** (sample lens — R2), **#330** (SMP-7K2D, sampler assignment — R1.3), **#237**
(AUD-7R3M, reverse — R1.5), **#507** (the link seam), **#473** (slot floor), **#266**
(AUD-6T2K, separation — R2.4, behind an extra). Probed, not built: **#509**.
On a "go", #507, #510 and #511 move to `stage: ready` (they are `requirements` today
because the decisions below had not been made).

## Requirements Confidence

**Level: Medium.** The *mechanisms* are high-confidence: every Live-side call this wave
needs was probe-confirmed on 12.4.5 today (`docs/research/audio-first-class/lom-probe-results.md`
rows 14–19 — no clip reverse, `SimplerDevice.replace_sample(abs_path)` round-trips an
arbitrary path, Simpler's `reverse()` is destructive), every DSP primitive it composes
already runs on numpy arrays in `src/hallucinote/audio/`, and the beat↔seconds map it
needs is `src/hallucinote/audio/section.py`'s `BeatSampleMap`. What is medium is whether the *musical*
surface is the right one — the requirements' own three open questions are still open, and
the plan answers them by parameterizing rather than deciding (owner ruling L2: these are
tools).

**Open assumptions / unknowns:**

- `[ASSUMPTION: symbolic carving is useful on its own, not merely a draft of the measured
  pass | MED impact | user can override]` Carried from the requirements. Both routes are
  built on one operation (R6.1), so if it is wrong the cost is one unused code path.
- `[ASSUMPTION: librosa `pyin` is adequate for spoken F0, and formants via LPC over
  `scipy.signal` are adequate for R2.2 — no new dependency for feature extraction | MED
  impact | user can override → chunk 02 prices in `pyworld` or `parselmouth` as an
  optional extra instead]` Both are standard for speech at this fidelity; the falsifier is
  a real line whose F0 track is unusable, which chunk 15's lens will show on bars.
- `[ASSUMPTION: Simpler is the supported sampler host; `MultiSampler` (Sampler) is
  unprobed | LOW impact]` Carried from #330's own decision: `audio_file` on a Sampler
  fails at plan time with a teaching error naming Simpler until chunk 17 probes Sampler.
- `[ASSUMPTION: sources and derived cache are committed to the (private) songs repo, no
  LFS, with a size guard | HIGH impact — a poisoned history is expensive to clean | user
  can veto before the song's first commit]` D9 below states the guard.
- `[ASSUMPTION: the three open questions (source cleanliness, uniform vs per-sample
  treatment, does the music lead) stay open through this wave and are answered by the
  song | MED impact]` Each surface is parameterized so either answer is authorable:
  separation is optional, detectors are parameterized generators, the follower takes a
  key constraint or none (R4.6).

**What would raise confidence:** the first hearing — one line ingested, its lens read,
one symbolic carve and one follower part pushed. That is chunk 15's acceptance plus
chunk 17's session, and it is the earliest point the user can tell us whether the shape
is right. The R6.2 listen (chunk 12's harness) settles the one dependency decision.

## Scope boundary — what this plan does NOT do

- **R4.3 grain-scatter with formant preservation.** Gated on the R6.2 decision, which is
  an audible A/B on real dialogue the user must hear before it is built. Chunk 12 builds
  the harness; the decision and the build are the next plan's. → stays on #510's
  transform list, marked *gated on R6.2*.
- **R5.1 continuous samples across sections (#267).** General envelope auto-partition;
  the perform route already covers the song-spanning case. Not sample-specific.
- **R5.2 turn-taking as arrangement material.** The design's advisory stands: no
  `Conversation` class until the song has been hand-authored once. Zero code.
- **R5.3 as a *coaching* lens.** The 2026-08-10 owner ruling on #279 binds: no new lens
  that grades or coaches until the listening day. Chunk 06 ships the intelligibility
  **measurement** (speech-band-over-bed per turn, neutral numbers, no findings); the
  `/mix-review` framing that turns it into a producer's question waits for the listening
  day and is filed there.
- **R2.4 separation (#266), chunk 11.** Deferred at dispatch (owner: "as much fanout as will
  be efficient", 2026-09-09): it would lock `torch` for a requirement whose place on the critical
  path depends on open question 1, and its tests cannot verify a real run. The chunk section stays
  below as the spec to dispatch when Q1 is answered; #266 stays open.
- **#509 (arrangement extent) build.** Chunk 17 runs its probe; the build is drawn on
  #509 after the verdict, because both of its design questions turn on what Live exposes.
- **Feature caching on disk.** Extraction on a seconds-long line is fast; streams are
  computed on demand and memoized in-process. A cache is a persisted format, and it is not
  needed yet (D13).
- **A DB table for assets.** D8 — the manifest is source, the DB references paths.
- **Acquisition from media, fetching, take lanes and comping.** L1, D5, AUD-1M4V.

## Design decisions this plan adds (D8–D15)

D1–D7 are in `../SMP-6V2K/design.md` and stand. These are the decisions chunk 00 has to
have made before a brief can be written.

**D8 — No DB surface for assets. The manifest is source; the DB references paths.**
new `assets/manifest.json` is one JSON file per song (not per-file sidecars — one place,
one diff), `manifest_version: 1`, keyed by source **name**. The questions its consumers
will ask, elicited from the consumers this plan builds: *what is this line* (a free-text
note — for film material it is the only record of what the sample is), *where is it
from* (an origin string: title, medium, scene — never a path to a media file, per L1),
*has the file changed* (sha256 of the normalized WAV), *can I trust the normalized copy*
(sample rate, channels, duration, the original filename and container, whether the
original was lossy), *when* (ingested-at, ISO-8601 UTC). `[DECISION: one manifest file,
name-keyed, no DB table | the data-model norm's why — source is what is in git; a table
would be materialized state re-deriving a file already in git | user can override]`

**D9 — Binary policy: commit sources and the derived cache to the songs repo, guarded.**
Sources are seconds long; thirty of them is tens of megabytes in a private repo. Ingest
warns above 25 MB per file and refuses above 100 MB without `--allow-large`. No LFS this
wave. `[DECISION: commit, with a size guard | R1.7 says the cache is checked in so opening
a song never requires a re-render; LFS adds a dependency to every clone for a problem the
guard bounds | user can veto — and must, before the reference song's first commit, because
this is the one-way door the design named]`

**D10 — Derived audio is content-addressed, and the address is the whole answer to #393.**
new `assets/derived/<hash>-<slug>.wav` beside new `assets/derived/<hash>.json`, where `hash` is
sha256 over (source checksum, the transform chain with every parameter, the backend id
and library version, and — for a score-dependent recipe — the **reference fingerprint**:
`src/hallucinote/sync/push_notes.py`'s `clip_fingerprint` over the referenced clips' notes for a symbolic field,
the capture take id plus `src/hallucinote/audio/codeversion.py`'s `disk_signature()` for a measured one). A
clip references the path the recipe returns. Change the source, the recipe, or the
bassline it was carved against, and the address changes; the old file is an orphan the
`derived prune` subcommand lists. This is R3.7 by construction and it is exactly the
"invisible parameter, never an author-managed file" #393 asked for — the objection that
closed it (a second source of truth going silently stale) cannot arise, because nothing
can reference a stale file by a current address. The record answers: *what produced this*
(the chain), *from what* (source checksum), *against what* (the reference fingerprint),
*is it still valid* (recompute the address), *can I delete it* (always — regenerable).
`[DECISION: content-addressed derived cache with the reference fingerprint in the address
| engages D2's why and #393's objection together | user can override]`

**D11 — The recipe surface in `build.py`.** `from hallucinote.assets import source, derive`;
`line = source(SONG_DIR, "rivers-01")` returns a `Source`; `derive(line, reverse())`,
`derive(line, trim(0.4, 2.1), normalize(peak_dbfs=-1.0))` returns a `Derived` whose
`.path` is what `create_audio_clip(audio_file=...)` takes. Transforms are frozen
dataclasses: `trim`, `fade`, `normalize`, `reverse`, `pitch_shift`, `stretch_to_bars`,
`chop_at_onsets` (yields a list), and, from chunk 13, `carve` / `vocode`. Backend per D4:
librosa by default; a transform that asks for `formant_preserve=True` refuses with a
teaching error naming chunk 12's harness until the R6.2 decision lands.

**D12 — The shared types are the contract, and the coordinator writes them first.**
`src/hallucinote/assets/types.py` (`Source`, `Derived`, `Transform` protocol), `src/hallucinote/features/types.py`
(`FeatureStream` in seconds; `BeatStream`; `Segment`; `FeatureEvent`; the
`BeatMap` protocol `src/hallucinote/audio/section.py` already satisfies), `src/hallucinote/spectral/types.py`
(`SpectralField`, `ReferenceSchedule`, `MaskParams`, `ResolutionReport`). Dataclasses and
validation only — no logic a delegate would need to change. They are what makes twelve
briefs writable without reading each other.

**D13 — Features are computed, not cached.** See Scope boundary.

**D14 — The link seam (#507): pull writes the link when it ingests.** Of the three homes
the issue named, (a) is chosen. The "links are push-owned" boundary exists so link rows
are truthful to Live; pull creates the row *from* an observed Live clip, so at that moment
it holds the strongest evidence any writer will ever have, and it writes through the same
mutator push does (`link_db_to_ableton`, one event). (b) crosses the planner-never-writes
line; (c) adds a reconcile pass to re-discover what pull already knew.
`[DECISION: pull links what it ingests | engages the sync-boundary contract's why (truthful
links) rather than its roster of who writes them | user can veto]`

**D15 — Intelligibility ships as measurement, framed later.** Per #279's ruling (Scope
boundary). Neutral numbers in the report; no `Finding`, no threshold, no grade.

## Status

**A ticked box means the code is built, reviewed on the integration branch and green.**
Chunks 07, 14 and the #509 probe carry live "Done when" clauses only chunk 17 discharges;
`capability-truth.md` is updated by chunk 16 to say exactly what has and has not run
against Live.

- [ ] Chunk 00: contracts, extras, the slot floor *(coordinator, before dispatch)*
- [ ] Chunk 01: asset store — ingest, normalize, manifest *(wave A)*
- [ ] Chunk 02: the second front door — a sample loader and its feature streams *(wave A)*
- [ ] Chunk 03: spectral fields — symbolic from the score, measured from the capture set *(wave A)*
- [ ] Chunk 04: one field, one mask, a polarity — carve and vocode on arrays *(wave A)*
- [ ] Chunk 05: recipes — transforms and the content-addressed derived cache *(wave A)*
- [ ] Chunk 06: intelligibility — the speech band over the bed, per turn, measured *(wave A)*
- [ ] Chunk 07: a sampler gets its sample — `assign_sample`, push, capture (#330) *(wave A)*
- [ ] Chunk 08: pull links what it ingests (#507) *(wave A)*
- [ ] Chunk 09: the follower — an F0 contour becomes a part *(wave A)*
- [ ] Chunk 10: feature events with musical gates *(wave A)*
- [ ] Chunk 12: the stretch / pitch A/B harness for R6.2 *(wave A)*
- [ ] Chunk 13: carve and vocode as recipes, with the reference in the address *(wave B)*
- [ ] Chunk 14: `reverse=1` materializes through the derived cache (#237) *(wave B)*
- [ ] Chunk 15: the sample lens — inspect a line against bars, and the skill that runs it *(wave B)*
- [ ] Chunk 16: the docs say what is true, the contract artifacts track, the CLIs are wired *(coordinator; cumulative)*
- [ ] Chunk 17: the Live session — sampler live, reverse live, the #509 and Sampler probes *(operator-gated)*

Context: plan drawn 2026-09-09 on the merged, unreleased wave 1 (develop `c86df39`); owner
handed off the same day ("go using as much fanout as will be efficient"). Chunk 11 deferred
at dispatch. The wave-1 plan stays live until the develop→main release; this plan declares
its own branch so both resolve. Next: wave A dispatched from the chunk-00 commit.

---

## Delegation

**The owner asked for this plan to be built by parallel subagents, as wide as the
partition allows** — that is the standing approval; `project-preferences.md` records
delegation as pre-approved on this shape. Precedent: COLLAB-TURN ran four delegates;
this plan runs **eleven in wave A and three in wave B**, materially wider. The reason it
is safe to be wider is that eight of the eleven create only new modules — the partition
is disjoint by construction, not by care — and each delegate's verification is capped at
its own new test files, so twelve delegates put roughly twelve narrow pytest runs on the
box rather than twelve full suites.

**Mechanics.** Integration branch `plan/smp-6v2k-w2`, checked out in the primary
checkout (so the Prawduct gates see it — the wave-1 shape). For each delegate the
coordinator runs `git worktree add ../hallucinote-w2-NN -b w2/NN-<slug> plan/smp-6v2k-w2`,
writes the brief into it at new `.prawduct/.delegate-brief.md`, then dispatches the agent
at that directory. The worktree pytest `pythonpath` pin is already in `pyproject.toml`;
manual `python -c` checks in a worktree need `PYTHONPATH=src:hallucinote_mcp/src`
(the editable `.pth` points at the primary — a standing learning).

**Ownership — wave A.** *Owns* means may create or edit; everything not listed is
forbidden, and in particular no delegate touches `src/hallucinote/cli.py`, `pyproject.toml`, `uv.lock`,
anything under `docs/`, `skills/`, `.prawduct/` (except its own brief), the change log,
or any existing test file it does not own.

| Chunk | Owns | Must not touch |
|---|---|---|
| 01 | new `src/hallucinote/assets/store.py`, `src/hallucinote/assets/manifest.py`, `src/hallucinote/assets/ingest.py`, new `src/hallucinote/tools/asset_ingest.py`; new `tests/unit/assets/test_store.py`, `test_manifest.py`, `test_ingest.py` | `src/hallucinote/assets/types.py` (00's), `src/hallucinote/assets/recipes.py` / `transforms.py` / `derived.py` (05's), `src/hallucinote/assets/__init__.py` (13's) |
| 02 | new `src/hallucinote/audio/sample_io.py`, new `src/hallucinote/features/f0.py`, `formants.py`, `energy.py`, `segments.py`, `beatmap.py`; new `tests/unit/audio/test_sample_io.py`, new `tests/unit/features/test_f0.py`, `test_formants.py`, `test_energy.py`, `test_segments.py`, `test_beatmap.py` | `src/hallucinote/audio/io.py` (the capture loader stays as it is — D7), `src/hallucinote/features/types.py`, `src/hallucinote/features/events.py` (10's) |
| 03 | new `src/hallucinote/spectral/symbolic.py`, `measured.py`, `schedule.py`; new `tests/unit/spectral/test_symbolic.py`, `test_measured.py`, `test_schedule.py` | `src/hallucinote/spectral/types.py`, `src/hallucinote/spectral/ops.py` / `resolution.py` (04's), `src/hallucinote/audio/io.py`, `src/hallucinote/audio/reconcile.py` (read and reuse; do not edit) |
| 04 | new `src/hallucinote/spectral/ops.py`, `resolution.py`; new `tests/unit/spectral/test_ops.py`, `test_resolution.py` | everything else under `src/hallucinote/spectral/` |
| 05 | new `src/hallucinote/assets/recipes.py`, `transforms.py`, `derived.py`; new `tests/unit/assets/test_recipes.py`, `test_transforms.py`, `test_derived.py` | `src/hallucinote/assets/store.py` / `manifest.py` / `ingest.py` (01's), `src/hallucinote/assets/__init__.py` |
| 06 | new `src/hallucinote/audio/intelligibility.py`; **sole wave-A owner of** `src/hallucinote/audio/report.py` and `src/hallucinote/audio/analyze.py`; new `tests/unit/audio/test_intelligibility.py`; `tests/unit/audio/test_report.py` if its shape assertions need the new field | `SCHEMA_VERSION` (the coordinator decides at integration whether an additive field bumps it), `src/hallucinote/audio/masking.py` (reuse, do not edit) |
| 07 | `hallucinote_mcp/src/hallucinote_mcp/actions/device.py`, `hallucinote_mcp/src/hallucinote_mcp/handlers/device.py`, `src/hallucinote/sync/push/devices.py`, `src/hallucinote/capture.py`; new `hallucinote_mcp/tests/unit/test_handlers_device_sample.py`, new `tests/unit/sync/test_push_devices_sample.py`, new `tests/unit/capture/test_capture_sample_assignment.py` | `hallucinote_mcp/tests/unit/test_version_fingerprint.py` (the coordinator re-records the flip), every other action/handler module |
| 08 | `src/hallucinote/sync/pull/clips.py`; new `tests/unit/sync/test_pull_clips_link.py` | `src/hallucinote/sync/push/clips.py` (14's, wave B), `src/hallucinote/db/mutations/links.py` (reuse) |
| 09 | new `src/hallucinote/generators/follow.py`; new `tests/unit/generators/test_follow.py` | `src/hallucinote/generators/__init__.py` (16 exports it), everything under `src/hallucinote/features/` |
| 10 | new `src/hallucinote/features/events.py`; new `tests/unit/features/test_events.py` | every other `src/hallucinote/features/` module |
| 11 *(deferred)* | new `src/hallucinote/audio/separation.py`; new `tests/unit/audio/test_separation.py` | `pyproject.toml` (the coordinator adds the extra when it is dispatched) |
| 12 | new `src/hallucinote/tools/stretch_ab.py`; new `tests/unit/tools/test_stretch_ab.py` | `pyproject.toml`, `src/hallucinote/assets/transforms.py` (05 owns the production stretch; 12 is a listening harness and may duplicate a call rather than import 05's unfinished module) |

**Ownership — wave B.**

| Chunk | Owns | Must not touch |
|---|---|---|
| 13 | `src/hallucinote/assets/__init__.py` (the public `source` / `derive` API composing 01 and 05), new `src/hallucinote/assets/transforms_spectral.py`; new `tests/unit/assets/test_transforms_spectral.py`, `test_public_api.py` | any module 01–05 created (import them) |
| 14 | `src/hallucinote/sync/push/clips.py`; new `tests/unit/sync/test_push_clips_reverse.py` | `src/hallucinote/sync/pull/clips.py` |
| 15 | new `src/hallucinote/tools/sample_lens.py`, new `skills/sample-lens/SKILL.md`; new `tests/unit/tools/test_sample_lens.py` | `src/hallucinote/cli.py`, `docs/`, every other skill |

**Model per chunk** — the owner's rule (COLLAB-TURN): Opus 5 for mechanical parts, Fable
5.1 where the result is materially better for it. **Fable — 02, 03, 04, 05, 06, 09, 10,
13, 15**: DSP where the wrong default is inaudible until the song is wrong, a persisted
format, a generator whose musical judgment must stay out of it (R4.6), and the lens prose a
cold agent reads. **Opus — 01, 07, 08, 12, 14** (and 11 when dispatched): bounded wiring
against recorded contracts, with tests.

**What each delegate returns:** its branch name, a diff summary, the exact verification it
ran (its ceiling, below), every default or wording it had to *decide* rather than take
from this plan or the requirements (marked **proposed** — the seam nobody else checks),
and anything it left for integration. Delegates do **not** run the Critic, tick Status
boxes, touch `project-state.yaml`, write the change log, open PRs, or edit docs.

**Verification ceiling per delegate:** `python -m pytest <its own new test files> -q`,
plus `ruff check <its own files>` and `mypy <its own files>`; 01, 12 and 15 additionally
run their tool's `main()` once on a synthesized WAV written to the scratchpad. **Never the
full suite** (the ratified `Delegate verification` row). Audio tests use
`tests/unit/audio/fixtures.py` (`sine`, `pink_noise`, `silence`); no delegate commits an
audio file.

**Coordinator integration.** Merge each wave-A branch `--no-ff` into `plan/smp-6v2k-w2`
as it returns (any order — disjoint). After each merge: `python -m pytest` with no path
argument, `ruff check .`, `mypy`, then `/prawduct:critic chunk` scoped to that chunk's
section, findings resolved before the next merge. Read the twelve reports *together* for
proposed-wording drift and duplicated helpers across `src/hallucinote/features/` and `src/hallucinote/spectral/` before
wave B is briefed. Wave B repeats the shape with three. Chunk 16's review is the one
`/prawduct:critic cumulative` against `origin/develop...HEAD`; the PR opens into
`develop` with `/prawduct:pr`.

---

## Build Chunks

### Chunk 00: contracts, extras, the slot floor

**Type:** code · **Visual change:** no · **Owner:** coordinator, before any dispatch.

**Spec.** Land the modules every brief points at, so no delegate has to guess a shape or
edit a shared file:

- new `src/hallucinote/assets/types.py` — `Source(name, path: Path, checksum: str,
  sample_rate: int, channels: int, duration_s: float)`; `Derived(path, address, record_path,
  source_checksum, chain: tuple[Transform, ...], reference_fingerprint: str | None)`;
  the `Transform` protocol (`kind: str`, `params() -> dict`, `apply(audio, sr, ctx) ->
  ndarray | list[ndarray]`). Validation only.
- new `src/hallucinote/features/types.py` — `FeatureStream(name, times_s, values,
  confidence, units)` with shape validation; `BeatStream(beats, values, confidence,
  units)`; `Segment(start_s, end_s, kind, label)`; `FeatureEvent(time_s, kind, payload)`;
  the `BeatMap` protocol (`seconds_to_beats`, `beats_to_seconds`) that
  `src/hallucinote/audio/section.py`'s `BeatSampleMap` satisfies once wrapped with a sample rate (chunk 02
  writes the wrapper). `FeatureStream.to_beats(beat_map) -> BeatStream` lives here because
  it is pure indexing.
- new `src/hallucinote/spectral/types.py` — `SpectralField(freqs_hz, times_s, magnitude,
  origin: 'symbolic' | 'measured', resolution: ResolutionReport, fingerprint: str)`;
  `ReferenceSchedule` = ordered `(start_beat, end_beat, nodes: tuple[NodeRef, ...])`
  where `NodeRef` is `('track', id) | ('return', id) | ('master',) | ('minus', target_track_id)`
  — the engine-side inverse of the wire `NodeAddr` (`src/hallucinote/db/queries.py`'s `get_node_path` is the
  resolver 03 uses); `MaskParams(polarity: 'carve' | 'vocode', harmonic_depth: int,
  notch_width_cents: float, depth_db: float (validated ≤ 40 — never to silence, R3.4),
  smoothing_s: float)`; `ResolutionReport(n_fft, hop, bin_hz, achieved_cents_at_hz(...))`.
- `pyproject.toml` — optional extra `audio-stretch-ab = ["pyrubberband>=0.4"]`; one
  `uv lock`. (The `audio-separation` extra lands with chunk 11 when it is dispatched.) `--all-packages` does not
  install extras, so the plugin's cold sync and `mcp_config.py`'s timeout are untouched.
- **#473, the slot floor.** `src/hallucinote/db/mutations/clips.py` refuses `slot < 1` with a teaching
  error (Live's `clip_index` is 1-based on this wire); `src/hallucinote/db/schema.sql` adds
  `CHECK (slot >= 1)` on `clips`; `src/hallucinote/db/connection.py` — SQLite cannot add a CHECK by
  ALTER, so the migration is the mutator (document it beside `_ADDED_COLUMNS`).
- **#237 R7, the stale comment.** `src/hallucinote/db/connection.py:311-315` still says reverse is "a
  playback parameter, not a derived file"; make it say what `schema.sql` and probe row 14
  say.
- new `tests/unit/test_sample_packages_isolation.py` — a subprocess imports every module
  under new `src/hallucinote/assets/`, new `src/hallucinote/features/`, new `src/hallucinote/spectral/` and asserts no `hallucinote.db`,
  `hallucinote.sync` or `hallucinote_mcp` module loaded, **except** new `src/hallucinote/spectral/symbolic.py`
  and new `src/hallucinote/spectral/measured.py`, which read the DB and captures by design and are listed by
  name. The generator-purity test's shape.

**Tests.** The isolation test (it will list only `types.py` modules until wave A lands —
that is the point); slot-floor tests in a new `tests/unit/db/test_clip_slot_floor.py`;
the schema canary flips and is re-recorded.

**Done when:** (1) tests green on the full no-path run; (2) committed on
`plan/smp-6v2k-w2`; (3) twelve worktrees and briefs written; then dispatch.

---

### Chunk 01: asset store — ingest, normalize, manifest

**Type:** code · **Foreign API:** `ffmpeg` CLI (decode only) · **Visual change:** yes —
the ingest tool's output is what a user reads to know what happened to their file.

**Spec.** R1.6 and D5, D8, D9. `hallucinote asset add <file> --name <name> --note "<what
the line is>" --origin "<title / medium / scene>"` (the CLI registration is chunk 16's;
this chunk ships `src/hallucinote/tools/asset_ingest.py` with a `main(argv)`):

- **Normalize** into new `assets/sources/<name>.wav`: WAV, FLAC and AIFF through `soundfile`;
  MP3, M4A and anything `soundfile` refuses through `ffmpeg -i <path> -f wav -` as a
  list-argument subprocess (no shell), decoded to PCM and written by `soundfile` — one
  canonical container regardless of input. Sample rate and channel count are **kept**
  (resampling is a transform, not an ingest step; the analysis loader in chunk 02
  resamples on read). Float32 subtype. The source is never edited in place afterwards.
- **Provenance** into new `assets/manifest.json` per D8, `manifest_version: 1`. `store.py`
  reads and writes it atomically (write-temp-rename); `manifest.py` validates a loaded
  manifest and refuses an unknown version with a teaching error.
- **Guard** per D9 (25 MB warn, 100 MB refuse without `--allow-large`).
- A name already in the manifest refuses unless `--replace`, and `--replace` records the
  prior checksum in the entry's `superseded` list — the source is immutable, its slot is
  not.
- `store.py` also answers `sources(song_dir) -> list[Source]` and `verify(song_dir)`
  (every manifest entry's file exists and its checksum matches — the check `compat` will
  call from #501 later).
- Say once, in the tool's `--help` and in the docstring: film dialogue is somebody's
  copyright; clearance is the user's call (D5).

**Tests.** Ingest a synthesized WAV; ingest a synthesized FLAC (round-trip through
`soundfile`) ; the ffmpeg path with `ffmpeg` faked by a shim on `PATH` that emits a WAV
(never a real decode in tests); duplicate-name refusal and `--replace`; the size guard;
`verify` catching a modified file.

**Done when:** (0) `verify-api` — run real `ffmpeg -i x.mp3 -f wav -` once against a
scratch MP3 to record the exact invocation and exit shape in the module docstring;
(1) tests green; (2) branch + report returned.

---

### Chunk 02: the second front door — a sample loader and its feature streams

**Type:** code · **Foreign API:** librosa (`pyin`, `onset_strength`) · **Visual change:** no

**Spec.** R2.1 and R2.2 under D7.

- new `src/hallucinote/audio/sample_io.py` — `load_sample(path, *, target_sr: int | None = None) ->
  SampleAudio(audio: (n, 2) float32, sr, source_sr, source_channels)`. Any rate, any
  channel count, any format `soundfile` reads: mono is duplicated to two channels,
  more-than-two is downmixed by equal-power sum, resampling via
  `scipy.signal.resample_poly`. The output is the array shape every module in `src/hallucinote/audio/`
  already takes; `src/hallucinote/audio/io.py` is untouched and its refusal stands.
- new `src/hallucinote/features/f0.py` — `f0_contour(audio, sr, *, fmin, fmax) -> FeatureStream` via
  `librosa.pyin`, values in Hz with `confidence` = voiced probability; unvoiced frames
  carry `nan`, never 0.
- new `src/hallucinote/features/formants.py` — `formant_tracks(audio, sr, n_formants=3) -> list[FeatureStream]`
  by LPC over 25 ms windows (`scipy.signal` — pre-emphasis, Hamming, autocorrelation
  Levinson, roots → frequencies with bandwidth < 400 Hz), in Hz.
- new `src/hallucinote/features/energy.py` — `energy_envelope(audio, sr, hop_s) -> FeatureStream` (RMS in dB
  relative to full scale) and the spectral descriptors already implemented, re-exposed as
  streams over the same hop: centroid, flatness, rolloff via `src/hallucinote/audio/timbre.py`'s helpers,
  bark-band energies via `src/hallucinote/audio/bark.py`.
- new `src/hallucinote/features/segments.py` — `onset_segments(audio, sr) -> list[Segment]` from
  `src/hallucinote/audio/onsets.py` (reuse `detect_onsets_with_strength`), and `phrase_segments(...)` —
  silence-bounded phrases using the energy envelope with a hysteresis floor. Also the
  syllable-rate reading (onsets per second inside a phrase).
- new `src/hallucinote/features/beatmap.py` — `beat_map_for_placement(tempo_segments, start_bar, ...) ->
  BeatMap` wrapping `src/hallucinote/audio/section.py`'s `BeatSampleMap` so that a stream in seconds maps
  to beats **through the clip's placement and the song's tempo map** — a re-tempo does not
  invalidate the extraction (R2.2).

**Tests.** A synthesized vibrato sine's F0 tracks its center within 1 %; a synthesized
two-formant vowel (two resonant filters over a pulse train) recovers both within 10 %;
onsets on a pulsed tone match the pulse period; the beat map round-trips seconds↔beats
across a tempo ramp; a 22.05 kHz mono file loads as 44.1 kHz stereo.

**Done when:** (0) `verify-api` — read librosa's `pyin` signature from the installed
package, not the docs, and record the version; (1) tests green; (2) returned.

---

### Chunk 03: spectral fields — symbolic from the score, measured from the capture set

**Type:** code · **Visual change:** no

**Spec.** R2.5, R2.6, R3.2, R3.3, R3.5, R3.6, and the fingerprint half of R3.7.

- new `src/hallucinote/spectral/symbolic.py` — `symbolic_field(conn, schedule: ReferenceSchedule,
  beat_map, *, freqs_hz, times_s, harmonic_depth, tuning) -> SpectralField`. For each
  schedule span, read the sounding notes of the referenced nodes through `src/hallucinote/db/queries.py`
  (a track node → its clips' notes over that span; a return node → the tracks that send
  to it; `master` → every track; `('minus', t)` → every track but `t`), expand each pitch
  to `harmonic_depth` partials (through `src/hallucinote/tuning/mapper.py` when the song carries a tuning),
  place unit magnitude at each partial for the note's duration. Exact, instant,
  timbre-blind — and it says so in `origin`. The field's `fingerprint` is
  `clip_fingerprint` over the notes it read, joined with the schedule.
- new `src/hallucinote/spectral/measured.py` — `measured_field(capture_set: CaptureSet, schedule,
  beat_map, *, n_fft, hop) -> SpectralField`. Resolve each node to the capture set's
  surfaces (`src/hallucinote/audio/io.py`'s `load_capture` — unchanged); `('minus', t)` is the stem-sum of every
  other stem, reusing `src/hallucinote/audio/reconcile.py`'s summation rather than re-implementing it
  (R3.5). STFT magnitude, time axis in seconds via the capture's own beat map; a node with
  no surface in the set, or a surface whose alignment cannot be established from the
  capture manifest, **refuses** (R3.6). Fingerprint: the take id plus
  `src/hallucinote/audio/codeversion.py`'s `disk_signature()`.
- new `src/hallucinote/spectral/schedule.py` — construction and validation of `ReferenceSchedule`
  (non-overlapping, ascending, at least one node per span), `schedule_from_sections(...)`
  so a reference can be authored per section, and `node_ref_from_addr(...)` mapping the
  wire `NodeAddr` dict to a `NodeRef` (R3.2, through `src/hallucinote/db/queries.py`'s `get_node_path`).

**Tests.** A one-note score yields a field with energy at exactly its partials and
nowhere else; the `minus` node on a three-stem synthesized capture equals the sum of the
other two; a schedule with overlapping spans refuses; an unaligned surface refuses.

**Done when:** tests green; returned.

---

### Chunk 04: one field, one mask, a polarity — carve and vocode on arrays

**Type:** code · **Visual change:** no

**Spec.** R3.1, R3.4, R3.8.

- new `src/hallucinote/spectral/ops.py` — `build_mask(field: SpectralField, params: MaskParams, *, bark) ->
  Mask` (time-varying, in the field's own bins): for each reference bin with energy, a
  notch of `notch_width_cents` scaled by that band's bark width, depth `depth_db`,
  smoothed over `smoothing_s`; `polarity='carve'` attenuates where the reference has
  energy, `'vocode'` keeps only there. `apply(target: ndarray, sr, mask, *, n_fft, hop)
  -> ndarray` — STFT the target, resample the mask onto the target's time/frequency grid,
  multiply, inverse-STFT against the original phase. **One function, one parameter apart**
  — there is no separate vocoder. Any `MaskParams` field may be an array aligned to the
  field's time axis (R3.4: automatable) — scalar or per-frame, same code.
- new `src/hallucinote/spectral/resolution.py` — `choose_resolution(lowest_hz, sr) -> ResolutionReport`
  and the multi-resolution path: below a configurable knee (default 200 Hz) the op runs a
  second, longer STFT for the low bins and stitches; where the requested `notch_width_cents`
  at the lowest reference pitch is narrower than the achieved bin width, the report says
  what was achieved and the op **does not claim** the requested precision (R3.8).

**Tests.** Carving a synthesized two-tone target against a field containing one of the
tones attenuates that tone by ≈ `depth_db` and leaves the other within 0.5 dB; vocode is
the complement; depth is capped (a 60 dB request validates to a refusal, per the type);
a 55 Hz reference at 2048/512 reports its achieved width honestly and the long-window
path narrows it.

**Done when:** tests green; returned.

---

### Chunk 05: recipes — transforms and the content-addressed derived cache

**Type:** code · **Foreign API:** librosa (`effects.time_stretch`, `effects.pitch_shift`) ·
**Visual change:** no

**Spec.** R1.7, D2, D4, D10, D11 — and the persisted format's consumer questions are in
D10, elicited before the fields were designed.

- new `src/hallucinote/assets/transforms.py` — frozen dataclasses `trim`, `fade`, `normalize`, `reverse`,
  `pitch_shift(semitones, formant_preserve=False)`, `stretch_to_bars(bars, bpm)`,
  `chop_at_onsets(min_gap_s)` (uses new `src/hallucinote/features/segments.py`; yields a list), each
  implementing the `Transform` protocol. Backend: librosa; `formant_preserve=True`
  refuses with a teaching error naming `hallucinote stretch-ab` (chunk 12) until R6.2 is
  decided. Every transform records `params()` exactly — that dict is what goes into the
  address.
- new `src/hallucinote/assets/derived.py` — `address(source, chain, reference_fingerprint, backend) -> str`
  (sha256, D10); `derive(source, chain, *, song_dir, reference_fingerprint=None) ->
  Derived`: compute the address, return the cached file if present **and its record's
  output checksum matches**, else run the chain, write new `assets/derived/<hash>-<slug>.wav`
  and `<hash>.json` (the record: source name and checksum, chain, backend and library
  versions, reference fingerprint, output checksum, created-at), then return. Tolerance
  for R6.3: a record whose library version differs from the running one is **still valid**
  (the address includes the version that made it; the file is cached precisely so a
  version bump does not force a re-render), and `derived verify` reports such files as
  *made-by-older-backend*, never as stale.
- new `src/hallucinote/assets/recipes.py` — `Recipe(source_name, chain)` value object, `prune(song_dir)`
  listing derived files no current recipe addresses (the orphan list; deletion is the
  user's), `verify(song_dir)`.

**Tests.** Same source + same chain → same address, byte-identical second call with no
re-run (assert the transform's `apply` is not called); any parameter change → new
address; `reverse` of `reverse` equals the source; `chop_at_onsets` on a pulsed tone
yields one file per pulse; a modified derived file fails `verify`; the record round-trips.

**Done when:** (0) `verify-api` — read librosa's `time_stretch` / `pitch_shift` signatures
from the installed package; (1) tests green; (2) returned.

---

### Chunk 06: intelligibility — the speech band over the bed, per turn, measured

**Type:** code · **Visual change:** no

**Spec.** R5.3 as **measurement** under D15: the masking analyzer re-framed for one
element against everything else.

- new `src/hallucinote/audio/intelligibility.py` — `measure_intelligibility(speech: Surface, bed: Surface,
  sr, *, turns: list[Segment]) -> list[TurnIntelligibility]`: per turn, the speech-band
  (300–3400 Hz, split into the bark bands that cover it) level of the speech surface over
  the bed's level in the same bands, plus the masked fraction from
  `src/hallucinote/audio/masking.py`'s spreading model with the speech as the target — numbers, per turn,
  per band. No threshold, no `Finding`.
- `src/hallucinote/audio/report.py` — `TurnIntelligibility` and its serializer; a
  `SectionMetrics.intelligibility: list[TurnIntelligibility] | None` field. Additive.
  **Do not bump `SCHEMA_VERSION`**; the coordinator decides at integration.
- `src/hallucinote/audio/analyze.py` — compute it when the declared song names a **speech track** (a new
  optional `DeclaredSpeech(track_name)` beside `DeclaredReverbSend`), with turns from the
  audio placements on that track; otherwise the field is `None`.

**Tests.** A synthesized voiced band over pink noise at three SNRs reports monotonically
rising masked fractions; a turn with no bed reads zero masking; the report round-trips
with the field present and absent.

**Done when:** tests green (including `test_report.py` if edited); returned.

---

### Chunk 07: a sampler gets its sample — `assign_sample`, push, capture (#330)

**Type:** code · **Foreign API:** Live Object Model (`SimplerDevice.replace_sample`,
probe row 18) · **Visual change:** no · **Operator-gated:** the live "Done when" is
chunk 17's.

**Spec.** #330's design, unchanged — it was written against the surface row 18 confirmed:

- `hallucinote_mcp/src/hallucinote_mcp/actions/device.py` — new action `assign_sample` (parent addressing + `device_index` /
  `device_path`, `sample_path` absolute), registered beside `load`. Re-callable.
- `hallucinote_mcp/src/hallucinote_mcp/handlers/device.py` — `assign_sample_handler`: resolve through `_resolve_device_node`,
  call `replace_sample`, map "not a sampler" and "bad path" to teaching errors.
  `info_handler` gains `sample_file_path` when the device exposes `.sample`.
- `src/hallucinote/sync/push/devices.py` — in `_emit_device_calls`, after the load call, for a row with
  non-NULL `audio_file`: resolve via `paths.resolve_audio_path`, existence-check (a
  missing file fails that device loudly at plan time), diff against the probed live
  sample path, emit `assign_sample` only when it differs. Order it **before** the param
  writes (probe row 18 did not record whether `replace_sample` resets parameters; chunk 17
  checks, and ordering assignment first is safe either way). `audio_file` on a class that
  cannot host a sample fails at plan time naming Simpler.
- `src/hallucinote/capture.py` — `_capture_devices_for_parent` reads `sample_file_path` off `info` for
  sampler-class devices and writes `entry["audio_file"]` in portable form.

**Re-vendor.** Both handler files are `_FINGERPRINT_PATHS` entries; the fingerprint
flips. Chunk 17 re-vendors once for the wave.

**Tests.** Handler tests against an inline fake (as the existing device tests do): assign
to a Simpler, non-sampler → teaching error, bad path → teaching error, `info` reports the
path. Planner tests: emitted when set; **not** emitted when the live path already
matches; missing file → per-device failure; nested Simpler in a rack gets the right
`device_path`. Capture test: portable form, round-trips through replay.

**Done when:** (0) `verify-api` — probe row 18 is the contract; (1) tests green;
(2) returned; live: chunk 17.

---

### Chunk 08: pull links what it ingests (#507)

**Type:** code · **Visual change:** no

**Spec.** D14. In `src/hallucinote/sync/pull/clips.py`, where an Ableton-only audio slot becomes a DB row
(`create_audio_clip`), also call `link_db_to_ableton` for that row and slot in the same
mutation batch, so the next push's `clip_at` finds it and conforms in place. Where a row
already exists and pull updates it, leave links alone (push owns reconciliation of
existing links). Dry-run previews the link write like every other mutation.

**Tests.** Ingest → the link row exists and points at the slot; a subsequent planner call
(`plan_push_clip`) against a fake probe showing the same clip plans conforms, **not** a
delete-and-recreate; dry-run writes nothing.

**Done when:** tests green; returned.

---

### Chunk 09: the follower — an F0 contour becomes a part

**Type:** code · **Visual change:** no

**Spec.** R4.1 under R4.6, bounded by #281's finding F3 (clip pitch-bend envelopes are
unreachable at Live's C++ boundary; `note_expression` pitch is the reachable
approximation). `src/hallucinote/generators/follow.py` — `follow_pitch(stream: BeatStream, *,
key: Key | None, register: tuple[int, int], min_note_beats, confidence_floor, bend:
'none' | 'note_expression') -> GeneratorOutput`:

- Segment the contour into notes where it dwells (median pitch over ≥ `min_note_beats`
  with confidence ≥ floor); quantize to `key` when given — **when `key` is `None` the
  contour's own pitch classes are kept**, which is how "does the music lead?" stays the
  author's choice (open question 3, R4.5/R4.6: a parameter, not a default).
- Emit tagged notes (`tag='follow'`) and, for `bend='note_expression'`, per-note pitch
  envelopes from the residual contour, in the `EnvelopeDict` shape `src/hallucinote/generators/envelopes.py`
  already emits.
- Pure: no DB, no MCP; the purity test covers it.

**Tests.** A stepped synthetic contour yields exactly its steps; a glide yields one note
with a bend; `key=None` preserves an out-of-key pitch that `key=C major` would move;
unvoiced gaps yield rests, not zero-pitch notes.

**Done when:** tests green; returned.

---

### Chunk 10: feature events with musical gates

**Type:** code · **Visual change:** no

**Spec.** R4.2's detector primitives, and R2.3's precondition (an event list is what the
lens shows on bars). `src/hallucinote/features/events.py`:

- `Gates(voiced_only, energy_floor_db, dwell_s, min_spacing_s)` — the four gates the
  requirement names, all required, no defaults that silently fire on real speech.
- `scale_tone_crossings(f0: FeatureStream, *, scale, gates) -> list[FeatureEvent]` — the
  worked example: an event where the tracked pitch enters a scale tone's ± band and
  dwells. `onset_events`, `energy_threshold_events` — the two generic detectors.
- `events_to_beats(events, beat_map) -> list[FeatureEvent]` in beats; a `grid_delay`
  helper that snaps an event onto the next grid position (the "delayed onto the grid"
  half of the cascade example). The cascade *gesture* itself is a song's composition and
  is not built here (L5).

**Tests.** A synthesized glide through a scale fires once per tone with dwell, and
continuously without gates (the failure the gates exist for, asserted as the contrast);
spacing suppresses a double fire; unvoiced frames never fire under `voiced_only`.

**Done when:** tests green; returned.

---

### Chunk 11: separation behind an extra (#266) — DEFERRED, not dispatched

**Type:** code · **Foreign API:** demucs · **Visual change:** no

**Spec.** R2.4 as an optional path. `src/hallucinote/audio/separation.py` — `separate_stems(audio, sr)
-> dict[str, ndarray]` (`vocals`, `drums`, `bass`, `other`) via HT-Demucs v4, imported
lazily inside the function; a missing extra raises a teaching error naming
`uv sync --extra audio-separation`. A `backend` seam so tests can inject a fake.

**Why cut-first:** open question 1 (how clean are the sources) decides whether this is
on the critical path or an optimization, and `torch` is the heaviest dependency this
repo would ever lock. It is in the plan because the requirement is written and the
partition has room; drop it first if the fan-out should narrow.

**Tests.** The fake backend path; the missing-extra error; never a real model run.

**Done when:** tests green; returned. Real-audio run: an operator-verification entry,
user's ears (Q1).

---

### Chunk 12: the stretch / pitch A/B harness for R6.2

**Type:** code · **Foreign API:** pyrubberband (optional) · **Visual change:** yes — its
output is a set of files the user listens to and a table they read.

**Spec.** R6.2 says the formant-preservation decision is made against an audible A/B on
real dialogue, before R4.3 is built. `src/hallucinote/tools/stretch_ab.py` — `main(argv)`: given a source
WAV, a stretch ratio and a semitone shift, render the same transform through every
available backend (librosa always; Rubber Band with `--formant` when `pyrubberband` and
the binary are present, reported absent otherwise) into `<out>/<backend>-<params>.wav`,
and print a table of what was rendered, with the spectral-centroid delta per file
(`src/hallucinote/audio/timbre.py`) as the one number that hints at formant smear. The decision is the
user's; the harness only makes it hearable.

**Tests.** With librosa only, renders one file and reports rubberband absent; with a fake
rubberband module injected, renders two; the table lists exactly the files written.

**Done when:** tests green; returned. Then `.prawduct/operator-verification.md` gains the
listening entry (chunk 16 writes it).

---

### Chunk 13: carve and vocode as recipes, with the reference in the address *(wave B)*

**Type:** code · **Visual change:** no

**Spec.** Composes 01, 03, 04, 05 into the public surface D11 names.

- new `src/hallucinote/assets/__init__.py` — `source(song_dir, name) -> Source` (manifest lookup via 01),
  `derive(source, *chain, song_dir=..., reference_fingerprint=None) -> Derived` (05),
  re-exported transforms. This is the only module `build.py` imports.
- new `src/hallucinote/assets/transforms_spectral.py` — `carve(schedule, params, *, field='symbolic' |
  'measured', capture=None)` and `vocode(...)` as `Transform`s whose `apply` builds the
  field (03) and runs the op (04); `params()` includes the field's **fingerprint**, so it
  enters the address (R3.7, D10). `field='measured'` with no capture refuses; the two
  routes are never substituted for each other silently (R6.1). The declared pipeline
  order of R4.5 is just the order of `derive` calls in `build.py` — nothing to build; the
  docstring says so.

**Tests.** `derive(src, carve(...))` on a synthesized target against a one-note symbolic
field attenuates that partial; changing a note in the referenced clip changes the
address; `field='measured'` without a capture refuses; the public API resolves a manifest
entry to a `Source`.

**Done when:** tests green; returned.

---

### Chunk 14: `reverse=1` materializes through the derived cache (#237) *(wave B)*

**Type:** code · **Visual change:** no · live "Done when": chunk 17.

**Spec.** #237 R3–R5. In `src/hallucinote/sync/push/clips.py`, **replace** the `reverse=1` refusal: resolve
the row's `audio_file` to a `Source` (13's API — a file not in the manifest is wrapped as
an unmanifested source with a checksum computed on the spot), `derive(source, reverse())`,
and plan the create against the derived path. Flipping the flag flips the address, so a
push after the flip points the clip at the right file or fails loudly (R5). The sampler
route is the same derived file assigned by chunk 07's emitter when `devices.audio_file`
belongs to a row with `reverse=1` — no new column (#237 R6). Also re-word the #507 alert
now that pull links: it fires only for a genuinely unlinked occupied slot.

**Tests.** A `reverse=1` row plans a create against a derived path whose record chain is
`reverse`; flipping to 0 plans against the source; a second push plans nothing; a missing
source still fails loudly.

**Done when:** tests green; returned; live: chunk 17.

---

### Chunk 15: the sample lens — inspect a line against bars, and the skill that runs it *(wave B)*

**Type:** code · **Visual change:** yes — the whole deliverable is what the agent reads
aloud to the user.

**Spec.** R2.3, #511. `src/hallucinote/tools/sample_lens.py` — `main(argv)`: given a song and a source name
(or a bare file plus `--bpm`), load through 02's front door, compute F0, formants,
energy, segments, and the events of a named detector with explicit gates (10), map them
to beats through the clip's placement (02's beat map), and **render** a reading a producer
can compose against: the implied pitch centre and its relation to the song's key
(`src/hallucinote/theory/`), phrase lengths in beats at the song's tempo, syllable rate, and *where the
detector would fire, against bars* — before a note of it is heard. `--json` for the
agent. Neutral: readings, never verdicts (the lens invariant `src/hallucinote/melody/` and `src/hallucinote/recurrence/`
already hold).

new `skills/sample-lens/SKILL.md` — when to run it (before composing to a line; when
tuning a detector), what to read back, and the one rule: the reading is a proposal, the
key and the register stay the user's (R4.6).

**Tests.** Renders a synthesized vibrato line at 92 bpm with the expected phrase count
and pitch centre; `--json` round-trips; a detector with no gates refuses.

**Done when:** tests green; the tool run once on a synthesized line and its output read
for legibility; returned. The skill's wiring into `/song-workflow`, the primer and
`docs/` is chunk 16's.

---

### Chunk 16: the docs say what is true, the contract artifacts track, the CLIs are wired

**Type:** cumulative-final · **Visual change:** yes (docs) · **Owner:** coordinator.

**Spec.**

- `src/hallucinote/cli.py` — register `asset add|verify|prune`, `sample-lens`,
  `stretch-ab`.
- `docs/song-authoring-conventions.md` — "Referencing a sample" gains the asset store,
  the recipe surface (D11), and reverse; its "What is not there yet" paragraph shrinks to
  what is still true (R4.3, #509).
- `docs/capability-truth.md` — the *Audio material* row says: ingest and provenance,
  features and the lens, symbolic and measured carve, reverse via derived, sampler
  assignment — each at the maturity chunk 17 recorded (built-and-unit-tested vs live).
- `.prawduct/artifacts/authorship-model.md` open problem §2 closes (ergonomics now have a
  home); `masking-analyzer-spec.md` gains a pointer to the intelligibility measurement.
- `docs/song-workflow.md`, `skills/song-workflow/SKILL.md`, the primer — `/sample-lens`
  wired in (a skill not on the spine is undiscoverable — standing learning).
- `docs/research/audio-first-class/producer-practice.md` — one paragraph on the copyright
  note (D5), if it is not already there.
- `.prawduct/operator-verification.md` — the wave-2 section: chunk 17's boxes, the R6.2
  listening entry, the separation run.
- Change-log entry (scope `SMP-6V2K-W2`, no `release=`), backlog closes in the ship-stamp
  commit (#510, #511, #330, #237, #507, #473; #266 if 11 shipped), `SCHEMA_VERSION`
  decision recorded.

**Done when:** (1) full no-path suite, ruff, mypy green; (2) committed, then
`/prawduct:critic cumulative` against `origin/develop...HEAD`, findings resolved;
(3) ticked.

---

### Chunk 17: the Live session — sampler live, reverse live, the #509 and Sampler probes

**Type:** code · **Foreign API:** Live Object Model (Live 12.4.x) · **Visual change:** no
· **Operator-gated:** yes — a running Live, the plugin re-vendored
(`/hallucinote:ableton-mcp-install`, fingerprint flipped by chunk 07), a human at the
machine, the scratch song `hallucinote-songs/songs/audio-verify/` extended.

One sitting, batched so the operator is asked once:

1. **Sampler assignment (07).** A `build.py` with a Simpler row carrying `audio_file`
   pushes; the device reads back the path; a second push emits no assignment; a
   hand-dropped sample survives capture → replay → push. Record whether
   `replace_sample` resets parameters (the ordering in 07 is safe either way; the record
   settles whether it must stay).
2. **Sampler (`MultiSampler`) probe.** Does it expose `replace_sample` or an equivalent?
   Verdict rewrites 07's teaching error or lifts it.
3. **Reverse via derived (14).** A `reverse=1` clip places and plays backwards; flipping
   it re-points the clip.
4. **#509 probe.** On an arrangement audio clip: is `end_marker` / length writable after
   `duplicate_clip_to_arrangement`, and after a direct create? Recorded on #509; its
   build is drawn there.
5. **A first hearing.** One real line ingested (01), its lens read (15), one symbolic
   carve pushed (13), one follower part pushed (09) — the acceptance the whole plan is
   for, and the moment the Requirements Confidence rises or the shape is corrected.

**Done when:** every question answered with a recorded call and its literal response in
`lom-probe-results.md`; every box in `operator-verification.md`'s wave-2 section ticked
or marked unreachable with the reason; `capability-truth.md` re-rated by what ran.

---

## Early Feedback Milestone

**Milestone chunk:** 15 (with 01, 02, 10 behind it). **What the user can do:** drop a
line in, run the lens, read where it sits and where a detector would fire — before any
carve or follower exists. Chunk 17 §5 is the first *hearing*.

## Governance Checkpoints

**Commit & PR cadence:** one integration branch; each delegate branch merged `--no-ff`
after its narrow run, followed by the coordinator's full run and a `chunk` Critic scoped
to that chunk; chunk 16's cumulative review is the PR gate; the PR opens into `develop`
when the user asks.

- **After chunk 00:** the three type modules read together — are they the contract, and
  nothing more? A delegate that needs to edit one is the signal the partition was drawn
  wrong; stop and redraw rather than let two briefs edit `types.py`.
- **Wave A integration (after the twelfth merge):** the cross-delegate read — duplicated
  helpers across `src/hallucinote/features/` and `src/hallucinote/spectral/`, proposed defaults that disagree (window
  sizes, hop, the speech band), and whether 06's report field bumps `SCHEMA_VERSION`.
- **Before wave B briefs:** re-check the partition against what actually returned.
- **Chunk 16 (cumulative):** full-bundle review; verify every teaching error in this wave
  names a recovery; verify no audio file entered the repo.
- **Chunk 17:** the hearing. What the user says there is the input to the next plan.
