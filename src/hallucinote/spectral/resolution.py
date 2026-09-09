"""What a spectral operation can resolve, and the longer window that resolves more.

A 2048-point window at 48 kHz spaces its bins 23 Hz apart; a semitone at 55 Hz
is 3 Hz wide. An operation asked to carve that semitone has two honest
answers: analyse the bass through a longer window, or say what width it
achieved. This module holds both. ``choose_resolution`` picks a low-band
window below a knee when the base window cannot meet the requested width;
``claim_precision`` records what was asked, what the windows can deliver and
whether the two agree, so a mask carries the truth about its own precision
instead of implying the request was met. ``split_bands`` is the crossover the
multi-resolution apply path stitches over: the bass goes through the long
window, the rest through the short one, and the two sum back to the input.

Discipline: a window is never chosen silently past its cost — the knee bounds
where the long window is used, and the cap bounds how long it may be, because
a window longer than a bass note blurs the note across its neighbours.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import fftconvolve, firwin

from hallucinote.spectral.types import ResolutionReport

DEFAULT_N_FFT = 2048
DEFAULT_HOP = 512

# Below the knee the operation is allowed to spend a longer window. 200 Hz is
# where Bark bands stop shrinking with pitch and where a 2048-point window's
# bin exceeds a semitone.
DEFAULT_KNEE_HZ = 200.0

# The precision a bass carve is expected to deliver unless the caller asks for
# another: one semitone, the smallest musically distinct notch.
DEFAULT_TARGET_CENTS = 100.0

# 32768 samples is 0.68 s at 48 kHz. Longer than that the window outlasts most
# bass notes and the carve smears across the note before and after.
MAX_LOW_N_FFT = 32768

# Crossover transition as a fraction of the knee; the FIR length follows from
# it. Half the knee keeps the filter under two thousand taps at 48 kHz.
_CROSSOVER_TRANSITION_FRACTION = 0.5


@dataclass(frozen=True)
class PrecisionClaim:
    """What a mask asked for at its lowest reference pitch, and what it delivers.

    ``achieved_cents`` is never below ``requested_cents``: a window cannot cut
    a notch narrower than its own bin, so the claim widens to the bin where the
    request was finer than the analysis. ``met`` says whether the request held.
    """

    lowest_hz: float
    requested_cents: float
    achieved_cents: float

    def __post_init__(self) -> None:
        if self.lowest_hz <= 0:
            raise ValueError(f"PrecisionClaim.lowest_hz must be > 0; got {self.lowest_hz}")
        if self.requested_cents <= 0:
            raise ValueError(
                f"PrecisionClaim.requested_cents must be > 0; got {self.requested_cents}"
            )
        if self.achieved_cents < self.requested_cents:
            raise ValueError(
                "PrecisionClaim.achieved_cents cannot be finer than requested_cents: "
                f"achieved {self.achieved_cents}, requested {self.requested_cents}"
            )

    @property
    def met(self) -> bool:
        return self.achieved_cents <= self.requested_cents

    def describe(self) -> str:
        if self.met:
            return (
                f"notch of {self.requested_cents:.0f} cents at {self.lowest_hz:.1f} Hz "
                f"resolved as requested"
            )
        return (
            f"notch of {self.requested_cents:.0f} cents requested at {self.lowest_hz:.1f} Hz; "
            f"the analysis window resolves {self.achieved_cents:.0f} cents there, so the "
            f"notch cut is {self.achieved_cents:.0f} cents wide — analyse the bass through "
            f"a longer window (choose_resolution) to narrow it"
        )


def choose_resolution(
    lowest_hz: float,
    sr: int,
    *,
    n_fft: int = DEFAULT_N_FFT,
    hop: int = DEFAULT_HOP,
    knee_hz: float = DEFAULT_KNEE_HZ,
    target_cents: float = DEFAULT_TARGET_CENTS,
) -> ResolutionReport:
    """Pick the windows that resolve ``target_cents`` at ``lowest_hz``.

    The base window is kept as it is; a longer low-band window is added only
    when the lowest reference pitch sits below the knee and the base window's
    bin there is wider than the target. The long window is the shortest
    doubling of the base that meets the target, capped at ``MAX_LOW_N_FFT`` —
    past the cap the report simply says what it achieves.
    """
    if lowest_hz <= 0:
        raise ValueError(f"lowest_hz must be > 0; got {lowest_hz}")
    if knee_hz <= 0:
        raise ValueError(f"knee_hz must be > 0; got {knee_hz}")
    if target_cents <= 0:
        raise ValueError(f"target_cents must be > 0; got {target_cents}")
    base = ResolutionReport(n_fft=n_fft, hop=hop, sample_rate=sr)
    if lowest_hz >= knee_hz or base.achieved_cents_at_hz(lowest_hz) <= target_cents:
        return base
    needed_bin_hz = lowest_hz * (2.0 ** (target_cents / 1200.0) - 1.0)
    low_n_fft = n_fft
    while low_n_fft < MAX_LOW_N_FFT and sr / low_n_fft > needed_bin_hz:
        low_n_fft *= 2
    if low_n_fft <= n_fft:
        return base
    return ResolutionReport(
        n_fft=n_fft, hop=hop, sample_rate=sr, low_knee_hz=knee_hz, low_n_fft=low_n_fft
    )


def claim_precision(
    lowest_hz: float, requested_cents: float, *reports: ResolutionReport
) -> PrecisionClaim:
    """The width the operation can honestly deliver at ``lowest_hz``.

    Every window on the path bounds the notch — the field's analysis places the
    reference no finer than its own bin, and the apply window cuts no finer
    than its bin — so the claim is the widest of them and the request.
    """
    achieved = float(requested_cents)
    for report in reports:
        achieved = max(achieved, report.achieved_cents_at_hz(lowest_hz))
    return PrecisionClaim(
        lowest_hz=float(lowest_hz), requested_cents=float(requested_cents), achieved_cents=achieved
    )


def bin_hz_over(report: ResolutionReport, freqs_hz: np.ndarray) -> np.ndarray:
    """``ResolutionReport.bin_hz_at`` over an array of frequencies."""
    f = np.asarray(freqs_hz, dtype=np.float64)
    out = np.full(f.shape, report.bin_hz, dtype=np.float64)
    if report.low_knee_hz is not None and report.low_n_fft is not None:
        out[f < report.low_knee_hz] = report.sample_rate / report.low_n_fft
    return out


def split_bands(mono: np.ndarray, sr: int, knee_hz: float) -> tuple[np.ndarray, np.ndarray]:
    """Split a mono signal at ``knee_hz`` into a low band and its exact complement.

    The low band is a zero-phase FIR low-pass; the high band is the input minus
    it, so the two sum back to the input sample for sample. Zero phase matters
    because the two bands are re-summed after separate resynthesis: a phase
    shift between them would comb the crossover region.
    """
    x = np.asarray(mono, dtype=np.float64)
    if x.ndim != 1:
        raise ValueError(f"split_bands takes a 1-D mono signal; got shape {x.shape}")
    if knee_hz <= 0 or knee_hz >= sr / 2:
        raise ValueError(f"knee_hz must lie strictly between 0 and Nyquist ({sr / 2}); got {knee_hz}")
    transition_hz = knee_hz * _CROSSOVER_TRANSITION_FRACTION
    # Hann-windowed FIR: main-lobe transition ≈ 3.3 · sr / numtaps.
    numtaps = int(np.ceil(3.3 * sr / transition_hz))
    numtaps += 1 - numtaps % 2
    taps = firwin(numtaps, knee_hz, fs=sr, window="hann")
    # An odd-length symmetric FIR taken 'same' is centred, hence zero-phase.
    low = fftconvolve(x, taps, mode="same")
    return low, x - low
