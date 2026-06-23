# Build plan — ARR-CMPHALT: comparator stops false-halting a faithful arrangement

**Backlog:** ARR-CMPHALT (`.prawduct/backlog.md`). Branch: `fix/arr-cmphalt-comparator` (worktree off develop).
**Refs:** `incoming-bugs/2026-06-22-arrangement-integrity-comparator-false-halts-samepitch-overlap-and-halfeps-bucketing.md`.
**Related:** ARR-PROJ (the safety net this regresses — PR #201), ARR-ORPHAN, ARR-FROMBUILD.

## Requirements Confidence

**Level:** High

**Why:** Both defects are root-caused against the real notes (64/64 mismatch cases explained by Live's same-pitch overlap-trim; 6 false missing/extra explained by `round()` half-eps instability) and confirmed in the code map. The fixes live entirely in one **pure, fully unit-testable** module (`sync/arrangement_compare.py`); the expected behavior is crisp. Both findings must land for the push to stop halting (each produces a HALT-tripping status independently), so they ship as one PR.

**Open assumptions / unknowns:**
- `[ASSUMPTION: normalize same-pitch overlaps on BOTH note sets (DB and Live), not DB-only | LOW impact | user can override]` — the report's preferred option; symmetric and idempotent (Live's side is already trimmed, so normalizing it is a no-op), which keeps the comparator robust if Live ever returns an un-trimmed read.
- `[ASSUMPTION: Finding 2 is fixed by tolerance-tolerant matching (a note present on both sides within eps of start + equal pitch + matching dur/vel must never land in BOTH missing and extra), mechanism chosen at build time | MED impact | user can defer mechanism]` — see Chunk 2; the *behavior* is fixed, the *mechanism* (surgical missing↔extra boundary-reconcile post-pass vs. replacing the integer bucket key with greedy nearest-neighbor pairing) is a build-time call validated cheaply against the pure module's test suite. Recommendation: the surgical post-pass (lower blast radius; preserves the existing same-(pitch,start) collapse).

**What would raise confidence:** N/A (High). The pure module means either Finding-2 mechanism is verifiable in minutes against the 10 existing + new unit tests.

## Root cause (bugfix discipline)

The ARR-PROJ integrity assert (`assert_arrangement_materialized`, `sync/arrangement_verify.py:228-253`) HARD-HALTs `execute --only arrangement` and fails `verify-arrangement` (exit 1) on a materialization that is in fact **faithful** — every note ONSET present in Live. `has_corruption()` (`arrangement_verify.py:74-81`) trips on any `diverged` status, and `compare_clip_notes` (`sync/arrangement_compare.py:100-140`) emits `diverged` from two independent comparator defects:

- **Finding 1 (load-bearing, 64/64 `mismatch`).** build.py authors overlapping **same-pitch** notes (a note whose duration runs past the next onset of the same pitch — `add_wildness` stacks, legato sustains, doublings). Live's clip model forbids same-pitch overlap, so `set_notes` **truncates the earlier note to end exactly at the next same-pitch onset** — faithful (onset survives, only `dur` clamped). The comparator models the same-(pitch,start) **collapse** (the `(pitch, _bucket(start))` grouping, lines 115-122) but **not the overlap TRIM**: a same-pitch *overlap* has *different* starts, so the two notes land in different groups; `_dur_vel_match` (lines 96-97) then fails `abs(a.dur - b.dur) <= eps` because Live clamped `dur` by whole beats → `mismatch` → HALT.
- **Finding 2 (6 false `missing`+`extra`).** `_bucket(start, eps) = round(start/eps)` (lines 89-93). `round()` is half-to-even; per-part `feel` offsets land some starts on an exact half-eps boundary (`start/eps = N.5`), and DB vs Live's round-tripped float differ sub-ULP, so the **same note** buckets to adjacent integers on the two sides → appears as BOTH `missing` (DB bucket) and `extra` (Live bucket). The "missing" and "extra" lists contain the identical note.

No same-pitch-overlap-trim handling exists anywhere in `sync/` (confirmed by code map). Both fixes are confined to the pure `arrangement_compare.py`.

## Chunk 1 — Finding 1: normalize same-pitch overlap-trim before comparing  [status: not started]

- **Description:** Add a pure normalization pass that, within each note set, for each pitch (sort that pitch's notes by start), clamps every note's effective `dur` to end no later than the next same-pitch onset — the exact transform Live's `set_notes` applies. Apply it to **both** the DB-side and Live-side `NoteLite` sets inside `compare_clip_notes`, after `_to_lite` and before grouping (Live's side is already trimmed → idempotent). Faithful overlap-trims then pass `_dur_vel_match`; a genuine drop/drift still surfaces.
- **Depends on:** none.
- **Deliverables:** edit to `src/hallucinote/sync/arrangement_compare.py` — a new pure helper (e.g. `_clamp_same_pitch_overlaps(notes) -> list[NoteLite]`) called from `compare_clip_notes`. No change to `NoteLite`, `_dur_vel_match`, or the public signature.
- **Tests:** new unit tests in `tests/unit/sync/test_arrangement_compare.py` (matching the existing `db()`/`live()` factory style, 10 tests already there):
  - **faithful overlap-trim** — DB authors p63 @0.0 dur 3.0 and p63 @1.0 dur 1.0; Live holds p63 @0.0 dur **1.0** (trimmed to next onset) + p63 @1.0 dur 1.0 → `faithful` (currently `mismatch`). Use a real case from the report (e.g. Human Riff chorus2 trim).
  - **trim does not mask a real drop** — same DB stack but Live is *missing* the second onset entirely → still reads `missing` (the normalization clamps durations, it must not erase a genuinely absent onset).
  - **non-overlapping same-pitch notes unchanged** — two same-pitch notes that don't overlap keep their durations (no spurious clamping).
- **Acceptance criteria:** the new tests pass; all 10 existing `test_arrangement_compare.py` tests stay green (esp. `test_wildness_stack_is_faithful_not_divergent` and `test_wildness_key_with_one_matching_member_is_faithful` — the collapse path must be untouched).
- **Critic mode:** (inferred — `chunk`)
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

## Chunk 2 — Finding 2: kill the half-eps bucket-boundary instability  [status: not started]

- **Description:** Make the comparator tolerance-stable at bucket boundaries so a note present on both sides (equal pitch, starts within `eps`, matching dur/vel post-normalization) can **never** appear in both `missing` and `extra`. **Recommended mechanism:** keep the existing grouping but add a pure post-pass that reconciles leftover `missing`↔`extra` pairs — for each `missing` note, if an `extra` note of equal pitch exists whose start is within `eps` and whose `(dur, vel)` matches (`_dur_vel_match`), cancel both (they are the same note split across adjacent buckets). **Alternative** (flagged in Open assumptions): replace the integer `_bucket` key with greedy nearest-neighbor pairing within `eps` per pitch. Choose at build time against the test suite; do not change `eps`/`vel_tol` or the same-(pitch,start) collapse semantics.
- **Depends on:** Chunk 1 (the reconcile compares dur/vel via the same `_dur_vel_match`, which Chunk 1's normalization feeds — so boundary reconciliation works on already-overlap-normalized notes).
- **Deliverables:** edit to `src/hallucinote/sync/arrangement_compare.py` — the post-pass (or the matching-core change) in `compare_clip_notes`/`_bucket`.
- **Tests (unit):** in `tests/unit/sync/test_arrangement_compare.py`:
  - **half-eps boundary faithful** — a note at `start = k*eps + eps/2` with sub-ULP noise on one side only (use the report's values, e.g. 17.9825 / 5.9675 / 13.9775 at eps 1e-3) → `faithful` (currently both `missing` and `extra`). This is the exact failing case; assert the note is in *neither* list.
  - **genuine missing near a boundary still reads missing** — a DB note at a half-eps start with NO Live counterpart within eps → still `missing` (the reconcile must not cancel an unpaired note).
  - **genuine extra near a boundary still reads extra** — symmetric.
  - **invariant** — across the new + existing cases, assert no `NoteLite` instance appears in both `missing` and `extra` (the report's hard rule).
- **Tests (end-to-end regression):** one test in `tests/unit/sync/test_arrangement_verify.py` (real `init_db` conn + `FakeResp`/`make_send_fn` Live model): DB authors a same-pitch overlap; the fake Live returns the trimmed-and-sub-ULP-noised read; `verify_song_arrangement` reports `faithful` and `assert_arrangement_materialized` does **not** raise — proving the full HALT path (Findings 1+2 together) is unblocked, not just the pure comparator.
- **Acceptance criteria:** all unit + the e2e regression pass; every existing `test_arrangement_compare.py` and `test_arrangement_verify.py` test green; the report's 9-divergence `alien` shape would now read faithful.
- **Type:** cumulative-final
- **Critic mode:** (declared via `Type: cumulative-final` — the chunk's own review IS the one `/prawduct:critic cumulative`; this is the riskier matching-core change, so the cumulative pass reviews Findings 1+2 as a coherent whole)
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. Committed and chunk marked `[x]` in Status
  3. `/prawduct:critic cumulative` run against `merge-base...HEAD` and blocking findings resolved (the `/prawduct:pr create` gate)

## Verification strategy

Pure engine fix — **no MCP fingerprint flip, no re-vendor, no Live required**. `arrangement_compare.py` imports only `dataclasses`/`typing`; every fix is exercised by deterministic unit tests reproducing the exact `alien` divergence values from the report, plus one end-to-end test through `verify_song_arrangement` with a fake Live model (the comparator-to-HALT path). Optional operator-confirm (songs repo + Live, not in this repo): rebuild `alien`, `execute --only arrangement --probe`, `verify-arrangement --song alien` → exit 0 (the 9 divergences gone, the render unblocked). Confirmation, not a gate.

> **Note on the authoring-side smell (not worked here):** the report flags that same-pitch overlaps in `add_wildness`/feel layers are arguably a build.py smell (durations no DAW can represent). Per the user's "don't work around it" directive, the FRAMEWORK fix (materialize+verify gracefully) is what's planned. Pre-clamping in the mutator/materialization path is a *separate* optional hardening — out of scope here; note in the backlog if wanted.

## Governance checkpoints

**Commit & PR cadence:** commit per chunk after `/prawduct:critic chunk` passes (Chunk 1); PR after Chunk 2's one `/prawduct:critic cumulative` passes.
- After Chunk 1: `chunk` review — the overlap-normalization helper + that it doesn't mask genuine drops and leaves the collapse path untouched.
- After Chunk 2 (`cumulative`): Findings 1+2 reviewed together as the safety-net regression — confirm the comparator still catches a *real* bulk-drop/orphan (the 06-21/06-22 bugs ARR-PROJ built it to catch), i.e. the false-halt fix didn't blind the detector.
