"""Mix-level reconstruction for the audio analysis pipeline (F1).

The M4L analyzer is a **parallel tap in each track's device chain**, so the
captured per-stem WAVs are **pre-fader** — Live applies the track volume (and
pan) *after* the device chain. Masking is a *relative-level* phenomenon, so
analysing the raw captures measures collisions at SOURCE level, not at the level
the stems actually sit in the mix. This module reconstructs mix-level by
applying each track's fader gain to its stem before analysis.

Scope of this first cut (build-plan C3):

* **Static fader gain only.** Per-track ``tracks.volume`` (Live's normalized
  0..1) → linear amplitude gain. Volume *automation* (a stem that ducks under
  the chorus) is a richer refinement — a per-section gain evaluated from the
  volume envelope — and is deferred.
* **Pan is intentionally NOT applied.** Masking mono-sums, and constant-power
  pan leaves the mono level ~unchanged; pan's real effect is *spatial*
  unmasking, which mono-sum can't see anyway (F3). Applying a pan law here would
  add complexity without changing the mono masking result.
* **Masking only.** Loudness/attribution still run on raw captures; whether to
  level-correct them too is a separate decision (they have the same pre-fader
  property) — deferred so this change doesn't alter shipped metrics.

**The fader curve is CALIBRATED against Live 12** (2026-05-28), by sweeping a
track's ``mixer_device.volume`` and reading the parameter's ``display_value``
(dB) over Python LOM. Two findings:

* **[0.40, 1.00] is exactly linear in dB:** ``dB = 40·(v − 0.85)`` — verified at
  0.40 → −18.0, 0.50 → −14.0, 0.75 → −4.0, 0.90 → +2.0, 1.00 → +6.0 (and 0.85 →
  0 unity). No error at any sampled point.
* **(0, 0.40) bends steeper toward −∞** — measured breakpoints below. The whole
  curve is stored as a (norm, dB) table and linearly interpolated, so it
  reproduces Live exactly at the breakpoints. ``v ≤ 0`` → −∞ (muted).

Isolated here so a future pull that stores dB directly can bypass it.
"""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

_UNITY_NORM = 0.85   # 0.85 reads 0 dB in Live
_MAX_DB = 6.0        # 1.0 reads +6 dB
_NEG_INF_DB = float("-inf")

# Live 12 fader calibration: normalized volume → dB, measured via LOM
# display_value. The [0.40, 1.00] tail is exactly 40·(v−0.85); the sub-0.40
# points are the measured bend. (0.0, -70.0) is a practical floor so (0, 0.05)
# interpolates toward silence; v <= 0 is special-cased to −∞ in live_fader_db.
_CALIB_NORM = np.array(
    [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.75, 0.85, 0.90, 1.0]
)
_CALIB_DB = np.array(
    [-70.0, -57.2, -48.6, -41.0, -34.4, -24.2, -18.0, -14.0, -4.0, 0.0, 2.0, 6.0]
)


def live_fader_db(normalized_volume: float) -> float:
    """Live normalized track volume (0..1) → dB. CALIBRATED — see module doc.

    Linear interpolation of the measured Live 12 curve; exact at the sampled
    breakpoints. ``v ≤ 0`` → −∞ (muted); ``v ≥ 1`` clamps to +6 dB.
    """
    v = float(normalized_volume)
    if v <= 0.0:
        return _NEG_INF_DB
    if v >= 1.0:
        return _MAX_DB
    return float(np.interp(v, _CALIB_NORM, _CALIB_DB))


def live_fader_gain(normalized_volume: float) -> float:
    """Live normalized track volume (0..1) → linear amplitude gain (≥ 0).

    ``gain = 10^(dB/20)``; v=0 → 0.0, v=0.85 → 1.0 (unity), v=1.0 → ~1.995.
    """
    db = live_fader_db(normalized_volume)
    if db == _NEG_INF_DB:
        return 0.0
    return 10.0 ** (db / 20.0)


def apply_stem_gains(
    stem_segments: Sequence[tuple[str, np.ndarray]],
    stem_gains: Mapping[str, float],
) -> list[tuple[str, np.ndarray]]:
    """Scale each ``(track_id, audio)`` by its linear gain (default 1.0).

    Returns new arrays (does not mutate inputs). A track absent from
    ``stem_gains`` is passed through unchanged — so an empty map is a no-op and
    synthetic fixtures (which construct levels directly) are unaffected.
    """
    out: list[tuple[str, np.ndarray]] = []
    for track_id, audio in stem_segments:
        gain = stem_gains.get(track_id, 1.0)
        if gain == 1.0:
            out.append((track_id, audio))
        else:
            out.append((track_id, (audio * gain).astype(audio.dtype, copy=False)))
    return out


__all__ = ["live_fader_db", "live_fader_gain", "apply_stem_gains"]
