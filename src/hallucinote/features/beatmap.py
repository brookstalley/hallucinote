"""Seconds ↔ song beats for one placed sample, through the song's tempo map.

A feature stream is measured in seconds against the file. A generator wants
beats. The bridge is the clip's placement — the song-absolute beat at which
the file's first sample sounds — and the tempo map from there on: beat
``b`` is the placement plus however many beats the tempo map covers in
``seconds`` of wall clock. Because the map is *evaluated* at consumption
rather than baked into the stream, a re-tempo moves every mapped beat
without touching the extraction.

The maths is ``audio/section.py``'s: ``BeatSampleMap`` for seconds → beats
across the file's span (it integrates the same tempo segments the section
lens uses) and ``declared_span_seconds`` for the exact beats → seconds
integral. This module only anchors them to a placement and a sample rate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

from hallucinote.audio.section import BeatSampleMap, TempoSegment, declared_span_seconds

# Bisection tolerance for the inverse integrals, in beats — a thousandth of
# a tick at any tempo, and far under the frame hop of any stream.
_BEAT_TOLERANCE = 1e-9
_MAX_BISECTIONS = 200


@dataclass(frozen=True)
class PlacedBeatMap:
    """The ``BeatMap`` for a file whose first sample sounds at ``start_beat``.

    ``end_beat`` is the song beat at which the file ends; ``duration_s`` is
    the file's length. Build one with :func:`beat_map_for_placement`.
    """

    start_beat: float
    end_beat: float
    duration_s: float
    sample_rate: int
    tempo_segments: tuple[TempoSegment, ...]
    _sample_map: BeatSampleMap = field(repr=False, compare=False)

    def beats_to_seconds(self, beats: float) -> float:
        """Seconds from the file's first sample at which song beat ``beats``
        falls — negative before the placement, past ``duration_s`` after the
        file's end."""
        if beats == self.start_beat:
            return 0.0
        if beats > self.start_beat:
            span = declared_span_seconds(self.start_beat, beats, self.tempo_segments)
        else:
            span = declared_span_seconds(beats, self.start_beat, self.tempo_segments)
            span = None if span is None else -span
        if span is None:
            raise ValueError(
                f"beat {beats} precedes the tempo map's first point; the song's "
                f"tempo map must start at or before every beat it is asked about"
            )
        return float(span)

    def seconds_to_beats(self, seconds: float) -> float:
        """Song beat sounding ``seconds`` into the file.

        Inside the file the sample map answers directly; beyond either end the
        answer is the inverse of :meth:`beats_to_seconds`, so a tail that runs
        past the file still lands on the right beat.
        """
        if 0.0 <= seconds <= self.duration_s:
            return self._sample_map.sample_to_beat(seconds * self.sample_rate)
        if seconds > self.duration_s:
            lo, hi = self.end_beat, self.end_beat + 1.0
            while self.beats_to_seconds(hi) < seconds:
                hi += hi - lo
        else:
            lo, hi = self.start_beat - 1.0, self.start_beat
            while self.beats_to_seconds(lo) > seconds:
                lo -= hi - lo
        return _bisect_beats(self.beats_to_seconds, seconds, lo, hi)


def _bisect_beats(
    seconds_at: Callable[[float], float], target_s: float, lo: float, hi: float
) -> float:
    """Beat at which the monotonic ``seconds_at`` reaches ``target_s``."""
    for _ in range(_MAX_BISECTIONS):
        mid = 0.5 * (lo + hi)
        if hi - lo < _BEAT_TOLERANCE:
            return mid
        if seconds_at(mid) < target_s:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def beat_map_for_placement(
    tempo_segments: Sequence[TempoSegment],
    *,
    start_beat: float,
    n_samples: int,
    sample_rate: int,
) -> PlacedBeatMap:
    """Anchor a file of ``n_samples`` at ``sample_rate`` to song beat ``start_beat``.

    ``tempo_segments`` is the song's tempo map in beats (the same shape the
    section lens takes); it must have a point at or before ``start_beat``,
    which a song's map always does because it starts at beat 0. Bar→beat
    conversion is the caller's, through the meter map.
    """
    if n_samples <= 0:
        raise ValueError(f"n_samples must be > 0; got {n_samples}")
    if sample_rate <= 0:
        raise ValueError(f"sample_rate must be > 0 Hz; got {sample_rate}")
    segments = tuple(s for s in tempo_segments if s.bpm > 0)
    if not segments:
        raise ValueError(
            "tempo_segments must hold at least one TempoSegment with bpm > 0 — "
            "pass the song's tempo map (a single segment at beat 0 for a "
            "constant tempo)"
        )
    first = min(s.start_beat for s in segments)
    if start_beat < first:
        raise ValueError(
            f"start_beat {start_beat} precedes the tempo map's first point at beat "
            f"{first}; a placement needs a tempo in force, so either place the clip "
            f"at or after beat {first} or add a tempo point at or before it"
        )
    duration_s = n_samples / sample_rate

    def seconds_from_start(beat: float) -> float:
        span = declared_span_seconds(start_beat, beat, segments)
        return 0.0 if span is None else span

    fastest = max(s.bpm for s in segments)
    hi = start_beat + duration_s * fastest / 60.0 + 1.0
    end_beat = _bisect_beats(seconds_from_start, duration_s, start_beat, hi)
    sample_map = BeatSampleMap(start_beat, end_beat, n_samples, segments)
    return PlacedBeatMap(
        start_beat=float(start_beat),
        end_beat=float(end_beat),
        duration_s=duration_s,
        sample_rate=int(sample_rate),
        tempo_segments=segments,
        _sample_map=sample_map,
    )


__all__ = ["PlacedBeatMap", "beat_map_for_placement"]
