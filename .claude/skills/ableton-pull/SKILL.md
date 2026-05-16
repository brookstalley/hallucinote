---
description: Pull Ableton state into the Hallucinote DB. Diffs Ableton against the DB and writes mutations through the standard mutator path so events fall out naturally. Use for ingesting manual edits made in Ableton (fader moves, mute toggles, send tweaks).
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Bash(python3 -m hallucinote.sync.pull_cli *), mcp__AbletonMCP__get_session_info, mcp__AbletonMCP__get_track_info, mcp__AbletonMCP__list_return_tracks, mcp__AbletonMCP__get_track_sends, mcp__AbletonMCP__get_track_volume
argument-hint: <song-slug> <session_id> <domain | natural-language request>
---

You are the Ableton pull orchestrator. Your job: read what the user wants pulled from Ableton, run the right MCP probes, hand the results to the DB layer, and report what changed.

$ARGUMENTS

## Conflict policy

**Ableton wins, always (V1).** Any field that differs between DB and Ableton is overwritten with Ableton's value. Mutations are emitted with `actor='sync'` and `reason="pull from session <session_id>"`. Three-way merge is deferred (see `docs/VISION.md`).

## Available domains and MCP-blocked domains

Map the user's request — domain token OR natural language — onto one of these.

**Available now (run these):**
- `mix-state` — track volume / pan / mute / solo / arm / color, return volume / pan, master volume / pan, sends.

**MCP-gap-blocked (do NOT attempt — surface the gap and offer the closest available alternative):**
- Notes / MIDI — blocked by MCP gap #4 (no note-level IDs). Pull-back of notes would be destructive (whole-clip rewrite); deferred until note-level addressing lands.
- Automation envelopes — blocked by no MCP read surface for envelopes (see `docs/mcp-requirements.md` "Capture-side read").
- Device parameter values — blocked by MCP gap #17b (`get_device_parameters` raises `No module named 'MCP_Server'`).
- Nested rack chains — blocked by MCP nested-chain probe gap.
- Audio — out of scope; the schema doesn't model audio clips yet.

**Natural-language mapping examples:**
- "fader moves" / "mix tweaks" / "volume + pan" → `mix-state`
- "send levels" / "reverb amounts" → `mix-state`
- "mute / solo / arm changes" → `mix-state`
- "midi notes" / "latest midi updates" → blocked. Explain gap #4. Do NOT run anything.
- "device settings" / "compressor params" → blocked. Explain gap #17b.
- "everything" → run every available domain in order (today: just `mix-state`).

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
- Invoke the matching MCP tool: `mcp__AbletonMCP__<call.tool>` with `**call.args`.
- Capture the response. If the MCP call raises, mark the result as `{"key": ..., "ok": false, "tool": ..., "error": "<message>"}`.
- On success, build `{"key": call.key, "ok": true, "tool": call.tool, "result": <response>}`.

The result `result` MUST be the normalized shape `apply_pull_results` expects. Today:

- `session_info` → `{"master": {"volume": <float>, "panning": <float>}, "tempo": <float>, "signature": "<n/d>"}` (extra keys are fine and ignored).
- `returns_list` → `[{"index": <1-based>, "name": <str>, "volume": <float>, "panning": <float>}, ...]`.
- `track_info:<id>` → `{"name": <str>, "type": <str>, "volume": <float>, "panning": <float>, "mute": <bool>, "solo": <bool>, "arm": <bool>, "color": <int|null>}` (any field can be omitted; missing == "no probe data for this field" == do not change DB).
- `track_sends:<id>` → `{"<return_name>": <float>, ...}`.

If the MCP response shape doesn't match (e.g. `get_session_info` returns nested differently), normalize before adding to the results array. Do NOT pass raw MCP shapes through unmodified — the apply layer's contract is the normalized shape above.

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
