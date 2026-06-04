"""Per-section onset density (ARR-7M3D's second energy-realization correlate).

CALIBRATION-FIRST (the learning "DSP with a detection front-end: calibrate
against real cases, don't assert from intuition"): these assertions were locked
only AFTER running the sharp-attack ``click`` corpus through the real
``section_onset_density`` and reading the numbers. The calibration revealed a
systematic, well-understood offset:

  * The very FIRST onset of a buffer that starts at sample 0 is NOT detectable
    — spectral flux needs preceding frames (documented in ``onsets.py``). So an
    N-onset stem reads N-1 onsets. The quarter-note 8-onset pulse reads 0.875
    (= 7/8) onsets/beat, the 8th-note 16-onset pulse reads 1.875 (= 15/8), the
    16th-note 32-onset pulse reads 3.875 (= 31/8).

  * This is a CONSTANT -1-onset-per-stem offset. Because the energy-realization
    lens reads density as a RELATIVE rank across sections (only the ordering
    feeds Spearman ρ), the offset cancels in the ranking when sections have the
    same active-stem count, and density correctly ranks a busier section above a
    sparser one. CAVEAT (carried into the lens + the e2e calibration): the
    offset is per-STEM, so across sections with DIFFERENT active-stem counts the
    offset differs — which is why loudness-ρ is the PRIMARY correlate and
    density is the corroborating second signal, never a confidently-precise
    absolute number.

These tests pin the calibrated values, NOT intuited ideals.
"""
from __future__ import annotations

import numpy as np

from hallucinote.audio.density import section_onset_density

from .fixtures import SAMPLE_RATE, onsets_at_beats

SR = SAMPLE_RATE
BPM = 120.0


def _stem(beat_positions, total_beats):
    return onsets_at_beats(
        beat_positions, bpm=BPM, total_beats=total_beats, sr=SR,
    )


def test_quarter_pulse_density_is_calibrated_value():
    """A single stem with 8 quarter-note onsets over 8 beats reads 0.875
    onsets/beat — 7 detected (the sample-0 onset is undetectable). Calibrated,
    not the intuited 1.0."""
    stems = [("kick", _stem([0, 1, 2, 3, 4, 5, 6, 7], 8.0))]
    d = section_onset_density(stems, SR, window_beats=8.0)
    assert d == 0.875


def test_eighth_pulse_reads_denser_than_quarter():
    """A 16-onset 8th pulse reads ~1.875/beat — denser than the quarter pulse.
    The ranking (the only thing the lens uses) is preserved."""
    eighths = [i * 0.5 for i in range(16)]
    quarter = [("k", _stem([0, 1, 2, 3, 4, 5, 6, 7], 8.0))]
    d_eighth = section_onset_density([("hat", _stem(eighths, 8.0))], SR, window_beats=8.0)
    d_quarter = section_onset_density(quarter, SR, window_beats=8.0)
    assert d_eighth == 1.875
    assert d_eighth > d_quarter


def test_density_sums_across_stems():
    """Density is summed across stems: a busy section (quarter + 8th, 2 stems)
    ranks above a sparse one (quarter only). 7/8 + 15/8 = 22/8 = 2.75."""
    eighths = [i * 0.5 for i in range(16)]
    busy = [
        ("kick", _stem([0, 1, 2, 3, 4, 5, 6, 7], 8.0)),
        ("hat", _stem(eighths, 8.0)),
    ]
    sparse = [("kick", _stem([0, 1, 2, 3, 4, 5, 6, 7], 8.0))]
    d_busy = section_onset_density(busy, SR, window_beats=8.0)
    d_sparse = section_onset_density(sparse, SR, window_beats=8.0)
    assert d_busy == 2.75
    assert d_busy > d_sparse


def test_sixteenth_pulse_ranks_densest():
    """A 32-onset 16th pulse reads ~3.875/beat — the densest single-stem case."""
    sixteenths = [i * 0.25 for i in range(32)]
    d = section_onset_density([("hat", _stem(sixteenths, 8.0))], SR, window_beats=8.0)
    assert d == 3.875


def test_silent_window_density_is_zero():
    """A silent stem (no onsets) reads 0.0 — never raises, never nan. Mirrors
    the _measure_sections skip discipline."""
    n = int(round(8.0 * SR * 60.0 / BPM))
    silent = np.zeros((n, 2), dtype=np.float32)
    d = section_onset_density([("pad", silent)], SR, window_beats=8.0)
    assert d == 0.0


def test_empty_stem_list_density_is_zero():
    """No stems → 0.0 density (not an error, not nan)."""
    assert section_onset_density([], SR, window_beats=8.0) == 0.0


def test_nonpositive_window_returns_zero_not_nan():
    """A zero/negative window_beats returns 0.0 rather than dividing by zero —
    the degenerate case the lens excludes by start_beat, never a crash or nan."""
    stems = [("k", _stem([0, 1], 8.0))]
    assert section_onset_density(stems, SR, window_beats=0.0) == 0.0
    assert section_onset_density(stems, SR, window_beats=-4.0) == 0.0


def test_too_short_audio_returns_zero():
    """A stem too short to frame yields 0 onsets → 0.0 density, no raise."""
    tiny = np.zeros((64, 2), dtype=np.float32)
    assert section_onset_density([("k", tiny)], SR, window_beats=2.0) == 0.0
