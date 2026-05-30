"""hallucinote.theory — the harmonic substrate (a first-class structural axis).

Genre-general music-theory rulers: chords, modes, and authored progressions
(with harmonic rhythm), plus a build-time read-side lens that verifies note
content matches the declared harmony. The composer authors every chord; this
layer carries identity / arithmetic / structure and gets out of the way.

See `.prawduct/artifacts/arrangement-model.md` (harmony co-equal to energy) and
the module docstrings for the ruler-not-stamp discipline.
"""
from __future__ import annotations

from hallucinote.theory.model import (
    MODES,
    QUALITIES,
    Change,
    Chord,
    Mode,
    Progression,
    mode,
    pc_name,
    pitch_class,
)

__all__ = [
    "MODES",
    "QUALITIES",
    "Change",
    "Chord",
    "Mode",
    "Progression",
    "mode",
    "pc_name",
    "pitch_class",
]
