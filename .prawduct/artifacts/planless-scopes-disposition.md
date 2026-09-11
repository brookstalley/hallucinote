---
artifact: planless-scopes-disposition
version: 1
scope: RELFOLD-0910
last_validated: 2026-09-10
---

# Release-pending scopes with no build plan — why, per scope

`check-releasability` warns once per release-pending scope that has no
build-plan file under `.prawduct/artifacts/` (live or archived):

    WARNING: release-pending scope='<s>' has no build-plan file ... — work is
    shipping with no plan describing it.

The warning is correct and worth keeping. What it cannot know is *why* a given
scope has none, and an unanswered warning repeated at every release becomes
noise that hides the next real one. This file answers it per scope, so the
warning is dispositioned rather than carried.

**This is not a licence to ship planless work.** Each entry below states the
reason and whether it was legitimate. Two were.

| scope | why no plan | legitimate? |
| --- | --- | --- |
| `CHAIN-RESTORE-STR` | A one-line fix found mid-sitting during the #291 operator verification: `_param_write_kwargs` sent a float where the wire declares `str`. Trivial by the size heuristic (one file, one branch, no contract surface moved), and trivial work builds and verifies without a plan. | **Yes** — correctly sized. |
| `docs-hygiene` | Doc deep-link parity check extended from one file to every link. Mechanical sweep with a test as its own contract. | **Yes** — correctly sized. |
| `governance-file-sizes` | Ceilings on governance-file growth. Crossed a policy surface (what the repo enforces about its own artifacts) and set a durable rule, which is medium work by the "state outliving the process" clause. | **No** — should have had a plan. |
| `advisory-clearing` | Three post-sync advisories cleared in one pass: a merge driver added to `.gitattributes`, a bug report triaged, a norm re-affirmed by owner ruling. The norm re-affirmation is a governance decision, not a chore. | **No** — the ruling deserved a record of its own. |
| `effort-s-burndown` | A batch of ten-plus `effort:S` backlog items, including a **BREAKING** change to `resolve_db_path` resolution semantics and a retired CLI command (`capture restamp`). Individually small; collectively a release-visible surface change. | **No** — a batch is not trivial because its parts are. |

## The pattern worth naming

Three of the five are the same mistake: **work sized by the size of its
individual edits rather than by the size of what it changes.** A ceiling on
governance files, an owner ruling on a norm, and a breaking change to path
resolution are each a small diff and a durable commitment. The size heuristic
in `methodology/building.md` already says this — "state outliving the process"
is its medium trigger — and it was read as a file count three times.

Nothing is re-plannable now: the work shipped, and a build plan written after
the fact records a process that did not happen. What the change-log carries for
each of these is accurate and is the record that survives.

**For the release:** all five ship. The warning is answered, not suppressed —
`check-releasability` will keep emitting it, and that is correct, because the
gate should not learn to stay quiet about planless work. This file is what a
reader consults when it fires.
