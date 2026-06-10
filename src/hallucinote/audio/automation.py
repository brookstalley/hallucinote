"""Envelope-aware automation verification (AUD-8H2M).

The framework authors time-varying automation — a device-parameter flip (the
Amp Type Clean↔Heavy genre switch), a volume swell, a dynamic send. This module
verifies those gestures were REALIZED in the rendered audio: it windows a
surface around each declared breakpoint and asks whether the expected change
actually happened in the sound, reporting realized-vs-declared.

What's verifiable depends on where the analyzer taps — **pre-fader**, per
``levels.py``:

  - ``device_parameter`` (incl. enum flips like Amp Type) — the device sits
    BEFORE the analyzer tap, so its timbre change IS in the stem. The verdict is
    **directional**: "a timbre shift occurred at the declared beat", measured as
    a spectral-centroid move — NOT a scalar tolerance match, because timbre
    isn't a single number with a known target (Honest Confidence).
  - ``send_level`` — visible on the RETURN surface (more send → louder return).
    Numeric, so the expected direction (up/down) is known and checked.
  - ``mixer_volume`` — POST-fader, invisible to the pre-fader stem, but visible
    on the MASTER (the post-fader sum). AUD-3F8M: window the master around the
    breakpoint and check the level step. The declared fader values + the
    measured pre-fader stem power *predict* the expected master dB step
    (uncorrelated power model, ``levels.live_fader_gain`` calibration); when
    the prediction is below the detectability floor (stem too diluted in the
    mix, or the stem silent there), the breakpoint is honestly
    ``measurable=False`` rather than a false verdict. The realized check is
    directional + a lenient fraction of the predicted magnitude, because
    master-chain processing (the house limiter) compresses level deltas.
  - ``mixer_pan`` — post-fader; master-bus pan verification is the next chunk
    of AUD-3F8M. Still reported ``measurable=False`` with a teaching note.

DB-agnostic and beat-domain, like ``DeclaredReverbSend`` / ``SectionWindow``:
the MCP handler resolves DB envelopes into ``DeclaredEnvelope`` records (capture
surface IDs + song-absolute beat breakpoints) and passes them in. This module
never touches the DB.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .levels import live_fader_gain
from .report import EnvelopeVerification
from .section import BeatSampleMap

# Beats measured on each side of a breakpoint, clamped to the neighbouring
# breakpoints (so adjacent changes don't bleed into each other).
_WINDOW_BEATS = 2.0

# A device-parameter timbre shift counts as realized when the spectral centroid
# moves at least this fraction (relative) across the breakpoint. ~12% is well
# above measurement jitter but below a real Clean→distorted move.
_CENTROID_REL_THRESHOLD = 0.12

# A send-level step counts as realized when the return RMS moves at least this
# many dB in the DECLARED direction.
_SEND_DB_THRESHOLD = 1.5

# RMS below this (≈ -100 dBFS) is silence — a window this quiet can't be
# characterised, so the breakpoint is reported unmeasurable rather than
# misread as "not realized".
_QUIET_RMS = 1e-5

# A declared mixer_volume move must predict at least this much master-level
# change to be measurable there. Below it the stem is too diluted in the mix
# (or silent around the breakpoint) for the master to speak — calibrated on
# the sun-zone-done v4-full-aligned capture (2026-06-10 spike: pre-fader
# stem/master power ratios span 0.0–3.3 across stems and windows, so a fixed
# share threshold is meaningless; predict per-breakpoint instead).
_MIN_DETECTABLE_MASTER_DB = 0.75

# Realized when the measured master step is at least this fraction of the
# predicted step (and in the predicted direction). Lenient on purpose:
# master-chain processing (the house limiter) compresses level deltas, and
# program content differs across the breakpoint.
_VOLUME_REALIZED_FRACTION = 0.3

# Envelope kinds verified on the captured surface itself; mixer_volume is
# verified on the MASTER (post-fader sum), and mixer_pan is still honestly
# reported unverifiable (next AUD-3F8M chunk) — both dispatched by name in
# verify_envelope_realization.
_TIMBRE_KINDS = frozenset({"device_parameter"})
_LEVEL_KINDS = frozenset({"send_level"})


@dataclass(frozen=True)
class DeclaredEnvelope:
    """One declared automation envelope to verify, beat-domain.

    ``target_surface_id`` is the capture surface to MEASURE — for
    ``device_parameter`` the track (or return) hosting the device; for
    ``send_level`` the return the send feeds; for ``mixer_volume``/``mixer_pan``
    the track. ``target_kind`` is the DB envelope kind. ``breakpoints`` are
    ``(song_absolute_beat, value)`` pairs in time order. The MCP handler builds
    these; fixtures construct them directly.
    """
    target_surface_id: str
    target_kind: str
    parameter_path: str | None
    breakpoints: tuple[tuple[float, float], ...]


def _mono_window(
    audio: np.ndarray, beat_map: BeatSampleMap, lo_beat: float, hi_beat: float
) -> np.ndarray:
    a = beat_map.beat_to_sample(lo_beat)
    b = beat_map.beat_to_sample(hi_beat)
    if b <= a:
        return np.zeros(0, dtype=np.float64)
    seg = audio[a:b]
    return (0.5 * (seg[:, 0] + seg[:, 1])).astype(np.float64)


def _spectral_centroid_hz(mono: np.ndarray, sample_rate: int) -> float:
    """Magnitude-weighted mean frequency (Hz) — a coarse but robust timbre
    proxy. Distortion/brightness pushes it up; a darker setting pulls it down.
    0.0 for an empty/silent window."""
    if mono.size == 0:
        return 0.0
    spec = np.abs(np.fft.rfft(mono))
    total = float(spec.sum())
    if total <= 0.0:
        return 0.0
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / sample_rate)
    return float((freqs * spec).sum() / total)


def _rms(mono: np.ndarray) -> float:
    if mono.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(mono ** 2)))


def _change_points(breakpoints: Sequence[tuple[float, float]]) -> list[int]:
    """Indices i (≥1) where the value changes from breakpoints[i-1] — the beats
    at which an authored gesture takes effect."""
    return [
        i for i in range(1, len(breakpoints))
        if breakpoints[i][1] != breakpoints[i - 1][1]
    ]


def verify_envelope_realization(
    env: DeclaredEnvelope,
    surface_audio: np.ndarray,
    *,
    sample_rate: int,
    beat_map: BeatSampleMap,
    master_audio: np.ndarray,
) -> list[EnvelopeVerification]:
    """One verification per value-changing breakpoint in ``env``.

    For each change at beat B, window the surface ``before`` ``[B-W, B)`` and
    ``after`` ``[B, B+W)`` (clamped to neighbouring breakpoints) and compare the
    kind-appropriate metric. ``mixer_volume`` measures the MASTER windows
    (post-fader sum) against a prediction built from the declared fader values
    and the pre-fader stem window (AUD-3F8M); ``mixer_pan`` still returns a
    single ``measurable=False`` record (master-bus pan windowing is the next
    chunk).
    """
    if env.target_kind == "mixer_pan":
        return [EnvelopeVerification(
            target_surface_id=env.target_surface_id,
            target_kind=env.target_kind,
            parameter_path=env.parameter_path,
            at_beat=env.breakpoints[0][0] if env.breakpoints else 0.0,
            metric="n/a",
            before=float("nan"),
            after=float("nan"),
            measurable=False,
            realized=False,
            note=(
                "mixer_pan is post-fader — invisible to the pre-fader "
                "stem capture, so its realization can't be verified here. "
                "Master-bus pan windowing is the next AUD-3F8M chunk."
            ),
        )]

    bps = env.breakpoints
    results: list[EnvelopeVerification] = []
    for i in _change_points(bps):
        b_beat = bps[i][0]
        lo = max(bps[i - 1][0], b_beat - _WINDOW_BEATS)
        hi = b_beat + _WINDOW_BEATS
        if i + 1 < len(bps):
            hi = min(bps[i + 1][0], hi)
        before = _mono_window(surface_audio, beat_map, lo, b_beat)
        after = _mono_window(surface_audio, beat_map, b_beat, hi)

        if env.target_kind == "mixer_volume":
            master_before = _mono_window(master_audio, beat_map, lo, b_beat)
            master_after = _mono_window(master_audio, beat_map, b_beat, hi)
            results.append(_verify_mixer_volume(
                env, bps, i,
                stem_before=before,
                master_before=master_before,
                master_after=master_after,
            ))
            continue

        if _rms(before) < _QUIET_RMS or _rms(after) < _QUIET_RMS:
            results.append(EnvelopeVerification(
                target_surface_id=env.target_surface_id,
                target_kind=env.target_kind,
                parameter_path=env.parameter_path,
                at_beat=b_beat,
                metric="n/a",
                before=float("nan"),
                after=float("nan"),
                measurable=False,
                realized=False,
                note=(
                    "window too quiet to characterise (the surface is near "
                    "silent around this breakpoint) — can't confirm or refute "
                    "realization here"
                ),
            ))
            continue

        if env.target_kind in _TIMBRE_KINDS:
            results.append(_verify_timbre(env, b_beat, before, after, sample_rate))
        elif env.target_kind in _LEVEL_KINDS:
            results.append(_verify_level(env, bps, i, before, after))
        # Unknown kinds are filtered out by the handler before reaching here;
        # if one slips through, skip it silently (no false verdict).
    return results


def _verify_timbre(env, b_beat, before, after, sample_rate) -> EnvelopeVerification:
    c_before = _spectral_centroid_hz(before, sample_rate)
    c_after = _spectral_centroid_hz(after, sample_rate)
    rel = abs(c_after - c_before) / c_before if c_before > 0 else 0.0
    realized = rel >= _CENTROID_REL_THRESHOLD
    pct = rel * 100.0
    if realized:
        note = (
            f"timbre shift realized: spectral centroid {c_before:.0f}→"
            f"{c_after:.0f} Hz ({pct:+.0f}%) at the declared "
            f"{env.parameter_path or 'device-parameter'} change"
        )
    else:
        note = (
            f"no audible timbre shift ({c_before:.0f}→{c_after:.0f} Hz, "
            f"{pct:.0f}% < {_CENTROID_REL_THRESHOLD * 100:.0f}%) — the declared "
            f"{env.parameter_path or 'device-parameter'} change may not have "
            "been realized in the render"
        )
    return EnvelopeVerification(
        target_surface_id=env.target_surface_id,
        target_kind=env.target_kind,
        parameter_path=env.parameter_path,
        at_beat=b_beat,
        metric="spectral_centroid_hz",
        before=c_before,
        after=c_after,
        measurable=True,
        realized=realized,
        note=note,
    )


def _verify_mixer_volume(
    env, bps, i, *, stem_before, master_before, master_after,
) -> EnvelopeVerification:
    """AUD-3F8M: verify a post-fader volume move on the MASTER.

    The declared breakpoints are Live normalized fader values; with the
    measured pre-fader stem power around the move, the uncorrelated power
    model predicts the master step:

        P_after ≈ P_master − P_stem·g₁² + P_stem·g₂²

    A prediction below ``_MIN_DETECTABLE_MASTER_DB`` means the stem is too
    diluted (or silent) there for the master to speak — honest
    ``measurable=False``, never a false verdict.
    """
    b_beat = bps[i][0]
    if _rms(master_before) < _QUIET_RMS or _rms(master_after) < _QUIET_RMS:
        return EnvelopeVerification(
            target_surface_id=env.target_surface_id,
            target_kind=env.target_kind,
            parameter_path=env.parameter_path,
            at_beat=b_beat,
            metric="n/a",
            before=float("nan"),
            after=float("nan"),
            measurable=False,
            realized=False,
            note=(
                "master window too quiet to characterise around this "
                "breakpoint — can't confirm or refute the fader move here"
            ),
        )

    g1 = live_fader_gain(bps[i - 1][1])
    g2 = live_fader_gain(bps[i][1])
    p_master = _rms(master_before) ** 2
    p_stem = _rms(stem_before) ** 2
    expected_after_p = p_master - p_stem * g1 * g1 + p_stem * g2 * g2
    if expected_after_p <= 0.01 * p_master:
        # Model breakdown: the pre-fader stem at its declared gain accounts
        # for (nearly) all the measured master power — master-chain
        # compression/limiting makes the uncorrelated sum overshoot. A
        # prediction from a broken model would manufacture a false
        # "NOT realized"; report honestly unmeasurable instead.
        return EnvelopeVerification(
            target_surface_id=env.target_surface_id,
            target_kind=env.target_kind,
            parameter_path=env.parameter_path,
            at_beat=b_beat,
            metric="n/a",
            before=float("nan"),
            after=float("nan"),
            measurable=False,
            realized=False,
            note=(
                f"declared fader move ({bps[i - 1][1]:.2f}→{bps[i][1]:.2f}): "
                "the pre-fader stem at its declared gain accounts for more "
                "power than the measured master window (master-chain "
                "compression/limiting) — the uncorrelated prediction model "
                "breaks down here, so master-bus windowing can't confirm or "
                "refute this move"
            ),
        )
    expected_db = 10.0 * math.log10(expected_after_p / p_master)

    if abs(expected_db) < _MIN_DETECTABLE_MASTER_DB:
        return EnvelopeVerification(
            target_surface_id=env.target_surface_id,
            target_kind=env.target_kind,
            parameter_path=env.parameter_path,
            at_beat=b_beat,
            metric="n/a",
            before=float("nan"),
            after=float("nan"),
            measurable=False,
            realized=False,
            note=(
                f"declared fader move ({bps[i - 1][1]:.2f}→{bps[i][1]:.2f}) "
                f"predicts only {expected_db:+.2f} dB on the master — the "
                "stem is too diluted in the mix (or silent) around this "
                "breakpoint for master-bus windowing to confirm or refute it"
            ),
        )

    db_before = 20.0 * math.log10(max(_rms(master_before), 1e-12))
    db_after = 20.0 * math.log10(max(_rms(master_after), 1e-12))
    delta_db = db_after - db_before
    realized = (
        (delta_db > 0) == (expected_db > 0)
        and abs(delta_db) >= _VOLUME_REALIZED_FRACTION * abs(expected_db)
    )
    direction = "up" if expected_db > 0 else "down"
    note = (
        f"fader declared {direction} ({bps[i - 1][1]:.2f}→{bps[i][1]:.2f}, "
        f"predicting {expected_db:+.1f} dB on the master); master moved "
        f"{delta_db:+.1f} dB ({db_before:.1f}→{db_after:.1f} dBFS) — "
        + ("realized" if realized else "NOT realized in the declared direction")
    )
    return EnvelopeVerification(
        target_surface_id=env.target_surface_id,
        target_kind=env.target_kind,
        parameter_path=env.parameter_path,
        at_beat=b_beat,
        metric="master_rms_db",
        before=db_before,
        after=db_after,
        measurable=True,
        realized=realized,
        note=note,
    )


def _verify_level(env, bps, i, before, after) -> EnvelopeVerification:
    db_before = 20.0 * math.log10(max(_rms(before), 1e-12))
    db_after = 20.0 * math.log10(max(_rms(after), 1e-12))
    delta_db = db_after - db_before
    declared_dir = bps[i][1] - bps[i - 1][1]  # +ve = more send, -ve = less
    # Realized when the level moved in the declared direction by a real amount.
    realized = (
        abs(delta_db) >= _SEND_DB_THRESHOLD
        and (delta_db > 0) == (declared_dir > 0)
    )
    direction = "up" if declared_dir > 0 else "down"
    note = (
        f"send level declared {direction}; return moved {delta_db:+.1f} dB "
        f"({db_before:.1f}→{db_after:.1f} dBFS) — "
        + ("realized" if realized else "NOT realized in the declared direction")
    )
    return EnvelopeVerification(
        target_surface_id=env.target_surface_id,
        target_kind=env.target_kind,
        parameter_path=env.parameter_path,
        at_beat=bps[i][0],
        metric="rms_db",
        before=db_before,
        after=db_after,
        measurable=True,
        realized=realized,
        note=note,
    )


__all__ = [
    "DeclaredEnvelope",
    "verify_envelope_realization",
]
