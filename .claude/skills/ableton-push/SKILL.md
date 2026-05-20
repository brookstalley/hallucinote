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

Push is the **DB → Ableton** direction. The DB is the source of truth; Live is built from it. Push is **additive**: `execute` itself does not delete Live state that isn't in the DB. The one exception is W18-D's clean-default-scaffold workflow (Step 2a): on a first push (`--auto-session`) onto Live's canonical default scaffold, the skill offers to delete the leftover defaults *after* execute has populated the song's tracks alongside them — an explicit, user-opted-in cleanup, not silent destruction.

The ten phases run in a strict order set by Live's API constraints (e.g., envelopes must be written on session clips BEFORE `duplicate_to_arrangement`, per W4-A; cues must be written AFTER the arrangement is laid down, per Live's `[0, last_event_time]` clamp). The orchestrator (`push_cli execute`) owns this order — your job is to set up the session (probe-and-link + confirmation gates), invoke `execute` once, then read the on-disk state file and report. The per-call MCP path is preserved for interactive single-element iteration (see end of this file), not for full-song pushes.

## Required arguments

You need TWO pieces of information from `$ARGUMENTS`:

1. **The song slug** (required) — filesystem-safe identifier matching the song's directory + DB filename. The DB lives at `songs/<slug>/<slug>-<branch>.db` per W12-A (per-branch convention; outside a repo / detached HEAD falls back to `songs/<slug>/<slug>.db`).
2. **The session_id** — the `ableton_sessions.id` row that binds the DB to the currently-open Live set. Three paths to provide it:
   - **User passed an explicit id**: use it directly.
   - **User said "new session" / first push for this song**: pass `--auto-session` to `probe-and-link` (W9-B) — the CLI creates the row and returns its id in the response (`session_id` field, `auto_session_created: true`). Tell the user the new id so they can reuse it for subsequent pushes (the user typically wants ONE session per Live set, not a new one per push).
   - **User said "create a session named X"**: run `push_cli create-session --song <slug> --name X` first; capture the printed id; use it.

If the slug is missing, ask the user. For session, default to `--auto-session` only if the user explicitly signaled "this is the first push for this song / new session" — otherwise ask.

## Workflow overview (probe-driven; W18-B)

```
0a. Probe Live for installed plugins         → /tmp/ableton-push-plugins.json
0b. python -m hallucinote.sync.compat check  → refuse-and-confirm gate
1.  python -m hallucinote.sync.push_cli probe-and-link --probe → orchestrator
        probes Live, mints session if needed, upserts matches,
        reconciles stale links (one canonical entrypoint owns all three
        pieces of state: snapshot, sessions, links).
2.  python -m hallucinote.sync.push_cli execute --probe → coherence check
        + dispatch all ten phases against Live's Remote Script.
2a. (W18-D, only if probe-and-link surfaced default_scaffold_unmatched_tracks
     AND the user opted in) delete the canonical default tracks now that
     the song's own tracks survive as the ≥1-track guarantee — descending
     track-index order so the lower defaults don't renumber under you —
     then re-run probe-and-link --probe to relink to the shifted indices.
3.  Read .last-push-state.json + report.
```

**Probe-driven means the orchestrator owns the three pieces of per-machine state.** The DB carries `ableton_sessions` (this DB ↔ this Live set) and `ableton_links` (DB rows ↔ Live indices); the snapshot of Live's current track/return shape is regenerated on every probe-and-link invocation via `--probe`, which dispatches `ableton_track(list)` + `ableton_return(list)` in-process over the same MCP TCP client `execute` uses. **No tmp snapshot file persists between runs.** Strict reconciliation in probe-and-link removes any `ableton_links` row whose `ableton_index` doesn't appear in the fresh probe, so deleting a linked Live track no longer leaves a stale binding that the next push would dispatch against.

The `execute` subcommand (W10-E2) runs all ten phases inside the CLI process, dispatching every MCP call directly to Live's Remote Script over TCP. The agent doesn't touch the per-call MCP path for the bulk-data phases. **This is the default and only path for full-song pushes** — agent-side per-phase dispatch is the v1.0 ceiling (each `ableton_clip(create, notes=[…])` carries ~10–30 KB of inline JSON in the agent's tool-use block; a 29-clip song burned ~500 KB of context). `execute` removes that cost entirely.

The per-call MCP path documented at the bottom of this file is the **fallback** for interactive iteration (single clip edits, parameter nudges, A/B parameter comparisons) — not full-song pushes.

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
python3 -m hallucinote.sync.push_cli probe-and-link <session_id> --song <slug> --probe
```

(For first-push bootstrap, replace `<session_id>` with `--auto-session` and the CLI mints the row, prints its id, and uses it for this run. Note the id and reuse it for subsequent pushes — one session per Live set, not per push.)

`--probe` is the W18-B canonical path: the CLI calls `ableton_track(list)` + `ableton_return(list)` in-process over the MCP TCP client and feeds the fresh shape straight into matching. No tmp snapshot file involved. Strict reconciliation runs at the end of the pass — any `ableton_links` row whose `ableton_index` no longer appears in the live probe is deleted (closes the "user deleted a Live track between pushes" drift bug; surfaces in `unlinked_stale_tracks` / `unlinked_stale_returns`).

(The `--snapshot <path>` form is preserved for tests and offline debugging — it reads a pre-probed JSON file instead of dispatching to Live. Don't use it during normal authoring; staleness is what `--probe` is designed to eliminate.)

The CLI matches by name (track names directly; return names after stripping Live's `<letter>-` prefix per W4-C) and writes `ableton_links` rows for each match. Re-runnable: if the link already exists, it's an upsert; if the link is stale, strict reconciliation drops it.

Display to the user:
- The matched lists (concise — `"linked 3 of 5 DB tracks; 2 will be created"`).
- If `unlinked_stale_tracks` or `unlinked_stale_returns` is non-empty, mention the count — "cleared 1 stale link (the previously-linked Live track at index 5 is gone)." This is recovery, not an error.
- The `notes` list verbatim if non-empty. Notes cover duplicate names, kind mismatches, and **case-only near-matches** (W5-B). If a DB track 'Drums' and a Live track 'drums' both appear unmatched, the note flags them as a case-variant pair so the user can decide whether to rename one before push (otherwise phase 3 silently creates a duplicate `Drums` next to the existing `drums`).
- The `unmatched_live_tracks` / `unmatched_live_returns` lists if non-empty — these are existing Live entities push will NOT touch.

**Confirmation gates when `unmatched_live_tracks` is non-empty.** Two distinct cases; the CLI tells you which.

**Case 1: clean-default-scaffold (W18-D).** When `auto_session_created==true` AND `default_scaffold_unmatched_tracks` is non-empty (every unmatched Live track has a canonical default name — `1-MIDI` / `2-MIDI` / `3-Audio` / `4-Audio`), this is a first push onto a fresh Live set. The user almost certainly wants the song's tracks to be the only tracks, not alongside the defaults. **Default the prompt to "yes, clean":**

> "Live has its default scaffold tracks ({1-MIDI, 2-MIDI, 3-Audio, 4-Audio}) that this song doesn't use. Delete them after the push so only the song's tracks remain? (Y/n)"

If the user accepts, hold the `default_scaffold_unmatched_tracks` list — Step 2a will delete them **after** `execute` runs. Push-then-delete (strategy (b) from backlog #59) avoids the ≥1-track Live constraint: by the time the deletes fire, the song's own tracks are already in Live, so removing the defaults never leaves Live with zero tracks. The opposite ordering (delete first, push after) trips W18-E's last-track refuse-and-teach when the fourth default is the last surviving track.

**Case 2: generic unmatched-Live (W12-C).** Either `auto_session_created` is false (the user is pushing to a known Live session), OR the unmatched Live tracks include non-canonical names. We can't distinguish "another song's tracks already in Live" from "user customised the defaults" from probe output alone, so refuse-and-confirm without offering destructive cleanup:

> "These exist in Live and the push will not touch them — do you want to continue, or open a fresh Live set first? (yes/no)"

Proceed only on explicit `yes`. If the unmatched-Live lists are empty, no confirmation needed.

Unmatched DB entities will be created in phases 3/4. Unmatched Live entities are **not** touched by `execute` itself — push is additive. Step 2a's post-execute cleanup is the only destructive path, and it fires only on explicit user opt-in in Case 1.

### Step 2 — Execute the push

Run:
```
python3 -m hallucinote.sync.push_cli execute <session_id> --song <slug> --probe
```

`--probe` runs the W18-A coherence check on a freshly-probed Live snapshot before dispatching phases — refuses with a teaching error if any link is stale or the session row is missing, so a state-drift case the previous step missed (or that opened up between probe-and-link and execute) doesn't quietly corrupt the push. The `--snapshot <path>` form is preserved for the same offline-debugging reason as in Step 1; the `--probe` shape is the canonical one in normal flow.

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

### Step 2a — Clean default-scaffold tracks (W18-D; conditional)

Run this step **only** when Step 1 returned a non-empty `default_scaffold_unmatched_tracks` list AND the user accepted the cleanup prompt AND Step 2's `execute` exited 0 (`outcome == "ok"`). Skip otherwise — destructive cleanup on a partial push is a bigger drift bug than the cosmetic defaults it would solve.

**Why this step lives after `execute`, not before.** Live requires ≥1 track in a set (W18-E refuses-and-teaches at the MCP layer on the last-track delete). If we deleted the defaults before `execute`, the fourth delete would fail — Live would still have only the three remaining defaults, and removing the last default would leave Live with zero tracks. The song's own tracks have to land first; once they're alongside the defaults, deleting any of the defaults is safe because the song's tracks satisfy the ≥1 guarantee.

**Order of operations.**

1. Sort the `default_scaffold_unmatched_tracks` indexes in **descending** order. Lower indexes shift downward when a higher index is deleted, so descending-order deletion lets the remaining captured indexes stay valid through the loop. Ascending-order deletion would silently delete the wrong tracks after the first iteration.

2. For each index in that order, call:
   ```
   ableton_track(action='delete', track_index=N)
   ```
   If one delete refuses (e.g., Live shifted differently than expected, or the user interactively edited the set between Step 2 and Step 2a), stop the loop. Tell the user what landed, what remains, and that the rest can be cleaned up manually.

3. After the deletes complete, **re-run probe-and-link to reconcile the shifted indexes**:
   ```
   python3 -m hallucinote.sync.push_cli probe-and-link <session_id> --song <slug> --probe
   ```
   The song's tracks survived but their `track_index` shifted downward as defaults were removed. The strict reconciliation pass deletes the now-stale links pointing at the deleted defaults; the name-matching pass re-binds the song's DB tracks to their new Live indexes. The link rewrites go through `M.link_db_to_ableton`'s upsert path, so the per-`(session, db_kind, db_id)` rows update in place — no orphans, no duplicates.

You don't need a fresh `execute` after the cleanup — the song is already materialised; the re-link only repairs the index bookkeeping so the next iteration's push lands cleanly.

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
- **Provenance (W23-C).** Every `push_cli execute` invocation opens one `requests` row with `kind='push'` and closes it with the push's outcome (`ok` / `partial` / `failed`). Every link-binding event the apply layer emits is threaded back to that request_id. Future sessions can answer "what was the last push for this song" via `Q.get_latest_request_for_song(conn, song_id, kind='push')` and drill into "what did that push touch" via `Q.get_events_for_request(conn, rid)`. No skill-side ceremony required — the CLI does it.

## Post-push Live UX quirks the user should know about

Two Live 12.4 UI behaviors are inherent to Live's LOM + UI defaults, not Hallucinote bugs. Step 3 of the workflow surfaces them to the user **conditionally** — only when the push's actual content makes the user likely to hit them. Reference detail kept here so the skill body can stay concise:

1. **Mixer column hides on tracks with empty device chains.** Tracks that didn't have any devices loaded yet (e.g. before phase 7 runs, or after phase 7 if the song's DB lists no devices for a track) show no volume/pan/sends/master faders in Live's UI. The mixer state is still settable + functional via MCP; the UI just collapses. Loading any device into the chain restores the full column.

2. **Mixer / Pan / Send envelopes on MIDI clips are hidden in the per-clip envelope dropdown by default.** Empirical Live 12.4 + W4-A `.als` XML inspection confirm: envelopes written through `ableton_automation(write_envelope, target_kind='mixer_volume'|'mixer_pan'|'send_level')` on MIDI session/arrangement clips are **fully attached and functional during playback** (the fader visibly moves), but Live's per-MIDI-clip envelope-selector UI hides `Mixer → Track Volume` (et al.) from the dropdown by default. To make the envelope drawable + editable in the UI, the user must **right-click the affected mixer slider in Live and choose "Show Modulation"**. Live remembers the choice per-set. The envelope plays correctly without this step — the gesture is only for visibility/editability.
