---
description: Push the Hallucinote DB into Ableton Live. Drives fourteen ordered phases (tempo → meter → tracks → returns → scenes → clips → mix → devices → routing → device-sidechain → envelopes → performed automation → arrangement → cues) against a fresh or partially-built Live set. Use when you want to materialize a song from the DB.
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Bash, mcp__hallucinote-mcp__ableton_session, mcp__hallucinote-mcp__ableton_track, mcp__hallucinote-mcp__ableton_return, mcp__hallucinote-mcp__ableton_browser, mcp__hallucinote-mcp__ableton_arrangement, mcp__hallucinote-mcp__ableton_device, mcp__hallucinote-mcp__ableton_clip, mcp__hallucinote-mcp__ableton_automation
argument-hint: <song-slug> [<session_id> | --new-session]
---

You are the Ableton push orchestrator. Take the DB state for a song, materialize it in Live by driving fourteen ordered phases through MCP, and report what was created.

$ARGUMENTS

> **Running engine commands.** The engine ships in the plugin's uv env — there is no separate install. Resolve `$PY` once from `ableton://server/info`'s `python`; the command blocks below run as `"$PY" -m hallucinote.cli …`. See [`docs/running-the-engine.md`](../../docs/running-the-engine.md).

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
0b. hallucinote compat check                 → refuse-and-confirm gate
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
"$PY" -m hallucinote.cli compat check <slug> \
    --installed-plugins /tmp/ableton-push-plugins.json \
    --probe
```

`--probe` resolves every device's `preset_query` against Live's browser in-process, and — when the song loads content from an Ableton Pack — reads this machine's installed Packs so an absent one is named. Omit it if Live or the MCP bridge isn't available; the gate still enforces user confirmation on unverified entries, and Pack content then reports as a requirement (`pack_content`) rather than a refusal, because nothing looked.

The CLI emits a JSON report covering **two independent families**. Devices, under `entries` with status buckets `native`, `placeholder`, `third_party_ok`, `third_party_missing`, `third_party_unverified`, `preset_query_invalid`, `kind_unresolvable`, `kind_ambiguous`, `preset_query_unverified`, `pack_content`, `pack_content_missing`, `user_content`. Samples, under `samples` with `sample_ok`, `sample_missing`, `sample_unreadable`, `sample_not_a_file`, `sample_unresolvable`, and their own `samples_*` summary counts — each sample row carries `use_site`, `"clip"` or `"device"`, because a sampler's missing sample and a clip's are the same fault in different places. The report is JSON and nothing else — there is no human summary to read out; you compose one from the entries.

**A native class is not native content.** `pack_content` / `pack_content_missing` / `user_content` mark devices whose Live class ships with Live but whose SOUND does not — a Drum Rack out of an Ableton Pack, a Simpler pointing into the author's user library. `pack_content` and `user_content` are requirements for the *next* machine, not failures on this one, so they do not set exit 1; `pack_content_missing` does, because `--probe` looked and the Pack is not here.

**Exit codes:** `0` = clean. `1` = at least one DEVICE or at least one SAMPLE in a problem bucket. **Read which family actually fired before you speak** — a sample-only failure leaves every device bucket empty, so an agent that displays only devices shows the user nothing and asks them to confirm a refusal it cannot evidence. Display the offending entries from whichever family is non-empty, then ask:

> *Devices only:* "Some devices won't load cleanly on this machine. Pushing now will fail at device-load for those (the chain stays empty; nothing is substituted). Continue anyway? (yes/no)"
>
> *Samples only:* "Some clips or samplers reference samples that are missing or unreadable on this machine. Pushing now will place clips Live cannot play and samplers with nothing loaded. Continue anyway? (yes/no)"
>
> *A missing Pack:* "This song loads content from Ableton Pack(s) this machine doesn't have; those devices will come up empty. Continue anyway? (yes/no)" — name the Packs.
>
> *Both:* name both, in that order.

Proceed only on explicit `yes`. If `no`, point at `songs/<slug>/REQUIREMENTS.md` (regenerate with `compat write-requirements <slug>` if absent) and stop. Re-running compat after fixes is idempotent.

### Step 1 — Probe-and-link

```
"$PY" -m hallucinote.cli push probe-and-link <session_id> --song <slug> --probe
```

(First-push bootstrap: replace `<session_id>` with `--auto-session`.)

`--probe` calls `ableton_track(list)` + `ableton_return(list)` in-process via the MCP TCP client. Strict reconciliation drops any `ableton_links` row whose `ableton_index` no longer appears in the probe.

Display:
- Matched counts (`"linked 3 of 5 DB tracks; 2 will be created"`).
- `unlinked_stale_tracks` / `unlinked_stale_returns` / `unlinked_stale_clips` counts if non-empty. (`unlinked_stale_clips` are clip links cascade-dropped because their parent track was no longer linked — the set-swap recovery, SYN-3C8K.)
- `notes` verbatim if non-empty (duplicate names, kind mismatches, case-only near-matches).
- `unmatched_live_tracks` / `unmatched_live_returns` if non-empty.

**Re-materialize the arrangement after a note edit (ARR-PROJ).** Editing notes in `build.py` updates the *session* clips. To rebuild the timeline: rebuild, then **`execute --only arrangement`** — the arrangement phase is a pure projection of the DB. It CLEARS each track's existing arrangement clips (by probing Live) and re-creates them from the DB every push (note-only clips fill straight from the DB; envelope-bearing clips duplicate from the session clip, so those want `execute --only clips` first). Idempotent — same DB → same arrangement, regardless of the timeline's prior state — so there is **no** manual "delete the stale clips by hand, then re-duplicate" step (the old SYN-4R7P dance is retired). A post-phase integrity assert HALTs the push if any materialized clip's notes diverge from the DB, so a silent drop/stack becomes a loud failure, never an `OK`.

**Confirmation gates when `unmatched_live_tracks` is non-empty.** Two cases; the CLI tells you which.

**Case 1: clean-default-scaffold.** `default_scaffold_unmatched_tracks` non-empty (canonical default names like `1-MIDI` / `2-MIDI` / `3-Audio` / `4-Audio`). Fires on a fresh `--auto-session` push AND on a reused session pushed onto a fresh default set (the set-swap case — SYN-3C8K dropped the earlier `auto_session_created==true` requirement; the CLI populates the field either way). Default the prompt to "yes, clean":

> *"Live has its default scaffold tracks that this song doesn't use. Delete them after the push so only the song's tracks remain? (Y/n)"*

If accepted, hold the list — Step 2a deletes them after `execute` succeeds (push-then-delete avoids Live's ≥1-track constraint).

**Case 2: generic unmatched-Live.** Refuse-and-confirm without offering destructive cleanup:

> *"These exist in Live and the push will not touch them — do you want to continue, or open a fresh Live set first? (yes/no)"*

Proceed only on explicit `yes`.

### Step 2 — Execute

```
"$PY" -m hallucinote.cli push execute <session_id> --song <slug> --probe
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

Mutual exclusion: `--only` cannot combine with `--start-at`/`--stop-after`/`--resume`; `--resume` cannot combine with `--only`/`--start-at` (it derives `--start-at`), but **may** combine with `--stop-after` to resume into a bounded window. A typo'd phase name teaches with the valid list (exit 2). Scoped runs keep the coherence gate + idempotency.

**Tempo / signature: bar-1 only.** Live's MCP exposes `set_tempo` / `set_signature` for the global value. Per-bar tempo / meter automation is an MCP gap (see `ableton://guides/gaps`). The planner emits bar-1 and warns + skips the rest.

### Step 2a — Clean default-scaffold tracks (conditional)

Run only when Step 1 returned a non-empty `default_scaffold_unmatched_tracks` list AND the user accepted AND Step 2 exited 0.

```
"$PY" -m hallucinote.cli push cleanup-default-scaffold <session_id> --song <slug>
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
| `arrangement` | projection rebuild — `ableton_clip(action='delete', location='arrangement')` to clear, then `ableton_clip(action='create', location='arrangement')`+`set_notes` per note-only placement (`duplicate_to_arrangement` only for envelope-bearing clips) |
| `cues` | `ableton_arrangement(action='cue_create_batch')` |

## Failure modes

- **`probe-and-link` exits non-zero**: snapshot malformed, DB path wrong, or session_id unknown. Show stderr.
- **`execute` exits 1 (partial)**: act on the stdout "Halt cause" block (cause + next step); fix in `build.py`/snapshot, rebuild, re-run `execute`. Idempotent — already-applied rows skip. `.last-push-errors.json` has per-call forensics.
- **Arrangement looks wrong (missing / doubled notes), or you hand-edited clips in Live?** The arrangement phase is a pure projection (clear + rebuild from the DB every push) guarded by a post-phase integrity assert that HALTs on divergence — a corrupt materialize fails loud, never `OK`. To audit the current DB↔Live arrangement at any time, run **`"$PY" -m hallucinote.cli verify-arrangement --song <slug>`**: it probes Live via the note API and reports `extra` / `missing` / `mismatch` per (track, section), exit 0 = faithful, 1 = divergence (rebuild `build.py` first to compare build.py↔Live). If the push halts with `lane_unreadable` for a track, Live could not list that track's arrangement lane — push therefore neither cleared nor rebuilt it, so its old clips are still there. Re-run `execute --only arrangement --probe` (idempotent); if it keeps failing on the same track, inspect that lane in Live for a clip Live can't read. The old SYN-4R7P `IndexError: clip_index out of range` from a stale arrangement link can no longer occur — clear+rebuild never refreshes into a dead index, so the fix for a wrong-looking timeline is simply to re-run `execute --only arrangement`.
- **`devices` halts with `REFUSING to load …`**: the phase found a device the DB authors at a position Live already has something at, and could not match the two (class drift), or could not read that parent's chain at all. It refuses rather than loading — Live 12.4 has no reorder API, so a load TAIL-APPENDS, and appending onto a chain that already has the device silently doubles the signal path (and doubles again on every later push). The message names the track and what it saw. Three fixes, in the order to try them: run `probe-and-link --probe` to bind the chain that is already there (nothing changes in Live); or re-snapshot the set (`/song-snapshot`) so the DB describes Live's order; or, when the **DB's** order is the one you want, rebuild the chain into it with **`"$PY" -m hallucinote.cli chain-rebuild --song <slug> --track <live index> --from-position <N>`** — it captures the chain, journals it to disk before the first delete, deletes descending, reloads in the DB's order and restores every surviving device's parameters, refusing to report success until Live reads back equal (`docs/song-authoring-conventions.md` → *Reordering / inserting mid-chain*). Then re-run `execute`. To do that rebuild as part of the push instead, re-run with **`execute --reconcile-chains`** — same orchestration, opt-in per push (it is destructive and holds Live for minutes, so it never runs automatically). In-rack hand edits do not survive a rebuild: a rack comes back via its preset.
- **`devices` halts with `devices integrity: … DUPLICATE`**: the post-phase assert re-probed Live and found a chain carrying more of a device class than the DB authors there. This set is already doubled and a re-push cannot undo it (no reorder API): delete the duplicate devices in Live, or push into a fresh set, then re-run `probe-and-link --probe`. `chain-rebuild` is **not** the fix here — it rebuilds a chain into the DB's order, and a doubled chain first needs the extra copy gone. Devices Live carries that the DB never authored (a stock return effect, a hand-dropped utility) are surfaced as warnings, not halts.
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

## Exit criteria — this stage is done when

Push reports OK **and every phase the brief depends on actually moved
something.** A clean run is not evidence of a complete one: the phases that can
silently no-op are `envelopes`, `performed automation`, `arrangement` and
`devices`, and each of them reports success on zero work. If the brief calls for
a pitch bend, a filter sweep or a rise and the envelopes phase pushed nothing,
that is a **gap, not a clean run**.

One class of that gap now reports itself. A phase that left something the song
asked for un-materialized — because it could not **determine** what to do (a
failed per-track probe, a link that isn't there), or because it determined it
perfectly well and the route cannot **carry** it (an authored automation edge
shorter than the perform route's record tick) — is marked
`[GAP] … NOT PUSHED — N things the push could not carry`, the run's outcome is
`INCOMPLETE`, the exit code is non-zero, and the summary lists the reason
verbatim under `INCOMPLETE —`. Do not read that as a halt (nothing failed) and
do not read it as clean. Fix the named precondition and re-run
`execute --probe`; it re-probes and is idempotent. `skipped (nothing to push)`
still means exactly that — there was no work — and remains the case you have to
judge yourself against the brief.

**Route the gap to the stage that owns it**, not reflexively back one step:

- `envelopes` · `performed automation` · `arrangement` moved nothing the brief
  requires → **`/compose-part`** (stage 3). These are authored in `build.py`.
- `devices` moved nothing the brief requires → **`/song-pick-instruments`**
  (stage 2). The chain is authorship that ships in the snapshot, so a missing
  device is a sound-design gap, not a composition one.

One caveat specific to `devices`: it **diff-reconciles**, so zero work legitimately
means "already current". Distinguish the two by checking whether the thing the
brief names is actually present in the set — not by the phase count alone. A push
into a set that already matches proves nothing.

The reverse of that caveat is now guarded rather than trusted: a devices phase
that reports work it did NOT need to do (re-loading a chain Live already had)
used to double every effect silently. `execute` now probes each parent's chain
before planning, binds what is already there, refuses to append onto an occupied
slot, and re-probes afterwards to assert no chain came out duplicated.

Full model: [docs/song-workflow.md](../../docs/song-workflow.md#stage-exit-criteria).

## Next: read the mix

After a full-song push, capture + analyze (`ableton_render` → `ableton_analysis`
build the MixReport), then run **`/mix-review`** (needs Max for Live) to interpret
it against intent — masking, loudness, feel, energy per section. That's the checkpoint after the mix
materializes (the counterpart to `/compose-review` before it). The full lifecycle
is `/song-workflow`.
