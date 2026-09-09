---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# Build plan — SYN-4R7P: probe-and-link reconciles stale `arrangement_clip` links

**Type:** Bugfix (medium). **Branch:** `fix/arrangement-rematerialize` (worktree, off `develop`).
**Critic mode:** cumulative (at PR time).

## Problem (observable)

`push execute --only arrangement --probe` crashes with `IndexError: clip_index …
out of range` when the user has deleted arrangement clips in Live and re-runs the
phase to re-materialize them. The documented "notes → arrangement" recovery
(delete the stale arrangement clips, re-run the arrangement phase — see archived
report `backlog PSH-6W2J`)
therefore fails. Reported in
bug report "`push execute --only arrangement` is refresh-in-place, not
create-from-session — the documented notes→arrangement recovery fails with IndexError".

## Root cause

`probe.py`'s strict stale-link reconciliation (W18-B / SYN-3C8K) sweeps `track`,
`return`, and `clip` links but **deliberately skips `arrangement_clip`**
(`probe.py:500` — *"re-established by the next push's create-call path"*). That
claim is false: the create path (`duplicate_to_arrangement`) only fires when the
link is **absent** (`arr_at is None`). With the parent track still linked but the
Live arrangement clip deleted (Live re-numbers `arrangement_clip_index` on any
delete — confirmed in `sync/pull/clips.py`), the link persists, so
`plan_push_arrangement` takes the `replace_notes(location='arrangement',
clip_index=stale)` REFRESH branch → IndexError on a clip that no longer exists.
It is the exact sibling of the SYN-3C8K clip-link bug; `arrangement_clip` was
never added to the same sweep.

## Success

- `--only arrangement --probe` after deleting arrangement clips re-duplicates the
  missing placements (create) and refreshes the surviving ones — true
  create-or-refresh — instead of crashing.
- The probe reconciles `arrangement_clip` links against Live truth, symmetric
  with track / return / clip: drop the stale, re-bind the renumbered, keep the
  current. "Links describe Live truth" holds for `arrangement_clip` too.

## Out of scope

- No MCP-server change (the `ableton_clip(action='list', location='arrangement')`
  read already exists; no fingerprint flip / re-vendor).
- The `--snapshot` (test/debug) path stays arrangement-blind (like it's
  device-blind) — reconcile only runs with a fresh `--probe`.
- Session-override / "Back to Arrangement" recovery (separate report — backlog
  `MCP-7P3R`).

## Design (one chunk)

Identity for an arrangement clip is **position** (Live has no stable id / name
column and re-numbers indices on delete), mirroring the pull-side diff in
`sync/pull/clips.py`.

1. **`push_cli.py` — `_probe_live_arrangement_clips_via_mcp(live_tracks)`**: per
   live track, `ableton_clip(action='list', location='arrangement')` →
   `{track_index: [{arrangement_clip_index, name, start_beats, length}, …]}`.
   A per-track probe failure leaves that track's key **absent** (not empty) so the
   reconciler never drops a binding on transient failure. Wire into
   `_cmd_probe_and_link` behind `args.probe`; pass `None` on `--snapshot`.

2. **`probe.py` — `probe_and_link`**: new optional param
   `live_arrangement_clips_by_track`; new result fields
   `unlinked_stale_arrangement_clips`, `rebound_arrangement_clips`. After the
   SYN-3C8K clip cascade, when the param is supplied, reconcile each
   `arrangement_clip` link:
   - DB row gone, or parent track link gone → **drop** (cascade).
   - track absent from the probe map (transient failure) → **skip** (keep).
   - no live placement at the row's authored position → **drop** (create re-dupes).
   - live placement at a **renumbered** index → **re-bind** the link index.
   - live placement at the recorded index → **keep** (refresh works).
   Fix the false `probe.py:500` comment + the W18-B docstring nested-kinds line.

3. **`skills/ableton-push/SKILL.md`**: document the arrangement-clip probe +
   reconcile, the new result fields, and that `--only arrangement --probe` is now
   the real re-materialize path.

## Tests (`tests/unit/sync/`)

- drop when no live placement at authored position (the core bug)
- keep when live placement at the recorded index
- re-bind when live placement renumbered (different index, same position)
- drop when DB row gone / parent track gone (cascade)
- skip (keep link) when the parent track is absent from the probe map
- `--snapshot` path (probe `None`) leaves arrangement links untouched
- `ableton_link_removed` event emitted on drop (audit-trail seed)
- end-to-end payoff: `plan_push_arrangement` emits `duplicate_to_arrangement`
  after the reconcile drop (no IndexError)

## Done when

Tests green (full suite), Critic clean, SKILL + this plan current, operator-verify
enqueued (real Live repro: delete arrangement clips → `--only arrangement --probe`).

## Independent review (Critic) — resolutions

Reviewed `develop..HEAD` by an independent agent. Core fix confirmed correct,
well-tested, docs coherent. Two WARNINGs, both resolved:

- **W1 — the literal reported one-liner still IndexErrors.** `execute --probe`
  runs only a read-only `check_coherence` (track/return scoped); reconciliation
  lives in `probe-and-link`. Architecturally correct placement — the canonical
  flow is probe-and-link → execute. Resolved by **documentation**, not by
  expanding `execute` (that's the declined teaching-guard scope): SKILL now has an
  explicit error-recovery entry — on `IndexError` from the `arrangement` phase,
  re-run `probe-and-link --probe` (reconciles) then `execute --only arrangement`.
- **W2 — re-bind could double-bind on coincident positions.** Two DB placements
  sharing a start on one track could both match the first live clip. Resolved in
  code: recorded-index preference + per-track consumed-index tracking so each
  link keeps/binds its own clip (new test
  `test_probe_and_link_keeps_distinct_indices_for_coincident_arrangement_clips`).
  Start-only identity is deliberate (liveness, not content-diff — a Live resize
  keeps the binding); commented inline.

NOTEs (start-vs-(start,end) identity, double-placement bound, cleanup-scaffold
arrangement-blindness) accepted as documented / pre-existing scope.

Full suite after resolutions: 933 sync / 3986 total passed.
