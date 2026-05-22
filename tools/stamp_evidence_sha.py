#!/usr/bin/env python3
"""Stamp the current ``HEAD`` SHA into ``.prawduct/.test-evidence.json``.

Why this exists
---------------
The cumulative PR reviewer has flagged stale ``git_sha`` in test-evidence
across six consecutive chunks (V1-push session reflection, 2026-05-19).
``product-hook test-status`` validates the *timestamp* freshness, not the
SHA pointer, so an evidence record written before the final commit slipped
through every gate.

This script closes the loop. Idempotent: if the file is missing or the SHA
already matches ``HEAD``, it exits 0 without writing. When it updates the
file, it preserves every other field (only ``git_sha`` is rewritten).

Wiring
------
Hooked into the ``Stop`` event in ``.claude/settings.json`` so it fires at
the end of every Claude Code session, before the governance-gate
``product-hook stop`` reads test-evidence. Stays a standalone script
(rather than a ``product-hook`` subcommand) to avoid drifting into the
in-flight v1.5 framework WIP that occupies ``tools/product-hook``.

Failure modes are quiet: any error (no git repo, no .prawduct dir,
unparseable JSON) is reported to stderr and the script exits 0. The hook
is housekeeping; a noisy failure that blocks session shutdown would be
worse than silently skipping a stamp.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_EVIDENCE_PATH = Path(".prawduct/.test-evidence.json")


def _git_head_sha() -> str | None:
    """Return ``HEAD`` SHA, or ``None`` if the call fails for any reason.

    The caller treats ``None`` as "skip" — without a SHA we have nothing
    to stamp.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=2.0,
        )
        if proc.returncode != 0:
            return None
        sha = proc.stdout.strip()
        return sha if sha else None
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return None


def stamp(evidence_path: Path = _EVIDENCE_PATH) -> str:
    """Update ``evidence_path``'s ``git_sha`` to current ``HEAD`` if drifted.

    Returns one of:
      - ``"missing"`` — no evidence file on disk; nothing to stamp.
      - ``"no-head"`` — git couldn't resolve ``HEAD``.
      - ``"unparseable"`` — file exists but isn't valid JSON.
      - ``"current"`` — file's SHA matches; no write.
      - ``"stamped:<old>->>new>"`` — rewrote ``git_sha``.

    Always preserves every field other than ``git_sha``. Writes via a
    full re-serialization so the file remains a valid JSON object (no
    surgical patching of a partial file).
    """
    if not evidence_path.is_file():
        return "missing"
    head = _git_head_sha()
    if head is None:
        return "no-head"
    try:
        data = json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "unparseable"
    if not isinstance(data, dict):
        return "unparseable"
    old = data.get("git_sha")
    if old == head:
        return "current"
    data["git_sha"] = head
    evidence_path.write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8",
    )
    return f"stamped:{old or 'absent'}->{head}"


def main() -> int:
    result = stamp()
    # Stay quiet on the happy paths (`current`, `missing`) to keep the
    # hook output clean; chatter only when something changed or broke.
    if result.startswith("stamped:") or result in {"no-head", "unparseable"}:
        sys.stderr.write(f"stamp_evidence_sha: {result}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
