"""CLI bridge between the ``/ableton-push`` skill and the pure Python push layer.

Mirror of :mod:`hallucinote.sync.pull_cli`. The push side has a more
elaborate flow because :func:`push.plan_push_song` returns thirteen ordered
phases (vs. pull's flat domain set), and probe-and-link runs before
the phases to bind any Live tracks/returns that already match DB rows.

Subcommands:

    push_cli phases [session_id] (--song SLUG | --db PATH)
        -> emit {"phases": [{"name", "description"}, ...]} for the skill
           to enumerate. The push skill drives them in order.

    push_cli plan <phase> [session_id] (--song SLUG | --db PATH)
        -> emit one phase's PushPlan as JSON (same shape as pull_cli's
           plan output).

    push_cli apply [session_id] (--song SLUG | --db PATH) --results R [--plan P]
        -> read the results array, call apply_push_results, emit a
           {"applied", "failed", "details"} summary.
           W10-E: results may use the MINIMAL format (list of {ok, result}
           in plan order, no per-entry key/tool); pass --plan to point at
           the original plan.json so keys + tools get re-derived. The legacy
           full format ({key, ok, tool, result}) still works without --plan.

    push_cli probe-and-link [session_id] (--song SLUG | --db PATH) (--probe | --snapshot S)
        -> probe Live for {"tracks": [...], "returns": [...]} (default via
           ``--probe``: in-process MCP TCP call; W18-B canonical path with no
           tmp-file staleness risk), or accept a pre-probed snapshot via
           ``--snapshot`` (test/debug fallback). Match by name, write
           ableton_links for matches, strict-reconcile any link whose
           ableton_index no longer matches the fresh probe, emit a
           ProbeAndLinkResult JSON. Re-runnable.

    push_cli execute [session_id] (--song SLUG | --db PATH) [--state-dir D]
        -> W10-E2: dispatches the full thirteen-phase push directly against
           Live's Remote Script via :mod:`hallucinote_mcp.client`,
           bypassing the agent's tool-use channel. Writes
           ``.last-push-state.json`` (always) + ``.last-push-errors.json``
           (on failure) into ``--state-dir`` (default: DB directory).
           Canonical path for full-song pushes; the per-phase
           ``phases`` / ``plan`` / ``apply`` triplet stays available
           for development, debugging, and interactive iteration.

The default agent flow (full-song push) is probe-and-link → execute → read
state file. ``execute`` is in-process Python that talks to Live's Remote
Script directly; the historical per-phase agent loop is preserved as a
debugging path. DB resolution mirrors :mod:`pull_cli`: ``--song <slug>``
resolves via :func:`hallucinote.db.resolve_db_path` (per-branch path under
W12-A; legacy ``songs/<slug>/<slug>.db`` fallback outside a repo / on
detached HEAD); ``--db PATH`` is the escape hatch. ``session_id`` may be
omitted on every subcommand (WFL-7Q2N): the only / most-recent session in
the DB is auto-selected and echoed on stderr (apply prefers the plan
file's embedded session); multi-song DBs refuse to guess.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from hallucinote.db import init_db, mutations as M, queries as Q, resolve_db_path
from hallucinote.sync import push, push_execute, push_notes
from hallucinote.sync.session_resolve import resolve_session_id


def _resolve_send_fn():
    """Lazy resolver for ``hallucinote_mcp.client.send``.

    Pulled out into a module-level function so tests can
    ``monkeypatch.setattr(push_cli, "_resolve_send_fn", ...)`` to inject
    a fake. Patching the in-function ``from hallucinote_mcp import client``
    form via ``sys.modules`` is brittle: once the real submodule has been
    imported anywhere, ``hallucinote_mcp`` already holds a bound
    ``client`` attribute that a ``sys.modules`` replacement doesn't reach.
    A module-level seam sidesteps that entirely.
    """
    from hallucinote_mcp import client as _client  # type: ignore[import-not-found]
    return _client.send


def _probe_live_via_mcp(
    send_fn=None,
) -> tuple[list[dict], list[dict]]:
    """W18-B: probe Live's tracks + returns directly via the MCP TCP client.

    Returns ``(live_tracks, live_returns)`` shaped exactly like the legacy
    ``--snapshot`` JSON ({track_index, name, kind} / {return_index, name}).
    Same dispatch path as :func:`push_execute.execute_push` — reuses
    ``hallucinote_mcp.client.send`` so probe-and-link no longer relies on the
    agent maintaining ``/tmp/ableton-push-snapshot.json`` between invocations.

    ``send_fn`` injection is for tests; the real path resolves the MCP
    client lazily so import of this module doesn't require ``hallucinote_mcp``
    to be installed (mirrors :func:`push_execute.execute_push`).
    """
    if send_fn is None:
        from hallucinote_mcp import client as _client  # type: ignore[import-not-found]
        send_fn = _client.send
    from hallucinote_mcp.wire import Request  # type: ignore[import-not-found]

    track_resp = send_fn(Request(tool="ableton_track", action="list", params={}))
    if not getattr(track_resp, "ok", False):
        raise SystemExit(
            "push_cli --probe: ableton_track(list) failed — "
            f"{getattr(track_resp, 'error', 'unknown error')}"
        )
    return_resp = send_fn(Request(tool="ableton_return", action="list", params={}))
    if not getattr(return_resp, "ok", False):
        raise SystemExit(
            "push_cli --probe: ableton_return(list) failed — "
            f"{getattr(return_resp, 'error', 'unknown error')}"
        )
    track_payload = getattr(track_resp, "result", None) or {}
    return_payload = getattr(return_resp, "result", None) or {}
    live_tracks = list(track_payload.get("tracks") or [])
    live_returns = list(return_payload.get("returns") or [])
    return live_tracks, live_returns


def _probe_live_devices_via_mcp(
    *,
    live_tracks: list[dict],
    live_returns: list[dict],
    send_fn=None,
) -> dict[tuple[str, int], list[dict]]:
    """W20-A: probe ``ableton_device(action='list')`` per Live track + return
    so probe-and-link can bind DB devices to existing Live device-chain slots
    by ``(parent, position, class_name)`` — closing the re-push device
    duplication path.

    Returns a dict keyed by ``("track", track_index)`` / ``("return",
    return_index)`` with values shaped like the device handler's list output
    (``{device_index, name, class_name}``). Empty list when Live's chain is
    empty. Errors per parent fall back to "no devices known" — a transient
    failure on one parent shouldn't refuse the whole probe.

    Issues ``1 + len(tracks) + len(returns)`` calls (one each for the two
    list probes the caller already ran, plus N + M per-parent device list
    probes); cheap in practice and the existing ``execute`` path's per-call
    cost is the same shape.
    """
    if send_fn is None:
        from hallucinote_mcp import client as _client  # type: ignore[import-not-found]
        send_fn = _client.send
    from hallucinote_mcp.wire import Request  # type: ignore[import-not-found]

    by_parent: dict[tuple[str, int], list[dict]] = {}
    for t in live_tracks:
        idx = t["track_index"]
        resp = send_fn(Request(
            tool="ableton_device", action="list",
            params={"track_index": idx},
        ))
        if getattr(resp, "ok", False):
            payload = getattr(resp, "result", None) or {}
            by_parent[("track", idx)] = list(payload.get("devices") or [])
    for r in live_returns:
        idx = r["return_index"]
        resp = send_fn(Request(
            tool="ableton_device", action="list",
            params={"return_index": idx},
        ))
        if getattr(resp, "ok", False):
            payload = getattr(resp, "result", None) or {}
            by_parent[("return", idx)] = list(payload.get("devices") or [])
    return by_parent


def _probe_live_session_clips_via_mcp(
    *,
    live_tracks: list[dict],
    send_fn=None,
) -> dict[int, list[dict]]:
    """Probe ``ableton_clip(action='list', location='session')`` per Live track.

    Returns a dict keyed by ``track_index`` with the POPULATED session clips
    (``{clip_index, name, ...}`` — empty slots dropped) for clip-prune (B1b) to
    reconcile against the DB. A per-track probe failure falls back to "no clips
    known" for that track (it simply won't surface orphans there) rather than
    aborting the whole prune.
    """
    if send_fn is None:
        from hallucinote_mcp import client as _client  # type: ignore[import-not-found]
        send_fn = _client.send
    from hallucinote_mcp.wire import Request  # type: ignore[import-not-found]

    by_track: dict[int, list[dict]] = {}
    for t in live_tracks:
        idx = t["track_index"]
        resp = send_fn(Request(
            tool="ableton_clip", action="list",
            params={"track_index": idx, "location": "session"},
        ))
        if getattr(resp, "ok", False):
            payload = getattr(resp, "result", None) or {}
            clips = payload.get("clips") or []
            by_track[idx] = [c for c in clips if not c.get("empty")]
    return by_track


def _resolve_db_path(args: argparse.Namespace) -> Path:
    """``--song <slug>`` → per-branch DB via resolve_db_path; ``--db PATH`` → PATH.

    W12-A: resolves to ``songs/<slug>/<slug>-<branch>.db`` inside a repo,
    falling back to legacy ``songs/<slug>/<slug>.db`` outside a repo / on
    detached HEAD. If both exist, the per-branch form wins (matches build.py).
    """
    if args.db:
        path = Path(args.db)
    else:
        path = resolve_db_path(args.song)
        # Legacy-fallback: if the per-branch DB doesn't exist but the legacy
        # <slug>.db does, use that (pre-W12-A songs not yet rebuilt under
        # the new convention). This is purely transitional.
        if not path.exists():
            legacy = resolve_db_path(args.song, branch=None)  # bare <slug>.db, same song dir
            if legacy.exists():
                path = legacy
    if not path.exists():
        raise SystemExit(
            f"push_cli: DB not found at {path} — run `python songs/{args.song}/build.py` "
            "first to populate it."
        )
    return path


def _open_db(args: argparse.Namespace) -> sqlite3.Connection:
    """Open the song DB through ``init_db`` so an older on-disk DB is migrated to
    the current schema before any read/sync runs.

    The sync CLIs historically opened with bare ``connect()``, which never runs
    the additive-column migration — ``_ensure_added_columns`` lives only inside
    ``init_db``. A song DB built by an earlier release (e.g. one predating the
    RTE-1K9T track-routing columns) was then read raw, and the first planner to
    touch a newer column crashed with sqlite3's ``IndexError: No item with that
    key``. ``init_db`` is idempotent and safe on existing DBs — ``run_build``
    opens every existing song this way — so routing all sync-CLI opens through it
    makes the tool self-heal across schema-adding upgrades. See ``_ADDED_COLUMNS``
    in ``db/connection.py``.
    """
    return init_db(_resolve_db_path(args))


def _resolve_song_id(conn, session_id: str) -> str:
    session = Q.get_ableton_session(conn, session_id)
    if session is None:
        raise SystemExit(
            f"push_cli: no ableton_sessions row with id {session_id!r}"
        )
    return session["song_id"]


def _session_for(conn, args: argparse.Namespace, *, subcmd: str) -> str:
    """WFL-7Q2N: resolve the positional session_id, auto-discovering from the
    DB (echoed on stderr) when omitted. Mutates ``args.session_id`` so the
    rest of the command reads the resolved id."""
    args.session_id = resolve_session_id(
        conn, args.session_id, prog=f"push_cli {subcmd}",
    )
    return args.session_id


def _cmd_phases(args: argparse.Namespace) -> int:
    conn = _open_db(args)
    _session_for(conn, args, subcmd="phases")
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
    conn = _open_db(args)
    _session_for(conn, args, subcmd="plan")
    song_id = _resolve_song_id(conn, args.session_id)
    phases = push.plan_push_song(
        conn, song_id=song_id, session_id=args.session_id,
        perform_slowdown_factor=args.perform_slowdown,
    )
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
            "{key, ok, tool, result} dicts OR a minimal-format array of "
            "{ok, result} dicts (use --plan to enrich)"
        )
    conn = _open_db(args)
    # When --plan is passed, its embedded session_id is authoritative for an
    # omitted positional id (and a conflicting explicit id is refused) — the
    # plan was produced against that session.
    plan_doc: dict | None = None
    if args.plan:
        plan_doc = json.loads(Path(args.plan).read_text())
    args.session_id = resolve_session_id(
        conn, args.session_id, prog="push_cli apply",
        plan_session_id=(plan_doc or {}).get("session_id"),
    )

    # W10-E: support the minimal results format (positional {ok, result}
    # list, no per-entry key/tool). Agent assembles roughly half as much
    # JSON per call. Sniff: if NO entry carries 'key', look up the plan
    # via --plan <path> and zip by position. Legacy format still accepted.
    # Mixed-format input is rejected explicitly (rather than silently
    # falling back to one path) — the inconsistency almost certainly
    # signals an authoring bug worth surfacing.
    if results:
        keyed_count = sum(1 for r in results if "key" in r)
        if 0 < keyed_count < len(results):
            raise SystemExit(
                f"push_cli apply: mixed result formats — {keyed_count}/"
                f"{len(results)} entries carry 'key', the rest don't. Use "
                "ONE format throughout: legacy ({key, ok, tool, result}) OR "
                "minimal ({ok, result}, then pass --plan)."
            )
        if keyed_count == 0:
            if not args.plan:
                raise SystemExit(
                    "push_cli apply: minimal results format requires --plan "
                    "<path> (the same plan.json that produced the results) "
                    "so keys + tools can be re-derived. Pass --plan or fall "
                    "back to legacy {key, ok, tool, result} entries."
                )
            calls = (plan_doc or {}).get("calls") or []
            if len(results) != len(calls):
                raise SystemExit(
                    f"push_cli apply: minimal results length {len(results)} "
                    f"doesn't match plan calls length {len(calls)} — re-run "
                    f"plan + execute, or fall back to legacy format."
                )
            results = [
                {**r, "key": c.get("key"), "tool": c.get("tool")}
                for r, c in zip(results, calls)
            ]
        elif args.plan is not None:
            # Legacy format with --plan also passed: silently ignoring would
            # let the user think --plan is doing something. Warn loudly.
            print(
                "push_cli apply: --plan is ignored when results carry their "
                "own 'key' (legacy format). Drop --plan or convert to minimal "
                "format ({ok, result} per entry).",
                file=sys.stderr,
            )

    # apply_push_results raises on unknown key kinds and returns apply-layer
    # warnings (e.g. an unverified perform that recorded no fingerprint).
    # Surface a tiny summary so the skill can report per-phase progress.
    applied = sum(1 for r in results if r.get("ok"))
    failed = [r for r in results if not r.get("ok")]
    apply_warnings = push.apply_push_results(
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
        "apply_warnings": apply_warnings,
    }
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_probe_and_link(args: argparse.Namespace) -> int:
    if not args.song and not args.db:
        raise SystemExit(
            "push_cli probe-and-link: need --song <slug> or --db <path>"
        )
    # W18-B: --probe (canonical) probes Live in-process; --snapshot (fallback)
    # reads a pre-probed JSON file. The argparse mutex makes exactly one
    # active; require one explicitly so a forgotten flag isn't silently a
    # stale-snapshot read.
    # W20-A: --probe also walks each parent's device chain so probe-and-link
    # can bind devices by (position, class_name), closing the re-push device
    # duplication path. The --snapshot path stays device-blind (the JSON
    # file doesn't carry chain info); use --probe for the full coverage.
    live_devices_by_parent: dict | None = None
    if args.probe:
        live_tracks, live_returns = _probe_live_via_mcp()
        live_devices_by_parent = _probe_live_devices_via_mcp(
            live_tracks=live_tracks, live_returns=live_returns,
        )
    else:
        if not args.snapshot:
            raise SystemExit(
                "push_cli probe-and-link: pass --probe (W18-B canonical) "
                "or --snapshot <path> (test/debug fallback)"
            )
        live_tracks, live_returns = _load_snapshot_file(
            args.snapshot, subcmd="probe-and-link",
        )

    conn = _open_db(args)
    session_id = args.session_id
    auto_created = False

    if args.auto_session:
        # W9-B: bootstrap path for first-time push on a new song.
        # Requires --song <slug> (need the song to bind the session to).
        if not args.song:
            raise SystemExit(
                "push_cli probe-and-link: --auto-session requires --song <slug> "
                "(can't infer song from --db path)"
            )
        if session_id is not None:
            raise SystemExit(
                "push_cli probe-and-link: --auto-session and a positional "
                "session_id are mutually exclusive"
            )
        song = Q.get_song_by_name(conn, args.song)
        if song is None:
            raise SystemExit(
                f"push_cli probe-and-link: no song named {args.song!r} in DB — "
                "run build.py first"
            )
        name = args.session_name or f"{args.song}-{_timestamp()}"
        session_id = M.create_ableton_session(
            conn, song_id=song["id"], name=name,
            actor="sync",
            reason=args.reason or f"--auto-session from push_cli for {args.song}",
        )
        conn.commit()
        auto_created = True

    if session_id is None:
        # WFL-7Q2N: no positional id and no --auto-session — discover from
        # the DB (only / most-recent session; echoed on stderr).
        session_id = resolve_session_id(
            conn, None, prog="push_cli probe-and-link",
        )

    song_id = _resolve_song_id(conn, session_id)
    result = push.probe_and_link(
        conn,
        song_id=song_id,
        session_id=session_id,
        live_tracks=live_tracks,
        live_returns=live_returns,
        live_devices_by_parent=live_devices_by_parent,
        actor="sync",
        reason=args.reason or f"probe-and-link from session {session_id}",
        auto_session_created=auto_created,
    )
    out = result.to_dict()
    out["song_id"] = song_id
    out["session_id"] = session_id
    out["auto_session_created"] = auto_created
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _load_snapshot_file(path_str: str, *, subcmd: str) -> tuple[list, list]:
    """Read a {tracks, returns} JSON snapshot. Returns (live_tracks, live_returns).

    Shared between probe-and-link and check-coherence so both subcommands
    refuse with the same teaching errors on a malformed file.
    """
    snapshot = json.loads(Path(path_str).read_text())
    if not isinstance(snapshot, dict):
        raise SystemExit(
            f"push_cli {subcmd}: snapshot file must be a JSON object "
            'with "tracks" and "returns" arrays'
        )
    live_tracks = snapshot.get("tracks") or []
    live_returns = snapshot.get("returns") or []
    if not isinstance(live_tracks, list) or not isinstance(live_returns, list):
        raise SystemExit(
            f"push_cli {subcmd}: snapshot.tracks and snapshot.returns "
            "must be JSON arrays"
        )
    return live_tracks, live_returns


def _cmd_check_coherence_probe_or_snapshot(
    args: argparse.Namespace, *, subcmd: str
) -> tuple[list[dict], list[dict]]:
    """Shared --probe vs --snapshot resolver. Used by check-coherence and
    execute; both need the same {tracks, returns} shape from one of the two
    sources, refused identically on missing flag."""
    if getattr(args, "probe", False):
        return _probe_live_via_mcp()
    if not args.snapshot:
        raise SystemExit(
            f"push_cli {subcmd}: pass --probe (W18-B canonical) "
            "or --snapshot <path> (test/debug fallback)"
        )
    return _load_snapshot_file(args.snapshot, subcmd=subcmd)


def _cmd_check_coherence(args: argparse.Namespace) -> int:
    """W18-A: refuse-and-teach before ``execute`` mutates Live.

    Validates that ``ableton_sessions`` + ``ableton_links`` rows are
    consistent with a freshly-probed Live snapshot. The skill probes Live
    (via ``ableton_track(action='list')`` + ``ableton_return(action='list')``)
    and feeds the snapshot file in.

    Exits 0 on coherent state; non-zero with a JSON error summary on stdout
    if any check fails. The skill uses the recovery hints to fix the state
    before retrying.
    """
    conn = _open_db(args)
    _session_for(conn, args, subcmd="check-coherence")
    live_tracks, live_returns = _cmd_check_coherence_probe_or_snapshot(
        args, subcmd="check-coherence",
    )
    result = push.check_coherence(
        conn,
        session_id=args.session_id,
        live_tracks=live_tracks,
        live_returns=live_returns,
    )
    out = result.to_dict()
    out["session_id"] = args.session_id
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if result.ok else 1


# Markers in the version-handshake refusal text built by the Remote Script
# side (hallucinote_mcp.wire.check_version_compat). Matched as substrings so
# the detection survives the refusal coming from an OLDER Remote Script whose
# wording predates any change to that hint.
_VERSION_MISMATCH_MARKERS = ("version mismatch", "version handshake")


def _version_mismatch_recovery(result: "push_execute.ExecuteResult") -> str | None:
    """SYN-5C3J: teach the recovery that actually clears an engine↔Remote-Script
    version mismatch.

    When a fresh CLI process is built from a different commit than the Live
    session's running Remote Script, every call refuses on the version
    handshake. The generic ``execute`` recovery ("fix build.py and re-run") is
    actively misleading here — re-running with the same drift refuses again.
    Detect the handshake refusal among the surfaced error patterns and return
    the recovery that resolves it, including the pin path that keeps a
    mid-flight Live session untouched (the editable-install + parallel-engine-
    dev case from the swell friction log). Returns ``None`` when no version
    mismatch is present, so normal failures keep the generic recovery.

    The Remote Script side generates the refusal, so its hint can't be updated
    in a running session — the teaching has to come from THIS (CLI) side, which
    is why it lives here and not in ``hallucinote_mcp.wire``.
    """
    patterns = getattr(result, "top_error_patterns", None) or []
    matched = any(
        marker in (p.get("error_substring") or "").lower()
        for p in patterns
        for marker in _VERSION_MISMATCH_MARKERS
    )
    if not matched:
        return None
    return (
        "\nRecovery (version mismatch): the CLI and the running Remote Script "
        "are built from different commits, so re-running won't help until they "
        "agree. The refusal above reports the Remote Script's version — its "
        "`+<sha>` suffix is the commit it was vendored from. Two paths:\n"
        "  1. Update the Remote Script to match the CLI: run `/ableton-mcp-install`, "
        "then fully quit and reopen Live (Live caches Control Surface modules at "
        "startup — `/mcp` alone won't reload them).\n"
        "  2. Keep the live session and pin the CLI to the Remote Script's "
        "commit (no Live restart — best when you're developing the engine in "
        "parallel against a mid-flight song):\n"
        "       git worktree add /tmp/hallucinote-pin <sha-from-the-refusal-above>\n"
        "       export PYTHONPATH=/tmp/hallucinote-pin/src:/tmp/hallucinote-pin/hallucinote_mcp/src\n"
        "       python3 -m hallucinote_mcp.cli preflight   # confirm package.version == the vendored remote_script version\n"
        "       python3 -m hallucinote.sync.push_cli execute ...   # re-run, now pinned\n"
        "  See the error-recovery guide ('Engine version drift during a live "
        "compose session') for why the editable-install + parallel-dev combo "
        "makes this common.\n"
    )


def _cmd_execute(args: argparse.Namespace) -> int:
    """W10-E2: dispatch the full thirteen-phase push directly against Live's
    Remote Script, bypassing the agent's tool-use channel.

    See ``.prawduct/artifacts/push-execute-design.md`` for the contract.
    Writes ``.last-push-state.json`` (always) + ``.last-push-errors.json``
    (on failure) into the song's directory. Prints a one-page summary to
    stdout.

    Coherence-check policy (A1-resid hardening of W18-A/B). Exactly one of
    three flags must be passed; the mutex group enforces this at
    argparse time:

    * ``--probe`` — canonical path. Probes Live in-process via the MCP TCP
      client and runs ``check_coherence`` against a fresh snapshot. Refuses
      with a teaching error and exits non-zero on session-missing or
      stale-link drift.
    * ``--snapshot <path>`` — same shape against a pre-probed JSON file.
      Useful for tests and offline debugging; not for normal authoring
      (the whole point of W18-B was to eliminate stale snapshot files
      between runs).
    * ``--no-coherence-check`` — explicit opt-out. The push runs without
      the coherence safety net. Use only when the caller has externally
      verified that DB links match the live set (e.g. a CI scenario where
      both ends are scripted, or a debugging session where the user wants
      to observe what the dispatch does without the gate firing). The
      flag is named visibly so accidental omission of ``--probe`` doesn't
      silently skip the check (the pre-A1-resid default).
    """
    db_path = _resolve_db_path(args)
    conn = init_db(db_path)  # migrate-on-open; see _open_db
    _session_for(conn, args, subcmd="execute")
    song_id = _resolve_song_id(conn, args.session_id)

    if not args.no_coherence_check:
        # The mutex group makes --probe or --snapshot the only other paths,
        # so exactly one is set here.
        live_tracks, live_returns = _cmd_check_coherence_probe_or_snapshot(
            args, subcmd="execute",
        )
        check = push.check_coherence(
            conn,
            session_id=args.session_id,
            live_tracks=live_tracks,
            live_returns=live_returns,
        )
        if not check.ok:
            sys.stderr.write(
                "push_cli execute: refused — coherence check failed (W18-A).\n"
            )
            json.dump(check.to_dict(), sys.stderr, indent=2)
            sys.stderr.write("\n")
            return 1

    if args.state_dir:
        state_dir = Path(args.state_dir)
    else:
        state_dir = db_path.parent

    result = push_execute.execute_push(
        conn=conn,
        song_id=song_id,
        session_id=args.session_id,
        state_dir=state_dir,
        actor="sync",
        reason=args.reason or f"push_cli execute (session={args.session_id})",
        perform_slowdown_factor=args.perform_slowdown,
    )
    sys.stdout.write(push_execute.format_summary(result))

    # DOC-5W8B: a push whose devices phase applied anything leaves
    # REQUIREMENTS.md fresh in the same flow. Regen is content-idempotent,
    # so parameter-only device pushes regenerate harmlessly; a halted push
    # that still applied device changes regenerates too (the doc tracks
    # current set state, not push success). Regen failure must never mask
    # the push outcome — it degrades to a stderr notice.
    devices_phase = next(
        (p for p in result.phases if p.name == "devices"), None,
    )
    if devices_phase is not None and devices_phase.calls_ok > 0:
        if getattr(args, "song", None):
            from hallucinote.sync.compat import regen_requirements
            try:
                req_path = regen_requirements(args.song)
                sys.stderr.write(
                    f"push_cli execute: REQUIREMENTS.md regenerated "
                    f"({req_path})\n"
                )
            except (SystemExit, Exception) as exc:  # prawduct:allow prawduct/broad-except -- a docs-regen failure (bad slug, DB read, file write) must degrade to a notice, never replace the push's exit code
                sys.stderr.write(
                    f"push_cli execute: REQUIREMENTS.md regen skipped — "
                    f"{exc}\n"
                )
        else:
            sys.stderr.write(
                "push_cli execute: devices changed — REQUIREMENTS.md may be "
                "stale; re-run `python3 -m hallucinote.sync.compat "
                "write-requirements <slug>` (no --song given, can't locate "
                "the song dir)\n"
            )

    # A5: surface the verbatim recovery command on a non-clean exit so the
    # agent doesn't have to reassemble flags from the failure context.
    # Push is idempotent (W10-A + W20-A device binding by class/position) —
    # re-running is the structural retry, not a separate `--resume` path.
    if result.exit_code != 0:
        # SYN-5C3J: a version-mismatch refusal needs a different recovery than
        # the generic "fix build.py and re-run" — re-running can't clear drift.
        pin_recovery = _version_mismatch_recovery(result)
        if pin_recovery is not None:
            sys.stdout.write(pin_recovery)
        else:
            slug_flag = f"--song {args.song}" if getattr(args, "song", None) else f"--db {db_path}"
            sys.stdout.write(
                "\nRecovery: fix the underlying issue (build.py or snapshot), "
                "rebuild, then re-run:\n"
                f"  python3 -m hallucinote.sync.push_cli execute "
                f"{args.session_id} {slug_flag} --probe\n"
                "Re-run is idempotent: already-applied rows skip on the second pass.\n"
            )
    return result.exit_code


def _cmd_push_notes(args: argparse.Namespace) -> int:
    """Scoped note push (build-plan B1) — the incremental compose loop's
    materialize step. Pushes only the targeted (``--clip``) or content-changed
    (``--changed``) clips' notes to Live, in-process, so the notes never enter
    the agent's tool-use channel. Prints a counts-only summary; writes
    ``.last-notes-push.json`` (per-clip content fingerprints).

    No coherence gate (unlike ``execute``): this path only touches notes on
    already-linked clips, and ``plan_push_clip`` returns a teaching error per
    clip whose track isn't linked yet (run a full ``execute`` first).
    """
    db_path = _resolve_db_path(args)
    conn = init_db(db_path)  # migrate-on-open; see _open_db
    _session_for(conn, args, subcmd="push-notes")
    song_id = _resolve_song_id(conn, args.session_id)

    state_dir = Path(args.state_dir) if args.state_dir else db_path.parent

    result = push_notes.push_notes(
        conn,
        song_id=song_id,
        session_id=args.session_id,
        state_dir=state_dir,
        clip_ids=args.clip or None,
        changed_only=args.changed,
        actor="sync",
        reason=args.reason or f"push_cli push-notes (session={args.session_id})",
    )
    sys.stdout.write(push_notes.format_summary(result))

    if result.connection_lost:
        return push_execute.EXIT_CONNECTION_LOST
    if result.errors:
        return push_execute.EXIT_PARTIAL
    return push_execute.EXIT_OK


def _cmd_prune(args: argparse.Namespace) -> int:
    """B1b: opt-in structural deletion of orphan Live session clips.

    Dry-run by DEFAULT — lists Live clips whose slot has no matching DB clip on
    the linked track, without deleting. Pass ``--apply`` to actually delete
    them via ``ableton_clip(action='delete', location='session')`` (session
    deletes clear the slot without shifting indices, so order is irrelevant).

    NEVER deletes a DB-backed clip, and refuses (per-track) to gut a Live track
    that no DB track is linked to — that's a track-level concern for
    ``cleanup-default-scaffold`` or explicit removal. Scope is session clips,
    matching the scoped-push compose loop; arrangement prune is out of scope.
    """
    conn = _open_db(args)
    _session_for(conn, args, subcmd="prune")
    song_id = _resolve_song_id(conn, args.session_id)
    send_fn = _resolve_send_fn()

    live_tracks, _ = _probe_live_via_mcp(send_fn=send_fn)
    clips_by_track = _probe_live_session_clips_via_mcp(
        live_tracks=live_tracks, send_fn=send_fn,
    )

    tracks_input: list[dict[str, Any]] = []
    for lt in live_tracks:
        ti = lt["track_index"]
        db_track_id = Q.get_db_id_by_ableton_index(
            conn, session_id=args.session_id, db_kind="track", ableton_index=ti,
        )
        db_slots = None
        if db_track_id is not None:
            db_slots = {c["slot"] for c in Q.get_clips_for_track(conn, db_track_id)}
        tracks_input.append({
            "track_index": ti,
            "track_name": lt.get("name", ""),
            "db_slots": db_slots,
            "live_clips": clips_by_track.get(ti, []),
        })

    plan = push.plan_clip_prune(tracks_input)

    out: dict[str, Any] = {
        "dry_run": not args.apply,
        "session_id": args.session_id,
        "song_id": song_id,
        **plan.to_dict(),
    }

    if not args.apply:
        out["note"] = (
            f"dry-run: {len(plan.prunable)} clip(s) would be deleted. "
            "Pass --apply to delete them."
        )
        json.dump(out, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    from hallucinote_mcp.wire import Request  # type: ignore[import-not-found]
    deleted: list[dict[str, Any]] = []
    for tgt in plan.prunable:
        resp = send_fn(Request(
            tool="ableton_clip", action="delete",
            params={"track_index": tgt.track_index, "location": "session",
                    "clip_index": tgt.clip_index},
        ))
        if not getattr(resp, "ok", False):
            sys.stderr.write(
                f"push_cli prune: delete failed at track_index={tgt.track_index} "
                f"clip_index={tgt.clip_index} ({tgt.name!r}) — "
                f"{getattr(resp, 'error', 'unknown error')}\n"
            )
            return 2
        deleted.append({"track_index": tgt.track_index, "clip_index": tgt.clip_index,
                        "name": tgt.name})
    out["deleted"] = deleted
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_cleanup_default_scaffold(args: argparse.Namespace) -> int:
    """R-1.2: single-command cleanup of Live's brand-new-set defaults.

    Probes Live's current tracks + returns, classifies unmatched parents
    against the canonical-default name sets, dispatches descending
    ``ableton_track/return(action='delete')`` calls in-process, and
    re-runs ``probe_and_link`` so the resulting ``ableton_links`` reflect
    the cleaned state.

    Refuses (exit 1, JSON refusal on stderr) when:

    * any unmatched Live track/return is NOT a canonical default —
      cleanup is conservative; the user must hand-resolve non-defaults.
    * deleting every deletable track would leave Live with zero tracks.

    Without ``--auto-session``, requires an existing ``session_id``
    positionally. The session row is used to scope the link reconciliation
    so the cleaned-state probe-and-link writes to the right session.
    """
    if not args.song and not args.db:
        raise SystemExit(
            "push_cli cleanup-default-scaffold: need --song <slug> or --db <path>"
        )
    conn = _open_db(args)
    _session_for(conn, args, subcmd="cleanup-default-scaffold")
    song_id = _resolve_song_id(conn, args.session_id)

    live_tracks, live_returns = _probe_live_via_mcp()

    # First probe-and-link pass: identify which Live tracks/returns are
    # already matched to song entities (their indexes survive cleanup
    # unconditionally) and which are unmatched (candidates for cleanup
    # if canonical).
    pre = push.probe_and_link(
        conn,
        song_id=song_id,
        session_id=args.session_id,
        live_tracks=live_tracks,
        live_returns=live_returns,
        actor="sync",
        reason=args.reason or f"cleanup-default-scaffold pre-probe",
    )

    cleanup_plan = push.plan_cleanup_default_scaffold(
        unmatched_live_tracks=pre.unmatched_live_tracks,
        unmatched_live_returns=pre.unmatched_live_returns,
        total_live_track_count=len(live_tracks),
        matched_track_count=len(pre.matched_tracks),
    )

    if not cleanup_plan.can_proceed:
        sys.stderr.write(
            "push_cli cleanup-default-scaffold: refused — see refusals.\n"
        )
        json.dump(cleanup_plan.to_dict(), sys.stderr, indent=2)
        sys.stderr.write("\n")
        return 1

    # Dispatch deletes in-process. Track deletes first (descending), then
    # return deletes (descending). Order within track vs return doesn't
    # matter — Live's track + return lists are separate.
    from hallucinote_mcp.wire import Request  # type: ignore[import-not-found]
    send_fn = _resolve_send_fn()

    deleted_tracks: list[dict[str, Any]] = []
    deleted_returns: list[dict[str, Any]] = []

    for t in cleanup_plan.deletable_tracks:
        resp = send_fn(Request(
            tool="ableton_track", action="delete",
            params={"track_index": t["track_index"]},
        ))
        if not getattr(resp, "ok", False):
            sys.stderr.write(
                f"push_cli cleanup-default-scaffold: delete failed at "
                f"track_index={t['track_index']} ({t['name']!r}) — "
                f"{getattr(resp, 'error', 'unknown error')}\n"
            )
            return 2
        deleted_tracks.append(t)
    for r in cleanup_plan.deletable_returns:
        resp = send_fn(Request(
            tool="ableton_return", action="delete",
            params={"return_index": r["return_index"]},
        ))
        if not getattr(resp, "ok", False):
            sys.stderr.write(
                f"push_cli cleanup-default-scaffold: delete failed at "
                f"return_index={r['return_index']} ({r['name']!r}) — "
                f"{getattr(resp, 'error', 'unknown error')}\n"
            )
            return 2
        deleted_returns.append(r)

    # Re-probe Live + reconcile. The post-cleanup probe-and-link rewrites
    # link rows that may now point at shifted indexes; W18-B's strict
    # reconciliation drops any link pointing at a now-vacant slot.
    post_live_tracks, post_live_returns = _probe_live_via_mcp()
    post_devices = _probe_live_devices_via_mcp(
        live_tracks=post_live_tracks, live_returns=post_live_returns,
    )
    post = push.probe_and_link(
        conn,
        song_id=song_id,
        session_id=args.session_id,
        live_tracks=post_live_tracks,
        live_returns=post_live_returns,
        live_devices_by_parent=post_devices,
        actor="sync",
        reason=args.reason or "cleanup-default-scaffold post-reconcile",
    )

    out = {
        "deleted_tracks": deleted_tracks,
        "deleted_returns": deleted_returns,
        "post_probe_and_link": post.to_dict(),
        "session_id": args.session_id,
        "song_id": song_id,
    }
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_create_session(args: argparse.Namespace) -> int:
    """W9-B: low-level helper. Creates an ableton_sessions row for the song,
    prints its id on stdout. Used by ableton-push skill when the user hasn't
    bound a session yet."""
    conn = _open_db(args)
    song = Q.get_song_by_name(conn, args.song)
    if song is None:
        raise SystemExit(
            f"push_cli create-session: no song named {args.song!r} in DB — "
            "run build.py first"
        )
    name = args.name or f"{args.song}-{_timestamp()}"
    session_id = M.create_ableton_session(
        conn, song_id=song["id"], name=name,
        actor="sync",
        reason=args.reason or f"create-session for {args.song}",
    )
    conn.commit()
    json.dump({
        "session_id": session_id,
        "song_id": song["id"],
        "song_name": args.song,
        "name": name,
    }, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _timestamp() -> str:
    """Compact UTC timestamp for default session names. Avoids `:` for paths."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _perform_slowdown_arg(raw: str) -> float:
    """argparse type for --perform-slowdown: validate at the CLI boundary so an
    out-of-range value is rejected BEFORE any phase dispatches against Live
    (ENV-2T9K — the planner/handler also validate as wire-boundary defense, but
    a human-typed CLI value must fail fast, not 9 phases into a push)."""
    value = float(raw)  # ValueError → argparse reports a clean parse error
    if value < 1.0:
        raise argparse.ArgumentTypeError(
            f"--perform-slowdown must be >= 1.0 (1.0 = song tempo, off), got "
            f"{value}"
        )
    return value


def _add_db_args(p: argparse.ArgumentParser, *, mutex: bool = True) -> None:
    """Add --song / --db. By default mutually exclusive (one required).

    Set ``mutex=False`` for subcommands like ``probe-and-link --auto-session``
    that need ``--song`` for the slug AND optionally ``--db`` for an explicit
    DB path override.
    """
    if mutex:
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument("--song", help="song slug (resolves via resolve_db_path)")
        group.add_argument("--db", help="explicit path to the SQLite DB (escape hatch)")
    else:
        p.add_argument("--song", default=None,
                       help="song slug (resolves via resolve_db_path)")
        p.add_argument("--db", default=None,
                       help="explicit path to the SQLite DB (override of --song resolution)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hallucinote.sync.push_cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_phases = sub.add_parser("phases", help="emit the thirteen-phase metadata list")
    p_phases.add_argument("session_id", nargs="?", default=None,
                   help="ableton_sessions.id (omit to auto-select the "
                        "only/most-recent session in the DB; WFL-7Q2N)")
    _add_db_args(p_phases)
    p_phases.set_defaults(func=_cmd_phases)

    p_plan = sub.add_parser("plan", help="emit one phase's PushPlan as JSON")
    p_plan.add_argument("phase", help="phase name (e.g. tempo_map, tracks, clips)")
    p_plan.add_argument("session_id", nargs="?", default=None,
                   help="ableton_sessions.id (omit to auto-select the "
                        "only/most-recent session in the DB; WFL-7Q2N)")
    p_plan.add_argument(
        "--perform-slowdown", type=_perform_slowdown_arg, default=1.0,
        metavar="FACTOR",
        help="ENV-2T9K performed-automation fidelity: record at 1/FACTOR of the "
             "song tempo so the fixed tick rate lays down FACTOR× more "
             "breakpoints per beat (costs FACTOR× wall-clock). Default 1.0 = "
             "off. Only affects the performed_automation phase.",
    )
    _add_db_args(p_plan)
    p_plan.set_defaults(func=_cmd_plan)

    p_apply = sub.add_parser("apply", help="apply MCP results to the DB")
    p_apply.add_argument("session_id", nargs="?", default=None,
                   help="ableton_sessions.id (omit to auto-select the "
                        "only/most-recent session in the DB; WFL-7Q2N)")
    _add_db_args(p_apply)
    p_apply.add_argument("--results", required=True,
                         help="path to the results JSON the skill assembled")
    p_apply.add_argument("--plan", default=None,
                         help="W10-E: path to the original plan JSON. Required "
                              "when --results uses the minimal format (list of "
                              "{ok, result} without per-entry key/tool); ignored "
                              "for the legacy {key, ok, tool, result} format.")
    p_apply.add_argument("--reason", default=None,
                         help="optional reason annotation for emitted events")
    p_apply.set_defaults(func=_cmd_apply)

    p_pl = sub.add_parser(
        "probe-and-link",
        help="match Live tracks/returns by name → write ableton_links",
    )
    # session_id is optional when --auto-session is used (W9-B).
    p_pl.add_argument("session_id", nargs="?", default=None,
                      help="ableton_sessions.id (omit if --auto-session)")
    # Non-mutex: --auto-session needs --song for the slug; tests may pass
    # --db for an explicit override.
    _add_db_args(p_pl, mutex=False)
    # W18-B: --probe (canonical; in-process MCP TCP call) and --snapshot
    # (test/debug fallback; reads a pre-probed JSON file) are mutually
    # exclusive. Exactly one must be provided so callers don't silently
    # fall back to a stale snapshot from a prior run.
    probe_group = p_pl.add_mutually_exclusive_group(required=True)
    probe_group.add_argument("--probe", action="store_true",
                             help="W18-B canonical: probe Live's tracks + returns "
                                  "in-process via the MCP TCP client; no tmp file")
    probe_group.add_argument("--snapshot", default=None,
                             help="test/debug fallback: path to a pre-probed "
                                  "{tracks: [...], returns: [...]} JSON file")
    p_pl.add_argument("--reason", default=None,
                      help="optional reason annotation for emitted link events")
    p_pl.add_argument("--auto-session", action="store_true",
                      help="W9-B: create an ableton_sessions row if not provided "
                           "(requires --song <slug>; mutually exclusive with positional session_id)")
    p_pl.add_argument("--session-name", default=None,
                      help="optional name for the auto-created session "
                           "(default: <slug>-<utc-timestamp>)")
    p_pl.set_defaults(func=_cmd_probe_and_link)

    p_exec = sub.add_parser(
        "execute",
        help="W10-E2: dispatch the full thirteen-phase push directly against Live "
             "(bypasses agent tool-use channel for bulk-data phases)",
    )
    p_exec.add_argument("session_id", nargs="?", default=None,
                   help="ableton_sessions.id (omit to auto-select the "
                        "only/most-recent session in the DB; WFL-7Q2N)")
    _add_db_args(p_exec)
    p_exec.add_argument("--state-dir", default=None,
                        help="directory for .last-push-state.json + "
                             ".last-push-errors.json (default: DB directory)")
    # A1-resid (hardens W18-A/B): the coherence check is the safety net for
    # the punk-fate state-drift class. Pre-A1-resid the default was "skip
    # silently if neither --probe nor --snapshot is passed", which made the
    # safety net opt-in. Now the group is required and includes an explicit
    # opt-out flag so accidental omission can't slip past the gate.
    p_exec_probe = p_exec.add_mutually_exclusive_group(required=True)
    p_exec_probe.add_argument("--probe", action="store_true",
                              help="W18-B canonical: probe Live in-process "
                                   "and run the coherence check before "
                                   "dispatching phases")
    p_exec_probe.add_argument("--snapshot", default=None,
                              help="W18-A: pre-probed snapshot path; runs "
                                   "the coherence check before dispatching "
                                   "phases (alternative to --probe)")
    p_exec_probe.add_argument("--no-coherence-check", action="store_true",
                              dest="no_coherence_check",
                              help="A1-resid: skip the coherence check. "
                                   "Use only when the caller has externally "
                                   "verified that DB links match the live "
                                   "set (CI scripted scenarios, offline "
                                   "debugging). Pre-A1-resid this was the "
                                   "silent default — now it's explicit.")
    p_exec.add_argument("--reason", default=None,
                        help="optional reason annotation for emitted events")
    p_exec.add_argument(
        "--perform-slowdown", type=_perform_slowdown_arg, default=1.0,
        metavar="FACTOR",
        help="ENV-2T9K performed-automation fidelity: record at 1/FACTOR of the "
             "song tempo so the fixed tick rate lays down FACTOR× more "
             "breakpoints per beat (costs FACTOR× wall-clock). Default 1.0 = "
             "off. Only affects the performed_automation phase.",
    )
    p_exec.set_defaults(func=_cmd_execute)

    p_pn = sub.add_parser(
        "push-notes",
        help="B1: scoped note push — materialize only targeted (--clip) or "
             "content-changed (--changed) clips' notes to Live, in-process "
             "(notes never enter the agent's tool-use channel)",
    )
    p_pn.add_argument("session_id", nargs="?", default=None,
                   help="ableton_sessions.id (omit to auto-select the "
                        "only/most-recent session in the DB; WFL-7Q2N)")
    _add_db_args(p_pn)
    p_pn.add_argument("--clip", action="append", default=None,
                      help="clip id to push (repeatable); omit to consider every "
                           "clip on the song")
    p_pn.add_argument("--changed", action="store_true",
                      help="push only clips whose note content changed since the "
                           "last push-notes (content fingerprint, not event log)")
    p_pn.add_argument("--state-dir", default=None,
                      help="directory for .last-notes-push.json (default: DB directory)")
    p_pn.add_argument("--reason", default=None,
                      help="optional reason annotation for emitted events")
    p_pn.set_defaults(func=_cmd_push_notes)

    p_prune = sub.add_parser(
        "prune",
        help="B1b: opt-in deletion of orphan Live session clips (in Live, not "
             "in the DB). Dry-run by default; --apply to delete.",
    )
    p_prune.add_argument("session_id", nargs="?", default=None,
                   help="ableton_sessions.id (omit to auto-select the "
                        "only/most-recent session in the DB; WFL-7Q2N)")
    _add_db_args(p_prune)
    p_prune.add_argument("--apply", action="store_true",
                         help="actually delete the listed orphan clips "
                              "(default: dry-run — list only)")
    # No --reason: prune deletes Live-only orphans with no DB event to annotate
    # (orphans exist only in Live; nothing to emit against). See B1b NOTE.
    p_prune.set_defaults(func=_cmd_prune)

    p_cc = sub.add_parser(
        "check-coherence",
        help="W18-A: refuse-and-teach validation of ableton_sessions + "
             "ableton_links against a freshly-probed Live snapshot",
    )
    p_cc.add_argument("session_id", nargs="?", default=None,
                   help="ableton_sessions.id (omit to auto-select the "
                        "only/most-recent session in the DB; WFL-7Q2N)")
    _add_db_args(p_cc)
    # W18-B: --probe (canonical) | --snapshot (test/debug). Mutually exclusive,
    # exactly one required — same shape as probe-and-link.
    p_cc_probe = p_cc.add_mutually_exclusive_group(required=True)
    p_cc_probe.add_argument("--probe", action="store_true",
                            help="W18-B canonical: probe Live's tracks + returns "
                                 "in-process via the MCP TCP client")
    p_cc_probe.add_argument("--snapshot", default=None,
                            help="test/debug fallback: path to a pre-probed "
                                 "{tracks: [...], returns: [...]} JSON file")
    p_cc.set_defaults(func=_cmd_check_coherence)

    p_cleanup = sub.add_parser(
        "cleanup-default-scaffold",
        help="R-1.2: delete Live's brand-new-set default tracks/returns and "
             "re-reconcile links (refuses if non-canonical unmatched parents present)",
    )
    p_cleanup.add_argument("session_id", nargs="?", default=None,
                   help="ableton_sessions.id (omit to auto-select the "
                        "only/most-recent session in the DB; WFL-7Q2N)")
    _add_db_args(p_cleanup)
    p_cleanup.add_argument("--reason", default=None,
                           help="optional reason annotation for emitted events")
    p_cleanup.set_defaults(func=_cmd_cleanup_default_scaffold)

    p_cs = sub.add_parser(
        "create-session",
        help="W9-B: create an ableton_sessions row for the song, print its id",
    )
    # create-session always needs the slug (to look up the song row); --db is
    # an optional override for DB location. Doesn't use _add_db_args (which
    # makes --song and --db mutually exclusive).
    p_cs.add_argument("--song", required=True,
                      help="song slug (resolves to per-branch DB via resolve_db_path)")
    p_cs.add_argument("--db", default=None,
                      help="optional explicit DB path (override of --song resolution)")
    p_cs.add_argument("--name", default=None,
                      help="optional session name (default: <slug>-<utc-timestamp>)")
    p_cs.add_argument("--reason", default=None,
                      help="optional reason annotation for the emitted event")
    p_cs.set_defaults(func=_cmd_create_session)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
