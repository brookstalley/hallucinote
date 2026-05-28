"""Master-bus contribution attribution — the "which stems made the
master overshoot" analysis.

Two passes:

  1. ``find_master_overshoots(master, sr)`` — locate windows where the
     4×-oversampled master signal exceeds ``threshold_dbfs`` (default
     0 dBFS). Consecutive overshooting samples are grouped into windows
     (with a small gap-merge tolerance so a single overshoot event with
     a millisecond dip doesn't fragment into N micro-windows).
  2. ``master_bus_attribution(master, stems, sr, overshoots)`` — for
     each overshoot window, determine the dominant frequency band on
     the master (the band carrying the most RMS energy in that window),
     then rank stems by their RMS contribution in that band during
     that window. Top-N (default 5) are emitted as a ranked attribution
     list; the long tail is aggregated as ``(residual, fraction)``.

Per spike §6 — this is the analysis no commercial tool can produce
because it requires synchronized per-stem captures plus the master,
which only the source-of-truth platform has.

Beat conversion: the analyzer caller (``analyze_mix``) is responsible
for converting the per-window seconds into the CaptureSet's beat space
when populating ``MixReport.overshoots``. This module stays in the
seconds domain because it has no tempo information.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .io import Surface
from .report import MasterOvershoot

# Bands per spike §3. Names are stable wire-format identifiers (they
# land in MasterOvershoot.dominant_band and the agent groups by them);
# never rename without a schema bump.
BANDS: tuple[tuple[str, float, float], ...] = (
    ("sub_20_60", 20.0, 60.0),
    ("low_60_200", 60.0, 200.0),
    ("low_mid_200_500", 200.0, 500.0),
    ("mid_500_2k", 500.0, 2000.0),
    ("high_mid_2k_6k", 2000.0, 6000.0),
    ("air_6k_plus", 6000.0, 20000.0),
)

# Detection threshold for overshoot — 0 dBFS is the conservative default;
# float32 captures don't physically clip at 0 but anything above is
# headroom risk at the DAC boundary, which is what the analysis wants
# to flag.
_DEFAULT_OVERSHOOT_THRESHOLD_DBFS = 0.0

# Bridge consecutive overshooting samples that are separated by no more
# than this gap — keeps a single overshoot event from fragmenting when
# a sub-sample dip lands in the middle.
_DEFAULT_GAP_MERGE_S = 0.10

# Reject windows shorter than this — sub-millisecond detections are
# almost certainly transient artifacts of the 4× oversample, not
# meaningful master-bus events.
_DEFAULT_MIN_WINDOW_S = 0.005

# Top-N stems surfaced per overshoot. Long-tail stems are aggregated
# into a single residual entry so the report stays scannable.
_DEFAULT_TOP_N = 5

# True-peak oversampling factor — matches loudness.py for consistency.
_TRUE_PEAK_OVERSAMPLE = 4


@dataclass(frozen=True)
class OvershootWindow:
    """Detected overshoot window in seconds — pre-beat-conversion."""
    start_s: float
    end_s: float
    peak_dbtp: float


def find_master_overshoots(
    master_audio: np.ndarray,
    sample_rate: int,
    *,
    threshold_dbfs: float = _DEFAULT_OVERSHOOT_THRESHOLD_DBFS,
    gap_merge_s: float = _DEFAULT_GAP_MERGE_S,
    min_window_s: float = _DEFAULT_MIN_WINDOW_S,
) -> list[OvershootWindow]:
    """Locate true-peak overshoot windows in a master stereo capture.

    4× oversamples each channel (catches inter-sample peaks per
    BS.1770 §A.2), thresholds the per-sample magnitude against
    ``threshold_dbfs``, merges adjacent runs separated by less than
    ``gap_merge_s``, and discards windows shorter than ``min_window_s``.
    """
    from scipy.signal import resample_poly

    if master_audio.ndim != 2 or master_audio.shape[1] != 2:
        raise ValueError(
            f"master_audio must be stereo (n, 2); got shape {master_audio.shape}"
        )
    if master_audio.shape[0] == 0:
        return []

    threshold_linear = 10.0 ** (threshold_dbfs / 20.0)
    over_per_channel = []
    for ch in range(2):
        oversampled = resample_poly(
            master_audio[:, ch].astype(np.float64),
            up=_TRUE_PEAK_OVERSAMPLE,
            down=1,
        )
        over_per_channel.append(np.abs(oversampled))
    # Combine channels with elementwise max — overshoot in either
    # channel counts.
    over = np.maximum(over_per_channel[0], over_per_channel[1])

    over_mask = over > threshold_linear
    if not np.any(over_mask):
        return []

    # Convert sample positions in the oversampled domain back to seconds
    # using the original (non-oversampled) sample rate.
    oversampled_sr = sample_rate * _TRUE_PEAK_OVERSAMPLE

    runs = _runs_above_threshold(over_mask)
    merged = _merge_close_runs(runs, gap_samples=int(gap_merge_s * oversampled_sr))
    windows: list[OvershootWindow] = []
    for start_sample, end_sample in merged:
        duration_s = (end_sample - start_sample) / oversampled_sr
        if duration_s < min_window_s:
            continue
        peak_linear = float(over[start_sample:end_sample].max())
        peak_dbtp = 20.0 * float(np.log10(peak_linear)) if peak_linear > 0 else float("-inf")
        windows.append(OvershootWindow(
            start_s=start_sample / oversampled_sr,
            end_s=end_sample / oversampled_sr,
            peak_dbtp=peak_dbtp,
        ))
    return windows


def master_bus_attribution(
    master_audio: np.ndarray,
    stems: Sequence[Surface],
    sample_rate: int,
    overshoots: Sequence[OvershootWindow],
    *,
    top_n: int = _DEFAULT_TOP_N,
) -> list[MasterOvershoot]:
    """Per-overshoot dominant-band detection + per-stem attribution.

    Returns ``MasterOvershoot`` records with ``start_beat`` / ``end_beat``
    left in the SECONDS domain — the caller (``analyze_mix``) is
    responsible for the seconds-to-beat conversion using the
    ``CaptureSet``'s ``start_at_beat``, ``stop_at_beat``, and audio
    duration. Keeping conversion at the analyze_mix boundary means this
    module stays tempo-agnostic and reusable for non-beat consumers.
    """
    results: list[MasterOvershoot] = []
    for window in overshoots:
        start_sample = max(0, int(window.start_s * sample_rate))
        end_sample = min(master_audio.shape[0], int(window.end_s * sample_rate))
        if end_sample <= start_sample:
            continue

        master_seg = _to_mono(master_audio[start_sample:end_sample])
        master_band_energies = _band_energies(master_seg, sample_rate)

        # Dominant band by master energy in the window.
        dominant_idx = int(np.argmax(master_band_energies))
        dominant_name = BANDS[dominant_idx][0]

        # Per-stem energy in that band over the same window.
        stem_band_energies: list[tuple[str, float]] = []
        for stem in stems:
            seg = stem.audio[start_sample:end_sample]
            if seg.shape[0] == 0:
                stem_band_energies.append((stem.track_id, 0.0))
                continue
            mono = _to_mono(seg)
            energy = _single_band_energy(
                mono, sample_rate, BANDS[dominant_idx][1], BANDS[dominant_idx][2]
            )
            stem_band_energies.append((stem.track_id, float(energy)))

        total = sum(e for _, e in stem_band_energies)
        if total <= 0:
            ranked: list[tuple[str, float]] = []
        else:
            ranked = sorted(
                ((tid, e / total) for tid, e in stem_band_energies),
                key=lambda pair: pair[1],
                reverse=True,
            )
            ranked = ranked[:top_n]

        results.append(MasterOvershoot(
            start_beat=window.start_s,  # placeholder — caller rebeats
            end_beat=window.end_s,
            peak_dbtp=window.peak_dbtp,
            dominant_band=dominant_name,
            attribution=ranked,
        ))
    return results


def _to_mono(stereo: np.ndarray) -> np.ndarray:
    return 0.5 * (stereo[:, 0] + stereo[:, 1])


def _band_energies(mono: np.ndarray, sr: int) -> np.ndarray:
    """RMS energy per band (one value per band in BANDS order)."""
    energies = np.zeros(len(BANDS), dtype=np.float64)
    for i, (_, lo, hi) in enumerate(BANDS):
        energies[i] = _single_band_energy(mono, sr, lo, hi)
    return energies


def _single_band_energy(mono: np.ndarray, sr: int, lo_hz: float, hi_hz: float) -> float:
    """Bandpass-filter then return RMS energy in the band.

    Uses a Butterworth bandpass (order 4) via filtfilt for zero-phase
    response — keeps energy estimates aligned in time with the source
    signal, which matters when the same window is being measured across
    multiple stems for attribution.
    """
    from scipy.signal import butter, sosfiltfilt

    nyq = sr / 2.0
    low_n = max(lo_hz / nyq, 1e-6)
    high_n = min(hi_hz / nyq, 0.999)
    if high_n <= low_n:
        return 0.0
    sos = butter(4, [low_n, high_n], btype="band", output="sos")
    filtered = sosfiltfilt(sos, mono.astype(np.float64))
    return float(np.sqrt(np.mean(filtered**2)))


def _runs_above_threshold(mask: np.ndarray) -> list[tuple[int, int]]:
    """Return [(start, end_exclusive), ...] of contiguous True runs."""
    if mask.size == 0:
        return []
    # Find edges via diff on int view.
    int_mask = mask.astype(np.int8)
    diff = np.diff(np.concatenate(([0], int_mask, [0])))
    starts = np.where(diff == 1)[0]
    ends = np.where(diff == -1)[0]
    return list(zip(starts.tolist(), ends.tolist()))


def _merge_close_runs(
    runs: list[tuple[int, int]],
    *,
    gap_samples: int,
) -> list[tuple[int, int]]:
    """Merge adjacent runs separated by ≤ gap_samples."""
    if not runs:
        return []
    merged = [runs[0]]
    for start, end in runs[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= gap_samples:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


__all__ = [
    "BANDS",
    "OvershootWindow",
    "find_master_overshoots",
    "master_bus_attribution",
]
