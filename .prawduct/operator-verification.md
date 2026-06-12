# Operator Verification — pending attended-run / live-integration checks

Entries here are checks that need a human operator and/or a live Ableton
session that wasn't available when the work landed. `/pr create` surfaces
pending entries when `operator_verification_required: true`.

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

**Status:** PENDING. The core capability is already live-proven (2026-06-12,
Live 12.4.2: `select master → browser.load_item → delete_device` end-to-end, M4L
Align Delay — `.prawduct/artifacts/research-spike-automation-ingest.md`). Code +
unit tests landed (the gate removed in `handlers/device.py`, `analyzer/setup.py`,
`sync/push/devices.py`); these checks corroborate the integrated paths against a
live bridge. **Visual change:** yes (devices appear on the Master strip).
**Requires:** re-vendor the Remote Script (`/ableton-mcp-install`) + Live
quit/reopen (Live caches Control Surface modules), then `/mcp` reconnect.

1. **Native (non-M4L) device on master (the backlog's before-close caveat).**
   `ableton_device(action='load', master=True, kind='EQ Eight')` on both an
   empty and a non-empty master. Expect: the device appends to the Master chain
   (response `parent_kind='master'`, `master: True`), `delete_device` removes it.
   Rules out a device-class quirk (the proof used an M4L device).

2. **Full push of a DB-authored master-strip chain.** Author a master device
   chain in a song's DB (e.g. a Limiter with a dialed Ceiling); `push_cli
   execute`. Expect: the devices phase emits `device.load(master=True)`, it
   links, the convergence re-plan writes the param, and the push completes
   WITHOUT a PARTIAL halt (the old SYN-2M9P trap is gone).

3. **Render auto-loads the master analyzer on a fresh set.** Open a set with NO
   pre-placed master analyzer; `ableton_render(action='ensure_loaded')`. Expect:
   the sweep auto-loads HallucinoteAnalyzer onto the Master (port 11220), no
   "add it by hand" RuntimeError, idempotent on a second call.

On confirmation, close DEV-6M2K and finalize the re-triage of DEV-2M9K
(verdict retracted) / SYN-2M9P (planner-skip retired) / TPL-2D8K (`.als`
master-template workaround reduced to a convenience).
