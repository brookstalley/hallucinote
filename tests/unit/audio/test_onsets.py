"""Tests for the shared onset front-end — focused on the C8c accent dimension.

Onset *detection* (sample-accurate times) is exercised indirectly by
``test_timing.py`` / ``test_cross_rhythm.py``; this file pins the new per-onset
**accent strength** the grouping/polymeter decoders read. Correctness was
calibrated against the real librosa pipeline (amplitude-scaled clicks run
through the actual front-end, recovered strengths eyeballed) before these
assertions were locked — not asserted from intuition.
"""
from __future__ import annotations

import numpy as np

from hallucinote.audio.onsets import (
    DEFAULT_MIN_ONSET_SEPARATION_BEATS,
    dedup_onsets_with_strength,
    detect_onset_samples,
    detect_onsets_with_strength,
)

from .fixtures import SAMPLE_RATE, onsets_at_beats, silence

BPM = 120.0


def _detect(beats, amps=None, total_beats=8.0):
    audio = onsets_at_beats(beats, bpm=BPM, total_beats=total_beats, amplitudes=amps)
    mono = audio[:, 0] + audio[:, 1]
    return detect_onsets_with_strength(mono, SAMPLE_RATE)


# --------------------------------------------------------------------------- #
# Strength = accent: flat on equal hits, faithful on accents, monotonic on amp
# --------------------------------------------------------------------------- #

def test_equal_velocity_hits_read_flat_strength():
    """Byte-identical clicks at a steady pulse must NOT produce a spurious
    accent pattern — the single-flux-frame approach did (sub-hop alignment ramp);
    peak-amplitude is flat. This is the bug the calibration pass caught."""
    samples, strengths = _detect([i * 0.5 for i in range(16)])
    assert strengths.size >= 12
    norm = strengths / strengths.max()
    assert float(norm.std()) < 0.05  # essentially flat


def test_accent_pattern_is_recovered_faithfully():
    """A 2× louder hit every 4th onset reads ~2× the strength of the others."""
    amps = [2.0 if i % 4 == 0 else 1.0 for i in range(16)]
    samples, strengths = _detect([i * 0.5 for i in range(16)], amps=amps)
    norm = strengths / strengths.max()
    loud = norm[norm > 0.75]
    quiet = norm[norm <= 0.75]
    assert loud.size >= 3 and quiet.size >= 6
    # Accent ratio preserved: quiet hits ~0.5 of the loud ones (the 1:2 amp).
    assert 0.4 <= float(quiet.mean()) <= 0.6


def test_strength_is_monotonic_in_amplitude():
    """A click amplitude ramp produces a monotonically increasing strength."""
    amps = [0.25 + 0.25 * i for i in range(8)]
    samples, strengths = _detect([i * 0.5 for i in range(8)], amps=amps, total_beats=4.5)
    # Strictly non-decreasing (the front-end drops the sample-0 onset, so the
    # series starts at the 2nd-quietest hit — still monotonic upward).
    assert np.all(np.diff(strengths) > -1e-9)
    assert strengths[-1] > strengths[0]


def test_samples_match_plain_detector():
    """The strength variant returns the SAME onset samples as the plain
    detector — only the extra strength array is new (detection is unchanged)."""
    beats = [i * 0.5 for i in range(16)]
    audio = onsets_at_beats(beats, bpm=BPM, total_beats=8.0)
    mono = audio[:, 0] + audio[:, 1]
    plain = detect_onset_samples(mono, SAMPLE_RATE)
    samples, _ = detect_onsets_with_strength(mono, SAMPLE_RATE)
    assert np.array_equal(plain, samples)


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #

def test_silent_audio_returns_empty():
    mono = silence(2.0)[:, 0]
    samples, strengths = detect_onsets_with_strength(mono, SAMPLE_RATE)
    assert samples.size == 0 and strengths.size == 0


def test_too_short_audio_returns_empty():
    samples, strengths = detect_onsets_with_strength(
        np.zeros(64, dtype=np.float32), SAMPLE_RATE
    )
    assert samples.size == 0 and strengths.size == 0


def test_samples_and_strengths_are_index_aligned():
    samples, strengths = _detect([i * 0.5 for i in range(12)])
    assert samples.size == strengths.size
    assert strengths.dtype == np.float64
    assert np.all(strengths >= 0.0)


# --------------------------------------------------------------------------- #
# Strength-carrying dedup
# --------------------------------------------------------------------------- #

def test_dedup_keeps_max_strength_of_cluster():
    """Two near-coincident onsets (a flam) collapse to one event carrying the
    LOUDER sub-hit's strength — not whichever librosa detected first."""
    beats = np.asarray([1.0, 1.02, 2.0], dtype=np.float64)  # first two within window
    strengths = np.asarray([0.3, 0.9, 0.5], dtype=np.float64)
    db, ds = dedup_onsets_with_strength(beats, strengths, DEFAULT_MIN_ONSET_SEPARATION_BEATS)
    assert db.size == 2  # 1.0 and 1.02 merged
    assert ds[0] == 0.9  # max of the merged cluster, not 0.3
    assert ds[1] == 0.5


def test_dedup_no_merge_preserves_strengths():
    beats = np.asarray([1.0, 2.0, 3.0], dtype=np.float64)
    strengths = np.asarray([0.3, 0.9, 0.5], dtype=np.float64)
    db, ds = dedup_onsets_with_strength(beats, strengths, DEFAULT_MIN_ONSET_SEPARATION_BEATS)
    assert np.array_equal(db, beats)
    assert np.array_equal(ds, strengths)


def test_dedup_empty_and_single():
    empty = np.asarray([], dtype=np.float64)
    db, ds = dedup_onsets_with_strength(empty, empty, 0.06)
    assert db.size == 0 and ds.size == 0
    one_b, one_s = np.asarray([1.0]), np.asarray([0.7])
    db, ds = dedup_onsets_with_strength(one_b, one_s, 0.06)
    assert db.size == 1 and ds[0] == 0.7
