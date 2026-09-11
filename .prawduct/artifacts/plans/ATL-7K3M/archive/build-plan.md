---
lifecycle: completed
archived: 2026-09-08
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# ATL-7K3M — Build Plan: Per-song attempt ledger

**Branch:** `feat/attempt-ledger` (off `develop`). **Base for Critic/PR:** `develop`
(`feedback_pr_gate_base_is_develop`).
**Requirements:** `.prawduct/artifacts/song-attempt-ledger.md` (discovery, 2026-06-14).
**Critic mode:** cumulative at PR time (`feedback_critic_cadence_for_small_chunks`) — the
two chunks ship as one PR; commit both, then `/prawduct:critic cumulative` (base `develop`)
once, which is the `/prawduct:pr create` gate. Chunk 2 carries `Type: cumulative-final`.

## Requirements Confidence: **High**
Problem, success, and scope are each one sentence (requirements doc §2). The schema reuses
an existing, well-understood projection (`markdown_refs`). Firsthand-scoped against the
real code (schema.sql, connection.py migration machinery, markdown_refs.py, queries.py,
song_context.py, scaffold templates) during discovery + planning.

## Open assumptions / unknowns
- `[ASSUMPTION: write trigger = agent records an attempt the moment it resolves (revert/
  replace) + at the /compose-review and /mix-review checkpoints, propose-and-react | MED
  impact | user can correct]` — wired in Chunk 2's review-skill edits; reversible (it's
  skill prose, not schema).

## Lock-in note (persisted format — planning.md §"A persisted format is always a lock-in")
Chunk 1 introduces the `kind: attempt` row shape (a versioned, queried format every future
consumer depends on). The consumer queries it must answer were elicited in requirements §6
and drive the field set:
- *"what have we already tried on `<part>`?"* → `kind` + `scope`/`track` (existing) filters.
- *"what FAILED / was reverted?"* → `outcome` (worked|partial|failed) + `resolution`
  (kept|reverted|superseded), first-class + filterable.
- *"what did we do instead?"* → `related` (existing) links the chain forward.
- *"when / in which pass?"* → `frontmatter_date` (existing) + the prose body's free version label.
No field is added that no elicited query needs; no elicited query lacks a field.

## Surface enumeration (project-wide concept — planning.md §"Enumerate the surfaces")
`kind: attempt` is a new domain concept. Chunk 1 = its code surface; Chunk 2 = its adoption
+ discoverability surface (all prose):
1. `skills/song-attempts/SKILL.md` (new) — the pull retrieval skill.
2. `skills/compose-review/SKILL.md` — capture wiring (propose attempts after a compose pass).
3. `skills/mix-review/SKILL.md` — capture wiring (propose attempts after an analysis pass).
4. `skills/song-workflow/SKILL.md` — add the ledger to the lifecycle map.
5. `docs/song-workflow.md` — same, in the long-form spine.
6. `docs/song-authoring-conventions.md` — the `attempt` schema + worked example + when to write.
7. `CLAUDE.md` — one line tying the ledger into the song-making norms.
8. `skills/song-new/SKILL.md` — note that `attempts/` is now scaffolded.
Doc-only (no methodology/template token-budget tests in this repo). The new skill must also
be reachable; verify it appears in the plugin skill list after the dir is added.

---

### Chunk 1: `kind: attempt` schema + parse → validate → index → query → render (code)
**Type:** code. Thin vertical slice through every code layer (schema → migration → parser →
projection → query → CLI render → scaffold), proving the format round-trips end to end.

- **Done when:**
  1. **schema.sql** (`markdown_refs`): `'attempt'` added to the `kind` CHECK; two new
     columns `outcome TEXT CHECK (outcome IS NULL OR outcome IN ('worked','partial','failed'))`
     and `resolution TEXT CHECK (resolution IS NULL OR resolution IN ('kept','reverted','superseded'))`.
  2. **connection.py** `_rebuild_disposable_tables`: drop `markdown_refs` + `markdown_refs_fts`
     when stale (table exists but lacks the `outcome` column), so the new CHECK + columns take
     effect on existing song DBs; reindex (recall-on-read) rebuilds rows from disk — safe because
     the projection is re-derivable, never authored content. Docstring updated to name markdown_refs.
     *No `_ADDED_COLUMNS` entry* (drop+recreate via schema.sql covers fresh and migrated DBs; the
     schema canary stays green because nothing is ALTERed).
  3. **markdown_refs.py**: `KINDS` += `'attempt'`; `_ALLOWED_KEYS` += `outcome`, `resolution`;
     `Frontmatter` gains `outcome`/`resolution` (str|None); `_build_frontmatter` validates —
     `kind == 'attempt'` REQUIRES both with enum membership; `kind != 'attempt'` FORBIDS both
     (clear ValueError, typo/misuse caught at index time); `_serialize_markdown` field order
     extended; `_upsert_markdown_ref` writes both columns (+ ON CONFLICT update); new
     `_ATTEMPTS_GLOB = "attempts/*.md"` added to `discover_song_corpus` + `discover_corpus`.
  4. **queries.py** `find_markdown_refs`: optional `outcome: str | None = None` filter
     (`m.outcome = ?`); the new columns flow via the existing `SELECT m.*`.
  5. **song_context.py**: `'attempt'` added to `--kind` choices; new `--outcome` arg; `_format_row`
     renders `outcome`/`resolution` in the meta line when present.
  6. **scaffold**: new `src/hallucinote/tools/templates/song/attempts/.gitkeep` so `song-new`
     creates `attempts/` (auto-picked-up by the template walk; mirrors decisions/annotations —
     `.gitkeep` NOT `.md`, so reindex's frontmatter parse never trips on the seed).
  7. **Tests** (`tests/unit/markdown_refs`, `tests/unit/db`, `tests/unit/tools`): parse+validate
     an attempt (outcome/resolution accepted); reject bad-enum outcome/resolution; reject attempt
     missing either; reject outcome/resolution on a non-attempt kind; serialize round-trip incl.
     the two fields; `write_markdown_ref` round-trips an attempt to disk + indexes it;
     `discover_song_corpus` globs `attempts/*.md`; a *stale* markdown_refs (old shape) is rebuilt
     and an `attempt` row indexes without CHECK violation; `find_markdown_refs(kind='attempt')` +
     `outcome=` filter return correctly; the schema canary stays green; song_context `--kind
     attempt`/`--outcome` render.
  8. Full suite green; chunk committed.

- **Verification:** beyond unit tests, drive the user path on a real song DB
  (`songs/missing/missing.db`): write an `attempts/*.md` file by hand, run
  `python -m hallucinote.tools.song_context --db … --kind attempt`, confirm the chain renders.

### Chunk 2: adoption + discoverability — skill, capture wiring, spine (doc-only)
**Type:** cumulative-final. **Critic mode:** the cumulative pass (base `develop`) is this
chunk's review. All edits are prose/markdown (skills + docs + CLAUDE.md); no executable code.

- **Done when** (the 8 surfaces above):
  1. new `skills/song-attempts/SKILL.md` — thin pull skill over `song_context --kind attempt`
     (frontmatter mirrors `skills/song-context/SKILL.md`: `user-invocable`, `context: fork`,
     `allowed-tools: Bash, Read`); headline use = "what have we tried on `<target>`, how did it
     go?"; framed read-before-you-retry (the `--defensive` stance), never a verdict.
  2. `skills/compose-review/SKILL.md` + `skills/mix-review/SKILL.md` — a step: after the pass,
     propose any resolved attempt worth recording (the bagpipe-revert shape) via
     `write_markdown_ref(kind='attempt', …)`, propose-and-react; distinct from the intent
     learn-back annotation.
  3. `skills/song-workflow/SKILL.md` + `docs/song-workflow.md` — the ledger named in the
     lifecycle map (queried before re-touching a part; written when an attempt resolves).
  4. `docs/song-authoring-conventions.md` — the `attempt` schema (fields, enums, the chain via
     `related`) + the two-entry bagpipe worked example + "musical-craft only / not intent /
     not a tool gripe" boundary.
  5. `CLAUDE.md` — one line wiring the ledger into the song norms (query before re-trying;
     record dead ends).
  6. `skills/song-new/SKILL.md` — note `attempts/` is scaffolded alongside decisions/annotations.
  7. The new skill resolves in the plugin skill list (`/song-attempts`).
- **Then:** repoint `active_build_plan` → `artifacts/plans/ATL-7K3M/build-plan.md`; advance
  `[ATL-7K3M]` `stage=ready`→ via `/prawduct:backlog update` at PR; commit; run
  `/prawduct:critic cumulative` (base `develop`) — the PR gate.

## Status
- [x] Chunk 1: schema + parse→validate→index→query→render + scaffold + tests (code).
      Full suite 3751 passed / 2 skipped (+15 new tests). Real-CLI verified on a
      `songs/<slug>/<slug>.db` layout: `--kind attempt` renders the chain, `--outcome
      failed` isolates dead ends, fulltext surfaces prose; recall-on-read auto-indexed
      hand-authored `attempts/*.md`. No fingerprint flip (no MCP handler reads markdown_refs).
- [x] Chunk 2: skill + capture wiring + discoverability spine (doc-only, cumulative-final).
      8 surfaces: new /song-attempts skill; compose-review + mix-review capture wiring;
      song-workflow SKILL + docs/song-workflow.md; song-conventions.md schema + worked
      example; docs/song-authoring-conventions.md layout; CLAUDE.md norm; song-new desc.
      active_build_plan repointed → ATL-7K3M. Skills auto-discovered (no manifest edit).
      Full suite 3751 passed/2 skipped (doc-only — no code changed).

## Context
Chunk 1 landed: `kind: attempt` is a first-class markdown corpus kind with `outcome`
(worked|partial|failed) + `resolution` (kept|reverted|superseded), a drop-and-recreate
migration for the projection's CHECK change, scaffolded `attempts/` dir, and the
`--kind attempt`/`--outcome` query surface. Next: Chunk 2 (doc-only) — the `/song-attempts`
skill, capture wiring into compose/mix-review, and the discoverability spine — then repoint
`active_build_plan` and run `/prawduct:critic cumulative` (base develop) as the PR gate.

## Out of scope (recorded — requirements §3)
Cross-song promotion; push/auto-surface retrieval; any verdict/score; process/tooling lessons
(→ prawduct learnings / incoming-bugs); a new versioning system.
