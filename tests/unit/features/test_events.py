"""Detectors fire on musical moments, and the gates are what keep them from firing on every frame."""
from __future__ import annotations

import math

import numpy as np
import pytest

from hallucinote.features.events import (
    Gates,
    energy_threshold_events,
    events_to_beats,
    grid_delay,
    onset_events,
    scale_tone_crossings,
)
from hallucinote.features.types import FeatureEvent, FeatureStream, Segment

C_MAJOR = (0, frozenset({0, 2, 4, 5, 7, 9, 11}))
HOP_S = 0.005  # 200 frames/s resolves a 25 Hz wobble with eight frames per cycle
OFF = Gates(voiced_only=False, energy_floor_db=-math.inf, dwell_s=0.0, min_spacing_s=0.0)


def _midi_to_hz(midi: np.ndarray | float) -> np.ndarray:
    return 440.0 * 2.0 ** ((np.asarray(midi, dtype=np.float64) - 69.0) / 12.0)


def _f0(cents_from_c4: np.ndarray, *, confidence: np.ndarray | None = None) -> FeatureStream:
    times = np.arange(cents_from_c4.shape[0]) * HOP_S
    return FeatureStream("f0", times_s=times, values=_midi_to_hz(60.0 + cents_from_c4 / 100.0),
                         units="hz", confidence=confidence)


GLIDE_START_CENTS, GLIDE_END_CENTS, GLIDE_S = -160.0, 1340.0, 8.0
GLIDE_RATE = (GLIDE_END_CENTS - GLIDE_START_CENTS) / GLIDE_S  # cents per second
BAND_CENTS = 30.0


def _wobbly_glide() -> FeatureStream:
    """B3 to C5 in eight seconds with a ±20-cent, 25 Hz wobble — speech-like jitter on a glide.

    The glide starts and ends outside every band (B3's ±30 band begins at
    -130 cents, D5's at +170), so the tones it passes are exactly B3 .. C5.
    """
    n = int(GLIDE_S / HOP_S)
    t = np.arange(n) * HOP_S
    glide = np.linspace(GLIDE_START_CENTS, GLIDE_END_CENTS, n)
    return _f0(glide + 20.0 * np.sin(2.0 * math.pi * 25.0 * t))


def _glide_reaches(midi: int) -> float:
    """The second the underlying glide sits exactly on ``midi``."""
    return ((midi - 60) * 100.0 - GLIDE_START_CENTS) / GLIDE_RATE


class _ConstantTempo:
    """120 bpm, clip placed at beat 8."""

    def seconds_to_beats(self, seconds: float) -> float:
        return 8.0 + seconds * 2.0

    def beats_to_seconds(self, beats: float) -> float:
        return (beats - 8.0) / 2.0


# --- scale-tone crossings ---------------------------------------------------


def test_glide_through_the_scale_fires_once_per_tone_with_dwell():
    gates = Gates(voiced_only=False, energy_floor_db=-math.inf, dwell_s=0.06, min_spacing_s=0.0)
    events = scale_tone_crossings(_wobbly_glide(), scale=C_MAJOR, band_cents=30.0, gates=gates)

    assert [e.payload["midi"] for e in events] == [59, 60, 62, 64, 65, 67, 69, 71, 72]
    assert [e.payload["degree"] for e in events] == [6, 0, 1, 2, 3, 4, 5, 6, 0]
    assert [e.payload["pitch_class"] for e in events] == [11, 0, 2, 4, 5, 7, 9, 11, 0]
    assert all(e.kind == "scale_tone" for e in events)
    assert all(e.payload["dwell_s"] >= 0.06 for e in events)
    assert all(abs(e.payload["cents"]) <= 30.0 for e in events)
    assert events[1].payload["hz"] == pytest.approx(261.626, abs=0.01)
    times = [e.time_s for e in events]
    assert times == sorted(times)
    # Each entry lands while the glide is inside the tone's band, on the way
    # up to its centre — never after the pitch has passed the tone.
    band_crossing_s = 2 * BAND_CENTS / GLIDE_RATE
    for ev in events:
        centre = _glide_reaches(ev.payload["midi"])
        assert centre - band_crossing_s <= ev.time_s <= centre


def test_the_same_glide_fires_continuously_without_gates():
    """The contrast the gates exist for: the wobble re-enters each band several times."""
    gated = scale_tone_crossings(
        _wobbly_glide(), scale=C_MAJOR, band_cents=30.0,
        gates=Gates(voiced_only=False, energy_floor_db=-math.inf, dwell_s=0.06, min_spacing_s=0.0),
    )
    ungated = scale_tone_crossings(_wobbly_glide(), scale=C_MAJOR, band_cents=30.0, gates=OFF)
    assert len(ungated) >= 3 * len(gated)
    # Every ungated event is still a real band entry on a real scale tone.
    assert {e.payload["midi"] for e in ungated} == {59, 60, 62, 64, 65, 67, 69, 71, 72}


def _two_dwells_on_c4(gap_s: float = 0.05) -> FeatureStream:
    on = np.zeros(int(0.3 / HOP_S))
    gap = np.full(int(gap_s / HOP_S), np.nan)
    return _f0(np.concatenate([on, gap, on]))


def test_min_spacing_suppresses_the_second_of_two_close_fires():
    stream = _two_dwells_on_c4()
    loose = Gates(voiced_only=False, energy_floor_db=-math.inf, dwell_s=0.06, min_spacing_s=0.0)
    tight = Gates(voiced_only=False, energy_floor_db=-math.inf, dwell_s=0.06, min_spacing_s=0.5)
    two = scale_tone_crossings(stream, scale=C_MAJOR, band_cents=30.0, gates=loose)
    one = scale_tone_crossings(stream, scale=C_MAJOR, band_cents=30.0, gates=tight)
    assert [e.time_s for e in two] == pytest.approx([0.0, 0.35])
    assert [e.time_s for e in one] == [0.0]


def test_unvoiced_frames_never_fire_under_voiced_only():
    # A tracker that guesses a pitch on unvoiced frames reports low confidence there.
    n = int(0.3 / HOP_S)
    cents = np.zeros(n)
    voiced = Gates(voiced_only=True, energy_floor_db=-math.inf, dwell_s=0.06, min_spacing_s=0.0)
    unsure = _f0(cents, confidence=np.full(n, 0.1))
    assert scale_tone_crossings(unsure, scale=C_MAJOR, band_cents=30.0, gates=voiced) == []
    assert len(scale_tone_crossings(unsure, scale=C_MAJOR, band_cents=30.0, gates=OFF)) == 1
    sure = _f0(cents, confidence=np.full(n, 0.9))
    assert len(scale_tone_crossings(sure, scale=C_MAJOR, band_cents=30.0, gates=voiced)) == 1
    # A nan frame has no pitch to be in a band, whatever the gates say.
    silent = _f0(np.full(n, np.nan))
    assert scale_tone_crossings(silent, scale=C_MAJOR, band_cents=30.0, gates=OFF) == []


def test_a_low_confidence_frame_breaks_the_dwell_run():
    n = int(0.3 / HOP_S)
    conf = np.full(n, 0.9)
    conf[n // 2] = 0.0
    stream = _f0(np.zeros(n), confidence=conf)
    voiced = Gates(voiced_only=True, energy_floor_db=-math.inf, dwell_s=0.2, min_spacing_s=0.0)
    assert scale_tone_crossings(stream, scale=C_MAJOR, band_cents=30.0, gates=voiced) == []


def test_energy_floor_reads_an_energy_stream_on_its_own_frame_grid():
    n = int(0.6 / HOP_S)
    stream = _f0(np.zeros(n))
    # A coarser envelope: quiet for the first 0.3 s, then loud.
    energy = FeatureStream("energy", times_s=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
                           values=[-60.0, -60.0, -60.0, -20.0, -20.0, -20.0], units="dbfs")
    gates = Gates(voiced_only=False, energy_floor_db=-40.0, dwell_s=0.06, min_spacing_s=0.0)
    events = scale_tone_crossings(stream, scale=C_MAJOR, band_cents=30.0, gates=gates, energy=energy)
    assert len(events) == 1
    assert 0.25 < events[0].time_s <= 0.26  # the nearest energy frame hands over at 0.25

    with pytest.raises(ValueError, match="needs an energy stream"):
        scale_tone_crossings(stream, scale=C_MAJOR, band_cents=30.0, gates=gates)


def test_an_octave_step_is_a_new_tone_and_the_nearest_tone_wins_across_the_octave():
    n = int(0.2 / HOP_S)
    stream = _f0(np.concatenate([np.zeros(n), np.full(n, 1200.0), np.full(n, 2395.0)]))
    events = scale_tone_crossings(stream, scale=C_MAJOR, band_cents=30.0, gates=OFF)
    assert [e.payload["midi"] for e in events] == [60, 72, 84]
    assert events[2].payload["cents"] == pytest.approx(-5.0)


@pytest.mark.parametrize("scale,msg", [
    ((12, frozenset({0})), "tonic_pc"),
    ((0, frozenset()), "at least one"),
    ((0, frozenset({0, 13})), "0..11"),
    ("C major", r"\(tonic_pc, pitch_classes\)"),
])
def test_scale_is_validated(scale, msg):
    with pytest.raises(ValueError, match=msg):
        scale_tone_crossings(_f0(np.zeros(4)), scale=scale, band_cents=30.0, gates=OFF)


def test_band_and_stream_shape_are_validated():
    with pytest.raises(ValueError, match="band_cents"):
        scale_tone_crossings(_f0(np.zeros(4)), scale=C_MAJOR, band_cents=0.0, gates=OFF)
    vector = FeatureStream("bark", times_s=[0.0, 0.1], values=np.zeros((2, 3)), units="db")
    with pytest.raises(ValueError, match="scalar per frame"):
        scale_tone_crossings(vector, scale=C_MAJOR, band_cents=30.0, gates=OFF)


# --- gates ----------------------------------------------------------------------


@pytest.mark.parametrize("kwargs,msg", [
    (dict(voiced_only=1, energy_floor_db=-math.inf, dwell_s=0.0, min_spacing_s=0.0), "voiced_only"),
    (dict(voiced_only=False, energy_floor_db=math.nan, dwell_s=0.0, min_spacing_s=0.0), "energy_floor_db"),
    (dict(voiced_only=False, energy_floor_db=math.inf, dwell_s=0.0, min_spacing_s=0.0), "energy_floor_db"),
    (dict(voiced_only=False, energy_floor_db=-math.inf, dwell_s=-0.1, min_spacing_s=0.0), "dwell_s"),
    (dict(voiced_only=False, energy_floor_db=-math.inf, dwell_s=0.0, min_spacing_s=-1.0), "min_spacing_s"),
])
def test_gates_refuse_values_that_cannot_gate(kwargs, msg):
    with pytest.raises(ValueError, match=msg):
        Gates(**kwargs)


def test_every_gate_is_explicit():
    with pytest.raises(TypeError):
        Gates(voiced_only=True, energy_floor_db=-40.0, dwell_s=0.05)  # type: ignore[call-arg]


# --- energy threshold -------------------------------------------------------


def _envelope() -> FeatureStream:
    """Quiet, a 0.4 s phrase at -20, quiet, a 0.02 s click at -10, quiet."""
    hop = 0.01
    seq = [-60.0] * 20 + [-20.0] * 40 + [-60.0] * 20 + [-10.0] * 2 + [-60.0] * 20
    return FeatureStream("energy", times_s=np.arange(len(seq)) * hop, values=np.asarray(seq), units="dbfs")


def test_energy_threshold_fires_at_the_rising_edge_that_dwells():
    gates = Gates(voiced_only=False, energy_floor_db=-math.inf, dwell_s=0.1, min_spacing_s=0.0)
    events = energy_threshold_events(_envelope(), threshold_db=-30.0, gates=gates)
    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "energy_threshold" and ev.time_s == pytest.approx(0.2)
    assert ev.payload["energy_db"] == -20.0 and ev.payload["peak_db"] == -20.0
    assert ev.payload["duration_s"] == pytest.approx(0.39)
    # Without dwell the click fires too.
    assert len(energy_threshold_events(_envelope(), threshold_db=-30.0, gates=OFF)) == 2


def test_energy_threshold_voiced_only_needs_an_f0_stream_and_uses_it():
    env = _envelope()
    voiced = Gates(voiced_only=True, energy_floor_db=-math.inf, dwell_s=0.0, min_spacing_s=0.0)
    with pytest.raises(ValueError, match="needs an f0 stream"):
        energy_threshold_events(env, threshold_db=-30.0, gates=voiced)
    # Voiced only during the click, so only the click fires.
    hz = np.full(len(env), np.nan)
    hz[80:82] = 220.0
    f0 = FeatureStream("f0", times_s=env.times_s, values=hz, units="hz")
    events = energy_threshold_events(env, threshold_db=-30.0, gates=voiced, f0=f0)
    assert [e.time_s for e in events] == pytest.approx([0.8])


def test_energy_threshold_refuses_a_nan_threshold():
    with pytest.raises(ValueError, match="threshold_db"):
        energy_threshold_events(_envelope(), threshold_db=math.nan, gates=OFF)


# --- onsets -----------------------------------------------------------------


def test_onsets_drop_clicks_and_respect_spacing_and_the_energy_floor():
    segments = [
        Segment(0.0, 0.4, "onset", label="a"),
        Segment(0.4, 0.42, "onset", label="click"),
        Segment(0.42, 0.9, "onset", label="b"),
        Segment(0.9, 1.5, "onset", label="quiet"),
    ]
    energy = FeatureStream("energy", times_s=[0.0, 0.4, 0.42, 0.9], values=[-20.0, -20.0, -20.0, -50.0], units="dbfs")
    gates = Gates(voiced_only=False, energy_floor_db=-40.0, dwell_s=0.05, min_spacing_s=0.0)
    events = onset_events(segments, gates=gates, energy=energy)
    assert [e.payload["label"] for e in events] == ["a", "b"]
    assert events[0].kind == "onset" and events[0].payload["energy_db"] == -20.0
    assert events[1].payload["duration_s"] == pytest.approx(0.48)

    spaced = Gates(voiced_only=False, energy_floor_db=-40.0, dwell_s=0.05, min_spacing_s=0.5)
    assert [e.payload["label"] for e in onset_events(segments, gates=spaced, energy=energy)] == ["a"]
    assert onset_events(segments, gates=OFF) != [] and onset_events([], gates=OFF) == []


def test_onsets_under_voiced_only_read_voicing_at_the_start():
    segments = [Segment(0.0, 0.3, "onset"), Segment(0.5, 0.8, "onset")]
    f0 = FeatureStream("f0", times_s=[0.0, 0.5], values=[np.nan, 196.0], units="hz")
    voiced = Gates(voiced_only=True, energy_floor_db=-math.inf, dwell_s=0.0, min_spacing_s=0.0)
    events = onset_events(segments, gates=voiced, f0=f0)
    assert [e.time_s for e in events] == [0.5]
    assert events[0].payload["hz"] == 196.0


# --- beats and the grid -----------------------------------------------------


def test_events_map_to_beats_and_keep_their_seconds():
    events = [FeatureEvent(0.25, "scale_tone", {"midi": 60}), FeatureEvent(1.0, "onset")]
    mapped = events_to_beats(events, _ConstantTempo())
    assert [e.beat for e in mapped] == [8.5, 10.0]
    assert [e.time_s for e in mapped] == [0.25, 1.0]
    assert mapped[0].payload == {"midi": 60}
    assert events[0].beat is None  # the originals are untouched


@pytest.mark.parametrize("beat,grid,expected", [
    (8.3, 0.5, 8.5),
    (8.5, 0.5, 8.5),          # already on the grid: no delay
    (8.5000000001, 0.5, 8.5),  # map noise past a grid line is still on it
    (8.51, 0.5, 9.0),
    (0.0, 0.25, 0.0),
    (7.1, 1.0, 8.0),
])
def test_grid_delay_snaps_to_the_next_grid_position(beat, grid, expected):
    assert grid_delay(beat, grid) == pytest.approx(expected)


def test_grid_delay_refuses_a_degenerate_grid_or_beat():
    with pytest.raises(ValueError, match="grid_beats"):
        grid_delay(8.3, 0.0)
    with pytest.raises(ValueError, match="event_beat"):
        grid_delay(math.nan, 0.5)
