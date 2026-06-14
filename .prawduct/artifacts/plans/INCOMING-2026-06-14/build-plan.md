# INCOMING-2026-06-14 — Build Plan (swell-dogfood incoming bugs)

Branch: `fix/incoming-bugs-2026-06-14`. Critic mode: **cumulative** (base `develop`).

Four incoming bugs from the 2026-06-14 swell mix dogfood, all "blocking songwriters."
Parallel verify-first scoping (4 read-only agents) collapsed the set:

- **Bug 2 (install `--plugins-dir`) — ALREADY FIXED by INS-3W8P (v0.9.7).** The server
  self-reports `package_root` via `ableton://server/info`; the install vendors from that
  root, covering marketplace AND `--plugins-dir` by construction. The bug's `CLAUDE_PLUGIN_ROOT`
  fix is the *rejected* alternative (`project-state.yaml:307`). → close-out, no code.
- **Bug 4 (params_dialed display values) — mostly already works.** `{"value":"180 Hz"}`
  flows `_replay_devices`→`value_display`→push branch-2→live `set_parameter` inversion
  (DPP-7H2K) end-to-end. Gap = docs + a defensive warn for the bare-float trap.

## Requirements Confidence: **High** (firsthand seam scoping, file:line cited per chunk)

## Fingerprint note
`_FINGERPRINT_PATHS` = wire.py/schema.py/dispatcher.py/`actions/`/`handlers/`/`remote_script/`.
Chunks touching `handlers/` or `actions/` (4, 5) **flip the fingerprint → re-vendor required**.
Chunks 1/2/3/6 are engine/docs/skill only → **no flip, immediately effective**.

---

### Chunk 1: BUG4 params_dialed authoring — docs + bare-float warn (engine, no-flip)
- **Problem:** static device-param authoring lives in snapshot `params_dialed`, undocumented;
  authors don't know `{"value":"180 Hz"}` already works (push emits `value_display`, the live
  setter inverts the log curve via DPP-7H2K). A bare float `{"value":0.71}` with no `normalized`
  silently stores as the display string `"0.71"` and mis-routes at push.
- **Done when:** (1) `docs/snapshot-schema.md` `params_dialed` bullet expanded — purpose (sparse,
  non-default static params), entry shape (`value` display-or-normalized / `normalized` / `value_items`),
  the snapshot→`device_parameters`→push flow, and the "prefer a display string for continuous params;
  the live setter inverts" guidance with a worked EQ example. (2) `capture.py` `_replay_devices` warns
  when `value` is a bare float/int AND `normalized` is absent (the mis-route trap), pointing at
  `"normalized"`. (3) Tests: display-string pass-through; bare-float-no-normalized warns.

### Chunk 2: BUG1A analyzer-aware push device-matching (engine, no-flip) — ROOT CAUSE
- **Problem:** after a render leaves a trailing `HallucinoteAnalyzer`, push device-matching is
  position-equality, so a new authored device at DB-position p has no match (analyzer occupies the
  slot) → push appends it after the analyzer + emits false drift notes. Songwriters hand-delete ~29
  analyzers before a scoped device push.
- **Done when:** `sync/push/probe.py` `_match_devices_for_linked_parents` filters `is_analyzer_device`
  (already imported) out of the LIVE chain before building `live_by_pos`, so a trailing analyzer never
  shifts the position match (and false drift notes vanish). Test in `tests/unit/sync/test_push_devices.py`:
  DB `[EQ, Comp]` vs Live `[EQ, Comp, Analyzer]` → both link at correct positions, no drift note.

### Chunk 3: BUG3 skill doc — expected 60s wrapper timeout + poll (skill, no-flip)
- **Problem:** `render`/`analyze` complete server-side but the Claude Code MCP wrapper returns a red
  "timed out after 60s" — reads as a hard failure; no completion signal.
- **Done when:** `skills/mix-review/SKILL.md` "Refreshing the analysis" gains a note: the 60s wrapper
  timeout is EXPECTED and harmless; the job continues server-side; poll `<captures_dir>` for
  `manifest.json` (render) / `songs/<slug>/analysis/` for a new JSON (analyze). (Mirrors ableton-push's
  `.last-push-state.json` polling pattern.)

### Chunk 4: BUG1B bulk `ableton_render(action='strip')` (MCP, FLIP)
- **Problem:** no inverse of `ensure_loaded` — to clean a set for a deterministic push / clean save,
  delete ~29 analyzers by hand, one MCP call each.
- **Done when:** new `strip` action in `actions/render.py` + `strip_handler` in `handlers/render.py`,
  mirroring `ensure_loaded` — walk `_plan_surfaces()`, `_find_analyzer_index()` per surface, delete via
  `device_handlers.delete_handler` in a `run_on_main` bout with the inter-surface yield; return
  `{stripped_count, instances:[...]}`. Tests in `test_actions_render.py` + the per-surface delete in
  `test_analyzer_setup.py` (pure planner part). **Re-vendor required.**

### Chunk 5: BUG3 status.json heartbeat (MCP, FLIP)
- **Problem:** no mid-run completion signal → fragile `until [ -f manifest.json ]` dir-watch.
- **Done when:** `handlers/render.py` writes `<captures_dir>/status.json` (`{state:running,...}` during
  the wait loop via an optional writer seam, `{state:done|error}` at the end); `handlers/analysis.py`
  writes `<analysis_dir>/status.json` `{state:running}` before `analyze_mix` and `{state:done,report_path}`
  after. Tests in `test_actions_render.py` + `test_handlers_analysis.py`. **Re-vendor required (one
  re-vendor covers Chunks 4+5).**

### Chunk 6: BUG2 + backlog/incoming-bugs close-out (no code)
- Bug 2 already fixed by INS-3W8P → archive the incoming-bugs report. Archive the other 3 reports as
  resolved-by-this-cluster. File any deferred residual (full async render) as backlog.

## Status
- [ ] Chunk 1: BUG4 params_dialed authoring docs + warn
- [ ] Chunk 2: BUG1A analyzer-aware push matching
- [ ] Chunk 3: BUG3 skill doc expected-timeout
- [ ] Chunk 4: BUG1B bulk strip action
- [ ] Chunk 5: BUG3 status.json heartbeat
- [ ] Chunk 6: BUG2 + incoming-bugs close-out
