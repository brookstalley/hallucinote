"""melody.economy — the within-line motivic-economy / repetition reading (Chunk 4).

The cheap proxy (n-gram self-similarity over the INTERVAL sequence) with the
heavyweight theory named (COSIATEC + Kolmogorov simplicity, NOT shipped). Pins the
research-C4 contract: high on a cell-repeated line, low on a through-composed line,
interval-based (a TRANSPOSED repeat still counts), multi-interval (a single repeated
interval does NOT inflate it), and ``None`` for a line too short to read.

The C7 null (no "make it catchier" lever) is recorded in the module docstring —
asserted here so the honesty note can't be silently dropped.
"""
from __future__ import annotations

import inspect

from hallucinote.melody import economy
from hallucinote.melody.economy import repetition_coverage


def test_high_on_a_cell_repeated_line():
    # a 3-pitch (2-interval) cell C-E-G repeated 4x -> highly covered
    cell = [60, 64, 67] * 4
    cov = repetition_coverage(cell)
    assert cov is not None and cov > 0.8


def test_low_on_a_through_composed_line():
    # distinct moves throughout -> no repeated multi-interval cell
    tc = [60, 61, 63, 66, 70, 71, 69, 64, 55, 67]
    cov = repetition_coverage(tc)
    assert cov is not None and cov < 0.3


def test_interval_based_so_a_transposed_repeat_counts():
    """Temperley: a transposed repeat keeps interval identity, so it must count —
    the cell C-E-G then up-a-step D-F#-A then up-again is the SAME interval cell."""
    transposed = [60, 64, 67, 62, 66, 69, 64, 68, 71]  # +4,+3 cell, each entry +2
    cov = repetition_coverage(transposed)
    assert cov is not None and cov > 0.8


def test_multi_interval_so_a_single_repeated_interval_does_not_inflate():
    """A run of equal intervals (a whole-tone climb) is a SINGLE repeated interval,
    not a motivic cell — it must NOT inflate the number (research C4)."""
    equal_steps = [60, 62, 64, 66, 68, 70, 72, 74, 76, 78]  # all +2
    cov = repetition_coverage(equal_steps)
    assert cov is not None and cov < 0.1


def test_none_for_too_short_a_line():
    # fewer than 2 * _MIN_GRAM_INTERVALS intervals -> undefined, not zero
    assert repetition_coverage([60, 62, 64]) is None
    assert repetition_coverage([60]) is None
    assert repetition_coverage([]) is None


def test_c7_null_recorded_in_docstring():
    """The C7 null: motivic-rarity does NOT predict memorability — no
    'make it catchier' lever. Recorded in the module docstring; asserted so the
    honesty note can't be silently dropped."""
    doc = inspect.getdoc(economy) or ""
    assert "C7 null" in doc
    assert "make it catchier" in doc
    # the heavyweight theory is NAMED but NOT shipped (the lens's honesty pattern)
    assert "COSIATEC" in doc
    assert "Kolmogorov" in doc
