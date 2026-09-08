"""Per-part drum-hit TRANSIENT SHAPE — the kick-class lens.

The mix report can say how loud a kit is and where its onsets fall, but not
what a hit is *shaped* like: how fast it rises, how long it rings, and whether
its attack is sub weight (40-100 Hz), low-mid thud (100-250 Hz), boxiness
(250-600 Hz) or beater click (2-6 kHz). "The kick is a thud — muffled, muddy
with the other instruments" (the alien dogfood pass, 2026-09-08) was measured
with a throw-away script before it could be worked on; this module is that
script as a standing lens, so a "sharpen the kick" edit moves a number that
``compare_to`` can A/B across renders.

Design (see build-plan-aud-sharpness-transients.md):

  * Hits are picked on the LOW band (``band_hz``, default 40-150 Hz), not the
    spectral-flux front-end ``onsets.py`` gives the timing lenses. The question
    is about kick-class hits, and a kit stem's hats and snares would swamp a
    broadband picker. Envelope = |Hilbert| of the band-passed slice, smoothed
    5 ms; peaks at >= ``peak_rel`` of the window's loudest peak, >= ``min_sep_s``
    apart.
  * Per hit: rise = 10 -> 90 % of the low envelope up to the peak (searched back
    ``rise_search_s``); T20 = time after the peak for the low envelope to fall
    20 dB (capped at ``decay_cap_s``); the ATTACK window = the first
    ``attack_s`` after the 10 % point, over which four band RMS levels are read.
    Medians across hits are reported; the two band DIFFERENCES are the
    level-blind punch/thud reads.
  * Pure DSP, DB-agnostic — the caller slices stems to the window like the
    timing lens. Absolute band levels are dBFS of the PRE-FADER stem as
    captured (named so in the report); the differences and times are
    level-blind.

Neutral measurement — never a grade; ``/mix-review`` reads it against intent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .onsets import to_mono
from .report import PartTransient

# Bands (Hz) read over the attack window.
ATTACK_BANDS_HZ: dict[str, tuple[float, float]] = {
    "sub": (40.0, 100.0),
    "low": (100.0, 250.0),
    "lowmid": (250.0, 600.0),
    "click": (2000.0, 6000.0),
}

_DEFAULT_BAND_HZ = (40.0, 150.0)     # the hit picker's band (kick-class)
_DEFAULT_MIN_HITS = 4                # fewer low-band hits → the part is omitted
_DEFAULT_PEAK_REL = 0.25             # a hit is >= this fraction of the loudest
_DEFAULT_MIN_SEP_S = 0.20            # two peaks closer than this are one hit
_ENVELOPE_SMOOTH_S = 0.005
_RISE_SEARCH_S = 0.060
_ATTACK_S = 0.030
_DECAY_CAP_S = 0.600
_DB_FLOOR = 1e-9


@dataclass(frozen=True)
class TransientWindowResult:
    """Per-part transient shapes for one (pre-sliced) window."""
    parts: list[PartTransient]


def analyze_transients_window(
    stem_segments: Sequence[tuple[str, np.ndarray]],
    sample_rate: int,
    *,
    band_hz: tuple[float, float] = _DEFAULT_BAND_HZ,
    min_hits: int = _DEFAULT_MIN_HITS,
    peak_rel: float = _DEFAULT_PEAK_REL,
    min_sep_s: float = _DEFAULT_MIN_SEP_S,
) -> TransientWindowResult:
    """Measure each part's low-band hit shape over one window.

    ``stem_segments`` entries are ``(track_id, audio)``, mono ``(n,)`` or stereo
    ``(n, 2)``, already sliced to the window. A part with fewer than
    ``min_hits`` low-band hits is omitted — a pad or a voice has no kick-class
    transient to describe. Parts are returned in input order.
    """
    parts: list[PartTransient] = []
    if sample_rate <= 0:
        return TransientWindowResult(parts=parts)
    for track_id, audio in stem_segments:
        mono = to_mono(audio).astype(np.float64)
        shape = _part_transient(track_id, mono, sample_rate, band_hz=band_hz,
                                min_hits=min_hits, peak_rel=peak_rel,
                                min_sep_s=min_sep_s)
        if shape is not None:
            parts.append(shape)
    return TransientWindowResult(parts=parts)


def _bandpass(mono: np.ndarray, sr: int, lo: float, hi: float) -> np.ndarray:
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


def _part_transient(
    track_id: str, mono: np.ndarray, sr: int, *, band_hz, min_hits, peak_rel,
    min_sep_s,
) -> PartTransient | None:
    from scipy.signal import find_peaks, hilbert

    min_len = int(_DECAY_CAP_S * sr) + int(_RISE_SEARCH_S * sr) + 1
    if mono.shape[0] < min_len:
        return None
    low = _bandpass(mono, sr, *band_hz)
    env = np.abs(hilbert(low))
    k = max(1, int(_ENVELOPE_SMOOTH_S * sr))
    env = np.convolve(env, np.ones(k) / k, mode="same")
    top = float(env.max())
    if top <= 0.0:
        return None
    peaks, _ = find_peaks(env, height=peak_rel * top, distance=max(1, int(min_sep_s * sr)))
    if peaks.size < min_hits:
        return None

    rises, t20s = [], []
    bands: dict[str, list[float]] = {b: [] for b in ATTACK_BANDS_HZ}
    band_signals = {b: _bandpass(mono, sr, lo, hi) for b, (lo, hi) in ATTACK_BANDS_HZ.items()}
    n_attack = int(_ATTACK_S * sr)
    n_search = int(_RISE_SEARCH_S * sr)
    n_decay = int(_DECAY_CAP_S * sr)
    for p in peaks:
        pv = env[p]
        w0 = max(0, p - n_search)
        win = env[w0:p + 1]
        i10 = w0 + int(np.argmax(win >= 0.10 * pv))
        i90 = w0 + int(np.argmax(win >= 0.90 * pv))
        rises.append((i90 - i10) / sr * 1000.0)
        after = env[p:p + n_decay]
        below = np.nonzero(after <= pv * 10.0 ** (-20.0 / 20.0))[0]
        t20s.append((float(below[0]) if below.size else float(after.size)) / sr * 1000.0)
        a0, a1 = i10, min(mono.shape[0], i10 + n_attack)
        for b, sig in band_signals.items():
            bands[b].append(_rms_db(sig[a0:a1]))

    med = {b: float(np.median(v)) for b, v in bands.items()}
    return PartTransient(
        track_id=track_id,
        hit_count=int(peaks.size),
        rise_ms=float(np.median(rises)),
        t20_ms=float(np.median(t20s)),
        attack_sub_db=med["sub"],
        attack_low_db=med["low"],
        attack_lowmid_db=med["lowmid"],
        attack_click_db=med["click"],
        click_minus_sub_db=med["click"] - med["sub"],
        low_minus_sub_db=med["low"] - med["sub"],
    )
