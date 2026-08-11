# EFFORT-S-BURNDOWN — Build Plan

**Goal:** in one `fix/` branch, burn down every `effort:S` item open on
`brookstalley/hallucinote` (30 at branch time, 2026-08-11).

**Branch:** `fix/effort-s-burndown`

## Requirements Confidence: **High** (for the buildable set) / **N/A** (for the deferred set)

Each item carries its own problem statement, fix sketch and verifiable signal in
its GitHub issue — this plan does not restate them. What this plan adds is the
**triage**: which of the 30 an agent can actually close on this branch, and an
explicit disposition for every one it cannot. Nothing is silently dropped.

Two items (#318, #225) ship with a decision the issue leaves open at implement
time; both branches are fully specified in the issue and the choice is recorded
in the chunk's Done-when. One item (#274) offers "code OR a decision-record" —
the choice is recorded the same way.

## Triage — all 30 items

**Buildable on this branch (17):** 447, 445, 327, 326, 320, 318, 317, 316, 315,
314, 303, 264, 263, 274, 223, 225, 236

**Buildable but needs in-branch scoping first (3):** 233, 248, 252

**Blocked on upstream work that has not shipped (3)** — cannot be closed here;
each gets a disposition comment naming its blocker:
- **#268** envelope: mixer envelopes on audio *session* clips — gated on
  **CLP-AUD2** (session-view audio-clip placement). CLP-AUD1 chunks 01–02 are
  still unticked; CLP-AUD2 has no plan directory.
- **#256** device: flatten nested-rack devices in analysis extract — gated on
  recursive chain data from NODE-ADDR Chunk A. Chunk A shipped deep *addressing*
  (`device_path`), but `get_device_chains` is still one-level; the extract has
  nothing recursive to flatten.
- **#255** device: extract the shared plugin-discriminator — gated on the
  **W11-A** `hallucinote-core` shared package, which does not exist (`src/` holds
  only `hallucinote`). The lock-test already pins the two copies in sync, so
  there is no live drift risk to fix.

**Needs the user's ears, a second human, or a live Ableton probe (6)** — not
agent-buildable by construction; each gets a disposition comment:
- **#279** listening day (owner's ears — the item says so in its own body)
- **#242** melody by-ear calibration locks (same listening day)
- **#227** timbre/stereo threshold calibration (needs a render-jitter study in Live)
- **#305** forkability experiment (needs a second human on a second machine)
- **#311** relax quit-before-vendor (needs a macOS file-lock probe with Live running)
- **#281** probe Live 12.5+ pitch-bend/CC envelope support (needs Live 12.5+)

**Owner product decision (1):**
- **#308** polytempo in the schema vs. amending VISION.md — the item states
  outright that this is "a creative lock-in only the user can make — the agent
  flags it, never decides it." Left for the owner; the flag is re-raised.

## Work classification

Debt paydown, wide but shallow. Chunked by **blast radius**, not by issue
number, so each Critic pass sees one coherent surface. Docs/artifact chunks and
code chunks are kept apart so a doc-only chunk stays cheap.

---

## Chunk 1 — the PR #213 deferred-warning cluster (docs, skill, docstring)

Closes **#318, #315, #314, #316, #317**. These five were all deferred out of the
same PR #213 Critic review and touch the same story (the BAK-7D2V snapshot
durability contract). #318 decides `restamp`'s fate and #315 documents whatever
#318 leaves standing, so they must land together.

- **Type:** docs + one CLI surface decision
- **Critic mode:** chunk
- **Done when:**
  1. **#318 decided and executed.** Either `restamp` is deleted (subcommand +
     `capture.restamp_captured_at` + its tests) or it is kept and listed in
     `docs/snapshot-schema.md`'s `StaleSnapshotError` exits with its safety
     fence. The third state (present, unreferenced, undocumented) is gone.
  2. **#315** `capture_cli`'s module docstring enumerates every subcommand the
     parser registers, and a unit test asserts that set equality so it cannot
     drift again.
  3. **#314** in `skills/song-snapshot/SKILL.md`, the empty-diff `capture merge`
     fence sits *below* its trigger condition and yes/no consent prompt;
     `tests/unit/test_song_snapshot_empty_diff_bake.py` still passes.
  4. **#316** `boundary-patterns.md`'s Pull Planner section documents the
     two-channel contract (stdout JSON / stderr contract text the consumer MUST
     relay), stated as a consumer requirement and carried into the section's
     "When changing this surface" bullets.
  5. **#317** the BAK-7D2V closure note describes the shipped empty-diff **bake**
     (not the superseded re-stamp) and its check range matches the numbered
     checks in `.prawduct/operator-verification.md` — corrected on **closed
     issue #337**, NOT in `.prawduct/backlog.md`.
     **Resolved tension:** the issue (filed 2026-07-20) names the backlog file,
     but the 2026-08-10 cutover froze that file as the migration's source corpus
     under an explicit "preserve it verbatim" — it is what `verify-migration`
     and rollback read. The note migrated verbatim into #337, so #337 is the
     record a future scrub trusts and the frozen copy stays wrong as history.
     A grep of `.prawduct/backlog.md` will therefore still match the old text;
     that is the intended end state, not an undelivered item.

## Chunk 2 — stale citations + waiver hygiene

Closes **#445, #447, #320**. All three are "the tree says something that is no
longer true", spread across source comments, pragmas and a governing artifact.

- **Type:** chore
- **Critic mode:** chunk
- **Done when:**
  1. **#445** `git grep -n "backlog\.md" -- "*.py"` returns nothing outside
     `.prawduct/`; the user-facing MCP error string at `clip.py:358` no longer
     names any tracker; the quantize/groove comment no longer cites dropped
     GEN-2T8M.
  2. **#447** `grep -rn 'ok-broad-except'` returns 0 **tree-wide, not just in
     `*.py`** — the code sites AND every place that instructs the spelling
     (`CONTRIBUTING.md`, `project-state.yaml`, `project-preferences.md`). A
     sweep that stops at one file extension leaves the retired form being taught
     to the next contributor. Each of the 21 rewritten code sites carries a
     reason **specific to that catch**. A blanket reason string is a failure of
     this item, not a completion of it — any catch whose reason cannot be written
     honestly gets narrowed instead.
  3. **#320** every `songs/` path in `project-preferences.md` describes a
     workspace-relative location or is explicitly scoped to the `examples/`
     bounded exception (`examples/hallucinote.toml` has landed); no example
     command references a song absent from this repo.

## Chunk 3 — path resolution + compat-gate correctness

Closes **#327, #326**. Two real bugs where a check disagrees with the thing it
checks. Both are `src/hallucinote/sync|db` and both need regression tests.

- **Type:** bugfix
- **Critic mode:** chunk
- **Done when:**
  1. **#327** with a song dir in repo A on branch `main` and the process cwd in
     repo B on branch `feat/x`, `resolve_db_path(slug, root=<songs-root>)`
     returns `<song_dir>/<slug>-main.db`; `resolve_db_path(slug)` and
     `resolve_db_path(slug, root=...)` agree on the filename for the same song;
     a test pins the two-repo case. The DB-filename remap is called out in the
     change-log as a resolution-semantics change, not a pure bugfix.
  2. **#326** `_dry_run_key` includes `mode` and `case_sensitive`, and
     `_probe_browser_dry_runs` passes both into the browser search params, so the
     probe uses the matcher the loader will. A genuinely ambiguous substring
     query still reports `kind_ambiguous` — the fix must not become a rubber
     stamp. Tests pin both directions.

## Chunk 4 — push/capture robustness

Closes **#225, #264**. Both are push-path defects found in dogfood.

- **Type:** bugfix
- **Critic mode:** chunk
- **Done when:**
  1. **#225** a `set_chain_property` write against a disabled/locked chain-mixer
     parameter no longer manufactures a permanent phase halt. The fix option is
     chosen and recorded in the chunk close (capture-side `is_enabled`,
     planner-side pre-probe, or executor-side warning); a regression test pins
     the round-trip (capture → replay → push of an unchanged set is a clean
     no-op run).
  2. **#264** spurious-clip detection no longer relies on start-time alone, so a
     pre-existing clip sitting at exactly `dest_beats + source.length` cannot
     mask a new spurious clip. A test seeds that collision.

## Chunk 5 — self-ignoring artifacts + capture audit event

Closes **#303, #263**. Both are additive writes on the tool-output path.

- **Type:** feature
- **Critic mode:** chunk
- **Done when:**
  1. **#303** the render/analyze path writes `analysis/.gitignore` (`*`) when it
     creates `analysis/`, and the notes-push + snapshot paths self-ignore their
     state/backup files — a pre-bootstrap workspace stops surfacing these as
     committable with no manual root-`.gitignore` edit.
  2. **#263** `events.AUDIO_CAPTURED` exists and is emitted by the capture-success
     path with a `{captures_dir, manifest_seq, track_count}` payload, queryable
     through the existing `queries.get_events_for_song`.

## Chunk 6 — screen-recording grant + envelope confirmation lock

Closes **#223, #236**.

- **Type:** bugfix + test lock
- **Critic mode:** chunk
- **Done when:**
  1. **#223** `assert_capture_permission()` calls `CGRequestScreenCaptureAccess`
     on a denied preflight, so the OS prompt is actually raised. The existing
     actionable error path **survives**: on still-denied *or* newly-granted, the
     raised message still names the host app and states the relaunch
     requirement — the permission is read at process launch, so granting does not
     retroactively enable a running process. The fake CoreGraphics in
     `tests/unit/tools/test_capture_live_shot.py` covers denied→request→
     still-denied.
  2. **#236** a confirmation test pins that a `device_parameter` envelope on a
     sample-instrument MIDI track covered by its session clip routes to the
     sample-accurate `session_clip` path (it would fail if it regressed to the
     lossy perform path), plus the note-on ordering note (the breakpoint must sit
     at/just-before the trigger note-on so a phrase plays with its own window).
     The semantic-addressing half stays deferred on rule-of-three — that is the
     issue's own narrowing, restated here so it is not read as a silent drop.

## Chunk 7 — energy spectral correlate

Closes **#274**.

- **Type:** feature
- **Critic mode:** chunk
- **Done when:** either `MixReport.energy_realization.correlate_rho` carries a
  spectral correlate key computed over the windowed master and ranked by the same
  `realize_energy` Spearman path, **or** a decision record states loudness+density
  suffice with rationale. Whichever is chosen is recorded at chunk close.

## Chunk 8 — scoped-then-built: coherence guard, eval refresh, overview derivation

Closes **#248, #252, #233** — each needs a scoping call this chunk makes before
building. Any that the scoping shows is not S-sized on inspection gets re-sized
on the issue rather than half-built.

- **Type:** mixed
- **Critic mode:** chunk
- **Done when:**
  1. **#248** the taxonomy coherence pass is re-run against the siblings that
     have landed since 2026-06-03, and either records "no incoherence found" in
     `arrangement-model.md` or fixes what it finds.
  2. **#252** `canonical-priya.json` / `canonical-elena.json` are re-graded
     against the current two-sided melody rubric and canonicalized via
     `write_result(canonical=True)` with their transcripts — or, if the harness
     cannot be driven here, the blocker is recorded on the issue.
  3. **#233** the generate-vs-warn question is decided and the chosen direction
     built: the `<slug>.md` structure table + `build.py` docstring section layout
     are derived from `FORM`, or a build-time staleness warning fires when they
     diverge.

## Chunk 9 — dispositions for the 10 non-buildable items

No code. Every item in the blocked / needs-user / owner-decision buckets gets a
comment on its issue naming **why** it is not closed on this branch and **what
would unblock it**, so the burndown leaves no silent residue.

- **Type:** chore
- **Critic mode:** chunk
- **Done when:** each of #268, #256, #255, #279, #242, #227, #305, #311, #281,
  #308 carries a dated disposition comment, and this plan's triage section
  matches what the comments say.

---

## Status

- [x] Chunk 1 — PR #213 deferred-warning cluster (#318, #315, #314, #316, #317)
- [x] Chunk 2 — stale citations + waiver hygiene (#445, #447, #320)
- [x] Chunk 3 — path resolution + compat gate (#327, #326)
- [x] Chunk 4 — push/capture robustness (#225, #264)
- [x] Chunk 5 — self-ignoring artifacts + capture event (#303, #263)
- [x] Chunk 6 — screen-recording grant + envelope lock (#223, #236)
- [x] Chunk 7 — energy spectral correlate (#274)
- [ ] Chunk 8 — coherence guard, eval refresh, overview derivation (#248, #252, #233)
- [ ] Chunk 9 — dispositions for the 10 non-buildable items

**Context:** branch created from `develop` at `aa682e1`. Baseline 4986 passed /
2 skipped. Chunks 1-5 shipped; cumulative Critic `rev-20260811T130031Z-327d4a5c`
returned 0 blocking / 12 warning / 11 note, and its actionable findings were
fixed in one batch (tree-wide waiver sweep, the change-log's inverted
sibling-file mechanism, a stale re-stamp self-reference, `mode`/
`case_sensitive` structural validation, and a stderr signal for the DB-filename
remap). **#225 needed no code** — both halves had already shipped (capture-side
`is_enabled` decline at `capture.py:1435`, executor-side tolerance via
`_is_tolerated_failure`); it was verified and closed, not rebuilt.
Next: chunks 6-9.
