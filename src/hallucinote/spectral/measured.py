"""The measured spectral field — the STFT magnitude of a captured surface.

Every render captures per-track stems, per-return surfaces and the master,
float32 and sample-aligned at their heads. That capture set is the measured
field library: a node's field is the magnitude of its surface over the
schedule's spans, with device colour, saturation and reverb tails included
— the full truth, at the cost of a render. ``('minus', t)`` is the mix minus
one track, summed from every other surface the way the stem-sum lens sums
them, so a sample is never carved against its own energy.

Alignment is inherited, not restated: the capture's heads are calibrated
sample-aligned and the surfaces are trimmed to a common length before any
frame is placed. Where that inheritance does not hold — a node with no
surface in the set, a surface whose length cannot be a stop-ramp, a span
outside what was captured, a manifest whose beat span is empty — the field
refuses rather than approximates, because a carve one beat off carves the
wrong moment.

Discipline: one of the two modules under ``spectral/`` allowed to read the
DB and the capture set. The DB is read only to turn a node's DB id into the
manifest's surface id; the capture is read through ``audio/io.py`` as it is.
"""
from __future__ import annotations

import sqlite3
from typing import Mapping, Sequence

import numpy as np

from hallucinote.audio.alignment import trim_to_common_length
from hallucinote.audio.codeversion import disk_signature
from hallucinote.audio.io import CaptureSet, Surface
from hallucinote.audio.levels import apply_stem_gains
from hallucinote.audio.onsets import to_mono
from hallucinote.audio.section import BeatSampleMap, TempoSegment
from hallucinote.db import queries as Q
from hallucinote.features.types import BeatMap
from hallucinote.spectral.schedule import schedule_digest
from hallucinote.spectral.types import (
    NodeRef,
    ReferenceSchedule,
    ResolutionReport,
    SpectralField,
)

DEFAULT_N_FFT = 2048
DEFAULT_HOP = 512

# Surfaces from one render finalize on a wall-clock stop ramp of tens of
# milliseconds each (``audio/alignment.py`` measured it). A spread of lengths
# beyond a second is not that ramp — it is a surface from another take, or a
# recording that stopped early — and trimming to it would discard content
# while calling the result aligned.
MAX_STOP_RAMP_S = 1.0


def surface_id_for_node(conn: sqlite3.Connection, node: NodeRef) -> str:
    """The capture manifest's surface id for a node's DB id.

    Captures are keyed by structural position — ``track:N`` on
    ``track_index``, ``return:N`` on the return's ``position``, ``master`` —
    the format ``hallucinote_mcp.analyzer.setup.track_id_for_surface`` writes.
    The engine never imports the server package, so the format is mirrored
    here; it changes there first.
    """
    if len(node) != 2:
        return "master"
    kind, ident = node
    if kind == "return":
        ret = Q.get_return(conn, ident)
        if ret is None:
            raise ValueError(f"node {node!r}: no return with id {ident!r} in the DB")
        return f"return:{int(ret['position'])}"
    track = Q.get_track(conn, ident)
    if track is None:
        raise ValueError(f"node {node!r}: no track with id {ident!r} in the DB")
    return f"track:{int(track['track_index'])}"


def measured_field(
    capture_set: CaptureSet,
    schedule: ReferenceSchedule,
    beat_map: BeatMap,
    *,
    conn: sqlite3.Connection,
    n_fft: int = DEFAULT_N_FFT,
    hop: int = DEFAULT_HOP,
    tempo_segments: Sequence[TempoSegment] = (),
    stem_gains: Mapping[str, float] | None = None,
) -> SpectralField:
    """The magnitude surface the schedule's nodes actually produced.

    Frames are located in the capture through the capture's own beat map
    (its declared span over its aligned length, tempo-shaped by
    ``tempo_segments`` when given) and labelled in seconds through
    ``beat_map`` — anchor it to the target clip and the field lands on the
    target's clock, interchangeable with a symbolic one. ``stem_gains`` maps
    surface id → linear fader gain, the map the stem-sum lens takes; unity
    when omitted, so a raw pre-fader sum is what ``minus`` means then.
    Measured on the mono sum, like every cross-surface lens here.
    """
    resolution = ResolutionReport(n_fft=n_fft, hop=hop, sample_rate=capture_set.sample_rate)
    aligned = _require_aligned(capture_set)
    sr = aligned.sample_rate
    n_common = aligned.master.audio.shape[0]

    capture_end = aligned.stop_at_beat + aligned.ring_out_beats
    if schedule.start_beat < aligned.start_at_beat or schedule.end_beat > capture_end:
        raise ValueError(
            f"schedule spans beats [{schedule.start_beat:g}, {schedule.end_beat:g}) but the "
            f"capture at {aligned.manifest_path} covers [{aligned.start_at_beat:g}, "
            f"{capture_end:g}) — the reference at those beats was never captured, so "
            "it cannot be aligned; render that range or narrow the schedule"
        )
    capture_map = BeatSampleMap(
        aligned.start_at_beat, capture_end, n_common, tempo_segments
    )
    if capture_map.degenerate:
        raise ValueError(
            f"the capture at {aligned.manifest_path} yields no beat↔sample map "
            f"(start_at_beat={aligned.start_at_beat}, stop_at_beat={aligned.stop_at_beat}, "
            f"ring_out_beats={aligned.ring_out_beats}, samples={n_common}); the manifest "
            "cannot place a beat, so nothing here can be aligned"
        )

    surfaces = _surfaces_by_id(aligned)
    gains = dict(stem_gains) if stem_gains else {}

    region_start = capture_map.beat_to_sample(schedule.start_beat)
    region_end = capture_map.beat_to_sample(schedule.end_beat)
    if region_end <= region_start:
        raise ValueError(
            f"schedule [{schedule.start_beat:g}, {schedule.end_beat:g}) maps to no samples "
            f"in the capture ({region_start}..{region_end}); the span is shorter than one "
            "sample at this tempo"
        )
    buffer = np.zeros(region_end - region_start, dtype=np.float64)
    for span in schedule.spans:
        s0 = capture_map.beat_to_sample(span.start_beat) - region_start
        s1 = capture_map.beat_to_sample(span.end_beat) - region_start
        if s1 <= s0:
            continue
        summed = _node_sum(
            [_audio_for_node(conn, node, aligned, surfaces, gains) for node in span.nodes]
        )
        buffer[s0:s1] += summed[s0 + region_start : s1 + region_start]

    magnitude, freqs = _stft_magnitude(buffer, sr, n_fft=n_fft, hop=hop)
    centers = region_start + np.arange(magnitude.shape[1]) * hop
    beats = [capture_map.sample_to_beat(float(c)) for c in centers]
    times = np.asarray([beat_map.beats_to_seconds(b) for b in beats], dtype=np.float64)

    return SpectralField(
        freqs_hz=freqs,
        times_s=times,
        magnitude=magnitude,
        origin="measured",
        resolution=resolution,
        fingerprint=(
            f"measured:{aligned.captured_at}:{disk_signature()}:{schedule_digest(schedule)}"
        ),
    )


# --------------------------------------------------------------------------- #
# alignment
# --------------------------------------------------------------------------- #

def _require_aligned(capture: CaptureSet) -> CaptureSet:
    """The aligned capture, or a refusal naming what broke the inheritance."""
    if capture.stop_at_beat <= capture.start_at_beat:
        raise ValueError(
            f"the manifest at {capture.manifest_path} declares an empty beat span "
            f"(start_at_beat={capture.start_at_beat}, stop_at_beat={capture.stop_at_beat}); "
            "without a span no sample can be given a beat, so nothing can be aligned"
        )
    surfaces = [capture.master, *capture.stems, *capture.returns]
    empty = [s.track_id for s in surfaces if s.audio.shape[0] == 0]
    if empty:
        raise ValueError(
            f"surfaces {empty} in the capture at {capture.manifest_path} carry no "
            "samples; an empty surface has no head to align"
        )
    lengths = {s.track_id: s.audio.shape[0] for s in surfaces}
    longest, shortest = max(lengths.values()), min(lengths.values())
    drift_s = (longest - shortest) / capture.sample_rate
    if drift_s > MAX_STOP_RAMP_S:
        outliers = sorted(lengths, key=lambda surface_id: lengths[surface_id])
        raise ValueError(
            f"surface lengths in the capture at {capture.manifest_path} spread by "
            f"{drift_s:.2f} s (shortest {outliers[0]!r}={shortest}, longest "
            f"{outliers[-1]!r}={longest} samples) — far beyond the stop ramp one render "
            f"produces (< {MAX_STOP_RAMP_S:g} s), so these surfaces are not one aligned "
            "take; re-render, or drop the surface that does not belong"
        )
    aligned, _report = trim_to_common_length(capture)
    return aligned


def _surfaces_by_id(capture: CaptureSet) -> dict[str, Surface]:
    return {s.track_id: s for s in (capture.master, *capture.stems, *capture.returns)}


# --------------------------------------------------------------------------- #
# node → audio
# --------------------------------------------------------------------------- #

def _audio_for_node(
    conn: sqlite3.Connection,
    node: NodeRef,
    capture: CaptureSet,
    surfaces: Mapping[str, Surface],
    gains: Mapping[str, float],
) -> np.ndarray:
    """A node's mono audio over the whole aligned capture, fader-scaled."""
    if node[0] == "minus":
        excluded = surface_id_for_node(conn, ("track", node[1]))
        if excluded not in surfaces:
            raise _no_surface(node, excluded, capture)
        # Returns are part of what reaches the master, so the mix minus a
        # track keeps them — including the track's own send tail, which no
        # stem separates out; that residue is a limit of the capture, not of
        # this sum.
        others = [
            (s.track_id, to_mono(s.audio).astype(np.float64))
            for s in (*capture.stems, *capture.returns)
            if s.track_id != excluded
        ]
        if not others:
            raise ValueError(
                f"node {node!r}: the capture holds no surface other than {excluded!r}, "
                "so the mix minus it is empty"
            )
        return _node_sum([audio for _, audio in apply_stem_gains(others, gains)])
    surface_id = surface_id_for_node(conn, node)
    surface = surfaces.get(surface_id)
    if surface is None:
        raise _no_surface(node, surface_id, capture)
    (scaled,) = apply_stem_gains(
        [(surface_id, to_mono(surface.audio).astype(np.float64))], gains
    )
    return scaled[1]


def _node_sum(parts: Sequence[np.ndarray]) -> np.ndarray:
    """Sum equal-length mono buffers — the stem-sum lens's own summation."""
    return np.sum(np.stack(parts, axis=0), axis=0)


def _no_surface(node: NodeRef, surface_id: str, capture: CaptureSet) -> ValueError:
    present = sorted(_surfaces_by_id(capture))
    return ValueError(
        f"node {node!r} resolves to surface {surface_id!r}, which the capture at "
        f"{capture.manifest_path} does not hold (surfaces: {present}); a node with no "
        "captured surface has no measured field — render with it captured, or use "
        "the symbolic field"
    )


# --------------------------------------------------------------------------- #
# STFT
# --------------------------------------------------------------------------- #

def _stft_magnitude(
    mono: np.ndarray, sample_rate: int, *, n_fft: int, hop: int
) -> tuple[np.ndarray, np.ndarray]:
    """Centered-frame STFT magnitude and its bin frequencies."""
    import librosa

    spec = librosa.stft(mono.astype(np.float32), n_fft=n_fft, hop_length=hop, center=True)
    freqs = librosa.fft_frequencies(sr=sample_rate, n_fft=n_fft)
    return np.abs(spec).astype(np.float64), np.asarray(freqs, dtype=np.float64)


__all__ = [
    "DEFAULT_HOP",
    "DEFAULT_N_FFT",
    "MAX_STOP_RAMP_S",
    "measured_field",
    "surface_id_for_node",
]
