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

## PR plan — granular execution

### Repo conventions observed

From inspecting `uisato/ableton-mcp-extended` at the merge-base for these PRs:

- **Tests**: `tests/unit/test_<area>.py` using pytest, with mocked `mcp` framework. Pattern: `MagicMock` the `mcp.server.fastmcp` module, then import functions from `MCP_Server.server` and assert command construction. `tests/integration/` exists but is empty.
- **Commit messages**: mix of `feat: ...` for new features and plain descriptive titles ("Add X", "Standardize Y") for refactors/fixes. Use `feat:` for tool additions, plain for bug fixes.
- **Indexing**: 1-based across all MCP tools (per the recent "Standardize 1-based indexing" PR). New tools must follow this.
- **No CONTRIBUTING / CHANGELOG / .github** — no CI checks visible. Run tests locally before pushing.
- **Active maintainer**: recently merged PRs from `RobertTylman` and `Neftedollar` — community contributions are welcome.

### Per-PR template (use in PR descriptions)

```md
## What
<one-line description>

## Why
<problem this solves; link to issue if applicable>

## Changes
- file:line — short note
- ...

## Tests
- Added `tests/unit/test_<area>.py::Test<Name>` covering <cases>
- Manually verified via <song workflow / repro steps>

## Backwards compatibility
<none / additive only / breaking — see issue #N>
```

### Issues to file before any PR

Three architectural changes warrant a design discussion BEFORE code. File these as GitHub issues on `uisato/ableton-mcp-extended` and link them from the corresponding PR(s) when those open:

- **Issue A — Bulk arrangement operations** (covers req #5). Propose `batch_arrangement_layout` shape, transactional semantics, error reporting.
- **Issue B — Note-level addressing API** (covers req #4). Propose `get_clip_notes` / `update_notes` / `delete_notes` / `add_notes` signatures, note-ID stability story (Live's `notes_extended()` IDs persist across saves but reset on note re-creation — discuss).
- **Issue C — `add_notes_to_clip` rename** (covers req #1 part 2). The naming bug fix in PR 1 is non-breaking. Renaming the tool to `set_clip_notes` is breaking — propose deprecation period (v1: alias new→old, v2: alias old→new with warning, v3: remove old).

---

### Wave 1 — Bug fixes (build trust, no API change)

Diffs <50 lines each. Maintainer can review in a few minutes. Land these first.

#### PR 1 — Fix misleading `add_notes_to_clip` response message
- **Branch**: `mcp/fix-add-notes-response-message`
- **Title**: `Clarify add_notes_to_clip response: notes are replaced, not appended`
- **Why**: Response says `"Added N notes"` but the underlying call is `clip.set_notes(...)` which **replaces** all existing notes. Causes silent data loss for callers who expect append.
- **Files**: `AbletonMCP_Remote_Script/__init__.py` (response string in `_add_notes_to_clip`)
- **Change**: `"Added N notes to clip..."` → `"Set N notes on clip (replaced previous content)"`
- **Tests**: none required (string-only change). Optionally add a docstring noting replace semantics.
- **Acceptance**: maintainer sees the new wording matches the actual behavior.
- **Linked req**: #1 (response wording portion only — rename is Issue C / PR 13)
- **Depends on**: nothing
- **Estimated diff**: 3-5 lines

#### PR 2 — Fix `get_cue_points` returns numeric IDs instead of names
- **Branch**: `mcp/fix-get-cue-points-names`
- **Title**: `Fix get_cue_points showing numeric IDs instead of cue names`
- **Why**: `get_cue_points` returns `"1"`, `"2"`, etc. instead of the names that were set. Names persist correctly in Ableton's UI, so this is purely a serialization bug.
- **Files**: `AbletonMCP_Remote_Script/__init__.py` (the `_get_cue_points` formatter)
- **Change**: read `cue_point.name` (per Live's `CuePoint` API) instead of whatever produces the numeric id.
- **Tests**: `tests/unit/test_arrangement_commands.py::TestGetCuePoints` — mock cue point with name, assert response contains the name.
- **Acceptance**: round-trip — set names via `create_cue_point`, read back via `get_cue_points`, names match.
- **Linked req**: #13
- **Depends on**: nothing
- **Estimated diff**: 5-15 lines + test

#### PR 3 — Fix `create_cue_point` rejects names with apostrophes
- **Branch**: `mcp/fix-cue-point-apostrophe`
- **Title**: `Fix create_cue_point error on names containing apostrophes`
- **Why**: Names like `"C3'"` fail with misleading `"Cue point already exists at this position: 1"`. Likely a string-quoting issue in command construction; either escape properly or sanitize the message.
- **Files**: `MCP_Server/server.py` (caller) and possibly `AbletonMCP_Remote_Script/__init__.py` (handler) — diagnose first.
- **Change**: TBD pending diagnosis. Either properly escape the name in the JSON command payload, OR if Live's API genuinely rejects apostrophes, return a clear error (`"Invalid character in cue point name"`).
- **Tests**: `tests/unit/test_arrangement_commands.py::TestCreateCuePoint` — assert apostrophe names work OR produce the clear error.
- **Acceptance**: `create_cue_point(bar=83, name="C3'")` either succeeds OR returns clear error.
- **Linked req**: #12
- **Depends on**: nothing
- **Estimated diff**: 10-20 lines + test

---

### Wave 2 — Expose existing remote-script capabilities

The remote script already implements these; just need MCP-side exposure. Highest value-per-line-of-code in the entire plan.

#### PR 4 — Expose `add_notes_to_arrangement_clip` as MCP tool
- **Branch**: `mcp/expose-add-notes-to-arrangement-clip`
- **Title**: `feat: expose add_notes_to_arrangement_clip MCP tool`
- **Why**: Underlying remote script registers this command (line ~240 of `AbletonMCP_Remote_Script/__init__.py`) but no MCP tool surfaces it. Without this, every session-clip note change requires deleting all arrangement copies and re-duplicating — for a 50-clip arrangement that's 100 round-trips instead of 13.
- **Files**: `MCP_Server/server.py` (add `@mcp.tool()` definition that forwards to the remote script command)
- **Change**: Mirror the signature of `add_notes_to_clip` but address arrangement clips by `(track_index, arrangement_clip_index)`.
- **Tests**: `tests/unit/test_arrangement_commands.py::TestAddNotesToArrangementClip` — assert command construction (mock the socket layer).
- **Acceptance**: round-trip — set notes on an arrangement clip, verify in Ableton via UI inspection.
- **Linked req**: #3
- **Depends on**: nothing
- **Estimated diff**: 30-50 lines + test
- **Note**: response message should follow PR 1's pattern: `"Set N notes on arrangement clip (replaced previous content)"`.

---

### Wave 3 — Improve return values from existing tools

Small additive changes. Each is a separate PR for atomic review.

#### PR 5 — `duplicate_clip_to_arrangement` returns new clip identity
- **Branch**: `mcp/duplicate-arrangement-return-identity`
- **Title**: `feat: duplicate_clip_to_arrangement returns new arrangement clip identity`
- **Why**: Currently returns just `"Duplicated session clip to arrangement on track N"`. Caller can't track which arrangement clip resulted without a follow-up `get_arrangement_info` call. For a 49-clip rebuild, that's 49 wasted round-trips.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: Return `{track_index, arrangement_clip_index, name, start_bar, end_bar}` after the duplication. Backwards-compatible additive — existing callers ignore extra fields.
- **Tests**: `tests/unit/test_arrangement_commands.py::TestDuplicateClipToArrangement` — assert returned shape.
- **Acceptance**: caller can chain operations referencing the new clip without a separate query.
- **Linked req**: #6
- **Depends on**: nothing
- **Estimated diff**: 20-30 lines + test

#### PR 6 — `load_instrument_or_effect` returns loaded device info
- **Branch**: `mcp/load-instrument-return-device-info`
- **Title**: `feat: load_instrument_or_effect returns loaded device info`
- **Why**: Currently returns `"Loaded instrument with URI '...'. Devices on track:"` with empty trailing list. Caller can't programmatically confirm what loaded.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: Return `{loaded: bool, device_name, device_class, parameter_count}`. Read these from `track.devices[-1]` after the load.
- **Tests**: `tests/unit/test_device_commands.py::TestLoadInstrumentReturnInfo` — mock device, assert response shape.
- **Acceptance**: caller can verify the right device loaded without UI inspection.
- **Linked req**: #10
- **Depends on**: nothing
- **Estimated diff**: 20-30 lines + test

---

### Wave 4 — New small tools (atomic, composable, backwards-compat)

Each adds a new MCP tool without modifying existing ones. Land in this order — later PRs may compose earlier ones.

#### PR 7 — Add `delete_session_clip` tool
- **Branch**: `mcp/add-delete-session-clip`
- **Title**: `feat: add delete_session_clip tool`
- **Why**: Currently no way to delete a session clip via MCP. Stale slots accumulate forever across iteration cycles. Live's API exposes `clip_slot.delete_clip()` but it isn't surfaced.
- **Files**: `MCP_Server/server.py` (new `@mcp.tool()`), `AbletonMCP_Remote_Script/__init__.py` (handler + register in command list)
- **Change**: New tool `delete_session_clip(track_index, clip_index)`. Wraps `clip_slot.delete_clip()`. Errors clearly if slot is empty.
- **Tests**: `tests/unit/test_track_commands.py::TestDeleteSessionClip` — assert command construction, empty-slot behavior.
- **Acceptance**: clip removed; subsequent `create_clip` on same slot succeeds without error.
- **Linked req**: #2 (foundational half)
- **Depends on**: nothing
- **Estimated diff**: 40-60 lines + tests

#### PR 8 — Add `replace_session_clip` convenience tool
- **Branch**: `mcp/add-replace-session-clip`
- **Title**: `feat: add replace_session_clip atomic delete-create-populate tool`
- **Why**: The most common iteration op (regenerate a clip's notes) currently requires 2-3 calls (delete, create, add notes). Single tool collapses to 1 round-trip and is atomic on Ableton's main thread.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: New tool `replace_session_clip(track_index, clip_index, length, notes=None, name=None)`. Internally does delete (if exists) → create → add_notes (if provided) → set_clip_name (if provided). All on Ableton main thread for atomicity.
- **Tests**: `tests/unit/test_track_commands.py::TestReplaceSessionClip` — assert atomic behavior, partial-failure handling, optional params.
- **Acceptance**: regenerating a clip is one round-trip instead of 2-3.
- **Linked req**: #2 (convenience half)
- **Depends on**: PR 7 (delete_session_clip)
- **Estimated diff**: 50-80 lines + tests

#### PR 9 — `create_midi_track` accepts name + instrument_uri
- **Branch**: `mcp/create-midi-track-with-name-instrument`
- **Title**: `feat: create_midi_track accepts optional name and instrument_uri`
- **Why**: Setting up a track currently requires 3 calls: `create_midi_track` → `set_track_name` → `load_instrument_or_effect`. For 8 tracks: 24 calls instead of 8. Adding optional params is fully backwards-compatible.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: Add optional `name` and `instrument_uri` parameters. When provided, set/load after creation in one main-thread atomic block.
- **Tests**: `tests/unit/test_track_commands.py::TestCreateMidiTrackWithOptionalParams` — assert each combination works (none / name only / instrument only / both).
- **Acceptance**: `create_midi_track(index=-1, name="Drums", instrument_uri="query:Drums#FileId_5438")` returns track fully set up.
- **Linked req**: #8
- **Depends on**: nothing
- **Estimated diff**: 40-60 lines + tests

#### PR 10 — `get_browser_tree` accepts `depth` parameter
- **Branch**: `mcp/get-browser-tree-recursive-depth`
- **Title**: `feat: get_browser_tree supports recursive depth parameter`
- **Why**: Currently returns only one level. Drilling into instrument categories requires 1 call per level. Recursive load saves N round-trips. Defaults to current behavior (depth=1).
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: Add `depth: int = 1, max 5` param. Recursively walk children up to depth.
- **Tests**: `tests/unit/test_browser_path_normalization.py::TestBrowserTreeDepth` — assert depths 1, 2, 3 return progressively more.
- **Acceptance**: `get_browser_tree(category_type="instruments", depth=3)` returns nested tree.
- **Linked req**: #7
- **Depends on**: nothing
- **Estimated diff**: 30-50 lines + tests

---

### Wave 5 — Issue-first (architectural, discuss design before code)

These three need maintainer alignment before implementation. File the issues, wait for ack, then code. **Do not open PRs until issues have at least an emoji-reaction or a "+1" from the maintainer.**

#### PR 11 — Bulk arrangement operations (after Issue A)
- **Issue A title**: `Proposal: batch_arrangement_layout for bulk arrangement ops`
- **Branch**: `mcp/batch-arrangement-layout`
- **Title**: `feat: add batch_arrangement_layout tool for bulk arrangement ops`
- **Why**: Rebuilding an arrangement currently takes 1 call per clip operation. For my song: 46 deletes + 49 duplications = 95 sequential round-trips. Batching collapses to ~2 calls.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: New tool `batch_arrangement_layout(operations: [{op: "duplicate"|"delete", track_index, clip_index?, source_slot?, destination_bar?}])`. Returns `[{op, success, error?, resulting_clip_index?}]` per op. Transactional within Ableton's main-thread queue.
- **Tests**: `tests/unit/test_arrangement_commands.py::TestBatchArrangementLayout` — assert per-op result shape, partial-failure handling.
- **Acceptance**: 95-call rebuild becomes 1-2 calls; per-op errors are reported, not silently swallowed.
- **Linked req**: #5
- **Depends on**: PR 5 (return identity from duplicate)
- **Estimated diff**: 80-150 lines + tests

#### PR 12 — Note-level addressing (after Issue B)
- **Issue B title**: `Proposal: note-level addressing API (get/update/delete/add by ID)`
- **Branch**: `mcp/note-level-addressing`
- **Title**: `feat: add note-level addressing for clips`
- **Why**: Currently the only note operation is "set all notes for clip." To change one note's velocity, must regenerate the entire array. Live's `clip.get_notes_extended()` returns notes with stable IDs — surface them and unlock surgical edits + DB sync.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: Four new tools:
  - `get_clip_notes(track_index, clip_index)` → `[{id, pitch, start_time, duration, velocity, mute}, ...]`
  - `update_notes(track_index, clip_index, [{id, ...changes}])`
  - `delete_notes(track_index, clip_index, [id, ...])`
  - `append_notes(track_index, clip_index, [{pitch, start_time, ...}])` — true append, returns IDs
- **Tests**: `tests/unit/test_track_commands.py::TestNoteLevelAddressing` — assert ID stability, partial updates, deletes by ID.
- **Acceptance**: `get` → mutate → `update` round-trip preserves untouched notes byte-for-byte.
- **Linked req**: #4
- **Depends on**: nothing (composable with PR 1's response semantics)
- **Estimated diff**: 150-250 lines + tests

#### PR 13 — Rename `add_notes_to_clip` to `set_clip_notes` (after Issue C)
- **Issue C title**: `Proposal: rename add_notes_to_clip → set_clip_notes (deprecation plan)`
- **Branch**: `mcp/rename-set-clip-notes`
- **Title**: `feat: rename add_notes_to_clip to set_clip_notes (with deprecation alias)`
- **Why**: Tool name implies append; behavior is replace. PR 1 fixed the response message but the name is still misleading.
- **Files**: `MCP_Server/server.py`
- **Change**: Add new `set_clip_notes` tool. Keep `add_notes_to_clip` as alias that emits a deprecation warning in its response. Schedule removal for vN+2.
- **Tests**: `tests/unit/test_track_commands.py::TestSetClipNotesAlias` — assert both names work; deprecated one warns.
- **Acceptance**: existing callers still work; new callers use unambiguous name.
- **Linked req**: #1 (rename portion)
- **Depends on**: PR 1 (response message), PR 12 ideally (so `append_notes` exists as the true append variant before the rename lands — gives users a real append option)
- **Estimated diff**: 30-50 lines + tests
- **Breaking**: yes (eventual; alias provides graceful path)

---

### Wave 6 — Bulk variants / composites

Build on patterns established in waves 4 + 5. Land after dependencies merge.

#### PR 14 — Add `create_session_clips` bulk variant
- **Branch**: `mcp/bulk-create-session-clips`
- **Title**: `feat: add create_session_clips for bulk session-clip authoring`
- **Why**: Each clip currently requires 3 calls (create + add_notes + set_name). For 30 clips: 90 calls. Bulk variant collapses to 1.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: New tool `create_session_clips(clips: [{track_index, clip_index, length, name?, notes?}])`. Atomic per-Ableton-main-thread per clip. Returns per-clip results.
- **Tests**: `tests/unit/test_track_commands.py::TestCreateSessionClipsBulk` — assert ordering, per-clip failure isolation.
- **Acceptance**: 30-clip authoring is 1 round-trip with per-clip result reporting.
- **Linked req**: #9
- **Depends on**: PR 8 (`replace_session_clip` pattern shows atomic create-and-populate)
- **Estimated diff**: 60-100 lines + tests

---

### Wave 7 — Lower priority / nice-to-haves

Ship when bandwidth allows. None block the songwright DB-architecture work.

#### PR 15 — Add `get_session_devices_snapshot`
- **Branch**: `mcp/get-session-devices-snapshot`
- **Title**: `feat: add get_session_devices_snapshot for bulk device parameter capture`
- **Why**: `get_device_parameters` works per-device. Sound-design iteration wants all-tracks-all-devices state in one call (for diff/snapshot/restore workflows).
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: New tool returning `[{track_index, device_index, device_name, parameters: [{name, value, min, max}]}]` for all loaded devices.
- **Tests**: `tests/unit/test_device_commands.py::TestSessionDevicesSnapshot`
- **Linked req**: #11
- **Depends on**: nothing
- **Estimated diff**: 50-80 lines + tests

#### PR 16 — Add undo/redo wrappers
- **Branch**: `mcp/undo-redo-wrappers`
- **Title**: `feat: expose Ableton undo/redo via MCP`
- **Why**: Destructive ops (delete clips, replace notes) are immediate; no recovery path. Live's native undo works but isn't surfaced.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: New tools `undo()` and `redo()` wrapping `app.undo()` / `app.redo()`. Optionally `create_undo_checkpoint(name)` if Live's API supports named checkpoints (it doesn't in stock — would need bookkeeping).
- **Tests**: `tests/unit/test_arrangement_commands.py::TestUndoRedo`
- **Linked req**: #14
- **Depends on**: nothing
- **Estimated diff**: 20-40 lines + tests

#### PR 17 — Document clip slot capacity behavior
- **Branch**: `mcp/docs-clip-slot-capacity`
- **Title**: `docs: clarify session clip slot capacity and scene auto-creation`
- **Why**: Default sessions appear capped at 8 clip slots per track. Unclear if `create_clip` at slot 9+ adds scenes automatically or errors. Document the actual behavior.
- **Files**: `README.md` (new section under Tools docs)
- **Change**: Add section explaining slot/scene relationship, what `create_clip` does at out-of-range slots, recommended pattern for adding scenes.
- **Tests**: none (docs)
- **Linked req**: #15
- **Depends on**: nothing
- **Estimated diff**: 20-40 lines docs

---

### Summary — ship order

| # | PR | Wave | Depends on | Diff size |
|---|----|----|------------|-----------|
| 1 | Fix add_notes_to_clip response message | 1 | — | XS |
| 2 | Fix get_cue_points returns names | 1 | — | S |
| 3 | Fix create_cue_point apostrophe | 1 | — | S |
| 4 | Expose add_notes_to_arrangement_clip | 2 | — | M |
| 5 | duplicate_clip_to_arrangement returns identity | 3 | — | S |
| 6 | load_instrument_or_effect returns device info | 3 | — | S |
| 7 | delete_session_clip | 4 | — | M |
| 8 | replace_session_clip | 4 | PR 7 | M |
| 9 | create_midi_track with name + instrument | 4 | — | M |
| 10 | get_browser_tree depth | 4 | — | M |
| **A** | **Issue: bulk arrangement ops** | — | — | — |
| **B** | **Issue: note-level addressing** | — | — | — |
| **C** | **Issue: rename add_notes_to_clip** | — | PR 1 | — |
| 11 | batch_arrangement_layout | 5 | Issue A, PR 5 | L |
| 12 | note-level addressing (4 tools) | 5 | Issue B | L |
| 13 | rename to set_clip_notes (alias) | 5 | Issue C, PR 1, PR 12 | M |
| 14 | create_session_clips bulk | 6 | PR 8 | M |
| 15 | get_session_devices_snapshot | 7 | — | M |
| 16 | undo/redo wrappers | 7 | — | S |
| 17 | docs: clip slot capacity | 7 | — | S |

**XS** ≤ 10 lines · **S** 10-50 · **M** 50-150 · **L** 150-300

### Cadence suggestion

- **Week 1**: PRs 1, 2, 3 (bug fixes; build trust). File Issues A, B, C in parallel.
- **Week 2**: PRs 4, 5, 6 (high-value low-risk additions).
- **Week 3-4**: PRs 7, 8, 9, 10 (new tools, paced for review).
- **Week 5+**: PR 11, 12, 13 once issues are blessed.
- **Backlog**: PR 14, 15, 16, 17 as bandwidth allows.

If maintainer goes silent on Issues A/B/C, fall back: keep shipping waves 1-4. The DB-direction work in songwright can proceed using the current API (just slowly) until those land.
