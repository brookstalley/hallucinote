# EVT-6H9R — event-seed hardening (build plan)

From the 2026-07-02 audit, rec #9: harden the audit-log seed while it's cheap,
so the eventual event-store flip (EVT-4K8H) doesn't start from a desynced or
lineage-lossy log. Three chunks, one per deliverable. Baseline: develop @
6f2b0ba, full suite 4435 passed / 2 skipped.

## Chunk 1 — atomic write+emit at the `_core` level

**Problem.** Connections are autocommit (`isolation_level=None`); only ~4
mutators use `transaction()`. A crash between a mutator's state write and its
`_emit()` commits the state row without its event (or, for post-emit failures,
both rows of a partially-applied multi-statement mutator).

**Design.**
- New `_atomic` decorator in `db/mutations/_core.py`: wraps the mutator body in
  the EXISTING `connection.transaction()` helper (reuse, not a parallel
  mechanism). `transaction()` is already re-entrant via SAVEPOINTs, so
  mutator-calls-mutator composes: nested calls become savepoints that join the
  outermost transaction; only the outermost BEGIN/COMMITs. Callers that wrap
  batches in `transaction(conn)` (apply_pull_results etc.) keep their batch
  atomicity — decorated mutators inside become savepoints.
- Applied to EVERY state-writing public mutator (plus `_delete_track`) across
  the domain modules — 59 decorated functions (Critic AST-verified; an
  earlier summary said 55, an arithmetic slip). NOT applied to: pure helpers
  (`provenance_metadata`,
  `performed_automation_fingerprint`, `_normalize_note`, `_latest_actor_for`),
  and the `request()` / `build_session()` context managers (their inner
  `create_request` / `close_request` calls are themselves decorated; a whole
  build session must NOT be one transaction — partial-progress observability
  is a documented property).
- `reset_song_content`'s trailing `conn.commit()` is removed: it was an
  autocommit-era no-op-ish flush, but inside an explicit transaction it would
  commit early and make the wrapper's COMMIT fail. The wrapper now owns the
  commit. (Caller-level `conn.commit()` in sync/push_cli.py stays — Python's
  `Connection.commit()` outside a transaction is a no-op.)
- Existing inner `with transaction(conn):` blocks inside mutators
  (replace_clip_notes, replace_breakpoints, ...) are left in place — they
  become savepoints under the decorator; harmless and still correct for any
  future undecorated caller.

**Acceptance.**
- Crash injection (monkeypatched exception between write and emit): state row
  absent AND event absent after the failed call.
- Post-emit crash injection: neither state row nor event survives.
- A failing mutator nested inside an outer `transaction()` rolls back only
  itself (savepoint), outer work commits.
- Full suite green.

## Chunk 2 — drop the SET NULL FKs on `events`

**Problem.** `events.song_id` / `events.clip_id` / `events.request_id` are
`REFERENCES ... ON DELETE SET NULL`. An append-only audit log must not lose
lineage to a cascade: deleting a clip today nulls `clip_id` on every event
that ever touched it (breaking, e.g., historical actor lookups).

**Design.**
- `schema.sql`: the three columns become plain TEXT (stable IDs, not live
  FKs); comment documents the doctrine.
- SQLite can't ALTER an FK away → table-recreate migration
  `_migrate_events_drop_fks` in `init_db` (additive-migration home), before
  `executescript`. Detection: `PRAGMA foreign_key_list(events)` non-empty.
  Inside one `transaction()`: CREATE `events_new` (final shape) → INSERT
  SELECT with explicit column list (rows preserved byte-for-byte: same ids,
  seqs, ts, payloads) → DROP `events` → RENAME → recreate the five indexes.
  No table references `events`, so FK enforcement can stay ON throughout.
- Consequence cleanups (the FK was the only reason these existed):
  - `unlink_db_from_ableton`'s FK-GUARD (only stamp `clip_id` if the clip row
    still exists) is removed — the event now always carries the stable clip
    id. The two tests asserting the guard behavior are updated WITH rationale:
    they asserted FK-era incidental behavior (the guard existed solely to
    avoid the IntegrityError); the audit-information contract (id preserved
    in payload.db_id) is strengthened, not weakened — the id is now ALSO on
    the column.
  - `delete_clip` now stamps `clip_id` on its CLIP_DELETED event (previously
    impossible: the row was already gone, the FK would reject the insert).

**Acceptance.**
- `PRAGMA foreign_key_list(events)` empty on a fresh DB and on a migrated
  legacy DB.
- Migration preserves all pre-existing event rows byte-for-byte.
- Deleting a clip/song no longer nulls prior events' `clip_id`/`song_id`.
- Full suite green.

## Chunk 3 — fold-events-to-state replay smoke test

**Problem.** Nothing proves the event log can rebuild state; payload gaps
would surface only at flip time (EVT-4K8H).

**Design.** One test module `tests/unit/db/test_event_replay_smoke.py`:
- Fixture builds a representative song through the normal mutator API:
  song, sections, MIDI + audio tracks, mixer/routing, clips (both kinds),
  notes (insert + replace), device chain → device → parameters, a return +
  send, plus deletes (clip, device, track) so lineage paths are exercised.
- A fold in the test walks `events ORDER BY seq` and applies each FOLDED kind
  into a fresh `init_db` state via direct SQL (the fold is the read-model
  builder — reconstructing state FROM events is the one place raw SQL is the
  point; mutators can't be reused because they mint new ids and re-emit).
- Honest-but-complete boundary: kinds whose payloads fully determine state
  are FOLDED; kinds whose payloads are audit-grade but not replay-grade
  (e.g. `notes_inserted` carries note_ids + count but NOT pitch/start/etc.)
  are listed in NOT_YET_FOLDED with the reason. The test asserts
  FOLDED ∪ NOT_YET_FOLDED covers every constant in `hallucinote.db.events`,
  so a new event kind cannot ship unclassified.
- Convergence: per folded table, compare the event-derived rows against the
  materialized DB on the event-carried columns (ids included; timestamps
  excluded — they are wall-clock, not event-carried).

**Acceptance.**
- Fold of the fixture's event log converges with the materialized DB on every
  folded table, including the post-delete absence of deleted rows.
- Every fixture-emitted kind is folded or explicitly not-yet-folded; every
  `events.py` kind is classified.
- Full suite green (`python -m pytest`, no path arg).

## Status

- [x] Chunk 1 — atomic write+emit (54f2e00; suite 4441 green)
- [x] Chunk 2 — events FK drop + migration (b4b420f; suite 4447 green)
- [x] Chunk 3 — replay smoke test (this commit; full no-path suite 4452
      passed / 2 skipped)

Chunk 3 note: fix-what-you-find — `reset_song_content` emitted the literal
string "song_content_reset" instead of an `events.py` constant (the sanctioned
source per that module's convention, and required for the smoke test's
exhaustive kind classification). Added `E.SONG_CONTENT_RESET` and switched the
emit; the string value is unchanged.

Chunk 3 finding (for EVT-4K8H): the notes events are audit-grade, not
replay-grade — `notes_inserted` / `clip_notes_replaced` / `note_updated` /
`notes_deleted` / `notes_bulk_updated` carry ids and counts but not note
content, and `request_created` omits prompt_text/metadata. The smoke test
pins these as NOT_YET_FOLDED with reasons; payload enrichment is flip work.

## Critic round (post-chunk-3): 2 WARNINGs + 2 NOTEs, all landed

1. **WARNING — SQLITE_BUSY snapshot-upgrade exposure.** `transaction()`'s
   plain DEFERRED `BEGIN` + every mutator's read-before-write meant that in
   WAL, a second connection committing between the read and the write made
   the snapshot upgrade fail IMMEDIATELY with "database is locked"
   (busy_timeout is not consulted for a stale-snapshot upgrade; the
   MCP-server + build.py two-writer topology is exactly this shape). FIX:
   `BEGIN IMMEDIATE` at depth 0 — the write lock is taken at BEGIN, so
   concurrent writers queue on the busy handler instead of one side failing
   fast. Zero read-concurrency cost (transaction() is write-path-only; WAL
   readers never block on the writer). Regression test
   (`test_concurrent_writer_queues_instead_of_failing_fast`): a hook inside
   conn A's mutator proves conn B's write gets BUSY (A holds the lock from
   BEGIN) while A's mutator completes — under the old DEFERRED behavior B's
   write succeeded and A's write was the one that failed. Deterministic (B
   uses a 50 ms busy_timeout), no sleeps.
2. **WARNING — `_emit` accepted arbitrary kind strings.** An inline-string
   kind escaped both exhaustiveness guards (exactly how "song_content_reset"
   drifted). FIX: `events.py` now derives `KINDS` (frozenset of every
   UPPER_CASE string constant — adding a constant IS the registration step)
   and `_emit` rejects any kind not in it. Grep confirmed no remaining
   non-constant emitters (the one known case was fixed in chunk 3).
3. **NOTE — depth-counter leak on COMMIT failure.** If COMMIT raised, the
   `_TRANSACTION_DEPTH` pop never ran → the connection was stuck at
   depth>=1 and every later mutator SAVEPOINTed into a transaction nobody
   commits (silent write loss). FIX: pop moved to a `finally`; a failed
   COMMIT also ROLLBACKs so the connection stays usable. The nested branch
   got the symmetric `finally` depth-restore. Tested with a stub connection
   whose COMMIT raises.
4. **NOTE — migration copy list frozen at 10 columns.** A legacy `events`
   table carrying an unexpected extra column would have its data silently
   dropped by the recreate. FIX: `_migrate_events_drop_fks` asserts
   `PRAGMA table_info(events)` matches the expected 10 names and refuses
   loudly otherwise. Tested with a rogue-column legacy DB.

## Test-change log (rationale, per the tests-are-contracts rule)

- `tests/unit/db/test_mutations.py::test_unlink_clip_link_survives_deleted_clip_row`
  — asserted `ev["clip_id"] is None` for a dangling clip unlink. That NULL was
  the FK workaround itself (PSH-3K9D guard), not a product contract; the
  product contract ("no audit information lost", id preserved in payload) is
  strengthened by stamping the stable id on the column. Updated to assert
  `ev["clip_id"] == clip`.
- `tests/unit/db/test_mutations.py::test_unlink_existing_clip_link_stamps_clip_id`
  — unchanged in assertion; docstring updated (no longer "the normal case" vs
  a guard — stamping is now unconditional).
