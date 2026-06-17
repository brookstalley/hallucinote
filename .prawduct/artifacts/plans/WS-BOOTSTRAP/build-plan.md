# Build Plan — Songs-workspace bootstrap (WS-BOOTSTRAP)

Implements a concrete slice of the **technical entry gate** that
`onboarding-and-teaching-model.md` deliberately deferred ("Residual, deferred by
choice: the technical entry gate (clone / pip / MCP / Ableton click) still filters
… a distribution problem we are explicitly choosing not to fully solve now").
This plan does not touch the behavioral on-ramp (that shipped, C0–C4); it fixes a
code-level hole in *getting set up to run `/song-new` at all*.

## Problem (observable)

The README and quickstart require the user to run Claude Code in a **songs
workspace** — a repo with a `hallucinote.toml` marker — but **nothing creates that
marker.** There is no skill and no CLI subcommand for it; the user must hand-author
a TOML whose `[workspace]` schema is not shown in the README. Worse, if they skip
it, `hallucinote.workspace.resolve_song_dir` *silently* falls back to
`./songs/<slug>` relative to cwd (`workspace.py:151-154`) — so the first `/song-new`
scatters a song into whatever directory Claude happened to launch from, untracked
and unmarked, with no warning. The documented prerequisite has zero tooling and a
silent-degrade failure mode, hit by every new user exactly once, at their first
creative action.

## Requirements Confidence: **High**

The workspace marker contract is already implemented + validated
(`project-root-contract.md`; `hallucinote/workspace.py`). This plan only adds the
*author* side of a contract that already has a fully-tested *reader*. The marker
shape, layouts, and precedence are settled; the one design choice (default layout)
is forced by an existing limitation (see Decisions).

## Scope

**In:** a tested `init_workspace` module + `hallucinote init-workspace` CLI
subcommand that writes a `hallucinote.toml` marker (default `layout="monorepo"`,
`songs_root="songs"`), an idempotent `.gitignore` managed block for regenerable
toolchain artifacts, and optionally `git init`s the dir; a read-only `--check`
dry-run for skill detection; no-marker detection wired into `/getting-started` and
`/song-new`; README + quickstart show the marker and name the command;
project-root-contract "Still deferred" note updated.

**Also closes (fresh-workspace half):** the filed bug
`incoming-bugs/…song-workspace-gitignore-misses-tool-generated-artifacts.md`
suggested-fix #1 — ship/author a `.gitignore` stanza covering `*.db*`,
`**/captures/`, `**/analysis/`, `**/.last-*-push.json`, `**/captured_session.json.bak`,
`*.als*`, pyc. `init-workspace` now authors it at workspace-creation time (the
already-existing-workspace half — tools dropping artifacts into repos created before
this — remains open for the per-tool `.gitignore` direction #2).

**Out:** flat `layout="song"` end-to-end (blocked: `build.py` hardcodes
`root=Path(__file__).parent.parent` — deferred in the contract); cloning existing
songs repos; changing resolution precedence; adding a marker to the framework
monorepo itself; the MCP-7F2K fingerprint work (separate design step).

## Decisions

- **Default `layout="monorepo"`, `songs_root="songs"`.** This is the only
  build-proven layout — the spike (project-root-contract "What the spike proved")
  and the integration tests exercise monorepo-with-one-song; flat `song` layout's
  `build.py` mislocates its DB (contract "Still deferred"). Defaulting to the
  unproven layout would hand new users a broken build. `--layout song --slug X` is
  accepted but warns it is experimental.
- **`git init` on by default, `--no-git` to opt out, skipped if already a repo.**
  The README frames a workspace as a git repo ("git init-ing a folder"); a song's
  whole value proposition is "a song is a git repo you commit and fork"
  (VISION bet #2). Initializing git is the clean-deployment default, not gold-plating.
- **Refuse if already inside a workspace** (an ancestor marker exists) unless
  `--force` — prevents accidental nested workspaces, which would shadow resolution.

## Status

- [x] C1 — `init_workspace` module + CLI subcommand + unit tests
- [x] C2 — Wire no-marker detection into `/getting-started` + `/song-new`; docs (README, quickstart, contract)

**Context:** 2026-06-17. **C1 shipped:** `hallucinote/tools/init_workspace.py`
(`init_workspace()` atomic write + `--check` dry-run + `git init`) registered in
`cli.py`; 24 unit tests in `tests/unit/tools/test_init_workspace.py` (author↔reader
round-trip, refuse-in-existing-workspace, `--check` read-only, git paths, dispatcher
route) — all green; CLI smoke-tested end-to-end. **C2 shipped:** `/getting-started`
step 3 + `/song-new` Phase 2 now `--check` and offer `init-workspace` when no marker;
README "Your first song" + quickstart §1 show the marker + command;
`project-root-contract.md` documents the author side. Branch
`feature/songs-workspace-bootstrap` off `develop`. Next: full suite + `/prawduct:critic`.

## C1 — init_workspace module + CLI

**Success:** `hallucinote init-workspace [DIR]` writes a valid `hallucinote.toml`
that `find_workspace` then resolves; refuses (no write) inside an existing
workspace without `--force`; `--check` reports workspace status without writing;
JSON result on stdout like the other tool CLIs.
**Done when:**
- [ ] `hallucinote/tools/init_workspace.py` — `init_workspace()` (pure, testable,
  atomic write) + `main(argv)`; registered in `cli.py` `_SUBCOMMANDS`/`_SUMMARY`.
- [ ] Unit tests (mirror layout, `tests/unit/tools/test_init_workspace.py`):
  marker written + round-trips through `find_workspace`; refuse-in-existing-workspace;
  `--check` writes nothing; `--no-git`; flat-layout-requires-slug; the dispatcher
  routes `init-workspace`.
- [ ] Full suite green; evidence recorded. `/prawduct:critic`.

## C2 — Skill detection + docs

**Success:** `/getting-started` and `/song-new`, run outside a workspace, detect
the missing marker and *offer* to create one instead of silently scattering a song;
README + quickstart show the two-line marker and name the command.
**Done when:**
- [ ] `/getting-started` step 3: if no workspace on the path, offer
  `init-workspace` before the new/existing-song fork.
- [ ] `/song-new`: before scaffolding, `--check`; if no workspace, surface it and
  offer to create one (high-stakes: where the song lands).
- [ ] README "Your first song" + quickstart §1 show the marker + the command.
- [ ] `project-root-contract.md` "Still deferred" notes the author side now exists.
