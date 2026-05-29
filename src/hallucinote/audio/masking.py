"""Inter-stem spectral masking — the analysis no commercial tool can produce.

Commercial maskers (iZotope, Sonible, Gullfoss, RoEx) answer *"where do
frequencies collide?"* on the full mix. Because Hallucinote owns per-stem
captures **and** the score, this module answers the measurement half of a
better question — *which stems mask which, per section, and where* — leaving the
**intent** half ("is the element that's supposed to win actually winning?") to
the holistic interpreter, which grades this evidence against recalled composer
intent. See ``.prawduct/artifacts/masking-analyzer-goals.md`` (north star) and
``masking-analyzer-spec.md`` (this DSP).

This module is PURE DSP and DB-agnostic — it operates on whatever stem audio it
is handed, exactly like ``attribution.band_attribution``. That keeps it
synthetic-fixture-testable (the corpus *defines* correctness — there is no
labelled masking ground truth for real music).

Pipeline per window, per stem:

  1. Mono-sum, STFT → power per (frame, FFT-bin).
  2. Bin power → Bark critical-band power (24 Zwicker bands).
  3. Schroeder (1979) two-slope spreading function → per-band *spread
     excitation* (a masker's reach into neighbouring bands).

Then, per ordered pair (masker A, maskee B): B is *masked* in a tile when A's
spread excitation there exceeds B's own band power (minus a masking offset) AND
B carries non-trivial energy there. ``masked_fraction`` = masked tiles / B's
energized tiles. A **bed mode** repeats this with the masker being the *sum of
all other energized stems' excitation* — catching distributed buildup that
pairwise analysis structurally misses.

Two honest limitations baked into the wording, not hidden:

* **Pre-fader levels (F1).** Captured stems are pre-fader; masking is a
  relative-level measure, so real-song output is only valid on mix-level
  reconstructed stems (build-plan C3). The synthetic corpus feeds constructed
  levels directly, so the DSP is correct by construction here.
* **Spectral ≠ perceptual (F3/F4).** Mono-sum is pan-blind, and the ear also
  separates by pitch streaming / common onset / timbre — so same-timbre
  material over-reports. These are caveats the interpreter must carry; they are
  not corrected in the DSP.

Citations: Zwicker & Fastl *Psychoacoustics* (Bark bands); Schroeder, Atal &
Hall (1979) (spreading function); MPEG-1 psychoacoustic model 1 (masking
offset). Constants are literature defaults, calibrated against the corpus.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .report import BedMasking, MaskingPair

# Zwicker critical-band edges in Hz (Bark 1..24 lower edges + top). Standard
# table from Zwicker & Fastl; bands are [edge[i], edge[i+1]). The DSP needs
# critical-band resolution — coarser than attribution's 6 musical bands.
_BARK_EDGES_HZ: tuple[float, ...] = (
    0.0, 100.0, 200.0, 300.0, 400.0, 510.0, 630.0, 770.0, 920.0, 1080.0,
    1270.0, 1480.0, 1720.0, 2000.0, 2320.0, 2700.0, 3150.0, 3700.0, 4400.0,
    5300.0, 6400.0, 7700.0, 9500.0, 12000.0, 15500.0,
)

# Musical region labels (non-overlapping, by band-centre frequency) — the
# engineer's vocabulary the goals doc asks the report to speak. Hz stays under
# the hood in ``dominant_region_hz``.
_MUSICAL_REGIONS: tuple[tuple[str, float, float], ...] = (
    ("sub", 0.0, 60.0),
    ("lows", 60.0, 250.0),
    ("mud", 250.0, 500.0),
    ("body", 500.0, 2000.0),
    ("presence", 2000.0, 5000.0),
    ("brilliance", 5000.0, 8000.0),
    ("air", 8000.0, float("inf")),
)

# STFT calibration (48 kHz: 2048/512 ≈ 43 ms / 11 ms). Calibration parameters.
_DEFAULT_N_FFT = 2048
_DEFAULT_HOP = 512

# Masking offset (dB) subtracted from the masker's spread excitation to get the
# masking threshold. MPEG model 1 uses a tonality-dependent offset (~14.5 dB for
# tone-masking-noise); a fixed 15 dB is the corpus-calibrated MVP default.
_DEFAULT_MASKING_OFFSET_DB = 15.0

# A maskee tile counts toward the denominator only if its band power is within
# this many dB of the loudest band power anywhere in the window across all stems
# (so silence / noise floor never reads as "energized"). Scale-invariant.
_DEFAULT_ENERGY_GATE_DB = 60.0

_DEFAULT_TOP_N = 5

_EPS = 1e-12


@dataclass(frozen=True)
class MaskingWindowResult:
    """Both masking views for one window — ordered pairs + cumulative bed."""
    pairs: list[MaskingPair]
    bed: list[BedMasking]


def analyze_masking_window(
    stem_segments: Sequence[tuple[str, np.ndarray]],
    sample_rate: int,
    *,
    top_n: int = _DEFAULT_TOP_N,
    n_fft: int = _DEFAULT_N_FFT,
    hop_length: int = _DEFAULT_HOP,
    masking_offset_db: float = _DEFAULT_MASKING_OFFSET_DB,
    energy_gate_db: float = _DEFAULT_ENERGY_GATE_DB,
    reporting_floor: float = 0.0,
) -> MaskingWindowResult:
    """Compute inter-stem masking over a single (pre-sliced) window.

    ``stem_segments`` entries are ``(track_id, audio)`` where audio is mono
    ``(n,)`` or stereo ``(n, 2)`` — the caller slices each stem to the section
    window first (this function is window- and tempo-agnostic, like the rest of
    the audio package). Stems with no energy in the window are excluded
    (energy gate) so a silent stem never divides by zero or over-reports.

    Returns a :class:`MaskingWindowResult`. ``pairs`` keeps, per unordered stem
    pair, only the dominant direction (A masks B more than B masks A → A→B),
    ranked by ``masked_fraction``, top-N, above ``reporting_floor``. ``bed`` is
    one entry per maskee vs the summed excitation of all other energized stems.
    """
    bark = _bark_band_map(sample_rate, n_fft)

    # Per-stem band power [n_bands, n_frames] and spread excitation, keyed by id.
    # Drop stems that are silent or too short to STFT — they cannot mask and
    # cannot be masked meaningfully.
    powers: dict[str, np.ndarray] = {}
    excitations: dict[str, np.ndarray] = {}
    order: list[str] = []
    spread = _spreading_matrix(bark.n_bands)
    for track_id, audio in stem_segments:
        mono = _to_mono(audio)
        if mono.shape[0] < n_fft:
            continue
        band_power = _band_power(mono, sample_rate, n_fft, hop_length, bark)
        if not np.any(band_power > 0.0):
            continue
        powers[track_id] = band_power
        excitations[track_id] = spread @ band_power
        order.append(track_id)

    if len(order) < 2:
        return MaskingWindowResult(pairs=[], bed=[])

    # Align all stems to the shortest frame count (windows can differ by a
    # frame at the STFT boundary) so tile-wise comparisons are well-defined.
    n_frames = min(p.shape[1] for p in powers.values())
    for tid in order:
        powers[tid] = powers[tid][:, :n_frames]
        excitations[tid] = excitations[tid][:, :n_frames]

    # Window-global energy reference for the gate (loudest band power anywhere).
    max_power_db = max(
        float(10.0 * np.log10(p.max() + _EPS)) for p in powers.values()
    )
    gate_db = max_power_db - energy_gate_db

    pairs = _ordered_pairs(
        order, powers, excitations, bark,
        masking_offset_db=masking_offset_db, gate_db=gate_db,
    )
    pairs = [p for p in pairs if p.masked_fraction >= reporting_floor]
    pairs.sort(key=lambda p: p.masked_fraction, reverse=True)

    bed = _bed_masking(
        order, powers, excitations, bark,
        masking_offset_db=masking_offset_db, gate_db=gate_db,
    )
    bed = [b for b in bed if b.masked_fraction >= reporting_floor]
    bed.sort(key=lambda b: b.masked_fraction, reverse=True)

    return MaskingWindowResult(pairs=pairs[:top_n], bed=bed[:top_n])


# --------------------------------------------------------------------------- #
# Core per-pair / per-bed computation
# --------------------------------------------------------------------------- #

def _ordered_pairs(
    order: list[str],
    powers: dict[str, np.ndarray],
    excitations: dict[str, np.ndarray],
    bark: "_BarkMap",
    *,
    masking_offset_db: float,
    gate_db: float,
) -> list[MaskingPair]:
    """One entry per unordered stem pair — the dominant direction only."""
    out: list[MaskingPair] = []
    for i in range(len(order)):
        for j in range(i + 1, len(order)):
            a, b = order[i], order[j]
            fa, banda, hza = _masked_fraction(
                excitations[a], powers[b], gate_db, masking_offset_db, bark,
            )
            fb, bandb, hzb = _masked_fraction(
                excitations[b], powers[a], gate_db, masking_offset_db, bark,
            )
            if fa >= fb:
                out.append(MaskingPair(a, b, fa, banda, hza))
            else:
                out.append(MaskingPair(b, a, fb, bandb, hzb))
    return out


def _bed_masking(
    order: list[str],
    powers: dict[str, np.ndarray],
    excitations: dict[str, np.ndarray],
    bark: "_BarkMap",
    *,
    masking_offset_db: float,
    gate_db: float,
) -> list[BedMasking]:
    """Each maskee vs the SUM of every other stem's spread excitation."""
    out: list[BedMasking] = []
    for tid in order:
        bed_exc = sum(
            (excitations[other] for other in order if other != tid),
            start=np.zeros_like(excitations[tid]),
        )
        frac, band, hz = _masked_fraction(
            bed_exc, powers[tid], gate_db, masking_offset_db, bark,
        )
        out.append(BedMasking(tid, frac, band, hz))
    return out


def _masked_fraction(
    masker_excitation: np.ndarray,
    maskee_power: np.ndarray,
    gate_db: float,
    masking_offset_db: float,
    bark: "_BarkMap",
) -> tuple[float, str, tuple[float, float]]:
    """Fraction of the maskee's energized tiles the masker covers, + where.

    A tile (band, frame) is *energized* for the maskee when its power is within
    the gate of the window max. It is *masked* when the masker's spread
    excitation there, minus the offset, exceeds the maskee's own band power.
    Returns (fraction, dominant musical-region label, dominant Hz edges).
    """
    maskee_db = 10.0 * np.log10(maskee_power + _EPS)
    threshold_db = 10.0 * np.log10(masker_excitation + _EPS) - masking_offset_db

    energized = maskee_db > gate_db
    n_energized = int(np.count_nonzero(energized))
    if n_energized == 0:
        return 0.0, "", (0.0, 0.0)

    masked = energized & (maskee_db < threshold_db)
    fraction = float(np.count_nonzero(masked) / n_energized)

    # Dominant region = the Bark band carrying the most *masked* maskee energy.
    if not np.any(masked):
        return fraction, "", (0.0, 0.0)
    masked_energy_per_band = np.where(masked, maskee_power, 0.0).sum(axis=1)
    dom_band = int(np.argmax(masked_energy_per_band))
    lo, hi = bark.edges_hz[dom_band], bark.edges_hz[dom_band + 1]
    return fraction, _region_label((lo + hi) / 2.0), (lo, hi)


# --------------------------------------------------------------------------- #
# Bark mapping + spreading function
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class _BarkMap:
    """Precomputed FFT-bin → Bark-band assignment for one (sr, n_fft)."""
    n_bands: int
    bin_band: np.ndarray   # [n_bins] band index per FFT bin (-1 = out of range)
    edges_hz: np.ndarray   # [n_bands + 1] band edge frequencies


def _bark_band_map(sample_rate: int, n_fft: int) -> _BarkMap:
    nyq = sample_rate / 2.0
    edges = [e for e in _BARK_EDGES_HZ if e < nyq]
    edges.append(min(_BARK_EDGES_HZ[-1], nyq))
    edges_arr = np.asarray(edges, dtype=np.float64)
    n_bands = len(edges_arr) - 1

    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    # Band index for each bin: edges[k] <= f < edges[k+1].
    idx = np.searchsorted(edges_arr, freqs, side="right") - 1
    idx[(freqs < edges_arr[0]) | (freqs >= edges_arr[-1])] = -1
    return _BarkMap(n_bands=n_bands, bin_band=idx, edges_hz=edges_arr)


def _band_power(
    mono: np.ndarray,
    sample_rate: int,
    n_fft: int,
    hop_length: int,
    bark: _BarkMap,
) -> np.ndarray:
    """STFT power summed into Bark bands → [n_bands, n_frames]."""
    import librosa

    stft = librosa.stft(
        mono.astype(np.float32), n_fft=n_fft, hop_length=hop_length,
        window="hann", center=True,
    )
    power = (np.abs(stft) ** 2).astype(np.float64)  # [n_bins, n_frames]
    n_frames = power.shape[1]
    band_power = np.zeros((bark.n_bands, n_frames), dtype=np.float64)
    valid = bark.bin_band >= 0
    np.add.at(band_power, bark.bin_band[valid], power[valid])
    return band_power


def _spreading_matrix(n_bands: int) -> np.ndarray:
    """Schroeder (1979) two-slope spreading function as a [n_bands, n_bands]
    linear-power matrix. ``S[i, j]`` = how much a masker in band ``j`` raises
    excitation in band ``i`` (``dz = i - j`` Bark; upward spread is stronger).
    Excitation = S @ band_power.
    """
    i = np.arange(n_bands)[:, None]
    j = np.arange(n_bands)[None, :]
    dz = (i - j).astype(np.float64)
    sf_db = (
        15.81
        + 7.5 * (dz + 0.474)
        - 17.5 * np.sqrt(1.0 + (dz + 0.474) ** 2)
    )
    return 10.0 ** (sf_db / 10.0)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _to_mono(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 2:
        return 0.5 * (audio[:, 0] + audio[:, 1])
    return audio


def _region_label(center_hz: float) -> str:
    for name, lo, hi in _MUSICAL_REGIONS:
        if lo <= center_hz < hi:
            return f"{name} ({_fmt_hz(lo)}-{_fmt_hz(hi)})"
    return "air (8k+)"


def _fmt_hz(hz: float) -> str:
    if hz == float("inf"):
        return "20k"
    if hz >= 1000.0:
        return f"{hz / 1000.0:g}k"
    return f"{hz:g}"


__all__ = [
    "MaskingWindowResult",
    "analyze_masking_window",
]
