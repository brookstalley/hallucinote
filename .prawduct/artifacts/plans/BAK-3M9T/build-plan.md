---
artifact: build-plan
version: 2
scope: null
depends_on:
  - artifact: requirements   # .prawduct/artifacts/plans/BAK-3M9T/requirements.md
last_validated: null
---

# BAK-3M9T — Turnkey live→source bake: one durable bake

Requirements + audit: `.prawduct/artifacts/plans/BAK-3M9T/requirements.md`.
Decision (user, 2026-06-17): **Option 1 — one durable bake.** Make `/song-snapshot`
the single mix bake, model sidechain in the durable snapshot, delete the redundant
`/snapshot-bake-recent-changes`, and reframe `/ableton-pull` as the build.py-staging
primitive.

**Not yet the active build plan.** Build on a feature branch / worktree off `develop`
(`feedback_worktree_for_wip`); this touches the MCP-served `--plugin-dir` tree, so
Critic review runs via independent Agents + `gh` (`feedback_worktree_governance_gates_blind`).
Point `active_build_plan` here only when the build session starts.

## Requirements Confidence

**Level:** High

**Why:** Problem (one durable bake), success (sidechain round-trips through
`captured_session.json`; one command; redundant alias gone), and scope (4 chunks)
are each one sentence. 6 of 7 traps are already shipped and verified in the audit;
the only genuine new capability is modeling sidechain in the snapshot, and its
DB columns + push half + pull-read probe already exist (SDC-7K3M).

**Open assumptions / unknowns:**
- `[ASSUMPTION: the snapshot stores the sidechain source as the source track's surface name (stripped return-name form for returns), and replay resolves name→track UUID before calling set_device_sidechain | HIGH impact | user can correct]` — this is the surface-ID-not-UUID rule (the snapshot is durable + portable; UUIDs are per-build). Confirmed against `set_device_sidechain(source_track_id: UUID)` needing resolution. Chunk 01 verifies the exact reference form against SDC-7K3M's author API.
- `[ASSUMPTION: the device row's tuple in `_LATEST_ACTOR_EVENTS` already protects the sidechain event kind (SDC-7K3M registered it) | MED impact | Chunk 01 verifies + adds a regression test if missing]` — RTE-1K9T forgot exactly this for `track`.

**What would raise confidence:** N/A (High). The two assumptions are verified inside
Chunk 01's `verify-api` step before any handler is written.

## Status

- [x] Chunk 01: Model sidechain source in the snapshot (durable round-trip — keystone)
- [x] Chunk 02: Capture warns + lists any sidechain it cannot represent (no silent drop)
- [x] Chunk 03: Delete `/snapshot-bake-recent-changes` + clean all references
- [ ] Chunk 04: Reframe `/ableton-pull` as build.py-staging + document the one-bake model

Context: Built on worktree `feat/snapshot-sidechain` (off develop); gates are worktree-blind
so Critic runs via an independent Agent. **Chunk 01 DONE** (commit `dcfd16c`): capture probes
`get_input_routing` → stores source by surface name (+ channel); `replay_capture` resolves
name→track id in a deferred post-pass + clears on absence (snapshot authoritative). verify-api
confirmed `_LATEST_ACTOR_EVENTS["device"]` already carries `device_sidechain_set` (no prod
change) and the DB source is track-only (`REFERENCES tracks(id)`). 13 new tests; full suite
4070 green. Independent Critic `final`: 0 blocking / 0 warning / 2 note (both accepted —
idempotent clear-on-absence is safe; non-track-source drop is Chunk 02's warn). Operator
round-trip queued (acceptance criterion 5). **Next: Chunk 02** — turn the capture-side
non-track / unrepresentable drop into a `UserWarning` + re-apply list (no silent drop).

## Scaffolding

No scaffold — existing project. Engine in the plugin uv env; tests run via the repo's
pytest. Sync/capture tests live in `tests/unit/{sync,capture}/` with synthetic
fixtures (no song-specific data) per project preference.

### Verification Strategy

Per-chunk: unit tests in `tests/unit/capture/` (round-trip on synthetic snapshots,
no Live). End-to-end (acceptance criterion 5, Live-gated, operator): one session
dialing a mix that exercises all 7 trap categories — non-[0,1] continuous param,
enum, renamed return, **a sidechain** — then `/song-snapshot` → `build.py` → push →
confirm reproduction, analyzer-free, sidechain durable across a rebuild. Queue as an
operator-verification entry at Chunk 01 close (`Visual change: yes` — a live external
integration a test can't speak to).

## Project Structure

Edits land in existing modules; no new directories.

### Module Boundaries
- `src/hallucinote/capture.py` — snapshot format + `assemble_snapshot_via_probes`
  (capture) + `replay_capture` (replay). Owns the durable snapshot ⇄ DB boundary.
- `src/hallucinote/sync/pull/devices.py` — `plan_pull_device_sidechain` (the existing
  sidechain-source READ probe; Chunk 01 reuses its probe shape, does NOT route through it).
- `src/hallucinote/db/mutations/devices.py` — `set_device_sidechain` (existing push/replay write).
- `src/hallucinote/db/mutations/build.py` — `_LATEST_ACTOR_EVENTS` (tombstone protection).
- `skills/` — `song-snapshot`, `ableton-pull`, `snapshot-bake-recent-changes` (deleted).
- `docs/` — `snapshot-schema.md`, `song-workflow.md`, `song-authoring-conventions.md`.

## Build Chunks

### Chunk 01: Model sidechain source in the snapshot (durable round-trip — keystone)

- **Description:** Add a sidechain-source field to the snapshot device-entry schema so
  a dialed sidechain round-trips through the durable `captured_session.json` — capture
  populates it, `replay_capture` resolves it to the track FK and applies it via the
  existing `set_device_sidechain`. This is the one real capability gap and the thin
  vertical slice proving the durable round-trip (capture → JSON → replay → push) end to end.
- **Depends on:** none
- **Artifacts consumed:** `.prawduct/artifacts/plans/BAK-3M9T/requirements.md`; this plan.
- **Persisted-format decision (lock-in — enumerate before designing fields):** the
  snapshot device entry gains **one** field. Questions the data must answer:
  - *Replay's query:* resolve source → a `tracks.id` in THIS song to call
    `set_device_sidechain`. ⇒ store the source as the **source track's surface name**
    (stripped return-name form for returns — trap #6), NOT a UUID (per-build, non-portable).
    Replay resolves name→id exactly like sends key to return name.
  - *Channel:* `sidechain_source_channel` exists in the DB; capture it alongside when present.
  - *Absence:* omit the field (or null) when no sidechain source is set — narrow to the
    default-INDEPENDENT "source present" case; never write a guessed default (round-trip
    default-detection learning, RTE-1K9T ch05).
  - *Future consumers:* the snapshot diff (Chunk 02 / existing `diff_snapshots`) and the
    future event-store flip read the same field — keep it a plain surface-named reference.
- **Foreign API:** ableton-live-mcp
- **Deliverables:**
  - `src/hallucinote/capture.py` — capture: `assemble_snapshot_via_probes` emits the
    sidechain-source field on device entries that have one (reusing the probe shape from
    `plan_pull_device_sidechain` in `src/hallucinote/sync/pull/devices.py`). Replay:
    `replay_capture` resolves the surface name → song track id and calls
    `set_device_sidechain`; clears it when absent only if the prior state had one
    (idempotent, upsert-shaped — matches existing replay semantics).
  - new `tests/unit/capture/test_sidechain_snapshot.py` — synthetic round-trip tests.
  - `docs/snapshot-schema.md` — document the new field + the "stored by surface name" rule.
- **Tests:** (synthetic fixtures, no Live)
  - round-trip: snapshot device entry with `sidechain_source: "<track name>"` → replay →
    assert `devices.sidechain_source_track_id` FK resolved to the right track.
  - returns: a return-track source stored stripped ('Motion') resolves correctly.
  - absence: device with no sidechain → no field written; replay no-ops.
  - surface-id-not-UUID: fixture whose track UUIDs deliberately ≠ index/name, asserting
    resolution keys on the surface name (capture-handler keying learning).
  - tombstone regression: build-owns a device → sidechain replayed as actor='sync' →
    re-build → assert the device row + sidechain survive (guards the `_LATEST_ACTOR_EVENTS`
    device tuple includes the sidechain event kind — add it if `verify-api` finds it missing).
- **Acceptance criteria:** the round-trip + tombstone tests pass; a sidechain authored in
  the snapshot reproduces in the DB after `build.py`; no new DB column (reuse SDC-7K3M's);
  capture writes the source by surface name, never UUID.
- **Critic mode:** final  <!-- override: persisted-schema keystone; coherence matters before later chunks build on it -->
- **Visual change:** yes  <!-- Live-gated operator round-trip (acceptance criterion 5) -->
- **Done when:**
  0. `verify-api` — read `plan_pull_device_sidechain` + `set_device_sidechain`; probe the
     live read path for sidechain source on an actual witness device; confirm the exact
     reference form (name/index) and whether `_LATEST_ACTOR_EVENTS["device"]` already lists
     the sidechain event kind. Capture findings in this chunk's notes.
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic final` run (via independent Agent) and blocking findings resolved
  3. Committed; chunk marked `[x]`; operator-verification entry appended for the Live round-trip

### Chunk 02: Capture warns + lists any sidechain it cannot represent (no silent drop)

- **Description:** The umbrella's core guarantee — "warns, never silently drops." When
  capture encounters a sidechain source it cannot represent as a surface-stable snapshot
  reference (source track not in the song, an unsupported device class, an unresolvable
  name), emit a `UserWarning` with a **re-apply list** instead of dropping it silently —
  the same discipline as the existing analyzer-migration and return-stripping warnings.
- **Depends on:** Chunk 01
- **Artifacts consumed:** this plan; `src/hallucinote/capture.py`.
- **Deliverables:**
  - `src/hallucinote/capture.py` — the warn-and-list fallback at the capture boundary.
  - `tests/unit/capture/test_sidechain_snapshot.py` — extend with an unrepresentable-source
    fixture asserting the warning fires + the dropped item appears in the re-apply list.
- **Tests:** capture a sidechain whose source can't be surface-named → assert `UserWarning`
  with the re-apply list; assert the rest of the snapshot is still captured (warn, don't abort).
- **Acceptance criteria:** no sidechain is ever silently dropped from a capture; the warning
  names what wasn't captured and how to re-apply it.
- **Scope note (deliberate):** this chunk covers the *sidechain* re-apply guarantee, the
  concrete case the umbrella named. A general "diff everything probed vs everything the
  schema can represent" completeness sweep is **out of scope** here (open-ended; rule-of-three
  not met) — `log()` that boundary in the chunk, don't silently imply full coverage.
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic chunk` run (via independent Agent) and blocking findings resolved
  3. Committed and chunk marked `[x]`

### Chunk 03: Delete `/snapshot-bake-recent-changes` + clean all references

- **Description:** Remove the redundant alias whose DB-only "survives the next push"
  promise is the durability footgun (it reverts on the next `build.py`). Delete the skill
  and clean every reference so nothing dangles (no back-compat shim —
  `feedback_no_backcompat_to_throwaway`).
- **Depends on:** Chunk 01 (sidechain must round-trip via `/song-snapshot` before its
  param-bake alias is removed, so no capability is lost in the gap).
- **Artifacts consumed:** this plan.
- **Type:** cleanup
- **Deliverables:**
  - delete `skills/snapshot-bake-recent-changes/` (the whole skill dir) via `git rm`.
  - grep the repo for `snapshot-bake-recent-changes` and update/remove every reference —
    expected surfaces (per `project_song_workflow_discoverability_spine`): `CLAUDE.md` (if
    present), `docs/song-workflow.md`, `skills/song-workflow/SKILL.md`, the getting-started
    primer, skill handoff sections in `skills/ableton-push/SKILL.md` /
    `skills/song-snapshot/SKILL.md`, and any cross-links. Redirect callers to
    `/song-snapshot` (mix params) or `/ableton-pull` (build.py-owned domains).
- **Tests:** `grep -r snapshot-bake-recent-changes` returns no live references (only the
  change-log / plan history may mention it).
- **Acceptance criteria:** the skill is gone; no dangling reference remains; the discoverability
  spine (primer + `/song-workflow` + handoffs) points to the surviving commands.
- **Done when:**
  1. Acceptance criteria met (grep clean)
  2. `/prawduct:critic chunk` run (via independent Agent) and blocking findings resolved
  3. Committed and chunk marked `[x]`

### Chunk 04: Reframe `/ableton-pull` as build.py-staging + document the one-bake model

- **Description:** Make the one-durable-bake model explicit in the docs and skills, and
  grep out stale guards that predated sidechain-in-snapshot ("snapshot doesn't carry
  sidechain", "rides a separate domain" — the stale-exclusion learning).
- **Depends on:** Chunk 03
- **Artifacts consumed:** this plan; `.prawduct/artifacts/plans/BAK-3M9T/requirements.md`.
- **Type:** doc-only
- **Deliverables:**
  - `skills/ableton-pull/SKILL.md` — frame `/ableton-pull` as the lower-level
    build.py-staging primitive for build.py-owned domains (clip-notes, automation), and
    explicitly NOT a parallel mix bake; note that the durable mix bake is `/song-snapshot`.
  - `skills/song-snapshot/SKILL.md` — state it is THE mix bake and now carries sidechain;
    remove any "use `/ableton-pull device-sidechain` to persist sidechain" redirect.
  - `docs/snapshot-schema.md` + `docs/song-workflow.md` — document the one-bake model: durable
    target (`captured_session.json`) vs the regenerable DB, which command for which change.
  - grep `snapshot doesn't carry sidechain` / `rides a separate domain` / similar stale
    exclusions across `skills/` + `docs/` and update them.
- **Tests:** doc-only; the grep for stale-exclusion phrasing returns clean.
- **Acceptance criteria:** a reader of `/song-workflow` + the snapshot-schema doc can tell,
  in one place, that `/song-snapshot` is the single mix bake (sidechain included) and what
  `/ableton-pull` is for; no stale "snapshot can't carry sidechain" guidance remains.
- **Type:** cumulative-final
- **Done when:**
  1. Acceptance criteria met (docs coherent; stale-exclusion grep clean)
  2. Committed and chunk marked `[x]`
  3. `/prawduct:critic cumulative` run against `merge-base...HEAD` (via independent Agent)
     and blocking findings resolved — this IS the chunk's review and the `/prawduct:pr` gate
     (commit the chunk first; no separate `final`).

## Early Feedback Milestone

**Milestone chunk:** Chunk 01
**What the user can do:** after Chunk 01 + the Live-gated operator round-trip, dial a
sidechain in Live, run `/song-snapshot`, rebuild, and see it reproduce — the durability
trap is closed for the headline case before any consolidation lands.

## Governance Checkpoints

**Commit & PR cadence:** Commit per chunk after its `/prawduct:critic` pass (run via an
independent Agent against the worktree branch — gates are blind to worktrees this session).
PR into `develop` after Chunk 04's one `/prawduct:critic cumulative` (its review AND the PR
gate) passes. Open/merge the PR with `gh` per `feedback_worktree_governance_gates_blind`.

- After Chunk 01: architecture validation — the durable round-trip is the keystone the rest
  assumes; `final`-mode review + the Live-gated operator check before consolidating skills.
- After Chunk 04: cumulative review across the whole branch = the PR gate.
