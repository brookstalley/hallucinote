# Contributing to Hallucinote

Thanks for wanting to help. This guide covers the dev environment, tests, and
the branch/review workflow. If you're here to *use* Hallucinote rather than work
on it, start with the [README](README.md) and [Quickstart](docs/quickstart.md).

## Development setup

Requires **Python 3.10+**. Clone and install both packages editable, with the
`[dev]` extras (pytest, pytest-xdist, hypothesis):

```bash
git clone https://github.com/brookstalley/hallucinote.git
cd hallucinote
python -m venv .venv && source .venv/bin/activate     # Windows: py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e '.[dev]' -e './hallucinote_mcp[dev]'
```

The repo is two packages: `src/hallucinote/` (composition library — DB,
generators, sync, capture) and `hallucinote_mcp/` (the in-repo MCP server that
drives Ableton Live). See [README → Project layout](README.md#project-layout).

## Running tests

```bash
pytest -n auto --dist loadgroup        # full suite, parallel
pytest hallucinote_mcp/tests/unit/test_actions_device.py   # one file
```

`tests/conftest.py` auto-groups tests by directory for `--dist loadgroup`.
**Write tests alongside the code, never after** — if you can't write the test,
you don't yet understand the requirement. Never weaken a test to make it pass;
fix the code. Run the full suite green before opening a PR.

Per-song tests live under `songs/<slug>/tests/` and are discovered
automatically. Test filenames must be unique across songs
(`test_<slug>_build.py`, not bare `test_build.py`).

## MCP changes need a full refresh — all three steps

There are two live copies of the `hallucinote_mcp` code: the **server**
subprocess Claude Code talks to (the editable install), and the **Remote
Script** vendored into Live's User Library. A version handshake refuses to run
if their fingerprints disagree. The fingerprint covers `wire.py`, `schema.py`,
`dispatcher.py`, and the whole `actions/`, `handlers/`, and `remote_script/`
trees (`hallucinote_mcp/__init__.py:_FINGERPRINT_PATHS`).

So **editing essentially any dispatch/handler/action code bumps the fingerprint
and desyncs both copies.** Don't think "server-side vs Live-side" — a handler
edit is *both*. After such a change, do all three:

1. **`/ableton-mcp-install`** — re-vendor the package into Live's User Library
   (Live must be closed). Keeps the Remote Script's fingerprint matching.
2. **Fully quit and reopen Ableton Live** — it caches Control Surface modules at
   startup, so the refreshed Remote Script only loads on a real restart.
3. **`/mcp` → reconnect** in Claude Code — respawns the server subprocess so it
   loads your edited source (a running process holds the old modules in memory).
   If you ran the reinstall *through* the live bridge, this is what un-stales
   your own connection.

Only changes to **non-fingerprinted** files (e.g. `cli/`, `resources/`,
`install_paths.py`, `client.py`) skip the handshake — but the running server
still holds them in memory, so step 3 (`/mcp` reconnect) still applies.

`python -m hallucinote_mcp.cli preflight` shows the install state and whether
the Live-side Remote Script's fingerprint matches the server
(`remote_script.candidates[*].matches_mcp_server`).

## Branch & review workflow

The repo uses **gitflow**: `develop` is the integration branch, `main` is
release-only. Both are protected — no direct commits.

1. **Branch from `develop`** with a descriptive name: `feature/...`, `fix/...`,
   or `refactor/...`.
2. **Build with tests**, keep `develop`-baselined, run the full suite green.
3. **Critic review** — medium-or-larger changes get an independent `/critic`
   review before merge (it reads `.prawduct/.test-evidence.json`; it does not
   run tests itself). Fix blocking findings, address warnings.
4. **Open a PR targeting `develop`** (not `main`). PRs are created when you ask
   (`/pr`); an independent reviewer runs automatically.
5. `develop → main` happens via periodic **release PRs** only.

This project is developed with [Claude Code](https://claude.ai/code) under the
"prawduct" governance framework — the rules above are enforced by hooks and the
Critic. `CLAUDE.md` is the authoritative working-instructions file; read it
before a substantial change. Note that some framework files (`skills/`,
`.prawduct/`, `tools/product-hook`) may carry in-flight upstream framework work —
check before bundling unrelated edits to them into a feature PR.

## Code conventions

- Match the style of the surrounding code (naming, comment density, idioms).
- **Never swallow exceptions** — catch specific ones and log with context. A
  genuinely necessary broad catch is marked `# prawduct:ok-broad-except` with a
  reason.
- **Update artifacts when code changes what they describe** — stale docs are
  worse than none. If you change a contract surface (API, DB, IPC,
  frontend/backend), verify consumers aren't broken.
- Prefer structural fixes over patches; this codebase is expected to grow.

## Reporting issues

Open a GitHub issue with what you did, what you expected, and what happened.
For install/bridge problems, include the output of
`python -m hallucinote_mcp.cli preflight`.

**Security problems are the exception — don't open an issue.** Report them
privately through GitHub Security Advisories or the email in
[`SECURITY.md`](SECURITY.md), which also explains what is and isn't in scope
(notably: a song's `build.py` executing is by design, so review a `build.py`
before building a song you cloned from someone else).

## Code of conduct

Participation here is covered by our [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)
(Contributor Covenant 2.1). Report unacceptable behavior to the address listed
there.
