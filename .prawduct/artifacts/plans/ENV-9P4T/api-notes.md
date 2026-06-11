# ENV-9P4T — API notes & probe captures

Captures the foreign-API (Ableton Live) findings and the wire-shape design
decisions for the performed-automation-at-mix-scale work. Live-probe captures
are appended as they run; probes that could not run this session (Live bridge
version-mismatched + a 2nd agent holds a song) are listed as **DEFERRED** with
the exact recipe, and mirrored into `.prawduct/operator-verification.md`.

## Chunk 01 — single-pass batched recording

### Decision: replace the single-arc `perform` action with `perform_batch`

The shipped `ableton_automation(action='perform')` records ONE arc per call
(one transport pass per arc). Chunk 01 records all changed perform-routed arcs
in ONE transport pass. The plan offered "extend `perform` or add
`perform_batch`"; chosen: **a new `perform_batch` action that fully supersedes
`perform`, and the single-arc `perform` action + handler are removed.**

- **Why supersede, not coexist:** the planner (`plan_push_performed_automation`)
  is the *only code* consumer of the `perform` action (verified by grep). The
  remaining references were docs — `guides/gaps.md` and
  `skills/ableton-push/SKILL.md` (both updated to `perform_batch`). A 1-arc
  batch is the degenerate case of `perform_batch`, so keeping single-arc
  `perform` would be dead-on-the-planner-path code with a parallel test burden
  — the *no-back-compat-to-throwaway* norm says remove it.
- **Mechanism preserved, not rewritten:** the proven gesture lifecycle
  (save → arm → seek → `begin_gesture` → play → ramp → `end_gesture` → stop →
  restore, beat-space interp, `re_enable_automation` set-wide, async
  `record_mode` settle-poll) is generalized from 1 gesture to N **windowed**
  gestures. The N=1 batch is byte-for-byte the old event sequence — the
  `test_..._exact_gesture_sequence` test pins that the proven path survives.
- **Per-parameter windowing (the new work):** each arc's `begin_gesture` opens
  when the playhead enters its span and `end_gesture` closes at its span exit,
  inside one shared pass over the UNION span `[min(start), max(end)]`. Arcs
  active at the union start open before `start_playing` (matching the single-arc
  order); later arcs open mid-ramp. So a short arc never stamps a flat value
  across the whole song.
- **Per-arc correlation:** each wire arc carries an opaque `arc_id` (the planner
  stamps the envelope id) the handler echoes back per-arc. `apply_push_results`
  gates each arc's performed-state on ITS own `automation_state` — one
  unverified arc never blocks the others, and fingerprint-gating composes
  (only changed arcs enter the batch).
- **Cost model:** wall-clock estimate is the UNION-span integral
  (`_estimate_span_seconds(union_start, union_end)`), not the per-arc sum — one
  continuous pass. The operator-facing overwrite warning moves from `notes`
  (diagnostic, unseen) to **`alert()`** (CLR-A's operator-actionable channel),
  naming every span the pass will record/overwrite (Visible Costs).

### Explicit descope (not a silent drop)

The single-arc action exposed optional `span_start_beats` / `span_end_beats`
(record a span wider than the breakpoints — pre-roll). **The planner never used
them** (it always recorded `[first_bp, last_bp]`), so `perform_batch` derives
each arc's span from its breakpoints and does **not** expose per-arc explicit
span in v1. Re-add if a pre-roll need arises.

### Partial-batch failure stance (v1)

A per-arc runtime error mid-pass (a gesture/value write raising) aborts the
whole pass; the `finally` closes every open gesture and disarms the set (safe),
and no fingerprints are recorded, so all arcs retry next push (safe but
pessimistic — a good arc recorded earlier in the pass is discarded). Granular
per-arc error isolation is a possible later refinement, out of Chunk 01 scope.

### DEFERRED Live probes (verify-api — Chunk 01 step 0)

Live was unavailable this session: the bridge reported a **version mismatch**
(MCP server `c0b443e0` vs Remote Script `b0c3c347`), and resolving it needs
`/ableton-mcp-install` + a full Live restart that would disrupt a 2nd agent's
open song; recording automation through a mismatched wire risks corruption.
Run these on a scratch set once the bridge is healthy (also in
`operator-verification.md`):

1. **Two gesture windows in ONE record pass** — `perform_batch` with two arcs
   whose spans overlap partially (e.g. master volume `[0, 64]` + return volume
   `[16, 48]`). Assert BOTH `automation_state == 1`, and the `.als` dump shows
   both lanes' breakpoints confined to their own spans (the inner arc must NOT
   write a flat value across the whole pass). This is the keystone correctness
   check for per-parameter windowing.
2. **Achieved breakpoint density (Hz)** under N-params-per-tick batching —
   record a single ~32-beat arc via `perform_batch` and count `.als`
   breakpoints; compare to the single-arc baseline (~2.5–3 Hz from ENV-7G4K).
   This is the Chunk 03 fidelity baseline and confirms batching doesn't starve
   the main thread.
3. **Safe batch ceiling** — if many simultaneous open gestures misbehave,
   record the max arcs-per-pass M (bounded-batch fallback).
