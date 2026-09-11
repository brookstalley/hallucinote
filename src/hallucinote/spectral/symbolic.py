"""The symbolic spectral field — the score's sounding pitches as a magnitude surface.

The DB knows which pitches sound when; no plugin does. Read the notes the
schedule's nodes play over each span, expand every pitch to its first
``harmonic_depth`` partials, and place unit magnitude at each partial for as
long as the note sounds. The field is exact in pitch, costs nothing and is
available before anything has been rendered — and it is blind to timbre,
to velocity, to device colour and to every audio clip on a track, which its
``origin`` says. The measured field (``measured.py``) is the full truth at
the cost of a render; both feed the same operations.

Discipline: this is one of the two modules under ``spectral/`` that read
the DB (``tests/unit/test_sample_packages_isolation.py`` names it). It only
reads, through ``hallucinote.db.queries``; nothing here writes.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Protocol, Callable

import numpy as np

from hallucinote.db import queries as Q
from hallucinote.features.types import BeatMap
from hallucinote.spectral.schedule import schedule_digest
from hallucinote.spectral.types import (
    NodeRef,
    ReferenceSchedule,
    ResolutionReport,
    SpectralField,
)
from hallucinote.sync.geometry import _position_bar_to_beats
from hallucinote.sync.push_notes import clip_fingerprint


class TuningLike(Protocol):
    """What this module needs from an alternate tuning — structurally.

    The core path never imports ``hallucinote.tuning`` (the isolation the
    bolt-on is built on, grep-asserted in ``tests/unit/tuning``), so a tuned
    song hands its ``TuningData`` in explicitly and this module reads only the
    interval structure it needs. Nothing here deserializes a tuning.
    """

    step_count: int
    period_cents: float
    reference_note: int
    step_cents: tuple[float, ...]

    def to_blob(self) -> str: ...

# Concert pitch: MIDI 69 sounds at 440 Hz in 12-TET, and an alternate tuning's
# reference note is anchored to its own 12-TET frequency because the persisted
# tuning carries interval structure only (``tuning/model.py`` says why).
_A4_MIDI = 69
_A4_HZ = 440.0


@dataclass(frozen=True)
class SoundingNote:
    """One note as it sounds in the arrangement, in song-absolute beats."""

    track_id: str
    clip_id: str
    pitch: int
    start_beat: float
    end_beat: float
    velocity: int


def pitch_hz(pitch: int, tuning: TuningLike | None = None) -> float:
    """The frequency a MIDI note sounds at, in 12-TET or the song's tuning.

    Under a tuning Live makes consecutive MIDI numbers consecutive scale
    degrees from ``reference_note`` — the relation ``tuning/mapper.py``'s
    ``degree_to_midi`` encodes — so the note's offset from the reference
    splits into whole periods and a degree, and its cents follow from the
    step table. The mapper has no inverse of its own; this is it.
    """
    if tuning is None:
        return _A4_HZ * 2.0 ** ((pitch - _A4_MIDI) / 12.0)
    reference_hz = _A4_HZ * 2.0 ** ((tuning.reference_note - _A4_MIDI) / 12.0)
    period, degree = divmod(pitch - tuning.reference_note, tuning.step_count)
    degree_cents = 0.0 if degree == 0 else tuning.step_cents[degree - 1]
    return reference_hz * 2.0 ** ((period * tuning.period_cents + degree_cents) / 1200.0)


def symbolic_axes(
    resolution: ResolutionReport, *, duration_s: float
) -> tuple[np.ndarray, np.ndarray]:
    """The (frequency, time) grid an STFT at ``resolution`` would produce.

    Handing the symbolic field the same grid a measured field lands on is
    what lets an author iterate symbolic and commit measured on one
    operation without a resampling step between the two.
    """
    if duration_s <= 0:
        raise ValueError(f"duration_s must be > 0; got {duration_s}")
    freqs = np.fft.rfftfreq(resolution.n_fft, 1.0 / resolution.sample_rate)
    n_frames = int(np.ceil(duration_s * resolution.sample_rate / resolution.hop)) + 1
    times = np.arange(n_frames, dtype=np.float64) * resolution.hop / resolution.sample_rate
    return freqs.astype(np.float64), times


def bar_to_beat_for_song(conn: sqlite3.Connection, song_id: str) -> Callable[[float], float]:
    """The song's bar→beat ruler — the meter walk push uses, so a schedule
    authored in bars lands where the arrangement does."""
    ts_points = Q.get_time_signature_map(conn, song_id)
    return lambda bar: _position_bar_to_beats(float(bar), ts_points)


def sounding_notes(
    conn: sqlite3.Connection,
    node: NodeRef,
    *,
    song_id: str,
    start_beat: float,
    end_beat: float,
) -> list[SoundingNote]:
    """Every note a node sounds in ``[start_beat, end_beat)``, from the arrangement.

    A track sounds the notes of its placed clips; a return sounds the tracks
    that send to it; the master sounds every track; ``minus`` every track
    but one. Audio clips carry no notes and are silent here by construction
    — the measured field is the route for them.
    """
    tracks = _tracks_for_node(conn, node, song_id=song_id)
    ts_points = Q.get_time_signature_map(conn, song_id)
    out: list[SoundingNote] = []
    for track_id in tracks:
        for note in _track_notes(conn, track_id, ts_points):
            if note.start_beat < end_beat and note.end_beat > start_beat:
                out.append(note)
    return out


def symbolic_field(
    conn: sqlite3.Connection,
    schedule: ReferenceSchedule,
    beat_map: BeatMap,
    *,
    freqs_hz: np.ndarray,
    times_s: np.ndarray,
    harmonic_depth: int,
    resolution: ResolutionReport,
    tuning: TuningLike | None = None,
    song_id: str | None = None,
) -> SpectralField:
    """Rasterize the schedule's sounding partials onto ``(freqs_hz, times_s)``.

    ``beat_map`` says which song beat each output time is — anchor it to the
    target clip's placement and the field lands on the target's own clock.
    ``resolution`` names the grid the field was placed on, so a consumer can
    ask what one bin is worth at a pitch; the symbolic field's own precision
    is exact, and this report is the honest limit of the raster. ``tuning``
    is the song's ``TuningData`` when the song carries one — passed in by the
    caller, because this module never imports the tuning bolt-on — and a
    tuned song read without it refuses rather than sounding in 12-TET.
    ``song_id`` is inferred when the DB holds one song.
    """
    depth = int(harmonic_depth)
    if depth < 1:
        raise ValueError("harmonic_depth must be >= 1 (the fundamental alone)")
    freqs = np.asarray(freqs_hz, dtype=np.float64)
    times = np.asarray(times_s, dtype=np.float64)
    if freqs.ndim != 1 or freqs.size == 0 or (freqs.size > 1 and np.any(np.diff(freqs) <= 0)):
        raise ValueError("freqs_hz must be a non-empty, strictly increasing 1-D array")
    if times.ndim != 1 or times.size == 0:
        raise ValueError("times_s must be a non-empty 1-D array")

    sid = _resolve_song_id(conn, song_id)
    if tuning is None:
        row = Q.get_song_tuning(conn, sid)
        if row is not None and row["tuning_ref"] is not None:
            raise ValueError(
                f"song {sid} carries the alternate tuning {row['tuning_ref']!r}, so its "
                "partials cannot be placed in 12-TET. Pass "
                "tuning=hallucinote.tuning.store.load_song_tuning(conn, song_id) — the "
                "core never reads the tuning on its own (isolation invariant FR-6)."
            )
    ts_points = Q.get_time_signature_map(conn, sid)

    beats = np.asarray([beat_map.seconds_to_beats(float(t)) for t in times], dtype=np.float64)
    magnitude = np.zeros((freqs.shape[0], times.shape[0]), dtype=np.float64)
    read: dict[str, list[SoundingNote]] = {}

    for span in schedule.spans:
        in_span = (beats >= span.start_beat) & (beats < span.end_beat)
        if not np.any(in_span):
            continue
        tracks: set[str] = set()
        for node in span.nodes:
            tracks.update(_tracks_for_node(conn, node, song_id=sid))
        for track_id in sorted(tracks):
            if track_id not in read:
                read[track_id] = _track_notes(conn, track_id, ts_points)
            for note in read[track_id]:
                frames = in_span & (beats >= note.start_beat) & (beats < note.end_beat)
                if not np.any(frames):
                    continue
                fundamental = pitch_hz(note.pitch, tuning)
                for k in range(1, depth + 1):
                    bin_index = _nearest_bin(freqs, k * fundamental)
                    if bin_index is None:
                        break
                    magnitude[bin_index, frames] = 1.0

    return SpectralField(
        freqs_hz=freqs,
        times_s=times,
        magnitude=magnitude,
        origin="symbolic",
        resolution=resolution,
        fingerprint=_fingerprint(conn, schedule, sid, tuning),
    )


# --------------------------------------------------------------------------- #
# node → tracks
# --------------------------------------------------------------------------- #

def _tracks_for_node(conn: sqlite3.Connection, node: NodeRef, *, song_id: str) -> list[str]:
    """The DB track ids whose notes a node sounds, in track order."""
    rows = Q.get_tracks_for_song(conn, song_id)
    playing = [str(r["id"]) for r in rows if r["kind"] != "master"]
    if len(node) != 2:
        return playing
    kind, ident = node
    if kind in ("track", "minus"):
        if ident not in playing:
            known = {str(r["id"]): str(r["name"]) for r in rows}
            raise ValueError(
                f"node {node!r}: no playing track with id {ident!r} in song {song_id!r}; "
                f"the song's tracks are {known}"
            )
        return [ident] if kind == "track" else [t for t in playing if t != ident]
    returns = {str(r["id"]): str(r["name"]) for r in Q.get_returns_for_song(conn, song_id)}
    if ident not in returns:
        raise ValueError(
            f"node {node!r}: no return with id {ident!r} in song {song_id!r}; "
            f"the song's returns are {returns}"
        )
    # A send at level 0 reaches the bus with nothing; only an audible send
    # makes a track part of the return's reference.
    senders = {
        str(s["from_track_id"])
        for s in Q.get_sends_for_song(conn, song_id)
        if str(s["to_return_id"]) == ident and float(s["level"]) > 0.0
    }
    return [t for t in playing if t in senders]


def _track_notes(
    conn: sqlite3.Connection, track_id: str, ts_points: list[sqlite3.Row]
) -> list[SoundingNote]:
    """A track's notes as the arrangement sounds them.

    A placement sounds its clip from the placement's start for the shorter
    of the placement's extent and the clip's length: the extent is what the
    author wrote, the clip length is what Live's arrangement copy plays, and
    a note has to be inside both to be counted. Muted notes are silent.
    """
    out: list[SoundingNote] = []
    for placement in Q.get_arrangement_for_track(conn, track_id):
        if placement["clip_kind"] != "midi":
            continue
        clip = Q.get_clip(conn, placement["clip_id"])
        if clip is None:
            continue
        start = _position_bar_to_beats(float(placement["start_bar"]), ts_points)
        end = _position_bar_to_beats(float(placement["end_bar"]), ts_points)
        extent = min(end - start, float(clip["length_beats"]))
        for note in Q.get_notes_for_clip(conn, str(placement["clip_id"])):
            if note["mute"] or float(note["start_beats"]) >= extent:
                continue
            note_start = float(note["start_beats"])
            note_end = min(note_start + float(note["duration_beats"]), extent)
            if note_end <= note_start:
                continue
            out.append(
                SoundingNote(
                    track_id=track_id,
                    clip_id=str(placement["clip_id"]),
                    pitch=int(note["pitch"]),
                    start_beat=start + note_start,
                    end_beat=start + note_end,
                    velocity=int(note["velocity"]),
                )
            )
    return out


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _resolve_song_id(conn: sqlite3.Connection, song_id: str | None) -> str:
    if song_id is not None:
        if Q.get_song(conn, song_id) is None:
            raise ValueError(f"no song with id {song_id!r} in this DB")
        return song_id
    ids = [str(r["id"]) for r in conn.execute("SELECT id FROM songs ORDER BY id").fetchall()]
    if len(ids) != 1:
        raise ValueError(
            f"song_id is required when the DB holds {len(ids)} songs (found {ids}); "
            "pass song_id=..."
        )
    return ids[0]


def _nearest_bin(freqs: np.ndarray, hz: float) -> int | None:
    """The bin a partial lands on, or None past the top of the axis.

    Above the last bin there is nothing to place it on — that is the
    Nyquist limit of the raster, not a partial to fold back.
    """
    if hz > freqs[-1]:
        return None
    i = int(np.searchsorted(freqs, hz))
    if i == 0:
        return 0
    return i if abs(freqs[i] - hz) < abs(freqs[i - 1] - hz) else i - 1


def symbolic_fingerprint(
    conn: sqlite3.Connection,
    schedule: ReferenceSchedule,
    *,
    song_id: str | None = None,
    tuning: TuningLike | None = None,
) -> str:
    """The digest a symbolic field over ``schedule`` would carry, without rasterizing.

    A recipe's address needs to know what the reference *is* before any field
    is drawn; this reads exactly what ``symbolic_field`` reads and nothing
    more. A tuned song still needs its tuning passed in (the core never
    imports the bolt-on) — the same gate as the field builder's.
    """
    sid = _resolve_song_id(conn, song_id)
    if tuning is None:
        row = Q.get_song_tuning(conn, sid)
        if row is not None and row["tuning_ref"] is not None:
            raise ValueError(
                f"song {sid} carries the alternate tuning {row['tuning_ref']!r}; pass "
                "tuning=hallucinote.tuning.store.load_song_tuning(conn, song_id) — the core "
                "never reads the tuning on its own (isolation invariant FR-6)."
            )
    return _fingerprint(conn, schedule, sid, tuning)


def _fingerprint(
    conn: sqlite3.Connection,
    schedule: ReferenceSchedule,
    song_id: str,
    tuning: TuningLike | None,
) -> str:
    """What the field was built from: the notes of every placement the
    schedule can reach, where they were placed, the schedule and the tuning.

    A placement moved without a note changing still changes what sounds
    when, so placements enter the digest beside ``clip_fingerprint``.
    """
    ts_points = Q.get_time_signature_map(conn, song_id)
    tracks: set[str] = set()
    for span in schedule.spans:
        for node in span.nodes:
            tracks.update(_tracks_for_node(conn, node, song_id=song_id))
    placements: list[list[object]] = []
    for track_id in sorted(tracks):
        for placement in Q.get_arrangement_for_track(conn, track_id):
            if placement["clip_kind"] != "midi":
                continue
            clip_id = str(placement["clip_id"])
            placements.append(
                [
                    track_id,
                    clip_id,
                    _position_bar_to_beats(float(placement["start_bar"]), ts_points),
                    _position_bar_to_beats(float(placement["end_bar"]), ts_points),
                    clip_fingerprint(Q.get_notes_for_clip(conn, clip_id)),
                ]
            )
    blob = json.dumps(
        {
            "schedule": schedule_digest(schedule),
            "placements": placements,
            "tuning": tuning.to_blob() if tuning is not None else None,
        },
        separators=(",", ":"),
    )
    return "symbolic:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


__all__ = [
    "SoundingNote",
    "bar_to_beat_for_song",
    "pitch_hz",
    "sounding_notes",
    "symbolic_axes",
    "symbolic_field",
]
