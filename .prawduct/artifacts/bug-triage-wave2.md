# Bug Triage — falling-walking push session Wave 2 (2026-05-18)

Second comprehensive push pass after Chunks A-D landed. Goal: find every
remaining issue blocking a clean end-to-end push of `songs/falling-walking`
against real Live 12.4 via `hallucinote-mcp`.

## Severity legend

- **P0 — Blocking**: prevents core push workflows for real songs.
- **P1 — Important**: incorrect or misleading behavior; user-visible.
- **P2 — Cosmetic / consistency**: response shape, naming, edge-case errors.
- **D — Documented gap**: known deferred surface; track only.

## Status legend

- **NEW** — surfaced in this Wave 2 pass.
- **CONFIRMED** — Wave 1 bug confirmed still present.
- **FIXED-VERIFIED** — Wave 1 bug, now verified fixed end-to-end.
- **REGRESSION** — was working in Wave 1, broken now.

---

## Wave-1 bugs re-confirmed against fresh Remote Script (2026-05-18)

After the W2-5 Remote Script reinstall, the following Wave-1 findings remain present:

- **B-12** ↔ W2-8. device.enable/disable raw AttributeError. Live's `is_active` is read-only on at least CompressorDevice.
- **B-13**. `control_view(action_kind='collapse_track', track_index=1)` on a non-group track → raw `RuntimeError: This Track can not be collapsed`. No pre-check; teaching error missing.
- **B-15**. `session.play`, `session.stop`, `track.rename` all return `result: null`. Other set_* actions return structured results — inconsistent.
- **B-16**. `session.snapshot` raises `NotImplementedError` (deferred surface; expected).
- **B-23** ↔ W2-2. `track.delete` passes Track wrapper instead of int.
- **B-24**. `duplicate_to_arrangement` creates a spurious extra clip. Empirically reproduced: with Scaffold at 0..32 (length=32), `duplicate_to_arrangement(clip_index=2, start_beats=16)` produced [Scaffold 0..32, DupSource 16..20, **Scaffold 20..52**]. The second Scaffold (length 32, starting at the destination position) is the side effect. Live's `Track.duplicate_clip_to_arrangement` quirk — not a handler bug. Either document or compensate by deleting the spurious clip post-call.
- **B-26**. `clip.set_property(property='gain', value=0.5)` on MIDI clip → raw `RuntimeError: Gain is only available for Audio Clips`. No pre-check.

## Triage chunks (priorities for Phase 3 — autonomous fix wave)

Ordered by **falling-walking-push unblocking impact** first, then by **structural value**.

| Chunk | Findings | Why prioritized | Sizing |
|-------|----------|-----------------|--------|
| **W2-A** | W2-2, W2-3 + standardization helper | Track + return delete are sibling bugs; the cleanest fix introduces an `_delete_via_song(kind, index_1based)` helper and tightens the fakes (so future int-vs-wrapper bugs fail at test time, not in production). | ~150 LoC + tests |
| **W2-B** | W2-7 device-name resolution | Falling-walking has 24 devices, all currently unloadable. Biggest single push unblock. Adds `device_names.py` table + planner-side URI resolution. | ~250 LoC + tests |
| **W2-C** | W2-8/B-12, W2-9, B-13, B-26 teaching errors | Quick wins; pre-checks + targeted try/except around known Live-API quirks. Each adds a teaching error pointing at the correct workaround. | ~200 LoC + tests |
| **W2-D** | B-15 null result shapes | Cosmetic but agent-hostile (agents need to *know* what changed). Audit + populate result templates for stop/play/rename/etc. | ~100 LoC + tests |
| **W2-E** | W2-10 arrangement-clip envelopes | Falling-walking has 2 mixer_volume envelopes. Sub-cases: (a) document mixer_volume-on-arrangement gap + suggest session workaround; (b) fix clip_pitch_bend tuple/parameter resolution. | ~200 LoC + tests |
| **W2-F** | W2-4, W2-6 cue race | Falling-walking has 7 cue points. Needs deeper investigation of audio-thread settle when transport is stopped (200ms isn't enough). Probably a 1-2s settle + verify-via-side-effect for cue_delete. | ~300 LoC + tests + real-Live |
| **W2-G** | W2-5 Remote Script drift detection | Structural. Today's session burned ~30 min on stale-handler debugging. Replace `__version__` with content hash; surface mismatch in handshake; install skill detects + offers fix. | ~250 LoC + tests + install skill update |
| **W2-H** | B-24 duplicate quirk | Investigation; document or compensate. Lower priority — workaround is "duplicate then delete the spurious clip" client-side. | ~150 LoC |

Execution order: A → B → C → D → E → F → G → H. (G can move earlier if discovery shows we're burning time on drift again; for now the reinstall just happened.)

## Findings (chronological — append as they appear)

### W2-5. Remote Script in Live's User Library is stale; version handshake doesn't catch source drift  ·  P0  ·  NEW

Symptom: `ableton_arrangement(action='cue_create_batch', cues=[...])` returns "unknown action 'cue_create_batch'" with `valid_actions` listing only 9 actions (missing `cue_create_batch`). But `ableton_arrangement(action='help')` lists 10 actions including `cue_create_batch`.

Diagnosis: the server-side schema registry has `cue_create_batch` (verified by `python -c "from hallucinote_mcp import actions; from hallucinote_mcp.schema import action_names_for; print(action_names_for('ableton_arrangement'))"`). help is server-side resolved and returns the full list. But unknown-action errors from validation come back via the wire — the dispatcher forwards to Live, and Live's Remote Script has its OWN copy of the source tree under `~/Music/Ableton/User Library/Remote Scripts/Hallucinote/`. That copy hasn't been updated since before Chunk B (commit `dc1c971`, 2026-05-18) added the action. Live's stale registry rejects it.

**Root structural issue**: `hallucinote_mcp.__version__ = "0.1.0"` is hard-coded. B-8's version handshake compares this string between server and Remote Script — both sides import the same module from the SAME source tree (or different trees, but the constant is static), so the handshake always reports "match" even when the trees diverge. Source-vs-Remote-Script drift is therefore silent. Net agent UX: confusing "unknown action" errors that contradict what `help` advertises.

**Fix shape** (two layers):
1. Replace the static `__version__` with a content fingerprint that changes whenever the action surface changes. Cheapest: a build-time hash of the schema registry serialization (sort action names + param specs, sha256). On startup, the Remote Script sends its fingerprint; the server compares and surfaces a structured "Remote Script outdated, run /ableton-install-mcp" error on mismatch.
2. The `/ableton-install-mcp` skill detects the drift itself (compare timestamps or hashes of the source tree vs the Remote Script tree on first server boot) and prompts the user.

**User-facing implication**: until this lands, every source change touching the action surface needs a manual `/ableton-install-mcp` reinstall, which the user has no signal to trigger. Today's session likely has stale Live-side handlers for `cue_create_batch`, plus the Chunk C `browser.load_item` device fix, plus the Chunk D arrangement automation rewrite. All of Chunks B/C/D's claimed-fixed bugs may still manifest as Live-side errors until the install is re-run.

**Action for the user**: re-run the `/ableton-install-mcp` skill, then a full Live quit + reopen, before resuming wave-2 testing. Logging this now and skipping the affected actions for the remainder of this discovery pass.

### W2-4. `cue_create` returns false-positive success then fails subsequent calls  ·  P0  ·  NEW (likely B-4/B-6 regression under non-zero playhead)

Repro (real Live 12.4 against a single short clip 0-16 beats on track_index=5):

1. Playhead at 8.0 (from prior `session.seek(bar=3, beat=0)`).
2. `cue_create(position_beats=0, name='Intro')` → `ok:true, {cue_index:1, position_beats:0, name:'Intro'}`. Handler reported success.
3. `arrangement.cue_list` → `cue_points: []`. The "success" was a lie.
4. `cue_create(position_beats=8, name='Verse')` → fails with diagnostic `new_positions=[], all_observed=[], target=8.0`. So step 2 did NOT actually create a cue anywhere — Live's audio thread silently dropped the seek+toggle.
5. `cue_create(position_beats=4, name='TestCue')` → fails with diagnostic `new_positions=[8.0], all_observed=[8.0], target=4.0`. So this call's toggle DID create a cue, but at position 8 (the original playhead) — the seek to 4 didn't reach the audio thread within the 200ms sleep window.
6. `arrangement.cue_list` → `cue_points: [{cue_index:1, position_beats:8, name:'1'}]`. Live auto-named it.

Two distinct failures:
- **W2-4a**: handler false-positive on cue_create at position 0 (Chunk A's B-6 fix incomplete — wait-then-verify-via-side-effect somehow agreed even when Live didn't persist).
- **W2-4b**: 200ms `time.sleep` in `_seek_then_settle` is insufficient when prior playhead is far from target. Either the sleep needs to scale with seek-distance, or the verify step must compare playhead position before toggle (not just trust the sleep).

Both feel like the same root cause as Wave 1 B-4: trust-the-write semantics break when the audio thread is slower than the wall clock. Fix shape: post-seek, READ `current_song_time` in a loop until it equals the target (with a max wait), THEN toggle. The "asynchronous settle" pattern needs a verify-before-action gate, not a fixed sleep.

**Verified against fresh Remote Script (2026-05-18 post-reinstall)**:
- Empty arrangement (no clips) + cue_create at position past last_event_time: handler does NOT raise B-5's teaching error before attempting the toggle. Live's set_or_delete_cue then fires at the clamped playhead (0), creating spurious cues. The B-5 pre-check appears to use a `last_event_time` value that doesn't match Live's actual clamp boundary — Live reports `total_length_beats=24` even on empty arrangements (8-scene minimum?), and cues at 4, 8 fire at the unmoved playhead.
- With a real arrangement clip at 0-32: a SINGLE cue_create at position 0 returns ok-with-success but cue_list shows empty afterward (the cue was created then later toggled-off when the NEXT seek failed and toggled at the same position).
- `session.seek(bar=4, beat=0)` followed immediately by `session.info` shows current_song_time=12.0 (write took). Calling `cue_create(position_beats=16)` next: diagnostic reports the toggle fired at 12 (the prior seek's destination), not 16. The CUE-CREATE handler's own seek to 16 didn't settle within its 200ms sleep window.

This points at the **audio thread**'s settle delay being substantially > 200ms when transport is STOPPED. Likely: Live processes `current_song_time` writes lazily when transport is idle. The reliable fix is probably: (a) bump sleep aggressively (1-2s) for stopped transport, OR (b) loop-poll the audio-thread-visible playhead position via a different probe, OR (c) briefly start+stop transport to force a refresh (heavyweight but reliable).

Files: `handlers/arrangement.py::cue_create_handler` + `_seek_then_settle` helper. Tests: real-Live regression with playhead-at-far-position before cue_create.

### W2-6. `cue_delete` returns success but cue persists  ·  P1  ·  NEW (sibling of W2-4)

Repro: arrangement with 3 cues at positions 4, 12, 16. `cue_delete(cue_index=2)` succeeds, deleting the cue at 12. `cue_delete(cue_index=1)` succeeds but cue_list afterward still shows 2 cues at positions 4 and 16. One of the deletes was a no-op despite `ok:true`.

Likely same root cause as W2-4: cue_delete (which calls `set_or_delete_cue` after seeking to the cue's position) has the same async-settle race. Captured separately because the symptom differs (cue_delete handler doesn't verify-via-side-effect, so it returns success unconditionally after the toggle).

Files: `handlers/arrangement.py::cue_delete_handler`. Mirror the verify-via-side-effect pattern used by cue_create — confirm the target cue actually disappeared.

### W2-3. `ableton_return(action='delete')` passes Track object instead of int  ·  P1  ·  NEW

Same root-cause pattern as W2-2 / B-23, different handler. `handlers/return_.py:118` reads `delete_fn(ret)` — passing the ReturnTrack wrapper. Real-Live test:

```
ableton_return(action='delete', return_index=4)
→ ArgumentError: Python argument types in Song.delete_return_track(Song, Track)
  did not match C++ signature: delete_return_track(TPyHandle<ASong>, int)
```

Fix: `delete_fn(return_index - 1)` (mirrors the working `handlers/scene.py:123`).

By contrast, `handlers/scene.py:123` correctly does `delete_fn(scene_index - 1)` — verified working: `scene.delete(scene_index=9)` → `ok:true`. So the int-vs-wrapper inconsistency lives only in track + return.

### W2-2. `ableton_track(action='delete')` still passes Track object instead of int  ·  P1  ·  CONFIRMED (Wave 1 B-23)

The build-plan marked Chunk A "smoke pass complete" but `handlers/track.py:175` still reads `song.delete_track(track)` — passing the wrapper object. Real-Live test:

```
ableton_track(action='delete', track_index=4)
→ ArgumentError: Python argument types in Song.delete_track(Song, Track)
  did not match C++ signature: delete_track(TPyHandle<ASong>, int)
```

B-23 from `bug-triage.md` predicted this exactly. Fix: `song.delete_track(track_index - 1)`. Adds regression test against the wrapper-recreation fake (the handler can't trust `track` identity, but the int is computed from input).



### W2-7. `ableton_device(action='load')` rejects Live's internal class names — falling-walking's 24 devices unloadable  ·  P0  ·  NEW

Live exposes devices via TWO different name spaces:
- **Internal class name** (`device.class_name`): `Compressor2`, `Eq8`, `StereoGain`, `DrumGroupDevice`, `InstrumentGroupDevice`, `InstrumentMeld`, `InstrumentVector`, `LoungeLizard`.
- **Browser display name**: `Compressor`, `EQ Eight`, `Utility`, `Drum Rack`, `Instrument Rack`, `Meld`, `Wavetable`, `Electric`.

`device.list` returns the class name. `device.load(kind=...)` walks the browser looking for a node whose DISPLAY name matches. So a round-trip (capture → push) is broken for every built-in device with a class-vs-display rename: a captured `Compressor2` reaches the planner, which emits `device.load(kind='Compressor2')`, which finds no browser node named "Compressor2" → fails with "no loadable browser item found for kind='Compressor2'".

Empirical (real Live 12.4):
- `device.load(track_index=1, kind='Compressor2')` → `ValueError: no loadable browser item found for kind='Compressor2'`.
- `device.load(track_index=1, kind='Compressor', preset_uri='query:AudioFx#Compressor')` → `ok:true, device_index=1`. After load, `device.list` reports `{class_name: 'Compressor2'}`. Round-trip needs to know that translation.

**Impact**: falling-walking has 24 devices captured by class name; every push of devices fails today. This is the biggest single blocker for the push test.

**Fix shape** (two-tier):
1. **Handler tier**: in `device.load`, if the `kind` argument doesn't match a browser display name, try a **class-name → display-name** translation table (built-in Live device renames: `Compressor2 → Compressor`, `Eq8 → EQ Eight`, `StereoGain → Utility`, `DrumGroupDevice → Drum Rack`, `InstrumentGroupDevice → Instrument Rack`, `AudioEffectGroupDevice → Audio Effect Rack`, `MidiEffectGroupDevice → MIDI Effect Rack`, `InstrumentMeld → Meld`, `InstrumentVector → Wavetable`, `LoungeLizard → Electric`, `Operator → Operator` no-op, `Chorus2 → Chorus-Ensemble`, `Saturator → Saturator` no-op). Table lives in `hallucinote_mcp/src/hallucinote_mcp/device_names.py` (testable in isolation; resource-readable for agents).
2. **Sync-planner tier**: `plan_push_devices` should emit `kind=display_name, preset_uri=resolved_uri` whenever possible — the URI is the unambiguous load contract. The class-name field is captured for diff/identity, but the LOAD calls should prefer display+URI. Add a `_resolve_device_uri(class_name)` helper that uses the same table.

Tests: unit tests on the translation table; integration test that loads each major class name and confirms `class_name` after load matches the captured form.

### W2-8. `ableton_device(action='disable')` raw AttributeError on Compressor  ·  P1  ·  CONFIRMED (Wave 1 B-12)

Real Live 12.4: `device.disable(track_index=1, device_index=1)` (Compressor loaded) → `AttributeError: property of 'CompressorDevice' object has no setter`.

The handler writes to `device.is_active` directly. Live exposes `is_active` as read-only on at least Compressor (and presumably others). The setter, if any, is via a different API. Per Live docs, `parameters[0]` is conventionally "Device On" — and the get_parameters output for this device confirms `[0] = {name: "Device On", value: 1.0, value_display: "On"}`. So the real toggle is via the Device-On parameter, not `is_active`.

Fix shape: enable/disable handlers should find the parameter named "Device On" (index 0 by convention) and write `value = 1.0` (enable) or `0.0` (disable). Fall back to `is_active` only if no Device-On parameter exists. Wrap any AttributeError in a teaching error.

### W2-9. `device.get_parameters(detail='full')` raises raw RuntimeError on continuous parameters  ·  P1  ·  NEW

Real Live 12.4: `device.get_parameters(track_index=1, device_index=1, detail='full')` → `RuntimeError: Only quantized parameters have value items`. Live's `Parameter.value_items` accessor raises on non-quantized params; the handler eagerly calls it on every parameter. `detail='summary'` works fine because it doesn't read `value_items`.

Fix: in the full-detail loop, only call `parameter.value_items` when `parameter.is_quantized` is truthy. Catch+ignore the AttributeError/RuntimeError as a fallback.

### W2-10. Arrangement-clip envelopes broken for non-mixer kinds; `mixer_volume` rejected on arrangement clips  ·  P0  ·  NEW

Two distinct failures on arrangement clip envelopes against Live 12.4:
1. `write_envelope(target_kind='mixer_volume', track_index=1, location='arrangement', clip_index=1, breakpoints=[...])` → `RuntimeError: Not a session clip or parameter belongs to another track.` Live's `Clip.create_automation_envelope(target)` rejects the mixer-volume target when called on an arrangement clip. Chunk D's research assumed clip-scoped envelopes worked for both session AND arrangement — empirically they don't for `mixer_volume`.
2. `write_envelope(target_kind='clip_pitch_bend', track_index=1, location='arrangement', clip_index=1, breakpoints=[...])` → `ArgumentError: Python argument types in Clip.clear_envelope(Clip, tuple) did not match C++ signature: clear_envelope(TPyHandle<AClip>, TPyHandle<ATimeableValue>)`. The handler is passing a tuple to `clear_envelope` where Live expects a parameter object. The clip_pitch_bend target resolution probably returns a tuple `(controller_id, ...)` rather than a Parameter; clear_envelope can't accept that. Handler bug, not a Live API gap.

`write_envelope(target_kind='mixer_volume', location='session', ...)` DOES work (verified). So the breakage is specific to arrangement-side clip envelopes.

Implications for falling-walking: both of its mixer_volume envelopes (Verse Pad swell, Synth Bass chorus duck) must route through SESSION clips, not arrangement clips. That contradicts the natural-DB-mapping but matches what Live's API actually allows. Update the planner-side routing accordingly.

Fix shape:
- (1) `mixer_volume` on arrangement: surface a teaching error pointing the user at the session-clip workaround. Update gaps.md.
- (2) `clip_pitch_bend` arrangement: investigate the target-resolution helper; whatever returns the tuple needs to instead resolve to a `TimeableValue` (the MIDI controller parameter object). Probably need `clip.automation_parameters` instead of building a tuple.

### W2-1. MCP tool wrapper drops top-level kwargs — every parameterized action is unreachable in its documented form  ·  P0  ·  NEW  ·  FIXED-VERIFIED

The FastMCP wrapper registered in `hallucinote_mcp/src/hallucinote_mcp/server.py::_register_tool` has signature `wrapper(action: str, params: dict | None = None)`. FastMCP introspects this signature to build the tool's JSONSchema, so the surface Claude Code sees is `{action: str, params?: object}`. Every action parameter (`bpm`, `bar`, `track_index`, `name`, etc.) must be passed *nested* inside `params={...}`.

But every help string, example, and tip in `actions/*.py` and `resources/guides/*.md` documents the calling convention as **top-level kwargs**:

```python
ableton_session(action='set_tempo', bpm=132.0)           # what docs promise
ableton_session(action='set_tempo', params={'bpm': 132}) # what actually works
```

Empirical confirmation: `bpm=132` returned `missing required param(s) ... bpm`; `params={"bpm": 132.0}` returned `ok: true`.

**Impact**: every agent (and every Claude Code session) that tries to use the documented call shape silently fails with a confusing "missing required param" error. Net effect: the entire 10-tool surface is functionally unreachable until the agent figures out the nesting convention. This is THE root cause behind the "every push test gets stuck on the first call" pain.

**Fix shape**: flatten the wrapper so per-action params appear as top-level kwargs in the JSONSchema. Two implementations to consider:
1. Per-action sub-tools (one registered tool per action × per category) — explodes tool count, defeats the 10-tool design.
2. Custom JSONSchema construction on the single tool — FastMCP allows passing an explicit `inputSchema`; we generate `{action: {enum: [...]}, ...flatten(union of all action params)}` per tool. Validation stays inside the dispatcher.
3. Variadic wrapper `wrapper(action: str, **kwargs)` — relies on FastMCP introspecting `**kwargs` correctly.

Recommend (2) — produces a discoverable schema that matches the docs and keeps the 10-tool surface.

**Files**: `server.py::_register_tool`, possibly new `_build_input_schema(tool_name)` helper, plus tests in `tests/unit/test_server.py`.

**Resolution** (uncommitted, pending real-Live validation):
- `server.py::_register_tool` now synthesizes each wrapper's signature from
  the registry — `(action, **all_action_params_keyword_only_optional)`.
  FastMCP introspects the signature to build the JSONSchema, so the wire
  shape Claude Code sees matches every example string. `_collect_tool_params`
  enforces no type collisions across actions on the same tool.
- `tests/unit/test_server.py`: 6 new wire-level regressions —
  schema-shape (`params` envelope must not exist; every action's params at
  top level), end-to-end FastMCP call dispatch (flat kwargs land in
  the forwarded Request's `params`), optional-kwarg dropping, no-param
  help action via FastMCP, and the collision detection in
  `_collect_tool_params`.
- `tests/conftest.py`: preloads `actions` at conftest import so a test
  using `isolated_registry` early in collection order can't permanently
  empty the production registry.
- All 925 tests pass (919 baseline + 6 new). Diff: +263 / -11 across
  three files.

**Real-Live validation** (2026-05-18, post-`/mcp` reconnect):
- `ableton_session(action='set_tempo', bpm=132)` → `ok:true`. (flat kwarg accepted)
- `ableton_session(action='set_signature', numerator=4, denominator=4)` → `ok:true, result={numerator:4, denominator:4}`.
- `ableton_session(action='seek', bar=3, beat=0)` → `ok:true, result={bar:3, beat:0.0, song_time:8.0}`. (multi-kwarg incl. optional `beat`)
- `ableton_track(action='info', track_index=1)` → `ok:true` with full track info.

Wire shape now matches every help string and resource guide example.
Closing W2-1.

---

