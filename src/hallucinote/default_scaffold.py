"""What Live's brand-new-set scaffold is called — the one definition both sides
of the Live↔model boundary read.

Live 12.x opens a fresh set with four unused tracks and two returns. Two
subsystems have to recognize them and they sit on opposite sides of the model:
the push planner (:mod:`hallucinote.sync.push.probe`) offers to clean them up
before a first push, and capture (:mod:`hallucinote.capture`) excludes them so
an untouched scaffold never enters a snapshot as song material.

Why a module of its own rather than the planner's copy. Capture used to import
this set from ``sync.push.probe``, which put the canonical definition of a
*Live* fact inside the push planner and made a capture maintainer read push
internals to find it — and, worse, pointed the dependency edge the wrong way:
``sync/pull/devices.py`` already imports :mod:`hallucinote.capture`, so the
first planner that needed anything from capture would have closed a cycle.
Importing ``sync.push.probe`` also executes ``sync/push/__init__.py``, which
pulls in every planner module, for the sake of a four-element frozenset. The
precedent this follows is :mod:`hallucinote.analyzer_identity`, the neutral
module holding the other half of capture's exclusion filter, which capture and
the push probe both import for exactly the same reason.

Detection keys off these EXACT names. Any drift — a rename, a locale change, a
user customization — means the tracks and returns are no longer recognizable
defaults, and each caller falls back to treating them as authored content
rather than guessing.
"""
from __future__ import annotations

CANONICAL_DEFAULT_SCAFFOLD_TRACK_NAMES: frozenset[str] = frozenset({
    "1-MIDI", "2-MIDI", "3-Audio", "4-Audio",
})
"""Track names Live 12.x's brand-new-set scaffold ships."""

CANONICAL_DEFAULT_SCAFFOLD_RETURN_DEVICES: dict[str, str] = {
    "A-Reverb": "Reverb",
    "B-Delay": "Delay",
}
"""The one device Live's brand-new-set loads onto each default return, by the
return's raw (slot-prefixed) name.

Returns need the device as well as the name, where tracks needed only the name.
Live ships its default returns CARRYING these devices, so capture's track-side
"canonical name AND no devices" predicate can never fire on a return — applying
it verbatim would be dead code. What makes a return recognizably UNCLAIMED is
that it still holds exactly this device, still at its factory settings (see
:func:`hallucinote.capture.is_untouched_default_scaffold_return`).

The value is the device's Live class name, which is also its stock display
name. A user who swaps the Reverb for something else, or renames it, has made
the return theirs — the same reasoning as the name keys below."""

CANONICAL_DEFAULT_SCAFFOLD_RETURN_NAMES: frozenset[str] = frozenset(
    CANONICAL_DEFAULT_SCAFFOLD_RETURN_DEVICES
)
"""Return names Live's brand-new-set ships, with the ``[A-Z]-`` slot prefix
Live displays. Derived from the device map above so the two can never drift
apart. The probe-and-link returns matcher strips that prefix and matches
against the DB's stripped form (W4-C); cleanup keys off the raw names, because
cleanup is about deleting Live-side defaults the song has not claimed, not
about matching by stripped name."""
