"""One-shot migration: strip Live's `<letter>-` slot prefix from
`returns.name` rows.

W4-C cross-layer fix (2026-05-18). Live 12.4 unconditionally prefixes
every `ReturnTrack.name` write with `<slot-letter>-` (A-, B-, ...).
Storing the prefixed form in the DB causes double-prefixing on push
(DB "A-Reverb" → Live "A-A-Reverb"). The DB now stores SUFFIX-only
return names; capture / pull strip on read, push emits the bare
suffix, Live re-adds its prefix.

Required for any song DB created before W4-C. Songs whose returns.name
values don't match `^[A-Z]-` have nothing to do — idempotent.

Usage:

    python tools/migrate_returns_strip_prefix.py path/to/song.db

Prints a summary of rows updated. Safe to re-run.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

_SLOT_PREFIX = re.compile(r"^[A-Z]-")


def migrate(db_path: Path) -> dict[str, int]:
    """Migrate one DB in place. Returns {rows_examined, rows_stripped}."""
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    counts = {"rows_examined": 0, "rows_stripped": 0}
    try:
        conn.execute("BEGIN")
        rows = conn.execute(
            "SELECT id, name FROM returns WHERE name IS NOT NULL"
        ).fetchall()
        counts["rows_examined"] = len(rows)
        for r in rows:
            stripped = _SLOT_PREFIX.sub("", r["name"], count=1)
            if stripped != r["name"]:
                conn.execute(
                    "UPDATE returns SET name = ? WHERE id = ?",
                    (stripped, r["id"]),
                )
                counts["rows_stripped"] += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Strip Live's `<letter>-` slot prefix from returns.name."
    )
    parser.add_argument("db_path", type=Path, help="Path to the SQLite DB file.")
    args = parser.parse_args(argv)

    if not args.db_path.exists():
        print(f"error: {args.db_path} does not exist", file=sys.stderr)
        return 1

    counts = migrate(args.db_path)
    print(f"migrated {args.db_path}:")
    print(f"  rows_examined  {counts['rows_examined']:6d}")
    print(f"  rows_stripped  {counts['rows_stripped']:6d}")
    if counts["rows_stripped"] == 0:
        print("  (nothing to do — names already on suffix-only form)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
