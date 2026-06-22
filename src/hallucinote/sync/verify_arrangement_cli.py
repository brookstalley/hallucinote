"""ARR-PROJ Chunk 3 — ``hallucinote verify-arrangement`` audit command.

The DETECTION layer (design §6b-B): compare the song DB's arrangement against
Live's actual arrangement clip-by-clip (collapsed-set + tolerance, via the NOTE
API — never clip-list note_count) and report extra/missing/mismatch per
(track, section). Non-zero exit on ANY divergence — run it before trusting a set,
before a render, or after a hand edit. The PREVENTION twin is the push-time
assert folded into the executor (``assert_arrangement_materialized``).

Compares the CURRENT DB (the build artifact) against Live. To verify ``build.py``
itself, rebuild first (``python songs/<slug>/build.py``).
"""
from __future__ import annotations

import argparse
import sys

from .arrangement_verify import format_report, verify_song_arrangement
from .push_cli import _open_db, _resolve_song_id, _session_for

try:  # the MCP client is a sibling install; degrade if absent (mirrors execute_push)
    from hallucinote_mcp.client import (  # type: ignore[import-not-found]
        LiveConnectionError as _LiveConnectionError,
    )
    _CONNECTION_EXCS: tuple[type[BaseException], ...] = (_LiveConnectionError, OSError)
except ImportError:  # pragma: no cover - exercised only without the MCP package
    _CONNECTION_EXCS = (OSError,)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hallucinote verify-arrangement",
        description=(
            "Audit the DB arrangement against Live (collapsed-set + tolerance, "
            "via the note API). Exit 0 = faithful, 1 = divergence found."
        ),
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--song", help="song slug → its per-branch DB")
    src.add_argument("--db", help="explicit path to a song DB")
    p.add_argument(
        "session_id", nargs="?", default=None,
        help="ableton session id (auto-discovered from the DB if omitted)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    conn = _open_db(args)
    _session_for(conn, args, subcmd="verify-arrangement")
    song_id = _resolve_song_id(conn, args.session_id)
    try:
        report = verify_song_arrangement(
            conn, song_id=song_id, session_id=args.session_id,
        )
    except _CONNECTION_EXCS as exc:
        sys.stderr.write(
            "verify-arrangement: cannot reach Ableton Live — "
            f"{exc}. Open Live with the song's set and retry.\n"
        )
        return 2
    sys.stdout.write(format_report(report) + "\n")
    return 0 if report.faithful else 1


if __name__ == "__main__":
    sys.exit(main())
