"""Per-part drum-hit TRANSIENT SHAPE — the kick-class lens.

The mix report can say how loud a kit is and where its onsets fall, but not
what a hit is *shaped* like: how fast it rises, how long it rings, and whether
its attack is sub weight (40-100 Hz), low-mid thud (100-250 Hz), boxiness
(250-600 Hz) or beater click (2-6 kHz). "The kick is a thud — muffled, muddy
with the other instruments" (the alien dogfood pass, 2026-09-08) was measured
with a throw-away script before it could be worked on; this module is that
script as a standing lens, so a "sharpen the kick" edit moves a number that
``compare_to`` can A/B across renders (``section_deltas``).

Design (see build-plan-aud-sharpness-transients.md):

  * Hits are picked on the LOW band (``band_hz``, default 40-150 Hz), not the
    spectral-flux front-end ``onsets.py`` gives the timing lenses. The question
    is about kick-class hits, and a kit stem's hats and snares would swamp a
    broadband picker. Envelope = |Hilbert| of the band-passed slice, smoothed
    5 ms; peaks at >= ``peak_rel`` of the window's loudest peak, rising at
    least ``prominence_rel`` of it above their surrounding valley, >=
    ``min_sep_s`` apart.
  * Per hit: rise = 10 -> 90 % of the low envelope on its FINAL approach to the
    peak — both thresholds are found by scanning BACKWARD from the peak, so an
    earlier lobe of a two-lobe hit cannot capture the 90 % crossing (searched
    back ``_RISE_SEARCH_S``); T20 = time after the peak for the low envelope to fall
    20 dB (within ``_DECAY_CAP_S``); the ATTACK window = the first 30 ms
    from the 10 % point (reaching at least 15 ms past the peak), over which four
    band RMS levels are read. Medians
    across hits are reported; the two band DIFFERENCES are the level-blind
    punch/thud reads.
  * ``rise_ms`` carries the zero-phase band-pass's pre-ring (a few ms of
    envelope BEFORE the true onset), the same for every hit — so read it as a
    relative number across renders and parts, not as the sample's true attack.
    It is also a reading of the LOW band only: a kick whose beater click leads
    its low-band peak by tens of ms has an attack the hit band never sees, and
    a kick with two low-band lobes has its rise measured across BOTH of them
    whenever the valley between them stays above 10 % of the peak — the 10 %
    point is the last sample under the threshold before the final 90 % crossing,
    which on such a hit is the FIRST lobe's onset (the alien kit reads ~44 ms
    for lobes 31.8 ms apart: the span, not the later lobe's own ~14 ms). That is
    the hit's full rise, and it is stable, which is the property that matters —
    but it is not the later lobe's attack. The
    number is comparable across renders and sections of the SAME kit; it is not
    comparable across kits, and it moves with ``band_hz`` (on the alien kit,
    40-150 Hz reads 44 ms and 50-150 Hz reads 15 ms for the same hits).
    The pre-ring moves the attack window's start by the same few ms on every
    hit; the window is 30 ms from that point (at least 15 ms past the peak).
  * An estimator that hits its own boundary is CENSORED, not reported: a rise
    whose 10 % point was not found inside the search window, a T20 the envelope
    never reached inside the cap or the slice, an attack window with no 10 %
    point to anchor it (its own rise was censored) or cut by the slice end.
    Censored hits are counted (``censored_*``) and excluded from the medians,
    which read ``None`` when nothing survives — never a boundary value dressed
    as a measurement. Rise-censored implies attack-censored, so
    ``all_hits_censored`` is reachable on real material: a part whose hits all
    ride the previous hit's tail is a skip, not four band levels read over a
    window that was never placed.
  * A part with no reading says WHY, as a structured skip (``skipped``) the
    section carries as ``transient_skips`` — the lens has a failure channel,
    so an empty ``transients`` list is never four outcomes wearing one shape.
  * Pure DSP, DB-agnostic — the caller slices stems to the window like the
    timing lens. Absolute band levels are dBFS of the PRE-FADER stem as
    captured (named so in the report); the differences and times are
    level-blind.

Neutral measurement — never a grade; ``/mix-review`` reads it against intent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from .onsets import to_mono
from .report import PartTransient

# Bands (Hz) read over the attack window. The wire names carry their edges
# (like attribution.BANDS) because these edges are NOT attribution's: attack
# "sub" starts at 40 Hz where a kick's fundamental lives, not 20; "low" is the
# 100-250 Hz thud register, not 60-200.
ATTACK_BANDS_HZ: dict[str, tuple[float, float]] = {
    "sub_40_100": (40.0, 100.0),
    "low_100_250": (100.0, 250.0),
    "lowmid_250_600": (250.0, 600.0),
    "click_2k_6k": (2000.0, 6000.0),
}

# The hit picker's band: a kick's fundamental and its first partial; a snare's
# body (150-250 Hz) sits above it and closed hats have nothing here at all.
_DEFAULT_BAND_HZ = (40.0, 150.0)
# Fewer low-band hits than this and the medians are noise — one flam or one
# censored hit would move them. Four is one bar of four-on-the-floor.
_DEFAULT_MIN_HITS = 4
# A hit is a peak at >= this fraction of the window's loudest low-band peak:
# ghost kicks at ~-12 dB still count; a snare's low-band leakage (typically
# -20 dB or more below the kick in this band) does not.
_DEFAULT_PEAK_REL = 0.25
# Two peaks closer than this are one hit. 90 ms is just under a 16th at
# 160 BPM (94 ms), so 16th-note kicks are counted separately up to that tempo.
# Alone it is too permissive on a real kit stem — a snare's low-band leakage
# and a kick's own secondary envelope lobe both make peaks inside a kick's
# tail — so it works together with the prominence floor below.
_DEFAULT_MIN_SEP_S = 0.09
# A hit must rise at least this fraction of the window's loudest peak ABOVE the
# valley around it (scipy's prominence). A bump riding a previous hit's decay
# is not a hit. Measured on the alien kit (verse, chorus 3): 0.5 with 90 ms
# separation picks the same hits as a bare 200 ms separation (19 / 64 hits, 2 /
# 7 rise-censored), where 90 ms alone picked 39 / 125 with half of them
# censored — the extra "hits" were tail lobes and snare leakage.
_DEFAULT_PROMINENCE_REL = 0.5
# Envelope smoothing: 5 ms removes the Hilbert envelope's cycle ripple at
# 40-150 Hz (a 7-25 ms period) without rounding off a real 2-3 ms attack.
_ENVELOPE_SMOOTH_S = 0.005
# How far back from the peak the 10 % point is searched. 60 ms is three times
# the slowest attack the lens can usefully describe; a hit whose envelope is
# still above 10 % of its peak 60 ms before the peak is CENSORED, not reported.
_RISE_SEARCH_S = 0.060
# The attack window: the first 30 ms from the low envelope's 10 % point (the
# onset, give or take the zero-phase filter's pre-ring), extended if needed to
# reach 15 ms past the low-band peak. It is anchored on the ONSET because that
# is where the ear hears "attack": the beater click (at the onset, 5-15 ms
# long) and the thump a kick's pitch sweep starts on before it drops to the
# sub. A window anchored on the peak instead reads the body — on the alien kit
# it turned "low-mids loudest, click 23 dB under the sub" into "sub loudest,
# click 34 dB under", which is not what the ear reported. The peak-coverage
# floor makes the slice-end censoring deterministic (a hit whose peak is within
# 15 ms of the end is censored whatever the pre-ring did to its 10 % point).
_ATTACK_S = 0.030
_ATTACK_POST_PEAK_MIN_S = 0.015
# T20 search cap. A kick that has not fallen 20 dB in 600 ms (≈ a beat at
# 100 BPM) is a drone, not a hit — it is CENSORED, not reported as 600.
_DECAY_CAP_S = 0.600
_DB_FLOOR = 1e-9


@dataclass(frozen=True)
class TransientWindowResult:
    """Per-part transient shapes for one (pre-sliced) window, plus one
    structured skip per part that produced no reading (``kind`` names why —
    the complete set is ``invalid_sample_rate`` / ``window_too_short`` /
    ``no_low_band_energy`` / ``too_few_hits`` / ``all_hits_censored``)."""
    parts: list[PartTransient]
    skipped: list[dict] = field(default_factory=list)


def analyze_transients_window(
    stem_segments: Sequence[tuple[str, np.ndarray]],
    sample_rate: int,
    *,
    band_hz: tuple[float, float] = _DEFAULT_BAND_HZ,
    min_hits: int = _DEFAULT_MIN_HITS,
    peak_rel: float = _DEFAULT_PEAK_REL,
    min_sep_s: float = _DEFAULT_MIN_SEP_S,
    prominence_rel: float = _DEFAULT_PROMINENCE_REL,
) -> TransientWindowResult:
    """Measure each part's low-band hit shape over one window.

    ``stem_segments`` entries are ``(track_id, audio)``, mono ``(n,)`` or stereo
    ``(n, 2)``, already sliced to the window. Every part yields EITHER a
    :class:`PartTransient` OR a skip naming why not (a pad has no kick-class
    transient to describe; a slice shorter than the estimators' windows cannot
    be measured). Parts are returned in input order.
    """
    parts: list[PartTransient] = []
    skipped: list[dict] = []
    if sample_rate <= 0:
        return TransientWindowResult(parts=parts, skipped=[{
            "kind": "invalid_sample_rate", "track_id": None,
            "reason": f"sample_rate={sample_rate} — nothing can be measured",
        }])
    for track_id, audio in stem_segments:
        mono = to_mono(audio).astype(np.float64)
        outcome = _part_transient(
            track_id, mono, sample_rate, band_hz=band_hz, min_hits=min_hits,
            peak_rel=peak_rel, min_sep_s=min_sep_s, prominence_rel=prominence_rel,
        )
        if isinstance(outcome, PartTransient):
            parts.append(outcome)
        else:
            skipped.append(outcome)
    return TransientWindowResult(parts=parts, skipped=skipped)


def _bandpass(mono: np.ndarray, sr: int, lo: float, hi: float) -> np.ndarray:
    """ZERO-PHASE band-pass. The four attack bands must line up in time — a
    causal filter gives each band its own group delay (tens of ms at 40-150 Hz,
    nothing at 2-6 kHz), which put the click outside the low band's window. The
    price is a few ms of pre-ring before each onset, the same for every hit."""
    from scipy.signal import butter, sosfiltfilt

    nyq = sr / 2.0
    hi = min(hi, nyq * 0.99)
    if lo >= hi:
        return np.zeros_like(mono)
    sos = butter(4, [lo, hi], btype="band", fs=sr, output="sos")
    return sosfiltfilt(sos, mono)


def _rms_db(x: np.ndarray) -> float:
    if x.size == 0:
        return float("-inf")
    return float(20.0 * np.log10(np.sqrt(np.mean(x * x)) + _DB_FLOOR))


def _median_or_none(values: list[float]) -> float | None:
    return float(np.median(values)) if values else None


def _part_transient(
    track_id: str, mono: np.ndarray, sr: int, *, band_hz, min_hits, peak_rel,
    min_sep_s, prominence_rel,
) -> PartTransient | dict:
    """The part's shape, or the skip naming why there is none — never both and
    never neither. Returning ONE value rather than a (shape, skip) pair is that
    invariant made unrepresentable: a pair can hold two Nones or two values, and
    a caller then has to narrow twice and still cannot prove the second."""
    from scipy.signal import find_peaks, hilbert

    n_search = int(_RISE_SEARCH_S * sr)
    n_attack, n_post_min = int(_ATTACK_S * sr), int(_ATTACK_POST_PEAK_MIN_S * sr)
    n_decay = int(_DECAY_CAP_S * sr)
    min_len = n_decay + n_search + 1
    if mono.shape[0] < min_len:
        return {
            "kind": "window_too_short", "track_id": track_id,
            "reason": (f"slice is {mono.shape[0] / sr * 1000:.0f} ms; the rise/decay "
                       f"estimators need {min_len / sr * 1000:.0f} ms"),
        }
    low = _bandpass(mono, sr, *band_hz)
    env = np.abs(hilbert(low))
    k = max(1, int(_ENVELOPE_SMOOTH_S * sr))
    env = np.convolve(env, np.ones(k) / k, mode="same")
    top = float(env.max())
    if top <= 0.0:
        return {
            "kind": "no_low_band_energy", "track_id": track_id,
            "reason": f"nothing in the {band_hz[0]:.0f}-{band_hz[1]:.0f} Hz hit band",
        }
    peaks, _ = find_peaks(
        env, height=peak_rel * top, prominence=prominence_rel * top,
        distance=max(1, int(min_sep_s * sr)),
    )
    if peaks.size < min_hits:
        return {
            "kind": "too_few_hits", "track_id": track_id, "hit_count": int(peaks.size),
            "min_hits": int(min_hits),
            "reason": (f"{int(peaks.size)} low-band hit(s) at >= {peak_rel:.0%} of the loudest; "
                       f"the medians need {min_hits}"),
        }

    rises: list[float] = []
    t20s: list[float] = []
    censored_rise = censored_t20 = censored_attack = 0
    bands: dict[str, list[float]] = {b: [] for b in ATTACK_BANDS_HZ}
    band_signals = {b: _bandpass(mono, sr, lo, hi) for b, (lo, hi) in ATTACK_BANDS_HZ.items()}
    for p in peaks:
        pv = env[p]
        w0 = max(0, p - n_search)
        win = env[w0:p + 1]
        # The rise is the FINAL approach to the peak: scan BACKWARD from the
        # peak for the last sample under each threshold. Scanning FORWARD from
        # the window's edge instead lets an EARLIER envelope lobe capture the
        # 90 % crossing, which makes the estimator bimodal on any hit whose low
        # band has two comparable lobes: whether that lobe clears 0.90 x peak
        # decides which one is measured, so a 1 % change in its height moves
        # rise_ms by tens of ms. Measured on the alien kit (two lobes 31.8 ms
        # apart, invariant across the song): forward-scanning read 16 ms in
        # eight sections and 42-44 ms in two, off the same sample, and a mix
        # edit that lowered every section's first lobe by the same ~0.04 of the
        # peak flipped exactly the two that crossed 0.90. Backward-scanning
        # reads 43.6-44.6 ms in all ten and shows the mix edit as the uniform
        # -1.3 ms it was.
        below90 = np.nonzero(win < 0.90 * pv)[0]
        i90_rel = int(below90[-1]) + 1 if below90.size else 0
        below10 = np.nonzero(win[:i90_rel + 1] < 0.10 * pv)[0]
        # Censored rise: the envelope never fell under 10 % inside the search
        # window, so the true 10 % point is earlier than we can see.
        if below10.size:
            i10_rel = int(below10[-1]) + 1
            i10 = w0 + i10_rel
            rises.append((i90_rel - i10_rel) / sr * 1000.0)
        else:
            censored_rise += 1
            i10 = None
        # Censored T20: never fell 20 dB inside the cap, or the slice ended first.
        after = env[p:p + n_decay]
        below = np.nonzero(after <= pv * 10.0 ** (-20.0 / 20.0))[0]
        if below.size:
            t20s.append(float(below[0]) / sr * 1000.0)
        else:
            censored_t20 += 1
        # Censored attack window: no onset to anchor it, or cut by the slice
        # end. A censored RISE is a censored ATTACK — the window is anchored on
        # the 10 % point, so without one there is nothing to anchor. Falling
        # back to the search window's edge instead (as this did) silently reads
        # a 75 ms window, [peak-60 ms, peak+15 ms], into medians documented as
        # the first 30 ms: two window lengths 2.5x apart pooled in one number
        # whose mix depends on how many hits happened to be censored. Same
        # defect class as the bimodal rise — a level produced by window
        # geometry rather than by the sound.
        if i10 is None:
            censored_attack += 1
            continue
        a0, a1 = i10, max(i10 + n_attack, p + n_post_min)
        if a1 > mono.shape[0]:
            censored_attack += 1
            continue
        for b, sig in band_signals.items():
            bands[b].append(_rms_db(sig[a0:a1]))

    if not any(bands.values()):
        return {
            "kind": "all_hits_censored", "track_id": track_id, "hit_count": int(peaks.size),
            "reason": ("every hit's attack window was unplaceable (its rise was "
                       "censored, so there is no 10 % point to anchor it) or cut "
                       "by the slice end"),
        }
    med = {b: float(np.median(v)) for b, v in bands.items()}
    return PartTransient(
        track_id=track_id,
        hit_count=int(peaks.size),
        rise_ms=_median_or_none(rises),
        t20_ms=_median_or_none(t20s),
        censored_rise_hits=censored_rise,
        censored_t20_hits=censored_t20,
        censored_attack_hits=censored_attack,
        attack_sub_40_100_db=med["sub_40_100"],
        attack_low_100_250_db=med["low_100_250"],
        attack_lowmid_250_600_db=med["lowmid_250_600"],
        attack_click_2k_6k_db=med["click_2k_6k"],
        click_minus_sub_db=med["click_2k_6k"] - med["sub_40_100"],
        low_minus_sub_db=med["low_100_250"] - med["sub_40_100"],
    )
