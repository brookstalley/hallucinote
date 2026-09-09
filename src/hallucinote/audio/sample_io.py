"""The second front door: load any audio file into the array shape this package measures.

``io.py``'s capture loader refuses anything but the analyzer's float32 stereo,
and that refusal is correct — the mix maths depends on it. A sample arrives
from anywhere: a 22.05 kHz mono dialogue rip, a 5.1 stem, a 24-bit 96 kHz
field recording. This loader normalizes all of them *into* ``(n, 2)`` float32
at a chosen rate so every existing measurement module reads a sample exactly
as it reads a stem, and none of them learns a second shape.

Discipline: mono is duplicated, more than two channels are folded by an
equal-power sum, and resampling is polyphase (``scipy.signal.resample_poly``)
at the exact rational ratio — no interpolation drift across a long file.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


@dataclass(frozen=True)
class SampleAudio:
    """One loaded sample, normalized to the package's array shape.

    ``audio`` is ``(n_samples, 2)`` float32 at ``sr``; ``source_sr`` and
    ``source_channels`` say what the file held before normalization, so a
    consumer can tell a genuine stereo source from a duplicated mono one and
    a resampled file from a native one.
    """

    audio: np.ndarray
    sr: int
    source_sr: int
    source_channels: int
    path: Path

    @property
    def duration_s(self) -> float:
        return self.audio.shape[0] / self.sr


def as_mono(audio: np.ndarray) -> np.ndarray:
    """The one mono fold every feature stream measures from, as float64.

    Accepts ``(n,)``, ``(n, 1)``, ``(n, 2)`` and wider; channels are averaged
    (a stereo file's centre), so a mono file duplicated to stereo by
    :func:`load_sample` measures identically to the original mono.
    """
    arr = np.asarray(audio, dtype=np.float64)
    if arr.ndim == 1:
        return arr
    if arr.ndim != 2 or arr.shape[1] < 1:
        raise ValueError(
            f"audio must be (n,) or (n_samples, n_channels); got shape {arr.shape}"
        )
    return arr.mean(axis=1)


def fold_to_stereo(audio: np.ndarray) -> np.ndarray:
    """``(n, k)`` for any ``k`` → ``(n, 2)`` float32.

    Mono is duplicated so a centred source stays centred and at the same
    level per channel. More than two channels are summed with a ``1/sqrt(k)``
    gain — an equal-power fold — because the channels of a surround stem are
    largely uncorrelated and a plain sum would raise the level by up to
    ``k`` times; the fold is duplicated to both sides since the file carries
    no layout the loader could trust to assign channels to left and right.
    """
    arr = np.asarray(audio, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[:, None]
    if arr.ndim != 2 or arr.shape[1] < 1:
        raise ValueError(
            f"audio must be (n_samples, n_channels) with at least one channel; "
            f"got shape {arr.shape}"
        )
    n_ch = arr.shape[1]
    if n_ch == 2:
        return arr
    if n_ch == 1:
        return np.repeat(arr, 2, axis=1)
    fold = arr.sum(axis=1, dtype=np.float64) / np.sqrt(n_ch)
    return np.repeat(fold.astype(np.float32)[:, None], 2, axis=1)


def resample(audio: np.ndarray, sr: int, target_sr: int) -> np.ndarray:
    """Polyphase resample along axis 0 at the exact rational ``target_sr / sr``.

    ``resample_poly`` works from an integer up/down pair; reducing by the gcd
    keeps the filter short (44.1 kHz → 48 kHz is 160/147, not 48000/44100).
    """
    if target_sr <= 0:
        raise ValueError(f"target_sr must be > 0 Hz; got {target_sr}")
    if sr <= 0:
        raise ValueError(f"sr must be > 0 Hz; got {sr}")
    if target_sr == sr:
        return np.asarray(audio, dtype=np.float32)
    g = gcd(int(target_sr), int(sr))
    out = resample_poly(np.asarray(audio, dtype=np.float64), target_sr // g, sr // g, axis=0)
    return np.asarray(out, dtype=np.float32)


def load_sample(path: Path | str, *, target_sr: int | None = None) -> SampleAudio:
    """Read any file ``soundfile`` can open as ``(n, 2)`` float32.

    ``target_sr=None`` keeps the file's own rate; pass the song's session
    rate to align a sample with a capture set. Raises ``FileNotFoundError``
    for a missing file and ``ValueError`` for a file that is not audio, is
    empty, or a non-positive ``target_sr`` — each naming what to do.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(
            f"sample not found at {p}. Pass the path to an audio file "
            f"(WAV, AIFF, FLAC, OGG — anything libsndfile reads)."
        )
    if target_sr is not None and target_sr <= 0:
        raise ValueError(
            f"target_sr must be a positive sample rate in Hz or None to keep the "
            f"file's rate; got {target_sr}"
        )
    try:
        raw, source_sr = sf.read(str(p), dtype="float32", always_2d=True)
    except sf.LibsndfileError as exc:
        raise ValueError(
            f"{p} is not an audio file libsndfile can read ({exc}). Convert it "
            f"to WAV/AIFF/FLAC first; compressed containers such as MP4/M4A are "
            f"outside this loader."
        ) from exc
    if raw.shape[0] == 0:
        raise ValueError(f"{p} holds no samples; an empty file cannot be measured")

    source_channels = int(raw.shape[1])
    stereo = fold_to_stereo(raw)
    sr = int(source_sr)
    if target_sr is not None and target_sr != sr:
        stereo = resample(stereo, sr, target_sr)
        sr = int(target_sr)
    return SampleAudio(
        audio=np.ascontiguousarray(stereo, dtype=np.float32),
        sr=sr,
        source_sr=int(source_sr),
        source_channels=source_channels,
        path=p,
    )


__all__ = ["SampleAudio", "as_mono", "fold_to_stereo", "load_sample", "resample"]
