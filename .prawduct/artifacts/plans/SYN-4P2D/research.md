# SYN-4P2D — Research

n/a — deterministic bug, no external research question. Effort spent on reading
the push/clips/scene handler code to pick the fix option (see below).

## Root cause (confirmed from code)

`hallucinote_mcp/handlers/clip.py:289-293` raises
`IndexError: clip_index {N} out of range [1, {len(slots)}]` when the session
clip planner asks to create a clip in a slot beyond the track's clip-slot
count. A track's `clip_slots` length **equals the session scene count** (every
scene adds one clip slot per track). A default Live set ships 8 scenes →
`len(slots) == 8`.

The clip planner (`src/hallucinote/sync/push/clips.py:80`,
`plan_push_clip`) emits `"clip_index": clip["slot"]` with no awareness of how
many scenes exist Live-side. `clip["slot"]` traces to
`src/hallucinote/arrangement.py:368` (`slot = idx + 1`, section index + 1), so a
9-section song needs slot 9. During `execute_push`
(`push_execute.py`), the `clips` phase runs N create calls; each section-9 clip
on each affected track fails with its own IndexError, the phase reports
`calls_failed > 0`, halts (phase 5/10 = "clips"), and the remaining phases are
marked pending. That matches the live report (5 raw IndexErrors, halted at
clips). The push never provisions scenes — `grep` confirms **nothing under
`src/hallucinote/sync/` touches scenes today**.

## Fix-option decision (rationale)

The backlog lists three options; the structural fact that **the planner is pure
DB (no Live-side state)** is decisive:

- Option (a) "planner emits a `scenes` phase ensuring scene_count >= max slot":
  the planner knows the *required* max slot (DB) but NOT the *current* scene
  count (Live). It cannot compute `N - M`. It CAN emit an idempotent
  "ensure at least N scenes exist" call whose deficit math runs Live-side. This
  is viable only if paired with an idempotent MCP action.
- Option (b) "clips auto-creates a missing slot on demand": couples the clip
  create handler to scene lifecycle, scatters scene-creation across N per-clip
  calls (each create_scene re-wraps song.scenes — see the "Never use `is`"
  learning), and races on slot indices. Rejected — wrong layer, wrong
  granularity.
- Option (c) "pre-flight coherence check, fail fast with one message": strictly
  better than the status quo but still leaves the common new-song path broken
  (user must hand-run `ableton_scene(create)` then re-push). It's the *fallback*
  behavior, not the primary fix.

**Recommended: (a) implemented as a new idempotent
`ableton_scene(action='ensure_count', count=N)` MCP action + a `scenes`
planner phase before `clips`.** The action computes
`needed = count - len(song.scenes)` Live-side and appends that many scenes
(no-op when `needed <= 0`); the planner computes `N = max session-clip slot`
from `get_clips_for_song`. This delivers the strongest verifiable signal
("COMPLETES") and keeps the deficit math on the only side that can see the
current count. Option (c)'s actionable message becomes the natural error if
`ensure_count` itself fails (e.g., `create_scene` unavailable). This adds an
11th phase, which is a contract change pinned by `_PHASE_NAMES`
(`plan.py:51`), `test_push_song.py:93-114`, and `format_summary`'s "all N
phases" string — all must move together (see "Pattern sweeps are tree-wide"
learning). `ableton_scene(action='create')` already exists with the correct
append semantics (`handlers/scene.py:73-110`) — `ensure_count` reuses its
deterministic-index pattern, satisfying verify-api by reading that handler.
