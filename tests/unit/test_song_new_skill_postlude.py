"""Doc-drift lock for the /song-new postlude's `ensure_loaded` guidance.

SKL-8N3V: the postlude told the agent to call `ableton_render(action=
'ensure_loaded')`, and the natural reading — passing `song_slug` like every
other render action wants — errors `unknown param(s)`, because `ensure_loaded`
takes no params (it sweeps every existing surface). The fix (CLR-A) is doc-only:
the postlude must show the *no-params* call and warn that `song_slug` is
rejected. This locks that guidance so it can't silently regress back into the
foot-gun the swell dogfood hit. (Project learning: "when a doc IS the
deliverable, lock it with a drift test".)
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SONG_NEW_SKILL = _REPO / "skills" / "song-new" / "SKILL.md"


def test_song_new_postlude_shows_no_params_ensure_loaded():
    """The postlude shows the bare no-params call and warns `song_slug` errors."""
    text = _SONG_NEW_SKILL.read_text(encoding="utf-8")

    # The exact no-params call form the agent should copy.
    assert "ableton_render(action='ensure_loaded')" in text, (
        "song-new postlude must show the no-params ensure_loaded call form "
        "(SKL-8N3V) — agents copy this verbatim"
    )

    # The line(s) that mention ensure_loaded must carry the no-params contract,
    # so a regression that drops the warning (or re-suggests song_slug) fails.
    ensure_lines = [ln for ln in text.splitlines() if "ensure_loaded" in ln]
    assert ensure_lines, "expected an ensure_loaded mention in the song-new skill"
    guidance = "\n".join(ensure_lines)
    assert re.search(r"no (other )?params", guidance, re.IGNORECASE), (
        "song-new postlude must state ensure_loaded takes no params (SKL-8N3V)"
    )
    assert "song_slug" in guidance, (
        "song-new postlude must name that ensure_loaded rejects song_slug "
        "(the exact unknown-param foot-gun from the swell dogfood, SKL-8N3V)"
    )


def test_song_new_postlude_does_not_pass_song_slug_to_ensure_loaded():
    """No call form pairs ensure_loaded with a song_slug argument."""
    text = _SONG_NEW_SKILL.read_text(encoding="utf-8")
    # A call like ensure_loaded(..., song_slug=...) or ensure_loaded='...', song_slug
    # would re-introduce the bug. The only legitimate co-mention is the warning.
    bad = re.search(r"ensure_loaded'?\s*,\s*song_slug", text)
    assert bad is None, (
        "song-new postlude must not instruct passing song_slug to ensure_loaded "
        "(SKL-8N3V — it errors unknown param(s))"
    )
