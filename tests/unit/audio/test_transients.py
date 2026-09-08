"""Corpus tests for the low-band hit-shape (transient) lens — the corpus IS the spec.

No labelled "punchy vs thuddy" ground truth exists, so correctness is defined
by constructed fixtures: a kick with an instant attack, a short ring and a
beater click must read a shorter rise, a shorter T20 and a click closer to its
sub weight than a kick with a slow fade-in, a long ring and no click. Ordering
is the contract (absolute milliseconds carry the band-pass filter's own rise).
"""
from __future__ import annotations

import numpy as np

from hallucinote.audio.transients import analyze_transients_window

from .fixtures import SAMPLE_RATE, click, kick_onset, sine

SR = SAMPLE_RATE


def _fade_in(audio: np.ndarray, seconds: float) -> np.ndarray:
    n = int(seconds * SR)
    out = audio.copy()
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
    out[:n] *= ramp
    return out


def _hits(onset: np.ndarray, *, n: int = 8, spacing_s: float = 0.5, total_s: float = 5.0):
    buf = np.zeros((int(total_s * SR), 2), dtype=np.float32)
    for i in range(n):
        s = int(i * spacing_s * SR)
        e = min(s + onset.shape[0], buf.shape[0])
        buf[s:e] += onset[: e - s]
    return buf


def _punchy() -> np.ndarray:
    body = kick_onset(duration_s=0.3, decay_s=0.10)
    c = click(amplitude=0.5)
    body[: c.shape[0]] += c
    return _hits(body)


def _thuddy() -> np.ndarray:
    body = kick_onset(duration_s=0.6, f_start_hz=100.0, f_end_hz=60.0, decay_s=0.35)
    return _hits(_fade_in(body, 0.030))


def _one(audio: np.ndarray, track_id: str = "kick"):
    res = analyze_transients_window([(track_id, audio)], SR)
    assert len(res.parts) == 1
    return res.parts[0]


def test_counts_every_hit():
    assert _one(_punchy()).hit_count == 8
    assert _one(_thuddy()).hit_count == 8


def test_punchy_kick_rises_faster_and_rings_shorter_than_a_thud():
    p, t = _one(_punchy()), _one(_thuddy())
    assert p.rise_ms < t.rise_ms
    assert p.t20_ms < t.t20_ms


def test_click_reads_as_a_defined_attack_only_on_the_punchy_kick():
    p, t = _one(_punchy()), _one(_thuddy())
    assert p.click_minus_sub_db > t.click_minus_sub_db + 20.0
    assert p.attack_click_db > t.attack_click_db


def test_band_differences_are_level_blind():
    loud = _one(_punchy() * 4.0)
    quiet = _one(_punchy() * 0.25)
    assert abs(loud.click_minus_sub_db - quiet.click_minus_sub_db) < 0.5
    assert abs(loud.low_minus_sub_db - quiet.low_minus_sub_db) < 0.5
    assert abs(loud.rise_ms - quiet.rise_ms) < 0.5
    # absolute attack levels DO move with level (they are dBFS of the stem)
    assert loud.attack_sub_db > quiet.attack_sub_db + 20.0


def test_parts_without_low_band_hits_are_omitted():
    pad = sine(440.0, 5.0)                          # no 40-150 Hz transient
    two = _hits(kick_onset(), n=2)                  # below min_hits
    res = analyze_transients_window(
        [("pad", pad), ("sparse", two), ("kick", _punchy())], SR,
    )
    assert [p.track_id for p in res.parts] == ["kick"]


def test_too_short_or_silent_window_yields_no_parts():
    assert analyze_transients_window([("k", np.zeros((100, 2), np.float32))], SR).parts == []
    assert analyze_transients_window([("k", np.zeros((SR * 2, 2), np.float32))], SR).parts == []
