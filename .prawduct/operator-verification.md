# Operator Verification — pending attended-run / live-integration checks

Entries here are checks that need a human operator and/or a live Ableton
session that wasn't available when the work landed. `/pr create` surfaces
pending entries when `operator_verification_required: true`.

---

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
