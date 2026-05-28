"""Master-bus contribution attribution tests.

Pins success criterion #4 from the audio-analysis MVP build plan:
on a deliberately-overdriven synthetic fixture (kick + bass boosted in
a specific window) the analysis flags overshoot windows AND ranks kick
+ bass as top-2 contributors with combined attribution >60% in the
60-200 Hz band.
"""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.audio.attribution import (
    BANDS,
    find_master_overshoots,
    master_bus_attribution,
)
from hallucinote.audio.io import Surface

from .fixtures import SAMPLE_RATE, sine


def _stereo_zeros(duration_s: float) -> np.ndarray:
    n = int(round(duration_s * SAMPLE_RATE))
    return np.zeros((n, 2), dtype=np.float32)


def _surface(track_id: str, audio: np.ndarray, kind: str = "track") -> Surface:
    return Surface(
        track_id=track_id,
        surface_kind=kind,  # type: ignore[arg-type]
        surface_name=track_id,
        audio=audio,
        sample_rate=SAMPLE_RATE,
    )


def test_bands_table_covers_audible_range():
    """Sanity-check the band definitions match the spike's table."""
    band_names = [b[0] for b in BANDS]
    assert band_names == [
        "sub_20_60",
        "low_60_200",
        "low_mid_200_500",
        "mid_500_2k",
        "high_mid_2k_6k",
        "air_6k_plus",
    ]
    # No gaps between adjacent bands.
    for (_, _, hi), (_, lo_next, _) in zip(BANDS, BANDS[1:]):
        assert hi == lo_next


def test_find_overshoots_returns_empty_when_master_is_quiet():
    quiet_master = sine(440.0, 1.0, amplitude=0.1)
    overshoots = find_master_overshoots(quiet_master, SAMPLE_RATE)
    assert overshoots == []


def test_find_overshoots_detects_synthesized_overshoot_window():
    """Master with a hot section in the middle — should detect exactly
    one overshoot window spanning that section."""
    duration = 4.0
    quiet = sine(440.0, duration, amplitude=0.1)
    # Boost samples 1.5s..2.5s to +1.5 dBFS.
    hot_start = int(1.5 * SAMPLE_RATE)
    hot_end = int(2.5 * SAMPLE_RATE)
    master = quiet.copy()
    master[hot_start:hot_end] *= 12.0  # 0.1 * 12 = 1.2 → ~1.6 dBFS
    overshoots = find_master_overshoots(master, SAMPLE_RATE)
    assert len(overshoots) == 1
    o = overshoots[0]
    # Window covers roughly 1.5..2.5 s (allow generous slop for filter
    # ringing and the merge tolerance).
    assert 1.3 < o.start_s < 1.7
    assert 2.3 < o.end_s < 2.7
    assert o.peak_dbtp > 0.0


def test_attribution_top_two_exceed_60pct_in_dominant_band():
    """Success criterion #4 (build plan Chunk 3-B).

    Three stems play in a 1s window — a 60 Hz tone (kick), a 100 Hz tone
    (bass), and a 1 kHz tone (rhythm). The master is their sum scaled to
    overshoot. The dominant band should be ``low_60_200`` (covers both
    60 and 100 Hz), and kick + bass should make up >60% of energy in
    that band.
    """
    duration = 2.0
    silence_audio = _stereo_zeros(duration)

    # Hot window: 0.5..1.5 s. Tones live only in the hot window.
    kick = silence_audio.copy()
    bass = silence_audio.copy()
    rhythm = silence_audio.copy()
    start = int(0.5 * SAMPLE_RATE)
    end = int(1.5 * SAMPLE_RATE)
    win_dur = (end - start) / SAMPLE_RATE
    kick[start:end] = sine(60.0, win_dur, amplitude=0.6)
    bass[start:end] = sine(100.0, win_dur, amplitude=0.5)
    rhythm[start:end] = sine(1000.0, win_dur, amplitude=0.3)

    master_sum = (kick + bass + rhythm) * 1.5  # push master into overshoot

    stems = [
        _surface("track:1", kick),
        _surface("track:2", bass),
        _surface("track:3", rhythm),
    ]
    overshoots = find_master_overshoots(master_sum, SAMPLE_RATE)
    assert len(overshoots) >= 1
    attributed = master_bus_attribution(master_sum, stems, SAMPLE_RATE, overshoots)
    assert len(attributed) == len(overshoots)
    # Sanity: dominant band is low_60_200 (covers both 60 and 100 Hz).
    o = attributed[0]
    assert o.dominant_band == "low_60_200"
    # Top two by attribution should be kick + bass; combined >60%.
    by_track = dict(o.attribution)
    top_two_sum = by_track.get("track:1", 0.0) + by_track.get("track:2", 0.0)
    assert top_two_sum > 0.60, (
        f"top-2 attribution {top_two_sum:.3f} below 60% threshold; "
        f"full attribution: {o.attribution}"
    )


def test_attribution_skips_silent_stems():
    """A stem with no energy in the dominant band shouldn't pollute the
    attribution percentages — it gets 0 and is sorted to the bottom."""
    duration = 2.0
    silence_audio = _stereo_zeros(duration)
    start = int(0.5 * SAMPLE_RATE)
    end = int(1.5 * SAMPLE_RATE)
    win = (end - start) / SAMPLE_RATE
    kick = silence_audio.copy()
    silent = silence_audio.copy()
    kick[start:end] = sine(80.0, win, amplitude=0.9)
    master = kick * 2.0  # ensure clearly > 0 dBFS

    stems = [_surface("track:1", kick), _surface("track:silent", silent)]
    overshoots = find_master_overshoots(master, SAMPLE_RATE)
    assert overshoots, "synthesized master must overshoot for this test"
    attributed = master_bus_attribution(master, stems, SAMPLE_RATE, overshoots)
    by_track = dict(attributed[0].attribution)
    assert by_track.get("track:silent", 0.0) < 0.01
    assert by_track.get("track:1", 0.0) > 0.95
