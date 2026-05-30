"""Motivic variation operations — the canonical six, as pure rulers.

These are the transformation operations master arrangers apply to a motif so it
recurs in altered-but-recognizable forms. The set is the *verified* canonical
one (a competing 7-op list was refuted in research): **transposition, inversion,
retrograde, augmentation, diminution, fragmentation** — see
`.prawduct/artifacts/arrangement-model.md`.

Each op is a PURE function on a ``list[NoteDict]``. It removes the bookkeeping
arithmetic of the transform and makes ZERO musical decision about whether or
where to apply it — the composer decides that. **Rulers, not stamps**
(`feedback_great_art_not_software`).

A ``NoteDict`` is ``{pitch, start_beats, duration_beats, velocity, tags}``
(the generator note shape). Every op returns a NEW list of NEW dicts; inputs are
never mutated, and ``tags`` are carried through. Ops compose, and apply at any
scope — a bare motif, a layer, or every note of a whole section instance.

``shift`` (time translation) is included as a placement utility — the time-axis
analog of ``transpose`` — because phase/offset deltas (Reich-style) need it and
it is unambiguously bookkeeping.
"""
from __future__ import annotations

from typing import Any, Sequence

NoteDict = dict[str, Any]

_MIDI_MIN, _MIDI_MAX = 0, 127


def _copy(n: NoteDict) -> NoteDict:
    """Shallow copy with an independent tags list."""
    return dict(n, tags=list(n.get("tags", [])))


def _checked_pitch(original: int, result: int, op: str) -> int:
    if not (_MIDI_MIN <= result <= _MIDI_MAX):
        raise ValueError(
            f"{op}: pitch {original} -> {result} leaves MIDI range "
            f"[{_MIDI_MIN}, {_MIDI_MAX}]. Pick a smaller interval or a "
            f"different register before applying {op}."
        )
    return result


def _sorted(notes: list[NoteDict]) -> list[NoteDict]:
    return sorted(notes, key=lambda n: (n["start_beats"], n["pitch"]))


# --------------------------------------------------------------------------
# The canonical six
# --------------------------------------------------------------------------


def transpose(notes: Sequence[NoteDict], semitones: int) -> list[NoteDict]:
    """Shift every pitch by ``semitones`` (intervals preserved).

    Raises ``ValueError`` if any result leaves MIDI range — fail loud rather
    than silently collapse a melody against the ceiling.
    """
    out: list[NoteDict] = []
    for n in notes:
        m = _copy(n)
        m["pitch"] = _checked_pitch(n["pitch"], n["pitch"] + semitones, "transpose")
        out.append(m)
    return out


def invert(notes: Sequence[NoteDict], axis_pitch: int | None = None) -> list[NoteDict]:
    """Invert intervals around ``axis_pitch`` (``new = 2*axis - pitch``).

    ``axis_pitch`` defaults to the FIRST note's pitch, so the motif's opening
    note is the fixed pivot and the contour flips around it. Raises on out-of-range.
    """
    notes = list(notes)
    if not notes:
        return []
    axis = notes[0]["pitch"] if axis_pitch is None else axis_pitch
    out: list[NoteDict] = []
    for n in notes:
        m = _copy(n)
        m["pitch"] = _checked_pitch(n["pitch"], 2 * axis - n["pitch"], "invert")
        out.append(m)
    return out


def retrograde(notes: Sequence[NoteDict], span_beats: float | None = None) -> list[NoteDict]:
    """Reverse the motif in time.

    Each note's onset becomes ``span - (start + duration)``, so the motif's last
    release maps to 0 and it plays backwards. ``span_beats`` defaults to the
    latest release across the notes; pass an explicit span to retrograde within
    a fixed window (e.g. a bar) regardless of where the events sit.
    """
    notes = list(notes)
    if not notes:
        return []
    span = (
        max(n["start_beats"] + n["duration_beats"] for n in notes)
        if span_beats is None
        else span_beats
    )
    out: list[NoteDict] = []
    for n in notes:
        m = _copy(n)
        m["start_beats"] = span - (n["start_beats"] + n["duration_beats"])
        out.append(m)
    return _sorted(out)


def augment(notes: Sequence[NoteDict], factor: float) -> list[NoteDict]:
    """Lengthen rhythmic values by ``factor`` (>1 = slower/augmented).

    Scales both onset and duration so the motif keeps its shape, stretched in
    time. ``factor`` must be > 0.
    """
    if factor <= 0:
        raise ValueError(f"augment: factor must be > 0, got {factor}")
    out: list[NoteDict] = []
    for n in notes:
        m = _copy(n)
        m["start_beats"] = n["start_beats"] * factor
        m["duration_beats"] = n["duration_beats"] * factor
        out.append(m)
    return out


def diminish(notes: Sequence[NoteDict], factor: float) -> list[NoteDict]:
    """Shorten rhythmic values by ``factor`` (>1 = faster/diminished).

    The inverse of :func:`augment`: ``diminish(notes, 2)`` is twice as fast.
    ``factor`` must be > 0.
    """
    if factor <= 0:
        raise ValueError(f"diminish: factor must be > 0, got {factor}")
    return augment(notes, 1.0 / factor)


def fragment(
    notes: Sequence[NoteDict],
    start_beats: float,
    end_beats: float,
    *,
    rebase: bool = True,
) -> list[NoteDict]:
    """Keep only the notes whose ONSET falls in ``[start_beats, end_beats)`` —
    use a portion of the motif to seed new material.

    With ``rebase=True`` (default) the window's start maps to 0, so the fragment
    is a standalone motif you can re-place. ``end_beats`` must be > ``start_beats``.
    """
    if end_beats <= start_beats:
        raise ValueError(
            f"fragment: end_beats ({end_beats}) must be > start_beats ({start_beats})"
        )
    out: list[NoteDict] = []
    for n in notes:
        s = n["start_beats"]
        if start_beats <= s < end_beats:
            m = _copy(n)
            if rebase:
                m["start_beats"] = s - start_beats
            out.append(m)
    return _sorted(out)


# --------------------------------------------------------------------------
# Placement utility (time-axis translation — the analog of transpose)
# --------------------------------------------------------------------------


def shift(notes: Sequence[NoteDict], beats: float) -> list[NoteDict]:
    """Translate every onset by ``beats`` (positive = later).

    Pure time placement: used to position a motif at a bar, or to author a
    phase/offset delta (Reich-style phasing = a recurrence whose shift grows).
    Does NOT clamp to >= 0 — the mutator boundary refuses notes whose absolute
    onset ends up negative, which is the right place for that reality check.
    """
    out: list[NoteDict] = []
    for n in notes:
        m = _copy(n)
        m["start_beats"] = n["start_beats"] + beats
        out.append(m)
    return out
