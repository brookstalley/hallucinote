"""Live-Ableton capture orchestration (agent-driven).

Captures the mix layout of a running Ableton session to a snapshot JSON file.
The actual probing of Live's state is done by an MCP-equipped agent because
Python can't call MCP tools directly — this script's job is to document the
protocol and to serialize the assembled dict to disk.

Workflow:

  1. Open the target Ableton set.
  2. Have the agent run the probes listed by `hallucinote.capture.capture_plan()`:
       - `ableton_session(action='info')`              -> tempo, signature, master, counts
       - `ableton_return(action='list')`               -> return tracks list
       - `ableton_track(action='get_info', track_index=N)`   -> for each main track
       - `ableton_track(action='get_sends', track_index=N)`  -> for each main track
  3. Agent assembles the per-track / per-return / session dicts and calls
     `hallucinote.capture.compile_snapshot(...)`.
  4. Agent writes the result to `songs/<name>/captured_session.json`.
  5. `build.py` calls `hallucinote.capture.replay_capture(...)` to ingest.

CLI usage is intentionally minimal — the heavy lifting is the agent's:

  * ``--plan``                  print the MCP probe plan (JSON to stdout)
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
    merge_snapshots,
    migrate_snapshot,
    snapshot_needs_migration,
)


def _cmd_plan(_: argparse.Namespace) -> int:
    json.dump(capture_plan(), sys.stdout, indent=2)
    sys.stdout.write("\n")
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


def main() -> int:
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

    args = p.parse_args()
    if args.plan:
        return _cmd_plan(args)
    if hasattr(args, "func"):
        return args.func(args)
    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
