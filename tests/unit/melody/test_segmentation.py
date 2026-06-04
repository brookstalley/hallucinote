"""melody.segmentation — LBDM phrase segmentation + per-phrase contour (Chunk 5).

OPTIONAL chunk, BUILT because the Chunk-4 calibration surfaced the DR-3 friction: a
looping hook reads ``level`` whole-section even though each cycle has a real shape —
whole-section contour is too coarse on the real hooks. LBDM (Cambouropoulos, research
C2) is the cheap, deterministic, corpus-free segmenter; IDyOM/Grouper is named as the
heavyweight theory, NOT shipped (research C1/C3).

Pins: LBDM detects an obvious phrase break in a two-phrase fixture (a rest + register
jump), and per-phrase contour differs from the whole-line contour where it should
(the looping-hook flatten-to-level case, recovered per phrase).
"""
from __future__ import annotations

import inspect

from hallucinote.melody import segmentation
from hallucinote.melody.contour import contour_shape
from hallucinote.melody.segmentation import (
    per_phrase_contours,
    phrase_boundaries,
    phrase_segments,
)


def _n(pitch: int, start: float, dur: float = 0.5) -> dict:
    return {"pitch": pitch, "start_beats": start, "duration_beats": dur, "velocity": 80}


def test_lbdm_detects_an_obvious_phrase_break():
    """Two clearly separate phrases: a tight stepwise rise, a long REST + register
    jump, then a second tight rise. The rest + jump is a strong LBDM boundary."""
    phrase_a = [_n(p, i * 0.5) for i, p in enumerate([60, 62, 64, 65])]
    # a 2-beat rest, then a register jump up an octave for phrase B
    phrase_b = [_n(p, 4.0 + i * 0.5) for i, p in enumerate([72, 74, 76, 77])]
    notes = phrase_a + phrase_b
    bounds = phrase_boundaries(notes)
    assert 0 in bounds
    # the break is detected AT the start of phrase B (note index 4)
    assert 4 in bounds
    segs = phrase_segments(notes)
    assert len(segs) >= 2
    # phrase A's notes are the low register, phrase B's the high
    assert all(n["pitch"] < 70 for n in segs[0])
    assert all(n["pitch"] >= 70 for n in segs[-1])


def test_short_line_is_a_single_phrase():
    notes = [_n(p, i * 0.5) for i, p in enumerate([60, 62, 64])]
    assert phrase_boundaries(notes) == [0]
    assert len(phrase_segments(notes)) == 1


def test_per_phrase_contour_recovers_shape_a_looping_hook_flattens():
    """The DR-3 friction case: a hook whose CELL is a clear arch, tiled 3x. The
    whole-line contour flattens (the cells' centroids sit at the same height ->
    ``level``), but per-phrase the arch shape is recovered."""
    cell = [60, 64, 67, 64, 60]  # a clear arch within the cell
    notes = []
    for cycle in range(3):
        for i, p in enumerate(cell):
            # a small rest between cells gives LBDM a boundary to find
            notes.append(_n(p, cycle * 4.0 + i * 0.5))
    whole = [n["pitch"] for n in notes]
    # the whole-line read flattens (repeating cell -> no net section shape)
    assert contour_shape(whole) == "level"
    # per phrase, the arch is recovered on at least one phrase
    phrases = per_phrase_contours(notes)
    assert len(phrases) > 1
    assert any(shape == "arch" for shape, _ap, _pos in phrases)


def test_per_phrase_contour_differs_from_whole_line_where_it_should():
    """A descending-then-ascending line: whole-line reads ``valley`` (or level), but
    the two phrases read ``descending`` then ``ascending`` — the per-phrase facts the
    whole-line summary cannot carry."""
    desc = [_n(p, i * 0.5) for i, p in enumerate([72, 70, 67, 64])]
    asc = [_n(p, 4.0 + i * 0.5) for i, p in enumerate([60, 64, 67, 71])]
    notes = desc + asc
    phrases = per_phrase_contours(notes)
    shapes = [shape for shape, _ap, _pos in phrases]
    assert "descending" in shapes
    assert "ascending" in shapes


def test_lbdm_is_deterministic():
    notes = [_n(p, i * 0.5) for i, p in enumerate([60, 62, 64, 65, 72, 74, 76, 77])]
    assert phrase_boundaries(notes) == phrase_boundaries(notes)


def test_idyom_grouper_named_as_heavyweight_theory_not_shipped():
    """The lens's honesty pattern: the cheap proxy (LBDM) ships, the heavyweight
    theory (IDyOM / Grouper) is NAMED but not shipped (research C1/C3)."""
    doc = inspect.getdoc(segmentation) or ""
    assert "LBDM" in doc
    assert "IDyOM" in doc
    assert "Grouper" in doc
