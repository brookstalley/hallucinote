<!-- Requirements — SYN-8Q3F (sync-boundary contract + complexity budget; audit 2026-07-02 rec #8).
     WHAT this item must deliver. For HOW (governance), read /prawduct:building. -->
---
artifact: requirements
version: 1
scope: SYN-8Q3F
depends_on:
  - artifact: audit
    path: .prawduct/artifacts/audit-2026-07-02.md
  - artifact: design
    path: .prawduct/artifacts/arrangement-materialization-redesign.md
last_validated: 2026-07-04
---

# SYN-8Q3F — Sync-boundary contract + complexity budget

## Problem (observable)

The sync adapter is **16.7k lines — 37% of the engine** (sync/ 5,838 + push/ 6,271 +
pull/ 4,617) against 1.9k of generators, and it grows **quirk-first**: each Live
misbehavior lands as a special-case branch with the governing contract held only in
prose. Concretely:

1. **14 push phases whose ordering constraints live in comments.** The order is a
   hardcoded tuple (`push/plan.py _PHASE_NAMES`) whose *rationale* is a 70-line
   docstring; nothing machine-checks that the order satisfies the dependencies the
   prose asserts. Prose has already drifted: module docstrings still say
   "thirteen-phase" (`push_execute.py:2`, `push_cli.py:695`) and the orchestrator
   docstring numbers phases "1..13" with a "9b." splice.
2. **The unknown-result-kind halt class was point-patched twice**, one key kind
   apart: `device_param_override` (2026-06-18) and `device_chain_props`
   (2026-06-20) — the exact patch-the-symptom pattern ARR-PROJ was commissioned to
   end. A static emitted-kind guard now exists
   (`tests/unit/sync/test_push.py test_every_emitted_push_key_kind_is_declared`),
   but the *runtime* policy for a genuinely-unknown kind is still an uncaught
   `ValueError` that escapes `execute_push` as a raw traceback — violating the
   executor's own always-write-state + close-request contract.
3. **Two parallel diff engines hold independent float-equality semantics** that can
   drift: push-side `push/device_param_diff.py::_floats_equal` (rel+abs 1e-6,
   skip-on-confident-equal) vs pull-side `pull/_core.py::_FLOAT_EPS` (1e-3,
   absolute / relative variants). Nothing pins their relationship, so a tolerance
   edit on one side can silently break the push↔pull fixed point.
4. **What each phase may ASSUME vs must RE-PROBE from Live is undocumented.** The
   executor carries per-phase special-case passes (devices diff-reconcile,
   empty-rack guard, convergence re-plan, arrangement integrity assert, pad probe,
   cue deferral) whose trust boundaries exist only in scattered comments.

## Success criteria

- **(a)** `.prawduct/artifacts/sync-boundary-contract.md` exists, derived from the
  phase *implementations* (file:line referenced), covering all 14 phases: what each
  assumes from prior phases / the plan, what it re-probes from Live, and its
  failure/halt policy. Discrepancies between actual behavior and a sensible
  contract are recorded in a "Contract violations found" section (follow-up
  candidates), not silently normalized. A test asserts every `_PHASE_NAMES` member
  has a section in the artifact, so adding a phase without documenting its contract
  fails the suite (the cheap half of the complexity budget).
- **(b)** Phase ordering is declared data: each `PushPhase` declares
  `depends_on`; `plan_push_song` validates the declared order against the declared
  dependency graph (unknown dep / dep-after-dependent / cycle → raise). Behavior
  preserving: the executed order is byte-identical to today's `_PHASE_NAMES`
  (pinned by test).
- **(c)** Unknown-result-kind handling is a deliberate, tested policy: every known
  kind has an explicit resolution (`_LINK_KINDS` / `_ACK_ONLY_KINDS` /
  `perform_batch` — unioned into one registry constant); a genuinely-unknown kind
  fails **loud with context but controlled** — the executor converts the apply-layer
  `ValueError` into a phase halt (state file written, errors file carries the
  teaching message, request closed `partial`, exit `EXIT_PARTIAL`) instead of a raw
  traceback. The apply layer keeps its fail-loud `ValueError` (tests pin it); the
  static emitted-kind guard remains the structural exhaustiveness check.
- **(d)** *(deferred — see below)* capture.py split.
- **(e)** The two diff engines' float semantics are cross-checked: a test pins each
  side's tolerance behavior at its boundaries AND the cross-engine invariant
  (push-skip ⟹ pull-no-drift, i.e. push epsilon ≤ pull epsilon), with the
  intentional asymmetry documented at both definition sites.
- Full no-path `python -m pytest` green; all existing tests unchanged
  (behavior-preserving structural work).

## Out of scope

- **capture.py split — explicitly deferred (d).** A parallel branch (**BAK-7D2V**)
  is modifying `capture.py` right now; splitting it in this branch would guarantee
  a structural merge conflict. Re-plan after BAK-7D2V lands.
- **perform_batch watchdog** — that is **PSH-3H8M** (code-done), not this item. Do
  not duplicate.
- Rewriting `probe_and_link` (~390 lines) — its contract is *documented* in (a);
  decomposition is follow-up scope if the contract review justifies it.
- Any MCP wire-shape change. Everything here is engine-side
  (`src/hallucinote/sync/...`); the fingerprint must not flip.
- Fixing every prose drift found — recorded in (a)'s violations section; only
  drift on files already being edited (plan.py / push_execute.py phase-count
  prose) is fixed inline.

## Complexity budget (the standing rule this item installs)

The sync adapter may keep absorbing Live quirks, but each absorption must land
inside a *declared* structure, not as free-floating prose:

1. **A new push phase** must declare its dependencies in `_PHASE_DEPS` (the order
   validator fails otherwise) **and** get a section in
   `sync-boundary-contract.md` (the artifact-coverage test fails otherwise).
2. **A new result key kind** must be declared in `_LINK_KINDS` /
   `_ACK_ONLY_KINDS` / a dedicated branch (the static emitted-kind guard fails
   otherwise); a kind that reaches apply undeclared halts the push *controlled*,
   never as a traceback.
3. **A new float-comparison site** in either diff engine must reuse the existing
   tolerance constants/helpers of its side; changing a tolerance requires updating
   the cross-engine invariant test knowingly.
4. **A new executor special-case pass** (per-phase branch in `execute_push`) must
   be recorded in the boundary-contract artifact's executor section in the same
   change.

## Requirements confidence

**Level: High** for (a)/(b)/(c)/(e) — all derived from code read in full this
session; (b)/(c) are behavior-preserving with existing tests pinning today's
behavior. **Assumptions:**

- `[ASSUMPTION: performed_automation → arrangement relative order is convention,
  not dependency — arrangement clears CLIPS only, perform writes automation lanes;
  no dep is declared between them | LOW impact | validator keeps today's order
  regardless]`
- `[ASSUMPTION: the controlled-halt conversion for apply-layer ValueError is the
  policy the error model wants (phase-bounded accumulation + always-write-state +
  close_request); no caller relies on the traceback | MED impact | user can
  override to keep raw propagation]`
