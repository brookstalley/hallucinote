# Operator Verification — pending attended-run / live-integration checks

Entries here are checks that need a human operator and/or a live Ableton
session that wasn't available when the work landed. `/pr create` surfaces
pending entries when `operator_verification_required: true`.

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
   genuinely-cold-cache-within-60s worst case (CC#60224 silent tool-drop on a
   first-ever numpy/scipy/librosa build) is **not yet proven**. The C2 pre-warm hook is
   the mitigation; verify on a clean machine / fresh `~/.cache/uv` that the tools still
   appear within the timeout (the hook should warm the env before the handshake).
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
