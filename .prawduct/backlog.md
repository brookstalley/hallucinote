# Backlog — Songwright

<!-- Work discovered during sessions but out of current scope.
     Add items at the top. Each is a bullet with source marker:
     (builder), (critic), (reflection), or (migrated).
     Review with /janitor or when planning new work. -->

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
