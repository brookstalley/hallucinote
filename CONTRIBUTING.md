# Contributing to Hallucinote

Thanks for wanting to help.
This guide covers the dev environment, tests, and the branch/review workflow.
If you're here to *use* Hallucinote rather than work on it, start with the [README](README.md) and [Quickstart](docs/quickstart.md).

## Development setup

**[uv](https://docs.astral.sh/uv/) is the norm here**, because it's the one with CI enforcement behind it: the repo is a uv workspace, the shipped plugin runs `uv run --frozen`, and CI gates on `uv lock --check`. uv provisions the interpreter too; Python 3.10 is the floor.
A local `pip install -e '.[dev]'` venv still works for editing — it's a personal convenience, and **a "green" claim has to come from the locked environment.**

```bash
git clone https://github.com/brookstalley/hallucinote.git
cd hallucinote
uv sync --all-packages --all-extras    # both packages + dev extras, one env
```

Run everything through `uv run` (`uv run mypy`, `uv run ruff check .`).
If you change dependencies, commit the regenerated `uv.lock` — a stale lockfile fails CI's first gate and ships stale deps to users.

The repo is two packages: `src/hallucinote/` (composition library — DB, generators, sync, capture) and `hallucinote_mcp/` (the in-repo MCP server that drives Ableton Live).
See [README → Project layout](README.md#project-layout).

## Running tests

```bash
uv run python -m pytest -n auto --dist loadgroup                  # full suite, parallel
uv run python -m pytest hallucinote_mcp/tests/unit/test_actions_device.py   # one file, while iterating
```

**The pre-PR run takes no path argument.** `testpaths` is `["tests", "hallucinote_mcp/tests", "examples"]` — three roots — so a path-scoped run silently skips the others and still reports green.
Scope to a file while you iterate; run it bare before you push.

`tests/conftest.py` auto-groups tests by directory for `--dist loadgroup`.
Tests marked `ableton` need a running Live and are **default-skip** — see `conftest.py` to opt in.

### What CI covers, and the three gaps

CI is one job: `uv lock --check`, ruff, mypy, then the full suite on **ubuntu-latest, Python 3.12 only**.
Know the three gaps so you don't mistake a green check for more than it is:

- **No Ableton.** The `ableton`-marked tests default-skip and the MCP-server tests run against fakes.
  Nothing in CI proves the bridge talks to Live — that's on you and the [operator verification](README.md#troubleshooting) step.
- **No macOS or Windows leg.** Both are supported platforms; neither is automated.
  Platform-shaped changes (install paths, process lookup) need hand-verification, ideally on both.
- **One interpreter.** `requires-python` floors at 3.10; only 3.12 runs. mypy's `python_version = 3.10` covers the floor at type-check time.

### Test discipline

**Write tests alongside the code, never after** — if you can't write the test, you don't yet understand the requirement.
Never weaken a test to make it pass; fix the code.
Run the full suite green before opening a PR.

Per-song tests live beside the song, in `<slug>/tests/`, and are discovered automatically.
Authored songs live in their own workspace repo (the framework⇄songs split), so the case you'll meet in *this* repo is the `examples/` demo workspace — `examples/punk-fate/tests/` runs in the default suite, which is why `examples` is one of the three `testpaths` roots.
Test filenames must be unique across songs (`test_<slug>_build.py`, never a bare `test_build.py`).

## MCP changes need a full refresh — all three steps

There are two live copies of the `hallucinote_mcp` code: the **server** subprocess Claude Code talks to (the editable install), and the **Remote Script** vendored into Live's User Library.
A version handshake refuses to run if their fingerprints disagree.
The fingerprint covers `wire.py`, `schema.py`, `dispatcher.py`, and the whole `actions/`, `handlers/`, and `remote_script/` trees (`hallucinote_mcp/__init__.py:_FINGERPRINT_PATHS`).

So **editing essentially any dispatch/handler/action code bumps the fingerprint and desyncs both copies.** Don't think "server-side vs Live-side" — a handler edit is *both*.
After such a change, do all three:

1. **`/ableton-mcp-install`** — re-vendor the package into Live's User Library (Live must be closed).
   Keeps the Remote Script's fingerprint matching.
2. **Fully quit and reopen Ableton Live** — it caches Control Surface modules at startup, so the refreshed Remote Script only loads on a real restart.
3. **`/mcp` → reconnect** in Claude Code — respawns the server subprocess so it loads your edited source (a running process holds the old modules in memory).
   If you ran the reinstall *through* the live bridge, this is what un-stales your own connection.

Only changes to **non-fingerprinted** files (e.g. `cli/`, `resources/`, `install_paths.py`, `client.py`) skip the handshake — but the running server still holds them in memory, so step 3 (`/mcp` reconnect) still applies.

`uv run python -m hallucinote_mcp.cli preflight` shows the install state and whether the Live-side Remote Script's fingerprint matches the server (`remote_script.candidates[*].matches_mcp_server`).
From a bare shell without the env it won't import — that's expected.

## Branch & review workflow

The repo uses **gitflow**: `develop` is the integration branch, `main` is release-only.
Both are protected — no direct commits.

1. **Branch from `develop`** with a descriptive name: `feature/...`, `fix/...`, or `refactor/...`.
2. **Build with tests**, keep `develop`-baselined, run the full suite green.
3. **Critic review** — medium-or-larger changes get an independent `/prawduct:critic` review before merge (it reads `.prawduct/.test-evidence.json`; it does not run tests itself).
   Fix blocking findings, address warnings.
4. **Open a PR targeting `develop`** (not `main`).
   PRs are created when you ask (`/prawduct:pr`); an independent reviewer runs automatically.
5. `develop → main` happens via periodic **release PRs** only.

This project is developed with [Claude Code](https://claude.ai/code) under the "prawduct" governance framework — the rules above are enforced by hooks and the Critic.
`CLAUDE.md` is the authoritative working-instructions file; read it before a substantial change.
Note that some framework files (`skills/`, `.prawduct/`, `tools/product-hook`) may carry in-flight upstream framework work — check before bundling unrelated edits to them into a feature PR.

## Code conventions

- Match the style of the surrounding code (naming, comment density, idioms).
- **Never swallow exceptions** — catch specific ones and log with context.
  A genuinely necessary broad catch is waived inline, with the reason spelled out: `except Exception as e:  # prawduct:allow prawduct/broad-except -- <why>`.
  The reason says what is being absorbed and why absorbing it there is correct; a catch whose reason cannot be written honestly is one to narrow rather than annotate.
- **Update artifacts when code changes what they describe** — stale docs are worse than none.
  If you change a contract surface (API, DB, IPC, frontend/backend), verify consumers aren't broken.
- Prefer structural fixes over patches; this codebase is expected to grow.

## Reporting issues

Open a GitHub issue with what you did, what you expected, and what happened.
For install/bridge problems, include your preflight output — from a checkout, `uv run python -m hallucinote_mcp.cli preflight`; as a plugin user, just ask Claude to **run preflight**.

**Security problems are the exception — don't open an issue.** Report them privately through GitHub Security Advisories or the email in [`SECURITY.md`](SECURITY.md), which also explains what is and isn't in scope (notably: a song's `build.py` executing is by design, so review a `build.py` before building a song you cloned from someone else).

## Code of conduct

Participation here is covered by our [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) (Contributor Covenant 2.1).
Report unacceptable behavior to the address listed there.
