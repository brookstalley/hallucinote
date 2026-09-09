---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# PLUGIN-SELF-CONTAINED — the plugin ships the engine; no clone, no PyPI; one `hallucinote` CLI; Windows-safe hooks

**Status:** REQUIREMENTS (2026-06-16), pending go. Discovery done (mechanism verified first-hand).
**Source:** release-prep; user-directed. Resolves the README's "two installs" confusion at the root.

## Decisions (user, 2026-06-16) — load-bearing
- **D1 — No PyPI, ever.** Remove every PyPI reference (`pip install hallucinote`, the `[live]` extra framing, "not on PyPI yet").
- **D2 — Engine works *independently* = it comes WITH the plugin.** No separate clone + editable install for end users. (Option 1, not 2.)
- **D3 — One `hallucinote` CLI to cut the agent's step-sequencing — but keep the *signal* visible.** Hide the plumbing (which env/uv), never the result the agent acts on (build errors, the push **halt cause**). Don't collapse the build→push→verify loop into one opaque command.
- **D4 — Cross-platform (macOS + Windows).** Hooks rewritten in Python (bash isn't guaranteed on Windows).

## Mechanism (verified)
- The repo is the uv **workspace root** (`[tool.uv.workspace] members=["hallucinote_mcp"]`, root project `hallucinote`), so the plugin's launch (`uv run --all-packages --project ${CLAUDE_PLUGIN_ROOT}`) builds **one venv with both the engine and the bridge** in `${CLAUDE_PLUGIN_DATA}/venv`.
- `ableton://server/info` already exposes `package_root` (computed from the running server's `__file__` → inside the plugin, update-safe). The agent uses it to locate the plugin's uv project.
- Engine commands run via **`uv run --project <plugin-project-root> --frozen hallucinote <subcommand>`** — same env as the bridge, always version-synced, no ambient install. cwd stays the songs workspace (paths/`--song` resolve there); uv only supplies the env.

## Requirements / chunks
1. **Unified `hallucinote` CLI** — new `src/hallucinote/cli.py` dispatcher + `[project.scripts] hallucinote = "hallucinote.cli:main"`. Subcommands wrap the existing modules (`build`, `push`, `pull`, `compat`, `capture`, `context`, `melody`/`recurrence` lenses, `inventory`, …) with **unchanged, streamed output** — a dispatcher, not a black box. + tests. *Accept:* `hallucinote push execute …` produces the same visible phase/halt output as `python -m hallucinote.sync.push_cli execute …` today.
2. **`server/info` → `project_root`** — add the uv-project-dir field (the dir with `uv.lock`, = `${CLAUDE_PLUGIN_ROOT}`) so the agent has the exact `--project` arg without parent-traversal. (`resources/__init__.py`, outside `_FINGERPRINT_PATHS` → no re-vendor.) + test.
3. **Skills invoke via the plugin env** — update the engine-calling skills (push, pull, compose-part, song-new, compat, capture, song-context, lenses) + their `allowed-tools` to `uv run --project <project_root> --frozen hallucinote …`, resolving `project_root` from `server/info` once. Retire the ambient `python3 -m hallucinote.*` assumption. *Accept:* a fresh end-user (plugin installed, no clone) can compose + push.
4. **Remove clone + PyPI references** — README (drop the clone/engine step + "not on PyPI"), `docs/engine-pin.md`, and any skill/doc citing the clone, `pip install -e`, or `[live]`. The engine "comes with the plugin."
5. **README restructure — one flow** — end-user: install plugin → connect Ableton → verify → go. Contributor `--plugin-dir` path moves entirely to `CONTRIBUTING.md` (one pointer). No "just use / hack / clone" forks.
6. **Windows-safe hooks** — port `prewarm-mcp-env.sh` + `first-run-nudge.sh` to Python (`python "${CLAUDE_PLUGIN_ROOT}/hooks/x.py"`), exit-0-always discipline preserved; update `hooks.json` + both hook tests. (Independent of 1–5.)

## Risks / open
- **`uv run --project <root> --frozen` from the songs cwd** — verified feasible in principle; **operator-verify on a real install (mac + Windows)** before release.
- **Engine version coupling** simplifies: engine and bridge are the SAME uv env, so `engine-pin.md`'s drift concern largely dissolves (one lock, one env) — revisit that doc.
- **Scope is large.** Windows hooks (6) + the PyPI-reference removal (part of 4) are independent and low-risk. The CLI + plugin-env invocation (1–3) is the architecture core; README (4–5) depends on 1–3 landing (can't fully clean the README while the clone is still required). Staging TBD with the user.

## Status (2026-06-16)
- [x] **6 — Windows-safe hooks** — `prewarm-mcp-env.sh`/`first-run-nudge.sh` → `.py`, launched via `uv run --no-project python` (uv is the one cross-platform-consistent prereq); `.sh` deleted; 14 tests green. (Windows operator-verify pending.)
- [x] **1 — unified `hallucinote` CLI** — `src/hallucinote/cli.py` dispatcher + `[project.scripts] hallucinote`; `capture_cli.main` gained `argv`; 19 tests. **Mechanism proven:** `uv run --project . hallucinote --help` builds the env + runs (exit 0).
- [x] **2 — `server/info` `project_root`** — `install_paths.project_root()` (walks up to `uv.lock`) exposed on the resource; resources test extended. Full suite **3965 green**.
- [x] **3 — skills via plugin env** — ALL engine-calling skills migrated: `ableton-push`, `compose-part`, `song-new`, `ableton-pull` (`allowed-tools` → `Bash(uv run *)`) + `song-snapshot`, `snapshot-bake`, `song-context`, `decisions`, `song-attempts`, `compose-review`, `song-pick-instruments` (broad `Bash`/`Read` — no allowed-tools change). Commands → `uv run --project "$ROOT" --frozen hallucinote …` / `… python build.py`; each links `docs/running-the-engine.md`.
- [ ] **4 — scrub PyPI/clone — DEFERRED (bundle with README, chunk 5).** The references live across the *install-narrative* docs (`quickstart.md`, `collaboration.md`, `engine-pin.md`, `dev-vs-use-coexistence.md`, the install skill, pyproject `[live]` + its comment). Scrubbing piecemeal while the tabled README still says "clone" creates incoherence; and removing the pyproject `[live]` extra needs a careful `uv.lock` re-lock. Do it as one install-narrative rewrite when the README is untabled.
- [x] **Operator-verify (you) — PASSED 2026-06-16** on a real install (worktree-as-plugin, server `0.1.0+3094116a63fa`): Stages 0/1a/1b/2a/2b all ✅. Scaffold + build + push (14 phases, 4 tracks) all ran via `uv run --project "$ROOT" --frozen …` resolving the worktree engine — **no pip install in the songs workspace**. 2b's transient Remote-Script mismatch was the expected NODE-ADDR re-vendor (orthogonal), cleared by `/ableton-mcp-install` via `server/info`'s `package_root`. **Windows verify still pending** (mac confirmed).

**Critic W2 fix (2026-06-16) — env-targeting corrected.** The first skill migration used `uv run --project "$ROOT" --frozen hallucinote …`, which uses uv's default `$ROOT/.venv` — a *different* env from the bridge's, and unwritable on a read-only plugin root (the mac verify passed only because the worktree root was writable). Fixed: `server/info` now exposes `python` (= `sys.executable`, the running server's interpreter), and **all skills run `"$PY" -m hallucinote.cli <command>` / `"$PY" build.py`** — the exact prewarmed env, guaranteed version-synced, read-only-root-safe. Proven locally: `-m hallucinote.cli --help` + `compat --help` dispatch correctly. Bonus: the engine is installed **editable**, so `-m hallucinote.cli` needs no console-script registration / re-sync — the earlier `[project.scripts]` deploy gotcha is moot (the console script remains for interactive use). `allowed-tools` for the write skills dropped to broad `Bash` (a dynamic interpreter path can't be prefix-matched). Full suite 3965 green.

**Critic residuals:** W1 (`.test-evidence.json`) re-stamps at commit. N1 (`getting-started` "separate install" line) is inside the deferred doc scrub. N2/N3 minor.

## Tests
- CLI dispatch (each subcommand routes + preserves output) — unit.
- `server/info` carries `project_root` — extend the resources test.
- Skill `allowed-tools` match the new invocation (skill-consistency).
- Hook ports: first-run + prewarm Python tests (mirror the existing bash-invoking tests, now `python`).
- Operator-verify (real install, mac + Windows): compose + push with NO clone.
