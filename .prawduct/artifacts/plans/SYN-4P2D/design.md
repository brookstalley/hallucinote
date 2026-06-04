# SYN-4P2D — Design

**Item:** SYN-4P2D (area: sync). Bug, effort S, impact L.
**Type:** bugfix (no both-sides authoring/lens surface — see "Both-sides N/A" below).
**Confidence:** High.

> Source of truth for the bug, signal, and fix-option survey:
> `.prawduct/backlog.md` lines 427-449 and `.prawduct/artifacts/plans/SYN-4P2D/research.md`.
> This design does not restate the root-cause trace — read research.md for it.
> Below records only the *design decisions* layered on top of that grounding.

## Problem (one sentence)

The first push of a song with more sections than the set has scenes hard-fails
at the `clips` phase with one raw `IndexError: clip_index N out of range [1, M]`
per affected track, because the push never provisions the scenes (= session clip
slots) its section clips require.

## Success (one sentence)

Pushing a ≥9-section song into a fresh default 8-scene set **COMPLETES** — the
push provisions the scenes it needs before creating clips — and if scene
provisioning is impossible, it fails fast with a single actionable message
("song needs N scenes; set has M — add N−M"), never N raw per-clip IndexErrors.

## Out of scope

- Deleting/trimming *excess* scenes (a set with more scenes than the song needs
  is fine — empty trailing scenes are harmless). `ensure_count` only grows.
- Auto-creating slots per-clip (option (b) — rejected, see DR-1).
- Any change to how `slot` is derived (`arrangement.py:368`, `slot = idx + 1`) —
  that mapping is correct; the bug is the missing provisioning, not the slot math.
- Scene *naming* — provisioned scenes keep Live's default names. Naming session
  scenes after sections is a separate cosmetic concern, not this bug.

---

## Both-sides N/A (ruler-not-stamp boundary)

The BOTH-SIDES principle (every *dimension* needs an authoring surface + a
measurement lens) does not apply here: this is a sync-infrastructure bug, not a
new musical/expressive dimension. There is no "amount" to author and nothing to
measure or grade. `ensure_count` is a **ruler/scaffold**, not a stamp: it
provisions the structural substrate (clip slots) that the *already-authored*
arrangement requires, derived deterministically from the song's section count.
It makes no musical decision — the number of scenes is a pure function of the
song the composer already wrote (`max slot` over the song's session clips). The
composer's arrangement is the source; the scenes are its mechanical shadow in
Live. Nothing here grades, suggests, or chooses on the composer's behalf.

---

## Decision records

### DR-1 — Fix option: (a) a `scenes` phase + idempotent `ensure_count` MCP action, with (c) as the fail-fast fallback

**Decided:** Implement option (a): a new idempotent MCP action
`ableton_scene(action='ensure_count', count=N)` plus a new `scenes` phase in the
push planner that runs **before** `clips`. Option (c)'s single actionable
message becomes the natural error surface if `ensure_count` cannot satisfy the
request (e.g. `Song.create_scene` unavailable in this Live build).

**Why (a) and not (b) or (c)-alone:**

The decisive structural fact (confirmed in research.md): **the planner is
pure-DB.** It knows the *required* max slot (from `Q.get_clips_for_song` →
`clip["slot"]`) but NOT the *current* Live scene count. It therefore cannot
compute the deficit `needed = N − M` itself — that subtraction must happen
Live-side. This forces the shape: planner emits "ensure at least N scenes
exist"; the MCP handler reads `len(song.scenes)` and appends the deficit.

| Option | Verdict | Rationale |
|---|---|---|
| (a) `scenes` phase + `ensure_count` | **CHOSEN** | Deficit math runs Live-side (only side that can see the current count). Idempotent. One call per push (not per-clip). Reuses the proven `ableton_render(ensure_loaded)` "idempotent provisioning sweep" precedent and the existing `create_scene` append semantics. Delivers the strongest verifiable signal ("COMPLETES"). |
| (b) `clips` auto-creates missing slot on demand | **REJECTED** | Wrong layer + wrong granularity: couples the clip-create handler to scene lifecycle, scatters scene creation across N per-clip calls, and each `create_scene` re-wraps `song.scenes` (the "never use `is` for Live object identity" trap). Races on slot indices when N clips on N tracks all discover the slot missing. |
| (c) pre-flight coherence check, fail fast only | **FALLBACK, not primary** | Strictly better than the status quo (one message instead of N IndexErrors) but leaves the *common* new-song path broken: the user must hand-run `ableton_scene(create)` then re-push. We keep (c)'s message — but only as the error `ensure_count` raises when it structurally cannot provision (no `create_scene`), so the autonomous path is fixed AND the unfixable case still teaches. |

**Trade-offs accepted:**
- Adds an 11th phase. This is a contract change pinned across multiple surfaces
  (see DR-3) — the cost is a tree-wide sweep, paid once.
- `ensure_count` only *grows* scene count; it never trims. A set with surplus
  empty scenes is left as-is. Accepted: empty trailing scenes are harmless and
  trimming would be a destructive op needing its own safety story (out of scope).

### DR-2 — `ensure_count` handler shape (verify-api grounded)

**Decided:** New handler `ensure_count_handler(context, *, count: int)` in
`hallucinote_mcp/handlers/scene.py`, registered as
`ableton_scene(action='ensure_count', count=int)` in `actions/scene.py`.

Behavior (grounded in the existing `create_handler`, scene.py:73-110, read
during this design):

```
needed = count - len(song.scenes)
for _ in range(max(0, needed)):
    song.create_scene(-1)          # -1 == append (Live's documented semantic)
return {"scene_count": len(song.scenes), "created": max(0, needed)}
```

- **Idempotent:** `needed <= 0` → creates nothing, returns the current count.
  Re-running the whole push is therefore a no-op for this phase (matches the
  push's idempotency contract — `_core` / `plan.py` docstrings).
- **No `is`-scan:** like `create_handler`, it never scans `song.scenes` for
  object identity (the re-wrapping trap). It only reads `len(song.scenes)` before
  and after, and appends via the `-1` index. This is deterministic-from-semantics
  (the "Never use `is` for Live API object identity" learning).
- **Refuse-and-teach fallback (option (c)):** if `getattr(song, "create_scene",
  None) is None` AND `needed > 0`, raise a `NotImplementedError` (or
  `RuntimeError`) carrying option (c)'s actionable message:
  `"song needs {count} scenes; set has {len(song.scenes)} and this Live build "`
  `"does not expose Song.create_scene — add {needed} scenes manually, then "`
  `"re-run the push (idempotent)."` This is the single actionable message the
  verifiable signal allows as the acceptable failure.
- **`count` validation:** `count >= 1` (a set always has ≥1 scene; asking for 0
  is meaningless). Reject `count < 1` with a teaching `ValueError`. Schema
  `ParamSpec(name="count", type="int", minimum=1)`.

**Verify-api note (Foreign API: ableton-live-mcp):** the real Live surface used
is `song.scenes` (length) and `song.create_scene(index)` with `-1`=append —
both already exercised by the in-tree `create_handler` (scene.py:73-110). The
build chunk's verify-api step re-reads that handler to confirm the append
semantics before writing `ensure_count`, and (Live being up) probes a real
instance: call `ableton_scene(action='create')` / `list` to confirm
`len(song.scenes)` grows by one and the append index is `-1`. No new Live API
verb is introduced.

### DR-3 — 11th phase is a tree-wide contract sweep

Adding the `scenes` phase changes the phase contract pinned in **all** of these
surfaces. Per the "Pattern sweeps are tree-wide or they don't count" learning,
they MUST move together in one chunk (a partial sweep ships self-contradicting
docs):

| Surface | What pins the count/order | Edit |
|---|---|---|
| `src/hallucinote/sync/push/plan.py` | `_PHASE_NAMES` tuple (line 51); `plan_push_song` phases tuple + the runtime drift-guard `if tuple(...) != _PHASE_NAMES`; docstring says "ten phases" / "Returns 10 phases" (×3) | Insert `"scenes"` before `"clips"` in `_PHASE_NAMES` + the phases tuple (with a `PushPhase(name="scenes", plan_fn=..., description=...)`); update docstrings to "eleven phases". The drift-guard then enforces parity automatically. |
| `src/hallucinote/sync/push/plan.py` `_ACK_ONLY_KINDS` | every planner key kind must be declared here or `apply_push_results` raises | Add `"scene"` to `_ACK_ONLY_KINDS` (the `ensure_count` call carries no DB binding to record — there's no per-scene DB row to link). |
| `tests/unit/sync/test_push_song.py` | `test_plan_push_song_returns_ten_phases` (==10); `test_plan_push_song_phase_names_and_order` (explicit list); `test_end_to_end_drive_links_every_entity` (per-phase emit counts, docstring "all ten phases") | Update to 11, insert `"scenes"` before `"clips"` in the name list, add the `scenes` emit-count assertion. **These are contracts — they change because the contract changed (a new required phase), not to make code pass.** |
| `tests/unit/sync/test_push_execute.py` | `test_execute_happy_path_writes_state_no_errors_file` names list ("The ten phases are present") | Insert `"scenes"` before `"clips"`. |
| `src/hallucinote/sync/push_notes.py` (docstring line 11) | prose "all ten phases" | → "all eleven phases". |
| `skills/ableton-push/SKILL.md` — count words | `description:` frontmatter, body "ten ordered phases" (lines 2, 9, 33, 100) | Update every count word "ten"→"eleven". Agent-facing — read every session, so highest drift impact. |
| `skills/ableton-push/SKILL.md` — **inline arrow sequence** | line 2 `description:` contains the literal ordered list `tempo → meter → tracks → returns → clips → mix → devices → envelopes → arrangement → cues` (ten entries, in phase order, **no count word**) plus any body repetition of that arrow list | Insert `scenes` into the arrow sequence **between `returns` and `clips`**, wherever the sequence appears → `… → returns → scenes → clips → …`. This is a SEPARATE pin from the count words: the Done-when-4 count-word grep (`'ten phases\|10 phases\|Returns 10'`) CANNOT catch a stale arrow list because the arrow list contains no count word. A second grep is mandatory (see Done-when 4). This is exactly the self-contradicting-doc failure the "Pattern sweeps are tree-wide or they don't count" learning warns about — count word says "eleven", arrow still lists 10, missing `scenes`. |
| `skills/ableton-push/SKILL.md` — tool-mapping table | phase-by-phase tool-mapping table (lines ~144-150) | Add a `scenes` row mapping to `ableton_scene(action='ensure_count')`, positioned before the `clips` row. |
| `hallucinote_mcp` action help / dispatcher | `ableton_scene` action menu (`action='help'`) | Auto-derived from the registered `Action`; registering `ensure_count` makes it appear. No manual prose to sync, but confirm via the dispatcher test. |

`src/hallucinote/sync/push_execute.py` `format_summary` already uses
`len(result.phases)` dynamically — it needs **no** edit (it will print "all 11
phases" automatically). That dynamic phrasing is the correct pattern; do not
regress it to a hardcoded number.

`docs/archive/**` runbooks mention "10 phases" historically — these are dated
archaeology of past runs (`docs/archive/canary-songs/*`, `pre-v1-walkthrough.md`)
and are intentionally NOT updated (they record what happened on a given date).
Note them in the chunk's grep audit as category (b) "intentional historical
reference," per the tree-wide-sweep learning's step 2.

### DR-4 — `scenes` planner phase shape

New planner `plan_push_scenes(conn, *, song_id, session_id)` in
`src/hallucinote/sync/push/` (new module `scenes.py`, mirroring the one-concern
-per-module layout: `clips.py`, `tracks.py`, etc.). Wired into `plan.py`'s phase
tuple before `clips`.

```
plan = PushPlan()
rows = Q.get_clips_for_song(conn, song_id)        # each row has `slot` (1-based)
max_slot = max((r["slot"] for r in rows), default=0)
if max_slot <= 0:
    plan.warn("no session clips; no scenes to provision")
    return plan                                    # warn (not bare-empty) → phase SKIPPED but progress-reported
plan.add(ToolCall(
    tool="ableton_scene",
    args={"action": "ensure_count", "count": max_slot},
    key="scene:ensure",                            # ack-only key kind "scene"
    purpose=f"ensure >= {max_slot} scenes exist before creating section clips",
))
```

- **Why `max slot`, not section count:** the clips planner places clips at
  `clip["slot"]` (clips.py:76), and `slot` traces to section index + 1
  (`arrangement.py:368`). `max slot` over the song's actual session clips is the
  exact upper bound the `clips` phase will address — deriving from clip rows (not
  re-deriving from sections) keeps `scenes` and `clips` reading the same source,
  so they cannot disagree (the "link, don't summarize" / single-source discipline).
- **Empty-plan path (warn, NOT bare-empty):** a song with no session clips emits
  no `ToolCall` but DOES emit `plan.warn("no session clips; no scenes to
  provision")` — matching the documented per-phase convention. `plan_push_song`'s
  docstring (`plan.py:119-125`) states every phase must "produce a plan with a
  `no … to push` warn instead of an empty plan, so the skill's progress reporting
  can distinguish 'ran cleanly with nothing to do' from 'phase skipped'", and the
  sibling `plan_push_clips` (`clips.py:134`) follows it with `plan.warn("no clips
  for this song; nothing to push")`. A warn adds no *call*, so `execute_push`'s
  `if not plan.calls` branch still reports the phase `SKIPPED (idempotent)` — the
  verifiable signal is unaffected — but `scenes` must NOT be the lone phase that
  silently bare-empties (that would contradict the docstring it lives beside).
- **Key kind `scene` is ack-only:** there is no per-scene DB row to link (scenes
  are a Live-set structural property, not a Hallucinote entity), so `"scene"`
  goes in `_ACK_ONLY_KINDS`, NOT `_LINK_KINDS`. `apply_push_results` already
  raises on undeclared kinds — adding it is mandatory or the phase's own result
  blows up at apply time.
- **Single canonical call, no alias:** `ableton_scene(action='ensure_count')` is
  a directly-callable tool with no `ALIASES_TODAY` entry. Per the "Sync planner
  discipline" learning, the planner's emitted args (`count: int`) must match the
  real MCP signature — verify-api covers this, and add a one-line signature note
  in `mcp_names.py` if the directly-callable-tool convention calls for it.

---

## Proposed canonical-doc deltas (NOT applied here — recorded for Critic-gated edit later)

This bug touches **no** canonical model doc (arrangement-model.md /
melody-model.md / performance-model.md) — scene provisioning is sync mechanics,
not a musical model. The only "canonical" surface is the **push phase contract**,
which lives in code (`_PHASE_NAMES`) and its agent-facing mirror
(`skills/ableton-push/SKILL.md`), both edited under the build plan (DR-3), not as
a separate canonical-doc pass.

If a sync-architecture doc exists that enumerates the phases (none found under
`docs/` outside dated archive runbooks), its proposed delta would be:

> **Delta (phase list):** insert `scenes` as phase 5, before `clips`:
> "5. `scenes` — `plan_push_scenes`. Ensures the Live set has at least `max
> session-clip slot` scenes (= clip slots per track) before `clips` creates
> section clips. Emits one idempotent `ableton_scene(action='ensure_count')`
> call; deficit math runs Live-side. No link deps. Prerequisite for `clips`."
> Renumber `clips`…`cues` to 6…11; total "eleven phases".

If no such doc is found during the build (grep `docs/` for a non-archive phase
enumeration), record "no canonical sync doc to update" in the chunk and rely on
the code + SKILL.md as the contract surface.

---

## Verification strategy (Live UP but UNATTENDED)

The verifiable signal is **objective and render-free** — "push completes / fails
with one message," observable from `execute`'s exit code + `.last-push-state.json`
without any by-ear judgement. Two layers:

1. **Unit (no Live):** a regression test pushing a synthetic ≥9-section song
   against a fake `send_fn` whose `ableton_scene:ensure_count` returns ok and
   whose clip-create succeeds — asserting the `scenes` phase runs before `clips`,
   emits one `ensure_count` call with `count == max_slot`, and the push reaches
   `outcome == "ok"`. A companion test with a fake that simulates the OLD
   behavior (no scenes provisioned → clip-create raises IndexError on slot 9)
   confirms the test would have FAILED pre-fix (the "pin what now passes" leg of
   the tree-wide-sweep discipline).
2. **Live integration (objective, unattended-safe):** push a synthetic
   9-section song into a fresh/default 8-scene set via the real MCP path and read
   the exit code + state file. PASS = exit 0 / `outcome: ok` and
   `len(song.scenes) >= 9` after. This is fully objective — no ear needed.

**No by-ear / render-gated decision exists in this item.** Scene count is a
deterministic integer derived from the song; there is no "amount to tune" and no
audio to listen to. (Flagged explicitly because the constraint requires it:
`byEarCalls = []`.)
