"""Dialogue intelligibility — the speech band over the bed, per turn, measured.

The film-mix question is "can I hear the line?", and the answer has two
halves: how far the voice sits above the music in the band that carries
speech, and how much of the voice the music's spread excitation covers. Both
are the masking lens (``masking.py``) run for ONE element against everything
else — the speech surface as the maskee, the summed bed as the masker — and
restricted to the Bark bands that cover the speech band, reported per spoken
turn rather than per section. The same spreading model, the same energy gate
and masking offset; this module adds only the per-band split, the per-turn
slicing and the level pair beside the fraction.

Pure DSP, DB-agnostic, like the rest of the package: it is handed two
surfaces and a list of turns in seconds and returns numbers. It never decides
whether a number is a problem — a line that sits under the music may be
exactly the mix the director asked for — so there is no threshold, no grade
and no ``Finding`` here; the report carries the rows and the interpreter
frames them.

Why the masking module's private helpers rather than its public
``analyze_masking_window``: the public function pools every Bark band the
maskee has energy in and returns one fraction with one dominant band. A
speech reading needs the fraction PER band and restricted TO the speech band
— pooling the voice's low-frequency chest energy into the number is how a
warm bed reads as "masking the dialogue" while every consonant is clear. The
band power and spreading matrix are reused so the two lenses can never
disagree about what a tile is or how a masker reaches into a neighbour.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from ..features.types import Segment
from .bark import BarkMap, bark_band_map
from .io import Surface
from .masking import (
    _DEFAULT_ENERGY_GATE_DB,
    _DEFAULT_HOP,
    _DEFAULT_MASKING_OFFSET_DB,
    _DEFAULT_N_FFT,
    _band_power,
    _spreading_matrix,
    _to_mono,
)
from .report import IntelligibilityBand, TurnIntelligibility

# The band that carries speech intelligibility — the telephone band. Vowels
# and voicing sit in its lower half, the formants that separate one vowel
# from another across its middle, and the first consonant cues at its top.
# The Bark bands that overlap this span are the ones measured; the split into
# Bark bands (rather than a single 300–3400 Hz filter) is what lets a reader
# see a bed that covers the vowels but leaves the consonants alone.
SPEECH_BAND_HZ: tuple[float, float] = (300.0, 3400.0)

_EPS = 1e-12

# Surface identity the summed bed carries into the measurement. A bed is a
# construct of the analysis, not a captured surface, so the id cannot collide
# with the capture manifest's ``track:N`` / ``return:N`` / ``master`` ids.
BED_SURFACE_ID = "bed"


@dataclass(frozen=True)
class _TurnSlice:
    """Sample bounds of one turn against the surfaces, after clamping."""
    start: int
    end: int


def speech_bark_bands(bark: BarkMap) -> list[int]:
    """Indices of the Bark bands that overlap the speech band, low to high.

    Overlap, not containment: the top Bark band that reaches 3400 Hz is
    3150–3700, and dropping it would leave the /s/–/f/ region unmeasured
    while including it costs only 300 Hz of extra band above the edge.
    """
    lo_hz, hi_hz = SPEECH_BAND_HZ
    edges = bark.edges_hz
    return [
        i for i in range(bark.n_bands)
        if edges[i] < hi_hz and edges[i + 1] > lo_hz
    ]


def sum_bed(
    stems: Sequence[tuple[str, np.ndarray]],
    *,
    sample_rate: int,
    like: np.ndarray,
) -> Surface:
    """The bed: every stem handed in, summed into one surface.

    Stems arrive pre-sliced and pre-gained by the caller (mix-level, the F1
    correction the masking lens also applies) so this is a plain sum. ``like``
    is the speech audio, whose shape the bed takes when there is nothing to
    sum — a speech track alone in a capture has a silent bed, and the
    measurement must still run and read zero masking rather than fail on a
    shape it cannot infer.
    """
    n = like.shape[0]
    bed = np.zeros_like(like, dtype=np.float32)
    for _track_id, audio in stems:
        m = min(n, audio.shape[0])
        bed[:m] += audio[:m].astype(np.float32, copy=False)
    return Surface(
        track_id=BED_SURFACE_ID,
        surface_kind="track",
        surface_name="bed",
        audio=bed,
        sample_rate=sample_rate,
    )


def measure_intelligibility(
    speech: Surface,
    bed: Surface,
    sr: int,
    *,
    turns: Sequence[Segment],
    n_fft: int = _DEFAULT_N_FFT,
    hop_length: int = _DEFAULT_HOP,
    masking_offset_db: float = _DEFAULT_MASKING_OFFSET_DB,
    energy_gate_db: float = _DEFAULT_ENERGY_GATE_DB,
) -> list[TurnIntelligibility]:
    """Per turn: the speech band's level over the bed, and how much is masked.

    ``speech`` and ``bed`` are full-length surfaces at ``sr``; ``turns`` are
    spans in seconds against them (``Segment.start_s`` / ``end_s``), one per
    spoken line, and one row comes back per turn in the same order with
    ``turn_index`` naming its position. A turn is analysed on its own slice —
    the energy gate is relative to the loudest tile within that turn, across
    both surfaces — so a whispered line is judged against the bed under it,
    not against the shout three lines later.

    A turn whose clamped span is shorter than one analysis window cannot be
    transformed; its row is returned with ``n_frames == 0`` and every
    measurement NaN rather than dropped, so the report's turn count always
    matches the declared placements.

    The sample rate is taken explicitly and checked against both surfaces:
    a bed resampled to a different rate than the speech would shift every
    Bark band under the speech and the numbers would still look plausible.
    """
    if sr <= 0:
        raise ValueError(f"sr must be > 0; got {sr}")
    for name, surface in (("speech", speech), ("bed", bed)):
        if surface.sample_rate != sr:
            raise ValueError(
                f"{name} surface is at {surface.sample_rate} Hz but the "
                f"measurement was asked for at {sr} Hz — resample the surfaces "
                "to one rate before measuring, or pass that rate as sr"
            )
    speech_mono = _to_mono(speech.audio)
    bed_mono = _to_mono(bed.audio)
    n_samples = min(speech_mono.shape[0], bed_mono.shape[0])

    bark = bark_band_map(sr, n_fft)
    bands = speech_bark_bands(bark)
    spread = _spreading_matrix(bark.n_bands)

    rows: list[TurnIntelligibility] = []
    for index, turn in enumerate(turns):
        sl = _clamp_turn(turn, sr, n_samples)
        if sl.end - sl.start < n_fft:
            rows.append(_unmeasured_turn(index, turn, bark, bands))
            continue
        speech_power = _band_power(
            speech_mono[sl.start:sl.end], sr, n_fft, hop_length, bark,
        )
        bed_power = _band_power(
            bed_mono[sl.start:sl.end], sr, n_fft, hop_length, bark,
        )
        # The two STFTs can differ by a frame at the boundary; tile-wise
        # comparison needs one frame count.
        n_frames = min(speech_power.shape[1], bed_power.shape[1])
        speech_power = speech_power[:, :n_frames]
        bed_power = bed_power[:, :n_frames]
        bed_excitation = spread @ bed_power

        rows.append(_measure_turn(
            index, turn, speech_power, bed_power, bed_excitation, bark, bands,
            masking_offset_db=masking_offset_db,
            energy_gate_db=energy_gate_db,
        ))
    return rows


def _clamp_turn(turn: Segment, sr: int, n_samples: int) -> _TurnSlice:
    start = int(round(turn.start_s * sr))
    end = int(round(turn.end_s * sr))
    start = max(0, min(start, n_samples))
    end = max(0, min(end, n_samples))
    return _TurnSlice(start=start, end=max(start, end))


def _measure_turn(
    index: int,
    turn: Segment,
    speech_power: np.ndarray,
    bed_power: np.ndarray,
    bed_excitation: np.ndarray,
    bark: BarkMap,
    bands: list[int],
    *,
    masking_offset_db: float,
    energy_gate_db: float,
) -> TurnIntelligibility:
    """One turn's reading from its band-power matrices.

    The gate and the masking rule are the masking lens's, tile for tile: a
    speech tile is energized when its band power sits within ``energy_gate_db``
    of the loudest tile in the turn (either surface), and masked when the bed's
    spread excitation there, less the offset, exceeds the speech's own power.
    """
    speech_db = 10.0 * np.log10(speech_power + _EPS)
    bed_db = 10.0 * np.log10(bed_power + _EPS)
    threshold_db = 10.0 * np.log10(bed_excitation + _EPS) - masking_offset_db
    gate_db = max(float(speech_db.max()), float(bed_db.max())) - energy_gate_db

    energized = speech_db > gate_db
    masked = energized & (speech_db < threshold_db)

    band_rows: list[IntelligibilityBand] = []
    for b in bands:
        n_energized = int(np.count_nonzero(energized[b]))
        fraction = (
            float(np.count_nonzero(masked[b]) / n_energized)
            if n_energized
            else math.nan
        )
        s_level = _mean_power_db(speech_power[b])
        b_level = _mean_power_db(bed_power[b])
        band_rows.append(IntelligibilityBand(
            lo_hz=float(bark.edges_hz[b]),
            hi_hz=float(bark.edges_hz[b + 1]),
            speech_db=s_level,
            bed_db=b_level,
            speech_over_bed_db=s_level - b_level,
            masked_fraction=fraction,
        ))

    n_energized_all = int(np.count_nonzero(energized[bands]))
    fraction_all = (
        float(np.count_nonzero(masked[bands]) / n_energized_all)
        if n_energized_all
        else math.nan
    )
    speech_level = _mean_power_db(speech_power[bands].sum(axis=0))
    bed_level = _mean_power_db(bed_power[bands].sum(axis=0))
    return TurnIntelligibility(
        turn_index=index,
        start_s=turn.start_s,
        end_s=turn.end_s,
        speech_db=speech_level,
        bed_db=bed_level,
        speech_over_bed_db=speech_level - bed_level,
        masked_fraction=fraction_all,
        n_frames=int(speech_power.shape[1]),
        bands=band_rows,
        label=turn.label,
    )


def _unmeasured_turn(
    index: int, turn: Segment, bark: BarkMap, bands: list[int],
) -> TurnIntelligibility:
    """The row for a turn too short to transform: present, and honestly NaN."""
    return TurnIntelligibility(
        turn_index=index,
        start_s=turn.start_s,
        end_s=turn.end_s,
        speech_db=math.nan,
        bed_db=math.nan,
        speech_over_bed_db=math.nan,
        masked_fraction=math.nan,
        n_frames=0,
        bands=[
            IntelligibilityBand(
                lo_hz=float(bark.edges_hz[b]),
                hi_hz=float(bark.edges_hz[b + 1]),
                speech_db=math.nan,
                bed_db=math.nan,
                speech_over_bed_db=math.nan,
                masked_fraction=math.nan,
            )
            for b in bands
        ],
        label=turn.label,
    )


def _mean_power_db(power_per_frame: np.ndarray) -> float:
    """Mean linear power over frames, in dB with the analyzer's floor.

    Averaged in the power domain before the log so a turn with a pause in it
    reads as its energy, not as the log of its silences.
    """
    return float(10.0 * np.log10(float(np.mean(power_per_frame)) + _EPS))


__all__ = [
    "BED_SURFACE_ID",
    "SPEECH_BAND_HZ",
    "measure_intelligibility",
    "speech_bark_bands",
    "sum_bed",
]
