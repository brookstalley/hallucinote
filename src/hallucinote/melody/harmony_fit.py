"""hallucinote.melody.harmony_fit — the line's pitch read against the harmony.

Melody's PITCH dimension reads harmony (melody-model.md §2, §5): empirically a
line's stable tones favor chord tones and strong metrical positions, and its
non-chord-tones resolve **by step, forward in time**, to a proximate chord tone
(Bharucha's melodic anchoring — §3.A3, §3.A5). This module **reuses
``theory.model``** (the harmonic substrate the harmony axis already authored) — it
does NOT re-derive harmony — and is the HORIZONTAL, single-line counterpart to
``theory.lint``'s vertical (chordal) conformance.

The coupling is real but **modest, statistical, and classical-bound** (it flattens
in rock/modal idioms — §3.A1), so these are *facts*, graded against a line's
declared harmonic-freedom downstream (§5), never a universal gate. A chromatic
bebop head and a modal riff are not "wrong" here. Stdlib only; reports, never edits.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence

from hallucinote.theory.model import Progression

ToneClass = Literal["chord-tone", "scale-tone", "chromatic"]

# Shared with ``intervals.STEP_MAX_SEMITONES`` — a "stepwise" resolution is a major
# 2nd or smaller. (Kept as a local literal so this module needs no cross-import.)
_STEP_MAX_SEMITONES = 2

# An onset within this many beats of a strong metrical position counts as "on" it —
# tight, so only genuinely on-beat notes register (authored micro-timing is the
# performance layer's concern, not the melody lens's).
_STRONG_BEAT_TOLERANCE = 1e-6


@dataclass(frozen=True)
class HarmonyFit:
    """One line's pitch conformance to the section's declared harmony.

    Fractions are over the line's notes. ``nct_resolves_by_step`` is over the
    non-chord-tones that HAVE a successor (``None`` if there are none);
    ``chord_tone_on_strong_beat`` is over the notes that land on a strong metrical
    position (``None`` if none do). All ``None``-safe so a line sparse in either
    dimension reports honestly rather than a misleading 0."""

    note_count: int
    chord_tone_fraction: float
    scale_tone_fraction: float
    chromatic_fraction: float
    nct_resolves_by_step: float | None
    chord_tone_on_strong_beat: float | None

    @property
    def non_chord_tone_fraction(self) -> float:
        """Everything that is not a chord tone (scale tones + chromatics)."""
        return self.scale_tone_fraction + self.chromatic_fraction

    def to_dict(self) -> dict[str, Any]:
        return {
            "note_count": self.note_count,
            "chord_tone_fraction": self.chord_tone_fraction,
            "scale_tone_fraction": self.scale_tone_fraction,
            "chromatic_fraction": self.chromatic_fraction,
            "non_chord_tone_fraction": self.non_chord_tone_fraction,
            "nct_resolves_by_step": self.nct_resolves_by_step,
            "chord_tone_on_strong_beat": self.chord_tone_on_strong_beat,
        }


def classify_tone(pc: int, chord_pcs: frozenset[int], mode_pcs: frozenset[int]) -> ToneClass:
    """Classify a pitch class against the sounding chord + the mode:
    ``chord-tone`` (in the chord) > ``scale-tone`` (in the mode, not the chord) >
    ``chromatic`` (outside the mode). The stability ranking the research confirms
    (chord-tone > diatonic > chromatic — §3.A3)."""
    pc %= 12
    if pc in chord_pcs:
        return "chord-tone"
    if pc in mode_pcs:
        return "scale-tone"
    return "chromatic"


def _is_strong_beat(start_beats: float, beats_per_bar: float) -> bool:
    """A strong metrical position: the downbeat (bar position 0) or the mid-bar
    point (``beats_per_bar / 2``) — the canonical strong beats of common-time-like
    meters. Tight tolerance: only genuinely on-beat onsets register."""
    pos = start_beats % beats_per_bar
    half = beats_per_bar / 2.0
    return (
        pos <= _STRONG_BEAT_TOLERANCE
        or abs(pos - beats_per_bar) <= _STRONG_BEAT_TOLERANCE
        or abs(pos - half) <= _STRONG_BEAT_TOLERANCE
    )


def analyze_harmony_fit(
    sequence: Sequence[tuple[float, int]],
    prog: Progression,
    *,
    beats_per_bar: float,
) -> HarmonyFit:
    """Read an onset-ordered ``(start_beats, pitch)`` line against ``prog``.

    Each note is classified against the chord sounding at its onset
    (``prog.chord_at``) and the progression's mode. Then two grounded read-side
    facts: do non-chord-tones resolve **by step, forward in time**, to a chord tone
    (anchoring — §3.A3), and do chord tones favor strong metrical positions (§3.A1)?
    """
    seq = list(sequence)
    total = len(seq)
    if total == 0:
        return HarmonyFit(0, 0.0, 0.0, 0.0, None, None)

    mode_pcs = prog.mode.pitch_classes(prog.key_pc)
    classes: list[ToneClass] = []
    for start, pitch in seq:
        chord_pcs = prog.chord_at(start).pitch_classes()
        classes.append(classify_tone(int(pitch), chord_pcs, mode_pcs))

    chord = classes.count("chord-tone")
    scale = classes.count("scale-tone")
    chrom = classes.count("chromatic")

    # NCT resolution (Bharucha): a non-chord-tone with a successor "resolves" if the
    # next note is a chord tone reached by step (the anchor follows — asymmetry — and
    # is a pitch neighbor — proximity). Forward-in-time is implicit in "next note".
    nct_eligible = nct_resolved = 0
    for i in range(total - 1):
        if classes[i] != "chord-tone":
            nct_eligible += 1
            step = abs(int(seq[i + 1][1]) - int(seq[i][1])) <= _STEP_MAX_SEMITONES
            if classes[i + 1] == "chord-tone" and step:
                nct_resolved += 1
    nct_resolves = (nct_resolved / nct_eligible) if nct_eligible else None

    # Chord-tone-on-strong-beat: of the notes on strong positions, the fraction that
    # are chord tones (the tonal-metric coupling — §3.A1).
    strong_total = strong_chord = 0
    for (start, _pitch), cls in zip(seq, classes):
        if _is_strong_beat(start, beats_per_bar):
            strong_total += 1
            if cls == "chord-tone":
                strong_chord += 1
    strong_fit = (strong_chord / strong_total) if strong_total else None

    return HarmonyFit(
        note_count=total,
        chord_tone_fraction=chord / total,
        scale_tone_fraction=scale / total,
        chromatic_fraction=chrom / total,
        nct_resolves_by_step=nct_resolves,
        chord_tone_on_strong_beat=strong_fit,
    )
