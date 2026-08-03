"""``hallucinote captures`` — inspect and prune rendered capture takes.

Renders write one directory per take under ``songs/<slug>/captures/``, holding a
32-bit-float WAV for every track, return and the master. That is roughly 23 MB
per surface-minute, so a full-length multi-track song costs gigabytes per take.
The render path applies a rolling window automatically (see
``hallucinote.takes``); this command is the operator's view of the same
mechanism — inspect what is on disk, reclaim space on demand, and pin a take
that must outlive the window.

Deleting an old take is safe because the durable measurement is the MixReport in
``songs/<slug>/analysis/``, not the audio: analysis reads a take once and writes
a self-contained JSON, and baseline comparison resolves against those JSONs. The
reports are never swept. What a prune costs is the ability to re-analyze that
specific take with different parameters.

Commands::

    hallucinote captures list [--song SLUG]
    hallucinote captures prune (--song SLUG | --all) [--keep N] [--dry-run] [--force]
    hallucinote captures pin <take-dir>
    hallucinote captures unpin <take-dir>

``prune`` requires an explicit ``--song`` or ``--all``: reading is safe and
defaults to everything, but deleting gigabytes should never be what happens when
you forget an argument.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from hallucinote.takes import (
    DEFAULT_KEEP,
    ENV_KEEP,
    ENV_SWEEP,
    PIN_FILENAME,
    Take,
    execute_sweep,
    format_bytes,
    keep_from_env,
    list_takes,
    plan_sweep,
)
from hallucinote.workspace import (
    ENV_SONGS_ROOT,
    LAYOUT_SONG,
    find_workspace,
    resolve_song_dir,
)


def _captures_root(slug: str) -> Path:
    return resolve_song_dir(slug) / "captures"


def _unknown_song(slug: str) -> bool:
    """True when the slug names no song directory.

    Worth refusing rather than reporting "nothing to prune": a typo'd slug would
    otherwise look like a successful sweep that found nothing, and the operator
    would believe disk was reclaimed when it wasn't.
    """
    return not resolve_song_dir(slug).is_dir()


def discover_song_slugs() -> list[str]:
    """Every song with a captures directory, from the songs root renders use.

    Mirrors ``workspace.resolve_song_dir``'s precedence exactly —
    ``$HALLUCINOTE_SONGS_ROOT``, then a ``hallucinote.toml`` marker, then the
    legacy ``songs/`` — because the two must agree on WHERE songs live. If this
    enumerated a different root than the per-slug resolver, ``--all`` would scan
    a directory renders never write to and silently prune nothing.

    A single-song workspace reports its own slug.
    """
    env = os.environ.get(ENV_SONGS_ROOT)
    if env:
        root = Path(env)
    else:
        ws = find_workspace()
        if ws is not None and ws.layout == LAYOUT_SONG:
            return [ws.slug] if ws.slug else []
        root = (ws.root / ws.songs_root) if ws is not None else Path("songs")
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and (p / "captures").is_dir()
    )


def _describe(take: Take) -> str:
    flags = []
    if take.pinned:
        flags.append("pinned")
    if take.in_flight:
        flags.append("in-flight")
    suffix = f"  [{', '.join(flags)}]" if flags else ""
    stamp = take.captured_at or "(no captured_at)"
    return f"  {take.path.name:<28} {format_bytes(take.size_bytes):>10}  {stamp}{suffix}"


def _cmd_list(args: argparse.Namespace) -> int:
    if args.song and _unknown_song(args.song):
        print(f"error: no song directory for {args.song!r}", file=sys.stderr)
        return 2
    slugs = [args.song] if args.song else discover_song_slugs()
    if not slugs:
        print("no songs with a captures directory found", file=sys.stderr)
        return 0
    grand_total = 0
    for slug in slugs:
        takes = list_takes(_captures_root(slug))
        total = sum(t.size_bytes for t in takes)
        grand_total += total
        print(f"{slug} — {len(takes)} take(s), {format_bytes(total)}")
        for take in takes:
            print(_describe(take))
    if len(slugs) > 1:
        print(f"\ntotal across {len(slugs)} song(s): {format_bytes(grand_total)}")
    return 0


def _cmd_prune(args: argparse.Namespace) -> int:
    if not args.song and not args.all:
        print(
            "error: prune requires --song SLUG or --all (deleting takes is "
            "not the default for a forgotten argument)",
            file=sys.stderr,
        )
        return 2
    if args.song and _unknown_song(args.song):
        print(f"error: no song directory for {args.song!r}", file=sys.stderr)
        return 2
    slugs = [args.song] if args.song else discover_song_slugs()
    keep = args.keep if args.keep is not None else keep_from_env()

    total_freed = 0
    total_removed = 0
    failed = False
    for slug in slugs:
        root = _captures_root(slug)
        plan = plan_sweep(root, keep=keep, force=args.force)
        if not plan.sweep:
            print(f"{slug}: nothing to prune ({len(plan.kept)} take(s) kept)")
            continue
        print(
            f"{slug}: {len(plan.sweep)} take(s) to remove, "
            f"{format_bytes(plan.reclaimable_bytes)} reclaimable"
        )
        for take in plan.sweep:
            print(_describe(take))
        if args.dry_run:
            continue
        result = execute_sweep(plan)
        total_removed += len(result.removed)
        total_freed += result.freed_bytes
        for path, err in result.failures:
            failed = True
            print(f"  FAILED to remove {path}: {err}", file=sys.stderr)

    if args.dry_run:
        print("\n(dry run — nothing was removed)")
        return 0
    if total_removed:
        print(f"\nremoved {total_removed} take(s), freed {format_bytes(total_freed)}")
    return 1 if failed else 0


def _cmd_pin(args: argparse.Namespace) -> int:
    take_dir = Path(args.take_dir)
    if not take_dir.is_dir():
        print(f"error: not a directory: {take_dir}", file=sys.stderr)
        return 2
    (take_dir / PIN_FILENAME).write_text(
        "Pinned: retention sweeps skip this take. Delete this file to unpin.\n",
        encoding="utf-8",
    )
    print(f"pinned {take_dir}")
    return 0


def _cmd_unpin(args: argparse.Namespace) -> int:
    take_dir = Path(args.take_dir)
    marker = take_dir / PIN_FILENAME
    if not marker.exists():
        print(f"{take_dir} was not pinned")
        return 0
    marker.unlink()
    print(f"unpinned {take_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hallucinote captures",
        description=(
            "Inspect and prune rendered capture takes. Renders are swept "
            f"automatically at render start (keeping {DEFAULT_KEEP} by default); "
            f"set {ENV_KEEP} to change the window, or {ENV_SWEEP}=0 to turn the "
            "automatic sweep off."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="show takes on disk with their sizes")
    p_list.add_argument("--song", help="song slug (default: every song)")
    p_list.set_defaults(func=_cmd_list)

    p_prune = sub.add_parser("prune", help="remove takes outside the keep window")
    p_prune.add_argument("--song", help="song slug to prune")
    p_prune.add_argument(
        "--all", action="store_true", help="prune every song in the workspace"
    )
    p_prune.add_argument(
        "--keep", type=int, default=None,
        help=f"how many unpinned takes to keep (default: ${ENV_KEEP} or {DEFAULT_KEEP})",
    )
    p_prune.add_argument(
        "--dry-run", action="store_true",
        help="print what would be removed and exit without deleting anything",
    )
    p_prune.add_argument(
        "--force", action="store_true",
        help="also prune takes whose status.json still reads state=running "
             "(use when a render died and left a stale marker)",
    )
    p_prune.set_defaults(func=_cmd_prune)

    p_pin = sub.add_parser("pin", help="mark a take so sweeps never remove it")
    p_pin.add_argument("take_dir", help="path to the take directory")
    p_pin.set_defaults(func=_cmd_pin)

    p_unpin = sub.add_parser("unpin", help="remove a take's pin marker")
    p_unpin.add_argument("take_dir", help="path to the take directory")
    p_unpin.set_defaults(func=_cmd_unpin)

    args = parser.parse_args(argv)
    if getattr(args, "keep", None) is not None and args.keep < 0:
        print("error: --keep must be >= 0", file=sys.stderr)
        return 2
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover - console entry
    raise SystemExit(main())
