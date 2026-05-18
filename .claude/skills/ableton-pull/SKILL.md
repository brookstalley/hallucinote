---
description: Pull Ableton state into the Hallucinote DB. Diffs Ableton against the DB and writes mutations through the standard mutator path so events fall out naturally. Use for ingesting manual edits made in Ableton (fader moves, mute toggles, send tweaks).
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Bash(python3 -m hallucinote.sync.pull_cli *), mcp__hallucinote-mcp__ableton_session, mcp__hallucinote-mcp__ableton_track, mcp__hallucinote-mcp__ableton_return, mcp__hallucinote-mcp__ableton_arrangement, mcp__hallucinote-mcp__ableton_device, mcp__hallucinote-mcp__ableton_clip, mcp__hallucinote-mcp__ableton_note
argument-hint: <song-slug> <session_id> <domain | natural-language request>
---

You are the Ableton pull orchestrator. Your job: read what the user wants pulled from Ableton, run the right MCP probes, hand the results to the DB layer, and report what changed.

$ARGUMENTS

## Conflict policy

**Ableton wins, always (V1).** Any field that differs between DB and Ableton is overwritten with Ableton's value. Mutations are emitted with `actor='sync'` and `reason="pull from session <session_id>"`. Three-way merge is deferred (see `docs/VISION.md`).

## Available domains and MCP-blocked domains

Map the user's request — domain token OR natural language — onto one of these.

**Available now (run these):**
- `mix-state` — track volume / pan / mute / solo / arm / color, return volume / pan, master volume / pan, sends. Free side-effect: also ingests global tempo + signature (they ride along in the same `ableton_session(action='info')` probe).
- `score-globals` — global tempo + global time signature ONLY (bar-1 rows in each map). Cheaper than `mix-state` if all you've changed is tempo or meter.
- `cue-points` — arrangement cue point positions + names. Gap #13 (legacy fork's numeric-only names) is resolved in the greenfield server; apply still treats name diffs as informational warnings since DB-side cue names are user-authoritative.
- `devices` — top-level device chain on each linked track + return: positional diff of `(kind, display_name)` slots. Nested rack chains and `is_active` are NOT pulled (gap-blocked or not-yet-modeled — see below). Per-device parameter VALUES are pulled by the sibling `device-parameters` domain.
- `device-parameters` — per-device parameter values on every device the previous `devices` pull recorded. Diff by parameter name within device; `value_normalized` is computed from Live's raw `value` against `min`/`max`; enum and constant-range params store `value_normalized=NULL`. Float jitter within `_FLOAT_EPS` is not a diff. Adds present-in-Live-only params; removes present-in-DB-only params. The keystone for V1 round-trip parity: parameter-dialed native instruments (Operator, Wavetable, etc.) round-trip with sound when this domain runs after `devices`. Tracked in backlog as the W5-D close.
- `arrangement-clips` — per-track arrangement-clip placements (start_bar / end_bar). Positional diff: matched pairs no-op, DB-only positions are removed, Ableton-only positions warn. Positional matching cannot distinguish a *moved* placement from a *new* one (Live exposes no stable per-clip identity), so V1 takes no action on Ableton-only positions either way: it does not auto-create `clips` rows, and it does not infer moves. Mirror the change in DB (re-add the moved placement, or create the new clip + placement) and re-run pull. Clip-name renames are NOT detected here (the `arrangement_clips` table has no `name` column; names live on `clips.name` and round-trip via `session-clips` below).
- `session-clips` — per-track session-view clip-slot contents (slot, name, length). Slot-positional diff: matched slots no-op (or `update_clip` if name/length drifted), Ableton-empty slots delete the DB clip at that slot, Ableton-only populated slots warn (same V1 limit as `arrangement-clips`: can't auto-create a clip from name + length alone). Note content drift is NOT detected here — use `clip-notes` for that.
- `clip-notes` — per-clip note pull (gap #4 PARTIAL: read-with-stable-IDs works, surgical Ableton-side writes still blocked). Emits one `ableton_note(action='list')` per linked clip — returns notes with Live's stable per-note IDs. Content-diffs against DB notes by `(pitch, start_time, duration)` within 1/1000 of a beat: velocity / mute drift updates DB notes in place (UUID preserved); new notes insert (UUID assigned); missing notes delete. A note whose pitch/start/duration moves surfaces as delete + insert (UUID rotates — documented V1 limitation; edit by UUID DB-side if preservation matters). Duplicate-key collisions warn + first-row-wins, mirroring `arrangement-clips`.

**MCP-gap-blocked (do NOT attempt — surface the gap and offer the closest available alternative):**
- Surgical Ableton-side note writes — the `ableton_note(add / update / delete)` write surface remains gap-#4-blocked. The `clip-notes` pull above closes the READ half. Whole-clip writes via `ableton_clip(action='replace_notes')` preserve all V1 compose-time capability.
- Automation envelopes — blocked by no MCP read surface for envelopes (see `docs/mcp-requirements.md` "Capture-side read").
- ~~Device parameter values — sync-layer not yet built.~~ Resolved by W5-D — use the `device-parameters` domain. Run it AFTER `devices` so the parameter pull sees the current chain.
- Nested rack chains — blocked by MCP nested-chain probe gap. The `devices` domain walks only top-level chains; devices flagged `can_have_chains=True` won't have their internal chains traversed.
- Master-strip devices — separate planner (master is reached via `ableton_session`, not `ableton_track`); the `devices` domain skips master rows. Tracked as a backlog item.
- Per-arrangement (multi-point) tempo / signature changes — MCP read gap; only the global (bar-1) values are exposed via `ableton_session(action='info')`.
- Audio — out of scope; the schema doesn't model audio clips yet.

**Natural-language mapping examples:**
- "fader moves" / "mix tweaks" / "volume + pan" → `mix-state`
- "send levels" / "reverb amounts" → `mix-state`
- "mute / solo / arm changes" → `mix-state`
- "tempo change" / "BPM" / "meter" / "time signature" → `score-globals` (or `mix-state` if you want master fader too)
- "cue points" / "locators" / "arrangement markers" → `cue-points`
- "device chain edits" / "added/removed a plugin" / "moved the compressor" / "swapped the EQ" → `devices`
- "arrangement edits" / "moved a clip in the arrangement" / "deleted a clip from the timeline" / "rearranged the song" → `arrangement-clips`
- "session-view edits" / "renamed a clip in Session View" / "cleared a slot" / "shortened a session clip" → `session-clips`
- "midi notes" / "note edits" / "I changed the velocities" / "added some notes" / "pulled out the wrong note" → `clip-notes`
- "humanize back / fix what I just played in" → `clip-notes` to pull, then DB-side humanize via mutators, then push.
- "device settings" / "compressor params" / "what's the threshold set to" / "I dialed in an Operator patch" → `device-parameters` (run `devices` first if the chain itself may have changed).
- "everything" → run every available domain in order: `mix-state`, then `cue-points`, then `devices`, then `device-parameters`, then `arrangement-clips`, then `session-clips`, then `clip-notes`. (`score-globals` is a subset of `mix-state`'s probes; skip it.)

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
- `track_devices:<id>` and `return_devices:<id>` (from `ableton_device(action='list', track_index=N)` or `(return_index=N)`) — the raw probe returns `{"parent_kind": "track"|"return", "track_index"|"return_index": <int>, "devices": [{"device_index": <1-based>, "name": <str>, "class_name": <str>, "is_active": <bool>}, ...]}`. Pass it through unchanged — the apply layer (`_apply_devices_for_parent`) reads `devices[*].class_name` as the DB's `kind` and `devices[*].name` as `display_name`, diffs positionally against the top-level chain, and ignores `is_active` until the schema grows the column. Nested rack chains are NOT traversed (no recursion in the probe; that's a separate gap).
- `device_parameters:<device_id>` (from `ableton_device(action='get_parameters', detail='full')`) — the raw probe returns `{"device_index": <int>, "parent_kind": "track"|"return", "track_index"|"return_index": <int>, "parameters": [{"name": <str>, "value": <float>, "value_display": <str>, "min": <float>, "max": <float>, "is_enum": <bool>}, ...]}`. Pass it through unchanged — the apply layer (`_apply_device_parameters_for_device`) computes `value_normalized = (value - min) / (max - min)` clamped into [0, 1]; enum and constant-range (`min == max`) params store `value_normalized=NULL`. Diff is by parameter name: in both / in DB only / in Live only / value-differs each handled distinctly.
- `track_arrangement_clips:<id>` (from `ableton_clip(action='list', location='arrangement', track_index=N)`) — the raw probe returns `{"track_index": <int>, "location": "arrangement", "clips": [{"arrangement_clip_index": <1-based>, "name": <str>, "start_beats": <float>, "length": <float>}, ...]}`. Pass it through unchanged — the apply layer (`_apply_arrangement_clips_for_track`) converts each `start_beats` and `start_beats + length` to fractional bar positions via the song's time-signature map and diffs positionally by `(start_bar, end_bar)`. DB-only placements are removed; Ableton-only placements warn (V1 cannot auto-create a `clips` row from a manually-drawn arrangement clip). Name diffs are NOT detected here (the `arrangement_clips` table has no `name` column; names round-trip via `track_session_clips` below).
- `track_session_clips:<id>` (from `ableton_clip(action='list', location='session', track_index=N)`) — the raw probe returns `{"track_index": <int>, "location": "session", "clips": [{"clip_index": <1-based slot>, "empty": <bool>, "name": <str, populated only>, "length": <float, populated only>}, ...]}`. Pass it through unchanged — the apply layer (`_apply_session_clips_for_track`) diffs by `clips.slot` and emits `update_clip` for name/length drift, `delete_clip` for slots Ableton has cleared, and warns on Ableton-only populated slots (same V1 limit as arrangement-clips: can't auto-create the clip from name + length alone).
- `clip_notes:<id>` (from `ableton_note(action='list', track_index=N, location='session', clip_index=M)`) — the raw probe returns `{"track_index": <int>, "location": "session", "clip_index": <int>, "notes": [{"note_id": <int>, "pitch": <int>, "start_time": <float>, "duration": <float>, "velocity": <int>, "mute": <bool>}, ...]}`. Pass it through unchanged — the apply layer (`_apply_notes_for_clip`) content-diffs by `(pitch, start_time, duration)` within 1/1000 of a beat; velocity / mute drift updates DB notes in place (UUID preserved), Ableton-only notes insert, DB-only notes delete. Live's `note_id` field is used only for debug/dedup within a single pull pass — never store it (it expires on any note-write).

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
