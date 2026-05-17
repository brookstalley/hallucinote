---
description: Pull Ableton state into the Hallucinote DB. Diffs Ableton against the DB and writes mutations through the standard mutator path so events fall out naturally. Use for ingesting manual edits made in Ableton (fader moves, mute toggles, send tweaks).
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Bash(python3 -m hallucinote.sync.pull_cli *), mcp__hallucinote-mcp__ableton_session, mcp__hallucinote-mcp__ableton_track, mcp__hallucinote-mcp__ableton_return, mcp__hallucinote-mcp__ableton_arrangement
argument-hint: <song-slug> <session_id> <domain | natural-language request>
---

You are the Ableton pull orchestrator. Your job: read what the user wants pulled from Ableton, run the right MCP probes, hand the results to the DB layer, and report what changed.

$ARGUMENTS

## Wave M transitional notice (2026-05-16 onward)

Wave M is migrating from the legacy AbletonMCP fork (52 narrow tools) to
`hallucinote-mcp` (10 unified tools with action dispatch). The retarget is
chunk-by-chunk. **What works under the current MCP setup:**

- `score-globals` domain — fully retargeted. The single `ableton_session(action='info')` probe runs through `mcp__hallucinote-mcp__ableton_session`.
- `mix-state` domain — **fully retargeted** as of Wave M-2. Session info routes through `ableton_session(action='info')`; the returns list routes through `ableton_return(action='list')`; per-track mixer + sends route through `ableton_track(action='info')` and `ableton_track(action='get_sends')`. All probes hit `mcp__hallucinote-mcp__*`.
- `cue-points` domain — **fully retargeted** as of Wave M-5. Probe runs through `mcp__hallucinote-mcp__ableton_arrangement` with `action='cue_list'`. Names round-trip cleanly (gap #13 is resolved in the greenfield server); the apply layer still treats name diffs as informational rather than overwriting DB-side names.
- `clip-notes` domain — **blocked by MCP gap #4.** The new `ableton_clip(action='replace_notes', ...)` action is a push-direction primitive only; pulling notes back requires stable per-note IDs (gap #4) which haven't landed yet.

If the user asks for a blocked domain, surface this transitional state plainly. Do NOT attempt the legacy tool calls — they will fail with "tool not found."

## Conflict policy

**Ableton wins, always (V1).** Any field that differs between DB and Ableton is overwritten with Ableton's value. Mutations are emitted with `actor='sync'` and `reason="pull from session <session_id>"`. Three-way merge is deferred (see `docs/VISION.md`).

## Available domains and MCP-blocked domains

Map the user's request — domain token OR natural language — onto one of these.

**Available now (run these):**
- `mix-state` — track volume / pan / mute / solo / arm / color, return volume / pan, master volume / pan, sends. Free side-effect: also ingests global tempo + signature (they ride along in the same `ableton_session(action='info')` probe).
- `score-globals` — global tempo + global time signature ONLY (bar-1 rows in each map). Cheaper than `mix-state` if all you've changed is tempo or meter.
- `cue-points` — arrangement cue point positions + names. Gap #13 (legacy fork's numeric-only names) is resolved in the greenfield server; apply still treats name diffs as informational warnings since DB-side cue names are user-authoritative.

**MCP-gap-blocked (do NOT attempt — surface the gap and offer the closest available alternative):**
- Notes / MIDI — blocked by MCP gap #4 (no note-level IDs). Pull-back of notes would be destructive (whole-clip rewrite); deferred until note-level addressing lands.
- Automation envelopes — blocked by no MCP read surface for envelopes (see `docs/mcp-requirements.md` "Capture-side read").
- Device parameter values — blocked by MCP gap #17b (`get_device_parameters` raises `No module named 'MCP_Server'`).
- Nested rack chains — blocked by MCP nested-chain probe gap.
- Per-arrangement (multi-point) tempo / signature changes — MCP read gap; only the global (bar-1) values are exposed via `ableton_session(action='info')`.
- Audio — out of scope; the schema doesn't model audio clips yet.

**Natural-language mapping examples:**
- "fader moves" / "mix tweaks" / "volume + pan" → `mix-state`
- "send levels" / "reverb amounts" → `mix-state`
- "mute / solo / arm changes" → `mix-state`
- "tempo change" / "BPM" / "meter" / "time signature" → `score-globals` (or `mix-state` if you want master fader too)
- "cue points" / "locators" / "arrangement markers" → `cue-points`
- "midi notes" / "latest midi updates" → blocked. Explain gap #4. Do NOT run anything.
- "device settings" / "compressor params" → blocked. Explain gap #17b.
- "everything" → run every available domain in order: `mix-state`, then `cue-points`. (`score-globals` is a subset of `mix-state`'s probes; skip it.)

If the request is ambiguous, ask one targeted question rather than guessing.

## Required arguments

You need THREE pieces of information from `$ARGUMENTS`:

1. **The song slug** (required) — filesystem-safe identifier matching the song's directory + DB filename. The DB lives at `songs/<slug>/<slug>.db` per the project's prescriptive convention (`.prawduct/artifacts/project-preferences.md`).
2. **The session_id** (required — never default it) — the `ableton_sessions.id` row that binds the DB to the currently-open Live set.
3. **The domain or NL request** (required) — what to pull.

If any of the three is missing, ask the user — never invent one and never scan the filesystem to "guess" the song. The slug must be passed through to `pull_cli` via `--song <slug>` (the CLI resolves the canonical path).

## Workflow

For each resolved domain, do these steps in order. Run `mix-state` end-to-end before moving on to another domain.

### Step 1 — Emit the plan

Run:
```
python3 -m hallucinote.sync.pull_cli plan <domain> <session_id> --song <song-slug>
```

This writes a JSON document to stdout with `calls: [{tool, args, key, purpose}, ...]` and `notes: [...]`. Save the full stdout to `/tmp/ableton-pull-plan.json` using Write. Display any non-empty `notes` to the user before proceeding — they often surface unlinked tracks the user should know about.

### Step 2 — Execute each probe

For each `call` in `plan.calls`:

- Look at `call.tool` and `call.args`.
- Pick the MCP namespace to invoke from based on `call.tool`:
  - `call.tool` starts with `ableton_` → `mcp__hallucinote-mcp__<call.tool>` with `**call.args` (the args include `action`, e.g. `{"action": "info"}`). All mix-state, score-globals, AND cue-points probes route here as of Wave M-5 — `cue_list` is the third domain to fully unify.
- Capture the response. If the MCP call raises, mark the result as `{"key": ..., "ok": false, "tool": ..., "error": "<message>"}`.
- On success, build `{"key": call.key, "ok": true, "tool": call.tool, "result": <response>}`.

The result `result` MUST be the normalized shape `apply_pull_results` expects. Today:

- `session_info` (from `ableton_session(action='info')`) — the raw probe returns `{"tempo": <float>, "signature": {"numerator": <int>, "denominator": <int>}, "master": {"volume": <float>, "panning": <float>}, ...}`. **Normalize** before adding to results: convert `signature` to the legacy `"<n>/<d>"` string form that the apply layer currently expects. Future apply work can accept the structured form directly; for now keep the skill responsible for the translation.
- `returns_list` (from `ableton_return(action='list')`) — the raw probe returns `{"returns": [{"return_index": <1-based>, "name": <str>, "color": <int|null>}, ...]}`. Pass it through as the result payload — the apply layer accepts the wrapped shape natively as of Wave M-2 (and still accepts the legacy bare-list shape for backward compat). The per-return mixer state (volume, panning, mute, solo, color) is pulled separately via `ableton_return(action='info', return_index=...)` probes — see `return_info` below.
- `return_info:<id>` (from `ableton_return(action='info', return_index=N)`) — the raw probe returns `{"return_index": <int>, "name": <str>, "color": <int|null>, "volume": <float>, "panning": <float>, "mute": <bool>, "solo": <bool>}`. Pass it through unchanged. The apply layer (`_apply_return_info`) diffs each field against the DB row and emits the union of changes through `update_return`.
- `track_info:<id>` (from `ableton_track(action='info', track_index=N)`) — the raw probe returns `{"track_index": <int>, "name": <str>, "kind": <"midi"|"audio"|"group">, "color": <int|null>, "volume": <float>, "panning": <float>, "mute": <bool>, "solo": <bool>, "arm": <bool>}`. The apply layer's keys are slightly different: it wants `type` (not `kind`). Rename `kind` → `type` before adding to results; everything else passes through.
- `track_sends:<id>` (from `ableton_track(action='get_sends', track_index=N)`) — the raw probe returns `{"track_index": <int>, "sends": [{"return_index": <int>, "return_name": <str>, "value": <float>}, ...]}`. The apply layer wants `{"<return_name>": <float>, ...}`. Reshape: `{s["return_name"]: s["value"] for s in result["sends"]}`.
- `cue_points_list` (from `ableton_arrangement(action='cue_list')`) — the raw probe returns `{"cue_points": [{"cue_index": <int>, "position_beats": <float>, "name": <str>}, ...]}`. **Normalize** before adding to results: unwrap the `cue_points` list. The apply layer accepts three position shapes (`{position_beats}`, `{position_bar}`, `{bar, beat}`); the new beats-based shape converts via the song's time-signature map to `position_bar` for DB storage. Names round-trip cleanly in M-5+; name diffs surface as informational warnings without overwriting DB names.

If the MCP response shape doesn't match (e.g. `ableton_session(action='info')` returns nested data differently), normalize before adding to the results array. Do NOT pass raw MCP shapes through unmodified — the apply layer's contract is the normalized shape above.

Write the results array to `/tmp/ableton-pull-results.json`.

### Step 3 — Apply

Run:
```
python3 -m hallucinote.sync.pull_cli apply <session_id> --song <song-slug> --plan /tmp/ableton-pull-plan.json --results /tmp/ableton-pull-results.json
```

This writes a JSON summary to stdout: `{mutations, no_ops, skipped_unlinked, warnings, details}`.

### Step 4 — Report

Show the user:

- The total counts (`<N> mutations applied, <M> no-ops, <K> skipped (unlinked)`).
- Each line from `details` (these are the human-readable diffs — e.g. `track 'Drums' volume: 0.6 -> 0.75`).
- Any warnings.

If `mutations == 0` and there are no warnings, say "DB already matches Ableton — no changes needed" and stop.

## Failure modes

- **`plan` exits non-zero** — show stderr to the user; usually means the session_id or db path is wrong.
- **A probe MCP call fails** — record it in the results with `ok=false` and proceed. `apply` will surface the failure as a warning but won't crash.
- **`apply` exits non-zero** — show stderr; usually means an unknown key kind (planner / apply contract drift) or a malformed results file.

Do not retry MCP calls automatically — Ableton transient failures are rare and silent retries can mask real issues.

## What NOT to do

- Do not try to "improve" the diff before calling `apply`. The DB is the source of truth for the diff logic; your job is to faithfully ship the Ableton snapshot.
- Do not skip the `plan` step ("I already know what to probe"). The planner walks `ableton_links` to pick the right linked tracks; you don't have that context.
- Do not change `actor` or invent new domains. If the user asks for something not in the table above, surface it as a gap and stop.
- Do not "be helpful" by also pushing afterward. Pull is one direction; if the user wants a round-trip, they will say so.
