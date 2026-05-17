"""CLI bridge between the `/ableton-pull` skill and the pure Python pull layer.

Two subcommands:

    pull_cli plan <domain> <session_id> (--song SLUG | --db PATH)
        -> emit a PullPlan as JSON to stdout

    pull_cli apply <session_id> (--song SLUG | --db PATH) --plan P --results R
        -> diff results against the DB, write mutations, print an
           ApplyResult summary as JSON

The skill orchestrates: runs `plan`, executes each MCP probe in the returned
plan, assembles a `results` JSON file, runs `apply`. All MCP work lives in
the skill; Python stays pure (no MCP imports in this module).

DB resolution is prescriptive: `--song <slug>` resolves to the canonical path
`songs/<slug>/<slug>.db`. The `--db PATH` escape hatch exists for tests and
non-standard layouts. Exactly one is required.

`domain` is one of:
  - `mix-state`     — track + return + master mixer state + sends
                      (also free-ride ingests global tempo + signature)
  - `score-globals` — global tempo + signature only (bar-1 rows in each map)
  - `cue-points`    — arrangement cue point positions (names gap-flagged)
  - `devices`       — top-level device chain on each linked track + return
                      (positional kind/display_name diff; nested rack
                      chains and per-device parameters are gap-blocked)

Future chunks add `arrangement`. Note pull, envelope pull,
device-parameter pull, and nested rack pull are MCP-gap-blocked — they are
not domains here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hallucinote.db import queries as Q
from hallucinote.db.connection import connect
from hallucinote.sync import pull


_DOMAINS = {
    "mix-state":     pull.plan_pull_mix,
    "score-globals": pull.plan_pull_score_globals,
    "cue-points":    pull.plan_pull_cue_points,
    "devices":       pull.plan_pull_devices,
}


def _resolve_db_path(args: argparse.Namespace) -> Path:
    """`--song <slug>` -> `songs/<slug>/<slug>.db`; `--db PATH` -> PATH.

    Project convention: one SQLite DB per song at `songs/<slug>/<slug>.db`.
    See `.prawduct/artifacts/project-preferences.md`.
    """
    if args.db:
        path = Path(args.db)
    else:
        path = Path("songs") / args.song / f"{args.song}.db"
    if not path.exists():
        raise SystemExit(
            f"pull_cli: DB not found at {path} — "
            "songs convention is one DB per song at songs/<slug>/<slug>.db"
        )
    return path


def _resolve_song_id(conn, session_id: str) -> str:
    session = Q.get_ableton_session(conn, session_id)
    if session is None:
        raise SystemExit(
            f"pull_cli: no ableton_sessions row with id {session_id!r}"
        )
    return session["song_id"]


def _cmd_plan(args: argparse.Namespace) -> int:
    if args.domain not in _DOMAINS:
        raise SystemExit(
            f"pull_cli: unknown domain {args.domain!r}; "
            f"known: {sorted(_DOMAINS)}"
        )
    conn = connect(_resolve_db_path(args))
    song_id = _resolve_song_id(conn, args.session_id)
    planner = _DOMAINS[args.domain]
    plan = planner(conn, song_id=song_id, session_id=args.session_id)
    out = plan.to_dict()
    out["song_id"] = song_id
    out["session_id"] = args.session_id
    out["domain"] = args.domain
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    plan_dict = json.loads(Path(args.plan).read_text())
    results = json.loads(Path(args.results).read_text())
    if not isinstance(results, list):
        raise SystemExit(
            "pull_cli apply: results file must be a JSON array of "
            "{key, ok, tool, result} dicts"
        )

    conn = connect(_resolve_db_path(args))
    # song_id is on the plan; fall back to resolving from session if absent
    # (older plan files without the field).
    song_id = plan_dict.get("song_id") or _resolve_song_id(conn, args.session_id)

    out = pull.apply_pull_results(
        conn,
        results,
        song_id=song_id,
        session_id=args.session_id,
        actor="sync",
        reason=args.reason or f"pull from session {args.session_id}",
    )
    json.dump(out.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _add_db_args(p: argparse.ArgumentParser) -> None:
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--song", help="song slug (resolves to songs/<slug>/<slug>.db)")
    group.add_argument("--db", help="explicit path to the SQLite DB (escape hatch)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hallucinote.sync.pull_cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="emit a PullPlan as JSON")
    p_plan.add_argument("domain", help="e.g. mix-state")
    p_plan.add_argument("session_id", help="ableton_sessions.id (always explicit)")
    _add_db_args(p_plan)
    p_plan.set_defaults(func=_cmd_plan)

    p_apply = sub.add_parser("apply", help="apply MCP probe results to the DB")
    p_apply.add_argument("session_id", help="ableton_sessions.id (always explicit)")
    _add_db_args(p_apply)
    p_apply.add_argument("--plan", required=True,
                         help="path to the plan JSON emitted by `plan`")
    p_apply.add_argument("--results", required=True,
                         help="path to the results JSON the skill assembled")
    p_apply.add_argument("--reason", default=None,
                         help="optional reason annotation for emitted events")
    p_apply.set_defaults(func=_cmd_apply)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
