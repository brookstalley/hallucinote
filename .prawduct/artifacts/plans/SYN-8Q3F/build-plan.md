<!-- Build Plan — SYN-8Q3F (sync-boundary contract + complexity budget). Tier 1 (Source of Truth).
     WHAT to build. For HOW (governance, test discipline, Critic), read /prawduct:building.
     Requirements: .prawduct/artifacts/plans/SYN-8Q3F/requirements.md -->
---
artifact: build-plan
version: 1
scope: SYN-8Q3F
depends_on:
  - artifact: requirements
    path: .prawduct/artifacts/plans/SYN-8Q3F/requirements.md
last_validated: 2026-07-04
---

## Requirements Confidence

**Level:** High for Chunks 1–4 (code read in full; behavior-preserving; existing
tests pin today's behavior). Medium for the deferred chunks (5–6) — they depend on
BAK-7D2V landing and on user triage of the contract-violations list.

Critic mode: cumulative-final (chunks are small/structural; roll up at PR time per
[[feedback_critic_cadence_for_small_chunks]]).

## Status

- [x] Chunk 01 — **(a) Boundary-contract artifact.**
  `.prawduct/artifacts/sync-boundary-contract.md`: per-phase ASSUME / RE-PROBE /
  failure-policy for all 14 phases with file:line refs, executor cross-phase
  contract (special-case passes), pre-phase gates (coherence, arrangement probe,
  probe_and_link), apply-layer dispatch, and the "Contract violations found"
  section. Plus `tests/unit/sync/test_sync_boundary_contract.py` asserting every
  `_PHASE_NAMES` member has a phase section (complexity-budget rule 1, artifact
  half). Done when: artifact exists, coverage test green.
- [x] Chunk 02 — **(b) Phase ordering: prose → declared DAG.**
  `push/plan.py`: `_PHASE_DEPS` (per-phase declared dependencies),
  `PushPhase.depends_on` field, `PhaseOrderError` +
  `validate_phase_order(names, deps)` (unknown-dep, dep-after-dependent — which
  subsumes cycles for a total order — and unknown-phase-in-deps rejection), called
  from `plan_push_song` alongside the existing name canary. Fix the
  "thirteen-phase"/13 prose on the files touched. Tests: today's 14-name order
  validates and is byte-identical to the historical tuple; a reversed pair,
  an undeclared-dep graph, and a cyclic graph are rejected. Done when: suite
  green with no existing-test edits.
- [x] Chunk 03 — **(c) Unknown-result-kind: deliberate runtime policy.**
  `push/plan.py`: `KNOWN_RESULT_KEY_KINDS` registry constant
  (= `_LINK_KINDS ∪ _ACK_ONLY_KINDS ∪ {perform_batch}`) used by the apply
  dispatch's error message + the static guard. `push_execute.py`: wrap the two
  `_apply_results` call sites so an apply-layer `ValueError` (unknown kind /
  malformed key / missing arc_id — all planner↔apply contract drift) becomes a
  controlled phase halt: error record with the teaching message + hint, phase
  HALTED, later phases PENDING, terminal state file written, request closed
  `partial`, exit `EXIT_PARTIAL`. Apply layer keeps raising (its tests pin the
  fail-loud contract; the transaction still rolls the batch back). Tests: an
  executor run whose send_fn returns a result with a novel key kind exits
  EXIT_PARTIAL with the phase halted, state+errors files written, request closed —
  no traceback.
- [x] Chunk 04 — **(e) Diff-engine float-equality cross-check.**
  Decision: keep TWO comparison semantics (they are intentionally asymmetric —
  push-side 1e-6 skip-on-confident-equal vs pull-side 1e-3 churn-avoidance; see
  the artifact §Diff engines for the WHY) and PIN them instead of merging.
  New `tests/unit/sync/test_diff_float_semantics.py`: boundary-behavior pins for
  `push/device_param_diff._floats_equal` and `pull/_core`'s three matchers, plus
  the cross-engine invariant (push epsilon ≤ pull epsilon; push-skip ⟹
  pull-no-drift over representative pairs). Cross-referencing comments at both
  definition sites. Done when: suite green.
- [ ] Chunk 05 — **(d) capture.py split — DEFERRED.** Blocked on **BAK-7D2V**
  (parallel branch modifying capture.py now; splitting here guarantees a
  structural merge conflict). Re-plan after it lands: extract capture's probe
  walking / snapshot assembly / DB-write halves along the same _core/domain
  layout push/ and pull/ already use.
- [ ] Chunk 06 — **Contract-violation follow-ups (user triage).** From the
  artifact's violations section, the two behavior-relevant ones: (V2) a plan_fn
  raise (e.g. clips' W3-C strict ValueError under `--only clips`) escapes
  `execute_push` as a traceback — same class as the pre-Chunk-03 apply raise;
  convert to a controlled halt. (V3) the mix phase still owns a second
  return-CREATE path duplicating the returns phase. Plus prose-only fixes (V5–V7).
  File as backlog items rather than building silently.

Context: Chunks 1–4 built 2026-07-04 in worktree `feat/syn-8q3f-structural`
(base develop 6f2b0ba). Baseline 4435 passed / 2 skipped; engine-side only — NO
fingerprint path touched. The perform_batch watchdog is PSH-3H8M (code-done),
excluded from this item. Next session: PR the built chunks; then Chunk 06 triage;
Chunk 05 after BAK-7D2V merges.
