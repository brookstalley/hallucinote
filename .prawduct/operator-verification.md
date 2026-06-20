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

**Status:** PENDING — needs an attended Live session. **Visual change:** yes (the
arrangement timeline re-populates with clips). Added 2026-06-20, AFTER the
2026-06-14 blanket acceptance, so it blocks `/pr create` until run.

The unit suite proves the reconcile logic against an injected
`live_arrangement_clips_by_track` map; only a real bridge proves the live read —
`ableton_clip(action='list', location='arrangement')` per track — returns
placements shaped as the reconciler assumes (`arrangement_clip_index`,
`start_beats`, `length`), so position-matching binds to the right clip.

Why it can't be auto-verified: the reconcile reads the live arrangement lane from
a running Live set; there is no headless stand-in for the arrangement-clip list.

Checks (on a pushed song whose arrangement clips are already placed — e.g. `alien`
or `swell`, after `--only clips` + `--only arrangement` has materialized the lane):

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

## Bug 1 (incoming 2026-06-20) — arrangement-clip read gains note_count + muted

**Status:** PENDING — needs an attended Live session + re-vendor. **Visual change:**
no (read payload only). Added 2026-06-20. Touches `handlers/clip.py` +
`actions/arrangement.py` — both in `_FINGERPRINT_PATHS`, so the server fingerprint
flips: re-vendor (relaunch dev-mode, then `/ableton-mcp-install`) and reopen Live
before checking.

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
