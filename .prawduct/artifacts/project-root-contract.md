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

### Bounded exception — the example workspace

One workspace lives **inside** the framework repo: `examples/`, carrying its own
`hallucinote.toml` (`layout = "monorepo"`, `songs_root = "."`) and the demo song the
end-to-end tour is built from. It resolves through the normal precedence below with no
special-casing in the resolution code.

**Note the starting point, because it is not the song directory.** `find_workspace()`
(`src/hallucinote/workspace.py`) walks **up** from `CLAUDE_PROJECT_DIR`, the cwd, or an
explicit `start=` — never from the slug being resolved. `examples/hallucinote.toml` is a
*descendant* of the repo root, so the upward walk alone never sees it.

> **This was a defect, and it bit (2026-08-07).** The upward walk missed
> `examples/hallucinote.toml`, resolution fell through to the legacy `songs/<slug>`
> (which names nothing here), and *nothing refused*: `ableton_render` created the
> phantom tree and wrote ~290 MB of WAVs into `songs/angle-of-the-light/captures/`;
> `manifest.db_seq` came back `null` (no DB found, so no provenance tag);
> `ableton_analysis` then reported the song *"doesn't name a built song — run
> `build.py --reset`"*, advice that would have scaffolded a duplicate over a song
> that had been built all along. One misresolution, three symptoms, all silent.
>
> **Fixed by precedence step 4** (below) — a *bounded descent*: when the upward walk
> finds nothing, look at most `MAX_DESCEND_DEPTH` (2) levels below the start
> directory and take the marker found there if it is unambiguous. The descent is
> deliberately not a search: more than one workspace below means the choice is a
> guess, so it declines and falls through, and `explain_unresolved_song()` names the
> candidates. Two guards keep the failure from ever being silent again —
> `explain_unresolved_song()` distinguishes *wrong workspace* / *no marker anywhere*
> / *genuinely doesn't exist* and refuses to advise a rebuild when the song is built
> somewhere else, and `_refuse_render_into_phantom_song_dir()`
> (`hallucinote_mcp/server.py`) refuses a slug-derived render destination that does
> not exist rather than inventing it.
>
> Note what was *not* done: a `hallucinote.toml` at the **repo root** would also have
> resolved `examples/`, with no code change. It was rejected — it declares the
> framework repo itself a workspace (a contract-level change to the split, for a
> demo the *Bounded exception* deliberately keeps scoped) and it fixes exactly one
> repo, leaving every user whose editor is rooted above their songs repo with the
> same silent mis-write.

The descent is only ever a fallback: an explicit `start=`/`root=`, or a cwd inside
`examples/`, still resolves the marker directly and outranks it — which is how a CI
build of the example should invoke it.

It is an exception to the split above, granted for two things a separate demo repo
cannot give:

- **No second destination.** The demo sits in the repo a visitor has already landed
  on. The README, the tour, and the song they document are one clone, or none — a
  reader following the walkthrough is never sent somewhere else to find the song it
  describes.
- **CI can build it**, making the documented example a real integration test rather
  than a claim that rots.

**The exception is bounded to that purpose.** `examples/` is documentation and test
fixture; it is *not* the pattern users follow. The split still holds for authored
work: a user's songs live in their own workspace repo, created by
`hallucinote init-workspace`, depending on the installed plugin. Nothing here
licenses adding further song directories to the framework repo, and the quickstart
and getting-started paths continue to send users to a workspace of their own.

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

**Creating a marker (the author side).** `hallucinote init-workspace [DIR]` writes
this file (default `layout = "monorepo"`, `songs_root = "songs"`), an idempotent
`.gitignore` managed block covering the regenerable toolchain artifacts (DB,
`captures/`, `analysis/`, push-state caches — the fresh-workspace half of the filed
"gitignore misses tool artifacts" bug), and `git init`s the directory; it refuses
inside an existing workspace unless `--force`, and a `--check` dry-run reports
workspace status without writing. The onboarding skills
(`/getting-started`, `/song-new`) run `--check` and offer to create a marker when
they detect none — so a missing marker is surfaced, not silently degraded to the
legacy `./songs/<slug>` fallback (precedence step 4). Author lives in
`hallucinote/tools/init_workspace.py`; the reader is `hallucinote/workspace.py`.

## Resolution contract

`songs_root` (the value the MCP server, CLI tools, and skills need to map `slug → DB`) is
resolved with this precedence — first hit wins:

1. **Explicit argument** — `resolve_db_path(slug, root=...)`, `--db PATH`, `--song-root`.
   `build.py` already does this (`root=Path(__file__).parent.parent`).
2. **Env var** — `HALLUCINOTE_SONGS_ROOT` (the plugin/launcher sets this; a plugin MCP
   server inherits `CLAUDE_PROJECT_DIR`, from which the launcher derives the songs root).
3. **Marker discovery (up)** — walk up for `hallucinote.toml`, read `[workspace]`, resolve
   `songs_root` relative to the marker's directory.
4. **Marker discovery (down)** — when the upward walk found none, scan at most
   `MAX_DESCEND_DEPTH` (2) levels *below* the start directory, skipping hidden /
   VCS / cache / build / dependency dirs, never descending into a directory that is
   itself a workspace, and bounded by a directory budget. Exactly one workspace found
   → use it. Zero or more than one → decline and fall through, because a guess here is
   how the silent-wrong-answer bug happens. `find_workspace()` does **not** descend
   unless asked (`descend=True`): its default answers "which workspace am I *inside*?",
   which is the question `init-workspace`'s refuse-inside-a-workspace guard needs.
5. **Legacy default** — `"songs"` relative to cwd. *Transition-only* back-compat that keeps
   the live monorepo working while 1–4 land; remove once the monorepo carries a marker.

Any caller enumerating songs (rather than resolving one) must mirror this precedence
including the descent — `captures_cli.discover_song_slugs()` passes `descend=True` for
exactly that reason. A per-slug resolver and an enumerator that disagree about where
songs live is the shape of the next silent bug.

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
4. **`push_cli` + `pull_cli` resolution.** Both engine CLIs now resolve the song dir via the
   contract. `pull_cli._resolve_db_path` was pre-W12-A — it hardcoded
   `Path("songs")/<slug>/<slug>.db` with no per-branch naming and no contract, so
   `pull_cli --song <slug>` mislocated a song in its own repo; it now mirrors `push_cli` +
   `build.py` (per-branch via `resolve_db_path`, legacy `<slug>.db` fallback in the same
   resolved dir) so push and pull agree on the same DB. `push_cli`'s legacy fallback was
   rerouted off its `Path("songs")` literal too. (Surfaced by the PR reviewer.)
5. **Engine `[live]` extra** — `pip install hallucinote[live]` declares the lazy
   engine→`hallucinote-mcp` push coupling for a standalone song repo.

## Still deferred

- **Literal `songs/<slug>/…` paths in skill markdown.** The tool *invocations* in skills are
  now installed-module form (`-m hallucinote.tools.*`) — done. What remains is the literal
  `songs/<slug>/…` paths the `SKILL.md` bodies still spell out (e.g. `python3
  songs/<slug>/build.py`, `--db songs/<slug>/…`) in compose-part, ableton-push/pull, song-new,
  song-context, decisions, song-snapshot. These work in a nested songs workspace (cwd-relative,
  the chosen layout) but assume that shape; a future pass could resolve them via the contract.
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
