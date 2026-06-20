# `push probe-and-link` crashes with a FOREIGN KEY violation while reconciling stale links

**Severity:** M (push dead-end on a reused session after a `--reset` rebuild +
a track deleted in Live). The documented common-case flow — omit the session id,
let the CLI auto-select the bound session and reconcile links with `--probe` —
crashes with an unhandled `sqlite3.IntegrityError` instead of either succeeding
or teaching a recovery. The user-facing symptom is a raw Python traceback in the
middle of the canonical push workflow.

**Engine version:** `0.1.0+fe59b5d36c8d` (server fingerprint `fe59b5d36c8d`).

## What happened (swell, branch `compose/swell`)

Sequence that produced it:
1. Deleted an orphan track in Live via `ableton_track(action='delete')` — "ZZ
   Theme Preview" (Live went 24 → 23 tracks). It existed in neither `build.py`
   nor the DB, so this was a clean Live-only delete.
2. Rebuilt the DB from `build.py` with `--reset` (a compose change). The reset
   replayed the committed `captured_session.json` (which is **pre-SNP-8R4K** —
   the build emits the documented "snapshot predates SNP-8R4K" warning),
   recreating the `ableton_sessions` row + `ableton_links`.
3. `push probe-and-link --song swell --probe` (no session id → auto-selected the
   only session, `76c540da…` 'swell-20260618-044751').

Crash:

```
push_cli probe-and-link: session 76c540da… ('swell-20260618-044751') — auto-selected (only session)
Traceback (most recent call last):
  ...
  File ".../sync/push/probe.py", line 558, in probe_and_link
    M.unlink_db_from_ableton(
  File ".../db/mutations/links.py", line 267, in unlink_db_from_ableton
    _emit(
  File ".../db/mutations/_core.py", line 145, in _emit
    conn.execute(
sqlite3.IntegrityError: FOREIGN KEY constraint failed
```

The crash is in the **strict stale-link reconciliation** — `unlink_db_from_ableton`
emits a DELETE that violates an FK. Most likely a parent link row (track or
return) is deleted while child rows (clip links?) still reference it — i.e. the
cascade either isn't `ON DELETE CASCADE` or doesn't delete children-before-parent
in dependency order. The probe found a stale link (the deleted ZZ track's
`ableton_index`, and/or the `--reset`-regenerated links pointing at indices that
shifted when ZZ was removed), and unlinking it tripped the constraint.

## Workaround that unblocked

`push probe-and-link --auto-session --song swell --probe` — minting a **fresh**
session has no pre-existing `ableton_links` to reconcile, so it never enters
`unlink_db_from_ableton`. It then linked cleanly (all 23 DB tracks matched,
`unlinked_stale_* = []`, `unmatched_* = []`) and `execute` proceeded normally.
Cost: a fresh session re-performs all automation arcs (full-song realtime perform).

## Suspected fix

In `unlink_db_from_ableton` (`db/mutations/links.py`), delete dependent
clip-link rows before their parent track/return link (or add `ON DELETE CASCADE`
to the FK), so stale-link reconciliation can't violate the constraint. Reproduce
by: link a session, delete a linked track in Live, `--reset` rebuild, then
`probe-and-link --probe` against the reused session.

## Possibly-related

`2026-06-18-no-mcp-path-from-session-override-back-to-arrangement.md` — same "ZZ
Theme Preview" orphan track; this is the cleanup aftermath.
