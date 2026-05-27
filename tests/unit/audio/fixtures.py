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


__all__ = [
    "SAMPLE_RATE",
    "silence",
    "sine",
    "kick_onset",
    "pink_noise",
    "delayed_copy",
]
