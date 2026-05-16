# Backlog — Songwright

<!-- Work discovered during sessions but out of current scope.
     Add items at the top. Each is a bullet with source marker:
     (builder), (critic), (reflection), or (migrated).
     Review with /janitor or when planning new work. -->

- **MCP tool-surface cleanup.** The MCP fork has grown a fan of narrow per-property tools (`set_track_volume`, `set_track_panning`, `set_track_mute`, `set_track_solo`, `set_track_arm`, `set_track_color`, `set_master_volume`, `set_master_panning`, ...). Many of these should collapse into actions on existing tools — e.g. one `set_track_property(track_index, property, value)` covers mute/solo/arm/color and probably volume/pan too; one `set_master_property` covers master strip. Reduces tool count, makes the alias table in `mcp_names.py` smaller, makes `apply_push_results._ACK_ONLY_KINDS` smaller. Plan a coordinated rename/consolidation pass in the MCP fork; do NOT block chunk 4 on it. The current planner can emit either shape — the consolidation just collapses canonical names. (builder, chunk-4 setup)
- Capture extension for nested rack chains. The chunk-4 snapshot has racks (`InstrumentGroupDevice`, `DrumGroupDevice`) flagged with `_note: "Rack — internal chain instruments not captured"`. MCP gap #17b breaks `get_device_parameters`, so deep probe is blocked. Once #17b lands, extend `tools/capture.py` + `compile_snapshot` to recurse into rack chains and populate `device_chains` with `parent_rack_device_id`. (builder, chunk-4 setup)
- Master-strip device chains. `device_chains.parent_track_id` accepts the `kind='master'` row, but `plan_push_devices` skips `kind='master'` and `kind='return'` tracks today. Master devices (master limiter, master EQ) are common in real mixes — needs a master-specific push path (no track_index, reaches the master strip directly) and an MCP gap entry. falling-walking has no master devices today, so this is non-blocking. (builder, chunk 4a)
- `tracks.kind='return'` is a reserved value in the CHECK constraint but unused — real returns live in the `returns` table. Either drop `'return'` from `TRACK_KINDS` + the schema CHECK so misuse becomes an integrity error, or keep the reservation and document it more loudly. The `plan_push_mix` defensive skip for `kind='return'` rows is the only code path that would fire today. (critic, chunk 3)
- Enforce 1-based bar convention. Add CHECK `start_bar >= 1.0` (and `position_bar >= 1.0`) on `sections`/`tempo_map`/`time_signature_map`/`cue_points`, or a runtime guard in `sync.push._split_bar` that raises on `bar_pos < 1.0`. Today the convention is documented in `schema.sql` and `mcp-requirements.md` line 369 but not enforced — `_split_bar(0.0, ...)` returns `(0, 0.0)` which is an invalid Live position. (critic)
- Standardize `tests/test_score_extensions.py` fixtures on 1-based bars. Several tests use `start_bar=0.0` / `position_bar=0.0` which conflicts with the 1-based convention falling-walking now follows. Either land the CHECK above (forces the fix) or update the fixtures by hand. (critic)
- Audio clips: clip kind discriminator, file references, warp metadata, warp markers. Deferred from V1. (migrated)
- Track routing: sidechain, parallel busses, input/output routing config. Schema + sync work. (migrated)
- Group tracks (`tracks.parent_track_id` + Live group semantics). (migrated)
- Pull-side sync (Ableton → DB): per-domain read + diff + apply, gated on MCP read capability per domain. Wave 3. (migrated)
- Event replay function (`replay(events) → state`) and merge tooling. Required for cross-DB event-stream merges between collaborators; only useful after the event-store flip. (migrated)
- Post-hoc event annotation (`event_annotations` table) for narrative on-the-fly addition to history. (migrated)
- Real-time concurrent editing / cloud DB migration. Out of foreseeable scope; the mutator-discipline + storage abstraction already keeps the door open. (migrated)
- Song tests (on-demand layer): DB consistency + mix hygiene + audio/spectral. Land per-chunk as appetite allows; not gating any chunk's completion. (migrated)
- README out of date: still describes the legacy `gen_notes.py`-only world; needs updating to point at `src/songwright/` and link `docs/VISION.md`. (reflection)
- `db/connection.py` autocommit (`isolation_level=None`) makes `with conn:` a no-op — `replace_clip_notes` and `apply_push_results` are not actually atomic despite the comments claiming they are. Fix before any production-style work; add an atomicity-under-mid-fault test. (reflection)
- `pytest-xdist` is referenced in `tests/conftest.py` but not installed; every test run emits `PytestUnknownMarkWarning` and the `pytest -n0` form fails. Either install xdist or guard the marker code. (reflection)
- `boundary-patterns.md` is still the unfilled template; the DB schema and the MCP tool surface are the two real boundaries and both deserve naming. (reflection)
