"""Segments: onsets land on the pulse period; phrases open and close on the
envelope with hysteresis; the syllable rate counts onsets inside a phrase."""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.features.segments import (
    onset_segments,
    onset_times,
    phrase_segments,
    syllable_rate,
)
from hallucinote.features.types import Segment
from tests.unit.audio.fixtures import SAMPLE_RATE, concat, silence, sine

SR = SAMPLE_RATE


def _pulsed_tone(period_s: float, duration_s: float, *, first_at_s: float = 0.1, decay_s: float = 0.02) -> np.ndarray:
    """A 440 Hz ping every ``period_s``, each decaying smoothly to nothing."""
    n = int(round(duration_s * SR))
    buf = np.zeros(n)
    ping_len = int(round(6 * decay_s * SR))
    k = np.arange(ping_len, dtype=np.float64)
    ping = 0.5 * np.sin(2.0 * np.pi * 440.0 * k / SR) * np.exp(-k / (decay_s * SR))
    t = first_at_s
    while t < duration_s:
        s = int(round(t * SR))
        e = min(s + ping_len, n)
        buf[s:e] += ping[: e - s]
        t += period_s
    mono = buf.astype(np.float32)
    return np.stack([mono, mono], axis=1)


def test_onsets_on_a_pulsed_tone_match_the_pulse_period():
    period = 0.25
    times = onset_times(_pulsed_tone(period, 2.0), SR)
    assert times.size == 8
    assert np.allclose(np.diff(times), period, atol=0.010)
    assert times[0] == pytest.approx(0.1, abs=0.010)


def test_onset_segments_tile_from_each_onset_to_the_next_and_the_end():
    audio = _pulsed_tone(0.25, 2.0)
    segs = onset_segments(audio, SR)
    assert all(isinstance(s, Segment) and s.kind == "onset" for s in segs)
    assert len(segs) == 8
    for a, b in zip(segs, segs[1:]):
        assert a.end_s == b.start_s
    assert segs[-1].end_s == pytest.approx(2.0)
    assert segs[0].duration_s == pytest.approx(0.25, abs=0.010)


def test_silence_has_no_onsets_and_no_segments():
    assert onset_times(silence(0.5), SR).size == 0
    assert onset_segments(silence(0.5), SR) == []


def test_phrases_are_silence_bounded_and_survive_a_breath():
    audio = concat(
        silence(0.5),
        sine(300.0, 0.8),
        silence(0.08),       # a breath — shorter than the gap that closes a phrase
        sine(300.0, 0.4),
        silence(0.5),
        sine(300.0, 0.6),
        silence(0.3),
    )
    phrases = phrase_segments(audio, SR)
    assert [p.kind for p in phrases] == ["phrase", "phrase"]
    # Boundaries land within half an RMS frame plus one hop (~30 ms) of the truth.
    assert phrases[0].start_s == pytest.approx(0.5, abs=0.05)
    assert phrases[0].end_s == pytest.approx(1.78, abs=0.05)
    assert phrases[1].start_s == pytest.approx(2.28, abs=0.05)
    assert phrases[1].end_s == pytest.approx(2.88, abs=0.05)


def test_a_short_gap_splits_phrases_when_it_exceeds_min_gap():
    audio = concat(silence(0.2), sine(300.0, 0.5), silence(0.08), sine(300.0, 0.5), silence(0.2))
    assert len(phrase_segments(audio, SR)) == 1
    assert len(phrase_segments(audio, SR, min_gap_s=0.02)) == 2


def test_explicit_threshold_drops_a_quiet_phrase():
    # -9 dBFS then -29 dBFS: the quiet phrase clears the default (peak - 30 dB)
    # threshold but not an explicit -20 dBFS one.
    audio = concat(silence(0.2), sine(300.0, 0.5, amplitude=0.5), silence(0.3), sine(300.0, 0.5, amplitude=0.05), silence(0.2))
    assert len(phrase_segments(audio, SR)) == 2
    assert len(phrase_segments(audio, SR, threshold_dbfs=-20.0)) == 1


def test_a_click_is_too_short_to_be_a_phrase():
    audio = concat(silence(0.2), sine(300.0, 0.02), silence(0.3))
    assert phrase_segments(audio, SR) == []
    assert len(phrase_segments(audio, SR, min_phrase_s=0.0)) == 1


def test_silence_yields_no_phrases():
    assert phrase_segments(silence(0.5), SR) == []


def test_syllable_rate_counts_onsets_inside_the_phrase():
    onsets = np.asarray([0.1, 0.35, 0.6, 0.85, 1.4])
    assert syllable_rate(Segment(0.0, 1.0, "phrase"), onsets) == pytest.approx(4.0)
    assert syllable_rate(Segment(1.0, 2.0, "phrase"), onsets) == pytest.approx(1.0)
    assert np.isnan(syllable_rate(Segment(0.5, 0.5, "phrase"), onsets))


def test_syllable_rate_end_to_end_on_a_pulsed_phrase():
    audio = _pulsed_tone(0.25, 2.0)
    rate = syllable_rate(Segment(0.0, 2.0, "phrase"), onset_times(audio, SR))
    assert rate == pytest.approx(4.0)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"hysteresis_db": -1.0}, "hysteresis_db must be >= 0"),
        ({"min_gap_s": -0.1}, "must be >= 0"),
    ],
)
def test_phrase_parameters_are_validated(kwargs, match):
    with pytest.raises(ValueError, match=match):
        phrase_segments(sine(300.0, 0.2), SR, **kwargs)
