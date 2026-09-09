"""Formant tracks of a sample — the resonances that make a vowel a vowel.

Linear prediction over short windows, entirely in ``numpy`` / ``scipy``:
the signal is folded to mono, resampled to a rate whose Nyquist bounds the
formant region, pre-emphasized to flatten the glottal tilt, framed with a
Hamming window, autocorrelated, solved by Levinson recursion
(``scipy.linalg.solve_toeplitz``), and the predictor polynomial's roots
become resonances — angle → Hz, radius → bandwidth. Only sharp resonances
(bandwidth under ``max_bandwidth_hz``) count as formants; a wide pole is the
spectral envelope's slope, not a resonance.

Discipline: a frame with no measurable formant carries ``nan``, and a silent
frame carries ``nan`` on every track — an LPC fit of the noise floor returns
numbers, and they are not formants.
"""
from __future__ import annotations

import numpy as np
from scipy.linalg import solve_toeplitz

from hallucinote.audio.sample_io import as_mono, resample
from hallucinote.features.types import FeatureStream

# LPC is done at a rate whose Nyquist just clears the formant region
# (F1–F4 all sit below 5 kHz); working at the file's own 48 kHz would spend
# most of the predictor's poles on the empty top octaves. The order follows
# the classical 2 + rate/1000 rule — one pole pair per kHz plus two for the
# spectral tilt — which at 10 kHz is 12.
DEFAULT_LPC_RATE_HZ = 10_000
DEFAULT_WINDOW_S = 0.025
DEFAULT_HOP_S = 0.010
DEFAULT_MAX_BANDWIDTH_HZ = 400.0
# First-order pre-emphasis coefficient — the textbook value that flattens the
# ~-6 dB/octave glottal spectrum so high formants get a fair share of the fit.
PRE_EMPHASIS = 0.97
# A resonance below this is the tilt pole or a DC artefact, never F1 (which
# does not go below ~200 Hz in any voice); one above the working Nyquist
# minus this margin is the band edge.
_MIN_FORMANT_HZ = 90.0
_NYQUIST_MARGIN_HZ = 50.0
# A frame this far below the loudest frame is silence: skip the fit.
_SILENCE_GATE_DB = 60.0


def _lpc_order(rate_hz: int) -> int:
    return 2 + rate_hz // 1000


def _frame_resonances(
    frame: np.ndarray, order: int, rate_hz: float, max_bandwidth_hz: float
) -> tuple[np.ndarray, np.ndarray]:
    """(frequencies_hz, bandwidths_hz) of the frame's sharp poles, ascending."""
    n = frame.shape[0]
    spec = np.fft.rfft(frame, 2 * n)
    r = np.fft.irfft(np.abs(spec) ** 2)[: order + 1]
    if r[0] <= 0.0:
        return np.empty(0), np.empty(0)
    try:
        a = solve_toeplitz((r[:order], r[:order]), r[1 : order + 1])
    except np.linalg.LinAlgError:
        return np.empty(0), np.empty(0)
    roots = np.roots(np.concatenate(([1.0], -a)))
    roots = roots[np.imag(roots) > 0.0]
    if roots.size == 0:
        return np.empty(0), np.empty(0)
    freqs = np.angle(roots) * rate_hz / (2.0 * np.pi)
    radii = np.abs(roots)
    with np.errstate(divide="ignore"):
        bandwidths = -np.log(radii) * rate_hz / np.pi
    keep = (
        (bandwidths < max_bandwidth_hz)
        & (freqs > _MIN_FORMANT_HZ)
        & (freqs < rate_hz / 2.0 - _NYQUIST_MARGIN_HZ)
    )
    order_idx = np.argsort(freqs[keep])
    return freqs[keep][order_idx], bandwidths[keep][order_idx]


def formant_tracks(
    audio: np.ndarray,
    sr: int,
    n_formants: int = 3,
    *,
    window_s: float = DEFAULT_WINDOW_S,
    hop_s: float = DEFAULT_HOP_S,
    max_bandwidth_hz: float = DEFAULT_MAX_BANDWIDTH_HZ,
    lpc_rate_hz: int = DEFAULT_LPC_RATE_HZ,
    lpc_order: int | None = None,
) -> list[FeatureStream]:
    """``n_formants`` streams named ``F1``, ``F2``, … in Hz, one value per frame.

    Frames are centred (frame ``i`` at ``i * hop_s``), matching the energy and
    descriptor grids at the same hop so the tracks line up with them.
    ``confidence`` is ``1 - bandwidth / max_bandwidth_hz``: a sharper
    resonance is a surer formant. A frame with fewer sharp resonances than
    ``n_formants`` carries ``nan`` in the tracks it could not fill.
    """
    if sr <= 0:
        raise ValueError(f"sr must be > 0 Hz; got {sr}")
    if n_formants < 1:
        raise ValueError(f"n_formants must be >= 1; got {n_formants}")
    if window_s <= 0 or hop_s <= 0:
        raise ValueError(
            f"window_s ({window_s}) and hop_s ({hop_s}) must be positive seconds"
        )
    if max_bandwidth_hz <= 0:
        raise ValueError(f"max_bandwidth_hz must be > 0; got {max_bandwidth_hz}")
    mono = as_mono(audio)
    if mono.shape[0] == 0:
        raise ValueError("audio holds no samples; there are no formants to track")

    rate = int(min(lpc_rate_hz, sr))
    if rate <= 0:
        raise ValueError(f"lpc_rate_hz must be > 0; got {lpc_rate_hz}")
    y = np.asarray(resample(mono, sr, rate), dtype=np.float64) if rate != sr else mono
    order = lpc_order if lpc_order is not None else _lpc_order(rate)
    if order < 2:
        raise ValueError(f"lpc_order must be >= 2 to hold one resonance; got {order}")

    win = max(int(round(window_s * rate)), order + 2)
    hop = max(int(round(hop_s * rate)), 1)
    emphasized = np.empty_like(y)
    emphasized[0] = y[0]
    emphasized[1:] = y[1:] - PRE_EMPHASIS * y[:-1]
    half = win // 2
    padded = np.pad(emphasized, (half, win - half), mode="constant")
    n_frames = 1 + (y.shape[0] - 1) // hop if y.shape[0] > 0 else 0
    window = np.hamming(win)

    frame_energy = np.empty(n_frames)
    frames = np.empty((n_frames, win))
    for i in range(n_frames):
        seg = padded[i * hop : i * hop + win] * window
        frames[i] = seg
        frame_energy[i] = float(np.dot(seg, seg))
    peak = float(frame_energy.max()) if n_frames else 0.0
    gate = peak * 10.0 ** (-_SILENCE_GATE_DB / 10.0)

    values = np.full((n_frames, n_formants), np.nan)
    confidence = np.zeros((n_frames, n_formants))
    for i in range(n_frames):
        if peak <= 0.0 or frame_energy[i] < gate:
            continue
        freqs, bws = _frame_resonances(frames[i], order, float(rate), max_bandwidth_hz)
        k = min(n_formants, freqs.shape[0])
        values[i, :k] = freqs[:k]
        confidence[i, :k] = 1.0 - bws[:k] / max_bandwidth_hz

    times = np.arange(n_frames, dtype=np.float64) * hop / rate
    return [
        FeatureStream(
            name=f"F{j + 1}",
            times_s=times,
            values=values[:, j],
            units="Hz",
            confidence=np.clip(confidence[:, j], 0.0, 1.0),
        )
        for j in range(n_formants)
    ]


__all__ = [
    "DEFAULT_HOP_S",
    "DEFAULT_LPC_RATE_HZ",
    "DEFAULT_MAX_BANDWIDTH_HZ",
    "DEFAULT_WINDOW_S",
    "PRE_EMPHASIS",
    "formant_tracks",
]
