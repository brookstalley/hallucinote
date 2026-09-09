"""Detectors that turn a feature stream into a list of moments, musically gated.

A detector's output is a ``FeatureEvent`` list: the moments a gesture may
launch from, and the list the sample lens draws against bars so a threshold
can be tuned by ear before a note is heard. The three detectors here —
scale-tone crossings, energy-threshold crossings and gated onsets — share one
set of ``Gates``: voiced-only, an energy floor, a dwell time and a minimum
spacing. Real speech jitters across every band and threshold many times a
second, so an ungated detector fires continuously; the gates are what make an
event a musical moment rather than a frame. Every gate is explicit — a
detector never fills one in — because a gate that silently defaulted to
"off" would fire that way on the first real line and the author would tune
the wrong knob.

The cascade a crossing launches is a song's composition, authored in its
``build.py``; this module hands it the moments and ``grid_delay`` to land
them on the grid. Pure numpy over the shared feature types; nothing from
the DB, sync or MCP layers.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Sequence

import numpy as np

from hallucinote.features.types import BeatMap, FeatureEvent, FeatureStream, Segment

# A frame whose voicing confidence sits at or above this is voiced. It is the
# majority threshold pYIN's own voiced flag uses, so a stream that carries
# ``voiced_probs`` as its confidence agrees with the flag it came with.
VOICED_CONFIDENCE = 0.5

# 12-TET reference for the tone a pitch is measured against.
_A4_HZ = 440.0
_A4_MIDI = 69

Scale = tuple[int, frozenset[int]]
"""``(tonic_pc, pitch_classes)`` — the tonic names degree 0 of the scale."""


@dataclass(frozen=True)
class Gates:
    """The four musical gates every detector applies, each set on purpose.

    ``voiced_only`` drops frames the F0 tracker did not hear as pitched.
    ``energy_floor_db`` drops frames quieter than the floor (dBFS, the energy
    stream's units); ``-inf`` switches the floor off and says so in the call.
    ``dwell_s`` is how long the detector's condition must hold, continuously,
    before an entry counts — measured from the first frame of the run to its
    last, so ``0.0`` fires on entry. ``min_spacing_s`` is a refractory period
    after a fired event during which nothing else fires.
    """

    voiced_only: bool
    energy_floor_db: float
    dwell_s: float
    min_spacing_s: float

    def __post_init__(self) -> None:
        if not isinstance(self.voiced_only, bool):
            raise ValueError(
                f"Gates.voiced_only must be True or False; got {self.voiced_only!r}"
            )
        if math.isnan(self.energy_floor_db) or self.energy_floor_db == math.inf:
            raise ValueError(
                "Gates.energy_floor_db must be a dB level or -inf (floor off); "
                f"got {self.energy_floor_db}"
            )
        if not (self.dwell_s >= 0.0):
            raise ValueError(f"Gates.dwell_s must be >= 0 seconds; got {self.dwell_s}")
        if not (self.min_spacing_s >= 0.0):
            raise ValueError(
                f"Gates.min_spacing_s must be >= 0 seconds; got {self.min_spacing_s}"
            )

    @property
    def energy_gated(self) -> bool:
        return self.energy_floor_db > -math.inf


# --- shared frame machinery ---------------------------------------------------


def _scalar_stream(stream: FeatureStream, role: str) -> None:
    if stream.values.ndim != 1:
        raise ValueError(
            f"{role} stream {stream.name!r} must be scalar per frame (shape (n,)); "
            f"got {stream.values.shape}"
        )
    if len(stream) == 0:
        raise ValueError(f"{role} stream {stream.name!r} has no frames to detect on")


def _nearest_index(src_times: np.ndarray, times: np.ndarray) -> np.ndarray:
    """Index of the source frame nearest each query time.

    Streams are sampled at their own hop, and an energy envelope rarely shares
    the F0 tracker's grid; nearest-frame lookup keeps a gate honest about what
    was measured rather than interpolating a value nobody saw.
    """
    n = src_times.shape[0]
    if n == 1:
        return np.zeros(times.shape[0], dtype=np.intp)
    right = np.clip(np.searchsorted(src_times, times), 1, n - 1)
    left = right - 1
    pick_left = (times - src_times[left]) <= (src_times[right] - times)
    return np.where(pick_left, left, right)


def _voiced_mask(f0: FeatureStream) -> np.ndarray:
    """Frames the tracker heard as pitched: a finite F0 and, when it says how sure it is, sure enough."""
    voiced = np.isfinite(f0.values.astype(np.float64))
    if f0.confidence is not None:
        voiced &= f0.confidence >= VOICED_CONFIDENCE
    return voiced


def _eligible_mask(
    times: np.ndarray,
    gates: Gates,
    *,
    f0: FeatureStream | None,
    energy: FeatureStream | None,
    detector: str,
) -> np.ndarray:
    """Per-frame pass/fail for the voicing and energy gates at ``times``.

    Refuses when a gate is switched on but the stream it reads is missing —
    silently treating every frame as voiced or loud is exactly the failure
    the gates exist to prevent.
    """
    ok = np.ones(times.shape[0], dtype=bool)
    if gates.voiced_only:
        if f0 is None:
            raise ValueError(
                f"{detector}: Gates.voiced_only=True needs an f0 stream to read voicing "
                "from; pass f0=<the F0 FeatureStream> or set voiced_only=False"
            )
        _scalar_stream(f0, "f0")
        ok &= _voiced_mask(f0)[_nearest_index(f0.times_s, times)]
    if gates.energy_gated:
        if energy is None:
            raise ValueError(
                f"{detector}: Gates.energy_floor_db={gates.energy_floor_db} needs an "
                "energy stream (dBFS) to compare against; pass energy=<the energy "
                "FeatureStream> or set energy_floor_db=-inf to switch the floor off"
            )
        _scalar_stream(energy, "energy")
        level = energy.values.astype(np.float64)[_nearest_index(energy.times_s, times)]
        ok &= np.isfinite(level) & (level >= gates.energy_floor_db)
    return ok


def _runs(cond: np.ndarray, key: np.ndarray) -> list[tuple[int, int]]:
    """Maximal ``(start, end)`` index spans where ``cond`` holds and ``key`` is constant.

    ``key`` is what the run is *of* — the scale tone a pitch sits in — so a
    step straight from one tone's band into the next starts a new run rather
    than extending the old one.
    """
    n = cond.shape[0]
    if n == 0:
        return []
    boundary = np.ones(n, dtype=bool)
    boundary[1:] = (cond[1:] != cond[:-1]) | (key[1:] != key[:-1])
    starts = np.flatnonzero(boundary)
    ends = np.append(starts[1:], n) - 1
    return [(int(s), int(e)) for s, e in zip(starts, ends) if cond[s]]


def _space(events: list[FeatureEvent], min_spacing_s: float) -> list[FeatureEvent]:
    """Drop every event inside the refractory window after the last one kept."""
    kept: list[FeatureEvent] = []
    for ev in sorted(events, key=lambda e: e.time_s):
        if kept and ev.time_s - kept[-1].time_s < min_spacing_s:
            continue
        kept.append(ev)
    return kept


# --- scale-tone crossings ---------------------------------------------------


def _validate_scale(scale: Scale) -> tuple[int, tuple[int, ...]]:
    try:
        tonic_pc, pcs = scale
    except (TypeError, ValueError):
        raise ValueError(
            f"scale must be (tonic_pc, pitch_classes), e.g. (0, frozenset({{0, 2, 4, 5, 7, 9, 11}})) "
            f"for C major; got {scale!r}"
        ) from None
    if not isinstance(tonic_pc, int) or not 0 <= tonic_pc < 12:
        raise ValueError(f"scale tonic_pc must be an int in 0..11; got {tonic_pc!r}")
    pitch_classes = tuple(sorted(set(pcs)))
    if not pitch_classes:
        raise ValueError("scale pitch_classes must name at least one pitch class")
    bad = [pc for pc in pitch_classes if not isinstance(pc, int) or not 0 <= pc < 12]
    if bad:
        raise ValueError(f"scale pitch_classes must be ints in 0..11; got {bad!r}")
    return tonic_pc, pitch_classes


def _hz_to_midi(hz: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return _A4_MIDI + 12.0 * np.log2(hz / _A4_HZ)


def _midi_to_hz(midi: float) -> float:
    return _A4_HZ * 2.0 ** ((midi - _A4_MIDI) / 12.0)


def _nearest_scale_tone(midi: np.ndarray, pitch_classes: tuple[int, ...]) -> tuple[np.ndarray, np.ndarray]:
    """For each frame, the nearest MIDI note of the scale and the distance to it in cents.

    Every octave of every scale pitch class is a candidate, so a line that
    crosses an octave keeps finding the tone it is nearest to.
    """
    pcs = np.asarray(pitch_classes, dtype=np.float64)[:, None]
    m = midi[None, :]
    candidates = pcs + 12.0 * np.round((m - pcs) / 12.0)
    distance = np.abs(m - candidates)
    pick = np.argmin(distance, axis=0)
    cols = np.arange(midi.shape[0])
    tone = candidates[pick, cols]
    cents = 100.0 * (midi - tone)
    return tone, cents


def scale_tone_crossings(
    f0: FeatureStream,
    *,
    scale: Scale,
    band_cents: float,
    gates: Gates,
    energy: FeatureStream | None = None,
) -> list[FeatureEvent]:
    """Moments the tracked pitch enters a scale tone's ± band and stays.

    One event per entry that dwells: the event's ``time_s`` is the entry, and
    its payload names the tone (``midi``, ``pitch_class``, ``degree`` from
    the tonic, ``hz``) plus the mean ``cents`` deviation and the ``dwell_s``
    actually measured, so a cascade can transpose up the scale from the
    degree it landed on. ``band_cents`` is the half-width of each tone's band;
    a band wider than half the gap to the next scale tone makes the bands
    overlap, and the nearer tone wins.
    """
    _scalar_stream(f0, "f0")
    tonic_pc, pitch_classes = _validate_scale(scale)
    if not (band_cents > 0.0):
        raise ValueError(f"band_cents must be > 0 (a half-width in cents); got {band_cents}")
    degree_of = {pc: i for i, pc in enumerate(sorted(pitch_classes, key=lambda p: (p - tonic_pc) % 12))}

    hz = f0.values.astype(np.float64)
    pitched = np.isfinite(hz) & (hz > 0.0)
    midi = np.where(pitched, _hz_to_midi(np.where(pitched, hz, 1.0)), np.nan)
    tone, cents = _nearest_scale_tone(np.where(pitched, midi, 0.0), pitch_classes)
    in_band = pitched & (np.abs(cents) <= band_cents)
    eligible = _eligible_mask(
        f0.times_s, gates, f0=f0, energy=energy, detector="scale_tone_crossings",
    )
    cond = in_band & eligible
    key = np.where(cond, tone, np.nan)

    events: list[FeatureEvent] = []
    for start, end in _runs(cond, key):
        dwell = float(f0.times_s[end] - f0.times_s[start])
        if dwell < gates.dwell_s:
            continue
        note = int(round(tone[start]))
        pc = note % 12
        events.append(FeatureEvent(
            time_s=float(f0.times_s[start]),
            kind="scale_tone",
            payload={
                "midi": note,
                "pitch_class": pc,
                "degree": degree_of[pc],
                "hz": _midi_to_hz(note),
                "cents": float(np.mean(cents[start:end + 1])),
                "dwell_s": dwell,
            },
        ))
    return _space(events, gates.min_spacing_s)


# --- energy threshold crossings ---------------------------------------------


def energy_threshold_events(
    energy: FeatureStream,
    *,
    threshold_db: float,
    gates: Gates,
    f0: FeatureStream | None = None,
) -> list[FeatureEvent]:
    """Moments the energy envelope rises through ``threshold_db`` and stays above it.

    The rising edge is the event; the run above the threshold must last
    ``gates.dwell_s``. The energy floor gate reads the same stream (a floor
    above the threshold simply raises it), and ``voiced_only`` reads ``f0``.
    Payload: ``energy_db`` at the edge, ``peak_db`` over the run, ``duration_s``.
    """
    _scalar_stream(energy, "energy")
    if math.isnan(threshold_db):
        raise ValueError("threshold_db must be a dB level; got nan")
    level = energy.values.astype(np.float64)
    above = np.isfinite(level) & (level >= threshold_db)
    eligible = _eligible_mask(
        energy.times_s, gates, f0=f0, energy=energy, detector="energy_threshold_events",
    )
    cond = above & eligible
    events: list[FeatureEvent] = []
    for start, end in _runs(cond, cond):
        duration = float(energy.times_s[end] - energy.times_s[start])
        if duration < gates.dwell_s:
            continue
        events.append(FeatureEvent(
            time_s=float(energy.times_s[start]),
            kind="energy_threshold",
            payload={
                "threshold_db": float(threshold_db),
                "energy_db": float(level[start]),
                "peak_db": float(np.max(level[start:end + 1])),
                "duration_s": duration,
            },
        ))
    return _space(events, gates.min_spacing_s)


# --- onsets ------------------------------------------------------------------


def onset_events(
    segments: Sequence[Segment],
    *,
    gates: Gates,
    energy: FeatureStream | None = None,
    f0: FeatureStream | None = None,
) -> list[FeatureEvent]:
    """The start of each onset-bounded segment that survives the gates.

    A segment shorter than ``gates.dwell_s`` is a click, not a note, and is
    dropped; a segment whose start is unvoiced or under the energy floor is
    dropped; the rest fire at ``start_s`` with the segment's ``kind``,
    ``label`` and ``duration_s`` (plus ``energy_db`` / ``hz`` at the start
    when those streams were given) in the payload.
    """
    if not segments:
        return []
    starts = np.asarray([s.start_s for s in segments], dtype=np.float64)
    eligible = _eligible_mask(starts, gates, f0=f0, energy=energy, detector="onset_events")
    level = (
        energy.values.astype(np.float64)[_nearest_index(energy.times_s, starts)]
        if energy is not None else None
    )
    hz = (
        f0.values.astype(np.float64)[_nearest_index(f0.times_s, starts)]
        if f0 is not None else None
    )
    events: list[FeatureEvent] = []
    for i, seg in enumerate(segments):
        if not eligible[i] or seg.duration_s < gates.dwell_s:
            continue
        payload: dict[str, Any] = {
            "segment_kind": seg.kind,
            "label": seg.label,
            "duration_s": seg.duration_s,
        }
        if level is not None:
            payload["energy_db"] = float(level[i])
        if hz is not None:
            payload["hz"] = float(hz[i])
        events.append(FeatureEvent(time_s=seg.start_s, kind="onset", payload=payload))
    return _space(events, gates.min_spacing_s)


# --- beats and the grid --------------------------------------------------------


def events_to_beats(events: Sequence[FeatureEvent], beat_map: BeatMap) -> list[FeatureEvent]:
    """The same events with ``beat`` filled through the clip's placement; ``time_s`` stays."""
    return [replace(ev, beat=beat_map.seconds_to_beats(ev.time_s)) for ev in events]


def grid_delay(event_beat: float, grid_beats: float) -> float:
    """The next grid position at or after ``event_beat`` — the moment a delayed gesture lands.

    An event already on the grid is not delayed; one a hair past a grid line
    (within a millionth of a beat, the noise of a seconds→beats map) is
    treated as on it rather than pushed a whole step.
    """
    if not (grid_beats > 0.0):
        raise ValueError(f"grid_beats must be > 0 (e.g. 0.25 for a sixteenth); got {grid_beats}")
    if not math.isfinite(event_beat):
        raise ValueError(f"event_beat must be finite; got {event_beat}")
    return math.ceil(event_beat / grid_beats - 1e-6) * grid_beats
