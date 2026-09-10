"""Remove a track row a capture snapshot no longer defines — the operator's
remedy for the orphan `replay_capture` reports.

Replay reconciles a song's track rows against a snapshot BY NAME, and a row the
snapshot does not claim is reported, never deleted: it can be carrying pulled
human work — its mixer state, its sends, a device chain with tuned parameters,
its clips and notes — that a build without ``--reset`` does not re-author, and
``replay_capture`` already REFUSES rather than silently reverting pulled edits.
Auto-pruning would be that same harm escalated from revert to delete, on the
strength of a snapshot that may simply be stale.

But reporting an orphan without offering a way to remove it just relocates the
problem into the operator's head, and an orphan is not inert: the next push
materializes it as a junk track in Live. So this command exists. It shows every
child row that goes with the track before it takes a confirmation, and it
REFUSES on anything it cannot fully enumerate — deleting something you could
not describe first is the failure the whole design exists to avoid.

Usage::

    hallucinote prune-tracks --db <song>.db [--song NAME] --track 'Old Bagpipes'
    hallucinote prune-tracks --db <song>.db --all-orphans --snapshot captured_session.json
    hallucinote prune-tracks --db <song>.db --all-orphans --snapshot ... --dry-run

``--track NAME`` (repeatable) removes rows the replay alert named.
``--all-orphans --snapshot PATH`` re-derives the orphan set against a snapshot
— the same reconciliation replay runs — and removes all of them. Nothing is
deleted without ``--yes`` or a typed ``yes`` at the prompt; ``--dry-run``
prints the plan and stops.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable

from hallucinote.capture import plan_track_reconciliation
from hallucinote.db import queries as Q
from hallucinote.db.connection import connect
from hallucinote.db.mutations.tracks import describe_track_deletion, prune_track


def _resolve_song_id(conn: sqlite3.Connection, song: str | None) -> str:
    """The song to act on: the named one, or the DB's only one.

    Guessing among several songs is exactly the kind of unenumerated deletion
    this command refuses, so a multi-song DB requires ``--song``.
    """
    if song is not None:
        row = Q.get_song_by_name(conn, song)
        if row is None:
            raise LookupError(f"no song named {song!r} in this DB")
        return row["id"]
    rows = conn.execute("SELECT id, name FROM songs ORDER BY name").fetchall()
    if not rows:
        raise LookupError("this DB holds no songs")
    if len(rows) > 1:
        names = ", ".join(repr(r["name"]) for r in rows)
        raise LookupError(
            f"this DB holds {len(rows)} songs ({names}) — name one with --song"
        )
    return rows[0]["id"]


def _orphan_rows(
    conn: sqlite3.Connection, song_id: str, snapshot_path: Path,
) -> list[Any]:
    """The rows a replay of `snapshot_path` would report as orphaned — derived
    by the same planner replay uses, so the two can never disagree."""
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    plan = plan_track_reconciliation(
        Q.get_tracks_for_song(conn, song_id), snapshot.get("tracks") or [],
    )
    return list(plan.orphans)


def _rows_by_name(
    conn: sqlite3.Connection, song_id: str, names: list[str],
) -> tuple[list[Any], list[str]]:
    """Resolve ``--track`` names to rows. A name matching zero or several rows
    is returned as a problem, never guessed at — the same refusal replay's
    reconciliation makes."""
    rows = Q.get_tracks_for_song(conn, song_id)
    problems: list[str] = []
    resolved: list[Any] = []
    for name in names:
        matches = [
            r for r in rows if r["name"] == name and r["kind"] != "master"
        ]
        if not matches:
            problems.append(f"no track named {name!r} in this song")
        elif len(matches) > 1:
            indexes = ", ".join(str(r["track_index"]) for r in matches)
            problems.append(
                f"{len(matches)} tracks are named {name!r} (indexes {indexes}) "
                "— rename them in Live so the one to remove is nameable"
            )
        else:
            resolved.append(matches[0])
    return resolved, problems


def _confirm(prompt: str, reader: Callable[[str], str]) -> bool:
    try:
        answer = reader(prompt)
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def _run(args: argparse.Namespace, reader: Callable[[str], str]) -> int:
    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"error: no DB at {db_path}", file=sys.stderr)
        return 2
    if not args.track and not args.all_orphans:
        print(
            "error: name what to remove — --track NAME (repeatable) or "
            "--all-orphans --snapshot PATH. Deleting track rows is not the "
            "default for a forgotten argument.",
            file=sys.stderr,
        )
        return 2
    if args.all_orphans and not args.snapshot:
        print(
            "error: --all-orphans needs --snapshot PATH — an orphan is only "
            "defined relative to the snapshot that fails to claim it",
            file=sys.stderr,
        )
        return 2

    conn = connect(db_path)
    try:
        try:
            song_id = _resolve_song_id(conn, args.song)
        except LookupError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        targets: list[Any] = []
        seen: set[str] = set()
        if args.track:
            resolved, problems = _rows_by_name(conn, song_id, args.track)
            for problem in problems:
                print(f"error: {problem}", file=sys.stderr)
            if problems:
                return 2
            for row in resolved:
                if row["id"] not in seen:
                    seen.add(row["id"])
                    targets.append(row)
        if args.all_orphans:
            snapshot_path = Path(args.snapshot)
            if not snapshot_path.is_file():
                print(f"error: no snapshot at {snapshot_path}", file=sys.stderr)
                return 2
            for row in _orphan_rows(conn, song_id, snapshot_path):
                if row["id"] not in seen:
                    seen.add(row["id"])
                    targets.append(row)

        if not targets:
            print("nothing to prune")
            return 0

        plans = []
        refused = False
        for row in targets:
            plan = describe_track_deletion(conn, track_id=row["id"])
            if plan is None:  # pragma: no cover — resolved a moment ago
                print(f"error: track row {row['id']!r} vanished", file=sys.stderr)
                return 1
            print(
                f"track index {plan.track_index} {plan.name!r} "
                f"— takes with it: {plan.summary()}"
            )
            for blocker in plan.blockers:
                refused = True
                print(f"  REFUSED: {blocker}", file=sys.stderr)
            plans.append(plan)
        if refused:
            print(
                "error: refusing to delete a track whose dependents cannot be "
                "fully enumerated",
                file=sys.stderr,
            )
            return 1

        if args.dry_run:
            print("\n(dry run — nothing was removed)")
            return 0
        if not args.yes and not _confirm(
            f"delete {len(plans)} track row(s) and everything above? [y/N] ",
            reader,
        ):
            print("aborted — nothing was removed")
            return 1

        for plan in plans:
            prune_track(
                conn, track_id=plan.track_id, actor="user",
                reason="hallucinote prune-tracks",
            )
            print(f"removed {plan.name!r} (was index {plan.track_index})")
        return 0
    finally:
        conn.close()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hallucinote prune-tracks",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--db", required=True, help="path to a song's SQLite DB")
    p.add_argument(
        "--song", default=None,
        help="song name (required only when the DB holds more than one)",
    )
    p.add_argument(
        "--track", action="append", default=[], metavar="NAME",
        help="name of a track row to remove; repeatable",
    )
    p.add_argument(
        "--all-orphans", action="store_true",
        help="remove every row --snapshot fails to claim",
    )
    p.add_argument(
        "--snapshot", default=None, metavar="PATH",
        help="captured_session.json to derive the orphan set from",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="print what would go and stop",
    )
    p.add_argument(
        "--yes", action="store_true",
        help="skip the confirmation prompt",
    )
    return p


def main(
    argv: list[str] | None = None,
    *,
    reader: Callable[[str], str] = input,
) -> int:
    args = _build_parser().parse_args(argv)
    return _run(args, reader)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
