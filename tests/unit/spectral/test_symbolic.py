"""The symbolic field: the score's partials, exactly, and nowhere else."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.spectral.schedule import constant_schedule, schedule_from_spans
from hallucinote.spectral.symbolic import (
    bar_to_beat_for_song,
    pitch_hz,
    sounding_notes,
    symbolic_axes,
    symbolic_field,
)
from hallucinote.spectral.types import ResolutionReport
from hallucinote.tuning.model import TuningData

A4 = 69
A3 = 57


class _ConstantTempo:
    """A BeatMap at one tempo: second 0 is ``start_beat``."""

    def __init__(self, bpm: float = 120.0, start_beat: float = 0.0) -> None:
        self.bpm = bpm
        self.start_beat = start_beat

    def seconds_to_beats(self, seconds: float) -> float:
        return self.start_beat + seconds * self.bpm / 60.0

    def beats_to_seconds(self, beats: float) -> float:
        return (beats - self.start_beat) * 60.0 / self.bpm


def _song(tmp_path: Path, name: str = "sym-song"):
    conn = init_db(tmp_path / f"{name}.db")
    sid = str(M.create_song(conn, name=name, key="C"))
    M.add_tempo_point(conn, song_id=sid, start_bar=1.0, tempo_bpm=120.0)
    M.add_time_signature_point(conn, song_id=sid, start_bar=1.0, numerator=4, denominator=4)
    return conn, sid


def _track(conn, sid, *, index: int, name: str, notes, clip_len: float = 4.0,
           bar: float = 1.0, bars: float = 1.0):
    tid = str(M.create_track(conn, song_id=sid, track_index=index, name=name))
    cid = str(M.create_clip(conn, track_id=tid, slot=1, length_beats=clip_len, name=f"{name}-clip"))
    M.insert_notes(conn, clip_id=cid, notes=notes)
    M.add_arrangement_clip(conn, song_id=sid, track_id=tid, clip_id=cid, start_bar=bar, end_bar=bar + bars)
    return tid, cid


def _note(pitch: int, start: float = 0.0, dur: float = 2.0, mute: int = 0):
    return {"pitch": pitch, "start_beats": start, "duration_beats": dur, "velocity": 100, "mute": mute}


def _nearest(freqs: np.ndarray, hz: float) -> int:
    return int(np.argmin(np.abs(freqs - hz)))


RES = ResolutionReport(n_fft=2048, hop=512, sample_rate=44100)


def test_one_note_lights_exactly_its_partials(tmp_path: Path):
    conn, sid = _song(tmp_path)
    tid, _ = _track(conn, sid, index=1, name="lead", notes=[_note(A4, 0.0, 2.0)])
    freqs, times = symbolic_axes(RES, duration_s=2.0)
    field = symbolic_field(
        conn, constant_schedule(0.0, 4.0, [("track", tid)]), _ConstantTempo(),
        freqs_hz=freqs, times_s=times, harmonic_depth=3, resolution=RES,
    )
    assert field.origin == "symbolic"
    assert field.fingerprint.startswith("symbolic:")
    assert field.magnitude.shape == (freqs.size, times.size)
    expected = {_nearest(freqs, 440.0 * k) for k in (1, 2, 3)}
    for j, t in enumerate(times):
        lit = set(np.flatnonzero(field.magnitude[:, j]).tolist())
        if t * 2.0 < 2.0:  # the note sounds for its first two beats
            assert lit == expected, f"frame {j} at {t:.3f}s"
            assert np.all(field.magnitude[sorted(lit), j] == 1.0)
        else:
            assert lit == set(), f"frame {j} at {t:.3f}s should be silent"


def test_nodes_resolve_to_the_tracks_they_sound(tmp_path: Path):
    conn, sid = _song(tmp_path)
    ta, _ = _track(conn, sid, index=1, name="a", notes=[_note(A4)])
    tb, _ = _track(conn, sid, index=2, name="b", notes=[_note(A3)])
    rid = str(M.create_return(conn, song_id=sid, name="verb", position=1))
    M.set_send_level(conn, from_track_id=tb, to_return_id=rid, level=0.5)
    M.set_send_level(conn, from_track_id=ta, to_return_id=rid, level=0.0)

    def pitches(node):
        return sorted(n.pitch for n in sounding_notes(conn, node, song_id=sid, start_beat=0.0, end_beat=4.0))

    assert pitches(("track", ta)) == [A4]
    assert pitches(("master",)) == [A3, A4]
    assert pitches(("minus", ta)) == [A3]
    # A send at level 0 reaches the bus with nothing.
    assert pitches(("return", rid)) == [A3]
    assert pitches(("minus", tb)) == [A4]


def test_partials_above_the_axis_are_not_folded_back(tmp_path: Path):
    conn, sid = _song(tmp_path)
    tid, _ = _track(conn, sid, index=1, name="high", notes=[_note(108)])  # C8, 4186 Hz
    res = ResolutionReport(n_fft=256, hop=64, sample_rate=8000)
    freqs, times = symbolic_axes(res, duration_s=1.0)
    field = symbolic_field(
        conn, constant_schedule(0.0, 4.0, [("track", tid)]), _ConstantTempo(),
        freqs_hz=freqs, times_s=times, harmonic_depth=8, resolution=res,
    )
    assert not np.any(field.magnitude)


def test_placement_moves_the_note_and_mute_silences_it(tmp_path: Path):
    conn, sid = _song(tmp_path)
    moved, _ = _track(conn, sid, index=1, name="moved", notes=[_note(A4, 0.0, 1.0)], bar=2.0)
    muted, _ = _track(conn, sid, index=2, name="muted", notes=[_note(A3, 0.0, 1.0, mute=1)])
    notes = sounding_notes(conn, ("track", moved), song_id=sid, start_beat=0.0, end_beat=8.0)
    assert [(n.start_beat, n.end_beat) for n in notes] == [(4.0, 5.0)]
    assert sounding_notes(conn, ("track", muted), song_id=sid, start_beat=0.0, end_beat=8.0) == []
    assert sounding_notes(conn, ("track", moved), song_id=sid, start_beat=0.0, end_beat=4.0) == []


def test_placement_extent_and_clip_length_both_bound_a_note(tmp_path: Path):
    conn, sid = _song(tmp_path)
    # Half a bar placed (2 beats) of a 4-beat clip: a note at beat 3 never
    # sounds, a note running past beat 2 is cut there.
    tid, _ = _track(
        conn, sid, index=1, name="short",
        notes=[_note(A4, 3.0, 1.0), _note(A3, 1.0, 4.0)], bars=0.5,
    )
    notes = sounding_notes(conn, ("track", tid), song_id=sid, start_beat=0.0, end_beat=8.0)
    assert [(n.pitch, n.start_beat, n.end_beat) for n in notes] == [(A3, 1.0, 2.0)]
    # A placement longer than its clip sounds the clip's length only.
    long_, _ = _track(conn, sid, index=2, name="long", notes=[_note(A4, 0.0, 8.0)], clip_len=2.0, bars=4.0)
    notes = sounding_notes(conn, ("track", long_), song_id=sid, start_beat=0.0, end_beat=64.0)
    assert [(n.start_beat, n.end_beat) for n in notes] == [(0.0, 2.0)]


def _bohlen_pierce() -> TuningData:
    period = 1901.955
    return TuningData(
        name="bp", step_count=13, period_cents=period, reference_note=A4,
        step_cents=tuple(period * i / 13 for i in range(1, 14)),
    )


def test_pitch_hz_in_12tet_and_under_a_tuning():
    assert pitch_hz(A4) == pytest.approx(440.0)
    assert pitch_hz(A4 + 12) == pytest.approx(880.0)
    bp = _bohlen_pierce()
    assert pitch_hz(A4, bp) == pytest.approx(440.0)
    assert pitch_hz(A4 + 13, bp) == pytest.approx(1320.0, rel=1e-4)   # one tritave up
    assert pitch_hz(A4 - 13, bp) == pytest.approx(440.0 / 3.0, rel=1e-4)
    assert pitch_hz(A4 + 1, bp) == pytest.approx(440.0 * 2 ** (1901.955 / 13 / 1200), rel=1e-6)


def test_a_tuned_song_needs_its_tuning_passed_in_and_it_moves_the_partials(tmp_path: Path):
    """The core never imports the tuning bolt-on, so the caller hands the
    song's TuningData in; a tuned song read without it refuses rather than
    quietly sounding in 12-TET."""
    conn, sid = _song(tmp_path)
    tid, _ = _track(conn, sid, index=1, name="bp", notes=[_note(A4 + 13)])
    bp = _bohlen_pierce()
    M.set_song_tuning(conn, song_id=sid, tuning_ref="tunings/bp.ascl", tuning_data=bp.to_blob())
    freqs, times = symbolic_axes(RES, duration_s=0.5)
    sched = constant_schedule(0.0, 4.0, [("track", tid)])
    with pytest.raises(ValueError, match=r"alternate tuning.*load_song_tuning"):
        symbolic_field(conn, sched, _ConstantTempo(), freqs_hz=freqs, times_s=times,
                       harmonic_depth=1, resolution=RES)
    tuned = symbolic_field(conn, sched, _ConstantTempo(), freqs_hz=freqs, times_s=times,
                           harmonic_depth=1, resolution=RES, tuning=bp)
    assert tuned.magnitude[_nearest(freqs, 1320.0), 0] == 1.0
    assert tuned.magnitude[_nearest(freqs, pitch_hz(A4 + 13)), 0] == 0.0
    # The tuning is part of what was read, so it is in the fingerprint.
    untuned_song, sid2 = _song(tmp_path, name="other")
    tid2, _ = _track(untuned_song, sid2, index=1, name="bp", notes=[_note(A4 + 13)])
    plain = symbolic_field(untuned_song, constant_schedule(0.0, 4.0, [("track", tid2)]),
                           _ConstantTempo(), freqs_hz=freqs, times_s=times,
                           harmonic_depth=1, resolution=RES)
    assert plain.fingerprint != tuned.fingerprint


def test_fingerprint_follows_notes_placements_schedule_and_nothing_else(tmp_path: Path):
    conn, sid = _song(tmp_path)
    tid, cid = _track(conn, sid, index=1, name="lead", notes=[_note(A4)])
    freqs, times = symbolic_axes(RES, duration_s=0.5)
    sched = constant_schedule(0.0, 4.0, [("track", tid)])

    def fp(schedule=sched, depth=1):
        return symbolic_field(conn, schedule, _ConstantTempo(), freqs_hz=freqs, times_s=times,
                              harmonic_depth=depth, resolution=RES).fingerprint

    base = fp()
    assert fp() == base
    assert fp(depth=4) == base  # depth is a mask parameter, not what was read
    assert fp(constant_schedule(0.0, 8.0, [("track", tid)])) != base
    M.insert_notes(conn, clip_id=cid, notes=[_note(A3, 2.0, 1.0)])
    after_note = fp()
    assert after_note != base
    M.add_arrangement_clip(conn, song_id=sid, track_id=tid, clip_id=cid, start_bar=3.0, end_bar=4.0)
    assert fp() != after_note


def test_unknown_nodes_and_ambiguous_songs_refuse(tmp_path: Path):
    conn, sid = _song(tmp_path)
    _track(conn, sid, index=1, name="lead", notes=[_note(A4)])
    freqs, times = symbolic_axes(RES, duration_s=0.5)
    with pytest.raises(ValueError, match="no playing track"):
        symbolic_field(conn, constant_schedule(0.0, 4.0, [("track", "nope")]), _ConstantTempo(),
                       freqs_hz=freqs, times_s=times, harmonic_depth=1, resolution=RES)
    with pytest.raises(ValueError, match="no return"):
        symbolic_field(conn, constant_schedule(0.0, 4.0, [("return", "nope")]), _ConstantTempo(),
                       freqs_hz=freqs, times_s=times, harmonic_depth=1, resolution=RES)
    M.create_song(conn, name="second", key="C")
    with pytest.raises(ValueError, match="song_id"):
        symbolic_field(conn, constant_schedule(0.0, 4.0, [("master",)]), _ConstantTempo(),
                       freqs_hz=freqs, times_s=times, harmonic_depth=1, resolution=RES)
    with pytest.raises(ValueError, match="harmonic_depth"):
        symbolic_field(conn, constant_schedule(0.0, 4.0, [("master",)]), _ConstantTempo(),
                       freqs_hz=freqs, times_s=times, harmonic_depth=0, resolution=RES, song_id=sid)


def test_schedule_gaps_and_spans_pick_nodes_per_beat(tmp_path: Path):
    conn, sid = _song(tmp_path)
    ta, _ = _track(conn, sid, index=1, name="a", notes=[_note(A4, 0.0, 4.0)])
    tb, _ = _track(conn, sid, index=2, name="b", notes=[_note(A3, 0.0, 4.0)])
    freqs, times = symbolic_axes(RES, duration_s=2.0)
    sched = schedule_from_spans([(0.0, 1.0, [("track", ta)]), (2.0, 3.0, [("track", tb)])])
    field = symbolic_field(conn, sched, _ConstantTempo(), freqs_hz=freqs, times_s=times,
                           harmonic_depth=1, resolution=RES)
    a_bin, b_bin = _nearest(freqs, 440.0), _nearest(freqs, 220.0)
    beats = times * 2.0
    assert np.all(field.magnitude[a_bin, beats < 1.0] == 1.0)
    assert not np.any(field.magnitude[b_bin, beats < 1.0])
    assert not np.any(field.magnitude[:, (beats >= 1.0) & (beats < 2.0)])
    assert np.all(field.magnitude[b_bin, (beats >= 2.0) & (beats < 3.0)] == 1.0)
    assert not np.any(field.magnitude[:, beats >= 3.0])


def test_bar_ruler_walks_the_meter_map(tmp_path: Path):
    conn, sid = _song(tmp_path)
    M.add_time_signature_point(conn, song_id=sid, start_bar=3.0, numerator=7, denominator=8)
    ruler = bar_to_beat_for_song(conn, sid)
    assert ruler(1.0) == 0.0
    assert ruler(3.0) == 8.0
    assert ruler(4.0) == pytest.approx(11.5)


def test_symbolic_axes_match_an_stft_grid():
    freqs, times = symbolic_axes(RES, duration_s=1.0)
    assert freqs.shape == (RES.n_fft // 2 + 1,)
    assert freqs[-1] == pytest.approx(RES.sample_rate / 2)
    assert times[1] - times[0] == pytest.approx(RES.hop / RES.sample_rate)
    assert times[-1] >= 1.0
    with pytest.raises(ValueError, match="duration_s"):
        symbolic_axes(RES, duration_s=0.0)
