"""Per-section onset (event) density — the second energy-realization correlate.

ARR-7M3D's energy-realization lens ranks declared per-section energy against
*measured* per-section intensity. Loudness (LUFS-S median) is the dominant
correlate and is already in ``SectionMetrics``. This module supplies the second:
**onset/event density** — how busy a section is — summed across the stems the
section window already slices, divided by the window's length in beats.

Reuses the calibrated shared onset front-end (``onsets.detect_onset_samples`` +
``onsets.dedup_onsets``) — no new detector. Per the learning "DSP with a
detection front-end: calibrate against real cases, don't assert from intuition",
the test suite calibrates this against a sharp-attack synthetic click fixture
(``tests/unit/audio/test_density.py``) and the e2e render (ARR-7M3D chunk 5)
prints real per-section densities before any assertion is trusted.

Level-blind by construction: onsets are detected from spectral flux, which does
not move with a static gain change, so density needs no ``stem_gains``
reconstruction (matching the timing/cross-rhythm passes). It is a *relative*
read across sections — only the ranking feeds Spearman — so a constant
per-detector offset cancels and the absolute density value is informational, not
a calibrated target.

Pure DSP, DB-agnostic, no MixReport coupling — the same layer as ``onsets`` /
``timing``.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from .onsets import (
    DEFAULT_HOP,
    DEFAULT_MIN_ONSET_SEPARATION_BEATS,
    dedup_onsets,
    detect_onset_samples,
    to_mono,
)


def section_onset_density(
    stem_segments: Sequence[tuple[str, np.ndarray]],
    sample_rate: int,
    *,
    window_beats: float,
    min_onset_separation_beats: float = DEFAULT_MIN_ONSET_SEPARATION_BEATS,
    hop_length: int = DEFAULT_HOP,
) -> float:
    """Onsets-per-beat summed across the section's stems.

    ``stem_segments`` entries are ``(track_id, audio)`` where audio is the
    already-windowed mono ``(n,)`` or stereo ``(n, 2)`` slice for this section —
    the same ``sliced_stems`` the masking/timing passes consume. ``window_beats``
    is the section's length in beats (the caller owns the beat geometry, like the
    timing pass). Each stem's onsets are detected via the shared spectral-flux
    front-end and deduped per-stem (one musical event → one onset, so a kick's
    pitch-sweep double-trigger doesn't inflate density); the kept onset counts
    are SUMMED across stems and divided by ``window_beats``.

    Summing across stems (not per-stem) is the intensity read: a busier section
    has more simultaneous activity across more parts. The dedup is per-stem
    because two different stems hitting the same beat are two events (a kick and
    a snare on beat 1 is denser than a lone kick), whereas one stem's flam is
    one event.

    Returns ``0.0`` for an empty stem list, a non-positive ``window_beats``, or
    a window with no detected onsets — never raises and never returns ``nan``,
    mirroring the ``_measure_sections`` skip discipline (the lens excludes a
    degenerate section by ``start_beat``, it does not crash on it). The dedup
    works in beats, so onsets are mapped samples→beats first using the same
    constant-window geometry the timing pass uses (``window_beats`` over the
    slice length).
    """
    if window_beats <= 0.0 or sample_rate <= 0:
        return 0.0

    total_onsets = 0
    for _track_id, audio in stem_segments:
        mono = to_mono(audio)
        n = mono.shape[0]
        if n <= 0:
            continue
        onset_samples = detect_onset_samples(mono, sample_rate, hop_length)
        if onset_samples.size == 0:
            continue
        # Map samples → beats over the window's constant geometry so dedup's
        # beat-domain merge window matches the rest of the onset front-end.
        beats_per_sample = window_beats / n
        onset_beats = onset_samples.astype(np.float64) * beats_per_sample
        onset_beats = dedup_onsets(onset_beats, min_onset_separation_beats)
        total_onsets += int(onset_beats.size)

    return total_onsets / window_beats


__all__ = ["section_onset_density"]
