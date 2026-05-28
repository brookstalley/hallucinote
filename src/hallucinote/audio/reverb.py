"""Reverb send verification — measure RT60 of a declared dry→wet send.

Two steps:

  1. ``deconvolve_ir(dry, wet, sr)`` — Wiener-regularized spectral
     deconvolution recovers the impulse response that produced ``wet``
     from ``dry``: ``IR(ω) = WET·conj(DRY) / (|DRY|² + ε)``. The
     ε regularization keeps the result stable where the dry spectrum
     has near-zero bins (which is why spike §3 specified Wiener over
     naive ``wet/dry``).
  2. ``verify_reverb_send(dry, wet, sr, declared_rt60_s, ...)`` —
     deconvolve, then measure RT60 via
     ``pyroomacoustics.experimental.rt60.measure_rt60``. Compare to
     the declared value, return a ``ReverbVerification`` record.

The MVP path uses the dry stem captured at the source track's analyzer
and the wet signal captured at the return-track analyzer. That's the
clean dry/wet pair the spike calls out — far better than blind RT60
estimation on the master (spike §7).
"""
from __future__ import annotations

import numpy as np

from .report import ReverbVerification

# Success criterion #5 (build plan Chunk 3-B): measured vs declared RT60
# must agree within this tolerance on a synthetic dry impulse + known IR.
# Real-world noisy material gets wider tolerance per spike §7.
REVERB_TOLERANCE_S = 0.15

# Wiener regularization floor. Tiny but non-zero — prevents division-by-
# zero in dry spectrum bins. Picked to be well below the noise floor of
# a typical -60 dBFS reverb tail.
_WIENER_EPSILON = 1e-6


def deconvolve_ir(
    dry: np.ndarray,
    wet: np.ndarray,
    *,
    sr: int,  # noqa: ARG001 -- API symmetry with verify_reverb_send; not used in math
) -> np.ndarray:
    """Recover the impulse response that produced ``wet`` from ``dry``.

    Uses Wiener-regularized spectral deconvolution. Both inputs must be
    stereo (n, 2) float; processing happens per-channel and the result
    is the same length as ``dry``.
    """
    if dry.ndim != 2 or dry.shape[1] != 2:
        raise ValueError(f"dry must be stereo (n, 2); got shape {dry.shape}")
    if wet.ndim != 2 or wet.shape[1] != 2:
        raise ValueError(f"wet must be stereo (n, 2); got shape {wet.shape}")
    if dry.shape[0] != wet.shape[0]:
        raise ValueError(
            f"dry and wet must be the same length; "
            f"got dry={dry.shape[0]}, wet={wet.shape[0]} (the analyzer's "
            f"PDC alignment should guarantee this — has the capture been "
            f"truncated or mis-merged?)"
        )

    n = dry.shape[0]
    out = np.zeros_like(dry, dtype=np.float32)
    for ch in range(2):
        dry_f = np.fft.rfft(dry[:, ch].astype(np.float64))
        wet_f = np.fft.rfft(wet[:, ch].astype(np.float64))
        # Wiener: WET · conj(DRY) / (|DRY|^2 + ε)
        denom = (dry_f.conj() * dry_f).real + _WIENER_EPSILON
        ir_f = wet_f * dry_f.conj() / denom
        out[:, ch] = np.fft.irfft(ir_f, n=n).astype(np.float32)
    return out


def verify_reverb_send(
    dry: np.ndarray,
    wet: np.ndarray,
    *,
    sample_rate: int,
    declared_rt60_s: float,
    dry_track_id: str,
    wet_return_track_id: str,
    tolerance_s: float = REVERB_TOLERANCE_S,
) -> ReverbVerification:
    """Measure RT60 from (dry, wet), compare to declared, return verdict.

    Returns a ``ReverbVerification`` with ``measured_rt60_s`` populated.
    ``within_tolerance`` flips when the absolute difference exceeds
    ``tolerance_s``.
    """
    from pyroomacoustics.experimental.rt60 import measure_rt60

    ir = deconvolve_ir(dry, wet, sr=sample_rate)
    # Mono-sum the IR for RT60 measurement — pyroomacoustics expects 1-D
    # and reverb decay is largely channel-agnostic on real returns.
    ir_mono = (0.5 * (ir[:, 0] + ir[:, 1])).astype(np.float64)

    # Trim leading silence — the Schroeder integration is sensitive to
    # where energy starts. find the first sample above 1% of the IR peak.
    peak = float(np.max(np.abs(ir_mono)))
    if peak <= 0:
        # Fully silent IR — declared can't be verified.
        return ReverbVerification(
            dry_track_id=dry_track_id,
            wet_return_track_id=wet_return_track_id,
            declared_rt60_s=declared_rt60_s,
            measured_rt60_s=float("nan"),
            within_tolerance=False,
            tolerance_s=tolerance_s,
        )
    onset_threshold = 0.01 * peak
    onset_idx = int(np.argmax(np.abs(ir_mono) > onset_threshold))
    ir_trimmed = ir_mono[onset_idx:]

    measured = float(measure_rt60(ir_trimmed, fs=sample_rate))
    within = abs(measured - declared_rt60_s) <= tolerance_s

    return ReverbVerification(
        dry_track_id=dry_track_id,
        wet_return_track_id=wet_return_track_id,
        declared_rt60_s=declared_rt60_s,
        measured_rt60_s=measured,
        within_tolerance=within,
        tolerance_s=tolerance_s,
    )


__all__ = [
    "REVERB_TOLERANCE_S",
    "deconvolve_ir",
    "verify_reverb_send",
]
