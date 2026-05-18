# Build Plan — Wave SD: Sound-Design Round-Trip

**Wave goal.** Close the seven gaps identified in the 2026-05-17 sound-design audit so that LLM-driven patch discovery, parameter tweaks, and rack-internal work round-trip cleanly between Ableton and the Hallucinote DB. The "find a cool pad and play atmospheric stuff" → "I nudged the filter in Ableton, please don't lose it" loop closes.

**Requirements Confidence: Medium.** The seven gaps are concretely identified in the audit and `.prawduct/backlog.md`. What's *uncertain*: (a) whether Live's Remote Script exposes per-target-family envelope reads for all seven `target_kind` values (SD-5 may discover Live-API blockers); (b) whether `nested rack chain probe` ABI is uniform across `DrumGroupDevice` / `InstrumentGroupDevice` / `AudioEffectGroupDevice` (SD-4 may need per-class branches); (c) whether preset URIs returned by `ableton_device(action='list')` are stable across Live sessions (SD-3 round-trip assumes they are). Each chunk's "Investigate first" step closes its own confidence gap before locking implementation.

**Scope.** Schema + sync-layer additions in `src/hallucinote/` and MCP additions in `hallucinote_mcp/` to close gaps #1–#7 from the audit. **Out of scope:** quantize/groove module (separate backlog item), audio render/analysis, master-strip device chains (separate backlog item), tempo/signature envelope automation (Live-API blocked per backlog).

**Branching.** Wave branch `feature/wave-sd-sound-design`, cut from `develop`. One PR per chunk to `develop` (per `project-preferences.md` gitflow). User triggers `/pr` — automatic PR creation is OFF.

**Audit reference.** This plan addresses the seven gaps enumerated in the 2026-05-17 session conversation. The backlog entries that pre-track these gaps remain the authoritative source for context (`.prawduct/backlog.md` lines covering MCP envelope read surface, nested rack chain probe + push, device-parameter pull sync-layer).

---

## Status

**Wave SD — not started.** No chunk has begun. Pending the user's pivot back from Ableton testing.

**Context line.** Plan written 2026-05-17 in the same session as the audit. User is currently testing existing capabilities in Ableton; will return to this plan afterward. No commits made.

---

## SD-1 — Schema cleanups: `is_active` + enum parameter persistence

**Addresses gaps:** #6 (is_active drops on pull), #2 (enum parameter values not storable).

**Why first.** Both are small structural schema lifts that gate the device-parameter pull in SD-2. Bundling them avoids two schema migrations in two chunks.

**Requirements Confidence: High.** Both surfaces are well-understood — `is_active` is already returned by `ableton_device(action='list')` and dropped silently on apply; enum params have value_items in `get_parameters(detail='full')` and the push planner already detects + skips them with a warning. Schema changes are localized.

**Critic mode:** `chunk`.

### Investigate first

- Confirm the shape of `value_items` in `ableton_device(action='get_parameters', detail='full')` for enum params: is it always `list[str]`? Is the current value addressable by string match or by index? Decides whether `device_parameters` gets a `value_enum TEXT` column or an `enum_index INTEGER`.
- Confirm there is no existing `is_active` column on `devices` (grep the schema).
- Identify all push/pull/apply callsites that touch `devices` rows and `device_parameters` rows so the schema changes propagate atomically.

### Scope

- **Schema.** Add `devices.is_active BOOLEAN NOT NULL DEFAULT 1`. Add `device_parameters.value_enum TEXT` (nullable; mutually exclusive with `value_normalized` via CHECK constraint). Migration tool follows the `tools/migrate_arrangement_clip.py` pattern (single-transaction, idempotent, schema-probe first).
- **Mutators.** Extend `create_device` to accept `is_active`; add `set_device_active(device_id, is_active, ...)`. Extend `set_device_parameter` to accept `value_enum` as an alternative to `value_normalized`. Add CHECK constraint validation in the mutator (one or the other, not both).
- **Push planner.** Stop skipping enum params with a warning — emit `ableton_device(action='set_parameter', value_type='enum', value=...)` using `value_enum`. Push `is_active` via `ableton_device(action='enable'|'disable')` when it differs from Ableton state (will be exercised once SD-2's pull lands).
- **Pull apply.** Wire `is_active` through `_apply_devices_for_parent` to call `set_device_active` on diff.
- **Tests.** Mutator tests for both columns; push-planner test for enum emission and active toggling; CHECK-constraint test for mutex.

### Done when

- [ ] `devices.is_active` and `device_parameters.value_enum` exist in schema; migration tool runs idempotently against falling-walking's DB.
- [ ] Mutators enforce the value_normalized/value_enum mutex.
- [ ] `plan_push_devices` emits enum set_parameter calls for enum params (no more skip-with-warning).
- [ ] Pull apply round-trips `is_active`.
- [ ] Full test suite passes; new tests cover mutex, push emission, pull apply.
- [ ] `/critic chunk` review clean.
- [ ] Status section updated, chunk reflection appended.

---

## SD-2 — Device-parameter pull

**Addresses gap:** #1 (parameter values don't flow Ableton → DB).

**Why second.** This is the biggest UX unlock — manual Ableton tweaks survive sync. Depends on SD-1's enum schema so the pull doesn't silently drop discrete params.

**Requirements Confidence: High.** Backlog entry "Sync-layer not-yet-built: device-parameter pull" explicitly confirms the MCP side works (`ableton_device(action='get_parameters')` is fine in the greenfield server). The shape mirrors the existing `plan_pull_devices` / `_apply_devices_for_parent` pattern.

**Critic mode:** `chunk`.

### Investigate first

- Read `plan_pull_devices` + `_apply_devices_for_parent` (`sync/pull.py:246–319, 1276–1420`) end-to-end. Confirm the per-track / per-return / per-master probe loop is the right place to fan out parameter probes (one extra probe per linked device).
- Decide probe granularity: is it acceptable to call `ableton_device(action='get_parameters', detail='summary')` per device per pull, or do we batch? Latency budget vs. round-trip count.
- Confirm `_FLOAT_EPS` jitter tolerance from the existing pull layer applies to `value_normalized` diffing (it should — same kind of float, same display-rounding source).

### Scope

- **Probe.** `plan_pull_device_parameters(conn, session_id) -> PullPlan` emitting `ableton_device(action='get_parameters', detail='full')` per linked device. `detail='full'` because we need `value_items` to round-trip enum names.
- **Normalize.** Convert MCP response shape into a dict keyed by `(device_id, parameter_name)` with `value_normalized` for continuous and `value_enum` for discrete.
- **Apply.** `_apply_device_parameters_for_parent(conn, ...)` diffs against current `device_parameters` rows; calls `set_device_parameter` to upsert; deletes rows for params no longer in the probe. Tolerance: `_FLOAT_EPS` for continuous; exact string match for enum.
- **Wire into pull driver.** `apply_pull_results` learns the new domain; sync-manifest.json gets a new domain entry.
- **Tests.** Unit: planner emits the expected probes; apply diffs correctly (add / update / delete / no-op); enum vs. continuous handling; epsilon tolerance for continuous.
- **Integration smoke.** ableton-pull skill manually verified: tweak a continuous param in Ableton → pull → DB shows new value. Tweak an enum (Filter Type) → pull → `value_enum` updates.

### Done when

- [ ] `plan_pull_device_parameters` exists and is exercised by the ableton-pull skill.
- [ ] `_apply_device_parameters_for_parent` handles add/update/delete cleanly.
- [ ] Continuous + enum round-trip end-to-end against falling-walking.
- [ ] Full test suite passes; new tests cover the planner and apply diff cases.
- [ ] `/critic chunk` review clean.
- [ ] Status section updated, chunk reflection appended.
- [ ] Backlog entry "Sync-layer not-yet-built: device-parameter pull" removed.

---

## SD-3 — Track instrument-URI round-trip + preset listing

**Addresses gaps:** #5 (`tracks.instrument_uri` one-way), #7 (no "list presets for device kind").

**Why bundled.** Both touch the preset-discovery surface and a fresh `tracks.instrument_uri` pull is the natural place to exercise a flatter preset enumeration. Small chunk.

**Requirements Confidence: Medium.** Uncertain whether preset URIs are stable across Live sessions (file-ID-based URIs probably are; query-form URIs may not be). The investigation step nails this down before locking the pull shape.

**Critic mode:** `chunk`.

### Investigate first

- Walk a real `ableton_device(action='list')` response on falling-walking and confirm what shape `preset_uri` takes for: (a) factory Operator preset, (b) user-saved preset, (c) third-party VST patch. Confirm stability across Live restart.
- Confirm `ableton_browser(action='at_path', ...)` can enumerate presets in a single folder cheaply, or whether a deeper tree walk is unavoidable.
- Decide whether a new MCP action is warranted (`ableton_browser(action='list_presets', kind='Operator')`) vs. a documented recipe over existing primitives.

### Scope

- **MCP (optional, decided after investigation).** If the existing primitives require a tree walk that's too verbose for the agent, add `ableton_browser(action='list_presets', kind='Operator')` returning a flat list of `{name, preset_uri, folder_path}` tuples. If the existing `at_path` is sufficient, document the recipe in the relevant prompt instead.
- **Pull.** Extend `plan_pull_devices` (or add `plan_pull_track_instruments`) to capture `tracks.instrument_uri` from the top-level instrument device's `preset_uri`. Wire apply.
- **Push.** Push planner already references `tracks.instrument_uri` during track-create with a deferred-load note; tighten so a *changed* instrument URI on an already-linked track triggers a follow-up `ableton_device(action='load')` call.
- **Tests.** Pull captures instrument_uri changes; push emits load on URI change; if new MCP action added, dispatcher + handler tests in `hallucinote_mcp/tests/`.

### Done when

- [ ] Decision recorded in this chunk's "Investigate first" section: new MCP action or no.
- [ ] `tracks.instrument_uri` round-trips end-to-end: change in Ableton → pull captures it; change in DB → push loads it.
- [ ] If MCP action added, it's listed in the relevant prompt/help surfaces.
- [ ] Full test suite passes.
- [ ] `/critic chunk` review clean.
- [ ] Status section updated, chunk reflection appended.

---

## SD-4 — Nested rack chain probe + push + pull

**Addresses gap:** #3 (devices inside racks invisible to LLM).

**Why fourth.** Large structural lift on both MCP and sync layers. Backlog entry "MCP gap: nested rack chain probe + push" lays out the surface. Independent of SD-1/2/3, so could move earlier if drum-kit work suddenly matters; defaulting to fourth to keep the wave's smaller wins moving first.

**Requirements Confidence: Medium.** The DB already models nested chains (`device_chains.parent_rack_device_id`). The capture/push/pull paths stay flat today. Unknown: whether `DrumGroupDevice`, `InstrumentGroupDevice`, and `AudioEffectGroupDevice` expose chains uniformly through the Remote Script API. The investigation step is non-trivial and may reshape the MCP design.

**Critic mode:** `chunk` (likely promoted to `final` if the chunk grows past ~3 days of work).

### Investigate first

- Confirm Live's `clip_slot.canonical_parent` / `track.devices[i].chains` accessors work the same way for all three rack classes. If they diverge, the MCP `get_device_chains` action needs per-class branches.
- Define chain addressing: positional index? Chain name? Both? The backlog suggests `(track_index, parent_device_index, chain_index)` — confirm uniqueness invariants.
- Decide how nested-nested racks behave (rack inside rack inside rack). Bound the recursion or accept arbitrary depth?

### Scope

- **MCP additions** in `hallucinote_mcp/src/hallucinote_mcp/actions/device.py` + `handlers/device.py`:
  - `ableton_device(action='get_chains', track_index=N, device_index=M)` → list of `{chain_index, chain_name, devices: [{device_index, kind, display_name, is_active, preset_uri}]}`.
  - `ableton_device(action='load_in_rack', track_index=N, parent_device_index=M, chain_index=C, position=P, kind=..., preset_uri=...)`.
  - `ableton_device(action='set_rack_parameter', track_index=N, parent_device_index=M, chain_index=C, device_index=D, parameter_name=..., value=..., value_type=...)`.
- **Sync — capture.** Extend `tools/capture.py` + `compile_snapshot` to recurse into rack chains; populate `device_chains` rows with `parent_rack_device_id` set.
- **Sync — push.** Extend `plan_push_devices` to walk nested chains and emit `load_in_rack` / `set_rack_parameter` calls in the right order (parent rack must be loaded before its chain devices).
- **Sync — pull.** Recursive probe path: for any device whose kind is one of the three rack classes, also probe `get_chains` and recurse. Apply path mirrors the existing flat-chain apply.
- **Tests.** Unit tests for each new MCP action; planner tests for push-into-rack and pull-of-rack; integration smoke against a falling-walking variant that has a drum rack.

### Done when

- [ ] Three new MCP actions land with dispatcher + handler tests.
- [ ] Capture/push/pull all recurse into rack chains.
- [ ] Drum-rack round-trip verified manually against Ableton.
- [ ] Full test suite passes.
- [ ] `/critic chunk` review clean (or `final` if the chunk grows large).
- [ ] Status section updated, chunk reflection appended.
- [ ] Backlog entries "MCP gap: nested rack chain probe + push" and "Capture extension for nested rack chains" removed.

---

## SD-5 — Envelope read surface

**Addresses gap:** #4 (envelope automation cannot be read back from Ableton).

**Why last.** Largest scope — seven `target_kind` families to mirror on the read side (`clip_cc`, `clip_pitch_bend`, `note_expression`, `device_parameter`, `mixer_volume`, `mixer_pan`, `send_level`). Independent of SD-1/2/3/4; placed last because it's a deep-dive on its own.

**Requirements Confidence: Low.** Live's Remote Script API exposure for *reading* envelopes is unverified for all seven families. SD-5 may discover one or more families need agent-side fallbacks or are entirely Live-API-blocked. The investigation step is mandatory and may significantly reshape this chunk.

**Critic mode:** `final` (chunk is large enough that final-mode rigor is warranted; promotes from `chunk` if investigation shrinks the scope dramatically).

### Investigate first

- For each of the seven `target_kind` values, identify the Live Remote Script accessor that returns envelope breakpoints (`device.parameters[i].automation_envelope`? `clip.get_envelope(param)`? Probe the live SDK).
- Map any read-side Live-API gaps to a fallback strategy (agent-side workaround, skip with documented limitation, or block the family entirely).
- Decide whether one unified `ableton_automation(action='get_envelope', target_kind=..., ...)` action mirrors the write side, or whether per-family actions read better.

### Scope

- **MCP.** Add `ableton_automation(action='list_envelopes', ...)` and `ableton_automation(action='get_envelope', target_kind=..., ...)`. Mirror the seven `target_kind` values from the existing write surface unless investigation rules a family out.
- **Sync — pull.** New planner `plan_pull_envelopes(conn, session_id)` emitting list + per-envelope read probes. New apply path that diffs breakpoints (within `_FLOAT_EPS`) and upserts via existing envelope mutators.
- **Tests.** Unit tests for each new MCP action (mock dispatcher); planner test for fan-out; apply tests for add/update/delete/no-op breakpoints; integration smoke against an envelope-rich falling-walking variant.
- **Property tests (Hypothesis).** Round-trip invariant: write envelope → pull → re-write should be a no-op within epsilon. Reuses the `dev`/`ci` profiles from `hallucinote_mcp/tests/unit/test_envelope_properties.py`.

### Done when

- [ ] Investigation report committed: which families are pull-supported, which need agent-side fallback, which are blocked.
- [ ] Supported families round-trip end-to-end.
- [ ] Property test confirms round-trip invariant within `_FLOAT_EPS`.
- [ ] Full test suite passes.
- [ ] `/critic final` review clean.
- [ ] Status section updated, chunk reflection appended.
- [ ] Backlog entry "MCP gap: hallucinote-mcp envelope read surface" removed.

---

## Wave close-out (after SD-5 ships)

- [ ] `develop → main` release PR consolidating Wave SD.
- [ ] Backlog summary line under "Pull-side sync follow-on" updated: all four deferred items either shipped or explicitly re-deferred with rationale.
- [ ] `project-state.yaml` `scope.later` block trimmed for items shipped in this wave.
- [ ] Wave-level reflection synthesized from chunk reflections, added to `.session-reflected`.

---

## Open questions (to revisit before each chunk's "Investigate first")

1. SD-3: are preset URIs returned by Live stable across sessions for all device classes (factory, user-saved, VST)?
2. SD-4: do all three rack classes expose internal chains via a uniform accessor, or do we need per-class branches?
3. SD-5: which of the seven `target_kind` families have a working read accessor in Live's Remote Script? Are any Live-API-blocked?

These do not block writing the plan; they block locking each chunk's implementation shape.
