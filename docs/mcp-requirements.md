# MCP Server Update Requirements

Source: gaps observed during the `falling-walking` song build (D minor electronic, ~98 bars, 12 tracks, 30+ session clips, 49 arrangement clips). Each gap below is something that either blocked iteration, forced a workaround, or made round-trips 5-10× longer than necessary.

Items grouped by **what unblocks the most workflow per fix**, not by implementation difficulty.

---

## Priority 1 — Iteration blockers (fix first)

These force destructive workarounds or many-times-as-many round-trips.

### 1. Rename `add_notes_to_clip` to reflect that it *replaces*

**Current behavior:** `add_notes_to_clip` calls `clip.set_notes(tuple(live_notes))` internally, which **replaces** all notes in the clip. The response message says `"Added N notes to clip..."`.

**Problem:** Name + response message both lie. Agents call it expecting append behavior, get silent destruction of existing notes. I only avoided the trap by reading the remote script source.

**Required:**
- Rename to `set_clip_notes` (preferred) OR add a true `append_notes_to_clip` variant
- Response: `"Set N notes on clip (replaced previous content)"` so it's unambiguous
- If keeping the old name for backwards compat, change the response message at minimum

### 2. Expose `delete_session_clip` and `replace_session_clip`

**Current state:** Only `delete_arrangement_clip` exists. Session clip slots can be created and modified-via-replacement but never deleted. Stale slots accumulate forever across iteration cycles.

**Required:**
- `delete_session_clip(track_index, clip_index)` — wraps `clip_slot.delete_clip()`
- `replace_session_clip(track_index, clip_index, length, notes?)` — atomically deletes + creates + optionally populates. Single round-trip for the most common iteration op.

### 3. Expose `add_notes_to_arrangement_clip`

**Current state:** The remote script registers it (line ~240 of `AbletonMCP_Remote_Script/__init__.py`) but it's not in the MCP tool list.

**Problem:** Without this, any session-clip note change requires deleting all arrangement copies and re-duplicating. For my v2 pass: 13 session clip note replacements forced 46 arrangement deletes + 49 re-duplications = 95 extra round-trips. With this tool exposed, it'd be ~13 calls.

**Required:** Just expose the existing implementation as an MCP tool with the same signature shape as `add_notes_to_clip`. (And give it the right semantics — see #1.)

### 4. Note-level addressing

**Current state:** Notes have no IDs. The only operation is "set all notes for this clip." To change one note's velocity, you must regenerate the entire note array and replace.

**Required:**
- `get_clip_notes(track_index, clip_index) → [{id, pitch, start_time, duration, velocity}, ...]` — read notes back with stable IDs (Live's API exposes `clip.get_notes_extended()` which provides these)
- `update_notes(track_index, clip_index, [{id, ...changes}, ...])` — mutate by ID
- `delete_notes(track_index, clip_index, [id, ...])` — surgical removal
- `add_notes(...)` — true append variant returning new IDs

This unlocks everything: humanization passes, "raise verse ghosts by 5", surgical fixes, and (eventually) sync-from-Ableton.

### 5. Bulk arrangement operations

**Current state:** Each `duplicate_clip_to_arrangement` and `delete_arrangement_clip` is a separate MCP call. For my song, rebuilding the arrangement was 46 deletes + 49 duplications = 95 sequential calls.

**Required:**
- `batch_arrangement_layout(operations: [{op: "duplicate"|"delete", track_index, clip_index, destination_bar?}])` — submit a full arrangement build/teardown in one call
- Returns: `[{op, success, error?, resulting_clip_index?}]` per operation
- Should be transactional within Ableton's main-thread queue (already serialized) so partial failures are reportable but don't corrupt state

### 6. `duplicate_clip_to_arrangement` should return the new clip's identity

**Current state:** Returns just `"Duplicated session clip to arrangement on track N"` — no indication of which arrangement clip resulted.

**Required:** Return `{track_index, arrangement_clip_index, name, start_bar, end_bar}` so subsequent ops can target the new clip without a follow-up `get_arrangement_info` call.

---

## Priority 2 — Efficiency (10×+ round-trip wins)

### 7. Recursive browser tree

**Current state:** `get_browser_tree` returns only top-level entries. Each level requires a separate `get_browser_items_at_path` call.

**Required:** Add `depth` parameter (default 1, max 5) so a single call can return the full instrument/drum browser tree. For me, choosing the drum kit was 2 calls; choosing across multiple categories would be many more.

### 8. Track creation with name + instrument

**Current state:** `create_midi_track` doesn't accept name. To set up a named track with an instrument, you need 3 calls: `create_midi_track` → `set_track_name` → `load_instrument_or_effect`. For my 8 tracks: 24 calls instead of 8.

**Required:** `create_midi_track(name?, instrument_uri?, index?)` — single call.

### 9. Bulk session-clip create

**Current state:** Each clip creation is 3 calls: `create_clip` → `add_notes_to_clip` → `set_clip_name`. For 30 clips: 90 calls.

**Required:** `create_session_clips(clips: [{track_index, clip_index, length, name?, notes?}])` — accepts an array, returns per-clip results.

### 10. `load_instrument_or_effect` should return what loaded

**Current state:** Returns `"Loaded instrument with URI '...' on track N. Devices on track:"` — the trailing list is empty.

**Required:** Return `{loaded: true, device_name, device_class, parameters_count}` so the caller can confirm the right thing loaded without UI inspection.

### 11. Device parameter snapshot

**Current state:** `get_device_parameters` works per-device. No way to snapshot all loaded devices' parameters across all tracks in one call.

**Required:** `get_session_devices_snapshot()` returning `[{track_index, device_index, device_name, parameters: [{name, value, min, max}]}]`. Critical for sound-design iteration where you want to capture "current state" before tweaking, or diff before/after.

---

## Priority 3 — Polish / correctness

### 12. `create_cue_point` apostrophe handling

**Current state:** Names containing `'` (e.g., `"C3'"`) error with `"Cue point already exists at this position: 1"` — both wrong cause and wrong position. Worked when renamed to `"C3 prime"`.

**Required:** Either escape apostrophes properly OR return a clear error like `"Invalid character in cue point name: apostrophe not supported"`.

### 13. `get_cue_points` should return real names

**Current state:** Returns numeric IDs (`"1"`, `"2"`, ...) instead of the names that were set. Names persist correctly in Ableton's UI.

**Required:** Return the actual names. Looks like a serialization bug.

### 14. Undo / snapshot support

**Current state:** Destructive ops (delete clips, replace notes) are immediate. No "save state" before bulk changes. Live's native undo presumably still works but isn't exposed.

**Required:**
- `create_undo_checkpoint(name)` — wraps Live's undo system
- `undo_to_checkpoint(name)` — restores
- At minimum: expose `app.undo()` / `app.redo()` so agents can recover from bad calls

### 15. Confirm clip slot capacity behavior

**Current state:** Default sessions appear capped at 8 clip slots per track. Unclear if/how `create_clip` at slot 9+ adds scenes automatically or errors silently.

**Required:** Document the behavior. If it errors, expose `add_scenes(count)` so agents can extend capacity programmatically.

---

## Future direction — Database as MIDI source of truth

This came up in conversation while building falling-walking. Capturing it because it would change how iteration works at architectural scale.

### Motivation

The current workflow (Python script generates note arrays → MCP replaces clip contents → arrangement rebuilt) has friction points:
- Manual edits in Ableton are lost on regen unless ported back to Python
- Note-level changes require regenerating an entire clip's note array
- No structured way to share groove templates / voicing libraries across songs
- Per-note edit history is invisible (only `gen_notes.py` git history exists)

### Proposed shape

**Hybrid: DB stores materialized notes; small generator layer writes to DB; MCP queries/mutates DB.**

```
generators/  ──writes──>  notes table (DB)  <──reads/mutates──  MCP tools
                                  │
                                  ├──pushes──>  Ableton clips
                                  └<──pulls──   Ableton clips (sync-back)
```

**Schema sketch:**
- `songs(id, name, key, tempo, time_signature, ...)`
- `tracks(id, song_id, index, name, instrument_uri)`
- `clips(id, track_id, slot, length_beats, section_role, ...)` — section_role like 'verse', 'chorus_twist'
- `notes(id, clip_id, pitch, start_time, duration, velocity, tags[])` — tags like 'ghost', 'kick_stumble', 'tresillo_hit'
- `arrangement(id, song_id, track_id, clip_id, start_bar, end_bar)`

**Generators become reusable functions** — `generate_trip_hop_drums(bars=15, with_fill_at=14, ghost_intensity=0.5)` writes notes rows tagged appropriately, returns clip_id. Same generator can be called for any song.

**MCP tools become surgical:**
- `query_notes(clip_id, where: {tag: 'ghost'})` → returns matching notes
- `update_notes(where: {clip_id, tag: 'ghost'}, set: {velocity: velocity + 5})` → bulk velocity bump on all ghosts
- `sync_clip_to_ableton(clip_id)` → push DB → live
- `sync_clip_from_ableton(track_index, clip_index, → clip_id)` → pull live → DB (preserves manual edits)

### What this depends on

The DB approach gets dramatically better once the Priority 1 MCP gaps are fixed:
- **#1 set_clip_notes** — reliable round-trip
- **#3 arrangement clip note updates** — DB-to-arrangement sync without rebuild
- **#4 note-level addressing** — surgical sync without full clip rewrites
- **#5 bulk operations** — push 1000 notes across 30 clips in one call

Without those, the DB just shifts the friction location: instead of regenerating Python and pushing JSON, you'd update DB rows and push JSON. Round-trip cost is the same.

**Verdict:** worth doing eventually for multi-song / shared-groove workflows. Do P1 MCP fixes first to make the DB layer pleasant rather than incremental.

### Out-of-scope but worth flagging

- **Per-note authoring UI** — once notes have IDs in a DB, a piano-roll-like web UI becomes viable. Not MCP-related but the architecture enables it.
- **Live-edit ingestion** — if Ableton emits MIDI change events (it can via control surfaces), the DB could subscribe and stay in sync without explicit pull.
- **Cross-song templates** — "load the Ahlimba kit + my standard sidechain bus + a verse-style trip-hop drum pattern in F# minor" becomes one tool call.

---

## Summary

If only 4 things ship, ship these in this order:

1. **#1** rename / fix response of `add_notes_to_clip` (5 minutes, prevents data loss)
2. **#3** expose `add_notes_to_arrangement_clip` (already implemented in remote script)
3. **#5** bulk arrangement operations (10× round-trip win on every rebuild)
4. **#4** note-level addressing (unlocks DB future + surgical edits)

Everything else is multiplicative on these foundations.
