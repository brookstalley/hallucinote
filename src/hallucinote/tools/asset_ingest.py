#!/usr/bin/env python3
"""Put an audio clip into a song's asset store, and say what happened to it.

The command a user runs to hand Hallucinote a sample::

    hallucinote asset add <file> --name rivers-01 \\
        --note "the pilot's last transmission" \\
        --origin "Rivers of Sand (1974), reel 3, the radio scene"
    hallucinote asset list
    hallucinote asset verify

``add`` normalizes the file into ``assets/sources/<name>.wav`` (float32 WAV,
its own sample rate and channel count kept) and records its provenance in
``assets/manifest.json``. ``list`` reads that manifest back; ``verify`` checks
that every source it names is still on disk and still its recorded checksum.
The output is the record of what happened to the file, so it names the route
the decode took, the shape of what landed, and anything the user should know.

Film dialogue is somebody's copyright. Personal and creative use is one thing
and distributing a released track built on it is another; clearance is the
user's call, not this tool's.

Exit codes: 0 = done · 1 = refused (with the reason and what to do) · 2 = no
such song · 3 = `verify` found a problem.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_COPYRIGHT_NOTE = (
    "Film dialogue is somebody's copyright: personal and creative use is one "
    "thing, distributing a released track built on it is another, and "
    "clearance is your call, not this tool's."
)


def _resolve_song_dir(args: argparse.Namespace) -> Path:
    """Where the store lives: an explicit dir, a named song, or the cwd.

    The cwd default is what makes the documented one-liner work from inside a
    song directory; ``--song`` resolves through the workspace precedence so the
    command reaches a song in a sibling songs repo too.
    """
    if args.song_dir is not None:
        return Path(args.song_dir)
    if args.song is not None:
        from hallucinote.workspace import resolve_song_dir

        return resolve_song_dir(args.song)
    return Path.cwd()


def _cmd_add(args: argparse.Namespace) -> int:
    from hallucinote.assets import ingest as ingest_mod

    song_dir = _resolve_song_dir(args)
    if not song_dir.is_dir():
        print(f"asset: no song directory at {song_dir}", file=sys.stderr)
        return 2
    try:
        result = ingest_mod.ingest(
            song_dir,
            args.file,
            name=args.name,
            note=args.note,
            origin=args.origin,
            replace=args.replace,
            allow_large=args.allow_large,
        )
    except ValueError as exc:
        print(f"asset add: {exc}", file=sys.stderr)
        return 1

    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    entry = result.entry
    verb = "replaced" if result.replaced else "added"
    channels = "mono" if entry.channels == 1 else f"{entry.channels}ch"
    print(
        f"{verb} {entry.name}: {entry.path} — {entry.duration_s:.2f}s, "
        f"{entry.sample_rate} Hz {channels}, float32 "
        f"(decoded by {result.decoder} from {entry.original_format}"
        f"{', lossy' if entry.original_lossy else ''})"
    )
    print(f"  what it is: {entry.note}")
    print(f"  from: {entry.origin}")
    print(f"  checksum: {entry.checksum}")
    if entry.superseded:
        print(f"  superseded: {', '.join(c[:12] + '…' for c in entry.superseded)}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    from hallucinote.assets import store

    song_dir = _resolve_song_dir(args)
    entries = store.load_manifest(song_dir).entries
    if not entries:
        print(f"no sources in {store.manifest_path(song_dir)}")
        return 0
    for entry in entries:
        channels = "mono" if entry.channels == 1 else f"{entry.channels}ch"
        print(
            f"{entry.name}: {entry.duration_s:.2f}s, {entry.sample_rate} Hz "
            f"{channels} — {entry.note} [{entry.origin}]"
        )
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    from hallucinote.assets import store

    song_dir = _resolve_song_dir(args)
    problems = store.verify(song_dir)
    if not problems:
        n = len(store.load_manifest(song_dir).entries)
        print(f"{n} source(s) verified: every file present and unchanged.")
        return 0
    for problem in problems:
        print(f"{problem.name}: {problem.detail}", file=sys.stderr)
    return 3


def _add_song_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--song", help="song slug (default: the current directory is the song)"
    )
    parser.add_argument(
        "--song-dir", help="explicit song directory; overrides --song"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hallucinote asset",
        description=__doc__,
        epilog=_COPYRIGHT_NOTE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_add = subparsers.add_parser(
        "add",
        help="normalize a clip into assets/sources/ and record its provenance",
        description=__doc__,
        epilog=_COPYRIGHT_NOTE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_add.add_argument("file", help="the audio clip to ingest")
    p_add.add_argument(
        "--name", required=True,
        help="the name this source is addressed by (also its filename)",
    )
    p_add.add_argument(
        "--note", required=True,
        help="what the line IS — for film material, the only record of it",
    )
    p_add.add_argument(
        "--origin", required=True,
        help="where it is from: title / medium / scene (prose, not a path)",
    )
    p_add.add_argument(
        "--replace", action="store_true",
        help="put new bytes in an existing name's slot (keeps the old checksum "
             "in the entry's superseded list)",
    )
    p_add.add_argument(
        "--allow-large", action="store_true",
        help="ingest a file above the 100 MB limit; sources are committed to "
             "the songs repo",
    )
    _add_song_arguments(p_add)
    p_add.set_defaults(func=_cmd_add)

    p_list = subparsers.add_parser("list", help="list the song's sources")
    _add_song_arguments(p_list)
    p_list.set_defaults(func=_cmd_list)

    p_verify = subparsers.add_parser(
        "verify", help="check every source is present and unchanged"
    )
    _add_song_arguments(p_verify)
    p_verify.set_defaults(func=_cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
