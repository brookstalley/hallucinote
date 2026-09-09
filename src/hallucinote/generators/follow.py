"""The pitch follower — a tracked F0 contour becomes a part.

A voice, a bowed line, a film actor's sentence: once its fundamental has been
tracked into a ``BeatStream`` of Hz against song beats, ``follow_pitch`` turns
that contour into notes an instrument can play, plus — when asked — a
per-note pitch envelope carrying the motion the notes alone cannot (the scoop
into a word, the glide between two held tones, the vibrato on a long one).

Discipline (the ruler-not-stamp norm, R4.6): the follower proposes a line and
decides nothing musical. The key it may quantize to, the register it lands in,
the dwell that counts as a note and the confidence it trusts are all
parameters the author passes. ``key`` in particular has no default: passing
``None`` keeps the contour's own pitch classes, which is how "does the music
lead, or does the sample?" stays a choice the author makes per song and per
moment rather than a default this module makes for them.

Pure: no database, no MCP. The caller threads the returned notes and
envelopes through the mutators; a per-note envelope here carries the note's
in-band address (pitch, start, duration) because a generator never knows a
row id.
"""
from __future__ import annotations

from bisect import insort
from typing import Literal

import numpy as np

from hallucinote.features.types import BeatStream
from hallucinote.generators.output import EnvelopeDict, GeneratorOutput, NoteDict
from hallucinote.theory.model import mode, pitch_class

FOLLOW_TAG = "follow"

BendMode = Literal["none", "note_expression"]
_BEND_MODES: frozenset[str] = frozenset({"none", "note_expression"})

# Units a contour must declare to be read as a fundamental in Hz. The units
# field exists so a cents or MIDI stream is refused rather than misread.
_HZ_UNITS: frozenset[str] = frozenset({"hz", "hertz"})

# A frame belongs to the region it is in while it sits within this many
# semitones of the region's median. Half a semitone is the width of one
# chromatic pitch's catchment, so a contour hovering at a pitch boundary is
# held by the median instead of flapping between two notes.
_STABLE_TOLERANCE_SEMITONES = 0.5

# A residual smaller than this everywhere is a straight note, not a bend; no
# envelope is emitted for it. One cent is below what any player perceives.
_BEND_SILENCE_SEMITONES = 0.01

# The narrowest register in which every pitch class has an octave to land in:
# twelve semitones inclusive, so any pitch can be transposed inside by octaves.
_MIN_REGISTER_SPAN = 11


def follow_pitch(
    stream: BeatStream,
    *,
    key: tuple[int | str, str] | None,
    register: tuple[int, int],
    min_note_beats: float = 0.25,
    confidence_floor: float = 0.5,
    bend: BendMode = "none",
    velocity: int = 100,
) -> GeneratorOutput:
    """Turn an F0 contour into tagged notes and, optionally, per-note bends.

    ``stream`` is a scalar ``BeatStream`` of Hz with ``nan`` on unvoiced
    frames. ``key`` is ``(tonic, mode_name)`` — the tonic a pitch class
    ``0..11`` or a note name like ``"Eb"`` — or ``None`` to keep every pitch
    class the contour actually sang. ``register`` is an inclusive
    ``(low_midi, high_midi)`` the line is transposed into by whole octaves, so
    a note is moved but never lost. A note is a stretch of at least
    ``min_note_beats`` where the contour dwells, on frames whose confidence
    reaches ``confidence_floor``; everything else is a rest or is folded into
    the neighbouring note as its scoop or glide.

    With ``bend='note_expression'`` each note whose contour moves carries an
    envelope on the MPE pitch axis: the contour minus the note's own centre,
    in semitones, note-relative beats. The residual is taken against the
    centre rather than the emitted pitch so a key or register decision is
    never quietly undone by the bend re-pitching the note back.
    """
    midi = _contour_in_midi(stream)
    voiced = _voiced_mask(stream, midi, confidence_floor)
    allowed = _allowed_pitch_classes(key)
    low, high = _checked_register(register)
    if min_note_beats <= 0:
        raise ValueError(
            f"min_note_beats must be > 0 (got {min_note_beats}); it is the "
            "shortest dwell that counts as a note"
        )
    if bend not in _BEND_MODES:
        raise ValueError(
            f"bend must be one of {sorted(_BEND_MODES)} (got {bend!r})"
        )
    if not 0 <= velocity <= 127:
        raise ValueError(f"velocity must be in [0, 127] (got {velocity})")

    beats = stream.beats
    frame_ends = _frame_ends(beats)
    out = GeneratorOutput()
    for run_start, run_stop in _voiced_runs(voiced):
        for span in _notes_in_run(
            midi, beats, frame_ends, run_start, run_stop, min_note_beats
        ):
            centre = float(np.median(midi[span.dwell_start:span.dwell_stop]))
            pitch = _into_register(_quantize(centre, allowed), low, high)
            start = float(beats[span.start])
            duration = float(frame_ends[span.stop - 1] - start)
            out.notes.append(_note(pitch, start, duration, velocity))
            if bend == "note_expression":
                env = _bend_envelope(
                    midi, beats, span, centre=centre, pitch=pitch,
                    start=start, duration=duration,
                )
                if env is not None:
                    out.envelopes.append(env)
    return out


# ---------------------------------------------------------------------------
# Reading the contour
# ---------------------------------------------------------------------------


def _contour_in_midi(stream: BeatStream) -> np.ndarray:
    """The contour as float MIDI, ``nan`` where it is unvoiced.

    Refuses a non-Hz stream, a vector stream and any non-positive Hz: a zero
    is what a tracker that never learned to say ``nan`` writes on silence,
    and quantizing it would hand the author a note nobody sang.
    """
    if stream.units.strip().lower() not in _HZ_UNITS:
        raise ValueError(
            f"follow_pitch reads an F0 contour in Hz; stream {stream.name!r} "
            f"is in {stream.units!r}. Pass the tracker's Hz stream, not a "
            "MIDI or cents series."
        )
    values = np.asarray(stream.values, dtype=np.float64)
    if values.ndim != 1:
        raise ValueError(
            f"follow_pitch takes a scalar contour; stream {stream.name!r} has "
            f"values of shape {values.shape}"
        )
    finite = np.isfinite(values)
    if np.any(values[finite] <= 0.0):
        raise ValueError(
            f"stream {stream.name!r} carries non-positive Hz on a voiced "
            "frame; unvoiced frames must be nan, never zero"
        )
    midi = np.full(values.shape, np.nan, dtype=np.float64)
    midi[finite] = 69.0 + 12.0 * np.log2(values[finite] / 440.0)
    return midi


def _voiced_mask(stream: BeatStream, midi: np.ndarray, floor: float) -> np.ndarray:
    if not 0.0 <= floor <= 1.0:
        raise ValueError(
            f"confidence_floor must lie in [0, 1] (got {floor}); it is "
            "compared against the stream's per-frame confidence"
        )
    voiced = np.isfinite(midi)
    if stream.confidence is not None:
        # nan confidence compares False and so counts as unvoiced.
        with np.errstate(invalid="ignore"):
            voiced &= stream.confidence >= floor
    return voiced


def _frame_ends(beats: np.ndarray) -> np.ndarray:
    """Where each frame's span ends: the next frame's beat, and for the last
    frame one typical hop on — the series describes spans, not instants."""
    if beats.shape[0] == 0:
        return beats.copy()
    hop = float(np.median(np.diff(beats))) if beats.shape[0] > 1 else 0.0
    return np.append(beats[1:], beats[-1] + hop)


def _voiced_runs(voiced: np.ndarray) -> list[tuple[int, int]]:
    """Half-open ``(start, stop)`` index ranges of consecutive voiced frames."""
    runs: list[tuple[int, int]] = []
    n = int(voiced.shape[0])
    i = 0
    while i < n:
        if not voiced[i]:
            i += 1
            continue
        j = i
        while j < n and voiced[j]:
            j += 1
        runs.append((i, j))
        i = j
    return runs


# ---------------------------------------------------------------------------
# Segmenting a voiced run into notes
# ---------------------------------------------------------------------------


class _NoteSpan:
    """Frame indices of one note: the frames it sounds over and, inside them,
    the dwell whose median names its pitch (the scoop and glide are excluded
    from that so they cannot pull the note off centre)."""

    __slots__ = ("start", "stop", "dwell_start", "dwell_stop")

    def __init__(self, start: int, stop: int, dwell_start: int, dwell_stop: int) -> None:
        self.start = start
        self.stop = stop
        self.dwell_start = dwell_start
        self.dwell_stop = dwell_stop


def _stable_regions(midi: np.ndarray, start: int, stop: int) -> list[tuple[int, int]]:
    """Split ``[start, stop)`` where the contour leaves its running median.

    A region grows frame by frame while the incoming frame lies within the
    tolerance of the median of the frames already in it. Judging against the
    median, not the first frame, is what lets vibrato ride inside one region
    while a real move to the next tone still breaks it.
    """
    regions: list[tuple[int, int]] = []
    i = start
    while i < stop:
        sorted_vals: list[float] = [float(midi[i])]
        j = i + 1
        while j < stop:
            candidate = float(midi[j])
            if abs(candidate - _median_of_sorted(sorted_vals)) > _STABLE_TOLERANCE_SEMITONES:
                break
            insort(sorted_vals, candidate)
            j += 1
        regions.append((i, j))
        i = j
    return regions


def _median_of_sorted(values: list[float]) -> float:
    n = len(values)
    mid = n // 2
    if n % 2:
        return values[mid]
    return 0.5 * (values[mid - 1] + values[mid])


def _notes_in_run(
    midi: np.ndarray,
    beats: np.ndarray,
    frame_ends: np.ndarray,
    run_start: int,
    run_stop: int,
    min_note_beats: float,
) -> list[_NoteSpan]:
    """Notes inside one voiced run.

    Regions long enough to be dwells become notes; a shorter region is
    transit and joins the note before it (a glide out) or, before any note
    exists, waits to open the first (a scoop in). A run with no dwell at all
    is a single note if the run itself is long enough — a glide sung as one
    gesture — and a rest otherwise.
    """
    def span_beats(i: int, j: int) -> float:
        return float(frame_ends[j - 1] - beats[i])

    notes: list[_NoteSpan] = []
    pending_transit: int | None = None
    for i, j in _stable_regions(midi, run_start, run_stop):
        if span_beats(i, j) >= min_note_beats:
            first = i if pending_transit is None else pending_transit
            notes.append(_NoteSpan(first, j, i, j))
            pending_transit = None
        elif notes:
            notes[-1].stop = j
        elif pending_transit is None:
            pending_transit = i
    if not notes and span_beats(run_start, run_stop) >= min_note_beats:
        notes.append(_NoteSpan(run_start, run_stop, run_start, run_stop))
    return notes


# ---------------------------------------------------------------------------
# Pitch decisions the author parameterized
# ---------------------------------------------------------------------------


def _allowed_pitch_classes(key: tuple[int | str, str] | None) -> frozenset[int] | None:
    if key is None:
        return None
    if not isinstance(key, tuple) or len(key) != 2:
        raise ValueError(
            f"key must be (tonic, mode_name) like (0, 'Major') or ('Eb', "
            f"'Dorian'), or None to keep the contour's own pitch classes; "
            f"got {key!r}"
        )
    tonic, mode_name = key
    if isinstance(tonic, str):
        tonic_pc = pitch_class(tonic)
    elif isinstance(tonic, int) and 0 <= tonic <= 11:
        tonic_pc = tonic
    else:
        raise ValueError(
            f"key tonic must be a pitch class 0..11 or a note name (got {tonic!r})"
        )
    return mode(mode_name).pitch_classes(tonic_pc)


def _quantize(centre: float, allowed: frozenset[int] | None) -> int:
    """The integer pitch nearest ``centre`` — any pitch when ``allowed`` is
    ``None``, else the nearest whose pitch class the key permits. An exact
    tie between two candidates resolves downward."""
    if allowed is None:
        return int(np.floor(centre + 0.5))
    best: int | None = None
    best_distance = float("inf")
    base = int(np.floor(centre))
    for candidate in range(base - 6, base + 8):
        if candidate % 12 not in allowed:
            continue
        distance = abs(candidate - centre)
        if distance < best_distance:
            best, best_distance = candidate, distance
    assert best is not None  # a mode always has at least its tonic
    return best


def _checked_register(register: tuple[int, int]) -> tuple[int, int]:
    if not isinstance(register, tuple) or len(register) != 2:
        raise ValueError(
            f"register must be an inclusive (low_midi, high_midi) pair; got {register!r}"
        )
    low, high = register
    if not (0 <= low <= high <= 127):
        raise ValueError(
            f"register must satisfy 0 <= low <= high <= 127; got {register!r}"
        )
    if high - low < _MIN_REGISTER_SPAN:
        raise ValueError(
            f"register {register!r} spans {high - low} semitones; it must span "
            f"at least {_MIN_REGISTER_SPAN} so every pitch class has an octave "
            "to land in — the follower transposes notes into the register, it "
            "never drops them"
        )
    return int(low), int(high)


def _into_register(pitch: int, low: int, high: int) -> int:
    while pitch < low:
        pitch += 12
    while pitch > high:
        pitch -= 12
    return pitch


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------


def _note(pitch: int, start: float, duration: float, velocity: int) -> NoteDict:
    return {
        "pitch": pitch,
        "start_beats": start,
        "duration_beats": duration,
        "velocity": velocity,
        "tags": [FOLLOW_TAG],
    }


def _bend_envelope(
    midi: np.ndarray,
    beats: np.ndarray,
    span: _NoteSpan,
    *,
    centre: float,
    pitch: int,
    start: float,
    duration: float,
) -> EnvelopeDict | None:
    """The note's residual contour as an MPE pitch envelope, or ``None`` for
    a note that does not move.

    Breakpoints are note-relative beats and semitones from the note's own
    centre, the coordinate system Live's ``envelope_for_note`` addresses.
    The note is named in-band by pitch, start and duration, exactly as the
    push planner addresses one, because no row id exists yet.
    """
    residual = midi[span.start:span.stop] - centre
    if float(np.max(np.abs(residual))) < _BEND_SILENCE_SEMITONES:
        return None
    times = beats[span.start:span.stop] - start
    breakpoints = [
        {"time_beats": float(t), "value": float(v), "curve_kind": "linear"}
        for t, v in zip(times, residual)
    ]
    return {
        "target_kind": "note_expression",
        "parameter_path": "pitch",
        "note_pitch": pitch,
        "note_start_beats": start,
        "note_duration": duration,
        "breakpoints": breakpoints,
    }


__all__ = ["FOLLOW_TAG", "BendMode", "follow_pitch"]
