"""One-shot migration: rename `arrangement` -> `arrangement_clips` and the
two ARRANGEMENT_* event kinds to ARRANGEMENT_CLIP_*.

Required for any song DB created before the rename commit. Songs whose
build.py has been re-run via `--reset` against the post-rename schema
have nothing to do — the script detects the new shape and exits cleanly.

What this does (single transaction):

  1. `ALTER TABLE arrangement RENAME TO arrangement_clips;`
  2. Drop the three legacy indexes and recreate them under the new name
     (`idx_arrangement_clips_song/track/clip`).
  3. `UPDATE events SET kind = 'arrangement_clip_added'  WHERE kind = 'arrangement_added';`
     `UPDATE events SET kind = 'arrangement_clip_removed' WHERE kind = 'arrangement_removed';`
  4. Rewrite `events.payload_json`: rename payload key
     `arrangement_id` -> `arrangement_clip_id` on any event row whose
     payload carries it (via SQLite's JSON1: `json_set` + `json_remove`).
  5. `UPDATE ableton_links SET db_kind = 'arrangement_clip' WHERE db_kind = 'arrangement';`

Usage:

    python tools/migrate_arrangement_clip.py path/to/song.db

Prints a per-step summary of rows updated. Safe to re-run — idempotent.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def migrate(db_path: Path) -> dict[str, int]:
    """Migrate one DB in place. Returns counters per step."""
    # timeout=10.0 matches the project convention (see project-preferences.md);
    # absorbs short contention if another writer is briefly active.
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    counts: dict[str, int] = {
        "table_renamed": 0,
        "indexes_recreated": 0,
        "events_kind_added": 0,
        "events_kind_removed": 0,
        "events_payload_rewritten": 0,
        "ableton_links_updated": 0,
    }
    try:
        conn.execute("BEGIN")

        has_old = _table_exists(conn, "arrangement")
        has_new = _table_exists(conn, "arrangement_clips")
        if has_old and has_new:
            raise RuntimeError(
                "both 'arrangement' and 'arrangement_clips' tables exist — "
                "manual reconciliation required"
            )

        # Step 1 + 2: rename table + indexes (only if old name is present).
        if has_old:
            conn.execute("ALTER TABLE arrangement RENAME TO arrangement_clips")
            counts["table_renamed"] = 1
            for old_idx, new_idx, col in (
                ("idx_arrangement_song",  "idx_arrangement_clips_song",  "song_id"),
                ("idx_arrangement_track", "idx_arrangement_clips_track", "track_id"),
                ("idx_arrangement_clip",  "idx_arrangement_clips_clip",  "clip_id"),
            ):
                conn.execute(f"DROP INDEX IF EXISTS {old_idx}")
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {new_idx} "
                    f"ON arrangement_clips({col})"
                )
                counts["indexes_recreated"] += 1

        # Step 3: rename event kinds.
        if _table_exists(conn, "events"):
            cur = conn.execute(
                "UPDATE events SET kind = 'arrangement_clip_added' "
                "WHERE kind = 'arrangement_added'"
            )
            counts["events_kind_added"] = cur.rowcount
            cur = conn.execute(
                "UPDATE events SET kind = 'arrangement_clip_removed' "
                "WHERE kind = 'arrangement_removed'"
            )
            counts["events_kind_removed"] = cur.rowcount

            # Step 4: rewrite payload key on rows that carry it.
            # JSON1's json_set creates the new key, json_remove drops the old.
            # We only touch rows whose payload has the old key — keeps the
            # update narrow and idempotent.
            cur = conn.execute(
                """UPDATE events
                   SET payload_json = json_remove(
                       json_set(payload_json, '$.arrangement_clip_id',
                                json_extract(payload_json, '$.arrangement_id')),
                       '$.arrangement_id'
                   )
                   WHERE json_extract(payload_json, '$.arrangement_id') IS NOT NULL"""
            )
            counts["events_payload_rewritten"] = cur.rowcount

        # Step 5: ableton_links db_kind rename.
        if _table_exists(conn, "ableton_links"):
            cur = conn.execute(
                "UPDATE ableton_links SET db_kind = 'arrangement_clip' "
                "WHERE db_kind = 'arrangement'"
            )
            counts["ableton_links_updated"] = cur.rowcount

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate a song DB from the legacy `arrangement` schema "
                    "to `arrangement_clips` + matching event kinds."
    )
    parser.add_argument("db_path", type=Path, help="Path to the SQLite DB file.")
    args = parser.parse_args(argv)

    if not args.db_path.exists():
        print(f"error: {args.db_path} does not exist", file=sys.stderr)
        return 1

    counts = migrate(args.db_path)
    print(f"migrated {args.db_path}:")
    for step, n in counts.items():
        print(f"  {step:30s} {n:6d}")
    if counts["table_renamed"] == 0 and counts["events_kind_added"] == 0 \
            and counts["events_kind_removed"] == 0 \
            and counts["ableton_links_updated"] == 0:
        print("  (nothing to do — DB already on the new schema)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
