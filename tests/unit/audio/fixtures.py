"""Synthetic audio fixtures for the audio-analysis test suite.

Why these live here, not in `src/hallucinote/audio/fixtures.py`:
the analysis package doesn't exist yet — Chunk 3 introduces it. The PDC
alignment unit test (Chunk 1) needs synthetic stems *now* to document the
verification the in-Live capture must satisfy. When the analysis package
lands, this module is re-exported from `src.hallucinote.audio.fixtures`
(per build-plan.md Chunk 3 scope).

All generators return float32 stereo arrays shaped (n_samples, 2). 32-bit
float is what `sfrecord~` will write per the spike's capture decision; the
test stems mirror that so PDC math runs on the same dtype it'll see in
production.
"""
from __future__ import annotations

import numpy as np

SAMPLE_RATE = 48_000  # Live's default; Chunk 1 captures use Live's session SR


def _to_stereo(mono: np.ndarray) -> np.ndarray:
    """Duplicate a mono buffer to stereo without copying twice."""
    return np.stack([mono, mono], axis=1).astype(np.float32, copy=False)


def silence(duration_s: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Stereo float32 silence — n_samples × 2."""
    n = int(round(duration_s * sr))
    return np.zeros((n, 2), dtype=np.float32)


def sine(
    freq_hz: float,
    duration_s: float,
    *,
    amplitude: float = 0.5,
    sr: int = SAMPLE_RATE,
    phase: float = 0.0,
) -> np.ndarray:
    """Stereo float32 sine. Default amplitude leaves headroom for summing."""
    n = int(round(duration_s * sr))
    t = np.arange(n, dtype=np.float64) / sr
    mono = amplitude * np.sin(2.0 * np.pi * freq_hz * t + phase)
    return _to_stereo(mono)


def kick_onset(
    *,
    duration_s: float = 0.25,
    f_start_hz: float = 110.0,
    f_end_hz: float = 45.0,
    decay_s: float = 0.18,
    amplitude: float = 0.8,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """One synthetic kick — exponential pitch sweep + exponential decay.

    Sharp transient at t=0 makes this a useful onset target for cross-
    correlation alignment tests.
    """
    n = int(round(duration_s * sr))
    t = np.arange(n, dtype=np.float64) / sr
    # Exponential pitch glide: high → low. Integral gives instantaneous phase.
    k = np.log(f_end_hz / f_start_hz) / max(duration_s, 1e-9)
    phase = 2.0 * np.pi * f_start_hz * (np.exp(k * t) - 1.0) / k
    env = np.exp(-t / decay_s)
    mono = amplitude * env * np.sin(phase)
    return _to_stereo(mono)


def pink_noise(
    duration_s: float,
    *,
    amplitude: float = 0.3,
    sr: int = SAMPLE_RATE,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Voss-McCartney pink noise. Cheap, good enough for fixture purposes.

    Future LUFS tests (Chunk 3) will want a calibrated -23 LUFS pink-noise
    generator; this is the un-calibrated primitive that calibration will
    build on.
    """
    rng = rng if rng is not None else np.random.default_rng(seed=42)
    n = int(round(duration_s * sr))
    # 16 octave-spaced random sources; sum yields ~1/f spectrum.
    n_sources = 16
    sources = rng.standard_normal((n_sources, n)).astype(np.float64)
    # Hold each source for 2^i samples (decimate-and-hold to introduce 1/f).
    pink = np.zeros(n, dtype=np.float64)
    for i in range(n_sources):
        hold = 1 << i
        if hold >= n:
            break
        held = np.repeat(sources[i, ::hold], hold)[:n]
        pink += held
    pink /= np.max(np.abs(pink)) + 1e-12
    pink *= amplitude
    return _to_stereo(pink.astype(np.float32))


def delayed_copy(audio: np.ndarray, *, delay_samples: int) -> np.ndarray:
    """Right-shift a stereo signal by ``delay_samples``, zero-padding the head.

    Models the PDC scenario: the master bus sees the same audio as a stem
    but delayed by the device chain's reported plugin-delay-compensation
    sample count. ``delay_samples`` can be negative to shift left.
    """
    if audio.ndim != 2 or audio.shape[1] != 2:
        raise ValueError(f"expected stereo (n, 2); got shape {audio.shape}")
    n = audio.shape[0]
    out = np.zeros_like(audio)
    if delay_samples >= 0:
        if delay_samples < n:
            out[delay_samples:, :] = audio[: n - delay_samples, :]
    else:
        shift = -delay_samples
        if shift < n:
            out[: n - shift, :] = audio[shift:, :]
    return out


def concat(*segments: np.ndarray) -> np.ndarray:
    """Concatenate stereo segments along time — for time-sequenced fixtures
    (e.g. stem A in the first half, B in the second half, to test no-time-
    overlap masking)."""
    return np.concatenate(segments, axis=0).astype(np.float32, copy=False)


def calibrated_pink_noise(
    target_lufs: float,
    duration_s: float,
    *,
    sr: int = SAMPLE_RATE,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Pink noise scaled to hit ``target_lufs`` LUFS-I exactly.

    One-shot calibration: generate raw pink, measure LUFS-I, scale by
    ``10^((target - measured) / 20)`` (amplitude domain, hence /20 not /10).
    The BS.1770 algorithm is power-summing inside its filters, so an
    amplitude scale by k shifts LUFS by 20*log10(k) = (target - measured).

    Used by ``test_loudness.py`` to pin success criterion #3
    (per-stem LUFS-I within ±0.2 LU on a known-loudness reference stem).
    """
    import pyloudnorm  # local import — fixtures stay light

    raw = pink_noise(duration_s, amplitude=1.0, sr=sr, rng=rng)
    meter = pyloudnorm.Meter(sr)
    measured = meter.integrated_loudness(raw.astype(np.float64))
    scale = 10.0 ** ((target_lufs - measured) / 20.0)
    return (raw * scale).astype(np.float32)


def synthetic_ir(
    rt60_s: float,
    *,
    duration_s: float = 2.0,
    sr: int = SAMPLE_RATE,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Synthetic impulse response with target RT60.

    Exponentially-decaying gaussian noise — the textbook approximation of
    an idealized room response. RT60 = decay time to -60 dB. Stereo float32
    so it lives in the same shape as the rest of the fixtures, but reverb
    verification works on mono IRs so callers typically take ``ir[:, 0]``.
    """
    rng = rng if rng is not None else np.random.default_rng(seed=7)
    n = int(round(duration_s * sr))
    t = np.arange(n, dtype=np.float64) / sr
    # Decay envelope: amplitude e^(-3*ln(10) * t / RT60) gives -60dB at t=RT60.
    decay = np.exp(-3.0 * np.log(10.0) * t / max(rt60_s, 1e-6))
    noise = rng.standard_normal(n)
    mono = (decay * noise).astype(np.float32)
    # Sharp onset — IR starts with the direct response, not noise from t=0.
    mono[0] = 1.0
    return _to_stereo(mono)


def convolve(dry: np.ndarray, ir: np.ndarray) -> np.ndarray:
    """FFT convolution of stereo dry stem with stereo IR.

    Channel-wise; returns length-of-dry stereo float32. Models the
    dry→reverb-return signal path for reverb verification testing.
    """
    from scipy.signal import fftconvolve

    if dry.shape[1] != 2 or ir.shape[1] != 2:
        raise ValueError("dry and ir must both be stereo (n, 2)")
    n_out = dry.shape[0]
    out = np.zeros((n_out, 2), dtype=np.float32)
    for ch in range(2):
        full = fftconvolve(dry[:, ch], ir[:, ch], mode="full")
        out[:, ch] = full[:n_out].astype(np.float32)
    return out


__all__ = [
    "SAMPLE_RATE",
    "silence",
    "sine",
    "kick_onset",
    "pink_noise",
    "concat",
    "delayed_copy",
    "calibrated_pink_noise",
    "synthetic_ir",
    "convolve",
]
