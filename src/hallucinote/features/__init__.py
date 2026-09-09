"""Feature streams — what can be known about a sample, as generator input.

A feature stream is a time series measured off an audio file in seconds and
mapped to beats at consumption, through the clip's placement and the song's
tempo map, so a generator sees musical time and a re-tempo does not invalidate
the extraction. The streams themselves (F0, formants, energy, segments) and the
detectors that turn them into events are built in the sibling modules; the
shapes they all share are in ``types.py``.

This package imports nothing from ``hallucinote.db``, ``hallucinote.sync`` or
``hallucinote_mcp`` — a generator consumes its output, and generators are pure.
"""
from __future__ import annotations

from .beatmap import PlacedBeatMap, beat_map_for_placement
from .energy import (
    SpectralDescriptors,
    bark_band_energies,
    energy_envelope,
    spectral_centroid,
    spectral_descriptors,
    spectral_flatness,
    spectral_rolloff,
)
from .events import (
    Gates,
    energy_threshold_events,
    events_to_beats,
    grid_delay,
    onset_events,
    scale_tone_crossings,
)
from .f0 import f0_contour
from .formants import formant_tracks
from .segments import onset_segments, onset_times, phrase_segments, syllable_rate
from .types import BeatMap, BeatStream, FeatureEvent, FeatureStream, Segment

__all__ = [
    "BeatMap", "BeatStream", "FeatureEvent", "FeatureStream", "Segment",
    "PlacedBeatMap", "beat_map_for_placement",
    "SpectralDescriptors", "bark_band_energies", "energy_envelope",
    "spectral_centroid", "spectral_descriptors", "spectral_flatness", "spectral_rolloff",
    "Gates", "energy_threshold_events", "events_to_beats", "grid_delay",
    "onset_events", "scale_tone_crossings",
    "f0_contour", "formant_tracks",
    "onset_segments", "onset_times", "phrase_segments", "syllable_rate",
]
