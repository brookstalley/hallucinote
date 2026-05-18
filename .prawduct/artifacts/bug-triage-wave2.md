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

## Findings (chronological — append as they appear)

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

