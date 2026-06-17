# Song-workspace gitignore misses artifacts the framework's own tools generate

**Severity:** L (hygiene / onboarding) — no data loss, but every workspace
re-discovers the same gaps and risks committing regenerable noise.
**Refs:** songs repo root `.gitignore`; skills `song-new`, `song-snapshot`,
`ableton-push`, `ableton-render`/`mix-review` (the generators of the artifacts below).

## What happened

Committing the two songs now in the workspace (`missing`, `swell`), the root
`.gitignore` already covered DBs, `captures/`, `*.als`, pyc, and (from 48b3ad8)
`.last-push-state.json` / `.last-push-errors.json`. But three classes of file that
**hallucinote tools write** were not ignored, so they showed up as committable:

- `songs/*/.last-notes-push.json` — a notes-push state cache, sibling to the
  already-ignored `.last-push-state.json` (the gitignore rule just missed this name).
- `**/analysis/*.json` — MixReport outputs from the render/analyze path. The gitignore
  comment beside `**/captures/` already *calls* analysis "(untracked) analysis
  artifacts — regenerable from a Live capture pass," but only `captures/` was actually
  listed. swell had 13 of these staged.
- `**/captured_session.json.bak` — the snapshot backup written beside
  `captured_session.json`.

All three are machine-specific / regenerable; none belong in git. Closed locally by
extending the workspace `.gitignore` (this commit), but the fix is per-workspace and
will be re-discovered by the next person who scaffolds songs.

## Why it's framework-shaped

The framework's own tools produce these files: the push path writes
`.last-notes-push.json`, render/analyze writes `analysis/`, and `song-snapshot` writes
`captured_session.json.bak`. A workspace scaffolded via `song-new` (or onboarded fresh)
has no shipped guidance that these are regenerable and should be ignored — so the
default state is "tool output is committable," which is the wrong default for
regenerable artifacts.

## Suggested directions

1. Ship a song-workspace `.gitignore` stanza (or have `song-new` author/append one) that
   covers everything the toolchain regenerates: `*.db*`, `**/captures/`, `**/analysis/`,
   `songs/*/.last-*-push.json`, `songs/*/.last-push-errors.json`,
   `**/captured_session.json.bak`, `*.als`/`*.als.bak`, pyc.
2. Or, cheaper: have each generating tool drop a local `.gitignore` in the directory it
   writes to (e.g. `analysis/.gitignore` = `*`), the way `captures/` could self-ignore.
3. Minimum: document the regenerable-artifact set in the workspace onboarding notes so
   the gitignore isn't reverse-engineered from `git status` each time.

## Partial resolution (2026-06-17, WS-BOOTSTRAP)

Direction #1 is now **done for freshly-bootstrapped workspaces**: `hallucinote
init-workspace` (the new songs-workspace bootstrap; `src/hallucinote/tools/init_workspace.py`)
writes an idempotent `.gitignore` managed block covering `*.db*`, `**/captures/`,
`**/analysis/`, `**/.last-*-push.json`, `**/captured_session.json.bak`, `*.als*`, pyc.
`/getting-started` + `/song-new` offer it when they detect no workspace, so a new
workspace ships the stanza from the start.

**Still open:** workspaces created *before* this (or by `git init` outside the skill)
don't retroactively get the block — direction #2 (each generating tool drops a local
`.gitignore` in the dir it writes to, e.g. `analysis/.gitignore = *`) would cover those
and is the durable per-tool fix. Re-scope this report to that remaining half.
