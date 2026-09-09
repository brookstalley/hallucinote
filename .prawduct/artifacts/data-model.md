---
artifact: data-model
version: 1
depends_on:
  - artifact: architecture
last_validated: 2026-08-06
---

# Data Model

The authoritative schema is **`src/hallucinote/db/schema.sql`** — read it, don't read a
paraphrase of it. This artifact records the *decisions* that shape it, which the schema
file itself cannot express.

## The central decision: materialized state, not source

The SQLite database is **not** the source of truth. It is materialized state, rebuilt
on demand from git-tracked source (`build.py` + `captured_session.json`). It is
gitignored, per-song, and per-branch.

*Why.* A disposable database can be deleted, rebuilt, and diffed against its source.
An authoritative one becomes a data-loss trap the moment it diverges from the code that
made it — and a binary blob you must back up rather than version. Everything valuable
about "a song is a git repo" follows from this choice. The full split of *what* lives
where is [`authorship-model.md`](authorship-model.md).

## The event log

Every state change writes a row to `events` **in the same transaction as the change
itself**, with a monotonic `seq`. Today this is an audit log riding alongside
materialized state; it is deliberately shaped as the seed of a future event store, so
the migration is a reinterpretation rather than a rewrite.

Two invariants make that future affordable, and both are absolute:

- **All writes go through mutators** (`db/mutations/`). No write SQL in callers.
- **Every mutator emits exactly one event.** `_emit` is the only path.

A caller that reaches around the mutators doesn't just skip an audit row — it makes the
event log a lie, which is the one failure this design cannot absorb.

## Identity

UUIDs (TEXT), generated in Python by the mutators via `_uuid()` — never database
autoincrement. Identity must survive a rebuild and be stable across machines and
branches, which an autoincrement counter cannot promise.

Live's own identifiers are **positional and get renumbered by Live**, so they are never
used as identity. Bindings between our UUIDs and Live's positions live in separate
`ableton_sessions` / `ableton_links` tables, isolated from core rows precisely because
they are the volatile part.

## Opening a database

Always open an existing song DB through **`init_db`**, never a bare `connect`. Additive
migration lives only in `init_db`; a bare connect reads a stale schema and crashes
legacy databases. This is the open-side sibling of mutator discipline.

## Consumers

Schema changes are a contract surface with a documented consumer list —
[`boundary-patterns.md`](boundary-patterns.md) has it, along with the "update mutators
and queries together" rule.

## Direction

Ratified 2026-08-10. These bind future work; the narrative above describes it.

- **The SQLite database is materialized state, never the source of truth.** Source is
  `build.py` + `captured_session.json` in git; the DB is gitignored, per-song, per-branch,
  and rebuildable with `build.py --reset`.
  Why: a disposable database can be deleted, rebuilt and diffed against its source. An
  authoritative one becomes a data-loss trap the moment it diverges from the code that
  made it, and a binary blob you must back up rather than version. Every recoverable
  failure in [`architecture.md`](architecture.md)'s runtime table descends from this
  choice, and so does everything valuable about "a song is a git repo".

- **All writes go through mutators (`db/mutations/`); no write SQL in callers.**
  Why: a caller that reaches around the mutators does not merely skip an audit row — it
  makes the event log a *lie*, and a log that is wrong in unknown places is worse than no
  log, because every future reader trusts it. This is the one failure this design cannot
  absorb.
  Scope: **writes**. Reads may use `conn.execute` directly — a `SELECT` cannot make the
  log lie, and the norm's original "no raw SQL in callers, *ever*" was wider than the why
  above justifies. Narrowed by owner ruling 2026-09-08 (JANITOR-2026-09 R1), the first
  Norm Health sweep, which measured 22 sites outside `db/`: 5 writes and 17 reads.
  Bounded exception (writes): **`markdown_refs.py`** writes `markdown_refs` and
  `markdown_refs_fts` with raw SQL, and does not emit events. It is a projection rebuilt
  from disk, not a domain mutation — the audit-side event (`MARKDOWN_REF_RECORDED`) fires
  when a file is authored, and reindex is the read-side index. The reasoning is stated at
  that module's docstring; it is recorded here so a *second* such bypass has a boundary to
  be measured against rather than a precedent to point at.

- **Every mutator emits exactly one event, in the same transaction as its state change.**
  `_emit` is the only path.
  Why: same-transaction emission is what makes the log complete by construction rather
  than by discipline — a crash between the write and the event cannot produce a gap. Paired
  with the mutator rule above, it is what keeps the eventual event-store flip a
  reinterpretation rather than a rewrite.

- **Identity is a Python-generated UUID from the mutators (`_uuid()`), never a database
  autoincrement.**
  Why: identity must survive a rebuild and stay stable across machines and branches. An
  autoincrement counter promises none of that — it renumbers on every rebuild, which in a
  product whose database is disposable means identity that dissolves exactly when it is
  needed.

- **Live's own identifiers are never used as identity; bindings live in the
  `ableton_sessions` / `ableton_links` tables.**
  Why: Live's identifiers are positional and Live renumbers them, so anything keyed on them
  silently retargets when a user drags a track. Isolating the bindings from core rows keeps
  the volatile part in one place where its churn is expected rather than surprising.

- **An existing song DB is opened through `init_db`, never a bare `connect`.**
  Why: additive migration lives only in `init_db`, so a bare connect reads a stale schema
  and crashes legacy databases — the open-side sibling of mutator discipline, and a failure
  that surfaces far from its cause.
  Rulings: [[Open an existing song DB through `init_db` (migrate-on-open) — bare `connect()` reads a stale schema and crashes]],
  [[The schema canary checks column PRESENCE, not column DEFINITION]]
