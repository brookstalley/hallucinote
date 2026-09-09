"""F0 contour of a sample — pitch in Hz over time, with a voicing confidence.

Probabilistic YIN (``librosa.pyin``, verified against librosa 0.11.0: the
signature is ``pyin(y, *, fmin, fmax, sr, frame_length, hop_length, ...,
fill_na=nan)`` returning ``(f0, voiced_flag, voiced_prob)``) because it gives
a per-frame voicing *probability* rather than a hard gate, and a follower
wants to know how sure the detector was before it writes a note.

Discipline: unvoiced frames carry ``nan``, never 0 — zero is a pitch, and a
consumer that quantizes it gets a note nobody sang. ``fmin`` / ``fmax`` are
required: the range is a musical fact about the material (a spoken line,
a bass, a whistle), and a default here would be a decision taken on the
caller's behalf that silently shapes every contour.
"""
from __future__ import annotations

import numpy as np

from hallucinote.audio.sample_io import as_mono
from hallucinote.features.types import FeatureStream

STREAM_NAME = "f0"

# pyin needs several periods of the lowest pitch in one frame to see it; four
# periods of fmin, rounded up to a power of two, is the floor that keeps a
# 60 Hz fundamental resolvable at 48 kHz (4096) without paying for it on a
# high-pitched source. Never shorter than pyin's own 2048 default.
_MIN_FRAME_LENGTH = 2048
_PERIODS_PER_FRAME = 4


def default_frame_length(sr: int, fmin: float) -> int:
    """Frame long enough to hold ``_PERIODS_PER_FRAME`` periods of ``fmin``."""
    need = _PERIODS_PER_FRAME * sr / fmin
    n = _MIN_FRAME_LENGTH
    while n < need:
        n *= 2
    return n


def f0_contour(
    audio: np.ndarray,
    sr: int,
    *,
    fmin: float,
    fmax: float,
    frame_length: int | None = None,
    hop_length: int | None = None,
) -> FeatureStream:
    """The F0 contour, in Hz, with ``confidence`` = pyin's voiced probability.

    ``frame_length`` defaults to :func:`default_frame_length`; ``hop_length``
    to a quarter of it (librosa's convention). Frame times follow librosa's
    centred frames, so frame ``i`` sits at ``i * hop_length / sr``.
    """
    if sr <= 0:
        raise ValueError(f"sr must be > 0 Hz; got {sr}")
    if fmin <= 0:
        raise ValueError(f"fmin must be > 0 Hz; got {fmin}")
    if fmax <= fmin:
        raise ValueError(f"fmax ({fmax}) must exceed fmin ({fmin})")
    if fmax >= sr / 2:
        raise ValueError(
            f"fmax ({fmax} Hz) must sit below Nyquist ({sr / 2} Hz) for sr={sr}"
        )
    mono = as_mono(audio)
    if mono.shape[0] == 0:
        raise ValueError("audio holds no samples; there is no contour to track")

    frame = frame_length if frame_length is not None else default_frame_length(sr, fmin)
    hop = hop_length if hop_length is not None else frame // 4
    if frame <= 0 or hop <= 0:
        raise ValueError(
            f"frame_length ({frame}) and hop_length ({hop}) must be positive sample counts"
        )

    import librosa

    f0, _voiced_flag, voiced_prob = librosa.pyin(
        mono.astype(np.float32),
        fmin=float(fmin),
        fmax=float(fmax),
        sr=sr,
        frame_length=frame,
        hop_length=hop,
        fill_na=np.nan,
        center=True,
    )
    values = np.asarray(f0, dtype=np.float64)
    times = np.asarray(
        librosa.frames_to_time(np.arange(values.shape[0]), sr=sr, hop_length=hop),
        dtype=np.float64,
    )
    confidence = np.clip(np.asarray(voiced_prob, dtype=np.float64), 0.0, 1.0)
    return FeatureStream(
        name=STREAM_NAME,
        times_s=times,
        values=values,
        units="Hz",
        confidence=confidence,
    )


__all__ = ["STREAM_NAME", "default_frame_length", "f0_contour"]
