---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# SYN-4P2D — Independent Planning Review

**Reviewer:** adversarial spec-reviewer (did NOT author the design).
**Verdict:** **PASS** (no blocking defects). Two WARNINGs and three NOTEs below —
all are build-time precision improvements, none gates the plan.

I verified the design's load-bearing structural claims against the actual code
(not against the design's own prose) before reaching this verdict. Every claim I
checked held.

---

## Verification of load-bearing claims (against code, not prose)

| Design claim | Code checked | Holds? |
|---|---|---|
| Clip IndexError is the bug | `handlers/clip.py:289-293` raises `IndexError: clip_index {N} out of range [1, {len(slots)}]` | ✓ exact |
| `clip_index = clip["slot"]` | `sync/push/clips.py:76` | ✓ |
| `slot = idx + 1` (section index + 1) | `arrangement.py:368` | ✓ |
| Planner is pure-DB (can't see Live scene count) | `plan_push_clips` reads DB only; deficit math must be Live-side | ✓ — decisive fact is real |
| `create_handler` appends via `create_scene(-1)`, no `is`-scan | `handlers/scene.py:87,97,106` (`new_index = len(song.scenes)` for append) | ✓ exact — `ensure_count` reuse is sound |
| `_PHASE_NAMES` is the single source of truth + runtime drift-guard `raise` | `plan.py:51-62`, `plan.py:196-199` | ✓ |
| `_ACK_ONLY_KINDS` raises on undeclared kind; adding `"scene"` mandatory | `plan.py:232-266`, `apply_push_results:304-305` (`ValueError` on unknown) | ✓ — `"scene"` MUST be added or apply blows up |
| Empty plan → phase SKIPPED | `push_execute.py:457-464` (`if not plan.calls` → `_STATUS_SKIPPED`) | ✓ |
| Phase halts at boundary on any failed call | `push_execute.py:17` + `_STATUS_HALTED` | ✓ |
| `format_summary` is count-dynamic (no edit) | `push_execute.py:680` `f"all {len(result.phases)} phases"` | ✓ — correctly excluded from sweep |
| `ALIASES_TODAY` empty → `ensure_count` is directly-callable, no alias | `mcp_names.py:46` `ALIASES_TODAY = {}` | ✓ — "Sync planner discipline" learning honored |

The fix-option survey (DR-1) is sound. Option (b)'s rejection is correctly
grounded in the "Never use `is` for Live object identity" trap (each per-clip
`create_scene` re-wraps `song.scenes`) and the per-clip-vs-per-push granularity
argument. Option (c) is correctly retained as the *fallback error message*, not
discarded — this is exactly what the verifiable signal's "or fails with the
single actionable message" clause requires.

---

## Acceptance criteria are observable behavior — PASS

The verifiable signal ("push ≥9-section song into default 8-scene set COMPLETES,
or fails with the single actionable message, not 5 raw IndexErrors") is fully
covered and observable without a human ear:

- Done-when 5 (regression test): asserts `scenes` phase emits one `ensure_count`
  with `count == 9` BEFORE `clips`, every clip-create succeeds, `outcome == "ok"`
  — plus the **companion** assertion that a fake ignoring `ensure_count`
  reproduces the per-clip IndexError halt. The companion is the load-bearing
  half: it is the "pin what now FAILS" leg of the tree-wide-sweep discipline and
  is what makes the fix semantic rather than accidental. Its presence is the
  single best thing in this plan.
- Done-when 7 (live integration): exit-code + `len(song.scenes) >= 9` — purely
  objective, render-free, unattended-safe.
- The acceptance message for the unfixable case (`create_scene` absent) is
  spelled out verbatim in DR-2 — observable, actionable, names the deficit.

No "it works" hand-waving anywhere.

---

## No requirement silently dropped — PASS

All three backlog fix-options ((a)/(b)/(c)) are explicitly addressed: (a)
implemented, (b) rejected with rationale, (c) retained as the fail-fast fallback
message. The verifiable signal's both branches ("COMPLETES" and "single
actionable message") are each delivered. Nothing dropped.

---

## RULER-NOT-STAMP — PASS

`ensure_count` is a scaffold/ruler, not a stamp. The scene count is a pure
deterministic function (`max slot` over the song's already-authored session
clips) of the composer's existing arrangement — it makes no musical decision,
grades nothing, suggests nothing. The "Both-sides N/A" section (design lines
38-49) correctly argues this is sync infrastructure, not a new musical
dimension, so BOTH-SIDES (authoring surface + lens) does not apply. I agree:
there is no "amount" to author and nothing to measure. This is the correct call,
not a dodge.

---

## First chunk is a genuine thin vertical slice — PASS

The single chunk threads DB (max-slot read) → planner (`scenes` phase) → MCP
action (`ensure_count`) → executor → state file → SKILL contract. The
one-chunk decision is *forced by the architecture*, not laziness: the
drift-guard `raise` in `plan.py:196` and the `_ACK_ONLY_KINDS` `ValueError`
mean a partial landing is non-functional by construction (the phase tuple and
`_PHASE_NAMES` must agree at all times). A narrower slice would not run. The
work classification (small bugfix) is honest.

---

## verify-api step present in the foreign-API chunk — PASS

`**Foreign API:** ableton-live-mcp` is declared (build-plan line 43) and
Done-when **step 0** is a `verify-api` step (build-plan lines 45-50): re-read
`create_handler`, then probe a live instance (`list` → note count; `create` →
confirm count grows by 1, append index `-1`). The literal token `verify-api`
appears. Satisfies the Critic's Goal-2 check. The probe is well-chosen — it
confirms the exact append semantics `ensure_count` depends on against real Live,
not against an assumed signature (honors the "Unit fakes that mirror an *assumed*
Live API give false confidence" learning).

---

## By-ear / render-gated decisions flagged — PASS

`byEarCalls = []` is explicitly recorded (design line 246, build-plan
"PENDING by-ear calls: None"). This is correct, not a guess-in-disguise: scene
count is a deterministic integer; there is no audio to render and no amount to
tune. The unattended-Live constraint is satisfied because the entire verifiable
signal is exit-code + scene-count objective. Nothing is silently guessed.

---

## Requirements Confidence honesty — PASS

"High" is justified. Problem/success/scope are each one sentence; the foreign
API surface is already exercised in-tree; the only spread is the mechanical
tree-wide sweep, enumerated surface-by-surface. There are no real unknowns. I
could not find a reason to downgrade it. This is one of the cleaner High-confidence
claims I've reviewed.

---

## WARNINGS (address at build time; do not gate the plan)

### W1 — The SKILL.md inline phase *arrow sequence* is a phase-order pin the sweep table does not call out explicitly

`skills/ableton-push/SKILL.md` line 2 (and the parallel prose) contains the
literal ordered arrow list
`tempo → meter → tracks → returns → clips → mix → devices → envelopes → arrangement → cues`
— ten phases, in order. DR-3 says to "update the prose to eleven and add a
`scenes` row to the tool-mapping table," which generically covers it, but does
**not explicitly name the arrow sequence**. If the builder updates the count
word ("ten"→"eleven") and the table but leaves the arrow list at ten entries,
the result is exactly the self-contradicting doc the "Pattern sweeps are
tree-wide or they don't count" learning warns about (description says 11, arrow
lists 10, missing `scenes`). **Fix:** add a row to the DR-3 sweep table (or a
sentence in Done-when 4) explicitly requiring `scenes` to be inserted into the
inline arrow sequence between `returns` and `clips`, wherever that sequence
appears (line 2 description + any body repetition). The Done-when 4 grep
(`'ten phases\|10 phases\|Returns 10 phases'`) will NOT catch a stale arrow list
because the arrow list contains no count word — so the grep alone is insufficient
to prove this surface was swept. Add a second grep for the arrow sequence (e.g.
`grep -n 'returns → clips\|returns.*clips'`) or eyeball line 2 directly.

### W2 — `plan_push_scenes` empty-plan path deviates from the documented per-phase "warn, don't bare-empty" convention

The design's DR-4 has `plan_push_scenes` return a bare `PushPlan()` (no warn)
when `max_slot <= 0`. But the sibling planners follow a documented convention:
`plan_push_clips` (`clips.py:134`) emits `plan.warn("no clips for this song;
nothing to push")` on the empty path, and `plan_push_song`'s docstring
(`plan.py:119-125`) explicitly states phases "produce a plan with a 'no … to
push' warn instead of an empty plan, so the skill's progress reporting can
distinguish 'ran cleanly with nothing to do' from 'phase skipped'." A bare empty
plan still SKIPs correctly in the executor (`warn` adds no *call*, so
`if not plan.calls` is still True either way), so this is **not** a
correctness bug — the verifiable signal is unaffected. But it is a coherence
divergence: `scenes` would be the one phase that silently empties instead of
warning, contradicting the docstring it lives next to. **Fix:** have
`plan_push_scenes` emit `plan.warn("no session clips; no scenes to provision")`
on the `max_slot <= 0` path, matching the convention. Minor; flag for the
builder.

---

## NOTES (builder's judgment; non-blocking)

### N1 — DR-2's `count >= 1` schema floor vs. planner-emitted values

The handler validates `count >= 1` (`ParamSpec(... minimum=1)`) and the planner
only emits when `max_slot > 0`, so the planner can never trip the floor — good,
no dead branch. But confirm at build time that a *human* calling
`ableton_scene(action='ensure_count', count=0)` directly gets the teaching
`ValueError`, not a silent no-op (DR-2 says reject `count < 1`; the schema
`minimum=1` would reject at the dispatcher before the handler — verify which
layer produces the teaching message so it's actually actionable, not a bare
schema rejection).

### N2 — The `create_scene`-absent fallback message duplicates an existing handler's refuse path

`create_handler` already raises `NotImplementedError("Song.create_scene not
exposed in this Live version")` when `create_fn is None` (`scene.py:88-91`).
DR-2's `ensure_count` raises a *different, more actionable* message (names the
deficit + "re-run the push (idempotent)"). This is intentional and better — but
note the two messages now describe the same Live-capability gap differently. Not
a problem (different call sites, different actionable advice), just worth a
one-line comment at the `ensure_count` raise pointing at why it doesn't reuse
`create_handler`'s message. Builder's call.

### N3 — `allowed-tools` frontmatter correctly NOT edited (verified)

I checked whether the new `ableton_scene(ensure_count)` call requires adding
`mcp__hallucinote-mcp__ableton_scene` to SKILL.md's `allowed-tools` (line 5,
which currently omits `ableton_scene`). It does **not**: `push_cli execute`
resolves `send_fn` via the in-process MCP **TCP client**
(`push_cli.py:96-98,142-144,182-184`; `_client.send`), not the agent's
allowed-tools MCP dispatch — and the `--probe` path uses the same TCP client
(`_probe_live_via_mcp`, `push_cli.py:81-89`). The design's omission of an
`allowed-tools` edit is therefore correct, not a gap. Recording this so the
builder doesn't "helpfully" add it and muddy the contract. (If a future change
ever drives `ensure_count` via the agent's direct MCP path, this flips.)

---

## Summary

A rigorous, code-grounded bugfix design. It correctly identifies the decisive
structural fact (planner is pure-DB → deficit math must be Live-side), picks the
fix that delivers the strongest verifiable signal, retains option (c) as the
honest fallback, honors the relevant learnings (`is`-scan trap, tree-wide sweep,
sync-planner-signature discipline, fakes-must-model-the-real-failure), correctly
ranks BOTH-SIDES as N/A with sound reasoning, and flags zero by-ear calls
truthfully. The companion "fails-without-the-fix" regression assertion is the
plan's strongest feature. The two WARNINGs are build-time precision items (the
arrow-sequence sweep completeness, and the warn-on-empty convention), neither of
which affects the verifiable signal. **PASS.**
