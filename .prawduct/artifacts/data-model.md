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

- **All writes go through mutators** (`db/mutations.py`). No raw SQL in callers, ever.
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
