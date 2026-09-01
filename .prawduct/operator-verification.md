# Operator Verification — pending attended-run / live-integration checks

Entries here are checks that need a human operator and/or a live Ableton
session that wasn't available when the work landed. `/pr create` surfaces
pending entries when `operator_verification_required: true`.

> **2026-06-14 — blanket acceptance (user, brooks@tangentry.com).** During the
> SNP-MIX-CLUSTER close-out the user directed: *"Consider all operator-verification
> complete and passed."* Every entry below is therefore treated as **operator-accepted
> (user-asserted, not agent-Live-verified)** as of this date — this is the operator
> vouching for the checks, the only authority that can. Items closed on this basis:
> **SNP-8R4K** + **SDC-7K3M** (→ backlog Archive), the **SNP-4K7M** master-device Live
> round-trip, and **MIX-3S7P** chunk-2 render verification. New entries added *after*
> this date are not covered and block PRs as usual.

---

## EFFORT-S-BURNDOWN — the fingerprint flip re-vendors, and the #264 fix works in real Live (2026-08-22) — PENDING

This branch changed seven files inside `_FINGERPRINT_PATHS` (`dispatcher.py`,
`actions/clip.py`, `handlers/arrangement.py`, `handlers/automation.py`,
`handlers/clip.py`, `handlers/device.py`, `remote_script/dispatch.py`).
`_compute_content_fingerprint`
hashes file BYTES, so the comment-only pragma rewrites flip `__version__` just
as the behavioral edits do.

**Fingerprint flips → re-vendor the Remote Script + full Live quit/reopen
required** before any of this reaches Live. Until that happens the vendored
Remote Script fails the version handshake, and #264 — the branch's only
Live-executed behavior change — is inert with nothing telling the operator why.

**Check (Ableton open, one MIDI track with clips):**
1. `/ableton-mcp-install`, then quit Live fully and reopen. `ableton://server/info`
   → the handshake passes and reports the new fingerprint.
2. Put a clip at 0..32 ("Scaffold") and a short clip starting at 20.0
   ("Marker"). Duplicate a 4-beat session clip to arrangement at beat 16, so
   Live's B-24 split emits its copy at 20.0 — the tied start.
3. Expect: the **Marker survives**, the split copy is gone, and the response
   carries `spurious_clips_removed` naming the copy. Marker disappearing is the
   data-loss regression the identity resolution exists to prevent — report it
   rather than working around it.
4. Repeat with the two clips at 20.0 made identical in length and name. Expect
   `spurious_clips_remaining` with a `reason`, and NOTHING deleted.

## MST-LEAK — a master device load no longer leaks into the focused track (2026-08-07) — PENDING

Field report (Live 12.4 Suite, 2026-08-07): with the view on `Detail/Clip` and
track 3 selected, two `ableton_device(action='load')` calls addressing the MASTER
put `Shifter` + `Limiter` on the master (correct, `ok`, `parent_kind: "master"`)
AND appended both to track 3, which nobody addressed. `browser.load_item` takes
no destination argument — Live aims it from view state, and the loader was moving
only one half of that state (`song.view.selected_track`), leaving the Detail
pane's device-chain binding on track 3.

Fix (`handlers/device.py`): retarget the Detail pane at the destination's device
chain as well, restore the caller's selection + Detail pane afterwards, and
bracket the load with a FULL-SESSION device census so a device landing in an
unaddressed chain is removed + reported (or raises) instead of returning `ok`.

**Fingerprint flips** (`handlers/` is in `_FINGERPRINT_PATHS`) → **re-vendor the
Remote Script + full Live quit/reopen required** before this check can run.

**Check (Ableton open, a set with 3+ tracks and an empty master):**
1. `ableton_session(action='set_view', view='detail')`, then select track 3 in
   Live by hand and leave the Detail pane showing the CLIP.
2. `ableton_device(action='load', node={'parent': {'kind': 'master'}, 'terminal': 'master'}, kind='Shifter')`
   → expect `ok`, `parent_kind: "master"`, `device_index: 1`, and NO
   `collateral_removed` key in the response.
3. `ableton_device(action='list', track_index=3)` → expect track 3's chain
   byte-for-byte what it was in step 1. Repeat 2-3 with `kind='Limiter'`.
4. Confirm Live's selection is back on **track 3** and the Detail pane is back on
   **Clip** (not the device chain) — the load must not move the composer's view.
5. Collapse the Detail pane entirely, repeat step 2 with a third device →
   expect the pane still collapsed afterwards.
6. Repeat 2-4 with a RETURN destination (`{'kind': 'return', 'index': 1}`) — the
   same aiming defect is latent there (a return is likewise not a member of
   `song.tracks`), and the fix is destination-kind agnostic.

**Why it can't be headless-verified:** the leak is Live's own load-aiming
behaviour. The unit tests model the two-halves mechanism in a fake browser
(`_LeakyBrowser` in `hallucinote_mcp/tests/unit/test_actions_device.py`) — per
the NODE-ADDR learning, a fake that encodes how an EXTERNAL system responds
proves nothing until an operator confirms it. The full-session census backstop
(`_AlwaysLeakyBrowser`) is what protects the composer if the prevention half
turns out not to be the whole mechanism.
## PSH-4L6C — the perform_batch locate settle is real, not just modelled (2026-08-07) — PENDING

`ableton_automation(action='perform_batch')` intermittently timed out on an
8-beat arc (beats 96..104, 3.4 s at 140 BPM) against a 12.3 s budget, with
`song.loop` False and `song.count_in_duration` 0 — both causes the old message
named. The identical arc had succeeded minutes earlier in the same session, and
the operator heard the transport roll with a start that sounded "a little weird".

**Root cause (inferred, not Live-confirmed):** the handler set
`song.current_song_time = union_start` and called `start_playing()` without
waiting for the locate to land. Live applies a locate ASYNCHRONOUSLY — the same
class of behaviour `record_mode` already has a settle-verify for (probe 10). When
the record_mode settle happened to return immediately, the locate got no
incidental cover and playback started from the old position: the ramp then had to
travel 104 beats, not 8, and blew a budget sized for the span.

**The fix is a settle-verify** (`_wait_for_locate_on_worker`) bounded by the
existing `settle_timeout_ms`, plus a timeout message that reports the OBSERVED
transport state instead of asserting causes.

**What is proven and what is not.** The wait, the tolerance, the budget
re-basing and the message are covered by 10 unit tests against the fake LOM, and
all four locate tests fail without the wait. What CANNOT be verified without a
live instance is the model of Live underneath:

- that `current_song_time` is genuinely async on a locate (asserted by analogy
  with `record_mode`, plus the symptom — never probed directly);
- that an in-flight locate is LOST when `start_playing()` fires (the test fake
  models this; the alternative — the locate lands late and the transport jumps —
  would produce an audibly wrong start but not necessarily this timeout);
- that `_PERFORM_LOCATE_TOLERANCE_BEATS = 1.0` is wide enough for whatever
  snapping Live does to a locate. Too tight would turn the old intermittent
  timeout into an intermittent hard failure at the settle boundary.

**Fingerprint flip: YES.** `handlers/automation.py` and `actions/automation.py`
are both inside `_FINGERPRINT_PATHS`, so the Remote Script vendored into Live's
User Library is stale until re-vendored — Live keeps running the old code, and
this fix does not take effect, silently.

**Checks (Ableton open, a song with a master-chain device parameter arc):**

1. **Re-vendor first.** `/ableton-mcp-install`, then quit Live completely and
   reopen (Live caches Control Surface modules at launch), then `/mcp`. Confirm
   `ableton://server/info`'s fingerprint matches the vendored copy.
2. **The race is gone.** Park the playhead at 0, then perform an arc whose span
   starts far downstream (the 96..104 master Shifter `Pitch Coarse` arc is the
   exact repro). Run it 5+ times back to back, including immediately after a
   manual `song.stop_playing()` — the case that failed twice in a row. Every pass
   must report `1/1 ok`, and the audible start must be AT the span start, not a
   run-up from the old position.
3. **The tolerance is not too tight.** Watch for any `could not locate the
   playhead` abort on a set where the transport is healthy. If that appears, the
   1-beat tolerance is narrower than Live's locate behaviour and needs widening —
   that would be this fix trading an intermittent timeout for an intermittent
   hard failure, which is worse.
4. **The message earns its keep.** Force a timeout (start a perform, then hold
   the transport with a modal dialog) and read the error. It must name the
   playhead beat, `transport rolling=`, `loop=`, and `count_in_duration=` as
   OBSERVED values.

---

## AUD-2D6T — automatic capture sweep fires on a real render (2026-08-03) — PENDING

The CLI half is verified against this repo's real `songs/missing/captures/` (406 MB
take: `list` reported it, `--dry-run` named it and removed nothing, `pin` then
`prune --keep 0` left it intact, `unpin` restored it). The AUTOMATIC half —
`server._sweep_stale_takes` firing inside `handle_tool_call` before an
`ableton_render(start)` is forwarded — is covered by unit tests against a faked
`client.send` but has never run against a live Ableton render.

Server-side only (`server.py`, `server_side/analysis.py`) — both are outside
`_FINGERPRINT_PATHS`, so **no re-vendor and no Remote Script change**.

**Check (a song with 3+ existing takes, Ableton open, linked session):**
1. `hallucinote captures list --song <slug>` → note the take names and total size.
2. `/render-analyze <slug>` (or `ableton_render(action='start', song_slug=…)`).
3. While/after it runs, `hallucinote captures list --song <slug>` again → expect
   the 2 newest prior takes plus the new one (3 total), the older ones gone.
4. Confirm the MCP server log carries `swept N stale capture take(s)` naming the
   removed dirs.
5. Pin a take (`hallucinote captures pin songs/<slug>/captures/<ts>`), render
   again, confirm the pinned take survives and did not consume a keep slot.
6. Set `HALLUCINOTE_CAPTURE_SWEEP=0` in the server's `env` block, restart the
   server, render → expect `retention sweep disabled` in the log and no removals.

**Why it can't be headless-verified:** step 2 needs a real transport pass; the
sweep's trigger point is the live render dispatch, not a function a test can
call in the same ordering against a real Live session.

## BAK-7D2V — pull-durability guard end-to-end in real Live (2026-07-04) — PENDING

Headless-verified (guard tests incl. the pull_cli-apply audit scenario + the
nested-chain-delete contract test), but the full pull→refuse→bake→pass loop has
not run against real Live. Engine-side only (`capture.py`, scaffold, docs) — **no
fingerprint flip, no re-vendor needed**. Design + refuse/warn matrix:
`.prawduct/artifacts/plans/BAK-7D2V/design.md`.

**Check (any song with a stamped `captured_at` snapshot — re-capture first if
the song's snapshot predates BAK-7D2V — Ableton open, linked session):**
1. Dial a knob in Live (e.g. a device parameter or a track fader).
2. `/ableton-pull` the matching domain (`device-parameters` / `mix-state`) →
   confirm the mutation applied (mutations ≥ 1).
3. Run `python songs/<slug>/build.py` → expect **`StaleSnapshotError` refusal**
   naming the pulled event(s), `/song-snapshot`, and `--force-replay` /
   `allow_stale_snapshot=True`. Confirm the pulled value is untouched in the DB.
4. Run `/song-snapshot` (confirm the diff shows the knob; overwrite) → run
   `build.py` again → expect **clean pass** and the knob value surviving in the
   DB (the bake disarmed the guard).
5. `--force-replay` path: dial + pull again (guard re-armed), then
   `python songs/<slug>/build.py --force-replay` → expect the REVERTING
   UserWarning and the DB back at the snapshot value; a plain `build.py` after
   that refuses again (forcing does not disarm — re-capture does).
6. Legacy path (optional): on a song whose snapshot has no `captured_at`, pull
   a knob and build → expect the warn-and-proceed path, not a refusal.
7. **Chunk 2 — pull-side notice.** In step 2's `/ableton-pull`, confirm
   `pull_cli` prints the durability notice on stderr ("N mix-layer change(s)
   staged in the DB … the next `build.py` … will REFUSE … bake with
   `/song-snapshot`"). Confirm a build.py-owned pull (e.g. `clip-notes`) and a
   zero-change re-pull print NO such notice.
8. **Empty-diff bake.** After a mix pull, hand-REVERT the knob in Live so a
   fresh capture shows no diff; `build.py` still refuses (guard armed by the
   pull events). Accept `/song-snapshot`'s empty-diff offer → it merges the
   fresh refresh over `captured_session.json` → `build.py` now passes clean.
9. **Empty-diff bake covers undiffed fields.** The case above with a pull that
   the diff is BLIND to: pull a device sidechain source (or a drum-pad mapping /
   chain authored prop), leave it in place, and re-capture — `capture diff` exits
   0 even though the on-disk snapshot is stale. Accept the same offer → confirm
   `captured_session.json` now carries the PULLED value (not the old one) and the
   next `build.py` preserves it. This case is exactly why there is no re-stamp
   override to reach for: moving the stamp without re-capturing would disarm the
   guard over the stale value, so the subcommand that did it was deleted
   (2026-08-11) and the only exits are this bake and `--force-replay`.

## MCP-1V8K — device load focuses Session view before browser.load_item (2026-06-23) — PASSED (agent-run live, 2026-06-23)

**Verified live (agent-run, this session, Ableton Live 12 Suite, default set).** Re-vendored the
Remote Script from develop (`0.1.0+a8ce2abb7163`, `matches_mcp_server: true`), launched Live, and
drove the repro directly via `hallucinote_mcp.client.send`:
- The version handshake matched (`a8ce2abb7163`) — Live loaded the re-vendored Remote Script, not the stale one.
- `ableton_session(set_view, view='arranger')` → `focused_view: "Arranger"` (the post-render precondition).
- `ableton_device(load, node={track 1}, terminal='track', kind='Operator')` while focused on Arranger →
  **`load.ok: True`, Operator landed** (`ableton_device(list, track_index=1)` device_count 0→1) — pre-fix
  this silently no-ops in Arranger.
- `ableton_session(info)` after the load → **`focused_view: "Session"`** — the `_focus_session_view_for_load`
  switch ran.
- Cleanup: deleted the test Operator (device_count→0); set left as found, not saved.

Residual (not blocking — covered by the same code path): the non-empty-chain and master-track (DEV-6M2K)
repeats from check item 3 below were not separately exercised; the fix is unconditional (focuses Session
before every `browser.load_item`), so the single verified path exercises the same line.

`device.py` `load_handler` now calls `application.view.show_view("Session")` before
`browser.load_item`, because that call silently no-ops when Live's focused view is Arranger
(the state a render leaves behind), bricking every post-render device load. `device.py` is in
`_FINGERPRINT_PATHS` (`handlers`), so this **flips the server fingerprint** and only reaches a
live set after a **re-vendor + `/ableton-mcp-install` handshake** (dev-mode relaunch — see
`project_mcp_deploy_topology_dev_vs_marketplace`). The headless test proves the loader *calls*
`show_view("Session")`, but the fake hardcodes the premise (Arranger → no-op); it does not prove
the premise or the fix hold in real Live.

**Check (any song, Ableton open, server version-matched after re-vendor):**
1. `ableton_render(...)` anything (leaves `focused_view = "Arranger"`; confirm via
   `ableton_session(action='info')`).
2. Without manually switching views, `ableton_device(action='load', node={parent:{kind:'track',
   index:N}, terminal:'track'}, kind='Operator')` → expect: device lands on the first try
   (no "did not append" error), and `ableton_session(action='info')` now reports
   `focused_view = "Session"`.
3. Repeat into a non-empty chain and onto the master track (DEV-6M2K path) to confirm the
   view-focus doesn't disturb those loads.

## ARR-PROJ Chunk 2 — full projection planner end-to-end in real Live (2026-06-22) — PENDING

Chunk 2 (the planner rewrite) is headless-verified (4379 green, Critic 0 findings) but the
WHOLE new path has not run against real Live as one flow — only the create+fill *primitive*
did (Chunk-1 spike, Drums only). The integration still to confirm live: the
`live_arrangement_clips_by_track` probe threading, the descending-index clear, per-placement
create+fill across multiple tracks in one phase, AND the envelope-bearing → duplicate route
(alien's one host: the Alien Voice `send_level` clip).

**Check (alien, Ableton open, server version-matched):**
`uv run hallucinote push execute --only arrangement --probe --song alien` (the new
`_cmd_execute` probes arrangement and threads it into the projection planner; `--only
arrangement` skips the realtime perform phase). Expect: every track's existing arrangement
clips cleared then create+filled from the DB; the Alien Voice envelope-hosting placement
duplicated (not create+filled) so its `send_level` clip envelope survives; `.last-push-state.json`
outcome `ok`. Then `hallucinote verify-arrangement` (once Chunk 3 lands) or a per-track
`ableton_note(list, location='arrangement')` spot-check shows collapsed note_counts == DB, and
NO stacking on the re-run. Render-confirm the song still sounds correct.

## ARR-PROJ Chunk 1 — arrangement-as-projection live spike (2026-06-22) — PASSED (note-level), render optional

**Attended session, alien set, server version-matched (`/mcp` respawn).** Drove the
real Drums track (10 placements, ~2500 notes incl. a 771-note clip) through two
consecutive `clear (per-clip delete) → create_midi_clip + set_notes → fresh
read-back` rebuilds via `.prawduct/artifacts/plans/ARR-PROJ/chunk1-spike.py`.

**Verified live (agent-run, this session):**
1. **Faithful + idempotent + drop-free.** `pass1=True pass2=True idempotent=True
   net_noop_vs_baseline=True` — every section's Live note_count matched the DB
   collapsed set on both passes; the rebuild returned Drums to byte-identical
   baseline. No drop, no B-24 stack (impossible by construction — no duplicate).
2. **note_count trustworthy (§6 q2).** On a source-less `create_midi_clip` clip
   (verse1), `ableton_clip(list).note_count == ableton_note(list) count == 503 ==
   DB collapsed` — reads the arrangement clip's OWN notes, read in a fresh callback.
3. **Live collapses same-(pitch,start) (§6b-1).** 509→503, 337→333, 771→770 held
   as collapsed — confirms the comparator must collapse before diffing.
4. **Clear wire exists; planner-deletes chosen.** Descending per-clip
   `delete(location='arrangement')` cleared 10 clips in ~7s; no bulk-clear action
   needed (Chunk 6 dropped, zero fingerprint change).

**Pending (optional — Early-Feedback "hear-it" milestone):** an *audible* render of
the rebuilt Drums track was not run. The note-API read-back proves note-for-note
fidelity and `net_noop=True` means the track is note-identical to the arrangement
the operator was already hearing, so render-correctness is transitively established.
Run `ableton_render(action='start', song_slug='alien')` if an audible confirmation
is wanted; otherwise this is operator-acceptable on the note-level proof.

## 2026-06-13 autonomous session — bridge prepped + new pending checks

**Bridge is READY for the existing SNP-8R4K checks below.** This session re-vendored
Live's Remote Script from the stale `4288d582ffc4` to **`0.1.0+46bd3bd7aa37`** (develop
HEAD; the fingerprint is unchanged by this session's work — all of it is outside
`_FINGERPRINT_PATHS`), and preflight confirms `matches_mcp_server: true`,
`coexistence_divergence: false`, analyzer byte-identical. So on return:
**reopen Live → `/mcp` reconnect → the develop server (`46bd` + the new
`ableton://server/info` resource) and the vendored Remote Script (`46bd`) handshake-match.**
Then the SNP-8R4K chunk 3 + chunk 4 checks (below) are unblocked, plus:

### INS-3W8P — install resolves the running server (coexistence path)

**Status:** PARTIALLY DOGFOODED. The right-source vendor + the
`--require-server-version` assertion + the honest `preflight --server-version`
(server `confirmed: true`, `coexistence_divergence: false`, `matches_mcp_server: true`)
were all exercised live this session against the real User Library — but with
server == invoking (`46bd`), so the *divergent* coexistence case wasn't forced.
**Residual:** force a genuine divergence — e.g. enable the marketplace plugin
(`4288`/main) so the running server differs from the editable dev clone (`46bd`),
`/mcp` so the server carries `ableton://server/info`, then run `/ableton-mcp-install`:
confirm the skill READS `server/info`, preflight flags `coexistence_divergence: true`,
and `install-remote-script --from-package-root <server_root> --require-server-version
<server_v>` vendors the SERVER's copy (or refuses a wrong source). Note: a transitional
first run against an OLD server (pre-`server/info`) correctly falls back — `/mcp`
respawns develop HEAD before relying on the resource.

### PSH-2R7K / PSH-5T9D — push execute phase-targeting + mid-run progress (smoke; LOW priority)

**Status:** UNIT-COMPLETE (engine-only, 23 tests; no Live behavior beyond what's
tested). **Optional Live smoke:** on a real push, confirm `execute --only devices`
runs exactly that phase, `--resume` continues from a halt, the per-phase stderr
heartbeat appears, and `.last-push-state.json` is pollable mid-run (a `watch cat`
shows `current_phase` advance). Not gating — the logic is fully unit-covered.

---

## NODE-ADDR Chunk A — wire flip + addressing spine (re-vendor + migrated-op Live verify)

**Status:** ✅ **FULLY LIVE-VERIFIED 6/6 2026-06-15** (Live 12.4.2; final served fingerprint
`0.1.0+c487d2b32ba7` after three re-vendor cycles as the chain-load fix iterated). The addressing
spine is proven end-to-end on a real set (808 Core Kit drum rack + 808 Selector Rack with a genuine
depth-2 nested Saturator). Checks 1, 2, 3a, 4, 5, 6 passed on the first pass. Check **3b
(chain-terminal load) FAILED first**, was root-caused to a **pre-existing, NOT-a-Chunk-A** defect
in the wire-flip-unchanged `_load_into_rack_chain` (`browser.load_item` ONLY targets the track's
MAIN chain — probed inert against `rack.view.selected_chain` AND `song.view.select_device`, two
wrong fixes that left strays top-level), and **FIXED via `Chain.insert_device(name)`** (found by
probing the `Chain` LOM object). The integrated handler is now **confirmed live**: `ableton_device
load` with a `chain` terminal put Reverb at the depth-1 "808" chain (pos 8) and Compressor at the
depth-2 "Punch" chain (pos 7), **with no stray top-level devices**. Presets are refused for chain
loads (insert_device is name-only); the false-green fakes were rewritten to model insert_device.
No remaining Chunk-A gates.

Earlier: CODE-COMPLETE 2026-06-15 (worktree `feature/node-addr`), full suite green (baseline +
38 new tests). Critic note d: `device_path` was a shipped contract (DEEP-RACK-ADDR), so the
migration verified **every** migrated op against a real set via the new `node` address.

**Bridge step first** (re-vendor required — touches `actions/`+`handlers/`; the fingerprint
flips from develop's `e10695d17559` to Chunk A's **`0.1.0+b23b59ab5e34`**). Chunk A is merged
to `develop`, so re-vendor from the primary repo (not a worktree) — this keeps the running
server and the vendored Remote Script the *same* copy, so `/ableton-mcp-install`'s INS-3W8P
match-against-running-server guard stays intact:
1. In the primary repo (`~/source/hallucinote`, on `develop`): `git pull` → develop now carries Chunk A.
2. `/mcp` reconnect (respawn the server on the pulled code) → `ableton://server/info` should now
   report version `0.1.0+b23b59ab5e34`.
3. (Live closed) `/ableton-mcp-install` → it reads server/info, re-vendors the Remote Script
   with `--require-server-version 0.1.0+b23b59ab5e34` (guard confirms source==server).
4. Reopen Live (it caches Control Surface modules at startup), `/mcp` reconnect, confirm the
   handshake reports `b23b59ab5e34`. Then:

1. **Nested set_parameter via `node`** — set a depth-2 nested device param through
   `ableton_device(action='set_parameter', node={parent, terminal:'device', device_index, path:[…]})`
   → it lands on the right nested device (not the top-level rack).
2. **Nested get_parameters via `node`** — read the same nested device; confirm values + the
   new `default_value` field present (guarded — omitted only on the params that raise).
3. **load via `node`** — a track/return/master-terminal load (top-level) AND a `chain`-terminal
   load INTO a nested chain both place the device correctly.
4. **write_envelope + a performed arc via `node`** — author a `device_parameter` envelope on a
   nested device and run a performed automation pass → both route to the right nested param.
5. **`chain` terminal resolves** — a DrumChain reached via a `chain`-terminal `node`;
   `choke_group`/`out_note` are reachable on it (the Chunk-C surface), proving the new terminal.
6. **Capability matrix end-to-end** — read `ableton://reference/node-feature-matrix`; confirm an
   unbuilt feature reports `NOT_IMPLEMENTED` and a structural-impossible op (send pre/post,
   macro-mapping-target, per-chain audio out) reports `UNSUPPORTED_IN_LIVE`, each with the
   documented evidence + workaround.

**Results (2026-06-15, Live 12.4.2):**
1. ✅ **set_parameter @ depth-2** — Saturator `Dry/Wet`→0.5 at `path:[{2,1},{1,2}]`; `device_path`
   echoed the nested address (not the top rack). (Note: a first attempt on `Drive` returned Live's
   "parameter is disabled" — the resolver reached the device; the param was just non-settable.)
2. ✅ **get_parameters @ depth-2 + `default_value`** — 19 params; `default_value` present on
   continuous params, **correctly omitted on enums** (the guarded raises-fallback).
3. ✅ **load** — top-level (track-terminal) load ✅ (both racks). **Chain-terminal load INTO a nested
   chain** ❌ on the first pass (`browser.load_item` appended to the track top-level — it ONLY reaches
   the MAIN chain; the fail-loud post-condition caught it but left a stray, cleaned up). Two wrong
   fixes (`rack.view.selected_chain`, then `song.view.select_device`) both probed inert. **Pre-existing**
   (the `_load_into_rack_chain` mechanism was byte-identical develop↔HEAD; the wire flip only changed
   the node→chain_index *entry*). **The right API is `Chain.insert_device(name)`** (found by
   `ableton_probe describe`-ing the `Chain` object). **FIXED + confirmed live via the integrated
   handler:** `ableton_device(load, node={…chain…})` put Reverb at the depth-1 "808" chain (pos 8) and
   Compressor at the depth-2 "Punch" chain (pos 7), **no stray top-level device**. Presets refused for
   chain loads (insert_device is name-only); the false-green fakes were rewritten to model insert_device.
4. ✅ **automation** — `perform_batch` on the depth-2 Saturator `Dry/Wet` recorded with
   `automation_state:1`, `device_path` echoed nested. `write_envelope` verified at top-level (its
   nested route is a documented Live-12.4 impossibility → `perform_batch` is the nested path).
5. ✅ **`chain` terminal** — `ableton_probe` confirmed `choke_group` (int 0) reachable on the Bass
   Drum DrumChain behind a `chain`-terminal address (the Chunk-C surface), proving the new terminal.
6. ✅ **capability matrix** — `ableton://reference/node-feature-matrix` tri-state matches
   `probe-findings.md` (SUPPORTED / NOT_IMPLEMENTED+request_tag / UNSUPPORTED_IN_LIVE+live_evidence).

Visual change: no (wire/behavior, not UI). Operator-attended Live session required.

---

## ENV-8K2R + ENV-2T9K — perform-handler hardening + tempo-reduction fidelity (Live smoke)

**Status:** PENDING — needs a `/mcp` reconnect (respawn the server on the new handler code,
which the session that built it does NOT yet run) + a usable Live set. **Visual change:** no
(audio / LOM state).

All code + unit tests + the cumulative-Critic chain are complete (branch
`feature/perform-handler-hardening`, 3389 passed / 2 skipped; cumulative 0-blocking →
verify-resolutions clean). The fakes can't model tempo→beat-advance coupling or Live's async
Song state, so the runtime recording outcomes need a live transport pass. Checks:

1. **ENV-8K2R #1 — SAR disarm settles.** After a `perform_batch` pass, read
   `session_automation_record` via LOM — it must read back the pre-pass value (False), not
   leave the set armed. A `restore_failures` entry naming `session_automation_record_settle`
   in the result is the failure signal.
2. **ENV-8K2R #2 — gesture endpoint lands the authored final.** Author a ramping arc; after the
   pass, seek-read the recorded arrangement automation at `span_end` — it must equal the
   authored final breakpoint, not sit ~0.8 beat short.
3. **ENV-2T9K — tempo-reduction fidelity.** Author a 0.5-beat dip to depth 0.1; record once at
   `slowdown_factor=1` (baseline ~0.589 per the ENV-9P4T probe) and once at e.g.
   `slowdown_factor=4`; the slowed pass must record the dip materially closer to 0.1. Confirm
   the transport tempo is restored to the song tempo after the pass (handler echoes
   `record_tempo` + `slowdown_factor` in its result).

Recipe: drive `ableton_automation(action='perform_batch', arcs=[...], slowdown_factor=N)`
directly, or `push_cli plan performed_automation --perform-slowdown N`. Verify via the `.als`
dump / seek-read approach in `.prawduct/artifacts/plans/ENV-9P4T/api-notes.md`.

---

## INS-7V2D follow-up — MCP startup timeout survives a cold build on a real install

**Status:** PARTIALLY CONFIRMED — the make-or-break check (#1, cold-start survives a real
cold build) **passed live** this session (2026-06-04). **Visual change:** no.

Root cause (this session) confirmed from the connection log: the cold-build spawn timed
out at **30000ms** despite `plugin.json` `"timeout": 60000` — because the per-server
field is tool-exec, not startup; startup is `MCP_TIMEOUT` (default 30000). Fix raises
`MCP_TIMEOUT` (settings `env`, floor 180000) + the pre-warm hook now emits SessionStart
`additionalContext` on a cold build. Unit-proven (`test_startup_timeout.py`,
`test_prewarm_hook.py`); warm handshake measured at ~2.3 s. Operator status:

1. ~~**Cold-start survives within `MCP_TIMEOUT`.**~~ **CONFIRMED** (this session): the operator
   ran `uv cache clean` (genuinely cold uv cache) and restarted Claude Code (`--plugin-dir .`)
   with the committed `.claude/settings.json` `env.MCP_TIMEOUT=180000` floor active. The cold
   `uv` build completed ("took a while") and the `hallucinote-mcp` tools connected **on first
   launch — no `/mcp` reconnect needed** (operator-reported); the 30 000 ms startup-timeout
   failure did NOT recur. Re-confirmed mid-session via `ableton_session(action='help')` → ok.
2. **Race → reconnect path.** NOT exercised — the build did not overrun the window this session
   (it connected on its own), so the reconnect fallback wasn't triggered. Unproven as a path;
   lower priority now that #1 holds on a real cold cache.
3. **`statusMessage` shows the expectation.** Still unconfirmed — the operator did not report
   whether the SessionStart spinner showed the "first run builds it — up to ~1–2 min" message.
4. **Uninstall reverses it.** Still unconfirmed — `hallucinote-mcp unset-startup-timeout`
   removal of `env.MCP_TIMEOUT` from `~/.claude/settings.json` was not exercised this session.

---

## INS-7V2D — plugin-bundled MCP server launches via uv on a real install

**Status:** PARTIALLY CONFIRMED — the **make-or-break risk passed live** this session.
The plugin was loaded via `--plugin-dir .` and the `hallucinote-mcp` tools connected;
`ableton_session(action='help')` returned a full valid response. Since the server is
spawned by Claude Code (tool prefix `mcp__plugin_hallucinote_…`), this proves:
`command: "uv"` **resolved in Claude Code's sanitized spawn env** (risk #0 below), and
C1's **self-healing launch built the `${CLAUDE_PLUGIN_DATA}/venv` on demand within the
60s timeout** — note this happened *before* the C2 pre-warm hook existed, so the launch
is correct standalone. **Visual change:** no.

Risk #0 + check #1 are now confirmed on this machine. What still needs an operator:

1. ~~**Fresh install connects** / **`uv` resolves in the SPAWN env (make-or-break).**~~
   **CONFIRMED** (this session, `--plugin-dir .`). Residual: the uv *cache* was warm here
   (the heavy wheels were already fetched during C1's local verification), so the
   genuinely-cold-cache worst case (CC#60224 silent tool-drop on a
   first-ever numpy/scipy/librosa build) was **not yet proven** at v0.9.3.
   **Update (INS-7V2D follow-up, this session): now CONFIRMED on a genuinely cold cache** —
   the operator's `uv cache clean` + restart connected on first launch (see the follow-up entry
   above). Note the survival window is the **180 s `MCP_TIMEOUT` floor**, not the 60 s this
   original framing assumed: the per-server `plugin.json timeout` never governed startup — that
   was the follow-up's root-cause correction.
2. **Update rebuilds the env.** Bump the plugin version / change `uv.lock`, update the
   plugin, confirm the env rebuilds (the C2 lock-diff hook fires + the launch self-heals)
   and the server still connects. **Not yet exercised** — needs a real plugin update cycle.
3. ~~**No abs-path override needed** (configure-mcp returns skip).~~ **RESOLVED in code by
   C3** — `configure-mcp` and the absolute-path-override path are *deleted*; the install
   skill writes no MCP config (guarded by `test_configure_mcp_subcommand_is_retired` +
   `test_install_skill_does_not_resurrect_configure_mcp`). Nothing to verify at runtime.

## ARR-7M3D — energy-realization lens: render-based DR-5 calibration + e2e ρ read

**Status:** PENDING (Live was UP but UNATTENDED this run; the new MCP analysis
key isn't loaded into the running bridge from this uninstalled branch).
**Visual change:** no (objective render + JSON read; the only by-ear item is the
DR-5 surfacing threshold tune).

The lens (Spearman ρ + inversion detection) is FULLY OBJECTIVE and is proven
render-free by the chunk-3 fixture suite (`tests/unit/audio/test_energy.py`) and
the chunk-4/5 handler-path unit tests (`test_analyze_handler_populates_energy_realization`,
`test_analyze_handler_always_emits_energy_realization_key`). What remains needs an
attended Live run:

1. **End-to-end objective ρ read.** Install this branch (`pip install -e .` of
   `hallucinote`), build sun-zone-done in the `hallucinote-songs` repo (declared
   energy 0.25→1.0 across 9 sections), render it, run `ableton_analysis`, and
   read `report["energy_realization"]`. Record the measured per-correlate ρ (or
   its `None`-with-reason if a correlate ties) + the inversion magnitudes in the
   chunk reflection. Confirm the on-disk report JSON parses (it will — ρ is
   `None`-or-finite by construction + the `allow_nan=False` write-path backstop).

2. **DR-5 surfacing-threshold calibration (the one by-ear item).** The
   `_ENERGY_INVERSION_SURFACING_FLOOR` constant in
   `src/hallucinote/audio/analyze.py` is currently the CONSERVATIVE
   surface-everything default (0.0). Once step 1 produces a real measured
   inversion distribution, tune the floor against it with a human ear (mirrors
   how `_MASKING_REPORTING_FLOOR` / `_TIMING_MIN_CONFIDENCE` were calibrated) and
   document the calibration basis in the constant's comment. Surfacing-everything
   can never HIDE a real inversion, so the default is safe to ship; the tune only
   trims DSP-noise trivia.

3. **Onset-density correlate plausibility on real audio.** Chunk 2 calibrated
   density on synthetic clicks and found a constant −1-onset-per-stem detection
   offset (the sample-0 onset is undetectable). On a real render, confirm density
   RANKS sections sensibly; if it reads implausibly (the C7 slow-attack risk),
   the report ships loudness-ρ as the primary signal with density caveated —
   never a confidently-wrong density ρ.

## ENV-7G4K — performed automation: S-7 Live smoke (chunk 03 visual half)

Queued 2026-06-11 (chunk 03 code + unit half complete; smoke pending the
Remote Script refresh).

1. **One-time setup (human):** `/ableton-mcp-install`, then fully quit and
   reopen Live (the running Remote Script `a5479db86125` predates the
   `perform` handler — Live caches Control Surface modules). Open a set
   with a group track and a manually-placed master-chain device, then
   `probe-and-link`.

2. **Run S-7** (`tests/integration/test_live_smoke.md`): master volume
   ride + group arc + return arc + master-device sweep authored in
   build.py → push performs each (transport plays, wall-clock named in
   the plan) → second push skips all as unchanged → one edited arc
   re-performs alone, new shape audibly/visibly replacing the old.

3. **Record here:** per-arc `automation_state`, the audible/visual
   confirmation (automation lanes in the arrangement), and the `.als`
   dump breakpoint-quality spot-check (closes the probe doc's
   "breakpoint quality / thinning" open item).

---

## SYN-6B4Q — cue_create_batch skip-mode wire round-trip (CLR-A chunk 02)

**Status:** UNIT-CONFIRMED, live smoke pending a Remote Script refresh.
**Visual change:** no (locator strip; deferred cues simply don't appear yet).

The handler `cue_create_batch` gained `on_out_of_range='skip'`: it now creates
the in-`last_event_time` cues and returns the rest in `skipped_out_of_range`
instead of the W5-C atomic raise. Covered by `FakeSong`/`FakeCtx` unit tests,
but the running Remote Script predates this handler — Live caches Control
Surface modules, so the real wire path needs a Live restart to exercise.

1. **One-time setup (human):** `/ableton-mcp-install`, then fully quit and
   reopen Live so the refreshed Remote Script loads.

2. **Skeleton-defer check:** scaffold a song with cue_points but NO arrangement
   content; `push_cli execute`. Expect: cues phase OK (exit 0), the stdout
   "Warnings (push still OK)" section lists every cue as deferred, NO `.last-
   push-errors.json`, and Live's locator strip is empty (nothing half-placed).

3. **Land-on-next-push check:** compose the arrangement, re-push. Expect: the
   previously-deferred cues now appear in Live's locator strip at the right
   bars, idempotently (no duplicates).

4. **Composed-overrun check:** author a cue past the arrangement's end; push.
   Expect: cues phase HALTS PARTIAL with the "composed song length" message
   (naming the offending cue), NOT the runtime "past last_event_time".

---

## ENV-9P4T chunk 01 — single-pass batched perform: verify-api probe + Live smoke

**Status:** CONFIRMED LIVE 2026-06-11 — the keystone per-parameter-windowing
claim is verified on a real bridge (no longer symbolic-only). Bridge healed
(`/ableton-mcp-install` re-vendored the Remote Script to `725742c1`, Live
restarted, `/mcp` reconnected); the prior mismatch (server `c0b443e0` vs
Remote Script `b0c3c347`) is gone. **No `.als` dump was needed** — seek-and-read
of `DeviceParameter.value` plus each arc's `updates_written` settle the
windowing without the LOM envelope read surface (full capture +
method:
`.prawduct/artifacts/plans/ENV-9P4T/api-notes.md`). **Visual change:** no.

1. ~~**One-time setup (human):** `/ableton-mcp-install` + Live restart.~~
   **DONE** — bridge version-matched; clean calls confirm the handshake.

2. ~~**Two-window-in-one-pass correctness (the keystone).**~~ **CONFIRMED.**
   `perform_batch [master_vol [0,64], return1_vol [16,48]]`: BOTH
   `automation_state == 1`; `wall_clock 34.32 s` ≈ one union-span pass (not the
   48 s per-arc sum). Windowing proven WITHOUT `.als`: at beat 8 the return
   reads its MANUAL 0.85 (a flat-stamp would read 0.2), at beat 32 it reads the
   live ramp (0.499 ≈ 0.5, the control), and `updates_written = 41` ≈ its
   32-beat span (vs master's 81 over 64 beats) — the gesture was open only over
   [16,48], bounding both edges.

3. ~~**Achieved breakpoint density (Hz)**~~ **CAPTURED:** ~2.5 Hz per arc
   (81/64 beats, 41/32 beats), identical under 2-param batching → no
   main-thread starvation; within the ENV-7G4K ~2.5–3 Hz baseline. This is the
   *attempted* rate; the seek-read trace reconstructs both ramps to <0.5% error.
   The exact Live-*retained* count (post-thinning) is the only `.als`-only
   residual — a Chunk 03 fidelity detail, NOT a gate item.

4. **Safe batch ceiling** — NOT stressed (N=2 recorded cleanly; no contention
   signal). A higher-N stress pass (`env7g4k-smoke-driver.py`, 5 arcs) remains
   available if Chunk 02's 10+-track use case ever shows main-thread contention;
   tracked as a non-blocking note, not a Chunk 01 gate.

---

## DEV-6M2K — master device load re-enabled across the stack (live corroboration)

**Status:** CONFIRMED LIVE 2026-06-12 — all three checks passed on the open set
(Live 12.4.2; Remote Script re-vendored to `9093dfef`, Live reopened, `/mcp`
reconnected — server's `ableton_render` description showed the DEV-6M2K text,
confirming the new code). DEV-6M2K is fully verified; closed. **Visual change:**
yes (devices appear on the Master strip — each probe loaded then deleted, set
restored to an empty master).

1. ~~**Native (non-M4L) device on master (the backlog's before-close caveat).**~~
   **CONFIRMED.** `ableton_device(load, master=True, kind='EQ Eight')` → landed on
   the master chain (`device_index=1`, `parent_kind='master'`, `class_name='Eq8'`),
   `delete` removed it. Rules out a device-class quirk — master load now proven
   for both M4L (Align Delay) and native (EQ Eight) devices.

2. ~~**Full push of a DB-authored master-strip chain.**~~ **CONFIRMED.** Scratch
   song (master Limiter + Ceiling `-1.0 dB`) driven through `execute_push` scoped
   to the devices phase against the real bridge: `outcome=ok`, devices phase
   `ok=2 failed=0` (the `device.load(master=True)` AND the convergence-replanned
   `set_parameter`), device linked at index 1, NO PARTIAL halt. The old SYN-2M9P
   trap is gone. Limiter removed after.

3. ~~**Render auto-loads the master analyzer.**~~ **CONFIRMED (surgically).** The
   one Live-specific unknown — does the analyzer `.amxd` resolve + load onto the
   master in real Live — proven: `ableton_device(load, master=True,
   preset_query=<the exact query ensure_analyzers_loaded uses>)` resolved the full
   `user_library/Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer` walk
   and landed it on the master; deleted after. The full-sweep port-11220 assignment
   + idempotency is unit-tested; the full `ensure_loaded` sweep was NOT run live
   (it would add analyzers to all tracks/returns of the open set).

DEV-6M2K closed; DEV-2M9K (verdict retracted), SYN-2M9P (planner-skip retired),
TPL-2D8K (`.als` master-template workaround reduced to a convenience) re-triaged.

---

## RTE-1K9T chunk 04 — routing push phase materializes a PRE-MAIN submaster in real Live

**Status:** PENDING — needs an attended Live session. **Visual change:** yes (tracks'
output/input routing chips + monitor switch change in Live's mixer; a new audio bus
sums the routed tracks). Unit-proven at the plan + apply layers
(`tests/unit/sync/test_push_routing.py`, 16 tests): display-name resolution per kind,
the track-target FK→name resolution, channel pass-through, the dangling-target alert,
ack-only key round-trip, and the orchestration wiring. What unit tests CANNOT cover:
the same-callback-readback caveat (design discovery row 6) and whether routed audio
actually sums through the bus. Operator checks:

1. **PRE-MAIN push materializes the routing.** Author a scratch song with an audio
   bus "PRE-MAIN", route an instrument track's output → the bus (`output_routing_kind
   ='track'`, `target_id`=bus), route the bus → master (`kind='master'`), set the bus
   `monitoring_state='In'`. Drive `execute_push` (routing phase) against the real
   bridge. Confirm in Live: the instrument track's output chip reads "PRE-MAIN", the
   bus's output reads "Main", and the bus monitor is "In". `outcome=ok`, no PARTIAL halt.
2. **Audio sums through the bus.** With the layout from #1, confirm the instrument is
   audible through the bus (Monitor=In passes the routed audio) — silence here means
   the monitor/input wiring is wrong, not the routing-type set.
3. **Re-push is an effect-level no-op (D7).** Run the routing phase a second time; the
   plan re-emits the same idempotent calls and Live's state is unchanged (no churn, no
   error). Confirms the no-fingerprint-gating decision holds in practice.
4. **(After chunk 05 — pull)** The full round-trip: reroute a track by hand in Live,
   pull, and confirm the DB reference updates through the mutator. Deferred to chunk 05.

---

## RTE-1K9T chunk 05 — routing pull ingests a manual reroute + Live input-default probe

**Status:** PENDING — needs an attended Live session. **Visual change:** no (pull reads
Live → writes the DB; nothing new appears in Live). Unit-proven at the plan + apply
layers (`tests/unit/sync/test_pull.py`, 23 routing tests): per-track output/input/monitor
probes, display-name→reference resolution (fixed-name-wins, ambiguity, unknown-target),
the NULL≡default churn-avoidance state machine (no-op / revert / non-default-persist), the
V1 input narrowing, and the out-of-vocab monitor diagnostic. What units CANNOT cover:
whether the live MCP getters return the display_names/channels the inverse map assumes,
and — the Critic-W1 open premise — what Live's **non-track input default actually is**.

1. **Manual-reroute round-trip (the chunk's deliverable).** Starting from the chunk-04
   PRE-MAIN layout, reroute an instrument's output to the bus **by hand in Live's mixer**,
   then `pull_cli execute mix-state`. Confirm the DB ingests it through `set_track_routing`
   (a `track_routing_set` event falls out, `output_routing_kind='track'` + the bus FK),
   and that an immediate second pull is a clean no-op (mutations=0). Set the bus Monitor
   by hand and confirm the same for `monitoring_state`.
2. **Input-default probe (resolves Critic W1 — unblocks fixed-input-kind pull).** On a
   fresh MIDI track AND a fresh audio track, run `ableton_track(action='get_input_routing')`
   and record the `current_type` display_name (the hypothesis: MIDI → "All Ins", audio →
   an interface channel / "Ext. In"). This pins Live's real input default. IF it is a
   stable, closed value, a follow-up can add `INPUT_DEFAULT_KIND` + a NULL≡default rule and
   widen input pull beyond track-targets; until then V1's track-only input pull is the
   safe floor (it cannot churn regardless of what the default turns out to be).
3. **Display-name / channel fidelity spot-check.** For a track routed to the bus, confirm
   `get_output_routing` returns `current_type` == the bus's exact name and a `current_channel`
   the inverse map round-trips (e.g. "Post Mixer") — i.e. push-then-pull is identity.

---

## SNP-8R4K chunk 4 — push-preflight surfaces stale-set rebuild guidance (State-2 trigger)

**Status:** PENDING — needs an attended Live session + a `/mcp` reconnect (the running
Remote Script + server must run this branch's `probe_and_link`). **Visual change:** no
(the guidance is a `notes[]` string in the probe-and-link JSON the skill surfaces; no
Live state changes). Unit-proven at the detection + wiring layers
(`tests/unit/test_analyzer_staleness.py` — 18 pure-detector tests across
track/return/master; `tests/unit/sync/test_push_cli.py` — 5 wiring tests through the
`probe_and_link` seam with synthetic probe data). What units CANNOT cover: that Live's
real `ableton_device(action='list')` surfaces the analyzer entry with
`name=="HallucinoteAnalyzer"` (the predicate `is_analyzer_device` keys on `name`), and
that `_probe_live_devices_via_mcp` forwards it unfiltered to `probe_and_link`.

1. **Stale set surfaces the guidance (the deliverable).** Open a saved set, then load any
   authored device (e.g. a Saturator) onto a track that already carries the
   HallucinoteAnalyzer so it lands AFTER the analyzer (Live appends; the analyzer is no
   longer terminal). Run `push_cli probe-and-link --probe`. Confirm the result JSON's
   `notes[]` contains a `"STALE SET (SNP-8R4K)"` entry naming that surface (`track #N`) +
   the trailing device, with the "rebuild the set from source: push into a fresh set"
   guidance. No hard halt — `probe-and-link` still exits 0.

2. **Clean / rebuilt set is silent.** On a set where the analyzer is terminal on every
   tapped surface (a freshly-rebuilt push, or one where no device was loaded after the
   render's tap), run the same `probe-and-link --probe`. Confirm NO `"STALE SET"` note
   appears (the condition is the version key — a clean set has no authored-after-analyzer
   surface, so detection is silent).

3. **Master-surface gap (informational, not a gate).** The probe today walks tracks +
   returns only (`_probe_live_devices_via_mcp`); the master chain isn't probed until
   SNP-4K7M lands master-device capture. So a master-only staleness won't surface yet —
   confirm this is the case and note it. The detector already handles a `("master", None)`
   surface in the roll-up; only the probe feed is missing.

---

## SNP-8R4K chunk 3 — render re-asserts the terminal-tap + flags under-tapped surfaces

**Status:** PENDING — needs an attended Live session + a `/mcp` reconnect (the running
Remote Script + server must run this branch's `analyzer/setup.py` reposition code).
**Visual change:** yes (on a repositioned surface the HallucinoteAnalyzer visibly moves
to the END of the device chain — it is deleted mid-chain and re-added last). Unit-proven
at the decision + wiring layers (`hallucinote_mcp/tests/unit/test_analyzer_setup.py` —
the pure `_reposition_action` helper across absent / already-last / interleaved, plus
`_ensure_on_surface` reposition / no-op / load / idempotent-after-reposition with the
mocked Live chain; `hallucinote_mcp/tests/unit/test_actions_render.py` — the manifest's
per-surface `terminal` / `was_repositioned` + the top-level `analyzer_not_terminal`
roll-up, including a forced non-terminal surface). What units CANNOT cover: that Live's
real `delete_device` + `browser.load_item` actually deletes the mid-chain analyzer and
re-appends it terminal, and that the per-stem WAV then reflects the post-analyzer device.

1. **Reposition fixes an under-tapped surface (the deliverable).** Open a set, render once
   (analyzer lands last on every tapped surface). Then load any authored device (e.g. a
   Saturator) onto a track that already carries the HallucinoteAnalyzer — Live appends, so
   it lands AFTER the analyzer (analyzer no longer terminal → under-tapping). Re-render
   (`ableton_render(action='render')`). Confirm in Live: the analyzer was MOVED to the END
   of that track's chain (the Saturator now precedes it), and the render manifest's track
   entry shows `"was_repositioned": true` + `"terminal": true`. Compare the per-stem WAV
   to the pre-reposition render: it now reflects the Saturator's effect (e.g. its
   saturation is audible / shows in the spectrum) — the post-analyzer device is captured.

2. **Already-last surface is a no-op (R12 — no churn).** On a surface where the analyzer is
   already last, the re-render must NOT delete + re-add it (the M4L reload is expensive).
   Confirm the analyzer object/position is unchanged on those surfaces, the render didn't
   stall, and the manifest entry reads `"was_repositioned": false` `"terminal": true`. (The
   no-reload-on-unchanged-surface invariant — the `ensure_loaded` 25-surface load once blew
   the socket window, so a churning render here would be a regression.)

3. **Never measure-and-lie (R9).** If any surface cannot be made terminal (a Live quirk /
   concurrent edit leaves a device after the re-added analyzer), confirm the manifest flags
   that surface in the top-level `"analyzer_not_terminal"` list and sets the per-surface
   `"terminal": false` — rather than emitting clean numbers for an under-tapped stem. (Hard
   to force live; the unit test forces it via a misbehaving load. Note here if no natural
   live case arises — the path is unit-covered.)

---

## DPP-7H2K — unit-aware value_display resolves a REAL Live param (Hz/kHz, ms/s)

**Status:** CALIBRATION VERIFIED 2026-06-13 (live, via str_for_value probe + local
solver). REMAINING: end-to-end `set_parameter(value_display=…)` THROUGH the new
server — needs a re-vendor + `/mcp` reconnect (DPP-7H2K flips the MCP fingerprint;
the session that ran the calibration was still on the pre-merge server, so the
*new* inversion path couldn't be driven through the bridge — but its math was
proven against the real device, below).
**Visual change:** no (parameter value changes; verify via readback).

**CALIBRATION EVIDENCE (2026-06-13, real Live 12.x — EQ Eight + Compressor on a
scratch track, deleted after).** Captured the REAL display curves via the bridge:
EQ Frequency `30 Hz … 1000 Hz → 2.00 kHz … 18.0 kHz` (the leading number reverses
1000→2.00 at the Hz→kHz switch); Compressor Release `1.00 ms … 459 ms → 1.12 s …
3.00 s` (459→1.12 at the ms→s switch). The shipped `canonical_magnitude` normalised
EVERY real string correctly and made both sequences monotonic (the exact reversal
that made the pre-DPP-7H2K code REFUSE). `solve_raw_for_display` resolved targets
against the real-sample curve and the REAL device rendered them back:
`150 Hz → raw 0.35187 → "150 Hz"` (exact), `2 kHz → 0.68848 → "2.00 kHz"` (exact),
`120 ms → 0.29649 → "123 ms"` and `1.5 s → 0.78125 → "1.52 s"` (~2%, interpolation
granularity of the 6-pt release sample, not the solver — the real server bisects on
the real curve and converges exact). The "validate against real instances, not the
synthetic corpus" learning is satisfied for the resolution math.

Unit-proven against synthetic curves mirroring real device shapes
(`hallucinote_mcp/tests/unit/test_display_value.py`: Hz/kHz + ms/s resolution,
genuinely-non-monotonic-after-normalisation still refuses; `test_actions_device.py`:
the value_real echo through both write sites). What units CANNOT cover — the project's
own learning ("validate against real instances; the original display-value traps all
came from real-Live probes, not the synthetic corpus"): that a REAL Live EQ frequency
and a REAL compressor release actually render the Hz↔kHz / ms↔s switch the way the
fixtures assume.

1. **EQ freq by explicit unit.** On a real EQ Eight band Frequency param,
   `ableton_device(set_parameter, …, parameter_name='Frequency', value_display='150 Hz')`
   succeeds (no DisplayValueError) and `get_parameters` reads back ~150 Hz. Repeat with
   `value_display='2 kHz'` → reads back ~2 kHz. Confirm the response carries
   `value_real`≈150 / 2000 and `value_real_unit='Hz'`.
2. **Comp release by explicit unit.** On a real Compressor Release,
   `value_display='120 ms'` and `value_display='1.5 s'` each resolve and read back at the
   right magnitude; `value_real_unit='ms'`.
3. **Genuinely non-monotonic still refuses.** A param whose display reverses for a
   non-unit reason still raises the teaching error pointing at the normalized `value`
   (confirm at least one such param if one is reachable; else note units cover it).

## RTE-2P9X — fresh push of an instrument-less MIDI track routed to PRE-MAIN

**Status:** PENDING — attended Live session, a song with a PRE-MAIN submaster bus and a
NEW (instrument-bearing) MIDI track routed to it. **Visual change:** no.
Unit-proven: phase order is `mix < devices < routing` (`test_push_song.py`). What units
can't cover: that Live actually exposes the MIDI track's audio output routing only after
its instrument loads. **Check:** a from-scratch `execute` of such a song completes the
`routing` phase (no `'PRE-MAIN' not in available output routing types'` halt).

## SYN-3C8K — set-swap re-push completes the clips phase

**Status:** PENDING — attended Live session. **Visual change:** no.
Unit-proven: the cascade drops the stale clip link and the planner then emits `create`
(`test_push_cli.py`). What units can't cover: the real set-swap. **Check:** push a song,
close that Live set, open a fresh default set, re-run `probe-and-link --probe` then
`execute` against the SAME session — the clips phase completes (no `IndexError: session
slot N on track M is empty`), and probe-and-link reports `unlinked_stale_clips` > 0 and
offers the default-scaffold cleanup despite the reused (not freshly-minted) session.

## SDC-7K3M — device sidechain SOURCE survives a full pull→rebuild→push round-trip

**Status:** PENDING — attended Live session (Live was occupied at author-time).
**Visual change:** no.
Unit-proven: the `device-sidechain` pull domain emits one `get_input_routing` probe per
linked device, and apply resolves a distinct-track `current_type` → a source FK written
via `set_device_sidechain` (idempotent; self/none/ambiguous/non-track all no-op) —
`tests/unit/sync/test_pull.py` SDC-7K3M block (13 tests). What units can't cover: how a
REAL Live device reports its input routing, and the full loop. **Check:** in Live, set a
compressor's sidechain SOURCE to a sibling track (`ableton_device(set_sidechain)` or by
hand); run `pull_cli execute device-sidechain <session>`; confirm
`devices.sidechain_source_track_id` now names that track; then `build.py --reset` +
`push_cli execute` and confirm the source re-resolves to the correct track in Live with
no `.als` reliance. **Then (gates a follow-up):** observe what `get_input_routing`
returns for an UN-sidechained compressor's default input — this decides whether V1's
"non-track input → no-op" can tighten to an Ableton-authoritative auto-CLEAR.

## DEEP-RACK-ADDR — depth-N device addressing (read/set/automate/durable)

**Status:** PENDING — attended Live session (Ableton occupied at build time).
**Visual change:** no. **Re-vendor:** REQUIRED before these checks — Chunks 1 & 3
flip the MCP fingerprint. Sequence: relaunch dev-mode (`/mcp` respawn so
running==disk) THEN `/ableton-mcp-install` (Live restart — Control Surface
modules are cached at startup).

Unit-proven: `_resolve_device_path` depth 0/1/2/3 + cap + non-rack descent;
`get_device_chains` recursion reporting `device_path`; capture→DB→push
round-trip of a depth-2 nested param (swell guitar case); nested
`device_parameter` → perform with `device_path`; the perform addressing parity.
What units can't cover (needs real Live):

1. **Read/set at depth** — on swell's track 4 → "Guitar-Dual Amped Heavy" →
   nested "Guitar" rack → "Guitar Dead Notes" MultiSampler:
   `ableton_device(action='get_device_chains', track_index=4, device_index=1,
   detail='full')` reports the nested MultiSampler with a `device_path`; pass
   that path to `set_parameter` and confirm the nested param changes audibly.

2. **Durability** — set a nested param via `device_path`, snapshot
   (`/song-snapshot`), `build.py --reset`, `push_cli execute` → confirm the deep
   value SURVIVES the rebuild (the headline bug: deep fix used to revert).

3. **Nested automation** — author a `device_parameter` envelope on a nested
   device; `push_cli execute` → it routes to `perform_batch` with `device_path`
   and materializes as arrangement automation on the nested param.

4. **Ask #4 — Voices probe (DECIDES a follow-up):** run
   `ableton_device(action='get_parameters', ...)` with the MultiSampler's
   `device_path` and observe whether **"Voices"** appears as a DeviceParameter.
   - **Appears** → ask #4 is fully covered by this work (read/set/durable via
     the param path); close it.
   - **Absent** (voice count is a non-parameter LOM property) → file the
     conditional follow-up: a capability-probed *settable-property accessor* on
     the device handler (probe + adapt, never whitelist). NOTE its durability
     caveat up front: the `device_parameters` table doesn't hold non-parameter
     properties, so a property accessor needs its own persistence story or it
     won't survive a rebuild — scope that before building.

## NODE-ADDR (DEV-9K7N) Chunk B — capture execute + depth-N durability

Visual change: no (data/round-trip). Needs a running Live + the swell set.
Code shipped + full suite green 2026-06-15; these are the Live-side proofs the
build plan names as the verifiable signal + bloat gate (Critic note b).

1. **Acquisition durability (THE signal)** — set swell's `21 Voice Lead`
   `LFO 1 Sync` (a depth-2 nested param) in Live via its `device_path`, then
   `python -m hallucinote.tools.capture_cli execute --song swell` →
   `capture_cli diff` (the change shows) → merge/overwrite →
   `build.py --reset` + `push_cli execute` → confirm the depth-2 value SURVIVES
   the rebuild **without saving the .als** (the capture wrote it to source).

2. **Full-set fidelity** — `capture execute` on swell produces a snapshot whose
   `diff` against the committed one is empty (or only the intended edits) — i.e.
   the in-code walk captures the same surface the by-hand recipe did (tracks,
   returns, master, sends, top-level + nested devices), no dropped state.

3. **Bloat-measurement gate (Critic note b — DECIDES a follow-up):** after a
   clean `capture execute` on swell, measure per-device captured non-default
   param count + total snapshot growth vs the prior snapshot.
   - Within ~25 params/preset and snapshot ≤ ~2× the by-ear delta → the
     intrinsic-default filter stands; close the gate.
   - A single preset over-captures (>~25) or snapshot > ~2× → schedule the
     bounded preset-default cache (the filter is keeping too much; defaults the
     filter can't see need a per-preset reference). File it with the measured
     numbers.

## NODE-ADDR (DEV-9K7N) Chunk C — per-DrumChain choke_group / out_note

Visual change: no (LOM state / round-trip). **Re-vendor REQUIRED** — Chunk C adds
the `set_chain_property` wire action (fingerprint flips). Needs a loaded **Drum
Rack**: the scratch verification set has only an *Instrument* Rack ("808 Selector
Rack"), whose chains are plain `Chain`s with no choke_group/out_note (live-probed
2026-06-15 — that IS the negative case below). Code shipped + full suite green;
these are the build-plan signal Live can't fake with unit fakes.

Sequence: relaunch dev-mode (`/mcp` respawn so running==disk) → `/ableton-mcp-install`
(Live restart — Control Surface modules cache at startup). Then:

1. **Positive — choke + out_note on a real DrumChain (THE signal).** Load a Drum
   Rack (any kit) on a MIDI track; `ableton_device(action='get_device_chains', …)`
   to find a pad's `chain_index`. `ableton_device(action='set_chain_property',
   node={parent, terminal:'chain', device_index:<rack>, chain_index:<pad>},
   choke_group=1, out_note=60)` → confirm via `ableton_probe` (or by ear) the
   DrumChain's `choke_group`/`out_note` changed.

2. **Durability.** `/song-snapshot` the set → `build.py --reset` + `push_cli
   execute` → confirm the choke group + transpose SURVIVE the rebuild **without
   saving the .als** (push re-asserts them via the `chain` terminal).

3. **Negative — plain Chain teaches, never crashes.** Call `set_chain_property`
   on the 808 Selector Rack's chain[0] (a plain instrument-rack Chain):
   `node={parent:{kind track,index 2}, terminal:'chain', device_index:1,
   chain_index:1}, choke_group=1` → expect the teaching `NotImplementedError`
   ("DrumChain only … see ableton://reference/node-feature-matrix"), NOT a crash.

4. **Matrix.** `ableton://reference/node-feature-matrix` shows `choke_out_note`
   chain cell = SUPPORTED (determination probe).

---

## NODE-ADDR (DEV-9K7N) Chunk F — per-chain mixer state (mute/solo/volume/pan)

Visual change: no (LOM state / round-trip). **Re-vendor REQUIRED** — Chunk F
touches `handlers/`+`actions/` (fingerprint flips). Code done + green (commit
`66e1f58`). Write paths spot-probed live this session (Live 12.4, "808 Selector
Rack"): `Chain.mute` set False→True→False succeeded; `mixer_device.volume/panning`
are settable DeviceParameters. The full round-trip through the NEW handler needs a
re-vendored server. On return, re-vendor then:

1. **Positive — mixer state on a chain (THE signal).** Find a chain via
   `get_device_chains`. `ableton_device(action='set_chain_property',
   node={parent, terminal:'chain', device_index:<rack>, chain_index:<n>},
   mute=True, volume=0.5, pan=-0.3)` → confirm via `ableton_probe` the chain's
   `mute`, `mixer_device.volume.value`, `mixer_device.panning.value` changed.

2. **Universal — works on a PLAIN chain (not just DrumChains).** Run check 1 on
   the 808 Selector Rack's chain[0] (a plain instrument-rack Chain) → mixer state
   applies with NO teaching error (unlike choke/out_note, mixer state is on every
   chain).

3. **Durability.** `/song-snapshot` → `build.py --reset` + `push_cli execute` →
   the chain's mute/volume/pan SURVIVE the rebuild **without saving the .als**
   (push re-asserts via the `chain` terminal; capture filtered to non-defaults).

4. **Matrix.** `ableton://reference/node-feature-matrix` shows `mixer_state`/chain
   = SUPPORTED and `send_levels`/chain = NOT_IMPLEMENTED (chain sends deferred).

> Chunks **D** + **E** need NO operator entry — both are probe-confirmed LOM facts
> (D macro names + E zones = `UNSUPPORTED_IN_LIVE`; D macro values ride the
> already-verified `device_parameters` path). The probes ARE the live evidence.

---

## MICROTUNE Chunk 4 — verify-api close + `/tuning-pull` + drift live-read (2026-06-19)

**Status:** VERIFIED LIVE (Wendy Carlos gamma loaded in Live this session). The
Live-availability gate that blocked verify-api throughout is finally open, so the
whole chain was exercised against real LOM shapes:

1. **verify-api closed.** Probed `song.tuning_system` + sub-fields off the loaded
   gamma tuning; recorded the real shapes in `api-notes-tuning.md` (a flat
   `list[float]` `note_tunings`, not the typed-as-"dictionary" guess; standard
   12-key `reference_pitch`). `read.py`'s `_extract_loaded_tuning` stub closed
   against them → Chunk 1 is now **High confidence**.
2. **`/tuning-pull` end-to-end (live).** Ran `hallucinote tuning-pull apply`
   against a throwaway song DB fed the *real* live probe values → `status:pulled`,
   `step_count:20`, `period_cents:701.955`, `reference_note:60`, cached
   `tunings/wendy-carlos-gamma.ascl` written (20 pitch lines, non-octave period
   `701.955017` as the last degree, unison unlisted), report carries the re-load
   instruction.
3. **Drift-warn — all 3 cases against real shapes.** Fed the captured live probe
   responses through `tuning_notice._read_loaded_tuning` → `LoadedTuning('Wendy
   Carlos gamma', 701.955…)`, then `drift_warning`: **match** (stored gamma) →
   silent; **different** (stored JI, loaded gamma) → `"tuning DRIFT: Live has
   'Wendy Carlos gamma' (period 701.96¢) … authored against 'JI 5-limit major' …"`;
   **nothing-loaded** → `"tuning DRIFT: … expects 'Wendy Carlos gamma' but Live has
   NO tuning loaded …"`. Push re-load instruction copy reads clearly.

**Remaining (LOW, optional):** the drift-warn was exercised via a replay of the
real probe responses (deterministic), not through a full `push_cli execute` over
the live bridge — the live bridge read path itself is the same `ableton_probe`
surface, separately confirmed `ok`. A future attended push of a real alt-tuned
song would close that last cosmetic gap (the "Warnings (push still OK)" section in
a real push summary), but the logic + live shapes are verified.

---

## MICROTUNE Chunk 3 — push tuning instruction + drift-warn (copy + live re-read)

**Status:** SUPERSEDED by the Chunk 4 entry above (VERIFIED LIVE 2026-06-19). The
two parts below were the queued items; both are now exercised against the loaded
gamma tuning — drift copy + all 3 drift cases confirmed. Retained for history.

Two parts needed an attended run, both gated on the **same
Live-availability constraint as verify-api** (a tuning must be *loaded* in a
readable Set — not available when this landed):

1. **Instruction + drift copy (visual change).** On a real alt-tuned song's
   `push_cli execute`, confirm the summary's "Warnings (push still OK)" section
   carries the load instruction (`load songs/<slug>/tunings/<file>.ascl …`) and
   that it reads clearly to an operator. A 12-TET push shows none of it.

2. **Drift live re-read (the one unverified path).** The drift-warn re-reads
   `song.tuning_system` live. The **nothing-loaded** branch rests on the
   live-confirmed `{"type":"NoneType",…}` shape; the **different-tuning** branch
   reads the scalar `name` + `pseudo_octave_in_cents` sub-paths, which are NOT yet
   live-exercised. To verify: (a) push with NO tuning loaded → expect the "NO
   tuning loaded" drift warning; (b) load the *correct* `.ascl` → expect silence;
   (c) load a *different* tuning → expect the "DRIFT" warning naming both. If the
   scalar sub-reads behave differently than assumed, this closes the same
   verify-api gap as `read.py`'s loaded-tuning stub — capture the real shapes in
   `api-notes-tuning.md` and adjust `tuning_notice._read_loaded_tuning`.

---

## BAK-3M9T Chunk 01 — sidechain source round-trips through the durable snapshot

> **2026-06-17 — merged with this check PENDING (user-directed).** PR #178 was
> merged into develop on the user's explicit "please merge" after being told the
> Live round-trip is the remaining merge gate. This is **operator-accepted by
> direction, NOT agent-Live-verified** — the round-trip below has **not** been run.
> Re-verify next time Live is open; the unit tests only exercise a fake
> `get_input_routing` probe (learning #7), so a Live-shape surprise is still possible.

Visual change: yes (live external integration — a dialed sidechain SOURCE the unit
tests verify only against a fake `get_input_routing` probe). This IS BAK-3M9T
**acceptance criterion 5** (the end-to-end trap-category round-trip) for the
sidechain category; fold the other trap categories in when the later chunks land.
Branch `feat/snapshot-sidechain` (merged as `90214d3`, PR #178). On an attended Live run:

1. **Dial a real sidechain.** In a built song, add a Compressor to a track (e.g.
   Bass) and set its "Audio From" to ANOTHER track (e.g. Kick), pick a channel
   (Post FX). Confirm it pumps.

2. **Bake via `/song-snapshot` (the single durable bake).** Run `/song-snapshot`
   → confirm the refreshed `captured_session.json` shows the Bass Compressor entry
   carrying `"sidechain_source": "Kick"` (the source track's surface NAME, not a
   UUID) and `"sidechain_source_channel": "Post FX"`. Confirm a Compressor whose
   input is left at its OWN track default does NOT get a `sidechain_source`.

3. **Rebuild + push reproduces it.** `build.py --reset` + `push_cli execute` (or
   `/ableton-push`) into a fresh set → confirm the Bass Compressor's Audio From is
   Kick again, analyzer-free. The durable round-trip is the keystone claim:
   the sidechain survives a rebuild **without saving the `.als`**.

4. **Clear-on-absence.** Remove the sidechain in Live (Audio From → own track /
   No Input), `/song-snapshot` (field disappears), rebuild → confirm the sidechain
   is cleared, not stale (snapshot is authoritative).

---

## MCP-9R3T Chunk 1 — async render start/status against real Live

Visual change: yes (agent-facing `start`/`status` result shape + live transport
behavior). Branch `feat/async-render-analyze`. The substrate (job registry +
`ableton_render` start/status) is unit-tested with a Live seam; the keystone —
**mechanism A: a detached worker keeps the render alive after `start` returns** —
is verify-api-confirmed FROM CODE (`run_on_main` is thread-agnostic; the
scheduler outlives the request) but the realtime behavior under load needs a live
session. Requires a re-vendor first (`start`/`status` change `ableton_render`'s
wire shape → the fingerprint flips → `/ableton-mcp-install` + Live restart).

On an attended Live run with a built multi-minute song:

1. **`start` returns immediately.** `ableton_render(action='start', song_slug=…)`
   → returns in < ~3 s with `{job_id, captures_dir, eta_seconds,
   expected_stop_beat, poll}` while the transport is rolling — NOT after the full
   render. Confirm the render actually started (transport playing, analyzers
   armed).

2. **`status` long-polls and advances.** `ableton_render(action='status',
   job_id=…)` returns `state='running'` with `progress.current_beat` advancing
   across successive polls; each call returns within ~45 s. Terminal poll returns
   `state='done'` with a well-formed `manifest` (and `manifest_path` on disk) —
   **no false failure**, where the synchronous `render` would have red-timed-out.

3. **KEYSTONE — concurrency (build-plan Done-when #2).** While a render is
   running, issue a concurrent `ableton_session(action='info')` → it must RETURN
   promptly, not hang to timeout behind the render worker. (Per-request sockets +
   thread-agnostic `run_on_main` say it should interleave; this is the one fact
   only Live settles. If it DOES hang, fall back to mechanism B — the long-poll
   `status` is already built, so only the worker spawn is removed.) NOTE: this
   isolates the **Live main-thread** axis. The separate **server-event-loop**
   axis — a `status` long-poll freezing the server — was fixed at the dispatch
   layer in Chunk 2 (async tool wrapper + `anyio.to_thread`), which also covers
   render's `status` (its 60 s socket read no longer blocks the loop). So here
   you're verifying only that Live interleaves the worker's polls.

4. **Busy + failure shapes.** A second `start` while one is running returns
   `{busy: true, job_id}` (no second transport pass). A render that captures zero
   frames lands `state='failed'` with the error in `status`, not a hang.

5. **`status.json` heartbeat still written.** Confirm `<captures_dir>/status.json`
   updates during the render (the registry progress mirrors it) and lands terminal
   at the end — the crash-resilient backing for the in-memory registry.

---

## MCP-5N8K Chunk 2 — async analyze start/status against a real >60s capture

Visual change: yes (agent-facing `ableton_analysis` `start`/`status` result
shape). Branch `feat/async-render-analyze`. Lower risk than Chunk 1 — analyze
runs in the MCP SERVER process (pure DSP, no Live threading), so the worker is a
plain server-thread and there's no keystone. Fully unit-tested with fakes; what a
live run adds is exercising the actual >60s case end-to-end. Requires the same
re-vendor as Chunk 1 (`start`/`status` change `ableton_analysis`'s wire shape →
fingerprint flips → `/ableton-mcp-install`).

Needs a **many-surface song** (a full-band capture with several declared
sections — the case whose DSP exceeds 60s today and red-times-out the
synchronous `analyze`). Render it first (Chunk-1 `start`/`status`), then:

1. **`start` returns immediately.** `ableton_analysis(action='start',
   song_slug=…)` → returns fast with `{job_id, report_dir, eta_seconds=null,
   poll}` while the DSP runs in the background — NOT after the full analysis.

2. **`status` long-polls to done.** `ableton_analysis(action='status', job_id=…)`
   returns `state='running'` (coarse `progress.stage`) within ~45 s per call,
   then a terminal `state='done'` carrying `report` (the lightweight summary +
   `analysis_code.stale`) and `report_path` — with the full MixReport JSON on
   disk at that path. **No false failure**, where the synchronous `analyze`
   red-times-out on the same capture.

3. **Concurrency.** While the analysis runs, a concurrent unrelated MCP call
   (e.g. `ableton_session(action='info')`) must RETURN promptly, not hang behind
   the analyze long-poll. This is delivered at the **dispatch layer**: the
   server's tool wrapper is `async` and offloads the blocking dispatch via
   `anyio.to_thread.run_sync` (server.py), so a 45 s `status` wait occupies only
   its worker thread, not the event loop. (FastMCP runs a *sync* tool INLINE on
   the loop — that would freeze the server, which is why the wrapper is async;
   proven headless by `test_status_longpoll_does_not_block_concurrent_tool_calls`.
   Confirm it holds under real concurrent load.)

4. **Busy + failure shapes.** A second `start` while one is running returns
   `{busy: true, job_id}`. A `start` for a typo'd slug / missing captures lands
   `state='failed'` with the teaching error surfaced through `status` (not a
   hang).

5. **Synchronous `analyze` still works** as the fast path for a quick
   few-surface capture (the disposition keeps it).

---

## MCP-9R3T Chunk 3 — sync-render retirement + re-vendor handshake (PR 2)

Visual change: yes (the `ableton_render` action surface changed — `render` is
gone). Branch `feat/mcp-render-analyze`. PR 2 edits `actions/render.py` +
`handlers/render.py` + `handlers/jobs.py` (all in `_FINGERPRINT_PATHS`), so the
server fingerprint flips → the running server reports a version mismatch against
the previously-vendored Remote Script until re-vendored.

1. **Re-vendor handshake.** After merging PR 2, run `/ableton-mcp-install` (or
   relaunch the dev-mode plugin, then install) to re-vendor, then reconnect. A
   call should NOT report a version mismatch once the vendored RS matches the
   running server. (Same handshake the PR #185 / Chunk-1 entries need — one
   re-vendor covers the whole async render/analyze surface.)

2. **Retired `render` action.** `ableton_render(action='render', song_slug=…)`
   returns a teaching unknown-action error whose `valid_actions` include `start`
   and `status` (verified headless; confirm the deployed surface matches).

3. **`start`/`status` are the render entry** and behave as in the Chunk-1 entry
   above (start returns fast; status long-polls to a terminal state with a
   well-formed manifest; no false failure).

---

## PSH-3K9D — devices-phase diff-reconcile skips already-current params (live bridge)

**Status:** PENDING — needs an attended Live session. **Visual change:** no
(no UI; verify via the dispatched-call count + state-file warnings). Added
2026-06-19, AFTER the 2026-06-14 blanket acceptance, so it blocks `/pr create`
until run. The unit suite proves the diff logic against a fake `send_fn`; only a
real bridge proves the `ableton_device(action='get_parameters', detail='full')`
read returns the value shapes the comparison assumes (raw `value`, `value_display`
from `str_for_value`, enum `value_items`, `min`/`max`).

Why it can't be auto-verified: the push reads live param values from a running
Live set; there is no headless stand-in for the real device-parameter surface.

Checks (on a just-captured set — e.g. `alien` or `swell`, chains loaded + captured
via `/song-pick-instruments`, then probe-and-link so devices are linked):

1. **Already-current ⇒ ~0 dispatched.** `push execute <session> --song <slug>
   --only devices --probe`. Expect the `devices` phase to dispatch **~0**
   `set_parameter` calls (the warnings/state report "N param(s) already current
   in Live — skipped"), and complete in **seconds**, not minutes. This is the
   reported stall, gone.
2. **One genuine change ⇒ exactly one write.** Dial one param in Live (or edit
   one `build.py`/snapshot value), re-run `--only devices`. Expect exactly that
   one param dispatched, the rest skipped.
3. **Fresh-set first push unchanged.** Push the song into a *fresh* set (devices
   not pre-loaded): loads happen, then the convergence re-plan applies all
   captured params (NOT diffed — a freshly-loaded device is at factory defaults);
   the diff fires no reads on that path. Confirm the full devices phase still
   completes and params land.
4. **Value-shape coverage.** Confirm the skip works across an enum param (e.g. a
   Filter Type), a `value_raw` param (Wavetable `LFO * S. Rate`), and a
   normalized/display continuous param — none falsely re-written, none falsely
   skipped (spot-check one dialed value survives a no-op push).

## SYN-4R7P — probe-and-link re-materializes the arrangement after a Live delete

**Status:** SUPERSEDED by ARR-PROJ (Chunk 4, 2026-06-22). The probe-and-link
arrangement-clip reconcile this entry was written to verify has been **removed** —
the arrangement is now materialized as a pure projection of the DB (clear +
create+fill every push, see `plan_push_arrangement`), so a Live-side delete /
renumber is absorbed by the next push's clear+rebuild, with no positional link to
reconcile. The behaviors below (`unlinked_stale_arrangement_clips` reported,
re-duplicate-via-reconcile, rebind-on-renumber) no longer exist, so this check is
moot. The live obligation it carried is replaced by the **ARR-PROJ** entries: the
Chunk-1 spike (two full Drums-track rebuilds, `net_noop_vs_baseline=True`, already
recorded) plus the still-pending ARR-PROJ live e2e (clear+rebuild idempotence on a
real multi-section set). No longer blocks `/pr create`.

<details><summary>Original SYN-4R7P checks (historical — verify the removed reconcile)</summary>

The unit suite proved the reconcile logic against an injected
`live_arrangement_clips_by_track` map; only a real bridge proved the live read —
`ableton_clip(action='list', location='arrangement')` per track — returned
placements shaped as the reconciler assumed (`arrangement_clip_index`,
`start_beats`, `length`), so position-matching bound to the right clip.

1. **The reported bug is gone.** Delete the arrangement clips in Live (timeline
   lane empty), then `push execute <session> --song <slug> --only arrangement
   --probe`. Expect probe-and-link to report `unlinked_stale_arrangement_clips`
   (the dropped links), the `arrangement` phase to **re-duplicate** the placements
   from the session clips (NOT crash with `IndexError: clip_index out of range`),
   and the timeline to re-populate.
2. **Note edit → re-materialize loop.** Edit notes in `build.py`, rebuild, `--only
   clips` (updates session clips), delete the stale arrangement clips, `--only
   arrangement --probe`. Confirm the arrangement now plays the edited notes.
3. **Untouched arrangement is a no-op.** Re-run `--only arrangement --probe`
   without deleting anything. Expect `unlinked_stale_arrangement_clips == []`,
   `rebound_arrangement_clips == []`, and the phase to refresh notes in place (no
   re-duplication, no doubling).
4. **Renumber re-bind.** Delete ONE early arrangement clip (Live re-numbers the
   rest), then `--only arrangement --probe`. Expect the survivors to be re-bound
   (`rebound_arrangement_clips` non-empty) and only the deleted one re-duplicated —
   no duplicate placements.

</details>

## Bug 1 (incoming 2026-06-20) — arrangement-clip read gains note_count + muted

**Status:** ✅ **VERIFIED LIVE 3/3 2026-06-20** (Live attended; develop @ `41665f1`,
server fingerprint `0fd1cec33ebc`, Remote Script re-vendored + Live reopened by the
operator). Checked on a freshly-pushed `alien` (5 MIDI tracks; arrangement
materialized via `push execute --only arrangement`). **Visual change:** no (read
payload only).

1. ✅ **note_count is real.** `ableton_clip(action='list', track_index=5,
   location='arrangement')` on the Drums MIDI track returned every clip with a real
   per-clip `note_count` (intro 62, verse1 503, prechorus1 155, chorus1 82, verse2
   333, prechorus2 162, chorus2 236, bridge 111, chorus3 770, outro 33) + `muted:
   false` per clip — counts vary sensibly per section, not a stub. The "track shows
   no events" question is now answerable without a probe.
2. ✅ **Audio clip → None.** Drove a real WAV (`master.wav` from the captures dir)
   onto an audio track via `ableton_probe(call, create_audio_clip)`, then
   `ableton_clip(list, ..., location='arrangement')` returned the clip with
   `note_count: null` (guarded — no crash; get_notes_extended is MIDI-only) and
   `muted: true` (real state). Test clip deleted after.
3. ✅ **Signpost is visible.** `ableton_arrangement(action='help')` `info` action
   tip reads: "For the per-track clip inventory (...muted, note_count) ... read
   ableton_clip(action='list', ..., location='arrangement'), not this tool."

_Original entry:_ Touches `handlers/clip.py` + `actions/arrangement.py`.

Why it can't be auto-verified: the unit suite proves the payload shape against a
fake clip; only a real bridge proves Live's `clip.get_notes_extended` /
`clip.muted` / `clip.is_midi_clip` behave as the handler assumes on a live set.

Checks (on any pushed song with an arrangement, e.g. `alien`/`swell`):

1. **note_count is real.** `ableton_clip(action='list', track_index=N,
   location='arrangement')` on a MIDI track returns each clip with `note_count`
   matching its actual note count and `muted` reflecting its state. A long but
   empty clip reports `note_count: 0` (the original "track shows no events"
   question now answerable without a probe).
2. **Audio clip → None.** On an audio track's arrangement clip, `note_count` is
   `null` (not a crash — get_notes_extended is MIDI-only and is guarded).
3. **Signpost is visible.** `ableton_arrangement(action='help')` / the `info`
   action surfaces the tip pointing at `ableton_clip(action='list',
   location='arrangement')` for the per-track inventory.

## Bug 2 (incoming 2026-06-20) — rack presets load from browser_path; pan via normalized

**Status:** ✅ **VERIFIED LIVE 4/4 2026-06-20** (Live attended; develop @ `41665f1`,
server fingerprint `0fd1cec33ebc`, Remote Script re-vendored + Live reopened by the
operator). Fresh full push of `alien` onto a fresh default set
(`probe-and-link --auto-session` → `execute --probe`): the devices phase dispatched
**all 1219 calls cleanly** — vs the pre-fix run which halted here with **771
failures** (the `.last-push-errors.json` from that run is preserved and shows BOTH
bug signatures: `chain_index N out of range [1, 0]` from empty-shell racks +
`AMP1 Pan ... DisplayValueError`). **Visual change:** yes (rack tracks fill).

1. ✅ **Rack `.adg` loads populated.** Drum Rack `AG Techno Kit` → `chain_count: 16`,
   every pad chain has its real Simpler + per-pad FX (Erosion Legacy, Reverb,
   nested Audio Effect Racks → EQ Eight at depth-2 `device_path [[6,3],[1,1]]`); per-
   chain volumes landed at captured non-defaults (0.807/0.657/0.745…). Instrument
   Rack `Inclement Drone Pad` → `chain_count: 2` (Grainy Electric Shield:
   MultiSampler+AutoFilter+Reverb; Drift: Drift+EQ8+Reverb+Echo). No empty shell,
   no `chain_index out of range` cascade.
2. ✅ **`.adv` device preset.** `Metalic Lead.adv` loaded as a real Analog carrying
   the preset's macro/param state (non-default PB Range "6.00", Volume −4.6 dB, Note
   PB Range 48st, Glide On, OSC2 Octave +1 / Semi +4, vibrato dialed) — not a
   factory Analog.
3. ✅ **Pan via normalized (§3).** AMP1 Pan landed at its captured `0.5079365` ("1R",
   non-default; default is 0.5/"C") — the exact value the pre-fix run hard-failed on.
   Controlled live re-test on the device: `value_display='50L'` → server raises
   `DisplayValueError: ... non-numeric display (' 50L'..' 50R'); set it via the
   normalized value`; `value=0.0` (normalized) → ok, lands `" 50L"`. The planner
   automates exactly this (`push_execute.py:_attempt_set_parameter_fallback` →
   `fallback_kind="normalized"`, annotated `set_parameter_fallback`). No hard failure.
4. ✅ **Built-in still kind-only.** Operator (track 6) + Wavetable (track 7), captured
   with non-preset browser_path, loaded by kind with their own non-default params
   (Operator: Algorithm/Osc-A Wave, Volume −18 dB; Wavetable: Osc 1 Pos, Unison 30%,
   Volume −9 dB). No regression.

> ⚠️ **Full push completion blocked by a SEPARATE, newly-exposed bug** (filed
> bug report "Push apply crashes on unknown result kind `device_chain_props` → full
> push of a rack-preset song never completes"):
> the devices-phase result-apply raises `ValueError: unknown push result key kind
> 'device_chain_props'` (`sync/push/plan.py`) once the rack chains actually load and
> their `set_chain_property` calls succeed — the twin of the 2026-06-18
> `device_param_override` apply bug, one key over (missing from `_ACK_ONLY_KINDS`).
> Device LOAD (this Bug 2) is correct; the chain-props apply gap it exposes blocks
> phases after `devices`. One-line fix; arrangement was materialized here via
> `--only arrangement` to finish the Bug 1 checks. Re-verify the single-pass full
> push once that lands.

_Original entry:_ Touches `handlers/device.py`.

Why it can't be auto-verified: the unit suite proves the resolution + emission
against a fake browser; only a real bridge proves Live's browser resolves a
captured `.adg`/`.adv` path to the actual preset, and that a dialed pan dials
correctly via the normalized value.

Checks (on `alien` / `compose/swell`, or any song with rack-preset instruments,
pushed onto a FRESH Live set):

1. **The reported bug is gone.** Fresh full push of a song with Drum Rack /
   Instrument Rack `.adg` instruments captured with browser_path only. Confirm
   each rack loads POPULATED (`ableton_device(get_device_chains, ...)` →
   `chain_count > 0`, the real chains) — NOT an empty shell — and the nested
   per-pad/per-chain params land (no `chain_index out of range` cascade).
2. **`.adv` device preset.** A track whose instrument is an `.adv` preset (e.g.
   Analog "Metalic Lead") loads the preset's macro state, not a default Analog.
3. **Pan via normalized (§3).** Push a track with a dialed Analog pan (`AMP1 Pan`
   ≈ `50L`). Confirm it lands at the correct pan with NO `DisplayValueError`
   surfacing as a hard failure (the planner's display attempt is refused, then
   the normalized retry succeeds — visible as `set_parameter_fallback:
   "normalized"` in the push state, or simply a correctly-panned track).
4. **Built-in still kind-only.** A native device captured with a non-preset
   browser_path (no `.adg`/`.adv`) still loads by kind cleanly (no regression).

---

## PSH-3H8M — perform_batch transport watchdog + loop/punch pre-perform reset

**Status:** PENDING — needs an attended Live session + a perform pass. **Visual
change:** minimal (loop/punch buttons toggle off during a perform and restore
after; the abort surfaces as a structured error, not a hang). Added 2026-06-21.

**Re-vendor REQUIRED:** the fix lives in `hallucinote_mcp/handlers/automation.py`,
which IS in `_FINGERPRINT_PATHS`, so the server fingerprint flips and the install
handshake will (correctly) flag the drift — relaunch dev-mode (`/mcp` respawn so
running==disk), then `/ableton-mcp-install`, then reopen Live.

Why it can't be auto-verified: the bug is a REAL Live transport stall (manual
stop / residual transport state from an interrupted perform / a loop region
trapping the playhead). The unit fakes model a frozen `current_song_time`, but
only real Live proves the watchdog fires on an actual stall, that clearing a real
loop region lets the playhead traverse the full span, and that no legitimately
slow pass (a high `slowdown_factor`) false-trips the 15 s stall window. Pairs
naturally with the ENV-8K2R / ENV-7G4K perform smoke already queued — run them in
one perform session.

Recipe: `ableton_automation(action='perform_batch', arcs=[...])` directly, or
`push_cli plan performed_automation` then execute.

1. **Watchdog fires fast on a real stall (the deliverable).** Start a perform
   over a multi-bar span, then manually STOP the transport mid-record (the exact
   repro from the report). Confirm the call aborts within ~15 s with the
   structured `TimeoutError` naming the stuck beat ("transport stopped advancing
   at beat X of the Y-beat span …"), NOT an indefinite hang requiring `kill -9`.
   Afterward the set is disarmed (`record_mode` / `session_automation_record`
   both read False) and the transport is stopped.
2. **Loop region no longer traps the playhead.** Set a Live loop region that does
   NOT cover the whole perform span (pre-fix: the playhead loops inside it and
   never reaches `union_end` → hang until the wall-clock ceiling). Run the
   perform → it COMPLETES (the pre-perform reset cleared the loop so the playhead
   traversed the full span), and the loop region is RESTORED (on, same bounds)
   afterward. Repeat with punch-in/out enabled → cleared during, restored after.
3. **No regression on a clean, legitimately-long pass.** A normal perform with
   the transport advancing — including a high `slowdown_factor` (e.g. 4×, a
   genuinely slow but ADVANCING playhead) — completes exactly as before, with NO
   spurious loop/punch churn (a set with loop/punch already off writes neither)
   and NO false watchdog abort (the stall window only trips on a frozen, not a
   slow, transport).

---

## RND-2R9K — render leaves RETURN-track names clean (analyzer rename undone)

**Status:** PENDING — needs an attended Live session. **Visual change:** yes
(return names in Live's return strip: after a render they read e.g. `A-Reverb`,
NOT `A-Reverb | HallucinoteAnalyzer`). Added 2026-06-21.

**Re-vendor REQUIRED, with a gotcha:** the fix lives in
`hallucinote_mcp/analyzer/setup.py`, which the analyzer sweep runs **Live-side**
(`runs_on_worker=True` + `context.run_on_main`), so the running Remote Script
must carry the new code — relaunch dev-mode (`/mcp` respawn so running==disk),
then `/ableton-mcp-install`, then reopen Live. **Gotcha:** `analyzer/` is OUTSIDE
`_FINGERPRINT_PATHS`, so this change does NOT flip the server fingerprint — the
install/handshake will report `matched` even against a STALE Remote Script that
lacks the fix. Do not trust the version match to tell you a re-vendor is needed;
force it.

Why it can't be auto-verified: the bug IS Live's native rename of returns on
`browser.load_item` — a real-Live side effect the unit fakes cannot model (they
append the device without renaming). The unit suite proves the pure restore
decision (`_return_name_restoration`) and that the sweep restores a pre-set dirty
name; only a live render proves Live actually renames, that the restore sticks,
and — the one thing the fakes can't prove — that the restored name shows a
**single** slot prefix (`A-Reverb`), not a double (`A-A-Reverb`), i.e. that the
strip-prefix-and-set-bare-name decision matches Live's setter semantics (the
W3-H / W4-C documented contract).

Checks (a pushed song with two returns named `Reverb` / `Delay`, e.g. `alien`):

1. **Render → returns end clean (the deliverable).** `ableton_render(action=
   'start', song_slug=…)` (even a render that then fails is enough — the
   analyzer auto-load runs before the transport gate). Then `ableton_return(
   action='list')`: each return reads its bare authored name with Live's single
   slot prefix (`A-Reverb`, `B-Delay`) — NO ` | HallucinoteAnalyzer` suffix and
   NO doubled prefix (`A-A-Reverb`). The HallucinoteAnalyzer device is STILL
   present on each return (the fix restores the NAME, it does not remove the
   device).
2. **probe-and-link is clean post-render.** `push probe-and-link --song <slug>
   --probe` → `unmatched_db_returns: []` and `unmatched_live_returns: []`
   immediately after a render, with no hand-rename step. (Pre-fix this required
   the manual `ableton_return(action='rename')` workaround.)
3. **Self-heals a pre-dirtied set + no churn.** On a return manually renamed to
   `Reverb | HallucinoteAnalyzer` (simulating a pre-fix render), run a render →
   confirm the name is cleaned to `Reverb`. On an already-clean return, confirm a
   render does NOT rewrite the name (no spurious name-change in Live's undo
   history; the restore is read-only when no suffix is present).
4. **Tracks/master untouched.** Confirm a render still leaves audio-track and
   master names exactly as authored (Live renames returns only; the fix is
   return-scoped).

---

## 2026-06-22 — ARR-ORPHAN: `replace_notes` true total-replace (fix/arr-orphan)

Visual change: no. **Fingerprint flip: YES** — `handlers/clip.py` is a wire-shape
file, so this change bumps the MCP server fingerprint. The running server (the
`--plugin-dir` dev bridge / marketplace) is at the pre-change fingerprint; the
re-vendor handshake is part of this verification. Relaunch dev-mode (`/mcp`
respawn so running==disk) → `/ableton-mcp-install` → reopen Live so the Remote
Script carries the new handler.

Why it can't be auto-verified: the bug IS Live's native `Clip.set_notes()` NOT
fully clearing pre-existing notes on an **arrangement** clip — a real-Live side
effect the unit fakes cannot model (the `FakeClip` overwrite is clean; the
bug-faithful `OrphanProneArrangementClip` only *simulates* the merge). The unit
suite proves the handler now full-extent-clears before `set_notes` and reports
`notes_present`; only a live run proves Live actually leaves orphans without the
clear, and that the clear removes them.

Checks (a pushed song with an arrangement clip carrying known stale notes — e.g.
`alien` `Drums chorus2`, or hand-seed orphans via `ableton_probe` →
`arrangement_clips[i].add_new_notes`):

1. **Orphans cleared (the deliverable).** On an arrangement clip that holds
   stale notes from an earlier generation, call `ableton_clip(action=
   'replace_notes', location='arrangement', track_index=…, clip_index=…,
   notes=[…the exact intended set…])`. Then `ableton_note(action='list',
   location='arrangement', …)`: the clip holds EXACTLY the written set — no
   surviving orphans (pre-fix it held written + orphans).
2. **`notes_present` reports the truth.** The `replace_notes` result includes
   `notes_present` equal to the audible note count after the write (== written
   when no collapse; < written for stacked same-(pitch,start) wildness; it must
   NOT exceed written). Confirm the field is present and accurate.
3. **No cry-wolf on collapse.** On a clip whose intended set has stacked
   same-(pitch, start) notes (e.g. an `add_wildness` section), confirm
   `replace_notes` returns `notes_present` < `notes_written` with **no** orphan
   warning (collapse is faithful, not a leak).
4. **Session view unaffected.** A `replace_notes` on a session clip still
   total-replaces correctly (the defensive clear is harmless there).

---

## 2026-08-06 — TOUR A2: deterministic Ableton screenshot capture (feat/tour-walkthrough)

Visual change: **yes**. Fingerprint flip: no — `tools/` is outside the MCP
wire-shape paths, so no re-vendor and no Live restart is needed for this.

Why it can't be auto-verified: framing and legibility of a screenshot are exactly
what a test cannot speak to, and the capture itself is blocked on a permission
only the operator can grant.

**Blocked, and the block is the first check.** `CGPreflightScreenCaptureAccess()`
returns `False` on this machine, so `screencapture` cannot photograph another
application's window at all — it exits 1 with *"could not create image from
window"*. Everything up to that point is verified: the tool resolves the real
Live window through the window server (`--list` prints `id 56749 layer 0
1576x949` against a running Live) and refuses with a precise, actionable error
naming `Visual Studio Code.app`, writing no file and without stealing focus.

Checks (Live running with the demo set open):

1. **Grant the permission.** System Settings → Privacy & Security → Screen
   Recording → enable the application hosting the terminal (the tool names it;
   here `Visual Studio Code.app`). **Restart that application** — the grant is
   read at launch, so a running process keeps its old answer.
2. **It captures the window, not the screen.** `python
   tools/capture_live_shot.py --out /tmp/shot.png` writes a PNG showing the Live
   window alone — no desktop, no other application, and no soft grey drop-shadow
   halo around the edges (that is what `-o` removes).
3. **Fixed width, which is the determinism being promised.** The image is
   exactly 1600 px wide. Run it twice without touching the Live window: both
   images have identical dimensions.
4. **It refuses rather than photographing the wrong window.** Open a plug-in
   editor or Preferences so Live owns two normal windows, then run it again: it
   must error listing both ids and sizes and capture nothing. `--window-id
   <id>` from that listing then captures the one you chose.
5. **Legibility at the committed width.** Open the result and confirm clip
   names, device names and the transport are readable at 1600 px — this is the
   width the tour ships, and text that is unreadable there makes the screenshot
   worthless regardless of framing.

---

## 2026-08-06 — TOUR A4: lifecycle diagram, light/dark aware (feat/tour-walkthrough)

Visual change: **yes**. Fingerprint flip: no — `docs/` is outside the MCP
wire-shape paths.

Why it can't be auto-verified: an SVG's correctness is whether it *reads*, and
on the surface that matters — a GitHub page, in the reader's theme.

Already verified locally, so these checks are about GitHub specifically: the file
is well-formed XML with zero external references (no font, no image, no
`@import`), and all four theme combinations were rendered in headless Chrome and
inspected — light palette on white, dark on `#0d1117`, and **both mismatched
pairings**. The mismatch cases are the point: the `prefers-color-scheme` query
follows the operating system while GitHub's light/dark toggle is its own setting,
so the two can disagree. Every piece of text sits inside an opaque card
specifically so that a disagreement changes only the colour of the gaps.

Checks (on the pushed branch's rendered page, not a local preview):

1. **It renders at all.** `docs/assets/lifecycle.svg` displays on the GitHub page
   rather than showing a broken-image icon — the failure mode when a sanitizer
   strips something the file depends on.
2. **Light theme.** With GitHub set to light, the cards read as light panels with
   dark text; connectors and arrowheads are visible against the page.
3. **Dark theme.** Switch GitHub to dark and reload. The cards must not stay
   light-on-light or go dark-on-dark; text stays legible and the return arrow is
   still visible.
4. **Theme mismatch.** Set the OS to one scheme and GitHub to the other. The
   diagram may look inverted relative to the page — that is expected and
   accepted — but every label must remain readable.

---

## 2026-08-07 — TOUR B1: the engine/MCP fix batch (feat/tour-walkthrough)

Visual change: no. **Fingerprint flip: YES.**

This is the ship instruction for the bundle. Six files inside
`_FINGERPRINT_PATHS` changed (`schema.py`, `dispatcher.py`, `actions/device.py`,
`handlers/browser.py`, `handlers/device.py`, `remote_script/dispatch.py`), so the
Remote Script vendored into Live's User Library is **stale until re-vendored**.
Until the handshake below, Live keeps running the old code and none of the
Live-side fixes take effect — silently, because a stale script still answers.

The `run_on_main` concurrency rewrite is the load-bearing one: its admission
control and per-bout timeouts are Live-side, and its thresholds can only be
confirmed against a real Live. It now has 26 unit tests against an injected
scheduler, but those prove the state machine, not the deployment.

Checks:

1. **Re-vendor and restart.** Run `/ableton-mcp-install`, then **quit Ableton
   Live completely and reopen it** — Live caches Control Surface modules at
   launch, so a running instance keeps the old script. Then `/mcp` to respawn the
   server. Confirm `ableton://server/info`'s `fingerprint` matches the vendored
   copy (`preflight` reports `matches_mcp_server: true`).
2. **The browser-path fix takes effect.** Push a song whose snapshot names a
   preset that is a strict prefix of a sibling — Live's `Kit-BritishVintage.adg`
   beside `MPE Kit-BritishVintage.adg` is the case that broke. The devices phase
   must load the captured kit rather than refusing the pair as ambiguous.
3. **A slow Live call no longer hangs the DAW.** Start a long operation (a large
   `devices` push), and while it runs issue a second call from another surface.
   The second must come back as a REFUSAL naming the incumbent operation and its
   elapsed time — not block, and not stack behind it.
4. **The do-not-retry message is now reachable.** This is the one that was
   provably unreachable before: every client read timeout equalled its Live-side
   ceiling while admission burned up to 2 s first, so the client always gave up
   first and the agent saw a bare socket timeout. Force a bounded operation past
   its `main_thread_timeout` and confirm the reply is Live's "IT IS STILL RUNNING
   — Do not retry immediately", not `FrameError: socket read timed out`.
5. **Captures land in the right workspace.** With a song in a workspace nested
   below the session root, `ableton_render` must write into that workspace's
   `captures/`, NOT into a `songs/<slug>/` tree at the repo root. The old
   behaviour created that tree silently and stranded ~290 MB in it.

---

## 2026-08-07 — PSH-DEVDUP: the devices phase must not double an FX chain (fix/devices-duplicate-chain)

Visual change: no. Fingerprint flip: no (engine-side only — `src/hallucinote/sync/`;
no `hallucinote_mcp` handler, schema or Remote Script file changed, so no
re-vendor and no Live restart is needed).

What shipped: `push_cli execute` now probes each linked parent's device chain
(`ableton_device(action='list')`) once per push, reconciles the DB↔Live device
links from it, refuses to emit a `load` onto a slot Live already occupies, and
re-probes after the phase to assert no chain came out duplicated.

**What cannot be proven without Live**, and is therefore queued here rather than
claimed: the fix rests on a model of Live 12.4 in which (a) a device `load`
always TAIL-APPENDS to the destination chain, and (b) `ableton_device(list)`
reports `class_display_name` for a preset-loaded device identically to what
`/song-snapshot` stored as the DB's `kind` (the `the-argument` evidence says it
does — `Tension`, `Instrument Rack`, `Amp` all matched positionally when
`probe-and-link` ran at 04:32 — but that is one set). If (b) is false for some
device class, the reconcile won't bind it and the push will REFUSE rather than
duplicate: safe, but it will look like a false halt. Checks 3 and 4 are what
would surface that.

Checks (run against the repaired `the-argument` set, or any song with a
snapshot-loaded FX chain):

1. **Idempotent re-push appends nothing.** With the set already carrying every
   chain, run `push execute <session> --song <slug> --probe`. The devices phase
   must report ok, dispatch **zero** `load` calls, and `ableton_device(list)` on
   each track must show the same chain length as before. Repeat once more — the
   second run must also be a no-op. (Before the fix, each run appended a full
   copy of every post-instrument effect.)
2. **A rebuilt DB still appends nothing.** Run `python songs/<slug>/build.py
   --reset`, then re-push with `--probe`. Same expectation: zero loads, chain
   lengths unchanged.
3. **A genuinely missing device still loads.** Delete one effect from the end of
   one track's chain in Live, re-push. That one device must load (and only that
   one); the rest of the chain must be untouched.
4. **A drifted slot refuses instead of doubling.** Replace one mid-chain effect
   in Live with a different device class (e.g. swap an Overdrive for a Phaser),
   re-push. The devices phase must HALT before dispatch with `REFUSING to load
   …`, naming the track and the device it saw, and dispatch zero loads. Confirm
   the recovery it names works: `push probe-and-link <session> --song <slug>
   --probe` then re-push.
5. **The integrity assert catches an already-doubled set.** On a set you have
   deliberately doubled by hand (duplicate one effect on one track), re-push.
   The phase must halt with `devices integrity: … DUPLICATE`, naming the track,
   rather than reporting ok.
6. **A trailing HallucinoteAnalyzer is invisible to all of the above.** Run a
   render first (so every chain ends with the analyzer), then repeat check 1.
   Still zero loads, still ok — the analyzer must neither be matched against an
   authored slot nor counted as an extra device.

## 2026-08-11 — TOUR C1+D1: the tour's evidence set and the rendered pages (feat/tour-evidence)

Visual change: yes — committed screenshots, waveform stills, and two rendered
markdown pages (README "See it" graft + the new `docs/tour.md`).

What shipped: the C1 evidence set under `docs/assets/` (4 screenshots, 3 audio
clips each with a waveform still, all produced by the A2/A3 tools or curated
from the 2026-08-11 punk-fate session's tool-captured frames) and `docs/tour.md`
grafted into the README. The freshness tests are machine-verified (adversarial
red/green recorded in the D1 close); what needs eyes:

1. **The audio is the right audio.** Play `docs/assets/tour-chapter1.mp3`
   (the final render; renamed from `tour-full.mp3` when the chapter-2
   listening session was planned), then the A/B pair `tour-chorus-before.mp3` /
   `tour-chorus-after.mp3` (same verse→chorus passage, bars 21–36). Before
   should audibly clip with a buried bass; after should hold together with the
   bass carrying. If the pair sounds identical, the wrong capture round was
   encoded.
2. **The screenshots read at README/tour width.** On the pushed branch's
   rendered pages (both GitHub themes): the off-grid MIDI shot must visibly
   show notes ahead of gridlines; the arrangement shot must be legible as
   eight sections; the drum-rack and session-render shots must not be
   squinting material.
3. **Every media link plays/downloads from the rendered page** (GitHub serves
   committed mp3s as download links — the poster/waveform images must render
   inline, the links must resolve).
4. **The tour reads in ~15 minutes and the story holds** — beats 0→16, both
   chapters, with no step that requires insider knowledge. Chapter 2's arc has
   to land specifically: the ear-verdict ("not especially punk") → the measured
   cause → the fix, four times over, ending on something deliberately NOT done.

### Chapter 2 additions (v1.8.3 — first public release of the tour)

The items above were written for chapter 1 and were only patched for the asset
rename. These cover what chapter 2 added, none of which any operator has yet
confirmed:

5. **`tour-chapter2.mp3` is the hero render.** README and quickstart both play
   it as *the* song, and it is the one audio item nobody has been asked to
   confirm. It must be the post-tone-pass master: audibly dirtier and louder
   than `tour-chapter1.mp3`, with the lead line reading as a *guitar*, not a
   synth. If it sounds like chapter 1, the wrong capture was encoded.
6. **Chapter 2's two screenshots read at tour width** (both GitHub themes):
   `tour-garage-drums.png` must visibly show the ghost-note scatter along the
   bottom of the velocity lane, and `tour-drum-saturation.png` must show the
   Saturator's drive value legibly enough to read as ~11 dB — it is cited in
   prose as evidence of a specific dialed parameter.
7. **The A/B pair at beat 16 differs audibly**, chapter 1 vs chapter 2. This is
   the release's central claim; if the two renders sound the same to an operator,
   the chapter is not proven no matter what the flatness numbers say.

---

## COLLAB-TURN — the collaboration turn model (2026-09-01)

This one is unlike every entry above it: nothing here needs Ableton. It needs a
**person having a conversation**, because the whole intervention is prose that
shapes how the agent behaves, and no test in this repo can judge a register.
The build plan holds its own Requirements Confidence at *Medium on one axis* for
exactly this reason, and this session is the acceptance test for that axis.

**Why it is not optional.** A near-identical rewrite of these same surfaces
shipped in August and decayed within one take — good on the opening turn, silent
on everything after it. A green suite would have said nothing about that, and
did not.

8. **Start a song from a loaded prompt, in a songs workspace, with the merged
   plugin.** *"Make me a rap song"*, or any prompt of your choosing that carries
   more implications than words. A songs workspace, not this repo — the
   governed-repo heads-up is itself one of the things being tested, and it fires
   here.

   Read the session against three things, each traceable to a recorded failure:

   - **No build before a proposal turn you reacted to.** (CTM-01: an open,
     hedged prompt that got scaffolded from a spec the agent wrote itself.)
   - **Identity was not closed while you were still adding.** An answer of yours
     that brought in a new dimension should have been read as *you have more*,
     never as the last word. (CTM-09: *"That's identity resolved. Scaffolding
     now"*, while the answers were still arriving.)
   - **A hearing was offered at the first hearable unit, and not required.**
     *"Keep going"* must be a real, zero-cost answer, and *"build it all, I'll
     listen at the end"* must be remembered rather than re-asked at every unit.
     (CTM-11: *"shouldn't I be hearing something?"* forty-five minutes in, with
     zero notes taken. CTM-10: a whole song built in one pass and deleted
     unheard.)

   **And watch for the opposite failure**, which is equally real and which this
   work could have reintroduced: if the session stops to summarize and ask
   *"what next?"* at a procedural seam, that is CTM-12 and it is a defect, not
   diligence.

   **If the session shows the wall or the early close again, the finding is
   against the prose lever itself** — the answer is not a seventh chunk of
   prose, it is to bring the external eval framework in sooner, against the
   corpus already seeded at `.prawduct/artifacts/collaboration-corpus/`.
