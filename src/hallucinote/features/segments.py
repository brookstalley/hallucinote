"""Segments of a sample: onset-bounded chunks and silence-bounded phrases.

Two readings of where a sample divides. Onsets come from the rhythm
analyzers' own front end (``audio/onsets.py``), so a chop-at-onsets recipe
and a timing measurement agree on where a hit begins. Phrases come from the
energy envelope with a hysteresis floor — a phrase opens when the level
clears a threshold and closes only after it has stayed below a lower one
for a whole gap — so a breath inside a sentence does not split it and a
plosive at a sentence's edge does not open a phrase of its own.

The syllable-rate reading is onsets per second inside a phrase: for spoken
material, onsets are syllable starts, and the rate is the pacing a
generator can echo.
"""
from __future__ import annotations

import numpy as np

from hallucinote.audio.onsets import DEFAULT_HOP, dedup_onsets, detect_onsets_with_strength
from hallucinote.audio.sample_io import as_mono
from hallucinote.features.energy import DEFAULT_HOP_S, SILENCE_FLOOR_DBFS, energy_envelope
from hallucinote.features.types import Segment

ONSET_KIND = "onset"
PHRASE_KIND = "phrase"

# Onsets closer than this are one event — a flam, a plosive's double burst.
# 30 ms is under the fastest syllable rate anyone speaks and over any
# double-trigger the detector produces on a single transient.
MIN_ONSET_SEPARATION_S = 0.030
# Phrase gating. The open threshold defaults to 30 dB under the loudest
# frame, which sits above room tone and score bleed on a dialogue rip; the
# close threshold is `hysteresis_db` below it; a phrase ends only after the
# level has stayed below the close threshold for `min_gap_s` (a breath is
# shorter), and a phrase shorter than `min_phrase_s` is a click, not speech.
# The envelope's RMS frame (~43 ms) smears every event by about its own
# length, so the phrase minimum sits above the frame plus the shortest
# syllable; a 20 ms click reads as ~60 ms on the envelope and is still dropped.
DEFAULT_THRESHOLD_BELOW_PEAK_DB = 30.0
DEFAULT_HYSTERESIS_DB = 6.0
DEFAULT_MIN_GAP_S = 0.150
DEFAULT_MIN_PHRASE_S = 0.100


def onset_times(
    audio: np.ndarray,
    sr: int,
    *,
    hop_length: int = DEFAULT_HOP,
    min_separation_s: float = MIN_ONSET_SEPARATION_S,
) -> np.ndarray:
    """Onset times in seconds, ascending, near-duplicates merged.

    The detector cannot see an onset at the very first sample (spectral flux
    needs preceding frames), so material that starts on sample 0 has no
    onset there — its head is not a segment.
    """
    if sr <= 0:
        raise ValueError(f"sr must be > 0 Hz; got {sr}")
    mono = as_mono(audio)
    samples, _strengths = detect_onsets_with_strength(mono, sr, hop_length=hop_length)
    seconds = np.asarray(samples, dtype=np.float64) / sr
    return dedup_onsets(seconds, min_separation_s)


def onset_segments(
    audio: np.ndarray,
    sr: int,
    *,
    hop_length: int = DEFAULT_HOP,
    min_separation_s: float = MIN_ONSET_SEPARATION_S,
) -> list[Segment]:
    """One ``onset`` segment per detected onset, running to the next onset
    or to the end of the file."""
    mono = as_mono(audio)
    times = onset_times(mono, sr, hop_length=hop_length, min_separation_s=min_separation_s)
    end = mono.shape[0] / sr
    bounds = [*times.tolist(), end]
    return [
        Segment(start_s=float(a), end_s=float(b), kind=ONSET_KIND)
        for a, b in zip(bounds[:-1], bounds[1:])
        if b > a
    ]


def phrase_segments(
    audio: np.ndarray,
    sr: int,
    *,
    hop_s: float = DEFAULT_HOP_S,
    threshold_dbfs: float | None = None,
    hysteresis_db: float = DEFAULT_HYSTERESIS_DB,
    min_gap_s: float = DEFAULT_MIN_GAP_S,
    min_phrase_s: float = DEFAULT_MIN_PHRASE_S,
) -> list[Segment]:
    """Silence-bounded ``phrase`` segments from the energy envelope.

    ``threshold_dbfs`` is the level a phrase must clear to open; ``None``
    places it ``DEFAULT_THRESHOLD_BELOW_PEAK_DB`` under the file's loudest
    frame. A phrase closes when the level has stayed under
    ``threshold_dbfs - hysteresis_db`` for ``min_gap_s``; the segment ends
    where the level first dropped, not where the gap was confirmed.
    """
    if hysteresis_db < 0:
        raise ValueError(f"hysteresis_db must be >= 0; got {hysteresis_db}")
    if min_gap_s < 0 or min_phrase_s < 0:
        raise ValueError(
            f"min_gap_s ({min_gap_s}) and min_phrase_s ({min_phrase_s}) must be >= 0"
        )
    envelope = energy_envelope(audio, sr, hop_s)
    level = envelope.values
    times = envelope.times_s
    if level.size == 0:
        return []
    peak = float(level.max())
    if peak <= SILENCE_FLOOR_DBFS:
        # Digital silence throughout: a peak-relative threshold would open one
        # phrase over the whole file, and there is nothing in it to phrase.
        return []
    open_db = peak - DEFAULT_THRESHOLD_BELOW_PEAK_DB if threshold_dbfs is None else threshold_dbfs
    close_db = open_db - hysteresis_db
    hop = float(times[1] - times[0]) if times.size > 1 else hop_s
    gap_frames = int(np.ceil(min_gap_s / hop)) if hop > 0 else 0

    phrases: list[Segment] = []
    in_phrase = False
    start = 0.0
    below_since: int | None = None
    for i, db in enumerate(level):
        if not in_phrase:
            if db >= open_db:
                in_phrase = True
                start = float(times[i])
                below_since = None
            continue
        if db < close_db:
            if below_since is None:
                below_since = i
            if i - below_since + 1 >= gap_frames:
                _append_phrase(phrases, start, float(times[below_since]), min_phrase_s)
                in_phrase = False
                below_since = None
        else:
            below_since = None
    if in_phrase:
        end_idx = below_since if below_since is not None else level.size - 1
        _append_phrase(phrases, start, float(times[end_idx]), min_phrase_s)
    return phrases


def _append_phrase(phrases: list[Segment], start: float, end: float, min_phrase_s: float) -> None:
    if end - start >= min_phrase_s and end > start:
        phrases.append(Segment(start_s=start, end_s=end, kind=PHRASE_KIND))


def syllable_rate(phrase: Segment, onset_times_s: np.ndarray) -> float:
    """Onsets per second inside ``phrase`` (half-open ``[start, end)``);
    ``nan`` for a zero-length phrase, which has no rate."""
    if phrase.duration_s <= 0:
        return float("nan")
    t = np.asarray(onset_times_s, dtype=np.float64)
    inside = np.count_nonzero((t >= phrase.start_s) & (t < phrase.end_s))
    return float(inside) / phrase.duration_s


__all__ = [
    "DEFAULT_HYSTERESIS_DB",
    "DEFAULT_MIN_GAP_S",
    "DEFAULT_MIN_PHRASE_S",
    "DEFAULT_THRESHOLD_BELOW_PEAK_DB",
    "MIN_ONSET_SEPARATION_S",
    "ONSET_KIND",
    "PHRASE_KIND",
    "onset_segments",
    "onset_times",
    "phrase_segments",
    "syllable_rate",
]
