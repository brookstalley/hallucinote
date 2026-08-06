"""Shared helpers for the Arrangement-override (``back_to_arranger``) latch.

When a Session clip fires on a track whose real content lives in the
Arrangement, Live engages the global ``Song.back_to_arranger`` latch and dims
the Arrangement lane on every overridden track — those tracks ignore their
Arrangement clips and stay silent. The latch cannot be cleared through the
Live Object Model in Live 12.x: ``setattr(song, 'back_to_arranger', 0)`` is
accepted without raising and then silently ignored (verified on the main
thread — the dispatcher wraps handlers in ``run_on_main`` — so it is a LOM
property quirk, not a threading artifact). Only Live's **Back to Arrangement**
transport button reliably re-engages the Arrangement.

These constants and the :func:`is_overridden` probe let the transport / clip /
info surfaces *teach* that state in-band (inside the tool result) instead of
returning a misleadingly-successful or silent result. See
``backlog MCP-2K9F/MCP-3D6Q/MCP-7P3R``
(MCP-7P3R): an agent mid-recovery is reading tool results, so the teaching has
to come back there, the way ``device set_sidechain`` / ``gain_db`` already do.
"""
from __future__ import annotations

from typing import Any

# What the latched state means — composed into every surface that observes it
# so the agent reads the same explanation everywhere.
OVERRIDE_DESCRIPTION = (
    "Arrangement override is latched (back_to_arranger): a Session clip fired "
    "or a parameter was touched live, so overridden tracks ignore their "
    "Arrangement lane and stay silent until the Arrangement is re-engaged."
)

# The GUI recovery — the only thing that reliably clears the latch in Live 12.x.
CLICK_BACK_TO_ARRANGEMENT = (
    "This override cannot be cleared through the Live API in Live 12.x — click "
    "Live's Back to Arrangement button in the transport bar, then press Play."
)


def is_overridden(song: Any) -> bool:
    """True when the global Arrangement-override latch is engaged.

    Tolerant of fakes / older Live builds that don't expose the attribute:
    a missing ``back_to_arranger`` reads as not-overridden.
    """
    return bool(getattr(song, "back_to_arranger", False))


__all__ = [
    "OVERRIDE_DESCRIPTION",
    "CLICK_BACK_TO_ARRANGEMENT",
    "is_overridden",
]
