#!/usr/bin/env python3
"""Query a song's compose-time audit log.

Used by the `/decisions` skill to retrieve prior LLM prompts + reasoning
before non-trivial composition work. Output is markdown-formatted for
direct LLM consumption.

Two request fields scanned in one SQL pass, song-scoped:
  - requests.prompt_text     — verbatim seed prompt for a compose / push /
                                 pull / mutate cycle
  - requests.metadata_json   — bag carrying the convention key
                                 `decision_rationale` (LLM reasoning)

Multi-keyword semantics: AND. Every keyword must appear in the row.

Usage:
    python3 -m hallucinote.tools.decisions_cli --db <db> "bridge counter-melody"
    python3 -m hallucinote.tools.decisions_cli --db <db> --keywords "bridge,dim7"
    python3 -m hallucinote.tools.decisions_cli --db <db> --limit 5 "sidechain"

See also: `/song-context` for markdown-primary ADR retrieval
(decisions/<date>-slug.md + annotations/slug.md). The two are
complementary — `/decisions` queries the audit log (what the LLM was
asked + why); `/song-context` queries the durable markdown corpus.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


from hallucinote.db import queries as Q
from hallucinote.db.connection import init_db


def _format_row(row: Any) -> str:
    """One markdown section per request row — a prompt + optional rationale."""
    parts = [f"### request `{row['id']}` ({row['kind']})"]
    meta_bits = [f"ts: {row['sort_ts']}", f"intent: {row['intent']}"]
    if row["actor"]:
        meta_bits.append(f"actor: {row['actor']}")
    parts.append("  ".join(meta_bits))
    if row["prompt_text"]:
        parts.append("")
        parts.append(f"**Prompt:** {row['prompt_text']}")
    rationale = _extract_decision_rationale(row["metadata_json"])
    if rationale:
        parts.append("")
        parts.append(f"**Rationale:** {rationale}")
    return "\n".join(parts)


def _extract_decision_rationale(metadata_json: str | None) -> str | None:
    """Surface the load-bearing `decision_rationale` key out of the
    `metadata_json` bag — the rest of the bag (model, git_sha, hostname)
    is provenance noise from the LLM's perspective."""
    if not metadata_json:
        return None
    try:
        parsed = json.loads(metadata_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    rationale = parsed.get("decision_rationale")
    return rationale if isinstance(rationale, str) else None


def _resolve_song_id(conn: Any, slug: str | None) -> str | None:
    """Find the song id by slug. None for "all songs in the DB" — but in
    practice each song has its own DB, so the single-song row case is
    the path that fires. Returns None if no song exists in the DB."""
    if slug:
        row = conn.execute(
            "SELECT id FROM songs WHERE name = ?", (slug,),
        ).fetchone()
        return row["id"] if row else None
    row = conn.execute(
        "SELECT id FROM songs ORDER BY created_at LIMIT 1",
    ).fetchone()
    return row["id"] if row else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Path to a song's SQLite DB")
    parser.add_argument(
        "topic", nargs="?",
        help="Space-separated keywords. AND semantics — every keyword "
             "must appear in the row.",
    )
    parser.add_argument(
        "--keywords",
        help="Comma-separated keyword list (alternative to positional topic). "
             "AND semantics.",
    )
    parser.add_argument(
        "--song",
        help="Song slug to scope the search. Defaults to the (single) song "
             "in the DB — songs typically have one DB each.",
    )
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)

    if args.topic and args.keywords:
        print(
            "error: pass either a positional topic OR --keywords, not both",
            file=sys.stderr,
        )
        return 2
    if args.keywords:
        keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    elif args.topic:
        keywords = args.topic.split()
    else:
        print(
            "error: provide a topic (positional) or --keywords",
            file=sys.stderr,
        )
        return 2

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 1

    conn = init_db(db_path)
    try:
        song_id = _resolve_song_id(conn, args.song)
        if song_id is None:
            print(
                "no song found in DB"
                + (f" matching slug {args.song!r}" if args.song else ""),
                file=sys.stderr,
            )
            return 1
        rows = Q.find_related_decisions(
            conn, song_id, keywords=keywords, limit=args.limit,
        )
    finally:
        conn.close()

    if not rows:
        print("(no matching decisions)")
        return 0

    print(
        f"# {len(rows)} decision{'s' if len(rows) != 1 else ''} "
        f"matching {' AND '.join(repr(k) for k in keywords)}"
    )
    print()
    for row in rows:
        print(_format_row(row))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
