# Change Log — Hallucinote

<!-- Append new entries at the top. Each entry is a ## section.
     This file is separate from project-state.yaml to reduce merge conflicts
     when multiple branches add entries simultaneously. -->

## 2026-05-15 — Chunk 1: Foundation

DB-as-Source-of-Truth migration, chunk 1 of 5. Schema migrated to UUID identity (TEXT PKs generated via `uuid.uuid4().hex`); `events` table grew `seq` (monotonic local ordering), `actor`, `reason`, and `request_id` columns; new `requests` table for higher-level intent; new `ableton_sessions` + `ableton_links` projection split — Ableton bindings no longer live on core rows.

Mutator API: every mutator accepts `actor='system'`, `request_id=None`, `reason=None` kwargs. New mutators: `create_request`, `create_ableton_session`, `link_db_to_ableton(session_id, db_kind, db_id, ableton_index)` — the generic version replaces the three per-domain `link_*_to_ableton` functions. Sync planner and `apply_push_results` now thread `session_id`; bindings are read via `queries.get_ableton_link`.

Test suite: 43/43 passing (31 pre-existing + 12 new for UUIDs, requests, projection separation, mutator kwarg defaults, `events.seq` ordering, two-session isolation). Falling-walking rebuilds clean with `--reset`; `gen_notes.py` carries the FROZEN porting marker. `boundary-patterns.md` filled in with the four contract surfaces this chunk touches.

Critic (chunk mode): 4 warnings, all resolved before commit — raw-SQL leak in `sync/push.py` (added `Q.get_track`), three modules missing `from __future__ import annotations`, stale `int` type annotations in `songs/falling-walking/build.py`, unused `json` import.
