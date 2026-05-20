#!/usr/bin/env python3
"""Query the song-metadata markdown corpus (decisions + annotations).

Used by the `/song-context` skill to retrieve composer intent + decision
rationale before non-trivial composition work. Output is markdown-formatted
for direct LLM consumption.

Usage:
    python3 tools/song_context.py --db songs/falling-walking/falling-walking.db "dim7 bridge"
    python3 tools/song_context.py --db <db> --kind decision --limit 10
    python3 tools/song_context.py --db <db> --tags chorus,bridge
    python3 tools/song_context.py --db <db> --bars 33:40

If TOPIC is given, runs FTS5 match across body + tags. All filters AND-compose.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from hallucinote.db.connection import init_db
from hallucinote.db import queries as Q


def _format_row(row: Any) -> str:
    parts = [f"### `{row['path']}`"]
    meta_bits = [f"kind: {row['kind']}", f"scope: {row['scope']}"]
    if row["frontmatter_date"]:
        meta_bits.append(f"date: {row['frontmatter_date']}")
    if row["bars_json"]:
        meta_bits.append(f"bars: {row['bars_json']}")
    if row["tags_json"]:
        tags = json.loads(row["tags_json"])
        meta_bits.append(f"tags: {', '.join(tags)}")
    parts.append("  ".join(meta_bits))
    snippet = row["snippet"] if "snippet" in row.keys() else None
    if snippet:
        parts.append("")
        parts.append(snippet)
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", required=True, help="Path to a song's SQLite DB"
    )
    parser.add_argument(
        "topic", nargs="?",
        help="Fulltext search topic (FTS5 match). Optional.",
    )
    parser.add_argument(
        "--kind", choices=("decision", "annotation", "structural-fact"),
    )
    parser.add_argument(
        "--scope", choices=("song", "time", "track", "track-time"),
    )
    parser.add_argument("--track-id", help="Filter by tracks(id) UUID")
    parser.add_argument(
        "--track", help="Filter by track name (resolves to tracks.id)",
    )
    parser.add_argument(
        "--tags", help="Comma-separated tag list; contains-any match",
    )
    parser.add_argument(
        "--bars",
        help="Bar range overlap, like '33:40' or '33' (point).",
    )
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 1

    tags = (
        [t.strip() for t in args.tags.split(",") if t.strip()]
        if args.tags else None
    )

    bars: tuple[float, float] | None = None
    if args.bars:
        if ":" in args.bars:
            a, b = args.bars.split(":", 1)
            bars = (float(a), float(b))
        else:
            v = float(args.bars)
            bars = (v, v)

    conn = init_db(db_path)
    try:
        track_id = args.track_id
        if args.track and not track_id:
            row = conn.execute(
                "SELECT id FROM tracks WHERE name = ?", (args.track,)
            ).fetchone()
            if not row:
                print(f"track not found: {args.track!r}", file=sys.stderr)
                return 1
            track_id = row["id"]
        rows = Q.find_markdown_refs(
            conn,
            kind=args.kind,
            scope=args.scope,
            track_id=track_id,
            tags=tags,
            fulltext=args.topic,
            bars=bars,
            limit=args.limit,
        )
    finally:
        conn.close()

    if not rows:
        print("(no matching refs)")
        return 0

    print(f"# {len(rows)} match{'es' if len(rows) != 1 else ''}")
    print()
    for row in rows:
        print(_format_row(row))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
