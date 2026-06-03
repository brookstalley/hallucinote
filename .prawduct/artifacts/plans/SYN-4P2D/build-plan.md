# SYN-4P2D — Build Plan

**Item:** SYN-4P2D — first push of a >8-section song into a fresh default 8-scene
set hard-fails at `clips`; push doesn't auto-provision scenes.
**Design:** `.prawduct/artifacts/plans/SYN-4P2D/design.md` (read it; this plan
does not restate the decision records).

## Requirements Confidence: **High**

- Problem, success, and scope are each one sentence (see design.md).
- Fix option chosen with rationale (DR-1); the foreign API surface
  (`song.scenes` / `song.create_scene(-1)`) is already exercised by the in-tree
  `create_handler` — no unknown Live verb.
- The only "spread" is the tree-wide phase-count sweep (DR-3), which is
  enumerated surface-by-surface — mechanical, not uncertain.
- Nothing would raise it further; this is the cleanest autonomous-ready item.

## Work classification

Small bugfix that crosses one contract surface (the push phase contract) and
adds one MCP action. Single vertical-slice chunk (the fix is inherently atomic —
the new MCP action, the new planner phase, and the tree-wide phase-count sweep
must all land together or the drift-guard / `_ACK_ONLY_KINDS` raise fires). One
chunk keeps the diff reviewable in a single Critic pass.

---

## Chunk 1 — `scenes` provisioning phase + `ableton_scene(ensure_count)`, end-to-end

**Thin vertical slice:** this single chunk proves the whole path — DB (max-slot
read) → planner (`scenes` phase) → MCP action (`ensure_count`) → executor →
state file → the agent-facing SKILL contract. There is no narrower first slice;
the phase-count contract is pinned in N places that must agree at all times
(the drift-guard `raise` in `plan.py` enforces it), so a partial landing is
non-functional by construction.

- **Type:** code
- **Critic mode:** final
  *(single-chunk plan → inference picks `final`; declared explicitly because this
  chunk lands the phase-contract keystone — Goals 4 (Coherence, across the
  tree-wide sweep) and 7 (Design) must run, and the cross-file coherence is the
  main risk here.)*
- **Foreign API:** ableton-live-mcp
- **Done when:**
  0. **verify-api** — re-read `hallucinote_mcp/src/hallucinote_mcp/handlers/scene.py`
     `create_handler` (lines ~73-110) to confirm `song.create_scene(-1)` appends
     and the no-`is`-scan index pattern; with Live UP, probe a real instance
     (`ableton_scene(action='list')` → note `len(scenes)`; `ableton_scene(action='create')`
     → confirm count grows by 1) to confirm the append semantics before writing
     `ensure_count`. Confirm `count: int` is the only new param the planner emits.
  1. **MCP action exists:** `ableton_scene(action='ensure_count', count=N)` is
     registered (`actions/scene.py`) with `ParamSpec(name="count", type="int",
     minimum=1)` and dispatches to a new `ensure_count_handler` (`handlers/scene.py`).
     Handler computes `needed = count - len(song.scenes)`, appends `max(0, needed)`
     scenes via `create_scene(-1)`, returns `{"scene_count": ..., "created": ...}`.
     `needed <= 0` is a no-op (idempotent). When `count > len(scenes)` AND
     `create_scene` is unavailable, raise with option (c)'s single actionable
     message (see design DR-2). `count < 1` → teaching `ValueError`.
  2. **Planner phase exists:** new `plan_push_scenes(conn, *, song_id, session_id)`
     (new module `src/hallucinote/sync/push/scenes.py`) emits one
     `ableton_scene(action='ensure_count', count=max_slot)` call where `max_slot
     = max(clip["slot"] for clips in song, default 0)`. When `max_slot <= 0`, the
     plan emits NO `ToolCall` but DOES emit `plan.warn("no session clips; no
     scenes to provision")` — matching the documented per-phase warn-not-bare-empty
     convention (`plan.py:119-125` docstring; sibling `clips.py:134`), so `scenes`
     is not the lone phase that silently bare-empties (review W2). The warn adds no
     call, so the executor still reports the phase SKIPPED. Key `scene:ensure`
     (ack-only kind `"scene"`).
  3. **Phase wired before `clips`:** `plan.py` `_PHASE_NAMES` and the
     `plan_push_song` phases tuple both have `"scenes"` immediately before
     `"clips"`; the runtime drift-guard passes; `"scene"` added to
     `_ACK_ONLY_KINDS`. Phase order: tempo_map, time_signature_map, tracks,
     returns, **scenes**, clips, mix, devices, envelopes, arrangement, cues (11).
  4. **Tree-wide phase-count sweep complete** (per design DR-3 + the
     "Pattern sweeps are tree-wide" learning). The sweep has TWO independent
     surfaces, each with its own grep — the count-word grep alone is insufficient
     because the SKILL.md arrow sequence carries no count word (review W1):
     - **4a — count-word grep:** `grep -rn 'ten phases\|10 phases\|Returns 10'
       src tests skills hallucinote_mcp/src` leaves every live hit either (a)
       updated to eleven, or (b) an intentional dated-archive reference under
       `docs/archive/**` with no behavioral pin. Specifically updated:
       `plan.py` docstrings, `push_notes.py:11`, `test_push_song.py` (phase-count
       + name-list + end-to-end emit-count assertions), `test_push_execute.py`
       (name list), `skills/ableton-push/SKILL.md` count words (frontmatter +
       body prose).
     - **4b — arrow-sequence grep (mandatory; the count-word grep CANNOT catch
       this):** `grep -n 'returns → clips\|returns.*→.*clips' skills/ableton-push/SKILL.md`
       must return ZERO hits after the sweep — every occurrence of the inline
       arrow list `tempo → meter → tracks → returns → clips → …` (line 2
       `description:` + any body repetition) has `scenes` inserted **between
       `returns` and `clips`** → `… → returns → scenes → clips → …`. Confirm
       positively with `grep -n 'returns → scenes → clips' skills/ableton-push/SKILL.md`
       (must return ≥1 hit). If the builder updates the count word but leaves the
       arrow at ten entries, the result is the self-contradicting doc W1 / the
       tree-wide-sweep learning warns about — this grep is the proof it didn't.
     - **4c — tool-mapping table:** `skills/ableton-push/SKILL.md` phase-by-phase
       tool-mapping table gains a `scenes → ableton_scene(action='ensure_count')`
       row positioned before the `clips` row.
     `push_execute.py format_summary` is confirmed to need NO edit (uses
     `len(result.phases)` dynamically) — do not regress it to a literal.
  5. **Regression test (the bug's signal):** a test pushing a synthetic
     **9-section** song (9 session clips at slots 1..9 on ≥1 track) through
     `execute_push` with a fake `send_fn` that models a default 8-scene set —
     i.e. the fake's `ableton_clip:create` raises `IndexError` for `clip_index >
     scene_count` UNLESS a prior `ableton_scene:ensure_count` raised the count.
     ASSERT: with the fix, the `scenes` phase emits one `ensure_count` call with
     `count == 9` BEFORE the `clips` phase, every clip-create succeeds, and
     `result.outcome == "ok"`. Companion assertion (pins what now passes): a fake
     that ignores `ensure_count` (simulating the pre-fix world) reproduces the
     per-clip IndexError halt at `clips` — proving the test fails without the
     provisioning. Plus a handler unit test: `ensure_count` is idempotent
     (`needed <= 0` creates nothing) and the `create_scene`-absent path raises
     the actionable message. Plus a planner unit test (pins review W2's warn
     convention as a contract, not just prose): `plan_push_scenes` on a song with
     no session clips (`max_slot <= 0`) returns a plan with NO calls but a
     non-empty `notes`/warn (`"no session clips; no scenes to provision"`) —
     asserting `scenes` warns rather than bare-empties, matching the sibling
     `plan_push_clips` empty-path. Tests live in
     `tests/unit/sync/test_push_execute.py` (+ `tests/unit/sync/test_push_song.py`
     for the phase-order/emit assertions and the planner warn-on-empty assertion)
     and `hallucinote_mcp/tests/unit/` for the handler. Use the project's
     re-wrapping fake discipline for any `song.scenes` access (no `is`-scan).
  6. Full suite passes (`pytest` over `tests`, `hallucinote_mcp/tests`, `songs`).
  7. **Live integration verification (objective, unattended-safe):** push the
     synthetic 9-section song into a fresh/default 8-scene Live set via the real
     `push_cli execute` path; PASS = exit 0 / `.last-push-state.json` `outcome:
     ok` with the `scenes` phase `ok` and `len(song.scenes) >= 9` after
     (`ableton_scene(action='list')`). No render, no ear needed — purely
     exit-code + scene-count objective. If Live cannot be driven this run,
     downgrade to "documented, unit-proven; live integration deferred to next
     attended run" and say so explicitly (Principle 5) — do NOT claim a live pass
     that didn't happen.
  8. `/critic` run (mode `final`) and blocking findings resolved.
  9. Committed; chunk marked `[x]` in Status; reflection captured.

---

## Verification strategy

- **Unit (no Live, gates the chunk):** the regression test (Done-when 5) is the
  spec made executable — it pins the new phase order, the `ensure_count` emit,
  the idempotent handler, and the actionable-message fallback. The companion
  "fails without provisioning" assertion is the teeth that make the fix
  semantic, not accidental (the tree-wide-sweep learning's step 3).
- **Fake discipline (the recurring Live-fake trap):** the fake `send_fn` must
  model the *real* failure — a clip-create into a slot beyond the set's scene
  count raises `IndexError` (mirroring `handlers/clip.py:289-293`), and only
  succeeds after `ensure_count` grew the count. A fake that always succeeds at
  clip-create would give false confidence (the "Unit fakes that mirror an
  *assumed* Live API give false confidence" learning). Any `song.scenes` access
  in a handler-level fake uses the re-wrapping fake helper (`song.scenes` returns
  a fresh wrapper sequence each access) so a stray `is`-scan would fail.
- **Live integration (objective):** Done-when 7 — exit code + scene count, fully
  unattended-safe.

## Boundary investigation

This chunk crosses the **push phase contract** surface (a documented contract
boundary: the `_PHASE_NAMES` tuple + its SKILL.md mirror + the apply-side
`_ACK_ONLY_KINDS` dispatch table). Consumers of the contract: `push_execute.py`
(iterates phases, applies results — handled: `format_summary` is count-dynamic,
the apply layer gains the `"scene"` ack kind), the `ableton-push` skill
(agent-facing — updated in the sweep), and the unit tests that pin the count
(updated as contracts). The grep audit in Done-when 4 IS the boundary
investigation; record its results in the chunk.

## Governance checkpoint

One chunk → one checkpoint: the `final` Critic pass after Done-when 6, before the
live integration claim. The architecture-validation and completion checkpoints
collapse into this single pass because the chunk is the whole slice.

## PENDING by-ear calls

**None.** Scene count is a deterministic integer derived from the song's section
count; there is no "amount to tune" and no audio to render or audition. This
item has zero by-ear surface (recorded per the unattended-Live constraint).

---

## Review resolution

Independent planning review (`review.md`) verdict: **PASS**, no blocking
findings. Both WARNINGs were code-grounded coherence improvements fully
resolvable in the design phase; both are now resolved:

- **W1 (SKILL.md inline arrow sequence is an uncaught phase-order pin)** —
  Verified against `skills/ableton-push/SKILL.md` line 2: the `description:`
  frontmatter carries the literal arrow list `tempo → meter → tracks → returns →
  clips → … → cues` with **no count word**, so the Done-when-4 count-word grep
  cannot prove it was swept. Resolved by (1) splitting the DR-3 SKILL.md sweep
  row into three explicit surfaces — count words, the inline arrow sequence
  (insert `scenes` between `returns` and `clips`), and the tool-mapping table —
  and (2) splitting Done-when 4 into 4a (count-word grep), 4b (mandatory
  arrow-sequence grep: `grep -n 'returns → clips' …` must be ZERO and `grep -n
  'returns → scenes → clips' …` must be ≥1), and 4c (table row). The second grep
  is now the proof the arrow surface was swept.

- **W2 (`plan_push_scenes` empty path bare-empties instead of warning)** —
  Verified against `plan.py:119-125` (docstring mandates warn-not-bare-empty so
  the skill can distinguish "ran cleanly with nothing to do" from "phase
  skipped") and the sibling `clips.py:134` (`plan.warn("no clips …")`). Resolved:
  DR-4's code sketch + prose now have `plan_push_scenes` emit `plan.warn("no
  session clips; no scenes to provision")` on the `max_slot <= 0` path; Done-when
  2 documents it; Done-when 5 adds a planner unit test pinning the warn (NO calls,
  non-empty notes) as a contract. Not a correctness change (a warn adds no call,
  so the phase still SKIPs), purely the documented coherence convention.

NOTES N1–N3 are builder-judgment items already accounted for in the design
(N1: confirm which layer emits the `count < 1` teaching message; N2: optional
one-line comment at the `ensure_count` raise; N3: `allowed-tools` correctly NOT
edited because `push_cli` uses the in-process TCP client) — no spec edit needed.

---

## Status

- [x] **Chunk 1** — `scenes` provisioning phase + `ableton_scene(ensure_count)`, end-to-end.
  - Done-when 0 (verify-api): code-read confirmed `create_scene(-1)` append semantics; live probe folded into Done-when 7.
  - Done-when 1–5: implemented (new `sync/push/scenes.py`, `ensure_count` action+handler, `"scenes"` phase before `"clips"`, `"scene"` ack-only kind, full tree-wide phase-count sweep, regression + unit tests).
  - Done-when 4 sweep: **extended after first Critic pass** — the count-word grep missed 9 hyphenated `ten-phase` refs (`push_cli.py`, `push_execute.py`, `push_notes.py`, `test_push_cli.py`, `test_push_notes.py`); all swept to `eleven-phase`; re-grep clean.
  - Done-when 6: full suite green — **serial (canonical) invocation deterministic**; parallel `-n auto --dist loadgroup` confirmed green across repeated runs after the flake fix below.
  - Done-when 7 (Live integration, objective): **DEFERRED to next attended/post-install run, stated explicitly (not claimed).** The new `ableton_scene(action='ensure_count')` lives in the MCP server on this uninstalled feature branch, so it is not registered in the running bridge (needs a branch install + MCP server reload — an attended step that would disrupt the live session). The unit regression (Done-when 5) verifies the fix against the *real* failure mode (a fake `send_fn` modeling Live's actual per-clip `IndexError` from `handlers/clip.py:289-293`), so the fix is proven; the live exit-code/scene-count pass is queued for an attended run.
  - Done-when 8 (`/critic final`): run; 0 blocking, 2 warnings + 1 note — all resolved.

**Context:** SYN-4P2D complete on `fix/syn-4p2d-scenes-provisioning`. While verifying, an intermittent parallel-only flake surfaced in an unrelated test (`test_mix::test_set_send_intended_rt60_validator_contract`) — root-caused to hypothesis's default 200ms per-example deadline on an I/O-bound (real SQLite per example) property test under `-n auto` CPU contention, and **fixed in-PR** with `@settings(deadline=None)` (no assertion weakened). Next: ARR-9K4T.
