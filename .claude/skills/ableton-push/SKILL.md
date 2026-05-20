---
description: Push the Hallucinote DB into Ableton Live. Drives ten ordered phases (tempo → meter → tracks → returns → clips → mix → devices → envelopes → arrangement → cues) against a fresh or partially-built Live set. Use when you want to materialize a song from the DB.
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Bash(python3 -m hallucinote.sync.push_cli *), Bash(python3 -m hallucinote.sync.compat *), mcp__hallucinote-mcp__ableton_session, mcp__hallucinote-mcp__ableton_track, mcp__hallucinote-mcp__ableton_return, mcp__hallucinote-mcp__ableton_browser, mcp__hallucinote-mcp__ableton_arrangement, mcp__hallucinote-mcp__ableton_device, mcp__hallucinote-mcp__ableton_clip, mcp__hallucinote-mcp__ableton_automation
argument-hint: <song-slug> [<session_id> | --new-session]
---

You are the Ableton push orchestrator. Your job: take the DB state for a song, materialize it in Live by driving ten ordered phases through MCP, and report what was created.

$ARGUMENTS

## What push does

Push is the **DB → Ableton** direction. The DB is the source of truth; Live is built from it. Push is **additive**: it does not delete Live state that isn't in the DB. If the user wants to start clean, they should open a fresh Live set first.

The ten phases run in a strict order set by Live's API constraints (e.g., envelopes must be written on session clips BEFORE `duplicate_to_arrangement`, per W4-A; cues must be written AFTER the arrangement is laid down, per Live's `[0, last_event_time]` clamp). The orchestrator (`push_cli execute`) owns this order — your job is to set up the session (probe-and-link + confirmation gates), invoke `execute` once, then read the on-disk state file and report. The per-call MCP path is preserved for interactive single-element iteration (see end of this file), not for full-song pushes.

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
0.  Probe Live for tracks + returns         → snapshot.json
0a. Probe Live for installed plugins         → plugins.json
0b. python -m hallucinote.sync.compat check  → refuse-and-confirm gate
1.  python -m hallucinote.sync.push_cli probe-and-link → ableton_links rows for matches
2.  python -m hallucinote.sync.push_cli execute → dispatches all ten phases
3.  Read .last-push-state.json + report.
```

The `execute` subcommand (W10-E2) runs all ten phases inside the CLI process, dispatching every MCP call directly to Live's Remote Script over TCP. The agent doesn't touch the per-call MCP path for the bulk-data phases. **This is the default and only path for full-song pushes** — agent-side per-phase dispatch is the v1.0 ceiling (each `ableton_clip(create, notes=[…])` carries ~10–30 KB of inline JSON in the agent's tool-use block; a 29-clip song burned ~500 KB of context). `execute` removes that cost entirely.

The per-call MCP path documented at the bottom of this file is the **fallback** for interactive iteration (single clip edits, parameter nudges, A/B parameter comparisons) — not full-song pushes.

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

### Step 0a — Probe Live for installed plugins

Call `ableton_browser(action='plugins_list')` to enumerate VST/AU plugins Live has scanned. Write the response to `/tmp/ableton-push-plugins.json` via Write. The shape is `{"plugins": [{"name": "...", "uri": "..."}, ...], "count": N}` — pass through unchanged; the compat CLI accepts the wrapper.

Skipping this step is supported: if the MCP call fails (transient connection issue) or returns nothing useful, you can omit `--installed-plugins` in Step 0b. The compat report will mark every third-party plugin `third_party_unverified` instead of cleanly partitioning into ok / missing, and Step 0b's gate will require user confirmation. The plugin probe is cheap (one MCP round-trip), so the default is to run it.

### Step 0b — Compat check (cross-machine portability gate, W13-B)

Run:
```
python3 -m hallucinote.sync.compat check <slug> \
    --installed-plugins /tmp/ableton-push-plugins.json
```

The CLI walks the song's DB, classifies every device (including devices nested inside racks), and emits a JSON report with five status buckets:

- `native` — Live built-in. No install needed.
- `placeholder` — Author intentionally left empty; push will skip it cleanly (the consumer fills it in).
- `third_party_ok` — Plugin needed AND found in `--installed-plugins`. Safe to push.
- `third_party_missing` — Plugin needed but NOT in the installed list. The consumer hasn't installed it.
- `third_party_unverified` — Plugin needed but `--installed-plugins` was omitted; status unknown.

**Exit code contract.** `0` = clean (only `native` / `placeholder` / `third_party_ok` entries). `1` = at least one device is `third_party_missing` OR `third_party_unverified` — the user must confirm before pushing.

**On exit 1, refuse-and-confirm.** Display the `missing` + `unverified` lists from the report's `entries` array (filter by status). For each, show: track / chain path, position, display name, kind, lookup name. Then ask the user explicitly:

> "These third-party plugins this song needs are either missing on this machine or couldn't be verified. Pushing now will fail at device-load for the missing ones (the chain stays empty; nothing is substituted). Continue anyway? (yes/no)"

Proceed only on explicit `yes`. If `no`, point the user at `songs/<slug>/REQUIREMENTS.md` (regenerate with `compat write-requirements <slug>` if absent) so they know what to install, and stop.

**Re-running with no changes is idempotent** — the CLI is read-only against the DB. Run it again after the user installs the missing plugins; expect exit 0.

### Step 1 — Probe-and-link

Run:
```
python3 -m hallucinote.sync.push_cli probe-and-link <session_id> --song <slug> --snapshot /tmp/ableton-push-snapshot.json
```

The CLI matches by name (track names directly; return names after stripping Live's `<letter>-` prefix per W4-C) and writes `ableton_links` rows for each match. Re-runnable: if the link already exists, it's an upsert.

Display to the user:
- The matched lists (concise — `"linked 3 of 5 DB tracks; 2 will be created"`).
- The `notes` list verbatim if non-empty. Notes cover duplicate names, kind mismatches, and **case-only near-matches** (W5-B). If a DB track 'Drums' and a Live track 'drums' both appear unmatched, the note flags them as a case-variant pair so the user can decide whether to rename one before push (otherwise phase 3 silently creates a duplicate `Drums` next to the existing `drums`).
- The `unmatched_live_tracks` / `unmatched_live_returns` lists if non-empty — these are existing Live entities push will NOT touch.

**Confirmation gate when `unmatched_live_tracks` or `unmatched_live_returns` is non-empty (W12-C).** Live's default new-set scaffolding (`1-MIDI` / `2-MIDI` / `A-Reverb` / `B-Delay`) lands on the unmatched-Live side because the song's DB doesn't name those entities. That's almost always fine — the song will sit alongside them. But the same code path fires when the Live set already contains *another song*: those tracks/returns surface as "unmatched Live" too, and pushing additively on top of them silently jumbles two songs in one set. The signature you can't distinguish from probe-and-link's output alone is "default scaffolding" vs "someone else's song." So when either list is non-empty, **show the lists, then explicitly ask the user**: "These exist in Live and the push will not touch them — do you want to continue, or open a fresh Live set first? (yes/no)" Proceed only on explicit `yes`. If the lists are empty, no confirmation needed.

Unmatched DB entities will be created in phases 3/4. Unmatched Live entities are **not** touched — push is additive.

### Step 2 — Execute the push

Run:
```
python3 -m hallucinote.sync.push_cli execute <session_id> --song <slug>
```

This walks all ten phases in order, dispatching every MCP call directly to Live's Remote Script over TCP. Each phase's results are applied to the DB before the next phase plans, so `ableton_links` updates propagate as expected.

**Exit code contract:**

| Code | Meaning | What to do |
|------|---------|------------|
| 0 | All phases ok | Proceed to Step 3. |
| 1 | Partial — halted at a phase boundary | Read `.last-push-errors.json`, diagnose, fix in `build.py` (or fix the snapshot), rebuild, re-execute. Idempotent re-run skips already-applied rows. |
| 2 | Connection lost | Confirm Live is open + Hallucinote is selected as a Control Surface. Re-execute. |

`execute` writes two files into the song directory (`songs/<slug>/`):

- **`.last-push-state.json`** — per-phase status (`ok` / `skipped` / `halted` / `pending`), counts, the halted phase name. Always written.
- **`.last-push-errors.json`** — per-error forensics (key, tool, action, `args_summary`, error message, hint). Written only on failure. Stale files from prior partial runs are deleted on a clean re-run.

`args_summary` strips large payloads (notes arrays, breakpoints) to counts (`notes_count`, `breakpoints_count`). That's deliberate: this file is agent-readable, and reintroducing inline notes here would defeat the whole point of `execute`. Diagnose from the summary + the original `build.py`.

**Do not retry transient failures inside the loop.** `execute` doesn't retry. Idempotent re-run IS the retry — push is idempotent (W10-A), so already-applied rows skip on a second pass.

**Tempo / signature: bar-1 only.** Same constraint as the per-call path. Live's MCP exposes `ableton_session(set_tempo / set_signature)` which set the global (bar-1) value. Per-bar tempo / meter automation is a real MCP gap (see `hallucinote_mcp/.../guides/gaps.md`). The planner emits the bar-1 row and warns + skips the rest. Songs with mid-song tempo / meter changes will round-trip the bar-1 value only until the MCP gap closes.

### Step 3 — Final report

Read `songs/<slug>/.last-push-state.json` for the per-phase outcome. The CLI's stdout summary already includes the headline; the state file has the structured detail.

Surface the following to the user **in this order**:

1. **Outcome + totals.** `outcome` field (ok / partial / connection_lost) + per-phase ok/skipped/halted/pending counts.
2. **Per-domain summary.** A short line built from the phase counts (`"created 2 tracks, 1 return, 2 clips, 2 arrangement placements, 1 cue point; 1 envelope written"`).
3. **On partial / connection_lost: surface the top error patterns** from `.last-push-errors.json`'s `grouped_by_error` block — the CLI stdout already shows the top 3, but cite the file path so the user can read the full forensics if they want. Then tell the user the diagnose-and-fix loop: read the errors file, fix the underlying issue (usually in `build.py` or the snapshot), rebuild, re-run `push_cli execute`. Idempotent re-run skips the rows that landed cleanly.
4. **Live 12.4 UI heads-up — conditional, only emit the rows that apply to this push.** These two behaviors are not bugs; they look broken until the user knows the gesture that reveals state. Mention each only when the push's actual output makes the user likely to hit it:
   - **Mixer column hides on tracks with empty device chains.** Emit if any track in the push has zero devices (typically when the song's DB lists no devices for a track, or when the `devices` phase was skipped). One-liner: "Track 'X' has no devices yet → Live hides its mixer column; loading any instrument restores the faders." Name each affected track.
   - **Mixer / pan / send envelopes hidden in the MIDI clip envelope dropdown.** Emit if the `envelopes` phase wrote any `mixer_volume` / `mixer_pan` / `send_level` envelope on a MIDI clip. One-liner: "Mixer envelope(s) pushed onto MIDI clip 'Y' are playing (the fader will visibly move) but Live hides them in the clip's envelope dropdown by default. Right-click the affected mixer slider in Live and choose 'Show Modulation' to draw/edit them. Live remembers the choice per-set."

   If neither applies, skip this section entirely — don't add ceremony to a clean push.
5. **Cue-zoom hint, conditional (W15-D).** When the `cues` phase status is `ok` in `.last-push-state.json` and `calls_ok >= 1`, append a one-line hint: "Cues sit on Live's locator strip above the arrangement timeline. If they aren't visible: zoom out (Cmd + minus on macOS, Ctrl + minus on Windows) or scroll left; click any locator to jump the playhead there." Skip when the cues phase was skipped or halted.

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
- **`execute` exits 1 (partial)** — one or more calls failed; `execute` halted at the phase boundary. Read `.last-push-errors.json` for full forensics. Phases that ran cleanly are committed in Live + DB; the halted phase has partial state (`calls_ok` calls applied, `calls_failed` calls rejected); downstream phases didn't run. Fix the underlying issue (usually in `build.py` or the snapshot), rebuild, re-run `execute`. Push is idempotent — already-applied rows skip on re-run.
- **`execute` exits 2 (connection lost)** — Live wasn't reachable mid-push. Confirm Live is open + Hallucinote is selected as a Control Surface. Re-run `execute`.
- **`execute` raises a `ValueError` from inside a planner** — usually a strict-precondition issue (`plan_push_clip: track 'X' is not linked …`). Investigate: did Step 1's probe-and-link skip a track that should have matched? Show the user the error and stop the run.

Do not retry inside the loop. `execute` doesn't retry; re-running it is the retry.

## What NOT to do

- Do **not** drive the per-phase plan/apply loop yourself when doing a full-song push. `execute` is the canonical path; reverting to per-call MCP dispatch reintroduces the v1.0 context-budget ceiling (~500 KB inline JSON per 29-clip song).
- Do **not** skip probe-and-link "because the Live set is fresh." It's idempotent and cheap; running it always means the skill works the same against fresh and half-built sets.
- Do **not** invent new phases or reorder them. The order is set by Live's API constraints (W4-A: envelopes before arrangement; cue clamp: cues after arrangement). The planner enforces the order in `_PHASE_NAMES`.
- Do **not** retry MCP calls inside `execute`. Failures are rare and meaningful; re-running `execute` is the retry.
- Do **not** offer to pull back after pushing. Push is one direction; round-trips are a separate user request.

## Per-call MCP path (interactive iteration only)

For single-element edits — tweaking one clip's notes, nudging one parameter, A/B comparing two envelope shapes — the per-call MCP path is still available. Drive the relevant MCP namespace (`ableton_clip`, `ableton_device`, etc.) directly. Don't use it for full-song pushes; that's what `execute` is for.

`push_cli` still exposes `phases`, `plan`, and `apply` subcommands for development / debugging (e.g., "what would phase X emit right now?"). They're the same building blocks `execute` uses internally.

## Notes

- Real-Live performance: each phase typically takes < 1 second for falling-walking; the bottleneck is the per-call MCP round-trip, not the planner. A song with hundreds of envelopes will be slower.
- The throwaway `.prawduct/push-orchestrator.py` from Wave 3 is deleted by Wave 4 — this skill is now the only push driver. If you find references to that script in old reflections, they're historical.

## Post-push Live UX quirks the user should know about

Two Live 12.4 UI behaviors are inherent to Live's LOM + UI defaults, not Hallucinote bugs. Step 3 of the workflow surfaces them to the user **conditionally** — only when the push's actual content makes the user likely to hit them. Reference detail kept here so the skill body can stay concise:

1. **Mixer column hides on tracks with empty device chains.** Tracks that didn't have any devices loaded yet (e.g. before phase 7 runs, or after phase 7 if the song's DB lists no devices for a track) show no volume/pan/sends/master faders in Live's UI. The mixer state is still settable + functional via MCP; the UI just collapses. Loading any device into the chain restores the full column.

2. **Mixer / Pan / Send envelopes on MIDI clips are hidden in the per-clip envelope dropdown by default.** Empirical Live 12.4 + W4-A `.als` XML inspection confirm: envelopes written through `ableton_automation(write_envelope, target_kind='mixer_volume'|'mixer_pan'|'send_level')` on MIDI session/arrangement clips are **fully attached and functional during playback** (the fader visibly moves), but Live's per-MIDI-clip envelope-selector UI hides `Mixer → Track Volume` (et al.) from the dropdown by default. To make the envelope drawable + editable in the UI, the user must **right-click the affected mixer slider in Live and choose "Show Modulation"**. Live remembers the choice per-set. The envelope plays correctly without this step — the gesture is only for visibility/editability.
