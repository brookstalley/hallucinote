# CLR-B — Build Plan (compose-loop reliability, wave B: unattended-loop enablers)

Backlog items RND-7K3M (render burns the wait window when Live's audio engine
is off), SYN-2M9P (push planner emits master device-LOAD calls that can never
execute), ENV-5R2J (host-kind→route mapping encoded twice). The theme: remove
the software half of "an unattended render → MixReport → /mix-review loop
always waits on a human" (friction-log item 8; the `.als` template TPL-2D8K
remains the human half). One branch (`feature/clr-b-unattended-loop`), one
chunk per item, one PR into `develop` (gitflow base per
`feedback_pr_gate_base_is_develop`). Sequenced AFTER CLR-A merges.

## Requirements Confidence: **Medium**

- **Problem (one sentence):** A render against a disabled audio engine hangs
  silently for the full timeout, the push planner can emit master-device loads
  that are impossible by construction, and the envelope route partition lives
  in two modules that can drift.
- **Success (one sentence):** Render fails fast with an actionable cause when
  the audio engine is off, a push of a master-device-bearing song completes
  without ever planning an impossible load, and one module owns the
  host-kind→route mapping.
- **Out of scope (one sentence):** The master-analyzer `.als` template
  (TPL-2D8K), any Remote Script change that cannot be unit-verified without a
  Live restart cycle beyond one operator-verification queue entry, and the
  async/progress MCP protocol (MCP-4T6Y design note).

**Why Medium, not High:** SYN-2M9P may be partially superseded by the
DEV-2M9K fix wave (master loads already refuse; render is detect-only) — the
chunk's step 0 verifies current behavior before building; RND-7K3M's
audio-engine probe surface on the LOM is unverified.

**Open assumptions / unknowns:**

- `[ASSUMPTION: SYN-2M9P's remaining gap, if any, is the PARTIAL-halt UX when
  a plan contains a master-hosted device load — the fix is planner-side
  partition (manual_required listing, no halt), not a new wire action; if
  step 0 shows the DEV-2M9K wave already covers it, the chunk records
  supersession and closes the item | MED impact | user can veto]`
- `[ASSUMPTION: Live's audio-engine state is detectable from the Remote
  Script / M4L side cheaply (probe in chunk step 0); if no LOM surface
  exists, the fallback is a fast analyzer-handshake timeout with a teaching
  error naming the audio engine as the likely cause | HIGH impact for the
  fix shape | user can override]`
- `[ASSUMPTION: the deduped route mapping lives DB-side (a small
  `db/envelope_routing.py` or equivalent) so `db/mutations` never imports
  `sync/push` — layering preserved, sync imports db | LOW impact | defer]`

**What would raise confidence:** chunk step-0 probes (current master-load
behavior; LOM audio-engine surface) — both cheap, wire-level, no restart.

## Status

- [ ] Chunk 01: ENV-5R2J — single source for host-kind→route mapping
- [ ] Chunk 02: SYN-2M9P — verify current master-load behavior; close the remaining gap or record supersession
- [ ] Chunk 03: RND-7K3M — render pre-flight: fail fast when the audio engine is off (cumulative-final)
Context: plan authored 2026-06-11; nothing built yet.

## Scaffolding

Existing project — no scaffold work. Tests via `pytest`; homes:
`tests/unit/sync/test_push_envelopes.py` + `tests/unit/db/test_mutations.py`
(chunk 01), `tests/unit/sync/` (chunk 02),
`hallucinote_mcp/tests/unit/` (chunk 03).

---

## Chunk 01 — ENV-5R2J: route-mapping dedup

**Type:** code

The envelope host-kind→route partition is encoded in
`src/hallucinote/sync/push/envelopes.py` (`classify_envelope_route`) AND in
`src/hallucinote/db/mutations/devices.py` (the `_HOST_KIND_ROUTED_KINDS`
eligibility checks). Consolidate to one source. Layering constraint: the db
layer must not import sync — the shared mapping moves db-side and the planner
consumes it.

- **Done when:**
  1. One module owns the mapping; both consumers import it; a drift-canary
     test pins the shared source.
  2. Full suite green; `/prawduct:critic` per cadence.
  3. Committed; chunk marked [x] in Status.

## Chunk 02 — SYN-2M9P: master-load planner truth

**Type:** code

- **Done when:**
  0. verify current behavior — drive the push planner over a DB that authors
     a master-hosted device and capture what the plan emits today (the
     DEV-2M9K wave may already refuse cleanly).
  1. Either the remaining gap is closed planner-side (master loads partition
     to a manual_required listing with teaching, never a PARTIAL halt) with
     tests, OR supersession is recorded on the backlog item with the step-0
     evidence and no code ships.
  2. Full suite green; `/prawduct:critic` per cadence.
  3. Committed; chunk marked [x] in Status.

## Chunk 03 — RND-7K3M: render pre-flight for the audio engine

**Type:** code
**Foreign API:** Ableton Live LOM (audio-engine state surface)

A render with Live's audio engine OFF silently burns the full wait window —
no pre-flight, no actionable cause. Add the cheapest reliable detection ahead
of the capture pass and fail fast with a teaching error.

- **Done when:**
  0. verify-api — probe the running Live for an audio-engine state surface
     (`ableton_probe` against the LOM; read the vendored Remote Script
     source); capture the verdict in the chunk context. If no surface
     exists, the fallback design (fast analyzer-handshake timeout + teaching
     error) is recorded and built instead.
  1. Pre-flight failure path unit-tested; a wire smoke against the open Live
     set where feasible without a Remote Script reload; if the change ships
     Remote-Script-side, an operator-verification entry covers the
     restart-gated half.
  2. Full suite green; commit the chunk, then `/prawduct:critic cumulative`
     (develop base) — the PR-gate review; resolve blockers.
  3. Committed; chunk marked [x] in Status.
