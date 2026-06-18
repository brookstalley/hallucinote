#!/usr/bin/env python3
"""Reindex the song-metadata markdown corpus into a song's SQLite DB.

Walks `songs/<name>/decisions/*.md` and `songs/<name>/annotations/*.md`,
upserts rows into `markdown_refs`, refreshes the FTS5 index, and tombstones
rows whose file vanished.

Usage:
    python3 -m hallucinote.tools.reindex_markdown songs/falling-walking/falling-walking.db
    python3 -m hallucinote.tools.reindex_markdown --songs-root songs --repo-root . <db>

The DB path is positional; the repo root + songs root default to the current
working directory and `./songs`. Run from the repo root for the defaults to
make sense.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hallucinote.db.connection import init_db
from hallucinote.markdown_refs import reindex_corpus


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db_path", help="Path to a song's SQLite DB")
    parser.add_argument(
        "--songs-root", default="songs",
        help="Root of the songs tree (default: ./songs)",
    )
    parser.add_argument(
        "--repo-root", default=".",
        help="Repo root for computing relative paths (default: .)",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db_path).resolve()
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 1

    songs_root = Path(args.songs_root).resolve()
    repo_root = Path(args.repo_root).resolve()

    conn = init_db(db_path)
    try:
        counts = reindex_corpus(
            conn, songs_root=songs_root, repo_root=repo_root
        )
    finally:
        conn.close()

    print(
        f"reindex {db_path.name}: "
        f"upserted={counts['upserted']} "
        f"tombstoned={counts['tombstoned']} "
        f"unchanged={counts['unchanged']} "
        f"skipped={counts['skipped']}"
    )
    if counts["skipped"]:
        print(
            f"  WARNING: {counts['skipped']} corpus file(s) were unparseable "
            "and excluded from the index (see warnings above).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
