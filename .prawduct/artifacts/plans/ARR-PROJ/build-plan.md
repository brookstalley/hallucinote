<!-- Build Plan — ARR-PROJ (arrangement-as-projection). Tier 1 (Source of Truth).
     WHAT to build. For HOW (governance, test discipline, Critic), read /prawduct:building.
     Design artifact (canonical diagnosis + architecture): .prawduct/artifacts/arrangement-materialization-redesign.md -->
---
artifact: build-plan
version: 2
scope: ARR-PROJ
depends_on:
  - artifact: design
    path: .prawduct/artifacts/arrangement-materialization-redesign.md
last_validated: null
---

## Requirements Confidence

**Level:** Medium

**Why:** The architecture (arrangement-as-projection: clear + direct create+fill +
integrity assert) is clear and high-confidence — every primitive it needs already exists on
the MCP wire (verified) and the design is captured. What holds it at Medium: two empirical
facts can only be confirmed in an attended Ableton session — *why* the bulk duplicate
silently dropped one track's notes, and whether `create_midi_clip`+`set_notes` at full-song
scale is truly idempotent and overlap-free. Chunk 1 closes both before the planner is
rewritten.

**Open assumptions / unknowns:**
- `[ASSUMPTION: retire duplicate_to_arrangement for note-only placements; keep it ONLY for envelope-bearing placements | HIGH impact | user can override]`
- `[ASSUMPTION: the persistent arrangement ableton_link is removed (bound only transiently within a push, if at all) once rebuild is the sole path | HIGH impact | user can override]`
- `[ASSUMPTION: implement in the sync planner using existing wire (create/replace_notes/delete); add the bulk clear_arrangement wire action ONLY if Chunk 1 shows planned per-clip deletes are too slow or index-fragile | MED impact | user can defer]`
- `[ASSUMPTION: create+fill materializes the FULL clip spec from the DB (notes + name + color + clip envelopes), not notes alone | MED impact | user can override]`
- `[ASSUMPTION: the bulk-drop is a Live-side materialization/timing failure (tombstone-deletion ruled out — see design §6a); create+fill sidesteps it, confirmed in Chunk 1 | MED impact]`
- `[ASSUMPTION: the verify-arrangement audit command (the 2026-06-22 capability report) is in ARR-PROJ scope as Chunk 3's detection layer, sharing the push-time comparator | MED impact | user can defer to its own item]`

**What would raise confidence:** Chunk 1's Live spike — reproduce the bulk-drop, confirm
`list` note_count trustworthiness, and prove create+fill-at-scale idempotent on a real set.
After Chunk 1 the level rises to High for Chunks 2–6.

## Status

- [ ] Chunk 01: Live spike + one-track thin vertical slice (root-cause + architecture proof)
- [ ] Chunk 02: Sync-planner rebuild path (clear + create+fill + exception routing)
- [ ] Chunk 03: Integrity comparator — push-time assert + `verify-arrangement` audit (collapsed-set, tolerance)
- [ ] Chunk 04: Collapse the positional-link reconcile subsystem
- [ ] Chunk 05: Docs + skill — retire the SYN-4R7P recovery dance
- [ ] Chunk 06 (conditional): bulk `clear_arrangement` MCP wire action

Context: Plan authored 2026-06-22 from the discovery artifact. Nothing built yet. Chunk 1 is
Live-gated and must run in an attended Ableton session before Chunk 2. Branch: not yet cut
(feature branch off `develop` per gitflow — see [[feedback_pr_gate_base_is_develop]]).

## Scaffolding

N/A — existing mature codebase. No new project init. Test commands (unchanged):
- Engine sync tests: `pytest tests/ -k "arrangement or push"` (planner is testable without
  Live — `sync/push` returns a `PushPlan`).
- MCP handler tests: `pytest hallucinote_mcp/tests/unit/` (use the `_ReWrappingFake*`
  Live-API fakes — `hallucinote_mcp/tests/unit/test_actions_track.py` et al.).

### Verification Strategy

Two tiers, because unit fakes give false confidence on exactly this class of bug (a
`list.append` fake passes for both stacking and dropping — design §6a):
1. **Headless:** planner unit tests (PushPlan shape), handler tests against re-wrapping
   fakes, integrity-assert tests with a forced mismatch.
2. **Live operator-verification (Foreign API = Ableton LOM):** the no-stack / no-drop /
   idempotent-rebuild / halt-on-mismatch proofs run against a real set and a render. Each
   Live-gated chunk appends a `.prawduct/operator-verification.md` entry. The two
   2026-06-21 reports are the acceptance witnesses.

## Project Structure

Existing layout — chunks touch:
- `src/hallucinote/sync/push/arrangement.py` (the planner — primary change site)
- `src/hallucinote/sync/push/probe.py` (the reconcile subsystem — removed in Chunk 4)
- `hallucinote_mcp/.../handlers/clip.py`, `actions/clip.py` (only if Chunk 6 adds wire)
- `skills/ableton-push/SKILL.md` + `resources/guides/` (Chunk 5 docs)
- Tests alongside each.

## Build Chunks

### Chunk 01: Live spike + one-track thin vertical slice

- **Description:** Resolve the two Live-gated unknowns AND prove the architecture end-to-end
  on ONE track before widening. (a) Reproduce the bulk-drop on a real set and capture what
  state correlates with it. (b) Confirm whether `ableton_clip(list)` note_count reports the
  arrangement clip's own notes or mirrors the source (design §6 q2) — the integrity assert
  depends on this read being trustworthy. (c) Materialize one track's arrangement via
  clear + `create_midi_clip`+`set_notes` (existing wire), re-run it (idempotence), and
  render-verify the track's notes match the DB. Decide planner-only-deletes vs a new
  bulk-clear wire action (informs Chunk 6).
- **Depends on:** none
- **Artifacts consumed:** `.prawduct/artifacts/arrangement-materialization-redesign.md`
- **Deliverables:** a findings section appended to the design artifact (the §6 answers + the
  wire decision); a throwaway/spike script or recorded probe sequence proving one-track
  create+fill is idempotent and render-correct.
- **Tests:** spike-level — the durable tests land in Chunk 2. Capture the real LOM response
  shapes for `create`/`replace_notes`/`list`/`delete` on `location='arrangement'`.
- **Acceptance criteria:** the §6 q1+q2 answers are recorded; one track round-trips
  DB→clear→create+fill→render with notes matching the DB across two consecutive rebuilds
  (idempotent); the planner-deletes-vs-bulk-clear decision is made and written down.
- **Type:** code
- **Foreign API:** ableton-live-mcp
- **Visual change:** yes
- **Done when:**
  0. verify-api — drive the real LOM in an attended session for `create`/`replace_notes`/
     `list`/`delete` on `location='arrangement'`; capture actual response shapes + the
     note_count behavior in the design artifact's findings section.
  1. Acceptance criteria met; one-track slice render-verified.
  2. `/prawduct:critic` run (mode inferred) and blocking findings resolved.
  3. Findings appended to the design artifact; operator-verification entry recorded;
     chunk marked `[x]`.

### Chunk 02: Sync-planner rebuild path (the keystone)

- **Description:** Rewrite `plan_push_arrangement` (`src/hallucinote/sync/push/arrangement.py`)
  from the idempotent-skip + refresh-in-place + duplicate model to the projection model: for
  each track being materialized, emit a clear of its arrangement clips (per-chunk-1 decision)
  then, per placement, `create_midi_clip` + materialize the full clip spec from the DB
  (notes + name + color + clip envelopes). Route the two exceptions explicitly (design §5):
  envelope-bearing placements → `duplicate_to_arrangement` onto the cleared region;
  audio placements → the existing path. Resolve+validate the whole track's materialization
  before emitting any write (design §6a). Re-identify created clips by `start_time`, never
  `is`. All DB reads via queries, any writes via `db.mutations`. **Hard constraint (design
  §6b-A):** materialize by recreating the clip (delete + `create_midi_clip` + `set_notes`
  on a FRESH clip) — NEVER `replace_notes`-in-place on an existing arrangement clip, which
  is non-atomic and leaves orphan notes.
- **Depends on:** Chunk 01
- **Artifacts consumed:** the design artifact (incl. Chunk-1 findings)
- **Deliverables:** the rewritten planner returning a `PushPlan`; the envelope-bearing
  detection (a pure DB query); deletion-planning that accounts for Live's index renumbering.
- **Tests:** planner unit tests (no Live) asserting the emitted `PushPlan` for: a fresh
  materialize, a re-materialize onto an occupied timeline (must clear-then-rebuild, NOT
  stack), a note-only vs envelope-bearing vs audio placement (correct routing), and a
  mid-sequence-failure case (no half-materialized plan). Handler-level tests against
  `_ReWrappingFake*`. Cover the re-materialize cascade explicitly.
- **Acceptance criteria:** unit tests pass; re-materialize onto an occupied timeline emits a
  clear+rebuild plan (the stacking witness ARR-9X4T cannot be produced); envelope/audio
  routing verified; no raw SQL in the planner.
- **Type:** code
- **Foreign API:** ableton-live-mcp
- **Done when:**
  0. verify-api — confirm against Chunk-1's captured shapes (no fresh Live session needed if
     Chunk 1 captured them; re-probe only if a new action is used).
  1. Acceptance criteria met and tests pass.
  2. `/prawduct:critic` run and blocking findings resolved.
  3. Committed; chunk marked `[x]`.

### Chunk 03: Integrity comparator — push-time assert + `verify-arrangement` audit

- **Description:** Build ONE canonical comparator (DB-collapsed-set vs Live-arrangement-set)
  and use it two ways (design §6b-B). **Critical correctness — a raw note_count compare is
  WRONG and cries wolf**; the comparator must encode three normalizations: (1) compare the
  **distinct-(pitch, start) collapsed set** — Live holds one note per (pitch,start) while
  build.py legitimately stacks notes sharing pitch+start (e.g. `add_wildness`: alien Human
  Riff chorus3 is 332 raw DB → 305 Live, *faithful*); (2) **float tolerance** — start/dur ε
  ≈ 1e-3 beats, pitch exact, velocity small tolerance; (3) **read via the note API**
  (`get_notes_extended` / `ableton_note(list, location='arrangement')`), NOT `ableton_clip
  list` note_count (which can mirror the source). Read in a fresh probe/callback, not inline
  after the write (design §6a). Two consumers of the comparator:
  - **(a) Push-time assertion** — folded into the push arrangement phase: per arrangement
    clip, assert the audible set equals the DB's; HALT + report actionably (track/section,
    `extra`/`missing`/`mismatch`) on divergence instead of reporting `OK`. The prevention
    backstop for both 2026-06-21 bugs.
  - **(b) `hallucinote verify-arrangement --song <slug>` audit command** — fresh build →
    per-clip canonical collapsed set vs Live; report `extra` (orphan/stale), `missing`
    (dropped), `mismatch` (vel/dur drift) per (track, section); non-zero exit on any
    divergence. The detection layer; run before trusting a set / before a render / after
    any hand-edit. Reuse `push-notes --changed`'s per-clip content fingerprint where it fits.
- **Depends on:** Chunk 02
- **Artifacts consumed:** the design artifact (§6b)
- **Deliverables:** the shared collapsed-set comparator (with the 3 normalizations); the
  push-time assertion wired into the arrangement phase; the `verify-arrangement` CLI command.
- **Tests:** comparator unit tests for each normalization — a wildness clip (stacked
  pitch+start) reads FAITHFUL not divergent; a float-noise round-trip reads faithful; an
  orphan-survivor reads `extra`; a dropped track reads `missing`. A forced-mismatch push
  HALTs with the actionable message; a clean materialize passes. The read is not a
  same-callback readback.
- **Acceptance criteria:** the wildness false-positive does NOT fire; a deliberately-
  corrupted materialize HALTs (does not report OK); `verify-arrangement` exits non-zero on a
  seeded orphan and zero on a faithful set.
- **Type:** code
- **Visual change:** yes  <!-- the verify-arrangement CLI report is user-facing -->
- **Done when:**
  1. Acceptance criteria met and tests pass.
  2. `/prawduct:critic` run and blocking findings resolved.
  3. Committed; chunk marked `[x]`; operator-verification entry for the CLI report shape.

### Chunk 04: Collapse the positional-link reconcile subsystem

- **Description:** With rebuild as the sole path, the persistent positional arrangement link
  has nothing to reconcile. Remove the arrangement-clip branch of `probe_and_link`
  (`src/hallucinote/sync/push/probe.py` — the SYN-3C8K/SYN-4R7P logic: drop/keep/rebind by
  position, `unlinked_stale_arrangement_clips` / `rebound_arrangement_clips`) and any link
  state it maintained, keeping only what the cues phase genuinely needs (arrangement extent).
  Delete the dead code outright — no fallback path (per [[feedback_no_backcompat_to_throwaway]]).
- **Depends on:** Chunk 02, Chunk 03
- **Artifacts consumed:** the design artifact; the bug lineage (design §1, §10)
- **Deliverables:** the reconcile subsystem removed; the cues phase confirmed to still get
  the extent it needs.
- **Tests:** existing probe-and-link tests for non-arrangement kinds (track/return/clip) still
  pass; the removed-path tests are deleted, not skipped; a re-materialize → cues sequence
  still places cues.
- **Acceptance criteria:** no arrangement reconcile code remains; cues phase unaffected; full
  push of a multi-section song works end-to-end (planner-level).
- **Type:** cleanup
- **Done when:**
  1. Acceptance criteria met and tests pass.
  2. `/prawduct:critic` run and blocking findings resolved.
  3. Committed; chunk marked `[x]`.

### Chunk 05: Docs + skill — retire the SYN-4R7P recovery dance

- **Description:** Replace the foot-gun recovery docs with the projection model.
  `skills/ableton-push/SKILL.md` (the "Re-materialize the arrangement after a note edit
  (SYN-4R7P)" guidance and the two `unlinked_stale_arrangement_clips` / `IndexError`
  troubleshooting entries) → document clear+rebuild as the single canonical, idempotent path.
  Update `ableton://guides/gaps` / `conventions` to drop the "delete by hand then
  re-duplicate" workaround and note the integrity assertion. Mark the two 2026-06-21
  incoming-bug reports resolved and move them to `incoming-bugs/archives/`, updating the
  `refs:` in ARR-PROJ / ARR-9X4T / ARR-7H2N to the archived paths in the same change.
- **Depends on:** Chunk 02, Chunk 03, Chunk 04
- **Artifacts consumed:** the design artifact
- **Deliverables:** updated skill + guides; archived reports with refs rewired.
- **Tests:** N/A (doc-only) — but grep-assert the SYN-4R7P "delete the stale clip by hand"
  language is gone from the skill.
- **Acceptance criteria:** no doc instructs the delete-then-re-duplicate recovery; the
  canonical path is clear+rebuild; refs resolve.
- **Type:** doc-only
- **Done when:**
  1. Acceptance criteria met.
  2. `/prawduct:critic` run and blocking findings resolved.
  3. Committed; chunk marked `[x]`; backlog ARR-9X4T/ARR-7H2N updated via `/prawduct:backlog`
     (status=shipped/closed-by ARR-PROJ once the redesign lands).

### Chunk 06 (conditional — only if Chunk 1 chose it): bulk `clear_arrangement` wire action

- **Description:** If Chunk 1 found planned per-clip deletes too slow or index-fragile, add a
  bulk `ableton_clip(action='clear_arrangement', …)` (per-track and/or song-wide) Live-side
  loop. This flips the MCP fingerprint (new wire action in `_FINGERPRINT_PATHS`) → re-vendor
  + operator-verify (see [[project_mcp_deploy_topology_dev_vs_marketplace]] and the
  non-fingerprinted-Live-side-change learning). Switch the Chunk-2 planner to use it.
- **Depends on:** Chunk 01 (decision), Chunk 02
- **Artifacts consumed:** the design artifact §7 (fingerprint surface)
- **Deliverables:** the new action + handler; planner switched to it; install/handshake
  re-vendor verified.
- **Tests:** handler test against `_ReWrappingFake*`; the clear is idempotent (clearing an
  empty timeline is a no-op).
- **Acceptance criteria:** bulk clear removes all arrangement clips on the target scope;
  re-vendor handshake agrees; planner uses it.
- **Type:** code
- **Foreign API:** ableton-live-mcp
- **Visual change:** yes
- **Done when:**
  0. verify-api — confirm the `delete_clip` loop semantics + index behavior live.
  1. Acceptance criteria met and tests pass.
  2. `/prawduct:critic` run and blocking findings resolved.
  3. `/prawduct:critic cumulative` against `merge-base...HEAD` (PR gate) if this is the last
     chunk of the PR; committed; operator-verification entry recorded; chunk marked `[x]`.

## Early Feedback Milestone

**Milestone chunk:** Chunk 01 — the one-track slice is render-audible; the user hears a
correctly-rebuilt track and sees the architecture works before the planner is widened.

## Governance Checkpoints

**Commit & PR cadence:** Commit per chunk after `/prawduct:critic` (mode inferred) passes.
Chunk 1 may land as its own small PR (spike findings + one-track slice) or fold into the
Chunks 2–5 core PR. The last chunk of whichever PR opens runs the one
`/prawduct:critic cumulative` against `merge-base...HEAD` (the `/prawduct:pr create` gate).
PRs base on `develop` (gitflow — [[feedback_pr_gate_base_is_develop]]). Chunk 6, if taken,
is a separate PR (it requires a re-vendor + operator-verify).

- After Chunk 01: architecture-validation checkpoint — the Live spike either confirms the
  projection model or sends us back to the design before the planner is rewritten.
- After Chunk 04: midpoint coherence — the projection path + integrity guard + reconcile
  removal reviewed together (the keystone is whole).
- Before PR: cumulative Critic = the PR gate.
