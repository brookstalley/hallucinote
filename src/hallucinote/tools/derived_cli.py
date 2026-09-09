"""`hallucinote derived verify|prune` — the derived cache's lifecycle, from the song.

Every file under ``assets/derived/`` is the output of a recorded recipe and is
named by the content of what made it, so the cache needs exactly two questions
answered from outside: *is each file still what its record says* (``verify``)
and *which files does nothing in the song reference any more* (``prune``).
The recipes themselves live in ``build.py`` and have no registry by design;
the set a song currently addresses is what its DB's ``clips.audio_file`` and
``devices.audio_file`` columns point at, so ``prune`` reads those. Neither
subcommand deletes anything — ``prune`` lists, and the deletion is the user's.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hallucinote.assets import recipes
from hallucinote.db.connection import connect, resolve_db_path
from hallucinote.workspace import resolve_song_dir


def _song_dir(args: argparse.Namespace) -> Path | None:
    if args.song_dir:
        return Path(args.song_dir)
    if args.song:
        try:
            return resolve_song_dir(args.song)
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return None
    return Path.cwd()


def _addressed_by_song(song_dir: Path, slug: str | None) -> list[str] | None:
    """Every audio path a song's DB references, or None if there is no DB to read.

    The distinction is the whole safety of ``prune``: a song that references
    nothing and a song we could not read both yield an empty set, and an empty
    set condemns the entire cache. Only the first of those is an answer.
    """
    if slug is None:
        return None
    db_path = resolve_db_path(slug)
    if not Path(db_path).exists():
        legacy = song_dir / f"{slug}.db"
        if not legacy.exists():
            return None
        db_path = legacy
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT audio_file FROM clips WHERE audio_file IS NOT NULL "
            "UNION SELECT audio_file FROM devices WHERE audio_file IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    return [str(song_dir / r[0]) if not Path(r[0]).is_absolute() else r[0] for r in rows]


def _cmd_verify(args: argparse.Namespace) -> int:
    song_dir = _song_dir(args)
    if song_dir is None:
        return 2
    results = recipes.verify(song_dir)
    if not results:
        print(f"derived verify: nothing under {song_dir / 'assets' / 'derived'}")
        return 0
    bad = 0
    for r in results:
        bad += 0 if r.ok else 1
        print(f"  {r.status:<22} {r.path.name}  {r.detail or ''}".rstrip())
    print(f"derived verify: {len(results)} file(s), {bad} with a problem")
    return 3 if bad else 0


def _cmd_prune(args: argparse.Namespace) -> int:
    song_dir = _song_dir(args)
    if song_dir is None:
        return 2
    addressed = _addressed_by_song(song_dir, args.song)
    if addressed is None:
        why = (
            "no --song was given" if args.song is None
            else f"no database for song {args.song!r} was found under {song_dir}"
        )
        print(
            f"error: prune needs to read the song's clips and devices to know what is\n"
            f"       still referenced, and {why}. Without that every derived file looks\n"
            f"       unreferenced. Pass --song <slug> for a song that has been built.",
            file=sys.stderr,
        )
        return 2
    orphans = recipes.prune(song_dir, addressed)
    if not orphans:
        print("derived prune: every derived file is addressed by the song; nothing to remove")
        return 0
    print(f"derived prune: {len(orphans)} file(s) no clip or device references (not deleted):")
    for p in orphans:
        print(f"  {p}")
    print("Delete them yourself — every one is regenerable from its source and recipe.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hallucinote derived",
        description="Verify or prune a song's derived-audio cache (assets/derived/).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn, help_ in (
        ("verify", _cmd_verify, "check every derived file against its record"),
        ("prune", _cmd_prune, "list derived files nothing in the song references"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--song", help="song slug (resolves the song dir and its DB)")
        p.add_argument("--song-dir", help="explicit song directory (locates assets/derived/)")
        p.set_defaults(fn=fn)
    args = parser.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
