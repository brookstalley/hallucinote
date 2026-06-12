---
artifact: build-plan
version: 2
scope: null
depends_on:
  - artifact: discovery
    path: .prawduct/artifacts/plans/ENV-9P4T/discovery.md
last_validated: null
---

# ENV-9P4T — Performed Automation at Mix Scale: Build Plan

**Goal (write side only):** write automation at greater **fidelity** and **performance**.
Harvesting / reading hand-edited arrangement automation is **explicitly deferred** (user,
2026-06-11) — the `.als` read path is understood and documented in `discovery.md`, not
built here. Extends **ENV-7G4K** (shipped perform mechanism) / **AUD-1M4V** R3.2.

This plan extends an existing codebase — Scaffolding / Project Structure / Dependency
sections are **N/A** (no new packages; all work is in the shipped perform path).

## Requirements Confidence

**Level:** High (Chunks 01–02) · Medium (Chunk 03 — fidelity ceiling is probe-gated)

**Why:** The mechanism is proven and Live-smoke-verified (ENV-7G4K), and the two extension
points were read in code this session — the handler (`hallucinote_mcp/src/hallucinote_mcp/handlers/automation.py`)
and planner (`src/hallucinote/sync/push/perform.py`) already resolve a non-master
`track_index` mixer; the only gate is routing (`src/hallucinote/sync/push/envelopes.py`).
Batching is new machinery but well-understood. Fidelity (Chunk 03) depends on probes:
achievable tick density under batching, and whether the undocumented envelope-event API
reaches arrangement.

**Open assumptions / unknowns:**
- `[ASSUMPTION: authoring fork = infer-from-span — a plain track's mixer/send envelope routes to perform (continuous arrangement lane) when no single session clip on that track covers its beat range; otherwise session-clip | MED impact | user can override with an explicit per-envelope route flag]`
- `[ASSUMPTION: keep per-arc fingerprint gating (NOT clean-slate-re-record-all) — it is a data-safety feature: an unchanged authored arc is never re-recorded, so a hand-edited Live lane survives. "Fine to start over" = acceptable worst-case wall-clock, not a license to wipe edits | MED impact | user can override toward clean-slate]`
- `[ASSUMPTION: audio-track CONTINUOUS rides via perform are in scope (clip-less, no CLP-AUD2 dependency); audio-track PER-CLIP envelopes remain gated on CLP-AUD2 | LOW impact]`
- `[ASSUMPTION: one batched call replaces N perform calls; if Live cannot hold many simultaneous open gestures, fall back to bounded-batch (M arcs/pass). Resolved by Chunk 01's probe | MED impact]`

**What would raise confidence:** Chunk 01's `verify-api` probe (multi-gesture-in-one-pass
+ achieved breakpoint density) closes the batching and fidelity-ceiling unknowns. **Live
was unavailable this session (a 2nd agent holds a song)** — every probe is a build-time
`verify-api` step on a scratch set, not a precondition met now.

## Status

- [~] Chunk 01: Single-pass batched recording (the performance keystone) — CODE + tests
  complete & Critic-clean (0 blocking); the step-0 verify-api Live probe is DEFERRED
- [ ] Chunk 02: Plain-track + audio-track perform targets (the 10+-track capability)
- [ ] Chunk 03: Fidelity — adaptive sampling density + curve faithfulness

Context (2026-06-11, branch `feature/env-9p4t-perform-scale` off `develop`): **Chunk 01
code + tests landed** (commits 82b1eb5 → 9c2235c): the single-arc `perform` action is
replaced by `perform_batch` — all changed arcs record in ONE transport pass with
per-parameter gesture windowing (`_PreparedArc` pending→open→closed), the planner emits
one batched call (union-span cost + overwrite `alert()` + duplicate-target preflight),
and `apply_push_results` gates each arc independently on its `automation_state` (+
zero-write stale-lane guard). Critic `final` run 3× — 1 blocking (wire read-timeout
severed verification at scale → `perform_batch` now unbounded in the shared `client.send`
read-timeout policy, the single source BOTH recv routes use — server-only was the wrong
layer) + all
warnings resolved; suite 3358 green. **Chunk 01's step-0 `verify-api` Live probe (two
gesture windows in one pass + breakpoint density) is DEFERRED** — the bridge was
version-mismatched (`c0b443e0` vs `b0c3c347`) and a 2nd agent held a song. It is the
ONLY symbolic-only verification of the windowing claim, so it **GATES Chunk 02**:
`/ableton-mcp-install` + a Live restart, then run the probe (recipe in `api-notes.md` +
`operator-verification.md`) before starting Chunk 02. The safety invariant (per-arc
gating retained; batched plan loudly names every overwritten span) threads all chunks.
Existing verification asset: **AUD-3F8M** (shipped) render-verifies
`mixer_volume`/`mixer_pan` via master-bus windowing.

### Verification Strategy

Two layers per chunk. **(a) DB/plan-level tests** run always and are the gate — model the
batched call shape, the routing decision, and the per-span overwrite warning without Live
(pattern: `MIX-3S7P`'s `test_atmosphere_pushes_clip_local.py`). **(b) Live-smoke**
(`automation_state==1` per param + `.als` breakpoint-fidelity dump, the ENV-7G4K
`s7-smoke-test.als` pattern) runs when Live is free; gated arcs that can't be smoke-tested
this session are listed in `.prawduct/operator-verification.md`, never silently skipped.

## Build Chunks

### Chunk 01: Single-pass batched recording (the performance keystone)

- **Description:** Replace one-transport-pass-per-arc with **one pass that records all
  changed perform-routed arcs**. Today `plan_push_performed_automation` emits one
  `ableton_automation(action='perform')` per changed arc and sums wall-clock sequentially
  (`src/hallucinote/sync/push/perform.py`) — N arcs ⇒ N playthroughs. After this chunk: one
  batched call, one playthrough over the union span, **per-parameter gesture windowing**
  (each arc's `begin_gesture`/`end_gesture` opens/closes at its own span entry/exit inside
  the shared pass) so a short arc never stamps a flat value across the whole song. Scope is
  the EXISTING targets (master/group/return) — this chunk proves the batch architecture
  without changing routing.
- **Depends on:** none (architectural keystone).
- **Artifacts consumed:** `.prawduct/artifacts/plans/ENV-9P4T/discovery.md`,
  `.prawduct/artifacts/plans/ENV-7G4K/design.md`.
- **Deliverables:** batched perform in `hallucinote_mcp/src/hallucinote_mcp/handlers/automation.py`
  + `hallucinote_mcp/src/hallucinote_mcp/actions/automation.py` (a list-of-targets call —
  extend `perform` or add `perform_batch`); rewired `src/hallucinote/sync/push/perform.py`
  (one batched call; wall-clock estimate becomes the union-span integral, not the
  sequential sum); a loud Visible-Cost warning naming every span the pass will overwrite;
  probe capture in new `.prawduct/artifacts/plans/ENV-9P4T/api-notes.md`.
- **Tests:** DB/plan-level — batched call carries all changed arcs; unchanged arcs excluded
  (gating composes); the overwrite warning enumerates spans. Live-smoke — 2 arcs (e.g.
  master volume + return volume) record in ONE pass, both `automation_state==1`, `.als`
  confirms both lanes' breakpoints.
- **Acceptance criteria:** a song with ≥2 perform arcs records in a single playthrough;
  measured wall-clock ≈ one union-span pass (not the sum); per-arc gating preserved.
- **Critic mode:** final
  <!-- override: architectural keystone — batch coherence must hold before Chunks 02–03 build on it -->
- **Foreign API:** ableton-live
- **Done when:**
  0. `verify-api` — on a scratch set, probe (a) two gesture windows in ONE record pass each
     record correctly (`automation_state==1` on both; `.als` shows both lanes), (b) the
     achieved breakpoint density (Hz) — capture both in `api-notes.md`. If many simultaneous
     open gestures misbehave, record the safe batch ceiling M (bounded-batch fallback).
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic final` run and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

### Chunk 02: Plain-track + audio-track perform targets (the 10+-track capability)

- **Description:** Let an ordinary **MIDI or audio** track's own `mixer_volume`/`mixer_pan`
  (and `send_level`) route to perform, giving any track a continuous arrangement ride
  independent of clip seams — the 10+-track use case. The handler + planner already resolve
  a non-master `track_index` mixer (verified this session); the change is the **routing
  gate** `_route_for_host_kind` in `src/hallucinote/sync/push/envelopes.py` (today: midi
  host → session_clip, audio host → refused_audio) plus the infer-from-span authoring fork.
  **Adjacencies folded in (the "might as well" items):** this generalization gives
  **audio-track continuous rides for free** (perform side of **ENV-8H1T**; its session-clip
  side stays gated on CLP-AUD2) and **unlocks the deferred song-spanning send** that
  **MIX-3S7P / ENV-3M7K** could not host across tacet-section gaps (perform writes an
  arrangement lane whether or not the source track has a clip there). Capability only — the
  sun-zone-done DubDelay authoring + creative re-lock stays **user-owned** (MIX-3S7P note);
  do not author the song change.
- **Depends on:** Chunk 01 (records through the batched pass).
- **Artifacts consumed:** `.prawduct/artifacts/plans/ENV-9P4T/discovery.md`.
- **Deliverables:** routing change in `src/hallucinote/sync/push/envelopes.py`
  (`classify_envelope_route` / `_route_for_host_kind` admit midi+audio hosts to perform via
  infer-from-span; updated `_warn_non_session_route` teaching); any minimal addressing
  touch in `src/hallucinote/sync/push/perform.py`.
- **Tests:** DB/plan-level — a plain-track song-spanning volume envelope routes to perform
  (not session-clip) and is not segmented; a within-one-clip envelope still routes
  session-clip (infer-from-span boundary); an audio-track continuous ride routes to perform;
  audio-track per-clip envelope still refuses with CLP-AUD2 teaching. Live-smoke — a plain
  track's full-song volume ride records as one continuous lane.
- **Acceptance criteria:** plain MIDI/audio tracks get continuous arrangement
  volume/pan/send rides via perform; the session-clip path is unchanged for within-clip
  envelopes; the previously-deferred song-spanning send is now plan-routable.
- **Critic mode:** chunk
- **Foreign API:** ableton-live
- **Done when:**
  0. `verify-api` — probe a non-master/non-group plain track's `mixer_volume`/`mixer_pan`
     perform records cleanly (`automation_state==1`); repeat on an audio track. Capture in
     `api-notes.md`.
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic chunk` run and blocking findings resolved
  3. Committed; chunk marked `[x]`; backlog pass — note **ENV-8H1T** (perform side
     addressed; session-clip side still CLP-AUD2) and **MIX-3S7P/ENV-3M7K** (capability
     unlocked; authoring user-owned) via `/prawduct:backlog`.

### Chunk 03: Fidelity — adaptive sampling density + curve faithfulness

- **Description:** Raise recorded-shape fidelity in the perform loop. Today the loop ticks
  ~10 Hz (`_PERFORM_UPDATE_PERIOD_S`) for ~2.5–3 Hz achieved breakpoints
  (`hallucinote_mcp/src/hallucinote_mcp/handlers/automation.py`), so fast filter sweeps and
  sharp volume dips smear. Add **adaptive sampling** — sample more densely across steep
  segments (where the authored value changes fastest), bounded by the main-thread budget
  Chunk 01 measured under N-params-per-tick batching — while keeping `curve_kind` honored.
  **Probe-gated investigation:** also test whether the undocumented
  `create_automation_envelope`/`create_event` envelope-event API secretly reaches
  arrangement/take-lane clips (open question in
  `docs/research/audio-first-class/lom-recording-automation.md`). If YES, a direct-write
  path (exact breakpoints, no realtime, no Live thinning) is a future fidelity revolution —
  spin it out as its OWN item, do not expand this chunk. If NO, the deliverable is the tuned
  gesture loop.
- **Depends on:** Chunk 01 (density measurement + main-thread budget) and Chunk 02.
- **Artifacts consumed:** `.prawduct/artifacts/plans/ENV-9P4T/api-notes.md`,
  `docs/research/audio-first-class/lom-recording-automation.md`.
- **Deliverables:** adaptive sampling in the perform ramp loop
  (`hallucinote_mcp/src/hallucinote_mcp/handlers/automation.py`); probe verdict on the
  direct-write API reach recorded in `api-notes.md` (+ a new backlog item if it unlocks).
- **Tests:** Live-smoke — a fast filter sweep and a sharp volume dip record with faithful
  shape (`.als` breakpoint set vs authored, within tolerance); curve_kind segments preserved.
- **Acceptance criteria:** measured breakpoint density on steep segments improves vs the
  ~2.5–3 Hz baseline without main-thread starvation under a batched multi-arc pass.
- **Critic mode:** chunk
- **Type:** cumulative-final
- **Foreign API:** ableton-live
- **Done when:**
  0. `verify-api` — probe achievable tick density under batching + whether
     `create_automation_envelope`/`create_event` reaches arrangement/take-lane clips;
     record verdict in `api-notes.md`.
  1. Acceptance criteria met and tests pass
  2. Committed and chunk marked `[x]` in Status
  3. `/prawduct:critic cumulative` against `merge-base...HEAD` run and blocking findings
     resolved — this IS the chunk's review and the `/prawduct:pr create` gate (no separate
     `final`).

## Early Feedback Milestone

**Milestone chunk:** Chunk 01
**What the user can do:** push a song whose master/group/return rides all write in a single
transport run-through — the performance win is audible/measurable immediately.

## Governance Checkpoints

**Commit & PR cadence:** Commit per chunk after its `/prawduct:critic` passes; PR into
`develop` after Chunk 03's single `/prawduct:critic cumulative` (its review AND the PR gate).

- After Chunk 01: **architecture validation** — confirm one-pass batching with per-arc
  gesture windowing actually holds in Live (the probe + smoke) before Chunks 02–03 build on
  it. This is the keystone; if bounded-batch (M arcs/pass) is forced, revisit Chunk 02–03
  sizing.
- Before completion (Chunk 03): `cumulative` review across the branch = the PR gate.
