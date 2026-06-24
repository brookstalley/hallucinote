"""CLI bridge for ``/tuning-pull``: a probed ``song.tuning_system`` → cache + persist.

    tuning-pull apply --song SLUG [--db PATH] --probe P [--reason R]
        Read the probe JSON the skill assembled (the ``song.tuning_system``
        scalars/list), derive a :class:`~hallucinote.tuning.model.TuningData`,
        write the cached ``.ascl`` under ``songs/<slug>/tunings/``, and record
        ``tuning_ref`` + ``tuning_data`` on the song through the standard mutator
        (so the ``SONG_TUNING_SET`` event falls out). Print a JSON report incl.
        the push re-load instruction. A probe with no tuning loaded (``None``) →
        a clean no-op report, exit 0.

This mirrors the ``/ableton-pull`` plan→probe→apply split, **minus the dynamic
plan**: the tuning probe set is fixed (one ``song.tuning_system`` read + its
scalar/list sub-fields), so the skill hardcodes the probes and this CLI only
does the pure ``apply``. The agent orchestrates the MCP probes (it holds
``ableton_probe``); this module never calls MCP — it is pure Python over the
already-built ``read`` → ``cache`` → ``persist`` pieces.

**Isolation (FR-6).** This module lives *inside* ``hallucinote.tuning`` (the
bolt-on), so it freely imports ``read`` / ``store`` and the core (the allowed
direction). The core never imports it: ``hallucinote.cli`` registers the
``tuning-pull`` subcommand by **string**, lazily imported only when invoked, so
no static core→tuning import exists (grep-asserted in ``test_isolation.py``).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from hallucinote.db import init_db
from hallucinote.db import mutations as M
from hallucinote.db import queries as Q
from hallucinote.db.connection import resolve_db_path
from hallucinote.sync.push.tuning_notice import reload_instruction

from .read import read_tuning_system
from .store import persist_tuning


def _resolve_db_path(args: argparse.Namespace) -> Path:
    """``--db PATH`` (escape hatch) wins; else ``--song <slug>`` → per-branch DB.

    Mirrors ``pull_cli._resolve_db_path``: resolve via the project-root contract
    (a song may live in its own repo), then fall back to the legacy bare
    ``<slug>.db`` for pre-per-branch songs.
    """
    if args.db:
        path = Path(args.db)
    else:
        path = resolve_db_path(args.song)
        if not path.exists():
            legacy = resolve_db_path(args.song, branch=None)
            if legacy.exists():
                path = legacy
    if not path.exists():
        raise SystemExit(
            f"tuning-pull: DB not found at {path} — run "
            f"`python songs/{args.song}/build.py` first to populate it."
        )
    return path


def _open_db(path: Path) -> sqlite3.Connection:
    """Open through ``init_db`` so an older DB gains the additive tuning columns
    (the ``_ensure_added_columns`` migration lives only in ``init_db``)."""
    return init_db(path)


def _cmd_apply(args: argparse.Namespace) -> int:
    raw = json.loads(Path(args.probe).read_text())
    db_path = _resolve_db_path(args)
    song_dir = db_path.parent  # songs/<slug>/ — where tunings/ is written
    conn = _open_db(db_path)

    song = Q.get_song_by_name(conn, args.song)
    if song is None:
        raise SystemExit(
            f"tuning-pull: no song named {args.song!r} in {db_path}; "
            "check the slug or run build.py first."
        )
    song_id = song["id"]

    tuning = read_tuning_system(raw)
    if tuning is None:
        # No alternate tuning loaded in Live — a clean no-op (the 12-TET case).
        # Deliberately does NOT clear an existing tuning_ref: pulling with nothing
        # loaded is an "I forgot to load it" slip, not an intent to go 12-TET.
        json.dump(
            {
                "status": "no-tuning-loaded",
                "song": args.song,
                "tuning_ref": None,
                "message": (
                    "song.tuning_system is None — no alternate tuning loaded in "
                    "Live, so nothing was pulled. Load the .ascl into Live's "
                    "Tuning section first, then re-run. (A 12-TET song needs no "
                    "tuning pull.)"
                ),
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0

    # One attributed request, mirroring pull_cli: close 'ok' on success, 'failed'
    # if persist raises (so a half-written pull leaves an audit trail).
    request_id = M.create_request(
        conn,
        actor="sync",
        intent=f"tuning-pull apply song={args.song} tuning={tuning.name!r}",
        kind="pull",
        payload={"song": args.song, "tuning_name": tuning.name},
        song_id=song_id,
        reason=args.reason,
        metadata=M.provenance_metadata(
            extra={"driver": "tuning_pull_cli", "tuning_name": tuning.name},
        ),
    )
    try:
        ref = persist_tuning(
            conn,
            song_id=song_id,
            song_dir=str(song_dir),
            tuning=tuning,
            actor="sync",
            request_id=request_id,
            reason=args.reason or "tuning-pull from Live",
        )
    except Exception:  # prawduct:allow prawduct/broad-except -- audit-log finalizer: close the request 'failed' for any exception, then re-raise so the CLI signal isn't swallowed
        M.close_request(conn, request_id=request_id, outcome="failed", actor="sync")
        raise
    M.close_request(conn, request_id=request_id, outcome="ok", actor="sync")

    json.dump(
        {
            "status": "pulled",
            "song": args.song,
            "tuning": {
                "name": tuning.name,
                "step_count": tuning.step_count,
                "period_cents": round(tuning.period_cents, 4),
                "reference_note": tuning.reference_note,
            },
            "tuning_ref": ref,
            "reload_instruction": reload_instruction(args.song, ref),
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hallucinote tuning-pull")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_apply = sub.add_parser(
        "apply",
        help="cache + persist a probed song.tuning_system onto the song",
    )
    p_apply.add_argument(
        "--song", required=True,
        help="song slug (its DB name; also resolves songs/<slug>/<slug>.db)",
    )
    p_apply.add_argument(
        "--db", default=None,
        help="explicit path to the song DB (escape hatch for tests/non-standard layouts)",
    )
    p_apply.add_argument(
        "--probe", required=True,
        help="path to the JSON the skill assembled from the song.tuning_system probes",
    )
    p_apply.add_argument(
        "--reason", default=None,
        help="optional reason annotation for the emitted SONG_TUNING_SET event",
    )
    p_apply.set_defaults(func=_cmd_apply)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
