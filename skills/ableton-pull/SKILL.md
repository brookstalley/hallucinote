---
description: Pull Ableton state into the Hallucinote DB (a regenerable build artifact) — the lower-level build.py-staging primitive, NOT a parallel mix bake. Diffs Ableton against the DB and writes mutations through the standard mutator path so events fall out naturally. Use to stage build.py-owned manual edits (clip notes, automation) for folding into build.py, or for a quick DB-only ingest of fader/mute/send tweaks. For a DURABLE mix bake (params, sends, device chains, sidechain) that survives a rebuild, use /song-snapshot instead.
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Bash, mcp__hallucinote-mcp__ableton_session, mcp__hallucinote-mcp__ableton_track, mcp__hallucinote-mcp__ableton_return, mcp__hallucinote-mcp__ableton_arrangement, mcp__hallucinote-mcp__ableton_device, mcp__hallucinote-mcp__ableton_clip, mcp__hallucinote-mcp__ableton_note
argument-hint: <song-slug> <session_id> <domain | natural-language request>
---

You are the Ableton pull orchestrator. Read what the user wants pulled, run the right MCP probes, hand the results to the DB layer, and report what changed.

$ARGUMENTS

> **Running engine commands.** The engine ships in the plugin's uv env — no separate install. Resolve `$PY` once from `ableton://server/info`'s `python`; the `pull` commands below run as `"$PY" -m hallucinote.cli pull …`. See [`docs/running-the-engine.md`](../../docs/running-the-engine.md).

## When to use this — and the durability boundary (BAK-3M9T)

`/ableton-pull` writes to the song **`.db`**, which is a **regenerable build
artifact**: every `build.py` runs `replay_capture(captured_session.json)`, which
re-asserts the snapshot onto the DB. So a pulled **mix** edit (params, sends,
mixer, sidechain) is not durable on its own — it lives only in the regenerable
DB. `/ableton-pull` is therefore the lower-level **build.py-staging primitive**,
NOT a parallel mix bake:

- **Durable mix bake → `/song-snapshot`.** The single mix bake — instrument params,
  sends, device chains, and **sidechain sources** land in the git-tracked
  `captured_session.json` and survive a rebuild. Use it for "I dialed the mix; keep it."
- **`/ableton-pull`'s durable lane is the build.py-owned domains** — clip notes and
  automation envelopes — that you ingest here and then fold into `build.py` (the
  authorship home for notes/score). Its mix-domain pulls (`mix-state`,
  `device-parameters`, …) are a quick DB-only ingest / inspection; to make them
  durable, run `/song-snapshot` after.

> **The bake is the closing move (BAK-7D2V).** A mix-domain pull left un-baked
> is not silently reverted anymore — the next `build.py` **REFUSES to run**
> (`StaleSnapshotError`) rather than re-assert the stale snapshot over your
> pulled edits. After such a pull, `pull_cli` prints a durability notice on
> stderr naming the fix. Close the loop with **`/song-snapshot`** (which
> re-stamps `captured_session.json` newer than the pull and disarms the guard);
> only reach for `build.py --force-replay` to *consciously discard* the pulled
> edits. Build.py-owned pulls (clip-notes, envelopes, tempo, cue, arrangement,
> tuning) never arm the guard — that's the sanctioned staging lane.

## Conflict policy

**Ableton wins, always (V1).** Any field that differs is overwritten with Ableton's value. Mutations carry `actor='sync'` and `reason="pull from session <session_id>"`. Three-way merge is deferred (see `docs/VISION.md`).

## Available domains

- `mix-state` — track volume / pan / mute / solo / arm / color, return volume / pan, master volume / pan, sends. Also ingests global tempo + signature (free ride-along).
- `score-globals` — global tempo + signature ONLY (bar-1 rows). Cheaper than `mix-state` if that's all you've changed.
- `cue-points` — arrangement cue positions + names. Name diffs are informational warnings (DB-side names are user-authoritative).
- `devices` — top-level device chain on each linked track + return: positional `(kind, display_name)` diff. Nested chains live in `nested-rack-chains`; per-device parameter VALUES live in `device-parameters`.
- `nested-rack-chains` — one level of nested chains under each rack device. Run after `devices`. Recursively nested racks deferred.
- `device-parameters` — per-device parameter values on every device. Diff by parameter name. `value_normalized` computed from raw value vs min/max; enum + constant-range params store NULL. The keystone for V1 round-trip parity. Run after `devices`.
- `arrangement-clips` — per-track arrangement placements (start_bar / end_bar). Positional diff. Live exposes no stable per-clip identity, so V1 takes no action on Ableton-only positions (doesn't auto-create clips, doesn't infer moves) — mirror the change DB-side and re-run.
- `session-clips` — per-track session-view slot contents (slot, name, length). Matched slots update for name/length drift, cleared slots delete the DB clip, Ableton-only populated slots warn.
- `clip-notes` — per-clip notes. Content-diffs by `(pitch, start_time, duration)` within 1/1000 of a beat. Velocity / mute drift updates DB notes in place (UUID preserved); pitch/start/duration moves surface as delete + insert (UUID rotates — documented V1 limitation).
- `envelopes` — per-envelope automation. Round-trip mode only — pulls envelopes already in the DB; discovering Live-authored envelopes is a separate backlog item. Skip-symmetric with push.

**MCP-gap-blocked:**
- Surgical Ableton-side note writes (`ableton_note(add / update / delete)`) — gap #4. Use `ableton_clip(action='replace_notes')` for whole-clip writes.
- Master-strip devices — separate planner; the `devices` domain skips master.
- Per-arrangement tempo / signature changes — only the bar-1 values are exposed.
- Audio — out of scope.

## Natural-language mapping

Map verbs to domains:
- Mixer / sends / mute / solo / arm / color → `mix-state`
- Tempo / BPM / meter → `score-globals` (or `mix-state` if you want master fader too)
- Cue points / locators / markers → `cue-points`
- Device chain edits (added / removed / swapped a device) → `devices` (then `nested-rack-chains` if a rack's internals changed)
- Device parameter dial-ins / "what's the threshold set to" / "I dialed in an Operator patch" → `device-parameters` (run `devices` first if the chain may have changed)
- Arrangement edits (moved / deleted clips on the timeline) → `arrangement-clips`
- Session-view edits (renamed / cleared / shortened a session clip) → `session-clips`
- MIDI note edits / "I changed velocities" / "humanize back" → `clip-notes`
- Automation / envelope edits → `envelopes`
- "everything" → run every domain in order: `mix-state` → `cue-points` → `devices` → `nested-rack-chains` → `device-parameters` → `arrangement-clips` → `session-clips` → `clip-notes` → `envelopes`. (Skip `score-globals` — `mix-state` covers it.)

If the request is ambiguous, ask one targeted question rather than guessing.

## Required arguments

Three pieces from `$ARGUMENTS`:

1. **Song slug** — DB lives at `songs/<slug>/<slug>-<branch>.db` (per-branch isolation; see `docs/snapshot-schema.md`). The CLI resolves the path via `--song <slug>`.
2. **session_id** — optional (WFL-7Q2N): when omitted, the CLI auto-selects the only / most-recent session in the DB and echoes the choice on stderr (multi-song DBs refuse to guess). An explicit id always wins; `apply` treats the plan file's embedded session as authoritative.
3. **Domain or NL request**.

If slug or domain is missing, ask — never invent. For session, omission is fine; relay the CLI's auto-selection echo to the user.

## Workflow

For each resolved domain, do the steps in order. Run `mix-state` end-to-end before moving on to another domain.

**Multi-domain runs (`everything` or any multi-domain request): emit a progress line BEFORE Step 1 of each domain** — `pulling domain <N>/<M>: <domain-name>`. A nine-domain `everything` run takes long enough that the user otherwise can't tell whether the skill is hung.

### Step 1 — Plan

```
"$PY" -m hallucinote.cli pull plan <domain> <session_id> --song <slug>
```

Writes JSON to stdout: `{calls: [{tool, args, key, purpose}, ...], notes: [...]}`. Save to `/tmp/ableton-pull-plan.json` via Write. Display non-empty `notes` before proceeding — they often surface unlinked tracks.

### Step 2 — Execute each probe

For each `call` in `plan.calls`:
- Invoke `mcp__hallucinote-mcp__<call.tool>` with `**call.args`.
- On success: `{"key": call.key, "ok": true, "tool": call.tool, "result": <response>}`.
- On failure: `{"key": ..., "ok": false, "tool": ..., "error": "<message>"}`.

**Result shapes follow the contract the CLI's `plan` documents.** Each domain's response normalization happens in the apply layer; pass raw MCP shapes through unless the planner's per-key documentation says otherwise. Two cases where the skill MUST normalize before adding to results:

- `session_info` — convert `signature` from `{numerator, denominator}` to legacy `"<n>/<d>"` string form.
- `track_info` — rename `kind` field to `type`.
- `track_sends` — reshape `sends` list to `{return_name: value}` dict.
- `cue_points_list` — unwrap the `cue_points` array (the list itself, not the wrapper).

All other probes (`returns_list`, `return_info`, `track_devices`, `nested_rack_chains`, `device_parameters`, `track_arrangement_clips`, `track_session_clips`, `clip_notes`) pass through unchanged.

Write the results array to `/tmp/ableton-pull-results.json`.

### Step 3 — Apply

```
"$PY" -m hallucinote.cli pull apply <session_id> --song <slug> \
  --plan /tmp/ableton-pull-plan.json \
  --results /tmp/ableton-pull-results.json
```

Writes JSON summary to stdout: `{mutations, no_ops, skipped_unlinked, unreadable, warnings, details}`. The command also exits NON-ZERO when `unreadable > 0`.

### Step 4 — Report

**FIRST: if the command exited non-zero or `unreadable > 0`** (PULL-DRIFT-DETECT), the pull could NOT read some probes — pulled state is incomplete (usually a Live ↔ Remote-Script version mismatch). Tell the user how many probes were unreadable and that the pull is incomplete, and do NOT say "DB already matches" — "couldn't read" is not "no drift". Suggest relaunching dev-mode + `/ableton-mcp-install`, then retry.

Otherwise show the user:

- Total counts (`<N> mutations applied, <M> no-ops, <K> skipped (unlinked)`).
- Each line from `details` (human-readable diffs — `track 'Drums' volume: 0.6 -> 0.75`).
- Warnings. For the `clip-notes` "look moved" warning, add: *"If you nudge or restretch a note in Ableton and pull, the diff is correctly modeled as delete + insert — the note picks up a fresh UUID. If annotations/events keyed to the prior UUID matter, undo in Ableton and edit DB-side by the original UUID instead."*

If `mutations == 0` with no warnings AND `unreadable == 0`, say "DB already matches Ableton — no changes needed."

## Failure modes

- **`plan` exits non-zero**: usually session_id / db path wrong. Show stderr.
- **A probe MCP call fails**: record with `ok=false` and proceed. `apply` surfaces it as a warning.
- **`apply` exits non-zero**: usually unknown key kind or malformed results. Show stderr.
- **Connection errors**: see `ableton://guides/error-recovery`.

Do not retry MCP calls automatically — transient failures are rare; silent retries mask real issues.

## What NOT to do

- Do not "improve" the diff before calling `apply`. The DB is the source of truth for diff logic.
- Do not skip `plan` — the planner walks `ableton_links` to pick the right tracks.
- Do not invent new domains. Gaps stop the run.
- Do not push afterward. Pull is one direction.

## Provenance

Every `pull_cli apply` opens a `requests` row (`kind='pull'`), threads its id through every mutator, and closes it with `outcome='ok'` (or `'failed'`). Query via `Q.get_latest_request_for_song(...)` / `Q.get_events_for_request(...)`.
