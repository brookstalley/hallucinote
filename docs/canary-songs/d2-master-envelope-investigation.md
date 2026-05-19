# D2 — Master envelope LOM investigation

**Date**: 2026-05-19
**Live version probed**: 12.4 (running session at investigation time)
**Agent**: D2 master envelope probe (read-only)
**Branch**: `feat/wave-0-reliability-harness`

## Verdict

**(c) no path — ship loud refusal.** Live 12.4's LOM offers no route to author master-strip volume/pan/sends envelopes from MCP:

- No `create_automation_envelope` exists on song, master_track, mixer_device, or DeviceParameter — only on `Clip`.
- Master CANNOT host arrangement clips (`song.master_track.arrangement_clips` raises `"Main, Group and Return Tracks have no arrangement clips"`) and its `clip_slots` vector is empty by Live's design.
- Therefore the clip-routed envelope mechanism that powers `mixer_volume` / `mixer_pan` / `device_parameter` for regular tracks is categorically inapplicable to master.
- The "Utility on master" workaround (Angle 2) is also dead: even if we shipped master-strip device-load support, the envelope on the Utility's Gain parameter would STILL need a containing session clip on master — which is the same structural block.
- The third-party "Automate Master Track Volume" device referenced in the Ableton Drummer blog is a Max-for-Live device that lives on a **regular** track and exposes a parameter whose value is wired into master volume; the automation breakpoints live on the regular track's clip envelope, not on master. This is a UI/composition pattern, not an MCP-shippable mechanism.

W10-I should ship authoring-time validation + a teaching refusal pointing the user at the sub-bus pattern.

## Angle 1: Direct master_track LOM

Probed via `ableton_session(action='introspect', ...)`. All probes are read-only — no song mutation.

### `song.master_track` — dir surface

```
ableton_session(action='introspect', target='song.master_track', what='dir')
```

Relevant members (filtered from full dir):

- **Clip surface**: `arrangement_clips`, `clip_slots`, `create_audio_clip`, `create_midi_clip`, `delete_clip`, `duplicate_clip_slot`, `duplicate_clip_to_arrangement`. Method *names* exist (Track is the shared base class), but calling `arrangement_clips` raises:
  ```
  RuntimeError: Main, Group and Return Tracks have no arrangement clips
  ```
  And `clip_slots[0]` raises `Index out of range` — the vector is genuinely empty, not lazily populated.
- **Device surface**: `devices` (empty vector on a fresh master), `insert_device`, `delete_device`, `duplicate_device`. Master CAN host devices.
- **Mixer**: `mixer_device` (probed below).
- **No envelope-creation symbols.** No `create_automation_envelope`, no `automation_envelopes`, no `envelope_for_*`, no `add_envelope`, no `has_envelopes` on the master_track itself.

### `song.master_track.mixer_device` — dir surface

```
ableton_session(action='introspect', target='song.master_track.mixer_device', what='dir')
```

Members: `crossfader`, `crossfade_assign`, `crossfade_assignments`, `cue_volume`, `left_split_stereo`, `panning`, `panning_mode`, `panning_modes`, `right_split_stereo`, `sends`, `song_tempo`, `track_activator`, `volume`. (Plus listeners.)

No envelope/automation-creation methods. `song_tempo` is interesting and orthogonal — it's the master's own DeviceParameter mirror of `song.tempo`, which still has no envelope path (W6-F already proved this for tempo).

### `song.master_track.mixer_device.volume` — dir surface

```
ableton_session(action='introspect', target='song.master_track.mixer_device.volume', what='dir')
```

Full member list: `add_automation_state_listener`, `add_display_value_listener`, `add_name_listener`, `add_state_listener`, `add_value_listener`, `automation_state`, `automation_state_has_listener`, `begin_gesture`, `canonical_parent`, `default_value`, `display_value`, `display_value_has_listener`, `end_gesture`, `is_enabled`, `is_quantized`, `max`, `min`, `name`, `name_has_listener`, `original_name`, `re_enable_automation`, `remove_*_listener` (×5), `short_value_items`, `state`, `state_has_listener`, `str_for_value`, `value`, `value_has_listener`, `value_items`.

Important: `automation_state` and `re_enable_automation` are present, but they are **read/observe** the existence of automation and **re-enable** an already-disarmed envelope respectively. **Neither creates an envelope.** This matches the existing automation-handler doc at `hallucinote_mcp/src/hallucinote_mcp/handlers/automation.py:1-100` — Live 12 has no parameter-level `create_automation_envelope` for ANY track, master or otherwise.

### `song.master_track.view` — dir surface

No envelope methods: `device_insert_mode`, `is_collapsed`, `select_instrument`, `selected_device`. (Plus listeners.)

### `song` (root) — dir surface

No `create_automation_envelope` at song level either. `re_enable_automation` exists on song (re-arms previously-suspended envelopes globally) but does not create.

### Cross-check against Live 12's `LomTypes.pyc`

```
strings /Applications/Ableton\ Live\ 12\ Suite.app/Contents/App-Resources/MIDI\ Remote\ Scripts/_MxDCore/LomTypes.pyc | grep -i envelope
```

Yields only: `clear_all_envelopes`, `clear_envelope`, `has_envelopes`, `hide_envelope`, `select_envelope_parameter`, `show_envelope`, `beats_transient_envelope`, `complex_pro_envelope`. The string `create_automation_envelope` does NOT appear in `LomTypes.pyc` — it's defined on the `Clip` class directly, outside the M4L LOM whitelist. This is consistent with the existing W6 finding and the empirical introspection above.

### Conclusion for Angle 1

There is no LOM symbol on master_track (or any ancestor) that creates envelopes. The handler's existing line of reasoning (`automation.py:14-22`) generalizes correctly: clip-routed creation is the only path, and master can't host clips. Investigation closes here for Angle 1.

## Angle 2: Utility-on-master feasibility

### Can we load a Utility on master?

Today: **no, not via MCP.** `ableton_device(action='load')` requires `track_index` (1-based regular track) OR `return_index` — there is no `master` channel. `song.master_track` has `insert_device` exposed (verified via introspect), so the underlying Live API supports it; the MCP surface just doesn't address master. Adding the surface is a separate piece of work (~50-100 LoC plus tests in `ableton_device` to accept `track_kind='master'` and route to `song.master_track.insert_device`).

### If we DID add a Utility on master — would envelopes work?

**No.** Trace through `src/hallucinote/sync/push.py:1464-1573` (`_emit_device_parameter_envelope`):

1. Line 1481-1483: resolve `device_at` via `Q.get_ableton_link(... db_kind="device", db_id=device_id)`. Solvable if device-load were extended to master.
2. Line 1484-1496: look up `chain_row` → `parent_track_id`. The chain's parent would be master's track id.
3. Line 1512-1515: `parent_at = Q.get_ableton_link(... db_kind="track", db_id=master_track_id)`. **Returns None.** Master is never linked (see `push.py:211-223` — the tracks phase explicitly skips master because it exists implicitly in every Live set). Even if we synthesized a sentinel "master" link, the next step would still fail:
4. Line 1524-1538: `_resolve_envelope_session_clip(... target_track_id=master_track_id, ...)`. Looks for a session clip on master that COVERS the envelope's beat range. Master has no `clip_slots`. The DB shouldn't even let an arrangement_clip be placed on master (and if it does, that's a separate DB validation gap). Result: `placement is None` → warn + skip.
5. Even if we shipped a "synthesize a covering clip on master" detour, **step 4's LOM check at push time would fail** — Live rejects clip creation on master with the same `"Main, Group and Return Tracks have no arrangement clips"` error.

So the Utility-on-master pattern collapses for the same reason direct master automation does: **no containing clip is reachable on master, and Live's `create_automation_envelope` only lives on Clip.**

### Rough size estimate IF we wanted to attempt it anyway

Not recommended, but for completeness:

- MCP: `ableton_device(action='load')` master support (~80 LoC + tests)
- DB: `devices` allowed on master chain (already implicit in cross-song reuse; may need validation pass)
- Planner: special-case master device_parameter envelope to fail-loud with helpful message (~30 LoC) — but this is the SAME UX as Angle 3's loud-refusal, so the device-load work is wasted.

**UX implication if we shipped Utility-on-master ANYWAY (via M4L "Automate Master Track Volume" pattern):** The user would have to author their song with a hidden sub-bus or an M4L mirror device, and our LLM-generated songs would need to know to do this. That's an authoring-layer concern, not an MCP gap — better surfaced as a teaching error pointing at the workaround than implemented as a planner branch.

## Angle 3: Wider LOM exploration

Not strictly needed — Angles 1+2 are conclusive — but the existing W6 investigation at `hallucinote_mcp/src/hallucinote_mcp/handlers/automation.py:14-22` is corroborated by:

- **Web check** ([Structure Void Live 10 API XML](https://structure-void.com/PythonLiveAPI_documentation/Live10.0.1.xml), [Cycling74 LOM Max 8 docs](https://docs.cycling74.com/legacy/max8/vignettes/live_object_model)): no `create_automation_envelope` on MasterTrack or DeviceParameter; `automation_envelope()` getter exists on Clip only.
- **[Ableton Drummer — Automate Master Track Volume](https://blog.abletondrummer.com/automate-master-track-volume-in-ableton/)**: documents the third-party M4L workaround (a regular-track device that mirrors master volume). Confirms the structural gap exists in Live's GUI too — master volume isn't directly automatable from clip envelopes; the M4L device is the canonical sidestep.
- **[Ableton Drummer — Master Track Effects Automation](https://blog.abletondrummer.com/master-track-effects-automation-in-ableton/)**: master DEVICE parameters (EQ on master, etc.) are automatable IN LIVE'S UI via arrangement-view track lanes — but the LOM doesn't expose that lane as a writable envelope. The UI uses internal arrangement-lane envelopes that aren't reachable from Python.

No new path found.

## Recommendation

### W10-I scope (formerly D2)

**Ship loud refusal at planner time.** Concrete plan:

1. **Validation in `_emit_mixer_envelope` and `_emit_device_parameter_envelope`** (`src/hallucinote/sync/push.py:1576-1648` and `:1464-1573`): when the envelope's `target_track_id` resolves to a row with `kind='master'`, do NOT emit a session-clip lookup; instead, emit a structured `plan.error(...)` (or whatever the planner's hard-fail mechanism is — currently `plan.warn`) with:
   - The envelope id + target_kind
   - A clear message: `"Master-strip envelopes are not supported: Live 12.4's LOM has no envelope-creation path for master volume/pan/sends/devices. Workarounds: (1) route the affected sources to a sub-bus group track and automate the group's volume, or (2) use the Max-for-Live 'Automate Master Track Volume' device on a hidden audio track (out-of-band of Hallucinote MCP)."`
2. **Authoring-time validation** (DB write path, if applicable): reject envelopes targeting master at the mutator layer too, so they never enter the DB. This is the cleanest enforcement — invalid state can't exist.
3. **`hallucinote_mcp/src/hallucinote_mcp/handlers/automation.py` doc update**: extend the existing block-comment at lines 14-22 with the master-specific finding (Angle 1 + Angle 2 from this doc), so the next investigator doesn't re-walk this ground.
4. **Update `ableton://guides/gaps` resource**: add a "Master-strip automation" entry citing this investigation.

### Critic mark

**Yes** — even though the change is small, it's user-visible behavior (refusal vs. silent drop) and it locks in a non-support contract. Critic should validate (a) the refusal message is teaching-quality, (b) the validation fires at the right layer (mutator preferred over planner), (c) the gap is documented in BOTH `automation.py` AND the gaps guide.

### Approximate size

- **~150-250 LoC** across `push.py` (refusal branches), `mutators.py` (DB-side validation, ~30 LoC), `automation.py` docstring extension (~20 LoC), `guides/gaps` (~20 lines), tests (~80 LoC: one DB-side reject test, two planner-side teaching-error tests for mixer_volume + device_parameter on master).
- **1 chunk** (no architectural lock-in, no decision research needed beyond this doc).

### Open questions for user sign-off

1. **DB-layer reject vs. planner-layer reject?** Recommendation: BOTH (DB rejects writes, planner provides defense-in-depth + teaching messages on legacy data). Sign-off on the dual-layer approach.
2. **Should we also surface this in the DB schema as a CHECK constraint?** `CHECK (target_kind NOT IN ('mixer_volume','mixer_pan','send_level','device_parameter') OR target_track.kind != 'master')` — clean but cross-table CHECKs aren't sqlite-native. Probably skip — mutator-layer validation is sufficient.
3. **M4L "Automate Master Track Volume" workaround in the refusal message — link it or omit?** Recommendation: mention by name, don't link (link rot is real). The user can search.
4. **Naming**: keep this as W10-I (renamed from D2) or fold into an existing wave? Triage.md line 171 calls it W10-F. Reconcile the numbering before starting.
