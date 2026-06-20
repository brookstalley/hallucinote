"""Live return-track name normalization.

Shared between capture (replay path) and DB mutators (write path) so the
`<letter>-` prefix Live unconditionally applies to ReturnTrack.name is
stripped exactly once at the boundary into the DB. Living here rather
than inside capture.py avoids a circular import — `db.mutations` enforces
the same convention now, so the helper has to be reachable from both.
"""
from __future__ import annotations

import re

from hallucinote.analyzer_identity import ANALYZER_DEVICE_NAME


# Live 12.4 unconditionally prefixes every `ReturnTrack.name` with a
# `<slot-letter>-` segment (A-, B-, ..., Z-). Storing the prefixed form in
# the DB causes double-prefixing on push (DB "A-Reverb" → Live "A-A-Reverb").
# W3-H real-Live finding (2026-05-18); W4-C cross-layer fix.
_RETURN_SLOT_PREFIX = re.compile(r"^[A-Z]-")

# SYN-RENDER-RELINK: `ableton_render`'s analyzer auto-load renames RETURN tracks
# in Live, appending ` | HallucinoteAnalyzer` (the measurement device's name).
# Anchored at end-of-string, tolerant of the exact spacing around the `|`.
_ANALYZER_NAME_SUFFIX = re.compile(
    rf"\s*\|\s*{re.escape(ANALYZER_DEVICE_NAME)}\s*$"
)


def strip_return_slot_prefix(name: str | None) -> str | None:
    """Strip Live's `<slot-letter>-` prefix from a return-track name.

    Idempotent: names without the prefix (already-stripped, or never had it)
    pass through unchanged. The DB stores SUFFIX-only return names; push
    re-emits the suffix and Live re-adds its slot prefix.

    **Author trap (Wave 0 canary, solo-piano-ambient runbook step 3).** The
    regex strips ANY single uppercase-letter prefix, not just `A-` / `B-`.
    Hand-authored snapshots that put `"name": "A-Reverb"` lose the prefix on
    replay — `Q.get_return_by_name(..., "A-Reverb")` then returns None
    because the row was stored as `"Reverb"`. `replay_capture` emits a
    `UserWarning` summarizing strips so this isn't silent (Arc 7 / P7 also
    enforces the strip at the mutator boundary so build.py can't poison
    the DB by passing a prefixed name to `M.create_return` /
    `M.update_return`). See `docs/snapshot-schema.md` ("Return names:
    stored stripped") for the canonical form.
    """
    if name is None:
        return None
    return _RETURN_SLOT_PREFIX.sub("", name, count=1)


def strip_analyzer_suffix(name: str | None) -> str | None:
    """Strip a trailing ` | HallucinoteAnalyzer` suffix from a return-track name.

    SYN-RENDER-RELINK: `ableton_render` auto-loads the `HallucinoteAnalyzer`
    measurement device on every track + return + master; on RETURN tracks the
    load also renames the return (` | HallucinoteAnalyzer`). That device is never
    authored, so its suffix must not defeat probe-and-link's name matching — a
    render must not silently break DB↔Live return relink (every return-targeting
    push phase fails until the names are hand-restored). Idempotent + None-safe;
    anchored at end-of-string so a legitimately authored ` | ` mid-name survives.
    """
    if name is None:
        return None
    return _ANALYZER_NAME_SUFFIX.sub("", name)


def normalize_live_return_name(name: str | None) -> str | None:
    """A Live-side return name → its canonical DB-match form: strip Live's slot
    prefix AND any render-appended analyzer suffix. Use this (not the bare
    prefix strip) wherever a live return name is matched against a DB return."""
    return strip_analyzer_suffix(strip_return_slot_prefix(name))


__all__ = [
    "strip_return_slot_prefix",
    "strip_analyzer_suffix",
    "normalize_live_return_name",
]
