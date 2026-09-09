"""Database layer.

Discipline:
- All writes go through `mutations`, never raw SQL in callers.
- Every mutator emits an `events` row alongside the state change.
- This keeps the door open to flipping source-of-truth from state -> events
  without rewriting generators or sync code.
"""
from __future__ import annotations

from hallucinote.db.connection import connect, init_db, resolve_db_path

__all__ = ["connect", "init_db", "resolve_db_path"]
