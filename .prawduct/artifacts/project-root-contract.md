# Project-Root Contract

> **Status:** spike-validated (build path). Engine/MCP changes for the standalone-song
> path are scoped below but **not yet implemented**. Branch: `spike/project-root-contract`.

## Why this exists

The framework⇄songs split (engine as one distributable repo; songs as their own repos)
is the [VISION.md](../../docs/VISION.md) bet #2 — *"a song is a git repo … two
collaborators push and pull edits like code."* This contract is the boundary that lets a
song live **outside** the engine monorepo and still find (a) the engine, (b) its own song
directory, (c) its SQLite DB — without assuming the monorepo layout. It is the keystone:
nothing else in the split is safe until this is fixed.

Target topology (see the session discussion): **two repo roles** — one shared *framework*
repo (engine + `hallucinote_mcp` + skills/plugin, versioned together, marketplace-sourced
like `prawduct`), and *song* workspaces (one shared repo or one-per-collaborator) that
depend on the installed engine. Contributors clone the framework and editable-install it;
end users `uvx hallucinote-mcp` + install the plugin.

## The workspace marker

A **workspace** is the directory tree a song (or many) lives in. It is identified by a
`hallucinote.toml` marker at its root, discovered by walking up from `CLAUDE_PROJECT_DIR`
(or cwd), exactly like `.git` / `ruff.toml`. (`[tool.hallucinote]` in a `pyproject.toml`
is also honored if present, for song repos that already declare their engine dependency.)

```toml
# hallucinote.toml — at the workspace root
[workspace]
# "monorepo": many songs under songs_root/<slug>/   (the framework repo; multi-song repos)
# "song":     this repo IS one song; the repo root is the song dir
layout     = "monorepo"
songs_root = "songs"        # monorepo only; relative to the marker's directory
# slug     = "falling-walking"   # required for layout = "song"
```

## Resolution contract

`songs_root` (the value the MCP server, CLI tools, and skills need to map `slug → DB`) is
resolved with this precedence — first hit wins:

1. **Explicit argument** — `resolve_db_path(slug, root=...)`, `--db PATH`, `--song-root`.
   `build.py` already does this (`root=Path(__file__).parent.parent`).
2. **Env var** — `HALLUCINOTE_SONGS_ROOT` (the plugin/launcher sets this; a plugin MCP
   server inherits `CLAUDE_PROJECT_DIR`, from which the launcher derives the songs root).
3. **Marker discovery** — walk up for `hallucinote.toml`, read `[workspace]`, resolve
   `songs_root` relative to the marker's directory.
4. **Legacy default** — `"songs"` relative to cwd. *Transition-only* back-compat that keeps
   the live monorepo working while 1–3 land; remove once the monorepo carries a marker.

Per-layout `slug → DB` mapping:

| layout | song dir | DB path |
|---|---|---|
| `monorepo` | `<songs_root>/<slug>/` | `<songs_root>/<slug>/<slug>-<branch>.db` |
| `song` | workspace root | `<root>/<slug>-<branch>.db` |

Per-branch DB naming (`-<branch>`, `/`→`--`, no-branch fallback to `<slug>.db`) is
unchanged — it already probes the *song repo's* own branch, not the framework's.

## What the spike proved (2026-06-03)

One song (`falling-walking`) copied to `/tmp/hln-spike/songs/falling-walking/` (a fresh
`git init` repo, **outside** the monorepo), engine resolved via editable install
(= contributor mode), built and tested with the workspace root as cwd:

- **Engine resolution** — clean `import hallucinote…`, no `sys.path` hacks. ✅
- **build.py portability** — DB + `captured_session.json` resolved from `__file__`; ran
  unchanged. ✅
- **DB lands in the song repo** — `falling-walking-main.db` (30 tables; 1418 notes / 32
  clips / 13 tracks / 307 events), branch `main` correctly probed from the **scratch**
  repo (not the monorepo's branch). ✅
- **Tests travel with the song** — `songs/falling-walking/tests/` → 5 passed, with **no**
  monorepo `pyproject.toml`/`conftest.py` present. ✅
- **No monorepo leakage** — monorepo `git status` clean after the build. ✅

**Conclusion:** the *least-friction* layout — a song repo that keeps the `songs/<slug>/`
nesting (`layout = "monorepo"` with one song) — needs **zero engine changes for the build
path.** The split is viable.

## What remains (scoped, not built)

Findings from the path-coupling sweep + packaging/plugin research:

1. **MCP server DB resolution (the real gap).** `hallucinote_mcp/.../provenance.py:48`
   `_resolve_song_db_path(slug)` calls `resolve_db_path(slug)` with **no `root=`**, so it
   defaults to `"songs"` relative to the *server's cwd* → assumes cwd = monorepo. Fix:
   resolve `root` via the precedence above (env/marker), not cwd. This is the one change
   that makes the long-running server location-independent. Untested by the spike (needs a
   live Claude + Ableton session).
2. **Two unparameterized `Path("songs")` sites** — `src/hallucinote/sync/compat.py:726`
   (legacy DB fallback) and `:887` (`REQUIREMENTS.md` write). Thread the same override
   `pull_cli` (`--db`) and `resolve_db_path` (`root=`) already accept.
3. **Path-coupled skills** assume cwd = monorepo: `tools/…` invocations + `songs/<slug>/…`
   paths in compose-part, ableton-push/pull, song-new, song-context, decisions,
   compose-review, song-snapshot, clip-humanize. These become workspace-relative once the
   resolver lands.
4. **`song` (flat) layout** — requires `resolve_db_path` to support no-slug-nesting and
   `build.py` to stop using `.parent.parent`. Deferred; `monorepo`-with-one-song works today.
5. **Engine→server coupling is undeclared.** The engine lazily imports
   `hallucinote_mcp.client` to push to Live (`sync/push_cli.py:93-94`), but never declares
   it. Add to the **engine** `pyproject.toml`:
   `[project.optional-dependencies] live = ["hallucinote-mcp>=0.9"]` so a song repo that
   pushes to Live can `pip install hallucinote[live]` instead of hitting an undeclared
   `ImportError`. (Today it only resolves because both packages coexist in the dev venv.)

## Decisions

- **Marker file = `hallucinote.toml`** (not a `pyproject` table only): discoverable,
  greppable, works whether or not the song repo has a `pyproject.toml`. Pyproject
  `[tool.hallucinote]` honored as a fallback. *Alt rejected:* env-var-only — invisible,
  no per-repo source of truth.
- **Keep the two-distribution split** (`hallucinote` engine + `hallucinote-mcp` server) —
  it already exists and keeps `uvx hallucinote-mcp` numpy-free. *Alt rejected:* one dist +
  extra — would force numpy into the lightweight server resolve.
- **Plugin MCP definition stays the single `{"command":"hallucinote-mcp","args":["serve"]}`** —
  resolves to the venv console script for contributors (`--plugin-dir` + editable install)
  and to `uvx` for end users via standard packaging. No conditional interpolation needed.
  Marketplace sources the framework repo at `source: "./"`, mirroring `prawduct`.
- **Remote Script packaging unchanged** — it *is* the `hallucinote_mcp` package, copied
  from the installed package root (`install_paths.py`); keep `Path(__file__).parent`
  resolution (the installer needs a real on-disk dir to rsync; `importlib.resources`
  buys nothing here). The `.amxd` is already shipped via `[tool.setuptools.package-data]`.
