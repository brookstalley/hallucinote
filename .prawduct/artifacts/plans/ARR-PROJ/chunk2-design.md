# ARR-PROJ Chunk 2 — sync-planner rebuild path: design decisions

Captured 2026-06-22 before implementation, from the Chunk-1 findings (design §6c)
and an end-to-end contract trace of the push pipeline. Tier-2 design note for the
keystone chunk. Parent: `.prawduct/artifacts/arrangement-materialization-redesign.md`.

## The contract as it exists (trace findings)

- `plan_push_arrangement(conn, *, song_id, session_id)` is a pure DB→`PushPlan`
  function (`sync/push/arrangement.py:89`). The executor calls the phase thunk with
  zero inputs (`push_execute.py:1129`); **the execute path never probes Live's
  arrangement state.** That probe (`_probe_live_arrangement_clips_via_mcp`,
  `push_cli.py:223`) lives only in `probe-and-link --probe`.
- ToolCalls dispatch in exact `plan.add()` order (`_core.py:74`, `push_execute.py:899`),
  serially. So *deletes-then-creates*, deletes descending, creates ascending = add them
  in that order.
- Arrangement `delete` wire EXISTS (`handlers/clip.py:455`): `delete(location=
  'arrangement', track_index, clip_index)` → `track.delete_clip(clip)`; result has
  **no index field**; subsequent indices renumber down.
- `apply_push_results` (`plan.py:386`) raises on an unknown key prefix (`plan.py:519`).
  `arrangement_clip:{id}` records the link (`plan.py:283,495`); `_ACK_ONLY_KINDS`
  (`plan.py:303`) keys record no binding.
- The CUES phase reads the DB **extent** (`max(end_bar)`), NOT the arrangement_clip
  link (`arrangement.py:332`). Nothing else reads the link except the planner's own
  idempotency check (deleted here) and the probe reconcile (deleted in Chunk 4).
- Coherence check inspects only track/return links (`probe.py:1118`) — never
  arrangement; a clear+create plan passes it untouched.

## Decisions (load-bearing)

**D1 — Planner takes probed Live state as a pure data param.**
`plan_push_arrangement(conn, *, song_id, session_id, live_arrangement_clips_by_track=None)`.
Shape = `_probe_live_arrangement_clips_via_mcp`'s return: `dict[track_index, list[{
arrangement_clip_index, name, start_beats, length}]]`. Pure data → unit-testable by
passing a dict (no Live). The executor probes and passes it (D7).

**D2 — Clear is planner-emitted, descending index, ack-only key.**
Per involved track, for each probed live clip in **descending `arrangement_clip_index`**,
emit `ableton_clip(action='delete', location='arrangement', track_index, clip_index)`
keyed `arrangement_clip_clear:{track_index}:{arrangement_clip_index}`. Register the
`arrangement_clip_clear` prefix in `_ACK_ONLY_KINDS` (delete records no binding; result
has no index). Descending order is valid against the pre-clear snapshot: deleting a
higher index never shifts a lower one.

**D3 — Create+fill for note-only placements (the common path).**
Per placement (ascending `start_bar`): `ableton_clip(action='create', location=
'arrangement', kind='midi', start_beats=_position_bar_to_beats(start_bar),
length=clip.length_beats, name=clip_name, notes=_notes_for_mcp(...))`, keyed
`arrangement_clip:{db_id}` (apply still records the link — harmless continuity; Chunk 4
may drop). Full clip spec from DB = **notes + name**. (No clip `color` column exists in
the `clips` schema; clip envelopes are the duplicate route, D4 — so "full spec" for a
note-only clip is notes+name.) NEVER `replace_notes`-in-place (§6b-A): create makes a
FRESH clip, set_notes fills it → no orphans by construction.

**D4 — Envelope-bearing placements route to duplicate-onto-cleared.**
Detection (pure DB) — **as IMPLEMENTED in `envelope_hosting_clip_ids` (envelopes.py),
which corrected this section's first draft.** A first idea was "`get_envelopes_for_clip(
clip_id)` non-empty" — that is WRONG and was NOT shipped: the DB CHECK forbids
`target_clip_id` on `mixer_*`/`send_level`/`device_parameter` envelopes (they're
track/device/return-scoped), yet the `envelopes` phase still RIDES those on a covering
SESSION clip (W4-A snapshot-copy), so `get_envelopes_for_clip` would miss exactly the
clips that need the duplicate route. The shipped detection instead reuses the
authoritative `classify_envelope_route`: a clip hosts an envelope iff some envelope routes
`session_clip` and `_resolve_envelope_session_clip` lands on it, OR a `clip_scoped`
`note_expression` rides its note's clip (`clip_cc`/`clip_pitch_bend` are LOM-skipped today
but included defensively). Envelope-bearing → `duplicate_to_arrangement` (needs the clip
linked in a session slot); lands on the cleared region → no B-24. Confirmed live on alien:
exactly one host (Alien Voice `send_level`), which a `get_envelopes_for_clip` check would
have MISSED — proving the correction. Covered by `test_push_envelopes` host-detection tests
+ a planner routing test; alien is the live operator-verify witness.

**D5 — Audio placements: existing skip-and-warn (CLP-AUD2 scope).** Unchanged route.

**D6 — Per-track all-or-nothing (the §6a safety invariant).** The clear is destructive,
so only emit a track's clear+rebuild if the WHOLE track is materializable: resolve the
track link and every placement's clip link FIRST; if any required dep is unresolved,
emit NOTHING for that track (no clear, no partial rebuild) + a warn. Never clear a track
we cannot fully rebuild. (Apply-time failures are still possible → fail-loud is Chunk 3's
integrity assert + the executor's existing halt; the planner guarantees it never *plans*
a half-materialization.)

**D7 — Executor probes arrangement + threads the param.** Add an arrangement-clip probe
to the execute path (reuse `_probe_live_arrangement_clips_via_mcp`) and thread
`live_arrangement_clips_by_track` through `plan_push_song` → the arrangement phase thunk
→ `plan_push_arrangement`. Probe only the tracks the DB materializes. When the param is
`None` (a caller that didn't probe), emit create+fill with NO clear + a loud warn that
the timeline must be empty — this is the only non-projection fallback, retained solely so
non-execute callers/tests don't silently mis-clear. The execute path always probes.

**D8 — Idempotency machinery deleted.** Remove `already_linked`/`refreshed`/the
`_arrangement_note_refresh_call` use inside `plan_push_arrangement` and the "agent must
clear" warn (the planner now clears). Always clear+rebuild = idempotent by construction.

## Explicitly OUT of Chunk 2 (flagged, not dropped)

- `plan_push_arrangement_clip_notes` (the scoped compose-loop propagation,
  `arrangement.py:66`, called by `push_notes.py:227`) still uses `replace_notes`-in-place,
  which §6b-A shows leaves orphans. It is a SEPARATE scoped path (the fast
  `push-notes --changed` compose iteration), not the full arrangement phase. Its real fix
  is the **`replace_notes` handler** becoming a true total-replace (full-extent clear
  before set_notes) — a HANDLER change that **flips the MCP fingerprint** (re-vendor +
  operator-verify), so it stays separate per §6b-A ("filed separately, related to
  ARR-PROJ"). Chunk 2 does NOT touch it and does NOT use `replace_notes` anywhere in the
  new `plan_push_arrangement`. **Action:** file/confirm the backlog item for the
  replace_notes-handler atomicity fix so the orphan path isn't silently left.

## Test plan (headless; planner returns a PushPlan)

Rewrite the old-model tests (skip-if-linked / refresh-in-place / must-clear warn) to the
new contract — intentional behavior replacement, named in the change-log, NOT weakening:
- fresh materialize (empty `live_arrangement_clips_by_track`) → only create+fill calls,
  ascending start, keyed `arrangement_clip:{id}`, notes+name present.
- re-materialize onto an OCCUPIED timeline (probe dict has N clips) → emits N descending
  deletes THEN the creates (the stacking witness ARR-9X4T cannot be produced).
- note-only vs envelope-bearing vs audio routing (3 cases) — correct call per route.
- per-track all-or-nothing: a track with one unresolved clip link emits NO clear and NO
  create for that track (no half-materialize) + warn; a sibling fully-resolved track is
  unaffected.
- `None` param → create+fill + no-clear + the loud warn.
- apply round-trip: the `arrangement_clip_clear` ack-only key does not raise in
  `apply_push_results` and records no binding.
