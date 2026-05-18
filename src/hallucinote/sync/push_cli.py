"""CLI bridge between the ``/ableton-push`` skill and the pure Python push layer.

Mirror of :mod:`hallucinote.sync.pull_cli`. The push side has a more
elaborate flow because :func:`push.plan_push_song` returns ten ordered
phases (vs. pull's flat domain set), and probe-and-link runs before
the phases to bind any Live tracks/returns that already match DB rows.

Subcommands:

    push_cli phases <session_id> (--song SLUG | --db PATH)
        -> emit {"phases": [{"name", "description"}, ...]} for the skill
           to enumerate. The push skill drives them in order.

    push_cli plan <phase> <session_id> (--song SLUG | --db PATH)
        -> emit one phase's PushPlan as JSON (same shape as pull_cli's
           plan output).

    push_cli apply <session_id> (--song SLUG | --db PATH) --results R
        -> read the results array, call apply_push_results, emit a
           {"applied", "failed", "details"} summary.

    push_cli probe-and-link <session_id> (--song SLUG | --db PATH) --snapshot S
        -> read a {"tracks": [...], "returns": [...]} snapshot
           (the skill assembles it from ``ableton_track(action='list')``
           and ``ableton_return(action='list')`` MCP probes), match by
           name, write ableton_links rows for matches, emit a
           ProbeAndLinkResult JSON. Re-runnable.

The skill orchestrates: probe Live for tracks+returns → probe-and-link
→ enumerate phases → for each phase: plan → execute MCP calls → apply →
move on. All MCP work lives in the skill; Python stays pure.

DB resolution mirrors :mod:`pull_cli`: ``--song <slug>`` resolves to
``songs/<slug>/<slug>.db``; ``--db PATH`` is the escape hatch.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hallucinote.db import queries as Q
from hallucinote.db.connection import connect
from hallucinote.sync import push


def _resolve_db_path(args: argparse.Namespace) -> Path:
    """``--song <slug>`` → ``songs/<slug>/<slug>.db``; ``--db PATH`` → PATH."""
    if args.db:
        path = Path(args.db)
    else:
        path = Path("songs") / args.song / f"{args.song}.db"
    if not path.exists():
        raise SystemExit(
            f"push_cli: DB not found at {path} — "
            "songs convention is one DB per song at songs/<slug>/<slug>.db"
        )
    return path


def _resolve_song_id(conn, session_id: str) -> str:
    session = Q.get_ableton_session(conn, session_id)
    if session is None:
        raise SystemExit(
            f"push_cli: no ableton_sessions row with id {session_id!r}"
        )
    return session["song_id"]


def _cmd_phases(args: argparse.Namespace) -> int:
    conn = connect(_resolve_db_path(args))
    song_id = _resolve_song_id(conn, args.session_id)
    phases = push.plan_push_song(conn, song_id=song_id, session_id=args.session_id)
    out = {
        "song_id": song_id,
        "session_id": args.session_id,
        "phases": [
            {"name": p.name, "description": p.description} for p in phases
        ],
    }
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    conn = connect(_resolve_db_path(args))
    song_id = _resolve_song_id(conn, args.session_id)
    phases = push.plan_push_song(conn, song_id=song_id, session_id=args.session_id)
    chosen = next((p for p in phases if p.name == args.phase), None)
    if chosen is None:
        valid = ", ".join(p.name for p in phases)
        raise SystemExit(
            f"push_cli plan: unknown phase {args.phase!r}; valid: {valid}"
        )
    plan = chosen.plan_fn()
    out = plan.to_dict()
    out["song_id"] = song_id
    out["session_id"] = args.session_id
    out["phase"] = args.phase
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    results = json.loads(Path(args.results).read_text())
    if not isinstance(results, list):
        raise SystemExit(
            "push_cli apply: results file must be a JSON array of "
            "{key, ok, tool, result} dicts"
        )
    conn = connect(_resolve_db_path(args))

    # apply_push_results is void on success; raises on unknown key kinds.
    # Surface a tiny summary so the skill can report per-phase progress.
    applied = sum(1 for r in results if r.get("ok"))
    failed = [r for r in results if not r.get("ok")]
    push.apply_push_results(
        conn, results,
        session_id=args.session_id,
        actor="sync",
        reason=args.reason or f"push from session {args.session_id}",
    )
    out = {
        "applied": applied,
        "failed": len(failed),
        "details": [
            {"key": r.get("key"), "tool": r.get("tool"), "error": r.get("error")}
            for r in failed
        ],
    }
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_probe_and_link(args: argparse.Namespace) -> int:
    snapshot = json.loads(Path(args.snapshot).read_text())
    if not isinstance(snapshot, dict):
        raise SystemExit(
            "push_cli probe-and-link: snapshot file must be a JSON object "
            'with "tracks" and "returns" arrays'
        )
    live_tracks = snapshot.get("tracks") or []
    live_returns = snapshot.get("returns") or []
    if not isinstance(live_tracks, list) or not isinstance(live_returns, list):
        raise SystemExit(
            'push_cli probe-and-link: snapshot.tracks and snapshot.returns '
            "must be JSON arrays"
        )

    conn = connect(_resolve_db_path(args))
    song_id = _resolve_song_id(conn, args.session_id)
    result = push.probe_and_link(
        conn,
        song_id=song_id,
        session_id=args.session_id,
        live_tracks=live_tracks,
        live_returns=live_returns,
        actor="sync",
        reason=args.reason or f"probe-and-link from session {args.session_id}",
    )
    out = result.to_dict()
    out["song_id"] = song_id
    out["session_id"] = args.session_id
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _add_db_args(p: argparse.ArgumentParser) -> None:
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--song", help="song slug (resolves to songs/<slug>/<slug>.db)")
    group.add_argument("--db", help="explicit path to the SQLite DB (escape hatch)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hallucinote.sync.push_cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_phases = sub.add_parser("phases", help="emit the ten-phase metadata list")
    p_phases.add_argument("session_id", help="ableton_sessions.id (always explicit)")
    _add_db_args(p_phases)
    p_phases.set_defaults(func=_cmd_phases)

    p_plan = sub.add_parser("plan", help="emit one phase's PushPlan as JSON")
    p_plan.add_argument("phase", help="phase name (e.g. tempo_map, tracks, clips)")
    p_plan.add_argument("session_id", help="ableton_sessions.id (always explicit)")
    _add_db_args(p_plan)
    p_plan.set_defaults(func=_cmd_plan)

    p_apply = sub.add_parser("apply", help="apply MCP results to the DB")
    p_apply.add_argument("session_id", help="ableton_sessions.id (always explicit)")
    _add_db_args(p_apply)
    p_apply.add_argument("--results", required=True,
                         help="path to the results JSON the skill assembled")
    p_apply.add_argument("--reason", default=None,
                         help="optional reason annotation for emitted events")
    p_apply.set_defaults(func=_cmd_apply)

    p_pl = sub.add_parser(
        "probe-and-link",
        help="match Live tracks/returns by name → write ableton_links",
    )
    p_pl.add_argument("session_id", help="ableton_sessions.id (always explicit)")
    _add_db_args(p_pl)
    p_pl.add_argument("--snapshot", required=True,
                      help="path to {tracks: [...], returns: [...]} JSON")
    p_pl.add_argument("--reason", default=None,
                      help="optional reason annotation for emitted link events")
    p_pl.set_defaults(func=_cmd_probe_and_link)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
