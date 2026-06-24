"""The one authoring primitive: a scale-degree index → a plain MIDI integer.

This is the whole "isolation over integration" bet (decision 4). The microtonal
composer thinks in raw step indices; ``degree_to_midi`` turns those into the
integer-MIDI notes the **existing, unmodified** generators already consume. No
``tuning=`` parameter is threaded through ``generators/*``; no ``% 12`` in
``theory/`` is generalized. Live's loaded tuning reinterprets each MIDI number's
pitch, so feeding the right integer is all the authoring layer must do.
"""
from __future__ import annotations

from .model import TuningData

_MIDI_MIN = 0
_MIDI_MAX = 127


def degree_to_midi(tuning: TuningData, degree: int, period: int = 0) -> int:
    """MIDI note for scale ``degree`` in ``period``, clamped to 0–127.

    ``reference_note + period*step_count + degree`` — Live makes consecutive MIDI
    numbers consecutive scale degrees, so ``degree=0, period=0`` is the reference
    note, ``degree=step_count`` is the same scale position one period up, and any
    integer degree (negative, or past the period) is well-defined.

    Pure arithmetic with a 0–127 clamp (the playable MIDI range). The clamp is a
    deliberate, documented behavior, not error handling: a degree/period pair
    that lands off the keyboard saturates at the nearest endpoint rather than
    raising mid-build. Callers that need every degree on the keyboard should pick
    ``reference_note`` and degree ranges that stay in bounds.
    """
    raw = tuning.reference_note + period * tuning.step_count + degree
    return max(_MIDI_MIN, min(_MIDI_MAX, raw))


__all__ = ["degree_to_midi"]
