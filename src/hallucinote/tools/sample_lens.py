#!/usr/bin/env python3
"""Read a sample line against the song's bars before composing to it.

The sample lens is the read-side surface over ``hallucinote.features``: it
loads one source through the sample loader, measures its F0, formants,
energy and segments, optionally runs one named detector with the musical
gates the author chose, maps everything to song beats through the clip's
placement and the tempo map, and prints what a producer wants to know before
writing a note against the line — the pitch centre it implies and how that
sits in the song's key, how long its phrases are in beats at the song's
tempo, how fast it moves, and *where the detector would fire, against bars*.

Neutral by construction: every line is a reading, never a verdict. The lens
does not say the centre is the "right" key, does not choose a register, and
does not tune a gate — those are the author's (R4.6). What it makes possible
is tuning a detector by eye before a hearing, which is the failure mode the
requirements name: musical thresholds set blind.

Two front doors: a song and a source name (placement, tempo and key come from
the song), or a bare ``--file`` with ``--bpm`` (constant tempo, no placement
and no key unless ``--key`` is passed — and the reading says so).

Usage:
    python3 -m hallucinote.tools.sample_lens <slug> <source>
    python3 -m hallucinote.tools.sample_lens <slug> <source> --detector scale_tone \\
        --voiced-only yes --energy-floor -40 --dwell 0.08 --spacing 0.25 --band-cents 30
    python3 -m hallucinote.tools.sample_lens --file line.wav --bpm 92 --key Dm
    python3 -m hallucinote.tools.sample_lens <slug> <source> --json

Exit codes: 0 = reading printed · 2 = the song, its DB, the source or the
file cannot be found · 3 = the ask is incomplete (a detector without all
four gates, a scale detector without a key, ``--file`` without ``--bpm``).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from hallucinote.assets import store
from hallucinote.audio.sample_io import SampleAudio, load_sample
from hallucinote.audio.section import TempoSegment
from hallucinote.db import queries as Q
from hallucinote.db.connection import init_db, resolve_db_path
from hallucinote.features.beatmap import PlacedBeatMap, beat_map_for_placement
from hallucinote.features.energy import energy_envelope
from hallucinote.features.events import (
    VOICED_CONFIDENCE,
    Gates,
    energy_threshold_events,
    events_to_beats,
    grid_delay,
    onset_events,
    scale_tone_crossings,
)
from hallucinote.features.f0 import f0_contour
from hallucinote.features.formants import formant_tracks
from hallucinote.features.segments import (
    onset_segments,
    onset_times,
    phrase_segments,
    syllable_rate,
)
from hallucinote.features.types import FeatureEvent, FeatureStream, Segment
from hallucinote.paths import resolve_audio_path, same_file_path
from hallucinote.sync.geometry import (
    _beats_per_bar_at,
    _beats_to_position_bar,
    _position_bar_to_beats,
    _split_bar,
)
from hallucinote.theory.model import Mode, mode, pc_name, pitch_class
from hallucinote.tools.tuning_caveat import lens_caveat, song_tuning_ref
from hallucinote.workspace import resolve_song_dir

EXIT_OK = 0
EXIT_NOT_FOUND = 2
EXIT_INCOMPLETE = 3

DETECTORS: tuple[str, ...] = ("scale_tone", "energy_threshold", "onset")

# The F0 search range when the caller does not name one. Speech and most
# sung lines sit inside it, and the reading prints the range it used so a
# bass line or a whistle tracked against the wrong range is visible in the
# output rather than silently clipped.
DEFAULT_FMIN_HZ = 60.0
DEFAULT_FMAX_HZ = 800.0

# The grid a fired event is shown landing on. A sixteenth is the finest grid
# a cascade in this repertoire is placed on; the reading names it so a
# coarser one is a one-flag change.
DEFAULT_GRID_BEATS = 0.25

# Bar strip resolution: cells per beat. Four gives one cell per sixteenth,
# which matches the default grid so a fire and its landing cell coincide.
_CELLS_PER_BEAT = 4

# The reading's pitch range is the 5th–95th percentile of voiced frames so a
# single tracker glitch does not become "the line spans two octaves".
_RANGE_PERCENTILES = (5.0, 95.0)

# A frame within a quarter-tone of a scale tone rounds to it; the reading
# reports what fraction of the voiced line does, as a plain proportion.
_SCALE_TONE_HALF_WIDTH_CENTS = 50.0

_A4_HZ = 440.0
_A4_MIDI = 69


# --- key -----------------------------------------------------------------------


@dataclass(frozen=True)
class Key:
    """A tonic and a mode — what ``songs.key`` names, resolved to pitch classes."""

    tonic_pc: int
    mode: Mode

    @property
    def name(self) -> str:
        return f"{pc_name(self.tonic_pc)} {self.mode.name}"

    @property
    def pitch_classes(self) -> frozenset[int]:
        return self.mode.pitch_classes(self.tonic_pc)

    def degree_of(self, pc: int) -> int | None:
        """1-based scale degree of ``pc``, or ``None`` when it is not a scale tone."""
        ordered = sorted(self.pitch_classes, key=lambda p: (p - self.tonic_pc) % 12)
        return ordered.index(pc % 12) + 1 if pc % 12 in self.pitch_classes else None


_KEY_RE = re.compile(r"^\s*(?P<tonic>[A-Ga-g][#b]?)\s*(?P<rest>.*?)\s*$")
_MINOR_WORDS = frozenset({"m", "min", "minor", "-"})
_MAJOR_WORDS = frozenset({"", "maj", "major"})


def parse_key(text: str) -> Key:
    """Read a key string the way a song declares it: ``Dm``, ``C``, ``F# minor``,
    ``E Dorian``. A bare note is major, an ``m`` suffix is minor, anything
    else is looked up as a mode name."""
    m = _KEY_RE.match(text)
    if m is None:
        raise ValueError(
            f"cannot read {text!r} as a key; expected a note name with an optional "
            "quality or mode, e.g. 'Dm', 'C', 'F# minor', 'E Dorian'"
        )
    tonic = pitch_class(m.group("tonic"))
    rest = m.group("rest").strip()
    lowered = rest.lower()
    if lowered in _MAJOR_WORDS:
        return Key(tonic, mode("Major"))
    if lowered in _MINOR_WORDS:
        return Key(tonic, mode("Minor"))
    return Key(tonic, mode(rest))


# --- readings -------------------------------------------------------------------


@dataclass(frozen=True)
class Placement:
    """Where the file sounds in the song, in beats and in bar positions."""

    start_beat: float
    end_beat: float
    start_bar: float
    end_bar: float
    start_label: str
    end_label: str
    source: str
    other_placements: tuple[float, ...] = ()


@dataclass(frozen=True)
class PitchReading:
    """The pitch the voiced part of the line implies, and its relation to the key."""

    voiced_fraction: float
    centre_hz: float | None
    centre_midi: float | None
    centre_note: str | None
    centre_cents: float | None
    low_note: str | None
    high_note: str | None
    range_semitones: float | None
    pitch_class_histogram: dict[str, float]
    key: str | None
    centre_degree: int | None
    nearest_scale_tones: tuple[str, str] | None
    in_scale_fraction: float | None


@dataclass(frozen=True)
class FormantReading:
    name: str
    median_hz: float | None
    measured_fraction: float


@dataclass(frozen=True)
class PhraseReading:
    index: int
    start_s: float
    end_s: float
    start_beat: float
    end_beat: float
    start_bar_beat: str
    length_beats: float
    length_s: float
    onsets: int
    syllables_per_s: float
    syllables_per_beat: float
    centre_note: str | None


@dataclass(frozen=True)
class EventReading:
    time_s: float
    beat: float
    bar_beat: str
    grid_beat: float
    grid_bar_beat: str
    kind: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class DetectorReading:
    name: str
    gates: dict[str, Any]
    params: dict[str, Any]
    grid_beats: float
    events: tuple[EventReading, ...]


@dataclass(frozen=True)
class SampleReading:
    """Everything the lens measured on one line, in seconds and in beats."""

    source: str
    path: str
    duration_s: float
    sample_rate: int
    source_sample_rate: int
    source_channels: int
    tempo: str
    meter: str
    placement: Placement
    f0_range_hz: tuple[float, float]
    pitch: PitchReading
    formants: tuple[FormantReading, ...]
    peak_dbfs: float
    phrases: tuple[PhraseReading, ...]
    onset_count: int
    detector: DetectorReading | None
    bar_strip: tuple[str, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        return _jsonable(out)


def _jsonable(value: Any) -> Any:
    """Plain JSON types only: numpy scalars and non-finite floats do not survive
    ``json.dumps`` unchanged, and the ``--json`` form is read by an agent."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, np.bool_):
        return bool(value)
    return value


# --- pitch helpers --------------------------------------------------------------


def _hz_to_midi(hz: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return _A4_MIDI + 12.0 * np.log2(hz / _A4_HZ)


def _midi_to_hz(midi: float) -> float:
    return _A4_HZ * 2.0 ** ((midi - _A4_MIDI) / 12.0)


def _note_name(midi: float) -> str:
    n = int(round(midi))
    return f"{pc_name(n % 12)}{n // 12 - 1}"


def _voiced_midi(f0: FeatureStream) -> np.ndarray:
    hz = f0.values.astype(np.float64)
    voiced = np.isfinite(hz) & (hz > 0.0)
    if f0.confidence is not None:
        voiced &= f0.confidence >= VOICED_CONFIDENCE
    return _hz_to_midi(hz[voiced])


def read_pitch(f0: FeatureStream, key: Key | None) -> PitchReading:
    """The implied centre (median of the voiced frames, in the log domain), the
    range, the pitch-class weight, and — when a key is known — where the
    centre sits in it. Facts; the key stays whatever the author declared."""
    midi = _voiced_midi(f0)
    n_frames = len(f0)
    voiced_fraction = float(midi.shape[0] / n_frames) if n_frames else 0.0
    if midi.shape[0] == 0:
        return PitchReading(
            voiced_fraction=voiced_fraction, centre_hz=None, centre_midi=None,
            centre_note=None, centre_cents=None, low_note=None, high_note=None,
            range_semitones=None, pitch_class_histogram={},
            key=key.name if key else None, centre_degree=None,
            nearest_scale_tones=None, in_scale_fraction=None,
        )
    centre = float(np.median(midi))
    nearest = int(round(centre))
    lo, hi = np.percentile(midi, _RANGE_PERCENTILES)
    rounded = np.round(midi).astype(int)
    counts = np.bincount(rounded % 12, minlength=12) / rounded.shape[0]
    histogram = {
        pc_name(pc): float(counts[pc])
        for pc in np.argsort(-counts)
        if counts[pc] > 0.0
    }
    degree: int | None = None
    neighbours: tuple[str, str] | None = None
    in_scale: float | None = None
    if key is not None:
        pcs = key.pitch_classes
        degree = key.degree_of(nearest % 12)
        in_scale = float(np.mean([pc in pcs for pc in rounded % 12]))
        if degree is None:
            below = next(nearest - d for d in range(1, 12) if (nearest - d) % 12 in pcs)
            above = next(nearest + d for d in range(1, 12) if (nearest + d) % 12 in pcs)
            neighbours = (_note_name(below), _note_name(above))
    return PitchReading(
        voiced_fraction=voiced_fraction,
        centre_hz=_midi_to_hz(centre),
        centre_midi=centre,
        centre_note=_note_name(centre),
        centre_cents=100.0 * (centre - nearest),
        low_note=_note_name(float(lo)),
        high_note=_note_name(float(hi)),
        range_semitones=float(hi - lo),
        pitch_class_histogram=histogram,
        key=key.name if key else None,
        centre_degree=degree,
        nearest_scale_tones=neighbours,
        in_scale_fraction=in_scale,
    )


def _phrase_centre(f0: FeatureStream, phrase: Segment) -> str | None:
    inside = (f0.times_s >= phrase.start_s) & (f0.times_s < phrase.end_s)
    if not np.any(inside):
        return None
    sub = FeatureStream(
        name=f0.name, times_s=f0.times_s[inside], values=f0.values[inside],
        units=f0.units,
        confidence=None if f0.confidence is None else f0.confidence[inside],
    )
    midi = _voiced_midi(sub)
    return _note_name(float(np.median(midi))) if midi.shape[0] else None


# --- bars ---------------------------------------------------------------------


def constant_meter_rows(numerator: int, denominator: int) -> list[sqlite3.Row]:
    """A one-point meter map in the row shape the geometry helpers read.

    Built through an in-memory connection so the ``--file`` door hands the
    same helpers the same type the song door does, rather than a dict that
    only happens to support the same subscript.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT 1.0 AS start_bar, ? AS numerator, ? AS denominator",
            (int(numerator), int(denominator)),
        ).fetchall()
    finally:
        conn.close()


def bar_beat_label(beats: float, meter_rows: Sequence[sqlite3.Row]) -> str:
    """``bar 3 beat 2.50`` — 1-based bar, 1-based beat within it, the way a
    producer reads a position off Live's ruler."""
    if beats < 0.0:
        return f"{beats:.2f} beats before bar 1"
    pos = _beats_to_position_bar(beats, list(meter_rows))
    bar, within = _split_bar(pos, list(meter_rows))
    return f"bar {bar} beat {1.0 + within:.2f}"


def bar_strip(
    placement: Placement,
    phrases: Sequence[tuple[float, float]],
    event_beats: Sequence[float],
    meter_rows: Sequence[sqlite3.Row],
) -> tuple[str, ...]:
    """One row per bar the file spans: ``=`` where a phrase sounds, ``x`` where
    the detector fires, ``.`` for silence, ``|`` between beats, blank outside
    the file. Sixteenth cells, so a fire sits in the cell it would land in."""
    first_bar = int(_beats_to_position_bar(max(placement.start_beat, 0.0), list(meter_rows)))
    # A file ending exactly on a downbeat has nothing in that bar: the last
    # bar with content is the one before the ceiling of the end position.
    end_pos = _beats_to_position_bar(placement.end_beat, list(meter_rows))
    last_bar = max(int(math.ceil(end_pos - 1e-9)) - 1, first_bar)
    rows: list[str] = []
    for bar in range(first_bar, last_bar + 1):
        bar_start = _position_bar_to_beats(float(bar), list(meter_rows))
        bpb = _beats_per_bar_at(float(bar), list(meter_rows))
        cells: list[str] = []
        n_beats = int(round(bpb))
        for beat_i in range(n_beats):
            if beat_i:
                cells.append("|")
            for k in range(_CELLS_PER_BEAT):
                lo = bar_start + beat_i + k / _CELLS_PER_BEAT
                hi = lo + 1.0 / _CELLS_PER_BEAT
                mid = 0.5 * (lo + hi)
                if mid < placement.start_beat or mid >= placement.end_beat:
                    cells.append(" ")
                elif any(lo <= b < hi for b in event_beats):
                    cells.append("x")
                elif any(a <= mid < b for a, b in phrases):
                    cells.append("=")
                else:
                    cells.append(".")
        rows.append(f"bar {bar:>3}  {''.join(cells)}")
    return tuple(rows)


# --- the detector --------------------------------------------------------------


@dataclass(frozen=True)
class DetectorSpec:
    """One detector and every number it needs, all chosen by the caller."""

    name: str
    gates: Gates
    band_cents: float | None = None
    threshold_db: float | None = None

    def __post_init__(self) -> None:
        if self.name not in DETECTORS:
            raise ValueError(
                f"unknown detector {self.name!r}; one of {', '.join(DETECTORS)}"
            )
        if self.name == "scale_tone" and self.band_cents is None:
            raise ValueError(
                "scale_tone needs --band-cents (the half-width, in cents, of the band "
                "around each scale tone that counts as 'on' it — 30 is a quarter of a "
                "semitone; wider fires sooner on a wobbly line)"
            )
        if self.name == "energy_threshold" and self.threshold_db is None:
            raise ValueError(
                "energy_threshold needs --threshold-db (the dBFS level the envelope "
                "must rise through — read the peak the lens prints and set it below)"
            )

    def params(self) -> dict[str, Any]:
        if self.name == "scale_tone":
            return {"band_cents": self.band_cents}
        if self.name == "energy_threshold":
            return {"threshold_db": self.threshold_db}
        return {}


def run_detector(
    spec: DetectorSpec,
    *,
    f0: FeatureStream,
    energy: FeatureStream,
    onsets: Sequence[Segment],
    key: Key | None,
) -> list[FeatureEvent]:
    if spec.name == "scale_tone":
        if key is None:
            raise ValueError(
                "scale_tone fires on the tones of a scale, and no key is known: pass "
                "--key (e.g. --key Dm) or run against a song whose songs.key is set"
            )
        assert spec.band_cents is not None
        return scale_tone_crossings(
            f0, scale=(key.tonic_pc, key.pitch_classes), band_cents=spec.band_cents,
            gates=spec.gates, energy=energy,
        )
    if spec.name == "energy_threshold":
        assert spec.threshold_db is not None
        return energy_threshold_events(
            energy, threshold_db=spec.threshold_db, gates=spec.gates, f0=f0,
        )
    return onset_events(onsets, gates=spec.gates, energy=energy, f0=f0)


def _event_payload_label(ev: EventReading) -> str:
    p = ev.payload
    if ev.kind == "scale_tone":
        deg = p.get("degree")
        deg_txt = f" · degree {int(deg) + 1}" if deg is not None else ""
        return (
            f"{_note_name(float(p['midi']))}{deg_txt} · {p['cents']:+.0f} cents · "
            f"dwelt {p['dwell_s']:.2f} s"
        )
    if ev.kind == "energy_threshold":
        return (
            f"{p['energy_db']:.1f} dBFS at the edge · peak {p['peak_db']:.1f} · "
            f"held {p['duration_s']:.2f} s"
        )
    parts = [f"{p['duration_s']:.2f} s long"]
    if p.get("energy_db") is not None:
        parts.append(f"{p['energy_db']:.1f} dBFS")
    if p.get("hz") is not None and math.isfinite(float(p["hz"])):
        parts.append(_note_name(float(_hz_to_midi(np.asarray(float(p["hz"]))))))
    return " · ".join(parts)


# --- the reading ---------------------------------------------------------------


def read_sample(
    sample: SampleAudio,
    *,
    source_name: str,
    tempo_segments: Sequence[TempoSegment],
    meter_rows: Sequence[sqlite3.Row],
    start_beat: float,
    key: Key | None,
    detector: DetectorSpec | None,
    fmin: float = DEFAULT_FMIN_HZ,
    fmax: float = DEFAULT_FMAX_HZ,
    grid_beats: float = DEFAULT_GRID_BEATS,
    other_placement_bars: Sequence[float] = (),
    tempo_label: str | None = None,
    notes: Sequence[str] = (),
) -> SampleReading:
    """Measure one loaded line and place every reading on the song's bars.

    Pure over its inputs (no DB, no files): the two front doors resolve the
    song's facts and hand them in, so a test can read a synthesized line with
    a constant tempo and the CLI can read a placed source with the real map.
    """
    if not (grid_beats > 0.0):
        raise ValueError(f"grid_beats must be > 0 (0.25 is a sixteenth); got {grid_beats}")
    audio, sr = sample.audio, sample.sr
    beat_map: PlacedBeatMap = beat_map_for_placement(
        tempo_segments, start_beat=start_beat, n_samples=audio.shape[0], sample_rate=sr,
    )
    f0 = f0_contour(audio, sr, fmin=fmin, fmax=fmax)
    energy = energy_envelope(audio, sr)
    formants = formant_tracks(audio, sr)
    phrases = phrase_segments(audio, sr)
    onset_secs = onset_times(audio, sr)
    onsets = onset_segments(audio, sr)

    placement = Placement(
        start_beat=beat_map.start_beat,
        end_beat=beat_map.end_beat,
        start_bar=_beats_to_position_bar(beat_map.start_beat, list(meter_rows)),
        end_bar=_beats_to_position_bar(beat_map.end_beat, list(meter_rows)),
        start_label=bar_beat_label(beat_map.start_beat, meter_rows),
        end_label=bar_beat_label(beat_map.end_beat, meter_rows),
        source=source_name,
        other_placements=tuple(other_placement_bars),
    )

    phrase_readings: list[PhraseReading] = []
    for i, ph in enumerate(phrases, start=1):
        sb, eb = beat_map.seconds_to_beats(ph.start_s), beat_map.seconds_to_beats(ph.end_s)
        rate = syllable_rate(ph, onset_secs)
        length_beats = eb - sb
        phrase_readings.append(PhraseReading(
            index=i, start_s=ph.start_s, end_s=ph.end_s, start_beat=sb, end_beat=eb,
            start_bar_beat=bar_beat_label(sb, meter_rows),
            length_beats=length_beats, length_s=ph.duration_s,
            onsets=int(np.count_nonzero((onset_secs >= ph.start_s) & (onset_secs < ph.end_s))),
            syllables_per_s=rate,
            syllables_per_beat=(rate * ph.duration_s / length_beats) if length_beats > 0 else float("nan"),
            centre_note=_phrase_centre(f0, ph),
        ))

    formant_readings = tuple(
        FormantReading(
            name=track.name,
            median_hz=float(np.nanmedian(track.values)) if np.any(np.isfinite(track.values)) else None,
            measured_fraction=float(np.mean(np.isfinite(track.values))) if len(track) else 0.0,
        )
        for track in formants
    )

    detector_reading: DetectorReading | None = None
    event_beats: list[float] = []
    if detector is not None:
        events = events_to_beats(
            run_detector(detector, f0=f0, energy=energy, onsets=onsets, key=key), beat_map,
        )
        readings: list[EventReading] = []
        for ev in events:
            assert ev.beat is not None
            landed = grid_delay(ev.beat, grid_beats)
            readings.append(EventReading(
                time_s=ev.time_s, beat=ev.beat, bar_beat=bar_beat_label(ev.beat, meter_rows),
                grid_beat=landed, grid_bar_beat=bar_beat_label(landed, meter_rows),
                kind=ev.kind, payload=dict(ev.payload),
            ))
            event_beats.append(ev.beat)
        detector_reading = DetectorReading(
            name=detector.name,
            gates={
                "voiced_only": detector.gates.voiced_only,
                "energy_floor_db": detector.gates.energy_floor_db,
                "dwell_s": detector.gates.dwell_s,
                "min_spacing_s": detector.gates.min_spacing_s,
            },
            params=detector.params(),
            grid_beats=grid_beats,
            events=tuple(readings),
        )

    if tempo_label is None:
        tempo_label = _tempo_label(tempo_segments)
    return SampleReading(
        source=source_name,
        path=str(sample.path),
        duration_s=sample.duration_s,
        sample_rate=sr,
        source_sample_rate=sample.source_sr,
        source_channels=sample.source_channels,
        tempo=tempo_label,
        meter=_meter_label(meter_rows),
        placement=placement,
        f0_range_hz=(fmin, fmax),
        pitch=read_pitch(f0, key),
        formants=formant_readings,
        peak_dbfs=float(np.max(energy.values)) if len(energy) else float("-inf"),
        phrases=tuple(phrase_readings),
        onset_count=int(onset_secs.shape[0]),
        detector=detector_reading,
        bar_strip=bar_strip(
            placement, [(p.start_beat, p.end_beat) for p in phrase_readings],
            event_beats, meter_rows,
        ),
        notes=tuple(notes),
    )


def _tempo_label(segments: Sequence[TempoSegment]) -> str:
    if len(segments) == 1:
        return f"{segments[0].bpm:g} bpm"
    return ", ".join(f"{s.bpm:g} bpm from beat {s.start_beat:g}" for s in segments)


def _meter_label(meter_rows: Sequence[sqlite3.Row]) -> str:
    if not meter_rows:
        return "4/4 (assumed — the song has no meter map)"
    return ", ".join(
        f"{r['numerator']}/{r['denominator']}"
        + (f" from bar {float(r['start_bar']):g}" if len(meter_rows) > 1 else "")
        for r in meter_rows
    )


# --- rendering -------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "—" if value is None or not math.isfinite(value) else f"{value:.0%}"


def render(reading: SampleReading) -> str:
    """The reading a producer composes against, as prose and one bar strip.

    Every line states a measurement; none of them grades it. Where a number
    invites a decision (the centre against the key, a gate that fires too
    often), the line names the decision as the author's rather than making it.
    """
    r = reading
    p = r.placement
    lines: list[str] = []
    lines.append(
        f"sample lens — {r.source}: {r.duration_s:.2f} s · {r.tempo} · {r.meter} · "
        f"{len(r.phrases)} phrase(s) · {r.onset_count} onset(s)"
    )
    lines.append(
        "  (readings, NOT a verdict — the key, the register and whether the line "
        "or the music leads stay the author's; the lens only says what the line does)"
    )
    for note in r.notes:
        lines.append(f"  note: {note}")

    lines.append("")
    lines.append(
        f"placement: {p.start_label} → {p.end_label} "
        f"(beats {p.start_beat:.2f}–{p.end_beat:.2f}, {p.end_beat - p.start_beat:.2f} beats long)"
    )
    if p.other_placements:
        others = ", ".join(f"bar {b:g}" for b in p.other_placements)
        lines.append(f"  also placed at {others} — read against the first; the others follow the same seconds")
    lines.append(
        f"file: {r.path} · {r.sample_rate} Hz analysed "
        f"(source {r.source_sample_rate} Hz, {r.source_channels} ch) · peak {r.peak_dbfs:.1f} dBFS"
    )

    lines.append("")
    pr = r.pitch
    lines.append(f"pitch (F0 tracked {r.f0_range_hz[0]:g}–{r.f0_range_hz[1]:g} Hz; voiced {_pct(pr.voiced_fraction)} of frames):")
    if pr.centre_note is None:
        lines.append("  no voiced frames — nothing pitched to read (widen --fmin/--fmax if the line is pitched)")
    else:
        assert pr.centre_hz is not None and pr.centre_cents is not None
        lines.append(
            f"  implied centre {pr.centre_note} ({pr.centre_hz:.1f} Hz, {pr.centre_cents:+.0f} cents) · "
            f"range {pr.low_note}–{pr.high_note} ({pr.range_semitones:.1f} semitones, 5th–95th pct)"
        )
        top = list(pr.pitch_class_histogram.items())[:4]
        lines.append("  pitch classes: " + " · ".join(f"{n} {_pct(w)}" for n, w in top))
        if pr.key is None:
            lines.append("  key: none declared — pass --key to read the centre against a scale")
        elif pr.centre_degree is not None:
            lines.append(
                f"  against {pr.key}: the centre {pr.centre_note} is degree {pr.centre_degree}; "
                f"{_pct(pr.in_scale_fraction)} of voiced frames round to a scale tone"
            )
        else:
            assert pr.nearest_scale_tones is not None
            lo, hi = pr.nearest_scale_tones
            lines.append(
                f"  against {pr.key}: the centre {pr.centre_note} is not a scale tone "
                f"(nearest {lo} below, {hi} above); {_pct(pr.in_scale_fraction)} of voiced frames round to one"
            )

    measured = [f for f in r.formants if f.median_hz is not None]
    if measured:
        lines.append(
            "formants (median where measured): "
            + " · ".join(f"{f.name} ≈ {f.median_hz:.0f} Hz ({_pct(f.measured_fraction)} of frames)" for f in measured)
        )
    else:
        lines.append("formants: none measured (no sharp resonances — a pure tone or an unvoiced line reads this way)")

    lines.append("")
    if not r.phrases:
        lines.append("phrases: none — the envelope never cleared the phrase threshold")
    else:
        lens = [ph.length_beats for ph in r.phrases]
        rates = [ph.syllables_per_beat for ph in r.phrases if math.isfinite(ph.syllables_per_beat)]
        rate_txt = (
            f"{min(rates):.1f}–{max(rates):.1f} onsets/beat" if rates else "no onsets inside"
        )
        lines.append(
            f"phrases: {len(r.phrases)} · {min(lens):.2f}–{max(lens):.2f} beats long · "
            f"syllable rate {rate_txt}"
        )
        for ph in r.phrases:
            centre = f" · centre {ph.centre_note}" if ph.centre_note else ""
            lines.append(
                f"  {ph.index}. {ph.start_bar_beat} · {ph.length_beats:.2f} beats ({ph.length_s:.2f} s) · "
                f"{ph.onsets} onset(s), {ph.syllables_per_s:.1f}/s{centre}"
            )

    lines.append("")
    d = r.detector
    if d is None:
        lines.append(
            "detector: none named — pass --detector scale_tone|energy_threshold|onset with all "
            "four gates to see where it would fire"
        )
    else:
        g = d.gates
        floor = "off" if g["energy_floor_db"] == -math.inf else f"{g['energy_floor_db']:g} dBFS"
        params = ", ".join(f"{k} {v:g}" for k, v in d.params.items())
        lines.append(
            f"detector {d.name} ({params + ' · ' if params else ''}voiced-only {'yes' if g['voiced_only'] else 'no'} · "
            f"energy floor {floor} · dwell {g['dwell_s']:g} s · spacing {g['min_spacing_s']:g} s): "
            f"{len(d.events)} fire(s)"
        )
        if d.events:
            span = p.end_beat - p.start_beat
            lines.append(f"  {len(d.events) / span:.2f} fires per beat over the file · landing on a {d.grid_beats:g}-beat grid")
        for ev in d.events:
            lines.append(
                f"  {ev.bar_beat} (t={ev.time_s:.2f} s) → lands {ev.grid_bar_beat} · {_event_payload_label(ev)}"
            )

    lines.append("")
    lines.append("against bars (= phrase · x fire · . silence · | beat):")
    lines.extend(f"  {row}" for row in r.bar_strip)
    return "\n".join(lines)


# --- the two front doors --------------------------------------------------------


@dataclass(frozen=True)
class SongContext:
    song_dir: Path
    source_path: Path
    tempo_segments: tuple[TempoSegment, ...]
    meter_rows: tuple[sqlite3.Row, ...]
    key: Key | None
    key_text: str | None
    placements_bars: tuple[float, ...]


def _open_song_db(slug: str) -> sqlite3.Connection:
    db_path = resolve_db_path(slug)
    if not db_path.exists():
        legacy = resolve_song_dir(slug) / f"{slug}.db"
        if not legacy.exists():
            raise FileNotFoundError(
                f"no DB for {slug!r} at {db_path} (or {legacy}); run the song's "
                "build.py first — the lens reads tempo, meter, key and placement from it"
            )
        db_path = legacy
    return init_db(db_path)


def song_context(slug: str, source_name: str) -> SongContext:
    """Tempo map, meter map, key and every placement of ``source_name`` for the song."""
    song_dir = resolve_song_dir(slug)
    if not song_dir.is_dir():
        raise FileNotFoundError(
            f"no such song {slug!r} (expected its directory at {song_dir})"
        )
    src = store.source(song_dir, source_name)
    conn = _open_song_db(slug)
    try:
        song = Q.get_song_by_name(conn, slug)
        if song is None:
            raise FileNotFoundError(
                f"the DB for {slug!r} holds no song row named {slug!r}; the slug is the "
                "song name by convention — check build.py's create_song(name=...)"
            )
        song_id = song["id"]
        meter_rows = tuple(Q.get_time_signature_map(conn, song_id))
        tempo_rows = Q.get_tempo_map(conn, song_id)
        tempo_segments = tuple(
            TempoSegment(
                start_beat=_position_bar_to_beats(float(row["start_bar"]), list(meter_rows)),
                bpm=float(row["tempo_bpm"]),
                ramp=row["ramp"],
            )
            for row in tempo_rows
        )
        placements: list[float] = []
        for clip in Q.get_clips_for_song(conn, song_id):
            if clip["kind"] != "audio" or not clip["audio_file"]:
                continue
            if not same_file_path(resolve_audio_path(song_dir, clip["audio_file"]), src.path):
                continue
            placements.extend(
                float(a["start_bar"]) for a in Q.get_arrangement_for_clip(conn, clip["id"])
            )
        key_text = song["key"]
    finally:
        conn.close()
    key = parse_key(key_text) if key_text else None
    return SongContext(
        song_dir=song_dir,
        source_path=src.path,
        tempo_segments=tempo_segments,
        meter_rows=meter_rows,
        key=key,
        key_text=key_text,
        placements_bars=tuple(sorted(placements)),
    )


# --- CLI -----------------------------------------------------------------------


def _parse_yes_no(text: str) -> bool:
    lowered = text.strip().lower()
    if lowered in {"yes", "y", "true", "1", "on"}:
        return True
    if lowered in {"no", "n", "false", "0", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected yes or no; got {text!r}")


def _parse_floor(text: str) -> float:
    if text.strip().lower() == "off":
        return -math.inf
    try:
        return float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a dBFS level or 'off'; got {text!r}"
        ) from None


def _parse_meter(text: str) -> tuple[int, int]:
    m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*$", text)
    if m is None:
        raise argparse.ArgumentTypeError(f"expected N/D such as 4/4 or 6/8; got {text!r}")
    return int(m.group(1)), int(m.group(2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sample_lens",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("slug", nargs="?", help="song slug (omit with --file)")
    parser.add_argument("source", nargs="?", help="source name in the song's assets/manifest.json")
    parser.add_argument("--file", type=Path, help="read a bare audio file instead of a song's source")
    parser.add_argument("--bpm", type=float, help="constant tempo for --file (required with it)")
    parser.add_argument("--meter", type=_parse_meter, default=(4, 4),
                        help="meter for --file, N/D (default 4/4)")
    parser.add_argument("--key", help="key to read against (e.g. Dm, 'E Dorian'); overrides the song's")
    parser.add_argument("--start-bar", type=float,
                        help="place the file at this 1-based bar (default: the clip's placement, else bar 1)")
    parser.add_argument("--fmin", type=float, default=DEFAULT_FMIN_HZ, help="F0 search floor in Hz")
    parser.add_argument("--fmax", type=float, default=DEFAULT_FMAX_HZ, help="F0 search ceiling in Hz")
    parser.add_argument("--grid", type=float, default=DEFAULT_GRID_BEATS,
                        help="grid a fire lands on, in beats (default 0.25, a sixteenth)")
    det = parser.add_argument_group("detector — every gate is explicit; none defaults")
    det.add_argument("--detector", choices=DETECTORS, help="which detector to read")
    det.add_argument("--voiced-only", type=_parse_yes_no, metavar="yes|no",
                     help="fire only on frames the F0 tracker heard as pitched")
    det.add_argument("--energy-floor", type=_parse_floor, metavar="dBFS|off",
                     help="drop frames quieter than this (dBFS), or 'off'")
    det.add_argument("--dwell", type=float, metavar="S", help="seconds the condition must hold before a fire")
    det.add_argument("--spacing", type=float, metavar="S", help="seconds after a fire during which nothing fires")
    det.add_argument("--band-cents", type=float, help="scale_tone: half-width of each tone's band, cents")
    det.add_argument("--threshold-db", type=float, help="energy_threshold: level to rise through, dBFS")
    parser.add_argument("--json", action="store_true", help="emit the reading as JSON for an agent")
    return parser


_GATE_FLAGS = (("voiced_only", "--voiced-only"), ("energy_floor", "--energy-floor"),
               ("dwell", "--dwell"), ("spacing", "--spacing"))


def detector_spec_from_args(args: argparse.Namespace) -> DetectorSpec | None:
    """The detector the caller asked for, refusing when a gate was left to default.

    A gate the lens filled in would be the number the author never tuned —
    and then the first real line would fire on that number.
    """
    if args.detector is None:
        return None
    missing = [flag for attr, flag in _GATE_FLAGS if getattr(args, attr) is None]
    if missing:
        raise ValueError(
            f"--detector {args.detector} needs every gate stated: missing "
            f"{', '.join(missing)}. Gates are musical thresholds and none defaults — "
            "e.g. --voiced-only yes --energy-floor -40 --dwell 0.08 --spacing 0.25 "
            "(or --energy-floor off to switch the floor off on purpose)"
        )
    gates = Gates(
        voiced_only=args.voiced_only, energy_floor_db=args.energy_floor,
        dwell_s=args.dwell, min_spacing_s=args.spacing,
    )
    return DetectorSpec(
        name=args.detector, gates=gates,
        band_cents=args.band_cents, threshold_db=args.threshold_db,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    def refuse(code: int, message: str) -> int:
        print(f"sample-lens: {message}", file=sys.stderr)
        return code

    if args.file is None and (args.slug is None or args.source is None):
        return refuse(EXIT_INCOMPLETE,
                      "name a song and a source (`<slug> <source>`), or read a bare file with "
                      "`--file <wav> --bpm <tempo>`")
    if args.file is not None and args.bpm is None:
        return refuse(EXIT_INCOMPLETE,
                      "--file needs --bpm: a bare file carries no tempo, and every reading here "
                      "is in beats")
    if args.file is not None and args.bpm is not None and args.bpm <= 0:
        return refuse(EXIT_INCOMPLETE, f"--bpm must be > 0; got {args.bpm:g}")

    try:
        detector = detector_spec_from_args(args)
        key_override = parse_key(args.key) if args.key else None
    except ValueError as exc:
        return refuse(EXIT_INCOMPLETE, str(exc))

    notes: list[str] = []
    caveat: str | None = None
    other_bars: Sequence[float] = ()
    try:
        if args.file is not None:
            sample = load_sample(args.file)
            source_name = args.file.name
            tempo_segments: Sequence[TempoSegment] = (TempoSegment(0.0, float(args.bpm)),)
            meter_rows: Sequence[sqlite3.Row] = constant_meter_rows(*args.meter)
            key = key_override
            start_bar = args.start_bar if args.start_bar is not None else 1.0
            notes.append(f"bare file: constant {args.bpm:g} bpm and {args.meter[0]}/{args.meter[1]} "
                         "assumed; no song placement")
            if key is None:
                notes.append("no key: the centre is read on its own (pass --key to relate it to a scale)")
        else:
            ctx = song_context(args.slug, args.source)
            sample = load_sample(ctx.source_path)
            source_name = args.source
            if not ctx.tempo_segments:
                return refuse(EXIT_INCOMPLETE,
                              f"{args.slug!r} has no tempo map; add a tempo point in build.py "
                              "(M.add_tempo_point) so the line can be read in beats")
            tempo_segments = ctx.tempo_segments
            meter_rows = ctx.meter_rows
            key = key_override if key_override is not None else ctx.key
            if key_override is not None and ctx.key_text:
                notes.append(f"reading against --key {key.name if key else ''} rather than the song's "
                             f"declared {ctx.key_text!r}")
            elif key is None:
                notes.append("the song declares no key; pass --key to relate the centre to a scale")
            if args.start_bar is not None:
                start_bar = args.start_bar
                notes.append(f"placed at --start-bar {start_bar:g} for this reading")
            elif ctx.placements_bars:
                start_bar = ctx.placements_bars[0]
                other_bars = ctx.placements_bars[1:]
            else:
                start_bar = 1.0
                notes.append(f"{args.source!r} is not placed on any arrangement clip yet — read as if "
                             "at bar 1; pass --start-bar to try a placement")
            caveat = lens_caveat(song_tuning_ref(args.slug))
        start_beat = _position_bar_to_beats(float(start_bar), list(meter_rows))
        reading = read_sample(
            sample,
            source_name=source_name,
            tempo_segments=tempo_segments,
            meter_rows=meter_rows,
            start_beat=start_beat,
            key=key,
            detector=detector,
            fmin=args.fmin,
            fmax=args.fmax,
            grid_beats=args.grid,
            other_placement_bars=other_bars,
            notes=notes,
        )
    except (FileNotFoundError, KeyError) as exc:
        message = exc.args[0] if exc.args else str(exc)
        return refuse(EXIT_NOT_FOUND, str(message))
    except ValueError as exc:
        return refuse(EXIT_INCOMPLETE, str(exc))

    if args.json:
        out = reading.to_dict()
        if caveat is not None:
            out["tuning_caveat"] = caveat
        print(json.dumps(out, indent=2))
    else:
        if caveat is not None:
            print(caveat)
        print(render(reading))
    return EXIT_OK


__all__ = [
    "DETECTORS",
    "DetectorSpec",
    "Key",
    "SampleReading",
    "bar_beat_label",
    "bar_strip",
    "constant_meter_rows",
    "main",
    "parse_key",
    "read_pitch",
    "read_sample",
    "render",
    "song_context",
]


if __name__ == "__main__":
    sys.exit(main())
