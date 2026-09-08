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


def _hit_count(res) -> int:
    """The picker's count, whichever side of the failure channel it landed on.

    A part whose every hit is censored is a SKIP, not a shape — but the skip
    still carries what the picker found, which is what the picker's own tests
    are asserting."""
    if res.parts:
        return res.parts[0].hit_count
    return res.skipped[0]["hit_count"]


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
    assert p.attack_click_2k_6k_db > t.attack_click_2k_6k_db


def test_band_differences_are_level_blind():
    loud = _one(_punchy() * 4.0)
    quiet = _one(_punchy() * 0.25)
    assert abs(loud.click_minus_sub_db - quiet.click_minus_sub_db) < 0.5
    assert abs(loud.low_minus_sub_db - quiet.low_minus_sub_db) < 0.5
    assert abs(loud.rise_ms - quiet.rise_ms) < 0.5
    # absolute attack levels DO move with level (they are dBFS of the stem)
    assert loud.attack_sub_40_100_db > quiet.attack_sub_40_100_db + 20.0


def test_parts_without_low_band_hits_are_skipped_with_a_reason():
    pad = sine(440.0, 5.0)                          # no 40-150 Hz transient
    two = _hits(kick_onset(), n=2)                  # below min_hits
    res = analyze_transients_window(
        [("pad", pad), ("sparse", two), ("kick", _punchy())], SR,
    )
    assert [p.track_id for p in res.parts] == ["kick"]
    by_id = {s["track_id"]: s for s in res.skipped}
    assert by_id["pad"]["kind"] in ("no_low_band_energy", "too_few_hits")
    assert by_id["sparse"]["kind"] == "too_few_hits"
    assert by_id["sparse"]["hit_count"] == 2 and by_id["sparse"]["min_hits"] == 4


def test_too_short_or_silent_window_is_a_named_skip_not_silence():
    short = analyze_transients_window([("k", np.zeros((100, 2), np.float32))], SR)
    assert short.parts == [] and short.skipped[0]["kind"] == "window_too_short"
    silent = analyze_transients_window([("k", np.zeros((SR * 2, 2), np.float32))], SR)
    assert silent.parts == [] and silent.skipped[0]["kind"] == "no_low_band_energy"
    assert analyze_transients_window([("k", _punchy())], 0).skipped[0]["kind"] == "invalid_sample_rate"


def test_min_hits_and_peak_rel_decide_whether_a_part_appears():
    three = _hits(kick_onset(), n=3)
    assert analyze_transients_window([("k", three)], SR, min_hits=3).parts[0].hit_count == 3
    assert analyze_transients_window([("k", three)], SR, min_hits=4).skipped[0]["kind"] == "too_few_hits"
    # four loud hits + four at -18 dB: a 25 % floor keeps the quiet ones out,
    # a 5 % floor counts them
    body = kick_onset(duration_s=0.3, decay_s=0.10)
    buf = np.zeros((int(5.0 * SR), 2), dtype=np.float32)
    for i in range(8):
        s = int(i * 0.5 * SR)
        buf[s:s + body.shape[0]] += body * (1.0 if i % 2 == 0 else 0.125)
    assert analyze_transients_window([("k", buf)], SR, peak_rel=0.25).parts[0].hit_count == 4
    # the height floor and the prominence floor are a pair: lowering both
    # admits the quiet hits (>= rather than ==: a low floor can also admit a
    # hit's own secondary envelope lobe — the point is the quiet hits count)
    low = analyze_transients_window([("k", buf)], SR, peak_rel=0.05, prominence_rel=0.05)
    assert low.parts[0].hit_count >= 8


def test_prominence_rejects_a_bump_riding_a_tail():
    # a small second hit 100 ms into a big hit's ring: with the default
    # prominence it is part of the first hit's decay; with no prominence floor
    # it counts as a hit of its own
    big = kick_onset(duration_s=0.6, f_start_hz=60.0, f_end_hz=50.0, decay_s=0.4)
    small = kick_onset(duration_s=0.2, f_start_hz=60.0, f_end_hz=50.0, decay_s=0.05) * 0.4
    buf = np.zeros((int(5.0 * SR), 2), dtype=np.float32)
    for i in range(4):
        s = int(i * 1.0 * SR)
        buf[s:s + big.shape[0]] += big
        s2 = s + int(0.100 * SR)
        buf[s2:s2 + small.shape[0]] += small
    # The composite peak here IS the bump (the small hit rides high enough on
    # the big one's decay to outrank its onset), so every rise is censored and
    # the part is a skip — the picker's count is what this test is about, and
    # the skip carries it.
    assert _hit_count(analyze_transients_window([("k", buf)], SR)) == 4
    assert _hit_count(analyze_transients_window([("k", buf)], SR, prominence_rel=0.0)) > 4


def test_min_sep_counts_fast_sixteenths_separately():
    # kicks 100 ms apart (16ths at 150 BPM): the 90 ms default separates them,
    # a 200 ms separation merges neighbours and under-counts
    body = kick_onset(duration_s=0.09, decay_s=0.03)
    buf = np.zeros((int(4.0 * SR), 2), dtype=np.float32)
    for i in range(16):
        s = int((0.5 + i * 0.1) * SR)
        buf[s:s + body.shape[0]] += body
    assert analyze_transients_window([("k", buf)], SR).parts[0].hit_count == 16
    assert analyze_transients_window([("k", buf)], SR, min_sep_s=0.2).parts[0].hit_count < 16


def test_censored_estimators_are_counted_not_reported():
    # a ring still above 10 % of the NEXT hit's peak 60 ms before it: every
    # rise is censored, so every attack window is unplaceable too (it is
    # anchored on the 10 % point) and the part is a SKIP naming that — not four
    # band levels read over a window that was never placed
    long_ring = kick_onset(duration_s=1.0, f_start_hz=60.0, f_end_hz=50.0, decay_s=1.5)
    res = analyze_transients_window([("k", _hits(long_ring, n=4, spacing_s=1.0, total_s=5.0))], SR)
    assert not res.parts
    assert res.skipped[0]["kind"] == "all_hits_censored"
    assert res.skipped[0]["hit_count"] == 4

    # a ring that never falls 20 dB inside the 600 ms cap but decays enough to
    # leave the next hit's rise clean: t20 is None and counted, while rise_ms
    # is still reported — the estimators censor independently
    ring = kick_onset(duration_s=0.9, f_start_hz=60.0, f_end_hz=50.0, decay_s=0.30)
    t = _one(_hits(ring, n=4, spacing_s=0.85, total_s=3.9), "k")
    assert t.hit_count == 4
    assert t.t20_ms is None and t.censored_t20_hits == 4
    assert t.rise_ms is not None
    # a rise-censored hit is ALWAYS attack-censored: without a 10 % point there
    # is nothing to anchor the attack window on, so its bands never enter the
    # medians (the first hit here starts at the slice edge)
    assert t.censored_rise_hits == 1 and t.censored_attack_hits == 1
    # a normal kick census: no rise censored except the one at the slice edge
    n = _one(_punchy())
    assert n.rise_ms is not None and n.censored_rise_hits <= 1
    # a hit 12 ms before the slice end: its peak is inside the slice but its
    # attack window (which must reach 15 ms past the peak) is cut — censored,
    # excluded from the bands, still counted as a hit
    body = kick_onset(duration_s=0.3, decay_s=0.10)
    buf = _hits(body, n=4, spacing_s=0.5, total_s=2.5)
    tail = int(0.012 * SR)
    buf[-tail:] += body[:tail]
    t = analyze_transients_window([("k", buf)], SR).parts[0]
    assert t.hit_count == 5
    # two censored attacks from the two different causes the count covers: the
    # slice-end cut just planted, and the slice-edge hit whose rise is censored
    # (no 10 % point, so no window to place)
    assert t.censored_rise_hits == 1
    assert t.censored_attack_hits == 2


def _two_lobe_kick(first_rel: float, *, sep_s: float = 0.032, n: int = 6) -> np.ndarray:
    """A kick whose LOW BAND has two comparable lobes ``sep_s`` apart.

    The shape that made the forward-scanning rise estimator bimodal — on the
    alien kit the two lobes sit 31.8 ms apart, invariant across the song.
    ``first_rel`` scales the first lobe, sweeping it across the 90 % line.
    """
    lobe = kick_onset(duration_s=0.25, f_start_hz=80.0, f_end_hz=55.0, decay_s=0.008)
    buf = np.zeros((int(5.0 * SR), 2), dtype=np.float32)
    for i in range(n):
        s = int((0.3 + i * 0.7) * SR)
        buf[s:s + lobe.shape[0]] += lobe * first_rel
        s2 = s + int(sep_s * SR)
        buf[s2:s2 + lobe.shape[0]] += lobe
    return buf


def _first_lobe_ratio(audio: np.ndarray) -> float:
    """Median height of the lobe BEFORE the peak, as a fraction of the peak.

    The quantity the old forward-scanning estimator turned on: at or above 0.90
    it captured the 90 % crossing and the rise collapsed to the first lobe's.
    Measured the way the lens measures — same band, same envelope, same picker.
    """
    from scipy.signal import find_peaks, hilbert

    from hallucinote.audio.onsets import to_mono
    from hallucinote.audio.transients import _bandpass

    mono = to_mono(audio).astype(np.float64)
    env = np.abs(hilbert(_bandpass(mono, SR, 40.0, 150.0)))
    k = max(1, int(0.005 * SR))
    env = np.convolve(env, np.ones(k) / k, mode="same")
    top = float(env.max())
    peaks, _ = find_peaks(env, height=0.25 * top, prominence=0.5 * top,
                         distance=max(1, int(0.09 * SR)))
    ratios = []
    for p in peaks:
        win = env[max(0, p - int(0.060 * SR)):p + 1]
        pre = win[:max(1, len(win) - int(0.012 * SR))]
        ratios.append(float(pre.max() / env[p]))
    return float(np.median(ratios))


def test_a_two_lobe_hit_does_not_read_bimodally_across_the_90_percent_line():
    # The rise is measured on the FINAL approach to the peak. Scanning forward
    # from the search window's edge instead, a first lobe that clears 0.90 x
    # peak captures the 90 % crossing and the reading collapses to THAT lobe's
    # rise — so a 1 % change in one lobe's height moved rise_ms by ~30 ms.
    # (alien, 2026-09-08: verse 1 read 42 ms and eight other sections 16 ms off
    # the same kick, and a mix edit that lowered every section's first lobe by
    # the same amount flipped exactly the two that crossed 0.90.)
    rises, ratios = [], []
    for first_rel in (0.86, 0.88, 0.895, 0.905, 0.92, 0.96):
        audio = _two_lobe_kick(first_rel)
        t = _one(audio)
        assert t.hit_count == 6  # one hit per pair: the lobes are closer than min_sep
        assert t.rise_ms is not None and t.censored_rise_hits == 0
        rises.append(t.rise_ms)
        ratios.append(_first_lobe_ratio(audio))
    # The sweep is only a test of this at all if it STRADDLES the 0.90 line the
    # old estimator turned on — pin that, or a fixture change that lands all six
    # on one side passes green over a forward-scanning regression.
    assert min(ratios) < 0.90 < max(ratios), ratios
    assert max(rises) - min(rises) < 3.0, rises
    # and it is the LATER lobe's approach that is measured throughout — never a
    # short reading borrowed from the first lobe
    assert min(rises) > 30.0, rises
