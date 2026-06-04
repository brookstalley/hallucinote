# Operator Verification — pending attended-run / live-integration checks

Entries here are checks that need a human operator and/or a live Ableton
session that wasn't available when the work landed. `/pr create` surfaces
pending entries when `operator_verification_required: true`.

---

## INS-7V2D — plugin-bundled MCP server launches via uv on a real install

**Status:** PENDING (the plugin is not loaded in the authoring session; the launch
mechanism is proven locally via the shell, not yet via Claude Code spawning it).
**Visual change:** no (objective: do the `hallucinote-mcp` tools connect?).

C1 proved locally that `uv run --frozen --all-packages --project <root>` with
`UV_PROJECT_ENVIRONMENT=<dir>` builds the env and starts the server. What needs a real
install:

1. **Fresh install connects.** `/plugin marketplace add brookstalley/hallucinote` +
   `/plugin install hallucinote@hallucinote` (or `--plugin-dir .`), restart Claude with
   `uv` on PATH, and confirm the `hallucinote-mcp` tools appear (the env builds into
   `${CLAUDE_PLUGIN_DATA}/venv` within the 60s init timeout — watch for the CC#60224
   silent tool-drop on a cold uv cache; the C2 pre-warm hook is the mitigation).
   **0. `uv` must resolve in the SPAWN env (the make-or-break risk).** Claude Code spawns
   stdio MCP servers with a sanitized environment that does NOT inherit the shell's PATH.
   `command: "uv"` (bare) therefore assumes `uv` is on whatever PATH Claude Code's spawn
   uses. `uv` installs to a standard location (`/opt/homebrew/bin`, `~/.local/bin`,
   `~/.cargo/bin`) so it usually resolves — but if the tools DON'T appear, this is the
   first thing to check (run `uv --version` is not enough — it's the *spawn* PATH that
   matters). Fix if needed: an absolute uv path in `command` (the install skill can detect
   it — fold into C3), or add uv's dir to the server `env` PATH.
2. **Update rebuilds the env.** Bump the plugin version / change `uv.lock`, update the
   plugin, confirm the env rebuilds (lock-diff) and the server still connects.
3. **No abs-path override needed.** Confirm `/hallucinote:ableton-mcp-install`'s
   `configure-mcp` now returns `skip` (the uv launch is PATH-independent) — i.e. the old
   override path is dead (formalized when C3 removes it).

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
