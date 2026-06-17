# ONBOARD-M4L — first-run onboarding + non-Max-for-Live graceful degradation

**Status:** REQUIREMENTS (2026-06-16), pending build. Discovery complete (current behavior verified first-hand).
**Source:** release-prep work; user-directed. Sibling concern to the demo song (tabled) and AUD-8K2N (degraded render, deferred).

## Problem (verified)
1. **No first-run orientation** — a new user lands among 30+ skills with no entry point; no `/getting-started` exists.
2. **Cryptic failure without Max for Live** — a non-Suite user who renders or `/mix-review`s hits `preset_query found no loadable matches` (`handlers/device.py:810`), with no mention of M4L and no "what still works." Render fails hard. The analyzer (`HallucinoteAnalyzer.amxd`) is a Max-for-Live device behind render → analysis → `/mix-review`.
3. **`/mix-review`'s M4L dependency is undocumented** at most reference points.

## Decisions (user, 2026-06-16) — load-bearing
- **D1 — Don't infer Live edition / M4L. Ask.** No filesystem (`Max/Max.app`) or LOM (`get_variant`) inference. The render teaching error keys on the **missing device** (ground truth); where edition genuinely matters, ask the user. (Also avoids mac-vs-Windows path divergence.)
- **D2 — Cross-platform: macOS AND Windows.** No OS-specific filesystem logic; hooks mirror the existing prewarm hook's invocation so they behave identically on both. (Risk flagged below.)
- **D3 — `/getting-started` orients, never auto-acts.** It *offers* next steps conversationally and relies on model + conversation context to flow; it does not run `/ableton-mcp-install` itself.
- **D4 — Qualify `/mix-review` as "uses Max for Live / requires Suite" everywhere it's referenced** (a sweep).
- **D5 — First-run nudge is warm + conversational.**

## Goals
- A first-time user is oriented to setup + first song without reading the README.
- A non-M4L user gets an honest teaching error (not a crash) and knows what works without Suite.

## Non-goals (explicitly out)
- The demo song (tabled).
- Edition auto-detection (decided D1: ask).
- Proactive degraded render/analysis without M4L (master-bus-only) — filed **AUD-8K2N** (research).
- A persisted M4L flag — the teaching error keys on the live device, so no stored state is needed.

## Requirements

### A — Onboarding / first-run
**A1 — `/hallucinote:getting-started` skill** (user-invocable, conversational orientation).
- Runs `python -m hallucinote_mcp.cli preflight`; reports each prerequisite's state: uv · engine install · Remote Script + Control Surface slot · analyzer present.
- States honestly what works **with** vs **without** Max for Live (qualifies `/mix-review` per D4).
- When something's missing, **offers** the next step (e.g., "want me to walk through the install?") — never auto-runs it (D3). Proposes a conversational flow — install if needed → "new song or existing?" → hand to `/song-new` or a push — leaning on model+context, not a rigid script.
- *Accept:* on an incomplete setup it names which prereqs are missing + the M4L caveat and ends by **proposing** (not taking) the next step; on a complete setup it says "ready" + the first-song pointer.

**A2 — First-run nudge** (SessionStart hook).
- On the first session, emits `additionalContext`: a warm, conversational greeting pointing at `/hallucinote:getting-started`. Seed: *"Thanks for installing Hallucinote! It helps you plan, compose, mix, and produce any kind of musical work. Run `/hallucinote:getting-started` and I'll help you get set up."*
- Fires **once**, gated by a `${CLAUDE_PLUGIN_DATA}/.onboarded` marker (zero-friction; no question — D5/marker over ask).
- **Cross-platform (D2):** mirror `hooks/prewarm-mcp-env.sh`'s invocation pattern; never fail the session (exit 0); all non-JSON chatter on stderr; only the nudge JSON on stdout.
- *Accept:* first session emits the nudge + creates the marker; later sessions emit nothing; exits 0 on every branch.

### B — Non-M4L graceful degradation
**B1 — Teaching error at the analyzer-load boundary** (`analyzer/setup.py`).
- When the analyzer can't load because it isn't installed, raise a teaching error that: names **Max for Live / Live Suite**; says render + `/mix-review` need it; says **compose / push / pull / `/compose-review` work without it**; tells the user to run `/ableton-mcp-install` (and that Standard needs the M4L add-on). Keys on the **missing device** (D1); does not infer edition. Replaces the cryptic preset error for the analyzer case.
- *Accept:* a unit test on the analyzer-absent load asserts the teaching text (M4L + what-still-works), not the generic preset message; covers every render entry (`render`, `ensure_loaded`).

**B2 — Qualify `/mix-review` everywhere** (D4).
- Every user-facing reference to `/mix-review` carries "uses Max for Live / requires Suite": the mix-review skill, README, song-workflow, FAQ, skills index, compose-review handoff, MCP server instructions — sweep them.
- *Accept:* grep for `mix-review` references; each user-facing one carries the qualifier.

## Build chunks (order)
1. **B1** — teaching error + test (worst current experience; most contained).
2. **A1** — `/getting-started` skill.
3. **A2** — first-run nudge hook + `hooks.json` wiring + test.
4. **B2** — `/mix-review` qualifier sweep.
Then verify (full suite) + Critic.

## Risks / open
- **Cross-platform hooks (D2):** the hooks are bash invoked via `bash "…"`. On Windows this needs a bash shell available to Claude Code. This is a **pre-existing** property of the prewarm hook, not introduced here — the first-run nudge inherits the same behavior. Flag: verify the bash-hook pattern fires on Windows (or both hooks silently no-op there). Not silently assumed.

## Tests
- B1: analyzer-absent load → teaching error text (unit).
- A2: first-run hook — first run emits + marks, second run silent, exit 0 (mirror `test_prewarm_hook.py`).
- B2: a consistency check that user-facing `mix-review` references carry the qualifier (or prose-verified in the Critic sweep).
- A1: skill exists + frontmatter (skill-consistency).

## Status (2026-06-16)
- [x] **B1** — `PresetQueryNoMatchError(ValueError)` seam (`handlers/device.py`) + `AnalyzerNotInstalledError` teaching error at the `_load_analyzer` boundary (`analyzer/setup.py`) + test. Keys on the missing device (D1). Subclass preserves the contract message — preset-query + inventory tests green.
- [x] **A1** — `skills/getting-started/SKILL.md` (orients, offers, never auto-runs); indexed in `docs/skills.md` "Start here" + a README pointer.
- [x] **A2** — `hooks/first-run-nudge.sh` + `hooks.json` wiring + marker in `${CLAUDE_PLUGIN_DATA}`; mirrors the prewarm hook (exit 0, silent-when-onboarded); 6 tests.
- [x] **B2** — `/mix-review` qualified "needs Max for Live / Suite" at every user-facing decision point (README, the skill, catalog, song-workflow doc+skill, FAQ, push handoff, compose-review comparison); internal sibling cross-refs left unqualified (brevity).
- [x] **Verify** — full suite green (**3959 passed, 2 skipped**). The suite caught + fixed a README pipeline-phase-list reflow regression (`test_docs_pipeline_parity`).
- [x] **Critic** (base develop, `final` mode) — **0 BLOCKING**. 2 WARN + 2 NOTE all resolved: W2 (skills.md `/song-attempts` row added), N1 (server primer qualified), N2 (dead `falling-walking` pointer fixed). **W1 (test-evidence freshness) is pre-push bookkeeping** — suite verified green in-session; `.test-evidence.json` re-stamps at commit (not hand-fabricated).

**Remaining:** none in scope. Cross-platform hook behavior on Windows (D2 risk) is inherited from the prewarm hook and is an operator-verify item if/when run on Windows. The demo song is consciously tabled.
