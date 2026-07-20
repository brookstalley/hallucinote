"""CLI bridge between the `/ableton-pull` skill and the pure Python pull layer.

Three subcommands:

    pull_cli plan <domain> [session_id] (--song SLUG | --db PATH)
        -> emit a PullPlan as JSON to stdout

    pull_cli apply [session_id] (--song SLUG | --db PATH) --plan P --results R
        -> diff results against the DB, write mutations, print an
           ApplyResult summary as JSON

    pull_cli execute <domain> [session_id] (--song SLUG | --db PATH)
        -> plan + probe in-process via MCP + apply, all in one shot. Arc 3 / C3:
           the "bake mix-time tweaks" workflow asks for one command, not the
           two-step plan→file→apply dance the skill historically drove.

The `plan` / `apply` pair stays pure-Python — the skill orchestrates MCP probes
between the two and writes intermediate files. `execute` is the one place MCP
imports enter this module (lazy, via :func:`_resolve_send_fn`, mirroring the
same seam ``compat.py`` and ``push_cli.py`` use); ``plan``/``apply`` are
unaffected and remain MCP-free.

DB resolution is prescriptive: `--song <slug>` resolves to the canonical path
`songs/<slug>/<slug>.db`. The `--db PATH` escape hatch exists for tests and
non-standard layouts. Exactly one is required. `session_id` may be
omitted (WFL-7Q2N): the only / most-recent session in the DB is
auto-selected and echoed on stderr.

`domain` is one of:
  - `mix-state`         — track + return + master mixer state + sends
                          (also free-ride ingests global tempo + signature)
  - `score-globals`     — global tempo + signature only (bar-1 rows in each map)
  - `cue-points`        — arrangement cue point positions (names gap-flagged)
  - `devices`           — top-level device chain on each linked track + return
                          (positional kind/display_name diff). Nested rack
                          chains are a separate domain (`nested-rack-chains`);
                          per-device parameters are `device-parameters`.
  - `nested-rack-chains` — one level of nested chains per rack device (W7-B).
                          Iterates DB rack rows; emits one
                          `get_device_chains` probe each. Requires `devices`
                          to have run first to populate top-level device rows.
  - `arrangement-clips` — per-track arrangement-clip placements (start/end
                          bars). Ableton-only placements warn (V1 cannot
                          auto-create a `clips` row); name diffs not detected
                          (no `name` column on `arrangement_clips` — names
                          live on `clips.name`).
  - `session-clips`     — per-track session-view clip-slot contents
                          (slot, name, length). Ableton-only slots warn
                          (same V1 limit as arrangement-clips). Note
                          content drift is NOT detected here — use
                          `clip-notes` for that.
  - `clip-notes`        — per-clip note pull (gap #4 partial). Emits
                          one `ableton_note(action='list')` per linked
                          clip, content-diffs against DB notes
                          (matched by pitch + start + duration within
                          1/1000 of a beat). Velocity / mute drift
                          updates DB notes in place (UUID preserved);
                          new notes insert; missing notes delete. A
                          note whose pitch/start/duration moves
                          surfaces as delete + insert (UUID rotates).

All round-trip domains land here as of W7-B. (Earlier waves staged
envelopes / device-parameters / nested-rack-chains behind MCP gaps; those
are now reachable through the unified surface.)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.db.connection import resolve_db_path, transaction
from hallucinote.sync import pull
from hallucinote.sync.session_resolve import resolve_session_id


class _DryRunRollback(Exception):
    """Internal sentinel — raised inside ``transaction(conn)`` to force a
    rollback after the diff has been computed for ``--dry-run`` mode.
    Never propagates past ``_cmd_execute``."""


def _warn_durability_if_mix_layer(conn, *, request_id: str, prog: str) -> None:
    """Print the BAK-7D2V durability contract to stderr iff this pull apply
    staged mix-layer state the next ``build.py`` replay would revert.

    Fires on exactly the EVENT KINDS that arm the replay guard: it reuses the
    guard's own kind set via
    :func:`capture.count_request_replay_asserted_events` (same
    ``requests.kind='pull'`` provenance), so a pull whose mutations replay
    never re-asserts (clip-notes, envelopes, tempo/cue, arrangement, tuning)
    stays quiet, and a zero-change apply stays quiet.

    Kinds, not domains — and ``score-globals`` is why that distinction is load
    bearing. Its probe is ``ableton_session(action='info')``, which also
    ingests master volume/pan as a ride-along; that path calls
    ``M.set_track_mixer`` and emits ``track_mixer_set``, which IS in the
    guard's kind set. So a "tempo-only" pull DOES arm the guard whenever the
    master fader or pan drifted. Counting emitted events rather than
    classifying the requested domain is what keeps this correct.

    Kind parity, not outcome parity: what the guard then DOES with those events
    depends on the snapshot, so the notice text is careful to say the refusal is
    conditional on a usable ``captured_at`` (an unstamped legacy snapshot leaves
    replay no ordering evidence, so it warns and still reverts). Written to
    stderr so it never pollutes the JSON report on stdout that wrappers parse."""
    from hallucinote.capture import count_request_replay_asserted_events

    n = count_request_replay_asserted_events(conn, request_id=request_id)
    if n <= 0:
        return
    sys.stderr.write(
        f"{prog}: {n} mix-layer change(s) staged in the DB (regenerable) only "
        "— NOT yet durable. If the song's snapshot carries a `captured_at` "
        "stamp, the next `build.py` replay will REFUSE to run "
        "(StaleSnapshotError) rather than silently revert them; a legacy "
        "snapshot with no stamp gives no ordering evidence, so replay only "
        "WARNS and reverts them. Either way, bake them into the durable "
        "snapshot with `/song-snapshot` (or `capture_cli execute` + copy the "
        ".refresh.json over captured_session.json) before the next build.\n"
    )


_DOMAINS = {
    "mix-state":          pull.plan_pull_mix,
    "score-globals":      pull.plan_pull_score_globals,
    "cue-points":         pull.plan_pull_cue_points,
    "devices":            pull.plan_pull_devices,
    "nested-rack-chains": pull.plan_pull_nested_rack_chains,
    "device-parameters":  pull.plan_pull_device_parameters,
    "device-sidechain":   pull.plan_pull_device_sidechain,
    "arrangement-clips":  pull.plan_pull_arrangement_clips,
    "session-clips":      pull.plan_pull_session_clips,
    "clip-notes":         pull.plan_pull_notes_for_clips,
    "envelopes":          pull.plan_pull_envelopes,
}


def _resolve_db_path(args: argparse.Namespace) -> Path:
    """``--song <slug>`` → per-branch DB via resolve_db_path; ``--db PATH`` → PATH.

    Mirrors push_cli + build.py so push and pull agree on the same DB: the song
    dir is resolved via the project-root contract (env / ``hallucinote.toml``
    marker / legacy ``songs/<slug>``; see ``hallucinote.workspace``) so a song
    in its own repo resolves correctly, then W12-A per-branch naming applies,
    falling back to the legacy bare ``<slug>.db`` in the same dir.
    """
    if args.db:
        path = Path(args.db)
    else:
        path = resolve_db_path(args.song)
        # Legacy fallback: pre-W12-A songs not yet rebuilt under the per-branch
        # convention keep a bare <slug>.db in the same (resolved) song dir.
        if not path.exists():
            legacy = resolve_db_path(args.song, branch=None)
            if legacy.exists():
                path = legacy
    if not path.exists():
        raise SystemExit(
            f"pull_cli: DB not found at {path} — run "
            f"`python songs/{args.song}/build.py` first to populate it."
        )
    return path


def _open_db(args: argparse.Namespace) -> sqlite3.Connection:
    """Open the song DB through ``init_db`` so an older on-disk DB is migrated to
    the current schema before any read/sync runs.

    Mirrors ``push_cli._open_db``: bare ``connect()`` skips the additive-column
    migration (``_ensure_added_columns`` lives only in ``init_db``), so a DB built
    by an earlier release reads raw and the first planner to touch a newer column
    crashes with sqlite3's ``IndexError: No item with that key``. ``init_db`` is
    idempotent and safe on existing DBs, so opening through it self-heals across
    schema-adding upgrades.
    """
    return init_db(_resolve_db_path(args))


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
    conn = _open_db(args)
    args.session_id = resolve_session_id(
        conn, args.session_id, prog="pull_cli plan",
    )
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

    conn = _open_db(args)
    args.session_id = resolve_session_id(
        conn, args.session_id, prog="pull_cli apply",
        plan_session_id=plan_dict.get("session_id"),
    )
    # song_id is on the plan; fall back to resolving from session if absent
    # (older plan files without the field).
    song_id = plan_dict.get("song_id") or _resolve_song_id(conn, args.session_id)

    # W23-C: every pull-apply is one attributed request. Closes 'ok' on
    # success; the apply layer's own try/except boundary catches errors that
    # would otherwise leave the request open — exceptions propagate after we
    # mark the request failed so the test/CLI signal isn't swallowed.
    domain = plan_dict.get("domain") or "unknown"
    request_id = M.create_request(
        conn,
        actor="sync",
        intent=f"pull_cli apply domain={domain} session={args.session_id}",
        kind="pull",
        payload={"domain": domain, "session_id": args.session_id, "song_id": song_id},
        song_id=song_id,
        reason=args.reason,
        metadata=M.provenance_metadata(
            extra={
                "driver": "pull_cli",
                "session_id": args.session_id,
                "domain": domain,
            },
        ),
    )
    try:
        out = pull.apply_pull_results(
            conn,
            results,
            song_id=song_id,
            session_id=args.session_id,
            actor="sync",
            request_id=request_id,
            reason=args.reason or f"pull from session {args.session_id}",
        )
    except Exception:  # prawduct:ok-broad-except — audit-log finalizer: close the request with outcome='failed' for any exception, then re-raise.
        M.close_request(conn, request_id=request_id, outcome="failed", actor="sync")
        raise
    M.close_request(conn, request_id=request_id, outcome="ok", actor="sync")
    json.dump(out.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    _warn_durability_if_mix_layer(conn, request_id=request_id, prog="pull_cli apply")
    # PULL-DRIFT-DETECT: same fail-loud guard as `execute` — unreadable probes
    # mean drift could not be determined, so don't let exit 0 read as "in sync".
    if out.unreadable > 0:
        sys.stderr.write(
            f"pull_cli apply: {out.unreadable} probe result(s) UNREADABLE "
            "(ok=False or missing payload) — pulled state is incomplete; do NOT "
            "treat this as fully in sync.\n"
        )
        return 2
    return 0


def _resolve_send_fn():
    """Lazy resolver for ``hallucinote_mcp.client.send``.

    Mirrors :func:`hallucinote.sync.push_cli._resolve_send_fn` and
    :func:`hallucinote.sync.compat._resolve_send_fn`. Tests inject a
    fake via ``monkeypatch.setattr(pull_cli, "_resolve_send_fn",
    lambda: fake_send)``. Keeps the module importable when
    ``hallucinote_mcp`` isn't installed — only the new ``execute``
    subcommand exercises this path; ``plan``/``apply`` are MCP-free.
    """
    from hallucinote_mcp import client as _client  # type: ignore[import-not-found]
    return _client.send


def _execute_plan_via_mcp(
    plan: pull.PullPlan,
    *,
    send_fn=None,
) -> list[dict]:
    """Issue every :class:`pull.PullCall` in ``plan`` against the running
    Hallucinote MCP and collect results in the shape
    :func:`pull.apply_pull_results` expects:
    ``[{key, ok, tool, result, error?}, ...]``.

    The ``args`` dict on each PullCall carries ``action`` + the
    action-specific params; the wire shape is
    ``Request(tool, action, params)``, so we split here. Failed probes
    (``ok=False``) are passed through with their error string — the
    apply layer is the source of truth for per-key warnings, matching
    the contract :func:`pull.apply_pull_results` documents. This
    function never raises on tool-side errors.
    """
    if send_fn is None:
        send_fn = _resolve_send_fn()
    from hallucinote_mcp.wire import Request  # type: ignore[import-not-found]

    out: list[dict] = []
    for call in plan.calls:
        args = dict(call.args)
        action = args.pop("action", None)
        resp = send_fn(Request(
            tool=call.tool, action=str(action), params=args,
        ))
        ok = bool(getattr(resp, "ok", False))
        record: dict = {"key": call.key, "ok": ok, "tool": call.tool}
        if ok:
            record["result"] = getattr(resp, "result", None) or {}
        else:
            record["result"] = None
            record["error"] = getattr(resp, "error", "unknown error")
        out.append(record)
    return out


def _cmd_execute(args: argparse.Namespace) -> int:
    """plan + probe + apply in one in-process pass — the C3 entry point.

    The historical two-step `plan → write file → execute probes via skill
    → write file → apply` dance is fine for offline scripting but heavy
    for the common case ("I tweaked a few knobs in Live; bake them so the
    next push doesn't overwrite my work"). This subcommand collapses it.

    ``--dry-run`` wraps the request + apply in a SAVEPOINT that always
    rolls back, so the caller sees what WOULD change without committing.
    The output JSON's ``applied`` block reflects the diff that was
    computed; ``dry_run`` is echoed so a wrapper (e.g. the ``/ableton-pull``
    skill) can confirm the run was preview-only before promoting to a real apply.
    """
    if args.domain not in _DOMAINS:
        raise SystemExit(
            f"pull_cli execute: unknown domain {args.domain!r}; "
            f"known: {sorted(_DOMAINS)}"
        )
    conn = _open_db(args)
    args.session_id = resolve_session_id(
        conn, args.session_id, prog="pull_cli execute",
    )
    song_id = _resolve_song_id(conn, args.session_id)
    planner = _DOMAINS[args.domain]
    plan = planner(conn, song_id=song_id, session_id=args.session_id)
    results = _execute_plan_via_mcp(plan)

    def _open_apply_close() -> tuple[str, "pull.ApplyResult"]:
        request_id = M.create_request(
            conn,
            actor="sync",
            intent=(
                f"pull_cli execute domain={args.domain} "
                f"session={args.session_id}"
                + (" (dry-run)" if args.dry_run else "")
            ),
            kind="pull",
            payload={
                "domain": args.domain,
                "session_id": args.session_id,
                "song_id": song_id,
                "dry_run": args.dry_run,
            },
            song_id=song_id,
            reason=args.reason,
            metadata=M.provenance_metadata(
                extra={
                    "driver": "pull_cli.execute",
                    "session_id": args.session_id,
                    "domain": args.domain,
                    "dry_run": args.dry_run,
                },
            ),
        )
        try:
            applied_inner = pull.apply_pull_results(
                conn, results,
                song_id=song_id, session_id=args.session_id,
                actor="sync", request_id=request_id,
                reason=args.reason or f"pull from session {args.session_id}",
            )
        except Exception:  # prawduct:ok-broad-except — audit-log finalizer: close the request with outcome='failed' for any exception, then re-raise.
            M.close_request(conn, request_id=request_id, outcome="failed", actor="sync")
            raise
        M.close_request(conn, request_id=request_id, outcome="ok", actor="sync")
        return request_id, applied_inner

    if args.dry_run:
        # Open an outer transaction whose unconditional rollback covers the
        # request row, the apply mutations, and the close-request update.
        # The diff still surfaces via `applied` (computed before rollback).
        holder: list[tuple[str, "pull.ApplyResult"]] = []
        try:
            with transaction(conn):
                holder.append(_open_apply_close())
                raise _DryRunRollback
        except _DryRunRollback:
            pass
        request_id, applied = holder[0]
    else:
        request_id, applied = _open_apply_close()

    out = {
        "domain": args.domain,
        "song_id": song_id,
        "session_id": args.session_id,
        "dry_run": args.dry_run,
        "plan": plan.to_dict(),
        "applied": applied.to_dict(),
    }
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    # A dry-run rolled the request + its events back, so nothing was staged —
    # the durability contract only applies to a real apply.
    if not args.dry_run:
        _warn_durability_if_mix_layer(
            conn, request_id=request_id, prog=f"pull_cli execute domain={args.domain}",
        )
    # PULL-DRIFT-DETECT: probes that couldn't be read mean we could NOT
    # determine drift — exit non-zero so a wrapper (the /ableton-pull skill)
    # never mistakes an unreadable run for
    # "0 changes / in sync". The JSON report still prints (with `unreadable` and
    # per-probe warnings) so the caller sees exactly what failed.
    if applied.unreadable > 0:
        sys.stderr.write(
            f"pull_cli execute domain={args.domain}: {applied.unreadable} probe(s) "
            "UNREADABLE — drift could not be determined (likely a Live/Remote-"
            "Script version mismatch). Do NOT treat this as 'in sync'.\n"
        )
        return 2
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
    p_plan.add_argument("session_id", nargs="?", default=None,
                   help="ableton_sessions.id (omit to auto-select the "
                        "only/most-recent session in the DB; WFL-7Q2N)")
    _add_db_args(p_plan)
    p_plan.set_defaults(func=_cmd_plan)

    p_apply = sub.add_parser("apply", help="apply MCP probe results to the DB")
    p_apply.add_argument("session_id", nargs="?", default=None,
                   help="ableton_sessions.id (omit to auto-select the "
                        "only/most-recent session in the DB; WFL-7Q2N)")
    _add_db_args(p_apply)
    p_apply.add_argument("--plan", required=True,
                         help="path to the plan JSON emitted by `plan`")
    p_apply.add_argument("--results", required=True,
                         help="path to the results JSON the skill assembled")
    p_apply.add_argument("--reason", default=None,
                         help="optional reason annotation for emitted events")
    p_apply.set_defaults(func=_cmd_apply)

    p_exec = sub.add_parser(
        "execute",
        help=(
            "plan + probe + apply in one in-process pass (Arc 3 / C3). "
            "Same outcome as `plan` → run probes → `apply` but without the "
            "intermediate plan/results files. Requires hallucinote_mcp and "
            "a running Hallucinote bridge."
        ),
    )
    p_exec.add_argument("domain", help="e.g. device-parameters")
    p_exec.add_argument("session_id", nargs="?", default=None,
                   help="ableton_sessions.id (omit to auto-select the "
                        "only/most-recent session in the DB; WFL-7Q2N)")
    _add_db_args(p_exec)
    p_exec.add_argument("--reason", default=None,
                        help="optional reason annotation for emitted events")
    p_exec.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help=(
            "Compute diffs and run apply inside a SAVEPOINT that always "
            "rolls back. The output JSON reports what WOULD change; the "
            "DB is byte-identical after the call. Used by the "
            "`/ableton-pull` skill to preview before committing."
        ),
    )
    p_exec.set_defaults(func=_cmd_execute)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
