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

### Strategy: fork-first, upstream PRs are courtesy

The upstream repo (`uisato/ableton-mcp-extended`) does not accept issues and may not engage with PRs. So:

- **Primary**: every change lands in our fork (`brookstalley/ableton-mcp-extended`). Songwright depends on the fork. Iteration moves at our pace, no review gating, no design-discussion blocker.
- **Secondary**: when a feature is stable + tested, cherry-pick onto a clean branch off `upstream/main` and offer it upstream. If the maintainer merges it, great — we delete our equivalent commits on the next sync. If they don't engage, we keep it in the fork forever.

Implications vs. the previous "build trust, file issues first" plan:

- **No issue-first gating** — file PRs at our discretion, expect no response
- **No deprecation aliases for renames** — we control all consumers (just songwright), so clean breaking changes are fine in our fork
- **Re-ordered priority**: ship what songwright needs first (note-level addressing, bulk arrangement ops, replace/delete), not what builds maintainer rapport
- **Smaller PR count**: drops from 17 to 15 — some splits were political (separating delete/replace, splitting message-fix from rename) and no longer needed
- **Cadence is "as fast as we want"**

### Branch strategy in fork

```
upstream/main                   # read-only — sync source from uisato's repo
origin/main                     # OUR canonical version — songwright runs from here, diverges from upstream
origin/feat/<short-name>        # feature branches off origin/main, merge back when done
origin/upstream/<feature-name>  # clean cherry-picks off upstream/main for upstream PR offerings
```

**Local development flow:**

```bash
# Start a feature
git checkout main && git pull
git checkout -b feat/note-level-addressing

# ...code, commit, test...

# Land in fork
git checkout main
git merge --no-ff feat/note-level-addressing
git push origin main
```

**Periodic upstream sync:**

```bash
git fetch upstream
git checkout main
git merge upstream/main   # or rebase if no conflicts; resolve song-side breakage as needed
git push origin main
```

**Offering a PR upstream:**

```bash
git fetch upstream
git checkout -b upstream/expose-add-notes-to-arrangement-clip upstream/main
git cherry-pick <commit-from-feat-branch>   # or multiple commits
git push origin upstream/expose-add-notes-to-arrangement-clip
gh pr create --base main --repo uisato/ableton-mcp-extended
```

The `upstream/<name>` branch convention makes PR-offering branches easy to spot and clean up later.

**Songwright's `.mcp.json` runs the MCP server from `~/source/ableton-mcp-extended/MCP_Server/server.py`** — i.e., whatever's checked out at `origin/main` at runtime. Make sure `main` is the working branch; do feature work in branches and merge before relying on it from songwright.

### Repo conventions to follow (for our own quality)

- **Tests**: `tests/unit/test_<area>.py` using pytest with mocked `mcp` framework. Pattern: `MagicMock` the `mcp.server.fastmcp` module, then import functions from `MCP_Server.server` and assert command construction. `tests/integration/` exists but is empty.
- **Commit messages**: `feat: ...` for new tools, plain descriptive titles for bug fixes (matches existing repo style).
- **Indexing**: 1-based across all MCP tools. New tools must follow.
- **No CI** — run `pytest tests/` locally before merging into `main`.

### Per-PR template (use when offering upstream)

```md
## What
<one-line description>

## Why
<problem this solves; concrete impact e.g. "reduces 95 round-trips to 2">

## Changes
- file:line — short note
- ...

## Tests
- Added `tests/unit/test_<area>.py::Test<Name>` covering <cases>
- Manually verified via <reproducible workflow>

## Backwards compatibility
<additive only / breaking>
```

---

### Wave 1 — Foundational (unblock songwright's DB direction)

These three give songwright everything it needs to move from "regenerate-and-replace whole clips" to "surgical, DB-backed authoring."

#### PR A — Note-level addressing (4 tools)
- **Branch**: `feat/note-level-addressing`
- **Title**: `feat: add note-level addressing for clips`
- **Why**: Currently the only note operation is "set all notes for clip." To change one note's velocity, the entire array must be regenerated. Live's `clip.get_notes_extended()` returns notes with stable IDs — surfacing them unlocks surgical edits, DB sync, and humanization passes without re-deriving.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: Four new tools:
  - `get_clip_notes(track_index, clip_index)` → `[{id, pitch, start_time, duration, velocity, mute}, ...]`
  - `update_notes(track_index, clip_index, [{id, ...changes}])`
  - `delete_notes(track_index, clip_index, [id, ...])`
  - `append_notes(track_index, clip_index, [{pitch, start_time, ...}])` — true append, returns assigned IDs
- **Tests**: `tests/unit/test_track_commands.py::TestNoteLevelAddressing` — assert ID stability across get/update round-trips, partial updates preserve untouched notes, deletes by ID work.
- **Acceptance**: `get` → mutate one velocity → `update` round-trip preserves all other notes byte-for-byte.
- **Linked req**: #4
- **Depends on**: nothing
- **Estimated diff**: 150-250 lines + tests
- **Upstream-likely?**: Low — large API addition. Offer anyway; keep regardless.

#### PR B — Bulk arrangement operations (`batch_arrangement_layout`)
- **Branch**: `feat/batch-arrangement-layout`
- **Title**: `feat: add batch_arrangement_layout tool for bulk arrangement ops`
- **Why**: Rebuilding an arrangement currently takes 1 call per clip operation. The falling-walking song was 46 deletes + 49 duplications = 95 sequential round-trips for ONE iteration cycle. Batching collapses to 1-2 calls.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: New tool `batch_arrangement_layout(operations: [{op: "duplicate"|"delete", track_index, clip_index?, source_slot?, destination_bar?}])`. Returns `[{op, success, error?, resulting_clip_index?}]` per op. Serialized through Ableton's main-thread queue (already thread-safe).
- **Tests**: `tests/unit/test_arrangement_commands.py::TestBatchArrangementLayout` — assert per-op result shape, partial-failure isolation.
- **Acceptance**: 95-call rebuild becomes 1 call; per-op errors reported, not swallowed.
- **Linked req**: #5
- **Depends on**: PR F (return identity from duplicate — needed for `resulting_clip_index`)
- **Estimated diff**: 80-150 lines + tests
- **Upstream-likely?**: Low — architectural addition. Offer; keep regardless.

#### PR C — Expose existing `add_notes_to_arrangement_clip`
- **Branch**: `feat/expose-add-notes-to-arrangement-clip`
- **Title**: `feat: expose add_notes_to_arrangement_clip MCP tool`
- **Why**: Underlying remote script already registers this command (line ~240 of `AbletonMCP_Remote_Script/__init__.py`) but no MCP tool surfaces it. Without it, every session-clip note change requires deleting all arrangement copies and re-duplicating — for a 50-clip arrangement that's 100 round-trips instead of 13.
- **Files**: `MCP_Server/server.py` (add `@mcp.tool()` definition)
- **Change**: Mirror the signature of the renamed `set_clip_notes` (PR H) but address arrangement clips by `(track_index, arrangement_clip_index)`. Response: `"Set N notes on arrangement clip (replaced previous content)"`.
- **Tests**: `tests/unit/test_arrangement_commands.py::TestAddNotesToArrangementClip` — assert command construction.
- **Acceptance**: round-trip — set notes on an arrangement clip, verify in Ableton.
- **Linked req**: #3
- **Depends on**: PR H ideally (consistent naming) but not blocking
- **Estimated diff**: 30-50 lines + test
- **Upstream-likely?**: High — minimal change to surface existing capability. Good upstream offering.

---

### Wave 2 — Workflow accelerators (every iteration faster)

#### PR D — `delete_session_clip` + `replace_session_clip`
- **Branch**: `feat/session-clip-delete-replace`
- **Title**: `feat: add delete_session_clip and replace_session_clip tools`
- **Why**: Currently no way to delete a session clip via MCP. Stale slots accumulate forever across iteration cycles. The most common iteration op (regenerate a clip's notes) requires 2-3 calls; an atomic replace collapses to 1.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: Two new tools:
  - `delete_session_clip(track_index, clip_index)` — wraps `clip_slot.delete_clip()`
  - `replace_session_clip(track_index, clip_index, length, notes=None, name=None)` — atomic delete-if-exists → create → set_notes → set_name. All on Ableton main thread.
- **Tests**: `tests/unit/test_track_commands.py::TestDeleteSessionClip` and `TestReplaceSessionClip`.
- **Acceptance**: regenerating a clip = 1 round-trip; deleted slot accepts subsequent `create_clip`.
- **Linked req**: #2
- **Depends on**: nothing
- **Estimated diff**: 80-120 lines + tests
- **Upstream-likely?**: Medium — useful additions, no breaking changes.

#### PR E — `create_session_clips` bulk variant
- **Branch**: `feat/bulk-create-session-clips`
- **Title**: `feat: add create_session_clips for bulk session-clip authoring`
- **Why**: Each clip currently requires 3 calls (create + set_notes + set_name). Building falling-walking's 30 clips: 90 calls. Bulk variant collapses to 1 round-trip.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: New tool `create_session_clips(clips: [{track_index, clip_index, length, name?, notes?}])`. Per-clip result reporting; one clip's failure doesn't abort the batch.
- **Tests**: `tests/unit/test_track_commands.py::TestCreateSessionClipsBulk` — partial-failure handling.
- **Acceptance**: 30-clip authoring is 1 call.
- **Linked req**: #9
- **Depends on**: PR D (`replace_session_clip` shows the atomic create-and-populate pattern)
- **Estimated diff**: 60-100 lines + tests
- **Upstream-likely?**: Medium.

#### PR F — `duplicate_clip_to_arrangement` returns new clip identity
- **Branch**: `feat/duplicate-arrangement-return-identity`
- **Title**: `feat: duplicate_clip_to_arrangement returns new arrangement clip identity`
- **Why**: Currently returns just `"Duplicated session clip to arrangement on track N"`. Caller can't track the resulting clip without a follow-up `get_arrangement_info`. For a 49-clip rebuild: 49 wasted round-trips.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: Return `{track_index, arrangement_clip_index, name, start_bar, end_bar}`. Backwards-compat additive.
- **Tests**: `tests/unit/test_arrangement_commands.py::TestDuplicateClipToArrangement` — assert returned shape.
- **Acceptance**: caller can chain ops referencing the new clip without separate query.
- **Linked req**: #6
- **Depends on**: nothing
- **Estimated diff**: 20-30 lines + test
- **Upstream-likely?**: High — small additive improvement.

#### PR G — `create_midi_track` accepts name + instrument_uri
- **Branch**: `feat/create-midi-track-with-name-instrument`
- **Title**: `feat: create_midi_track accepts optional name and instrument_uri`
- **Why**: Setting up a track currently requires 3 calls: `create_midi_track` → `set_track_name` → `load_instrument_or_effect`. For 8 tracks: 24 calls instead of 8. Optional params are fully backwards-compatible.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: Add optional `name` and `instrument_uri` parameters. When provided, set/load atomically post-creation.
- **Tests**: `tests/unit/test_track_commands.py::TestCreateMidiTrackWithOptionalParams` — assert combinations.
- **Acceptance**: `create_midi_track(index=-1, name="Drums", instrument_uri="query:Drums#FileId_5438")` returns track fully set up.
- **Linked req**: #8
- **Depends on**: nothing
- **Estimated diff**: 40-60 lines + tests
- **Upstream-likely?**: High — purely additive.

---

### Wave 3 — Quality + correctness

#### PR H — Rename `add_notes_to_clip` to `set_clip_notes` (clean rename)
- **Branch**: `feat/rename-set-clip-notes`
- **Title**: `feat: rename add_notes_to_clip to set_clip_notes`
- **Why**: The tool name implies append; behavior is replace (calls `clip.set_notes(...)`). Causes silent data loss for callers expecting append. PR A's `append_notes` provides the real append path. This rename eliminates the misleading name.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py` (response message)
- **Change**: Rename the tool. Update response: `"Set N notes on clip (replaced previous content)"`. **No deprecation alias** — songwright is the only consumer and we update it in lockstep.
- **Tests**: `tests/unit/test_track_commands.py::TestSetClipNotes` — assert new name works, assert response wording.
- **Acceptance**: songwright uses `set_clip_notes` everywhere; `add_notes_to_clip` doesn't exist in our fork.
- **Linked req**: #1
- **Depends on**: PR A (so a real `append_notes` exists), PR C ideally (so `add_notes_to_arrangement_clip` gets renamed at the same time — call it `set_arrangement_clip_notes`)
- **Estimated diff**: 30-50 lines + tests
- **Upstream-likely?**: Low — breaking change. **Don't offer upstream as a single PR**; if offering, do an aliased version (separate branch) that keeps `add_notes_to_clip` as a deprecated alias.
- **Note**: After landing, update songwright's `gen_notes.py` invocation pattern in `falling-walking.md` and any future song docs.

#### PR I — Fix `get_cue_points` returns numeric IDs instead of names
- **Branch**: `fix/get-cue-points-names`
- **Title**: `Fix get_cue_points showing numeric IDs instead of cue names`
- **Why**: Returns `"1"`, `"2"`, etc. instead of names that were set. Names persist correctly in Ableton's UI — pure serialization bug.
- **Files**: `AbletonMCP_Remote_Script/__init__.py` (the formatter)
- **Change**: Read `cue_point.name` per Live's `CuePoint` API.
- **Tests**: `tests/unit/test_arrangement_commands.py::TestGetCuePoints` — round-trip verification.
- **Acceptance**: round-trip — set names via `create_cue_point`, read back, names match.
- **Linked req**: #13
- **Depends on**: nothing
- **Estimated diff**: 5-15 lines + test
- **Upstream-likely?**: Highest — clear bug fix.

#### PR J — Fix `create_cue_point` rejects names with apostrophes
- **Branch**: `fix/create-cue-point-apostrophe`
- **Title**: `Fix create_cue_point error on names containing apostrophes`
- **Why**: Names like `"C3'"` fail with misleading `"Cue point already exists at this position: 1"`. Likely string-quoting bug in command construction.
- **Files**: `MCP_Server/server.py` and/or `AbletonMCP_Remote_Script/__init__.py` — diagnose first.
- **Change**: Properly escape the name in the JSON command payload, OR if Live's API genuinely rejects apostrophes, return clear error.
- **Tests**: `tests/unit/test_arrangement_commands.py::TestCreateCuePoint` — assert apostrophe names work or produce clear error.
- **Acceptance**: `create_cue_point(bar=83, name="C3'")` either succeeds or returns clear error.
- **Linked req**: #12
- **Depends on**: nothing
- **Estimated diff**: 10-20 lines + test
- **Upstream-likely?**: Highest — clear bug fix.

#### PR K — `load_instrument_or_effect` returns loaded device info
- **Branch**: `feat/load-instrument-return-device-info`
- **Title**: `feat: load_instrument_or_effect returns loaded device info`
- **Why**: Currently returns `"Loaded instrument with URI '...'. Devices on track:"` with empty trailing list. Caller can't programmatically confirm what loaded.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: Return `{loaded: bool, device_name, device_class, parameter_count}` from `track.devices[-1]`.
- **Tests**: `tests/unit/test_device_commands.py::TestLoadInstrumentReturnInfo` — mock device, assert response shape.
- **Acceptance**: caller verifies device loaded without UI inspection.
- **Linked req**: #10
- **Depends on**: nothing
- **Estimated diff**: 20-30 lines + test
- **Upstream-likely?**: High — additive improvement.

#### PR L — `get_browser_tree` accepts `depth` parameter
- **Branch**: `feat/get-browser-tree-depth`
- **Title**: `feat: get_browser_tree supports recursive depth parameter`
- **Why**: Currently returns only one level. Drilling requires 1 call per level. Defaults to depth=1 (current behavior — no breaking change).
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: Add `depth: int = 1, max 5` param. Recursively walk children.
- **Tests**: `tests/unit/test_browser_path_normalization.py::TestBrowserTreeDepth` — assert depths 1, 2, 3 return progressively more.
- **Acceptance**: `get_browser_tree(category_type="instruments", depth=3)` returns nested tree.
- **Linked req**: #7
- **Depends on**: nothing
- **Estimated diff**: 30-50 lines + tests
- **Upstream-likely?**: High — backwards-compat additive.

---

### Wave 4 — Nice-to-have

Land when bandwidth allows. None block songwright work.

#### PR M — `get_session_devices_snapshot`
- **Branch**: `feat/get-session-devices-snapshot`
- **Title**: `feat: add get_session_devices_snapshot for bulk device parameter capture`
- **Why**: `get_device_parameters` works per-device. Sound-design iteration wants all-tracks-all-devices state in one call (diff/snapshot/restore workflows).
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: New tool returning `[{track_index, device_index, device_name, parameters: [{name, value, min, max}]}]` for all loaded devices.
- **Tests**: `tests/unit/test_device_commands.py::TestSessionDevicesSnapshot`.
- **Linked req**: #11
- **Depends on**: nothing
- **Estimated diff**: 50-80 lines + tests
- **Upstream-likely?**: Medium.

#### PR N — Undo/redo wrappers
- **Branch**: `feat/undo-redo-wrappers`
- **Title**: `feat: expose Ableton undo/redo via MCP`
- **Why**: Destructive ops (delete clips, replace notes) are immediate; no recovery path. Live's native undo works but isn't surfaced.
- **Files**: `MCP_Server/server.py`, `AbletonMCP_Remote_Script/__init__.py`
- **Change**: New tools `undo()` and `redo()` wrapping `app.undo()` / `app.redo()`.
- **Tests**: `tests/unit/test_arrangement_commands.py::TestUndoRedo`.
- **Linked req**: #14
- **Depends on**: nothing
- **Estimated diff**: 20-40 lines + tests
- **Upstream-likely?**: High — small useful addition.

#### PR O — Document clip slot capacity behavior
- **Branch**: `docs/clip-slot-capacity`
- **Title**: `docs: clarify session clip slot capacity and scene auto-creation`
- **Why**: Default sessions appear capped at 8 slots per track. Unclear what `create_clip` does at slot 9+.
- **Files**: `README.md`
- **Change**: Document slot/scene relationship and recommended pattern.
- **Tests**: none.
- **Linked req**: #15
- **Depends on**: nothing
- **Estimated diff**: 20-40 lines docs
- **Upstream-likely?**: High — pure docs.

---

### Summary — ship order

| # | PR | Wave | Depends on | Diff | Upstream-likely |
|---|-----|------|------------|------|-----------------|
| A | Note-level addressing (4 tools) | 1 | — | L | Low |
| B | batch_arrangement_layout | 1 | F | L | Low |
| C | Expose add_notes_to_arrangement_clip | 1 | (H) | M | High |
| D | delete + replace_session_clip | 2 | — | M | Medium |
| E | create_session_clips bulk | 2 | D | M | Medium |
| F | duplicate returns clip identity | 2 | — | S | High |
| G | create_midi_track w/ name + instrument | 2 | — | M | High |
| H | Rename to set_clip_notes (clean) | 3 | A, (C) | M | Low — offer aliased version separately if at all |
| I | Fix get_cue_points names | 3 | — | S | Highest |
| J | Fix create_cue_point apostrophe | 3 | — | S | Highest |
| K | load_instrument returns device info | 3 | — | S | High |
| L | get_browser_tree depth | 3 | — | M | High |
| M | get_session_devices_snapshot | 4 | — | M | Medium |
| N | undo/redo wrappers | 4 | — | S | High |
| O | docs: clip slot capacity | 4 | — | S | High |

**XS** ≤ 10 lines · **S** 10-50 · **M** 50-150 · **L** 150-300

### Cadence

Internal (fork): as fast as testing allows. Wave 1 unblocks the songwright DB direction, so do it first. Waves 2-4 are then quality-of-life and can be paced with songwright development needs.

Upstream offerings: queue them in a backlog and submit a few at a time. Order by `Upstream-likely`:

1. **Highest** (file first, gets bug-fix credit): PRs I, J
2. **High** (small additive, hard to refuse): PRs F, G, K, L, N, O, C
3. **Medium** (composite or bulk additions): PRs D, E, M
4. **Low** (architectural or breaking): PRs A, B, H — submit after the easy ones land or just don't bother

If the maintainer never engages, no behavior changes for us. Songwright keeps moving.

### Songwright impact / sequencing

The Wave 1 PRs (A, B, C) are the unlock for the **DB-as-MIDI-source-of-truth** direction described above. Until they land in the fork, songwright iterates with the current "regenerate Python → set_clip_notes → delete-and-redup arrangement" pattern. After they land:

- `get_clip_notes` enables sync-back from manual Ableton edits → DB
- `update_notes` / `delete_notes` enable surgical DB-driven mutations without rewriting whole clips
- `batch_arrangement_layout` makes arrangement rebuilds cheap enough to do on every DB push
- `add_notes_to_arrangement_clip` (exposed in PR C) eliminates the delete-and-redup cycle entirely for note-only updates

Realistic sequencing: ship Wave 1 to fork over a few days. Then start the songwright DB schema + sync layer in parallel with Wave 2/3 PRs.
