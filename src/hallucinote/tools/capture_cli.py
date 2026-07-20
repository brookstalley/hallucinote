"""Live-Ableton capture orchestration.

Captures the mix layout of a running Ableton session to a snapshot JSON file.
The ``execute`` subcommand probes Live's state IN CODE over the
`hallucinote_mcp.client.send` bridge (the same transport push/pull use), so the
whole capture is deterministic — no agent assembly step. (The earlier "Python
can't call MCP tools directly" framing was wrong; the bridge has always been
callable.) The legacy ``--plan`` form still prints the probe sequence for a
hand-driven / first capture.

Workflow (deterministic — NODE-ADDR Chunk B):

  1. Open the target Ableton set.
  2. ``python -m hallucinote.tools.capture_cli execute --song <slug>`` walks the
     live set via `hallucinote.capture.assemble_snapshot_via_probes`, reaching
     device parameters at every nesting depth (NodeAddr `path`), and writes
     `songs/<slug>/captured_session.refresh.json` (carrying `browser_path`
     forward from the existing snapshot).
  3. ``diff`` the refresh against the committed snapshot; on confirm, ``merge``
     + overwrite (the `/song-snapshot` skill drives the gate).
  4. `build.py` calls `hallucinote.capture.replay_capture(...)` to ingest.

CLI subcommands:

  * ``execute --song <slug>``   deterministic in-code capture -> writes the
                                `.refresh.json` and prints its path to stdout
  * ``--plan``                  print the MCP probe plan (JSON to stdout) — the
                                hand/first-capture documentation form
  * ``diff <old.json> <new.json>``  W12-B snapshot-refresh diff; structured
                                JSON to stdout + human summary to stderr
                                so the agent can pipe it both ways.
  * ``migrate <captured_session.json>``  SNP-8R4K: clean a committed snapshot
                                at rest — strip HallucinoteAnalyzer device
                                entries, densify survivors, stamp the snapshot
                                version. Writes in place + prints what it
                                stripped; no-op (no write) if already clean.

The diff path lets the `/song-snapshot` skill compare a fresh capture against
the on-disk snapshot before overwriting — see `src/hallucinote/capture.py`
`diff_snapshots` for the matching rules and result shape.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


from hallucinote.capture import (
    SNAPSHOT_SCHEMA_VERSION,
    capture_plan,
    diff_snapshots,
    format_diff_summary,
    has_usable_captured_at,
    merge_snapshots,
    migrate_snapshot,
    restamp_captured_at,
    snapshot_needs_migration,
)


def _cmd_plan(_: argparse.Namespace) -> int:
    json.dump(capture_plan(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _resolve_send_fn():
    """Lazy resolver for ``hallucinote_mcp.client.send`` — mirrors
    :func:`hallucinote.sync.pull_cli._resolve_send_fn`. Keeps this module
    importable when ``hallucinote_mcp`` isn't installed (only ``execute`` enters
    this path; ``plan``/``diff``/``merge``/``migrate`` are MCP-free). Tests
    inject a fake via ``monkeypatch.setattr(capture_cli, "_resolve_send_fn",
    lambda: fake)``.
    """
    from hallucinote_mcp import client as _client  # type: ignore[import-not-found]
    return _client.send


def _make_probe(send_fn):
    """Wrap a ``send_fn(Request) -> Response`` into the high-level
    ``probe(tool, action, **params) -> result_dict`` contract
    `assemble_snapshot_via_probes` expects. Raises on a tool-side failure — a
    partial snapshot would silently drop authored state, so capture aborts loudly.
    """
    from hallucinote_mcp.wire import Request  # type: ignore[import-not-found]

    def probe(tool: str, action: str, **params):
        resp = send_fn(Request(tool=tool, action=action, params=params))
        if not getattr(resp, "ok", False):
            raise RuntimeError(
                f"capture execute: {tool}(action={action!r}) failed: "
                f"{getattr(resp, 'error', 'unknown error')} (params={params!r})"
            )
        return getattr(resp, "result", None) or {}

    return probe


def _cmd_execute(args: argparse.Namespace) -> int:
    """Deterministic in-code capture (NODE-ADDR Chunk B): walk the live set via
    the MCP bridge, assemble a full snapshot, and write it to a side-by-side
    ``.refresh.json`` (never the canonical name — overwriting before the user
    has seen the diff is the bug `/song-snapshot` exists to prevent). Carries
    `browser_path` forward from the existing snapshot. Prints the refresh path
    to stdout so the skill can diff it.
    """
    from hallucinote.capture import assemble_snapshot_via_probes
    from hallucinote.workspace import resolve_song_dir

    if args.output:
        out_path = Path(args.output)
        old_path = Path(args.old) if args.old else None
    elif args.song:
        song_dir = resolve_song_dir(args.song)
        out_path = song_dir / "captured_session.refresh.json"
        old_path = song_dir / "captured_session.json"
    else:
        print(
            "error: capture execute needs --song SLUG (writes "
            "songs/<slug>/captured_session.refresh.json) or --output PATH",
            file=sys.stderr,
        )
        return 2

    old_snapshot = None
    if old_path is not None and old_path.exists():
        old_snapshot = json.loads(old_path.read_text())

    probe = _make_probe(_resolve_send_fn())
    snapshot = assemble_snapshot_via_probes(probe, old_snapshot=old_snapshot)

    out_path.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(
        f"capture execute: wrote {out_path} "
        f"({len(snapshot.get('tracks') or [])} tracks, "
        f"{len(snapshot.get('returns') or [])} returns)",
        file=sys.stderr,
    )
    print(str(out_path))
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    old_path = Path(args.old)
    new_path = Path(args.new)
    if not old_path.exists():
        print(f"error: old snapshot not found: {old_path}", file=sys.stderr)
        return 2
    if not new_path.exists():
        print(f"error: new snapshot not found: {new_path}", file=sys.stderr)
        return 2
    old = json.loads(old_path.read_text())
    new = json.loads(new_path.read_text())
    diff = diff_snapshots(old, new)
    # JSON to stdout for programmatic consumption; human summary to stderr so
    # an interactive caller sees something readable without redirecting.
    json.dump(diff, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    print(format_diff_summary(diff), file=sys.stderr)
    # Exit code 0 = no changes, 1 = changes present. Lets shell scripts branch.
    return 0 if not diff else 1


def _cmd_merge(args: argparse.Namespace) -> int:
    """Apply browser_path stickiness from `old` onto `new`, emitting the
    merged snapshot to stdout (or `--output`). `/song-snapshot` uses this
    between diff and overwrite so a refresh probe doesn't wipe load-time
    fields the list-time probes don't surface.
    """
    old_path = Path(args.old)
    new_path = Path(args.new)
    if not old_path.exists():
        print(f"error: old snapshot not found: {old_path}", file=sys.stderr)
        return 2
    if not new_path.exists():
        print(f"error: new snapshot not found: {new_path}", file=sys.stderr)
        return 2
    old = json.loads(old_path.read_text())
    new = json.loads(new_path.read_text())
    merged = merge_snapshots(old, new)
    if args.output:
        Path(args.output).write_text(
            json.dumps(merged, indent=2, sort_keys=True) + "\n"
        )
    else:
        json.dump(merged, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    return 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    """SNP-8R4K chunk 2 — clean a committed `captured_session.json` AT REST:
    strip HallucinoteAnalyzer device entries, densely renumber survivors, and
    stamp the snapshot schema version so the rewrite runs exactly once.

    Prints the report (what was stripped per parent + total) — never silent.
    A clean + stamped snapshot is a no-op (no write), printing "already clean".
    """
    path = Path(args.path)
    if not path.exists():
        print(f"error: snapshot not found: {path}", file=sys.stderr)
        return 2
    snapshot = json.loads(path.read_text())

    if not snapshot_needs_migration(snapshot):
        version = snapshot.get("snapshot_version", SNAPSHOT_SCHEMA_VERSION)
        print(f"{path}: already clean (v{version}) — no changes written.")
        return 0

    cleaned, report = migrate_snapshot(snapshot)
    # Match the existing snapshot writes' formatting (indent=2). The committed
    # snapshot is hand-readable + diff-friendly, so we don't sort_keys here —
    # the merge path sorts for stable side-by-side diffs, but a migrate is an
    # in-place rewrite where preserving the author's key order is friendlier.
    path.write_text(json.dumps(cleaned, indent=2) + "\n")

    version_before = report["version_before"]
    before_label = "unstamped" if version_before is None else f"v{version_before}"
    print(
        f"{path}: migrated {before_label} -> v{report['version_after']}, "
        f"stripped {report['total_removed']} analyzer device entr"
        f"{'y' if report['total_removed'] == 1 else 'ies'}."
    )
    for entry in report["stripped"]:
        print(
            f"  - {entry['kind']} {entry['parent']!r}: "
            f"removed {entry['removed']}"
        )
    return 0


def _cmd_restamp(args: argparse.Namespace) -> int:
    """Refresh a committed snapshot's ``captured_at`` in place WITHOUT a content
    change, disarming the replay guard (BAK-7D2V).

    This is a deliberate operator override, NOT a safe default, and no workflow
    reaches for it automatically: moving the stamp asserts that the on-disk
    content already matches Live, and nothing here can verify that. An empty
    ``capture diff`` is NOT such a verification — the diff never compares device
    sidechain sources, drum-pad mappings, or per-chain authored props, all of
    which replay re-asserts, so a pull touching only those fields diffs clean
    while the file is stale. Re-stamping over that state silently reverts the
    pulled work on the next build. Prefer baking a real capture (`/song-snapshot`,
    which merges the fresh refresh over the canonical file); prefer
    ``--force-replay`` when you consciously want to discard pulled edits, since
    it re-warns on every build instead of disarming the guard permanently."""
    from hallucinote.workspace import resolve_song_dir

    if args.song:
        path = resolve_song_dir(args.song) / "captured_session.json"
    elif args.path:
        path = Path(args.path)
    else:
        print(
            "error: capture restamp needs --song SLUG or a snapshot PATH",
            file=sys.stderr,
        )
        return 2
    if not path.exists():
        print(f"error: snapshot not found: {path}", file=sys.stderr)
        return 2

    snapshot = json.loads(path.read_text())
    old = snapshot.get("captured_at")
    # Refuse on an absent/malformed stamp. Replay treats an unstamped snapshot as
    # "no ordering evidence" and takes its warn-and-proceed branch — the user at
    # least SEES that pulled edits are being overwritten. Back-stamping one moves
    # it to the silent-pass branch instead, destroying the only signal in the one
    # case this tool cannot reason about. (Same reason `migrate_snapshot` never
    # stamps: dating unknown-age content defeats the guard.)
    if not has_usable_captured_at(snapshot):
        print(
            f"error: {path} has no usable `captured_at` stamp ({old!r}). "
            "Re-stamping it would silence the replay guard's warning without "
            "any evidence the content is current — capture the snapshot "
            "instead (`/song-snapshot`), which stamps it correctly.",
            file=sys.stderr,
        )
        return 2
    new = restamp_captured_at(snapshot)
    path.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(
        f"{path}: re-stamped captured_at {old!r} -> {new!r} "
        "(content unchanged; the replay guard is now disarmed)."
    )
    print(
        "warning: this asserts the on-disk snapshot already matches Live — "
        "nothing verified that. If a pull touched a device sidechain source, "
        "drum-pad mapping, or chain authored prop, those values are still "
        "stale here and the next build will silently revert them. Bake a real "
        "capture with `/song-snapshot` instead when you can.",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    # The legacy --plan flag is preserved so older skill bodies / docs keep
    # working; the subcommand form is the going-forward shape.
    p.add_argument(
        "--plan", action="store_true",
        help="Print the MCP probe plan for the agent to execute",
    )
    sub = p.add_subparsers(dest="cmd")

    plan_p = sub.add_parser("plan", help="Print the MCP probe plan")
    plan_p.set_defaults(func=_cmd_plan)

    exec_p = sub.add_parser(
        "execute",
        help=(
            "Deterministic in-code capture: walk the live set via the MCP "
            "bridge and write a side-by-side .refresh.json (requires "
            "hallucinote_mcp + a running Hallucinote bridge). Reaches device "
            "parameters at every nesting depth."
        ),
    )
    exec_p.add_argument(
        "--song", default=None,
        help="song slug — writes songs/<slug>/captured_session.refresh.json "
             "and preserves browser_path from the existing captured_session.json",
    )
    exec_p.add_argument(
        "--output", "-o", default=None,
        help="explicit output path (escape hatch / tests); overrides --song",
    )
    exec_p.add_argument(
        "--old", default=None,
        help="explicit existing-snapshot path for browser_path preservation "
             "(only meaningful with --output)",
    )
    exec_p.set_defaults(func=_cmd_execute)

    diff_p = sub.add_parser(
        "diff",
        help="Diff two snapshot JSON files (old vs new); exit 1 if changes",
    )
    diff_p.add_argument("old", help="Path to existing captured_session.json")
    diff_p.add_argument("new", help="Path to fresh capture (e.g. .refresh.json)")
    diff_p.set_defaults(func=_cmd_diff)

    merge_p = sub.add_parser(
        "merge",
        help=(
            "Merge two snapshots: take `new` as base, preserve sticky "
            "device fields (browser_path) from `old` where `new` omits them"
        ),
    )
    merge_p.add_argument("old", help="Path to existing captured_session.json")
    merge_p.add_argument("new", help="Path to fresh capture (e.g. .refresh.json)")
    merge_p.add_argument(
        "--output", "-o", default=None,
        help="Write merged JSON to PATH (default: stdout)",
    )
    merge_p.set_defaults(func=_cmd_merge)

    migrate_p = sub.add_parser(
        "migrate",
        help=(
            "SNP-8R4K: clean a committed captured_session.json at rest — strip "
            "HallucinoteAnalyzer device entries, densify survivors, stamp the "
            "snapshot version (writes in place; no-op if already clean)"
        ),
    )
    migrate_p.add_argument(
        "path", help="Path to the captured_session.json to clean in place"
    )
    migrate_p.set_defaults(func=_cmd_migrate)

    restamp_p = sub.add_parser(
        "restamp",
        help=(
            "BAK-7D2V: refresh captured_at in place with NO content change, to "
            "disarm the replay guard. Deliberate operator override — it asserts "
            "the on-disk content already matches Live and cannot verify it. "
            "Prefer /song-snapshot (bakes a real capture) or --force-replay."
        ),
    )
    restamp_p.add_argument(
        "--song", default=None,
        help="song slug — re-stamps songs/<slug>/captured_session.json",
    )
    restamp_p.add_argument(
        "path", nargs="?", default=None,
        help="explicit snapshot path (escape hatch / tests); overridden by --song",
    )
    restamp_p.set_defaults(func=_cmd_restamp)

    args = p.parse_args(argv)
    if args.plan:
        return _cmd_plan(args)
    if hasattr(args, "func"):
        return args.func(args)
    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
