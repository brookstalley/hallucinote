# PSH-6W2J — Note edits never reach arrangement clips

**Type:** bugfix (silent correctness) · **Size:** medium · **Base:** `develop`
**Branch:** `fix/psh-6w2j-note-edits-stale-arrangement-clips`
**Report:** `incoming-bugs/2026-06-15-note-changes-never-reach-arrangement-clips.md`

## Confidence check

1. **Problem.** A session clip's notes are pushed (DB + Live session clip updated,
   push reports success), but the **arrangement** clip — a distinct Live copy made
   once by `duplicate_to_arrangement` — keeps the old notes. Render/playback/`/mix-review`
   all read the stale arrangement. Silent: every signal says "success".
2. **Success.** After editing a clip's notes and re-pushing (scoped `push-notes` OR
   full `execute`), the linked arrangement clip(s) reflect the new notes; a regression
   test proves propagation through both paths. No re-duplication (placement stays
   idempotent — no doubled clips).
3. **Out of scope.** Audio-clip arrangement sync (CLP-AUD2). Arrangement *position*
   /length edits (only note content). A general content-aware re-materialize of
   placements. Automation/clip-property propagation to arrangement copies.

## Root cause (verified against code)

- `sync/push/arrangement.py::plan_push_arrangement` is idempotent on the **existence**
  of the `arrangement_clip` link (`arr_at is not None → continue`, lines 81–87). It
  never compares note content, so a re-push of changed notes emits **zero** arrangement
  ops for already-placed clips.
- `sync/push_notes.py::push_notes` plans via `plan_push_clip` → `replace_notes` on the
  **session** clip only (resolved via the `clip` link). Never touches arrangement copies.
- Net: note edits land in the session clip + DB; the arrangement copy the render/transport
  plays is frozen at first-materialization.

**Key enabler:** the MCP `replace_notes_handler` already accepts `location='arrangement'`
with `clip_index = arrangement_clip_index` (`handlers/clip.py:809`), and `get_ableton_link`
returns that index for `db_kind='arrangement_clip'`. So we can refresh an arrangement
clip's notes in place — no delete + re-duplicate needed.

## Approach — fix direction (1) from the report: propagate, don't re-duplicate

Already-linked arrangement placements emit a `replace_notes(location='arrangement')`
refresh (idempotent on **placement** — no doubling — but notes stay in sync). This
single mechanism fixes both push paths.

### Chunk A — shared refresh planner + full-push path
- **queries.py**: add `get_arrangement_for_clip(conn, clip_id)` (rows for one session
  clip, joined with `c.kind AS clip_kind`).
- **push/arrangement.py**:
  - `_arrangement_note_refresh_call(conn, *, row, session_id) -> ToolCall | None` —
    builds the `replace_notes(location='arrangement', track_index, clip_index=arr_index,
    notes)` call; returns `None` if track/arr link missing or source clip is audio.
    Key `arrangement_clip_notes:{row_id}`.
  - `plan_push_arrangement_clip_notes(conn, *, clip_id, session_id) -> PushPlan` —
    public per-clip planner (one refresh call per linked placement of the clip).
  - `plan_push_arrangement`: in the already-linked branch, emit the refresh call
    instead of pure skip. Track `new_placements` separately so the "agent must clear
    existing arrangement clips" warn fires only for genuine new duplicates, not refreshes.
    Reword the idempotency note ("notes refreshed, no re-duplication").
- **push/plan.py**: register `arrangement_clip_notes` in `_ACK_ONLY_KINDS` (no binding —
  the placement is already linked).
- **push/__init__.py**: export `plan_push_arrangement_clip_notes`.

### Chunk B — scoped-push path (`push_notes`)
- After a session clip is successfully pushed, extend the dispatch with
  `plan_push_arrangement_clip_notes(conn, clip_id=cid, ...)` calls so the scoped
  compose loop propagates too. Rides the existing per-clip `changed_only` fingerprint
  (unchanged session clip → arrangement copy needs no refresh either).

## Tests
- **Contract correction** (`test_push.py`): the existing
  `test_plan_push_arrangement_skips_already_linked_placements` asserts `plan.calls == []`
  — this **encodes the bug**. Rewrite to assert an already-linked placement emits exactly
  one `replace_notes`/`location=arrangement` refresh (NOT `duplicate_to_arrangement`),
  key `arrangement_clip_notes:`, plus the idempotency note. Update
  `…partial_state_emits_unlinked_only` for the linked-rows-now-refresh count. The
  clear-warn tests stay green (warn keyed on new duplicates only).
- New: refresh skips unlinked placements + audio sources; `plan_push_arrangement_clip_notes`
  emits one call per linked placement; multi-placement clip refreshes all copies.
- `test_push_notes.py`: a changed clip with a linked arrangement copy dispatches the
  arrangement refresh; unchanged clip (changed_only) dispatches neither.
- `test_push_execute.py` (if it has an arrangement-phase assertion): full re-push of
  changed notes now refreshes arrangement copies.

## Done when
- Both push paths propagate note edits to arrangement copies; no placement doubling.
- Contract-correction documented in the test docstring + change-log (W10-A idempotent-skip
  was too aggressive — suppressed propagation).
- Full suite green; `/prawduct:critic` clean.
- Note the heal path for pre-existing stale arrangements: one full `execute` push now
  refreshes all arrangement-copy notes unconditionally.
