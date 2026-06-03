# Project-Root Contract

> **Status:** implemented + validated. The engine/MCP resolution for the standalone-song
> path landed on `feature/project-root-contract`: the `hallucinote.workspace` marker module,
> env/marker resolution in `resolve_db_path` (which auto-fixes every MCP-server callsite),
> the two `compat.py` sites, and the engine `[live]` extra. Remaining deferred work
> (path-coupled skills, the flat-`song` `build.py` change) is listed under "Still deferred".

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

## Implemented this phase (`feature/project-root-contract`)

1. **`hallucinote/workspace.py`** — the marker module: `find_workspace()` (walk up from
   `CLAUDE_PROJECT_DIR`/cwd for `hallucinote.toml`), the `Workspace` dataclass (layout-aware
   `song_dir()`), and `resolve_song_dir()` implementing precedence 2→4.
2. **`resolve_db_path` resolves the song dir via the contract when `root` is not passed.**
   This **auto-fixes every MCP-server callsite** — `provenance.py:49` and
   `handlers/analysis.py:87,154` already call `resolve_db_path(slug)` with no `root`, so they
   inherit env/marker resolution with zero edits. The branch is now probed in the *resolved
   song dir* (the song's own repo), not the server's cwd. Explicit-`root` callers (`build.py`)
   are byte-identical. Proven from a foreign cwd via `CLAUDE_PROJECT_DIR` (no Ableton needed).
3. **The two `compat.py` sites** (`_resolve_db` legacy fallback; `_cmd_write_requirements`
   output path) now route through `resolve_db_path(slug, branch=None)` / `resolve_song_dir`.
4. **Engine `[live]` extra** — `pip install hallucinote[live]` declares the lazy
   engine→`hallucinote-mcp` push coupling for a standalone song repo.

## Still deferred

- **Path-coupled skills** assume cwd = monorepo: `tools/…` invocations + `songs/<slug>/…`
  paths in compose-part, ableton-push/pull, song-new, song-context, decisions,
  compose-review, song-snapshot, clip-humanize. They work in the monorepo today; they need
  workspace-relative wiring before songs move out. (The resolver they'd build on now exists.)
- **`song` (flat) layout end-to-end** — the resolver already supports `layout = "song"`
  (DB at the repo root), but `build.py` still hardcodes `root=Path(__file__).parent.parent`,
  so a flat repo's `build.py` would mislocate its DB. `monorepo`-with-one-song works today
  and is what the spike + integration test exercised; flat needs a `build.py`/scaffold change.
- **Live end-to-end** — pushing a song from its own repo into an open Ableton set. The
  resolution layer is proven; the full DAW round-trip is a manual verification (needs Live
  running; state-modifying).

## Decisions

- **Marker file = `hallucinote.toml`**: discoverable, greppable, works whether or not the
  song repo has a `pyproject.toml`. *Alt rejected:* env-var-only — invisible, no per-repo
  source of truth. *Alt deferred:* a `[tool.hallucinote]` table in `pyproject.toml` — would
  force a TOML parse of every ancestor `pyproject.toml` on the hot resolve path; the
  dedicated marker keeps discovery to `is_file()` stats until a marker is found.
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
