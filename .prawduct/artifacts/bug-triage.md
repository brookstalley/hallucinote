# Bug Triage — falling-walking push session (2026-05-17)

Findings from end-to-end push of `songs/falling-walking` against real Live 12.4
via `hallucinote-mcp`. Numbered for cross-reference from `build-plan.md`.

## Severity legend

- **P0 — Blocking**: prevents core push workflows for real songs.
- **P1 — Important**: incorrect or misleading behavior; user-visible.
- **P2 — Cosmetic / consistency**: response shape, naming, edge-case errors.
- **D — Documented gap**: known deferred surface; track only.

---

## Already fixed in source (need Live restart + Critic to validate)

These all shipped during the session as one-off fixes alongside discovery.
Tests added; ~886 tests pass. Each needs an end-to-end check against a fresh
Live before we close it out.

### B-1. `is`-identity scans fail under Live's wrapper recreation  ·  P0

Five handlers scanned `song.X` for `obj is new_obj` after a create call. Live
12.x re-wraps API objects on every property access, so `is` is unreliable;
the scan silently failed and the handler returned a false "Live API bug"
error (or returned a result missing a key field).

- `handlers/track.py::create_handler` — false-error, but track existed.
- `handlers/scene.py::create_handler` — same.
- `handlers/return_.py::create_handler` — same.
- `handlers/clip.py::create_handler` (arrangement path) — `arrangement_clip_index` missing from result; apply-layer link write was silently broken.

**Fix**: deterministic index from the create call's known semantics
(`len(song.X)` after append; `insert_at + 1` for insert; `start_time` match
for arrangement clips). Regression tests added in
`tests/unit/test_actions_{track,scene,return,clip}.py` using a fake that
simulates wrapper recreation.

### B-2. `cue_create` / `cue_delete` called `set_or_delete_cue(time)`  ·  P0

Older Live versions reportedly took a `time` argument; Live 12.x is no-arg.
Crashed with `ArgumentError` on every non-trivial cue operation.

**Fix**: always seek + no-arg toggle, with a wall-clock sleep to let Live's
audio thread settle the `current_song_time` write. Verify success via
`cue_points` (the real side effect) rather than via the `current_song_time`
getter (which can return stale cached values for ~hundreds of ms).
Files: `handlers/arrangement.py`. Tests updated.

### B-3. `LiveContext` Protocol missing `application`  ·  P0

Three handlers reached `song.get_application()`. Live's `Song` does NOT
expose that — `Live.Application.get_application()` is the module-level
accessor.

**Fix**: extended `LiveContext` with an `application` property; plumbed
through `LiveLiveContext` (wired to `ControlSurface.application`), and
updated `session.py`, `arrangement.py`, `browser.py`. Test fakes refactored
to own a `FakeApplication` on the ctx, not the song.

### B-4. `cue_create` — Live `current_song_time` settle is asynchronous  ·  P0

After `song.current_song_time = X`, the write is queued for the audio
thread; the main-thread getter and `set_or_delete_cue` both see a stale
value within the same callback. Same-callback bouncing through
`schedule_message(0, fn)` doesn't help — those callbacks fire back-to-back
in one engine tick without yielding wall-clock time to the audio thread.

**Fix**: use `time.sleep(0.2)` to give the audio thread real time, then
trust the write (don't verify via getter), then read `cue_points` to
confirm the cue exists at the target position. (An earlier attempt
built a `DeferredCompletion` / `schedule_after_tick` infrastructure on
the assumption the problem was same-tick visibility; empirically it
was audio-thread settle, which only wall-clock time solves. The deferred
scaffolding was removed after Critic flagged it as YAGNI.)

### B-5. `cue_create` clamps silently when `position_beats > last_event_time`  ·  P1

Live rejects (silently) `current_song_time` writes past the arrangement
extent. The cue ended up at 0, corrupting the cue at 0 if one existed.

**Fix**: pre-check `position_beats <= song.last_event_time` and raise a
teaching error pointing the user at the "place arrangement content first"
workflow. Test added.

### B-6. `cue_create` failed to apply the inline rename due to async timing  ·  P1

When the same-tick post-toggle scan missed the cue, the rename step was
skipped; cues landed with Live's auto-names (`"1"`, `"2"`, ...).

**Fix (partial)**: B-4's trust-the-write change makes the post-toggle scan
succeed reliably (we wait wall-clock time first). Added a `cue_rename`
action as a recovery path for any historical cues with bad names.

### B-7. `session.seek` response field misreports `song_time`  ·  P1

Handler read `song.current_song_time` AFTER writing it; the getter is
stale, so it returned `last_event_time` instead of the new playhead.

**Fix**: return the COMPUTED `song_time` from inputs, not a getter
readback. Same root cause as B-4.

### B-8. MCP-bridge version handshake missing  ·  P0 (foundational)

When MCP server side and Remote Script side run different versions of
the codebase, the bridge silently misbehaves (we hit this when I rebuilt
the Remote Script vs. the running MCP server).

**Fix**: added `wire.Request.server_version`; `client.send` stamps the
local `hallucinote_mcp.__version__`; Live-side handler checks before
dispatch and surfaces a structured `version_mismatch` error pointing at
the `/mcp` reconnect + `/ableton-install-mcp` recovery flow. 11 new
tests cover the wire-protocol surface.

### B-9. Remote Script side never imported `hallucinote_mcp.actions`  ·  P0

`_control_surface.py` only called `schema.register_help_actions()`,
leaving every non-help action unregistered on Live's side. Every
forwarded tool call returned `unknown action ... valid_actions=["help"]`.

**Fix**: added `from .. import actions as _actions` (side-effect import)
to `_control_surface.py`. AST regression test in `tests/unit/test_remote_script_init.py`.

---

## New bugs not yet fixed

### B-10. `ableton_device(action='load')` fails on BOTH tracks and returns  ·  P0

Previously believed to affect only returns. Empirical Live 12.4 testing
shows `getattr(track, 'load_device', None)` returns None for regular
`Track` objects too. **Every** device-load call fails with
`NotImplementedError: track does not expose load_device`.

- File: `handlers/device.py::load_handler`.
- Falling-walking has 24 device loads in DB across instrument tracks +
  returns. Zero of them succeed.
- Need to find Live's actual API path — likely `Application.browser.load_item(item)`
  after browser navigation to the device URI. Or `track.view.select_device`
  workflows.
- The existing backlog entry "MCP gap: device load on return tracks"
  needs to be expanded to cover regular tracks too.

### B-11. `ableton_automation(write_envelope)` fails for track-level arrangement automation  ·  P0

`target_kind='mixer_volume'` (and presumably the other mixer/send target
kinds) with `track_index=N` and NO `clip_index`/`location` raises
`NotImplementedError: track-level (arrangement) automation creation is
not exposed on this parent in this Live version`.

- File: `handlers/automation.py::write_envelope_handler` (or its mixer
  branch).
- Falling-walking has 2 `mixer_volume` envelopes (Verse Pad swell at
  bars 17-25, Synth Bass sidechain-style ducking through chorus). Neither
  can land today.
- Investigate Live's actual API. Possibilities: `MixerDevice.volume.automation_state`,
  `Track.envelopes.create_envelope()`, or arrangement-clip-scoped envelopes
  via `Clip.automation_envelopes.create_clip_automation_envelope(parameter)`.

### B-12. `ableton_device(action='enable')` and `'disable'` fail  ·  P1

Both raise `AttributeError: property of 'Device' object has no setter`.
The handler appears to be writing to a Live `Device.is_active`-shaped
property that isn't writable on this Live version (or this device class
— tested against `Reverb` on a return).

- File: `handlers/device.py::enable_handler`, `disable_handler`.
- Investigate which `is_active`-like property IS writable, or whether
  Live exposes the toggle via a method instead.

### B-13. `ableton_arrangement(control_view, action_kind='collapse_track')` on non-group tracks  ·  P2

Handler bubbles Live's `RuntimeError: This Track can not be collapsed`
without any pre-check. Users get a raw runtime error instead of a
teaching one.

- File: `handlers/arrangement.py::control_view_handler`.
- Pre-check `track.is_grouped` or similar before calling, raise a
  ValueError with guidance.

### B-26. `ableton_clip(set_property, property='gain'|'pitch'|'warp')` on MIDI clips  ·  P2

Audio-only properties bubble Live's raw error
("Gain is only available for Audio Clips") instead of a teaching
ValueError. Same shape as B-13 — handler should pre-check the clip kind
and reject with a clear message naming the audio-only properties.

- File: `handlers/clip.py::set_property_handler`.

### B-14. `ableton_return(action='create', name=X)` auto-prefixes the slot letter  ·  P2

Requesting `name="C-TestReturn"` stored as `"C-C-TestReturn"`. Live
appears to prepend `"C-"` (the slot letter) regardless of what the
handler sets.

- File: `handlers/return_.py::create_handler`.
- Likely fix: after setting the name, read it back; if Live prefixed,
  either strip the prefix from our incoming name, or surface a warning.

### B-22. Clip-scoped `write_envelope` calls `Envelope.clear()` which doesn't exist on Live 12.4  ·  P1

Validation pass observed: `ableton_automation(write_envelope, target_kind='mixer_volume',
track_index=N, location='session', clip_index=K, breakpoints=...)` fails with
`AttributeError: 'Envelope' object has no attribute 'clear'`. The handler
appears to call `.clear()` on the existing envelope before writing
breakpoints; Live 12.4's `Envelope` class doesn't expose `clear`.

- File: `handlers/automation.py::write_envelope_handler` (clip-local branch).
- Sibling of B-11 (track-level automation creation gap), but a separate
  fix because the API path is different (clip-bound envelope vs.
  track-level mixer envelope).
- Workaround: don't pre-clear; let `add_value_point` overwrite. Or
  iterate existing breakpoints and remove individually if such an API
  exists.

### B-23. `ableton_track(action='delete')` passes Track object but Live 12.4 expects int  ·  P1

Live 12.4's `Song.delete_track(int)` takes a 0-based int; the handler
passes the Track wrapper object. Fails immediately with
`ArgumentError: Python argument types in Song.delete_track(Song, Track)
did not match C++ signature: delete_track(TPyHandle<ASong>, int)`.

- File: `handlers/track.py::delete_handler`.
- Fix: pass `track_index - 1` (the 0-based index) to `song.delete_track`.

### B-24. `duplicate_to_arrangement` creates spurious extra clip when destination overlaps an existing arrangement clip  ·  P1

Repro: arrangement has clip ScaffoldA at 0..128. Call
`duplicate_to_arrangement(track_index=5, clip_index=1, start_beats=64.0)`
where session slot 1 = a 4-beat clip. Expected: one new arrangement clip
at 64..68. Observed: TWO new arrangement clips — the requested
SessionScaffold at 64..68 AND a second ScaffoldA at 68..196 (length 128,
same as the original). The original ScaffoldA at 0..128 remains
unchanged.

- Files: `handlers/clip.py::duplicate_to_arrangement_handler` (maybe).
  Could also be a Live API quirk we need to compensate for.
- Likely cause: Live's `Track.duplicate_clip_to_arrangement` may copy
  the destination-region's existing clip and shift it; the handler
  doesn't anticipate the side effect.
- Investigate by: calling Live's duplicate API directly with a fake
  arrangement and verifying the result matches expectation.

### B-25. `ableton_automation(action='clear_all', track_index=N)` track-level fails  ·  P1

`NotImplementedError: track does not expose clear_all_envelopes /
remove_automation in this Live version`. Sibling of B-11 — same
"track-level automation API isn't there" theme, different action.

- File: `handlers/automation.py::clear_all_handler`.
- Folded into Chunk D scope (track-level automation investigation).

### B-15. Multiple `set_*` actions return `null` instead of structured result  ·  P2

Inconsistent response shape across actions:

- `ableton_session(set_tempo)` → `{ok:true, result:null}`. Should be `{tempo: N}`.
- `ableton_session(play)` → `null`. Should be `{is_playing: true}`.
- `ableton_session(stop)` → `null`. Should be `{is_playing: false}`.
- `ableton_track(rename)` → `null`. Should be `{track_index, name}`.

Other actions (`set_signature`, `set_master_property`, `track.set_property`,
`return.set_property`, `clip.set_property`, etc.) return useful info.
The null-returning ones are the outliers.

- Files: `handlers/session.py`, `handlers/track.py`, and the declarative
  action specs in `actions/session.py`, `actions/track.py`.
- These are likely declarative actions; the result shape comes from the
  schema's `result_template` or similar. Need to audit which actions
  fall into this group and define proper result shapes.

---

## Documented gaps (track only, not fixing in this batch)

### B-16. Snapshot / revert / list_snapshots are deferred  ·  D

`ableton_session(snapshot|revert|list_snapshots)` all raise
`NotImplementedError`. Schema stable; implementation gated on the
design decision between Live undo-checkpoint and `.als` save-as.

### B-17. Envelope read surface gap  ·  D

`ableton_automation(list|get_envelope)` blocked. Backlog already covers.

### B-18. Per-note operations (gap #4)  ·  D

`ableton_note(add|update|delete)` blocked. Backlog already covers.

### B-19. Nested rack chain probe + push  ·  D

`DrumGroupDevice`, `InstrumentGroupDevice` cannot have their internal
chains traversed. Backlog already covers.

### B-20. No `ableton-push` skill / orchestrator  ·  D

The push workflow has no agent-facing skill. Each push session
re-derives the call sequence by hand. Backlog covers.

---

## What works (validated end-to-end against Live 12.4)

For the build plan, these are the "don't regress" surface — fixes
should not break these:

- `ableton_session`: `info`, `set_tempo` (works, response is null — see B-15),
  `set_signature`, `set_master_property`, `seek` (after B-7 fix),
  `play` / `stop` (work, return null — see B-15), `set_view` (after B-3 fix).
- `ableton_track`: `list`, `info`, `create` (after B-1 fix), `set_property`
  (volume, panning, mute, solo, arm, color), `get_property`, `set_send`,
  `get_sends`, `rename` (works, returns null — see B-15), `deletion_status`.
- `ableton_return`: `list`, `set_property`. `create` works for index
  resolution (after B-1 fix); name has the B-14 prefix issue.
- `ableton_clip`: `create` (both session and arrangement, after B-1 fix
  for arrangement), `list`, `set_property`, `rename`, `replace_notes`
  (validated at 1, 64, 105 note scales — and 137 earlier),
  `duplicate_to_arrangement` (32/32 placements at correct beats), `fire`,
  `stop`. `delete` untested.
- `ableton_note`: `list` (works; `add`/`update`/`delete` documented gap).
- `ableton_arrangement`: `info`, `cue_list`, `cue_create` (works in
  isolation after B-2 + B-4 + B-5 fix; parallel needs more work — see
  unresolved P0 issue below), `cue_delete` (after B-2 fix), `cue_rename`
  (new action; works), `cue_jump`, `set_loop`, `control_view` (zoom,
  scroll, follow_on/off; collapse needs B-13 fix).
- `ableton_scene`: `list`, `create` (after B-1 fix), `set_tempo` (returns
  scaled result; works).
- `ableton_device`: `list`, `info` (untested), `get_parameters`,
  `set_parameter` (continuous values work).
- `ableton_browser`: `tree`, `at_path` (untested), `plugins_list`.

---

## Unresolved P0 — needs design

### B-21. `cue_create` parallel-call race  ·  P0

Even with B-4's sleep-based settle, simultaneous calls (LLM agent firing
multiple `cue_create` calls in parallel) race the shared
`current_song_time`. Each handler's sleep is on the main thread; multiple
handlers' writes queue up and the audio thread can only process one per
audio buffer. Each handler ends up reading the PREVIOUS handler's target.

Options:
- **A. Serialize at the agent level**: don't fire parallel `cue_create` calls.
  Documentation-only; doesn't fix the race for other concurrent users.
- **B. Add a per-Song mutex in the handler**: only one cue_create can run
  at a time. Adds ~200ms latency per cue (acceptable for setup ops).
- **C. Batch cue creates into a single Remote-Script-side action**:
  `ableton_arrangement(action='cue_create_batch', [{position_beats, name}, ...])`.
  The handler serializes internally.

Recommend **B** (per-Song mutex) for the bridge layer + **C** (batch
action) as an ergonomics win.
