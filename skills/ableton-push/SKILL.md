---
description: Push the Hallucinote DB into Ableton Live. Drives fourteen ordered phases (tempo → meter → tracks → returns → scenes → clips → mix → routing → devices → device-sidechain → envelopes → performed automation → arrangement → cues) against a fresh or partially-built Live set. Use when you want to materialize a song from the DB.
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Bash(python3 -m hallucinote.sync.push_cli *), Bash(python3 -m hallucinote.sync.compat *), mcp__hallucinote-mcp__ableton_session, mcp__hallucinote-mcp__ableton_track, mcp__hallucinote-mcp__ableton_return, mcp__hallucinote-mcp__ableton_browser, mcp__hallucinote-mcp__ableton_arrangement, mcp__hallucinote-mcp__ableton_device, mcp__hallucinote-mcp__ableton_clip, mcp__hallucinote-mcp__ableton_automation
argument-hint: <song-slug> [<session_id> | --new-session]
---

You are the Ableton push orchestrator. Take the DB state for a song, materialize it in Live by driving fourteen ordered phases through MCP, and report what was created.

$ARGUMENTS

## Required arguments

You need TWO pieces of information from `$ARGUMENTS`:

1. **The song slug** — filesystem-safe identifier. DB path: `songs/<slug>/<slug>-<branch>.db` (per-branch isolation; see `docs/snapshot-schema.md`). Outside a repo / detached HEAD falls back to `songs/<slug>/<slug>.db`.
2. **The session_id** — `ableton_sessions.id` binding the DB to the open Live set. Four paths:
   - **User passed an id**: use it.
   - **Omitted (the common case, WFL-7Q2N)**: just omit it — every subcommand auto-selects the only / most-recent session in the DB and echoes the choice on stderr (multi-song DBs refuse to guess). Relay the echo to the user.
   - **"New session" / first push**: pass `--auto-session` to `probe-and-link`; CLI mints the row and returns its id (`session_id`, `auto_session_created: true`). Tell the user the new id — one session per Live set, not per push.
   - **"Create a session named X"**: run `push_cli create-session --song <slug> --name X` first; capture the printed id.

If slug is missing, ask. For session, omit it unless the user signaled "first push" (then `--auto-session`) — don't ask the user for an id the CLI can discover.

## Workflow overview

```
0a. Probe Live for plugins                   → /tmp/ableton-push-plugins.json
0b. python -m hallucinote.sync.compat check  → refuse-and-confirm gate
1.  push_cli probe-and-link --probe          → mints session, upserts matches,
                                               reconciles stale links
2.  push_cli execute --probe                 → coherence check + dispatch all
                                               fourteen phases over MCP TCP
2a. (conditional) cleanup-default-scaffold   → delete leftover defaults
3.  Read .last-push-state.json + report.
```

The CLI is the single entrypoint — the agent doesn't touch per-call MCP dispatch for bulk-data phases. The per-call MCP path is fallback for interactive iteration only (single clip edits, parameter nudges).

### Step 0a — Probe Live for installed plugins

Call `ableton_browser(action='plugins_list')`. Write the response to `/tmp/ableton-push-plugins.json`. Shape: `{"plugins": [{"name": "...", "uri": "..."}, ...], "count": N}` — pass through unchanged.

If the probe fails or returns nothing, omit `--installed-plugins` in 0b. The compat report will require user confirmation on every third-party plugin.

### Step 0b — Compat check (portability gate)

```
python3 -m hallucinote.sync.compat check <slug> \
    --installed-plugins /tmp/ableton-push-plugins.json \
    --probe
```

`--probe` resolves every device's `preset_query` against Live's browser in-process. Omit it if Live or the MCP bridge isn't available; the gate still enforces user confirmation on unverified entries.

The CLI emits a JSON report with status buckets — `native`, `placeholder`, `third_party_ok`, `third_party_missing`, `third_party_unverified`, `preset_query_invalid`, `kind_unresolvable`, `kind_ambiguous`, `preset_query_unverified`. The CLI also prints a human summary explaining each bucket.

**Exit codes:** `0` = clean. `1` = at least one device in a problem bucket — display the offending entries and ask the user:

> *"Some devices won't load cleanly on this machine. Pushing now will fail at device-load for those (the chain stays empty; nothing is substituted). Continue anyway? (yes/no)"*

Proceed only on explicit `yes`. If `no`, point at `songs/<slug>/REQUIREMENTS.md` (regenerate with `compat write-requirements <slug>` if absent) and stop. Re-running compat after fixes is idempotent.

### Step 1 — Probe-and-link

```
python3 -m hallucinote.sync.push_cli probe-and-link <session_id> --song <slug> --probe
```

(First-push bootstrap: replace `<session_id>` with `--auto-session`.)

`--probe` calls `ableton_track(list)` + `ableton_return(list)` in-process via the MCP TCP client. Strict reconciliation drops any `ableton_links` row whose `ableton_index` no longer appears in the probe.

Display:
- Matched counts (`"linked 3 of 5 DB tracks; 2 will be created"`).
- `unlinked_stale_tracks` / `unlinked_stale_returns` counts if non-empty.
- `notes` verbatim if non-empty (duplicate names, kind mismatches, case-only near-matches).
- `unmatched_live_tracks` / `unmatched_live_returns` if non-empty.

**Confirmation gates when `unmatched_live_tracks` is non-empty.** Two cases; the CLI tells you which.

**Case 1: clean-default-scaffold.** `auto_session_created==true` AND `default_scaffold_unmatched_tracks` non-empty (canonical default names like `1-MIDI` / `2-MIDI` / `3-Audio` / `4-Audio`). Default the prompt to "yes, clean":

> *"Live has its default scaffold tracks that this song doesn't use. Delete them after the push so only the song's tracks remain? (Y/n)"*

If accepted, hold the list — Step 2a deletes them after `execute` succeeds (push-then-delete avoids Live's ≥1-track constraint).

**Case 2: generic unmatched-Live.** Refuse-and-confirm without offering destructive cleanup:

> *"These exist in Live and the push will not touch them — do you want to continue, or open a fresh Live set first? (yes/no)"*

Proceed only on explicit `yes`.

### Step 2 — Execute

```
python3 -m hallucinote.sync.push_cli execute <session_id> --song <slug> --probe
```

`--probe` runs a coherence check on a freshly-probed Live snapshot before dispatching. Walks all fourteen phases in order, dispatching every MCP call directly over TCP.

**The transport PLAYS during the `performed_automation` phase.** Master/group/return arcs are gesture-recorded in real time — all changed arcs record in ONE pass over their union span (the plan names that union-span wall-clock and a loud alert lists every span it will overwrite). Audible playback during push is expected, not a bug. Unchanged arcs are fingerprint-skipped (so a hand-edited lane survives); a `--reset` DB or a new session re-performs everything.

**Exit codes:**

| Code | Meaning | What to do |
|------|---------|------------|
| 0 | All phases ok | Step 3. |
| 1 | Partial — halted at a phase boundary | The summary's "Halt cause" block names the failing tool.action, the error, and a next step — act on that. Fix in `build.py`, rebuild, re-execute. Re-run is idempotent. `.last-push-errors.json` has per-call forensics if the summary isn't enough. |
| 2 | Connection lost | See `ableton://guides/error-recovery`. Re-execute. |

`execute` writes:
- **`.last-push-state.json`** — per-phase status, counts, halted phase name. Always written. **Flushed after every phase (PSH-5T9D)**, so it's pollable mid-run: `current_phase` names the phase running now, and a `scope` field records any phase-targeting (null for a full run). `execute` also streams per-phase start/finish lines to **stderr** (stdout stays the parseable summary) — so a multi-minute push has a heartbeat (esp. the realtime `performed_automation` phase).
- **`.last-push-errors.json`** — per-error forensics. Written only on failure. `args_summary` redacts large payloads to counts.

**Recovery / scoped runs (PSH-2R7K).** `execute` accepts phase-targeting so a halt doesn't cost a full replay (incl. the ~8-11 min perform):
- `--resume` — continue from the last run's halted phase (reads `.last-push-state.json`).
- `--start-at PHASE` / `--from PHASE` — run from a phase to the end (resume case; assumes earlier phases already ran — it does NOT satisfy dependencies, e.g. `--start-at clips` needs `tracks` linked from a prior pass).
- `--only PHASE` — run exactly one phase (e.g. `--only devices`).
- `--stop-after PHASE` — bound a run to a prefix.
A typo'd phase name teaches with the valid list (exit 2). Scoped runs keep the coherence gate + idempotency.

**Tempo / signature: bar-1 only.** Live's MCP exposes `set_tempo` / `set_signature` for the global value. Per-bar tempo / meter automation is an MCP gap (see `ableton://guides/gaps`). The planner emits bar-1 and warns + skips the rest.

### Step 2a — Clean default-scaffold tracks (conditional)

Run only when Step 1 returned a non-empty `default_scaffold_unmatched_tracks` list AND the user accepted AND Step 2 exited 0.

```
python3 -m hallucinote.sync.push_cli cleanup-default-scaffold <session_id> --song <slug>
```

Probes Live, validates every unmatched parent is a canonical default (refuses-and-teaches on non-canonical names), checks deletes won't leave Live with zero tracks, dispatches `ableton_track(action='delete')` in descending index order, re-runs probe-and-link.

If the subcommand refuses, stderr JSON names the refusal (`non_canonical_tracks` / `non_canonical_returns` / `would_empty_live_tracks` / `nothing_to_do`). Hand-resolve or skip.

### Step 3 — Final report

Read `songs/<slug>/.last-push-state.json`. Surface in this order:

1. **Outcome + totals.** `outcome` field + per-phase counts.
2. **Per-domain summary.** `"created 2 tracks, 1 return, 2 clips, 2 arrangement placements, 1 cue point; 1 envelope written"`.
3. **On partial / connection_lost:** relay the summary's "Halt cause" lines (cause + next step) verbatim. Tell the user the loop: act on the next step → fix → rebuild → re-execute. Idempotent. Cite `.last-push-errors.json` only when per-call forensics are needed.
3a. **Unverified performs.** `.last-push-errors.json` can exist even on exit 0: a `tool: "apply_push_results"` record means a performed arc's write came back `automation_state != 1` — nothing was recorded, the next push retries that arc. Surface it; if it never verifies, the parameter is likely automation-overridden or locked in Live (the failure policy is yours, not the CLI's).
4. **Live 12.4 UI heads-up — conditional, only emit rows that apply:**
   - **Empty mixer column.** If any track has zero devices: *"Track 'X' has no devices yet → Live hides its mixer column; loading any instrument restores the faders."*
   - **Hidden mixer envelopes on MIDI clips.** If `envelopes` wrote any `mixer_volume` / `mixer_pan` / `send_level` on a MIDI clip: *"Mixer envelope(s) on MIDI clip 'Y' are playing but Live hides them in the clip's envelope dropdown by default. Right-click the affected mixer slider and choose 'Show Modulation'. Live remembers the choice per-set."*
5. **Cue-zoom hint** (conditional, when `cues` status is `ok` and `calls_ok >= 1`): *"Cues sit on Live's locator strip above the arrangement timeline. If they aren't visible: zoom out or scroll left."*

## Phase-by-phase tool mapping

| Phase | Tool(s) emitted |
|---|---|
| `tempo_map` | `ableton_session(action='set_tempo')` (bar-1 only) |
| `time_signature_map` | `ableton_session(action='set_signature')` (bar-1 only) |
| `tracks` | `ableton_track(action='create')` |
| `returns` | `ableton_return(action='create')` |
| `scenes` | `ableton_scene(action='ensure_count')` |
| `clips` | `ableton_clip(action='create' / 'replace_notes')` |
| `mix` | `ableton_track(set_property / set_send)`, `ableton_return(set_property)`, `ableton_session(set_master_property)` |
| `devices` | `ableton_device(action='load' / 'set_parameter')` |
| `envelopes` | `ableton_automation(action='write_envelope')` |
| `performed_automation` | `ableton_automation(action='perform_batch')` — realtime gesture recording, all changed arcs in one union-span pass; transport plays |
| `arrangement` | `ableton_clip(action='duplicate_to_arrangement')` |
| `cues` | `ableton_arrangement(action='cue_create_batch')` |

## Failure modes

- **`probe-and-link` exits non-zero**: snapshot malformed, DB path wrong, or session_id unknown. Show stderr.
- **`execute` exits 1 (partial)**: act on the stdout "Halt cause" block (cause + next step); fix in `build.py`/snapshot, rebuild, re-run `execute`. Idempotent — already-applied rows skip. `.last-push-errors.json` has per-call forensics.
- **`execute` exits 2 (connection lost)**: see `ableton://guides/error-recovery`. Re-execute.
- **`ValueError` from a planner**: usually a strict-precondition issue. Show the error and stop.

Do not retry inside the loop — re-running `execute` is the retry.

## What NOT to do

- Do not drive the per-phase plan/apply loop yourself for full-song pushes — `execute` is canonical.
- Do not skip probe-and-link "because the Live set is fresh" — it's idempotent and cheap.
- Do not reorder phases — the order is set by Live's API constraints.
- Do not retry MCP calls inside `execute`.
- Do not offer to pull back after pushing — push is one direction.

## Per-call MCP path (interactive iteration only)

For single-element edits (tweak one clip's notes, nudge one parameter), drive the relevant MCP namespace directly. `push_cli` also exposes `phases`, `plan`, `apply` subcommands for debugging.
