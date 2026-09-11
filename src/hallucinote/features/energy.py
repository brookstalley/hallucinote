"""Energy envelope and spectral descriptor streams of a sample, on one hop.

The per-surface timbre report (``audio/timbre.py``) reduces a whole surface
to a median; a generator needs the same measurements as *streams* — how
bright is this syllable, how loud is that one — so this module frames the
sample once (the timbre lens's 2048-point Hann STFT, on a hop given in
seconds) and exposes every descriptor over that grid: RMS energy, spectral
centroid, flatness, rolloff, and Bark-band energies. The per-frame maths is
the timbre and Bark helpers themselves, so a stream and the report never
disagree about what "centroid" means.

Discipline: energy is measurable in silence (it is the floor), so the
envelope is finite everywhere; timbre is not, so a descriptor frame that is
silent — more than ``SILENCE_GATE_DB`` below the loudest frame — carries
``nan``, the same sentinel the report uses.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hallucinote.audio.bark import aggregate_to_bands, bark_band_map
from hallucinote.audio.sample_io import as_mono
from hallucinote.audio.timbre import _band_flatness, _centroid_from_spectrum, _rolloff_hz
from hallucinote.features.types import FeatureStream

# 2048 @ 48 kHz ≈ 43 ms — the frame the masking and timbre lenses share, so
# their readings and these streams sit on one grid.
N_FFT = 2048
# 10 ms is the speech-analysis convention: fine enough to follow a syllable,
# coarse enough that a 30 s line is a few thousand frames.
DEFAULT_HOP_S = 0.010
# Digital silence has no logarithm; -120 dBFS is below any 20-bit noise floor
# and keeps the envelope finite so a consumer can difference and smooth it.
SILENCE_FLOOR_DBFS = -120.0
# A descriptor frame this far below the loudest frame is the noise floor, and
# its "timbre" is a fit of nothing — the timbre lens's own gate.
SILENCE_GATE_DB = 60.0
# Floor for band energies in dB; a Bark band with zero power is a hole, not
# minus infinity.
_BAND_FLOOR_DB = -120.0

ENERGY_STREAM = "energy"
CENTROID_STREAM = "spectral_centroid"
FLATNESS_STREAM = "spectral_flatness"
ROLLOFF_STREAM = "spectral_rolloff"
BARK_STREAM = "bark_bands"


def hop_samples(sr: int, hop_s: float) -> int:
    if hop_s <= 0:
        raise ValueError(f"hop_s must be positive seconds; got {hop_s}")
    return max(1, int(round(hop_s * sr)))


def _frame_times(n_frames: int, sr: int, hop: int) -> np.ndarray:
    """Centred-frame convention (librosa ``center=True``): frame ``i`` at ``i·hop/sr``."""
    return np.arange(n_frames, dtype=np.float64) * hop / sr


def _mono_or_refuse(audio: np.ndarray, sr: int) -> np.ndarray:
    if sr <= 0:
        raise ValueError(f"sr must be > 0 Hz; got {sr}")
    mono = as_mono(audio)
    if mono.shape[0] == 0:
        raise ValueError("audio holds no samples; there is nothing to measure")
    return mono


def energy_envelope(
    audio: np.ndarray, sr: int, hop_s: float = DEFAULT_HOP_S, *, frame_length: int = N_FFT
) -> FeatureStream:
    """RMS level per frame in dB relative to full scale (``20·log10(rms)``).

    A full-scale square wave reads 0 dBFS and a full-scale sine −3 dBFS —
    the plain RMS convention, with no sine-referenced offset. Floored at
    ``SILENCE_FLOOR_DBFS`` so the stream is finite through silence.
    """
    mono = _mono_or_refuse(audio, sr)
    hop = hop_samples(sr, hop_s)

    import librosa

    rms = librosa.feature.rms(
        y=mono.astype(np.float32), frame_length=frame_length, hop_length=hop, center=True
    )[0].astype(np.float64)
    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(rms)
    finite = np.nan_to_num(db, nan=SILENCE_FLOOR_DBFS, neginf=SILENCE_FLOOR_DBFS)
    values = np.maximum(finite, SILENCE_FLOOR_DBFS)
    return FeatureStream(
        name=ENERGY_STREAM,
        times_s=_frame_times(values.shape[0], sr, hop),
        values=values,
        units="dBFS",
    )


@dataclass(frozen=True)
class SpectralDescriptors:
    """The four descriptor streams of one sample, on one frame grid.

    ``bark_bands`` is a vector stream ``(n_frames, n_bands)`` in dB of STFT
    power — uncalibrated, so compare bands and frames within a file, never
    against a dBFS number.
    """

    centroid: FeatureStream
    flatness: FeatureStream
    rolloff: FeatureStream
    bark_bands: FeatureStream


def spectral_descriptors(
    audio: np.ndarray, sr: int, hop_s: float = DEFAULT_HOP_S, *, n_fft: int = N_FFT
) -> SpectralDescriptors:
    """Centroid, flatness, rolloff and Bark-band energies from one STFT.

    Silent frames (see ``SILENCE_GATE_DB``) carry ``nan`` in every stream;
    ``confidence`` is 1 where a frame was measured and 0 where it was gated,
    so a consumer can mask without re-deriving the gate.
    """
    mono = _mono_or_refuse(audio, sr)
    hop = hop_samples(sr, hop_s)
    if n_fft <= 0:
        raise ValueError(f"n_fft must be > 0; got {n_fft}")

    import librosa

    stft = librosa.stft(
        mono.astype(np.float32), n_fft=n_fft, hop_length=hop, window="hann", center=True
    )
    power = (np.abs(stft) ** 2).astype(np.float64)  # [n_bins, n_frames]
    n_frames = power.shape[1]
    frame_total = power.sum(axis=0)
    peak = float(frame_total.max()) if n_frames else 0.0
    measured = np.zeros(n_frames, dtype=bool)
    if peak > 0.0:
        measured = frame_total >= peak * 10.0 ** (-SILENCE_GATE_DB / 10.0)

    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    centroid = np.full(n_frames, np.nan)
    rolloff = np.full(n_frames, np.nan)
    flatness = np.full(n_frames, np.nan)
    bark = bark_band_map(sr, n_fft)
    bands_db = np.full((n_frames, bark.n_bands), np.nan)
    if np.any(measured):
        p = power[:, measured]
        centroid[measured] = [
            _centroid_from_spectrum(p[:, j], n_fft, sr) for j in range(p.shape[1])
        ]
        rolloff[measured] = _rolloff_hz(p, frame_total[measured], freqs)
        band_power = aggregate_to_bands(p, bark)  # [n_bands, n_frames_kept]
        flatness[measured] = _band_flatness(band_power)
        with np.errstate(divide="ignore"):
            db = 10.0 * np.log10(band_power.T)
        bands_db[measured] = np.maximum(
            np.nan_to_num(db, nan=_BAND_FLOOR_DB, neginf=_BAND_FLOOR_DB), _BAND_FLOOR_DB
        )

    times = _frame_times(n_frames, sr, hop)
    confidence = measured.astype(np.float64)
    return SpectralDescriptors(
        centroid=FeatureStream(CENTROID_STREAM, times, centroid, "Hz", confidence),
        flatness=FeatureStream(FLATNESS_STREAM, times, flatness, "ratio", confidence),
        rolloff=FeatureStream(ROLLOFF_STREAM, times, rolloff, "Hz", confidence),
        bark_bands=FeatureStream(BARK_STREAM, times, bands_db, "dB", confidence),
    )


def spectral_centroid(audio: np.ndarray, sr: int, hop_s: float = DEFAULT_HOP_S) -> FeatureStream:
    return spectral_descriptors(audio, sr, hop_s).centroid


def spectral_flatness(audio: np.ndarray, sr: int, hop_s: float = DEFAULT_HOP_S) -> FeatureStream:
    return spectral_descriptors(audio, sr, hop_s).flatness


def spectral_rolloff(audio: np.ndarray, sr: int, hop_s: float = DEFAULT_HOP_S) -> FeatureStream:
    return spectral_descriptors(audio, sr, hop_s).rolloff


def bark_band_energies(audio: np.ndarray, sr: int, hop_s: float = DEFAULT_HOP_S) -> FeatureStream:
    return spectral_descriptors(audio, sr, hop_s).bark_bands


__all__ = [
    "BARK_STREAM",
    "CENTROID_STREAM",
    "DEFAULT_HOP_S",
    "ENERGY_STREAM",
    "FLATNESS_STREAM",
    "N_FFT",
    "ROLLOFF_STREAM",
    "SILENCE_FLOOR_DBFS",
    "SILENCE_GATE_DB",
    "SpectralDescriptors",
    "bark_band_energies",
    "energy_envelope",
    "hop_samples",
    "spectral_centroid",
    "spectral_descriptors",
    "spectral_flatness",
    "spectral_rolloff",
]
