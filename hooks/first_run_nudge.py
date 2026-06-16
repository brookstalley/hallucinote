#!/usr/bin/env python3
"""SessionStart first-run onboarding nudge (ONBOARD-M4L A2; Python port for Windows).

On the FIRST session after install, hand Claude a SessionStart `additionalContext`
object telling it to greet the user and offer /hallucinote:getting-started. Fires
exactly once, gated by a marker in CLAUDE_PLUGIN_DATA (persistent, survives plugin
updates) — no question asked, no per-session chatter.

Cross-platform: launched via `uv run --no-project python` from hooks.json (bash
isn't guaranteed on Windows, and `python`/`python3` names differ by OS; uv is the
one consistently-named hard prereq). NEVER fails the session (exit 0 on every
branch); only the one-time nudge JSON is written to stdout — SessionStart parses a
hook's plain stdout into Claude's context, so the already-onboarded path is silent.

Independent of the prewarm hook: on the very first session (cold build AND first
run) both emit their own additionalContext object; Claude Code injects both — one
is the env-build heads-up, this one is the welcome.
"""
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    data = os.environ.get("CLAUDE_PLUGIN_DATA", "")
    if not data:
        print("[hallucinote first-run] CLAUDE_PLUGIN_DATA unset — skipping the nudge.", file=sys.stderr)
        return 0

    marker = os.path.join(data, ".onboarded")

    # Already onboarded → stay completely silent (no stdout) so normal sessions
    # don't get a stray context injection.
    if os.path.isfile(marker):
        return 0

    # First run: record the marker, then emit the nudge. If we can't write the
    # marker (DATA not writable), stay silent rather than nudge every session.
    try:
        os.makedirs(data, exist_ok=True)
        with open(marker, "w", encoding="utf-8"):
            pass
    except OSError:
        print(f"[hallucinote first-run] could not write {marker} — skipping the nudge.", file=sys.stderr)
        return 0

    ctx = (
        "[Hallucinote] First run on this machine. Greet the user warmly and briefly — "
        "thank them for installing Hallucinote, which helps them plan, compose, mix, and "
        "produce any kind of musical work — then offer to run /hallucinote:getting-started "
        "to check their setup and point them at a first song. Keep it short and friendly; "
        "do not dump docs."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": ctx,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
