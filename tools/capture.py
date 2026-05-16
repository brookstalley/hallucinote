"""Live-Ableton capture orchestration (agent-driven).

Captures the mix layout of a running Ableton session to a snapshot JSON file.
The actual probing of Live's state is done by an MCP-equipped agent because
Python can't call MCP tools directly — this script's job is to document the
protocol and to serialize the assembled dict to disk.

Workflow:

  1. Open the target Ableton set.
  2. Have the agent run the probes listed by `hallucinote.capture.capture_plan()`:
       - `get_session_info()`              -> tempo, signature, master, counts
       - `list_return_tracks()`            -> return tracks list
       - `get_track_info(track_index=N)`   -> for each main track
       - `get_track_sends(track_index=N)`  -> for each main track
  3. Agent assembles the per-track / per-return / session dicts and calls
     `hallucinote.capture.compile_snapshot(...)`.
  4. Agent writes the result to `songs/<name>/captured_session.json`.
  5. `build.py` calls `hallucinote.capture.replay_capture(...)` to ingest.

CLI usage is intentionally minimal — the heavy lifting is the agent's. This
file primarily exists as the documented entry point and as a place to grow a
batch CLI if it becomes useful (e.g., once read-side MCP coverage lands and
capture can be invoked from a single agent prompt).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add src/ to sys.path so this script runs without `pip install -e .`
# in environments where the editable install isn't present.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from hallucinote.capture import capture_plan  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--plan", action="store_true",
        help="Print the MCP probe plan for the agent to execute",
    )
    args = p.parse_args()
    if args.plan:
        json.dump(capture_plan(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
