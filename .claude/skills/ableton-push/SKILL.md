---
description: Push the Hallucinote DB into Ableton Live. Drives ten ordered phases (tempo → meter → tracks → returns → clips → mix → devices → envelopes → arrangement → cues) against a fresh or partially-built Live set. Use when you want to materialize a song from the DB.
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Bash(python3 -m hallucinote.sync.push_cli *), mcp__hallucinote-mcp__ableton_session, mcp__hallucinote-mcp__ableton_track, mcp__hallucinote-mcp__ableton_return, mcp__hallucinote-mcp__ableton_arrangement, mcp__hallucinote-mcp__ableton_device, mcp__hallucinote-mcp__ableton_clip, mcp__hallucinote-mcp__ableton_automation
argument-hint: <song-slug> [<session_id> | --new-session]
---

You are the Ableton push orchestrator. Your job: take the DB state for a song, materialize it in Live by driving ten ordered phases through MCP, and report what was created.

$ARGUMENTS

## What push does

Push is the **DB → Ableton** direction. The DB is the source of truth; Live is built from it. Push is **additive**: it does not delete Live state that isn't in the DB. If the user wants to start clean, they should open a fresh Live set first.

The ten phases run in a strict order set by Live's API constraints (e.g., envelopes must be written on session clips BEFORE `duplicate_to_arrangement`, per W4-A; cues must be written AFTER the arrangement is laid down, per Live's `[0, last_event_time]` clamp). The orchestrator owns this order — your job is to drive each phase through MCP and feed the results back.

## Required arguments

You need TWO pieces of information from `$ARGUMENTS`:

1. **The song slug** (required) — filesystem-safe identifier matching the song's directory + DB filename. The DB lives at `songs/<slug>/<slug>-<branch>.db` per W12-A (per-branch convention; outside a repo / detached HEAD falls back to `songs/<slug>/<slug>.db`).
2. **The session_id** — the `ableton_sessions.id` row that binds the DB to the currently-open Live set. Three paths to provide it:
   - **User passed an explicit id**: use it directly.
   - **User said "new session" / first push for this song**: pass `--auto-session` to `probe-and-link` (W9-B) — the CLI creates the row and returns its id in the response (`session_id` field, `auto_session_created: true`). Tell the user the new id so they can reuse it for subsequent pushes (the user typically wants ONE session per Live set, not a new one per push).
   - **User said "create a session named X"**: run `push_cli create-session --song <slug> --name X` first; capture the printed id; use it.

If the slug is missing, ask the user. For session, default to `--auto-session` only if the user explicitly signaled "this is the first push for this song / new session" — otherwise ask.

## Workflow overview

```
0. Probe Live for tracks + returns         → snapshot.json
1. python -m hallucinote.sync.push_cli probe-and-link → ableton_links rows for matches
2. python -m hallucinote.sync.push_cli phases → ten phase names
3. For each phase, in order:
     a. python -m hallucinote.sync.push_cli plan <phase> → plan.json
     b. Execute every call in plan.calls via MCP
     c. Assemble results.json
     d. python -m hallucinote.sync.push_cli apply --results results.json
4. Report total counts + any failures.
```

Steps 3a–3d must run **strictly in order**, one phase at a time. Phases later in the list inspect `ableton_links` written by earlier phases — if you batch-plan everything up front, later phases will see stale state and emit either redundant creates or strict-precondition errors.

### Step 0 — Probe Live for the snapshot

Call:
- `ableton_track(action='list')` → returns `{"tracks": [{"track_index": N, "name": ..., "kind": "midi"|"audio"|"group"}, ...]}`. Master is NOT included.
- `ableton_return(action='list')` → returns `{"returns": [{"return_index": N, "name": ..., "color": ...}, ...]}`. Names carry Live's auto slot-letter prefix (`"A-Reverb"`, `"B-Delay"`).

Assemble the snapshot as JSON and write it to `/tmp/ableton-push-snapshot.json`:

```json
{
  "tracks": [{"track_index": 1, "name": "Drums", "kind": "midi"}, ...],
  "returns": [{"return_index": 1, "name": "A-Reverb"}, ...]
}
```

### Step 1 — Probe-and-link

Run:
```
python3 -m hallucinote.sync.push_cli probe-and-link <session_id> --song <slug> --snapshot /tmp/ableton-push-snapshot.json
```

The CLI matches by name (track names directly; return names after stripping Live's `<letter>-` prefix per W4-C) and writes `ableton_links` rows for each match. Re-runnable: if the link already exists, it's an upsert.

Display to the user:
- The matched lists (concise — `"linked 3 of 5 DB tracks; 2 will be created"`).
- The `notes` list verbatim if non-empty. Notes cover duplicate names, kind mismatches, and **case-only near-matches** (W5-B). If a DB track 'Drums' and a Live track 'drums' both appear unmatched, the note flags them as a case-variant pair so the user can decide whether to rename one before push (otherwise phase 3 silently creates a duplicate `Drums` next to the existing `drums`).
- The `unmatched_live_tracks` / `unmatched_live_returns` lists if non-empty — these are existing Live entities push will NOT touch. The user often wants to know "the song will live alongside `1-MIDI`, `2-MIDI`, ..." so they can clean those up manually if desired.

Unmatched DB entities will be created in phases 3/4. Unmatched Live entities are **not** touched — push is additive.

### Step 2 — Enumerate phases

Run:
```
python3 -m hallucinote.sync.push_cli phases <session_id> --song <slug>
```

Output is a JSON document with a `phases` array, each entry `{"name", "description"}`. Hold this list in mind — the loop below iterates it in order.

### Step 3 — Drive each phase

For **each** phase in the list (top to bottom):

**3a. Emit the plan.**
```
python3 -m hallucinote.sync.push_cli plan <phase-name> <session_id> --song <slug>
```

Save stdout to `/tmp/ableton-push-plan-<phase>.json` using Write — `<phase>` substituted with the actual phase name (e.g., `tempo_map`, `tracks`). The apply step (3c) re-reads this file via `--plan`, so use the same path consistently in 3a and 3c.

Display any non-empty `notes` to the user before executing — they often surface unlinked dependencies (e.g., the `clips` phase warns when a track isn't linked yet because Step 1 didn't match it AND the `tracks` phase hasn't applied yet).

If `plan.calls` is empty, skip to the next phase. Common reasons: nothing in the DB for this phase (e.g., no devices), or every entity already linked (idempotent re-push).

**3b. Execute each call (minimal format).**

For each `call` in `plan.calls`, in plan-list order:

- `call.tool` always starts with `ableton_` — every emitter routes to a real `hallucinote-mcp` tool. (As of W5-A there are no emulator placeholders — `mcp_names.ALIASES_TODAY` is empty.)
- Route to the matching MCP namespace: `mcp__hallucinote-mcp__<call.tool>` with `**call.args` (the args include `action`, e.g. `{"action": "create", ...}`).
- **W10-E minimal format (recommended)**: build a compact `{"ok": true, "result": <response>}` per call — ~half the JSON of the legacy format. The CLI re-derives `key` + `tool` from the plan via `--plan`.
- On failure (MCP raises), build `{"ok": false, "error": "<message>"}` and continue. Do NOT retry — Ableton transient failures are rare and silent retries mask real bugs.

Order in the results list MUST match the order of calls in `plan.calls`. The CLI zips them by position.

**Tempo / signature: bar-1 only.** Live's MCP exposes `ableton_session(set_tempo)` and `set_signature` which set the global (bar-1) value. Per-bar tempo / meter automation is a real MCP gap (`ableton_automation` has no `song_tempo` / `song_signature` `target_kind` — see `hallucinote_mcp/.../guides/gaps.md`). The planner emits `ableton_session(set_tempo/set_signature)` for the bar-1 row of each map and warns + skips the rest. Songs with mid-song tempo / meter changes will round-trip the bar-1 value only until the MCP gap closes.

**3c. Apply with --plan (minimal format).**

Write the minimal results array to `/tmp/ableton-push-results.json` and run:
```
python3 -m hallucinote.sync.push_cli apply <session_id> --song <slug> \
    --results /tmp/ableton-push-results.json \
    --plan /tmp/ableton-push-plan-<phase>.json
```

The `--plan` arg points the CLI at the plan that produced the results, so it can re-derive `key` + `tool` and dispatch to the right apply path per call.

The CLI prints `{"applied": N, "failed": M, "details": [...]}`. The apply call writes `ableton_links` rows from successful results so the next phase's planner sees the new state.

**Legacy fallback**: if you already have `{"key", "ok", "tool", "result"}` entries (e.g., from a pre-W10-E playbook), pass them WITHOUT `--plan`. The CLI sniffs the format and accepts either.

**3d. Report per-phase.**

Tell the user concisely: `"<phase>: <N> calls, <K> applied, <F> failed"`. If any failed, list the keys + errors. Then move to the next phase.

### Step 4 — Final report

After all ten phases, surface the following to the user **in this order**:

1. **Totals.** Total applied / failed across phases.
2. **Per-domain summary.** A short line (`"created 2 tracks, 1 return, 2 clips, 2 arrangement placements, 1 cue point; 1 envelope written; 2 emulator-gap calls skipped"`).
3. **Live 12.4 UI heads-up — conditional, only emit the rows that apply to this push.** These two behaviors are not bugs; they look broken until the user knows the gesture that reveals state. Mention each only when the push's actual output makes the user likely to hit it:
   - **Mixer column hides on tracks with empty device chains.** Emit if any track in the push has zero devices (typically when the song's DB lists no devices for a track, or when the `devices` phase was skipped). One-liner: "Track 'X' has no devices yet → Live hides its mixer column; loading any instrument restores the faders." Name each affected track.
   - **Mixer / pan / send envelopes hidden in the MIDI clip envelope dropdown.** Emit if the `envelopes` phase wrote any `mixer_volume` / `mixer_pan` / `send_level` envelope on a MIDI clip. One-liner: "Mixer envelope(s) pushed onto MIDI clip 'Y' are playing (the fader will visibly move) but Live hides them in the clip's envelope dropdown by default. Right-click the affected mixer slider in Live and choose 'Show Modulation' to draw/edit them. Live remembers the choice per-set."

   If neither applies, skip this section entirely — don't add ceremony to a clean push.

If the user opens the Live set now, the song should be there.

## Phase-by-phase tool mapping

Each phase's planner emits a known set of MCP calls. This map lets you sanity-check that you've got the right MCP namespace before executing:

| Phase | Tool(s) emitted |
|---|---|
| `tempo_map` | `ableton_session(action='set_tempo')` for the bar-1 row; non-bar-1 rows skipped with a warn (MCP gap) |
| `time_signature_map` | `ableton_session(action='set_signature')` for the bar-1 row; non-bar-1 rows skipped with a warn (MCP gap) |
| `tracks` | `ableton_track(action='create')` |
| `returns` | `ableton_return(action='create')` |
| `clips` | `ableton_clip(action='create' / 'replace_notes')` |
| `mix` | `ableton_track(action='set_property' / 'set_send')`, `ableton_return(action='set_property')`, `ableton_session(action='set_master_property')` |
| `devices` | `ableton_device(action='load' / 'set_parameter')` |
| `envelopes` | `ableton_automation(action='write_envelope')` |
| `arrangement` | `ableton_clip(action='duplicate_to_arrangement')` |
| `cues` | `ableton_arrangement(action='cue_create_batch')` |

## Result shapes the apply layer expects

The CLI's `apply` reads each result's `result` field for link-bearing kinds. The MCP response shapes already match — pass them through unchanged. The link-bearing key kinds + the field the apply layer reads:

| key kind | result field |
|---|---|
| `track:<id>` | `track_index` |
| `return:<id>` | `return_index` |
| `clip:<id>` | `clip_index` (create returns the new index; `replace_notes` returns nothing — apply skips the link write) |
| `device:<id>` | `device_index` |
| `arrangement_clip:<id>` | `arrangement_clip_index` |
| `envelope:<id>` | `envelope_index` (apply skips if absent) |

All other key kinds (`track_volume`, `send`, `cue_batch`, `master_*`, `tempo_point`, `time_signature_point`, `device_parameter`) are ack-only — the apply just confirms `ok=true` without writing a link.

## Failure modes

- **`probe-and-link` exits non-zero** — snapshot file malformed, DB path wrong, or session_id unknown. Show stderr.
- **`plan` exits non-zero** — usually a strict-precondition raise (`plan_push_clip: track 'X' is not linked …`). Investigate: did Step 1's probe-and-link skip a track that should have matched? Did the previous phase's apply fail silently? Show the user the error and stop the run — pushing forward with a broken plan will multiply the damage.
- **An MCP call fails** — record with `ok=false` and continue. The apply layer skips failed results. The user sees the failure in Step 3d.
- **`apply` exits non-zero** — usually an unknown key kind (planner / apply contract drift). Show stderr; stop the run.

Do not retry MCP calls automatically.

## What NOT to do

- Do **not** plan all ten phases up front and then execute them. Later phases inspect `ableton_links` written by earlier phases; batch-planning silently breaks the dependency chain.
- Do **not** skip probe-and-link "because the Live set is fresh." It's idempotent and cheap; running it always means the skill works the same against fresh and half-built sets.
- Do **not** invent new phases or reorder them. The order is set by Live's API constraints (W4-A: envelopes before arrangement; cue clamp: cues after arrangement). The planner enforces the order in `_PHASE_NAMES`.
- Do **not** retry MCP calls. Failures are rare and meaningful.
- Do **not** try to "improve" the plan by collapsing calls before executing — the planner has already done that work (W3-C dedupe; Wave M+1 atomic creates).
- Do **not** offer to pull back after pushing. Push is one direction; round-trips are a separate user request.

## Notes

- Real-Live performance: each phase typically takes < 1 second for falling-walking; the bottleneck is the per-call MCP round-trip, not the planner. A song with hundreds of envelopes will be slower.
- The throwaway `.prawduct/push-orchestrator.py` from Wave 3 is deleted by Wave 4 — this skill is now the only push driver. If you find references to that script in old reflections, they're historical.

## Post-push Live UX quirks the user should know about

Two Live 12.4 UI behaviors are inherent to Live's LOM + UI defaults, not Hallucinote bugs. Step 4 of the workflow surfaces them to the user **conditionally** — only when the push's actual content makes the user likely to hit them. Reference detail kept here so the skill body can stay concise:

1. **Mixer column hides on tracks with empty device chains.** Tracks that didn't have any devices loaded yet (e.g. before phase 7 runs, or after phase 7 if the song's DB lists no devices for a track) show no volume/pan/sends/master faders in Live's UI. The mixer state is still settable + functional via MCP; the UI just collapses. Loading any device into the chain restores the full column.

2. **Mixer / Pan / Send envelopes on MIDI clips are hidden in the per-clip envelope dropdown by default.** Empirical Live 12.4 + W4-A `.als` XML inspection confirm: envelopes written through `ableton_automation(write_envelope, target_kind='mixer_volume'|'mixer_pan'|'send_level')` on MIDI session/arrangement clips are **fully attached and functional during playback** (the fader visibly moves), but Live's per-MIDI-clip envelope-selector UI hides `Mixer → Track Volume` (et al.) from the dropdown by default. To make the envelope drawable + editable in the UI, the user must **right-click the affected mixer slider in Live and choose "Show Modulation"**. Live remembers the choice per-set. The envelope plays correctly without this step — the gesture is only for visibility/editability.
