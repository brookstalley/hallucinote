#!/usr/bin/env python3
"""Query the song-metadata markdown corpus (decisions + annotations).

Used by the `/song-context` skill to retrieve composer intent + decision
rationale before non-trivial composition work. Output is markdown-formatted
for direct LLM consumption.

Usage:
    python3 -m hallucinote.tools.song_context --db songs/falling-walking/falling-walking.db "dim7 bridge"
    python3 -m hallucinote.tools.song_context --db <db> --kind decision --limit 10
    python3 -m hallucinote.tools.song_context --db <db> --tags chorus,bridge
    python3 -m hallucinote.tools.song_context --db <db> --bars 33:40

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
from hallucinote.markdown_refs import reindex_corpus


# Tokens that signal a constraint or avoidance — when a row mentions them,
# the row's intent is "don't do X" rather than "do X." Surfaced in
# --defensive mode so the agent reads the constraint BEFORE composing
# something that violates it.
_NEGATION_TOKENS: tuple[str, ...] = (
    "don't",
    "do not",
    "never",
    "avoid",
    "stay away",
    "stop ",
    "not be",
    "shouldn't",
    "should not",
    "won't",
    "cannot",
)


def _has_negation(text: str | None) -> bool:
    if not text:
        return False
    lower = text.lower()
    return any(tok in lower for tok in _NEGATION_TOKENS)


def _format_row(row: Any, *, defensive: bool = False) -> str:
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
    if defensive and _has_negation(snippet):
        parts.append(
            "**CONTRADICTION SIGNAL: row contains negation/constraint "
            "language — read in full before composing against it.**"
        )
    if snippet:
        parts.append("")
        parts.append(snippet)
    return "\n".join(parts)


def _collect_tags(rows: list[Any]) -> list[str]:
    tags: set[str] = set()
    for r in rows:
        raw = r["tags_json"] if "tags_json" in r.keys() else None
        if raw:
            tags.update(json.loads(raw))
    return sorted(tags)


def _related_by_tags(conn: Any, seed_rows: list[Any], *, limit: int) -> list[Any]:
    """Rows sharing at least one tag with any seed row, EXCLUDING seeds.

    Single SQL pass under the hood — `Q.find_markdown_refs` does the
    tag IN (?, ?, ...) match. Semantic search (embeddings) is v1.2+;
    this v1.1 surface relies on the author's manual tag taxonomy.
    """
    seed_paths = {r["path"] for r in seed_rows}
    seed_tags = _collect_tags(seed_rows)
    if not seed_tags:
        return []
    rows = Q.find_markdown_refs(conn, tags=seed_tags, limit=limit * 3)
    return [r for r in rows if r["path"] not in seed_paths][:limit]


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
    parser.add_argument(
        "--defensive",
        action="store_true",
        help=(
            "Defensive mode: reframe the results as 'things that may "
            "contradict your plan — read these before you compose.' "
            "Highlights rows whose snippet/tags carry negation/constraint "
            "language. Same query surface; rendering-layer change."
        ),
    )
    parser.add_argument(
        "--generative",
        action="store_true",
        help=(
            "Generative mode: after the topic matches, also surface rows "
            "sharing tags with the matches (under 'Related context'). "
            "Surfaces connections the user hasn't drawn yet."
        ),
    )
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
        # Recall-on-read: keep the markdown_refs projection fresh before
        # querying. The DB is disposable (rebuilt from build.py) and nothing
        # else reindexes, so without this /song-context recall is silently
        # empty. Scoped to THIS song (db_path is songs/<slug>/<slug>.db) since
        # find_markdown_refs below does not filter by song. Idempotent + cheap.
        song_dir = db_path.parent
        repo_root = song_dir.parent.parent
        try:
            reindex_corpus(conn, song_dir=song_dir, repo_root=repo_root)
        except (ValueError, OSError) as exc:
            # A malformed corpus file shouldn't block recall on the rest —
            # reindex is atomic (no partial state), so fall back to whatever
            # was already indexed and warn.
            print(f"warning: corpus reindex skipped: {exc}", file=sys.stderr)
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
        related: list[Any] = []
        if args.generative and rows:
            related = _related_by_tags(conn, rows, limit=args.limit)
    finally:
        conn.close()

    if args.defensive:
        print(
            "# Defensive mode: items below MAY CONTRADICT your plan. "
            "Read in full before composing against them — particularly "
            "any flagged with CONTRADICTION SIGNAL."
        )
        print()

    if not rows:
        print("(no matching refs)")
        return 0

    print(f"# {len(rows)} match{'es' if len(rows) != 1 else ''}")
    print()
    for row in rows:
        print(_format_row(row, defensive=args.defensive))
        print()

    if args.generative:
        if related:
            print(
                f"# Related context ({len(related)} item"
                f"{'s' if len(related) != 1 else ''}, by shared tag)"
            )
            print()
            for row in related:
                print(_format_row(row))
                print()
        else:
            print("# Related context: (none — top matches had no tags)")
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
