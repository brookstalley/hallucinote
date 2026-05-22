"""Live return-track name normalization.

Shared between capture (replay path) and DB mutators (write path) so the
`<letter>-` prefix Live unconditionally applies to ReturnTrack.name is
stripped exactly once at the boundary into the DB. Living here rather
than inside capture.py avoids a circular import — `db.mutations` enforces
the same convention now, so the helper has to be reachable from both.
"""
from __future__ import annotations

import re


# Live 12.4 unconditionally prefixes every `ReturnTrack.name` with a
# `<slot-letter>-` segment (A-, B-, ..., Z-). Storing the prefixed form in
# the DB causes double-prefixing on push (DB "A-Reverb" → Live "A-A-Reverb").
# W3-H real-Live finding (2026-05-18); W4-C cross-layer fix.
_RETURN_SLOT_PREFIX = re.compile(r"^[A-Z]-")


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


__all__ = ["strip_return_slot_prefix"]
