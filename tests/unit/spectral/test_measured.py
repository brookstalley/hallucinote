"""The measured field: a capture's surfaces, summed the way the stem-sum lens sums,
aligned by inheritance, and refusing wherever that inheritance breaks."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from hallucinote.audio.codeversion import disk_signature
from hallucinote.audio.io import load_capture
from hallucinote.db import init_db, mutations as M
from hallucinote.spectral.measured import (
    MAX_STOP_RAMP_S,
    measured_field,
    surface_id_for_node,
)
from hallucinote.spectral.schedule import constant_schedule, schedule_from_spans
from tests.unit.audio.fixtures import sine

SR = 48_000
BPM = 120.0
BEATS = 4.0
DURATION_S = BEATS * 60.0 / BPM


class _ConstantTempo:
    def __init__(self, bpm: float = BPM, start_beat: float = 0.0) -> None:
        self.bpm = bpm
        self.start_beat = start_beat

    def seconds_to_beats(self, seconds: float) -> float:
        return self.start_beat + seconds * self.bpm / 60.0

    def beats_to_seconds(self, beats: float) -> float:
        return (beats - self.start_beat) * 60.0 / self.bpm


def _entry(surface_id: str, filename: str, captures_dir: Path) -> dict:
    return {
        "track_id": surface_id,
        "surface_name": surface_id.replace(":", "_"),
        "surface_index": int(surface_id.split(":")[-1]) if ":" in surface_id else 0,
        "device_index": 1,
        "osc_port": 11020,
        "filename": filename,
        "absolute_path": str(captures_dir / filename),
    }


def _write_capture(
    captures_dir: Path,
    *,
    stems: dict[str, np.ndarray],
    master: np.ndarray,
    returns: dict[str, np.ndarray] | None = None,
    start_at_beat: float = 0.0,
    stop_at_beat: float = BEATS,
    ring_out_beats: float = 0.0,
    captured_at: str = "20260909T120000Z",
) -> Path:
    captures_dir.mkdir(parents=True, exist_ok=True)

    def write(surface_id: str, audio: np.ndarray) -> dict:
        filename = surface_id.replace(":", "-") + ".wav"
        sf.write(str(captures_dir / filename), audio, SR, subtype="FLOAT")
        return _entry(surface_id, filename, captures_dir)

    manifest = {
        "schema_version": "1",
        "captured_at": captured_at,
        "song_slug": "measured-song",
        "start_at_beat": start_at_beat,
        "stop_at_beat": stop_at_beat,
        "ring_out_beats": ring_out_beats,
        "analyzer_signature": "hallucinote-analyzer-v1",
        "tracks": [write(k, v) for k, v in stems.items()],
        "returns": [write(k, v) for k, v in (returns or {}).items()],
        "master": write("master", master),
    }
    path = captures_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def _song(tmp_path: Path):
    conn = init_db(tmp_path / "measured.db")
    sid = str(M.create_song(conn, name="measured-song", key="C"))
    M.add_tempo_point(conn, song_id=sid, start_bar=1.0, tempo_bpm=BPM)
    ids = [
        str(M.create_track(conn, song_id=sid, track_index=i, name=name))
        for i, name in ((1, "a"), (2, "b"), (3, "c"))
    ]
    return conn, sid, ids


def _three_stems():
    a = sine(220.0, DURATION_S, sr=SR)
    b = sine(440.0, DURATION_S, sr=SR)
    c = sine(880.0, DURATION_S, sr=SR)
    return a, b, c


def _nearest(freqs: np.ndarray, hz: float) -> int:
    return int(np.argmin(np.abs(freqs - hz)))


def _interior(field, frames=None) -> np.ndarray:
    """Frames a whole window away from the region's edges, where a truncated
    sine's rectangular-edge leakage cannot reach — the field's honest content."""
    edge = field.resolution.n_fft // field.resolution.hop + 1
    mask = np.zeros(field.times_s.size, dtype=bool)
    mask[edge:-edge] = True
    return mask if frames is None else (mask & frames)


def _peak_ratio(field, hz: float) -> float:
    """Energy at a pitch's bin relative to the field's loudest bin, interior frames."""
    inner = _interior(field)
    return float(field.magnitude[_nearest(field.freqs_hz, hz), inner].max() / field.magnitude[:, inner].max())


def test_minus_node_is_the_sum_of_the_other_stems(tmp_path: Path):
    conn, sid, (ta, tb, tc) = _song(tmp_path)
    a, b, c = _three_stems()
    manifest = _write_capture(
        tmp_path / "cap", stems={"track:1": a, "track:2": b, "track:3": c}, master=a + b + c
    )
    capture = load_capture(manifest)
    bm = _ConstantTempo()
    minus = measured_field(capture, constant_schedule(0.0, BEATS, [("minus", ta)]), bm, conn=conn)
    others = measured_field(
        capture, constant_schedule(0.0, BEATS, [("track", tb), ("track", tc)]), bm, conn=conn
    )
    assert minus.origin == "measured"
    np.testing.assert_allclose(minus.magnitude, others.magnitude, rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(minus.times_s, others.times_s)
    assert _peak_ratio(minus, 440.0) > 0.5
    assert _peak_ratio(minus, 880.0) > 0.5
    assert _peak_ratio(minus, 220.0) < 1e-3


def test_track_master_and_return_nodes_are_their_surfaces(tmp_path: Path):
    conn, sid, (ta, tb, tc) = _song(tmp_path)
    rid = str(M.create_return(conn, song_id=sid, name="verb", position=1))
    a, b, c = _three_stems()
    verb = sine(660.0, DURATION_S, sr=SR)
    manifest = _write_capture(
        tmp_path / "cap", stems={"track:1": a, "track:2": b, "track:3": c},
        returns={"return:1": verb}, master=a + b + c + verb,
    )
    capture = load_capture(manifest)
    bm = _ConstantTempo()
    track = measured_field(capture, constant_schedule(0.0, BEATS, [("track", ta)]), bm, conn=conn)
    assert _peak_ratio(track, 220.0) == 1.0
    assert _peak_ratio(track, 440.0) < 1e-3
    ret = measured_field(capture, constant_schedule(0.0, BEATS, [("return", rid)]), bm, conn=conn)
    assert _peak_ratio(ret, 660.0) == 1.0
    master = measured_field(capture, constant_schedule(0.0, BEATS, [("master",)]), bm, conn=conn)
    for hz in (220.0, 440.0, 660.0, 880.0):
        assert _peak_ratio(master, hz) > 0.5
    # The mix minus a track keeps the returns — a send tail is part of the mix.
    minus = measured_field(capture, constant_schedule(0.0, BEATS, [("minus", ta)]), bm, conn=conn)
    assert _peak_ratio(minus, 660.0) > 0.5
    assert _peak_ratio(minus, 220.0) < 1e-3


def test_surface_ids_follow_track_index_and_return_position(tmp_path: Path):
    conn, sid, (ta, tb, tc) = _song(tmp_path)
    rid = str(M.create_return(conn, song_id=sid, name="verb", position=2))
    assert surface_id_for_node(conn, ("track", tc)) == "track:3"
    assert surface_id_for_node(conn, ("return", rid)) == "return:2"
    assert surface_id_for_node(conn, ("master",)) == "master"
    with pytest.raises(ValueError, match="no track"):
        surface_id_for_node(conn, ("track", "nope"))


def test_times_are_labelled_on_the_callers_clock(tmp_path: Path):
    conn, sid, (ta, _, _) = _song(tmp_path)
    a, b, c = _three_stems()
    capture = load_capture(_write_capture(tmp_path / "cap", stems={"track:1": a}, master=a))
    # The capture ran at 120 bpm; the caller's clock says 60 bpm from beat 1,
    # so a frame at capture-second s sits at beat 2s and lands at 2s - 1.
    field = measured_field(
        capture, constant_schedule(0.0, BEATS, [("track", ta)]),
        _ConstantTempo(bpm=60.0, start_beat=1.0), conn=conn, n_fft=1024, hop=256,
    )
    frames = np.arange(field.times_s.size)
    np.testing.assert_allclose(field.times_s, 2.0 * frames * 256 / SR - 1.0, atol=1e-6)
    assert field.resolution.n_fft == 1024 and field.resolution.sample_rate == SR
    assert field.freqs_hz.shape == (513,)


def test_gaps_between_spans_carry_no_energy(tmp_path: Path):
    conn, sid, (ta, tb, _) = _song(tmp_path)
    a, b, c = _three_stems()
    capture = load_capture(
        _write_capture(tmp_path / "cap", stems={"track:1": a, "track:2": b}, master=a + b)
    )
    sched = schedule_from_spans([(0.0, 1.0, [("track", ta)]), (3.0, 4.0, [("track", tb)])])
    field = measured_field(capture, sched, _ConstantTempo(), conn=conn)
    beats = field.times_s * 2.0
    # Inside the gap, clear of a window's reach from either boundary.
    gap = (beats > 1.2) & (beats < 2.8)
    assert np.any(gap)
    assert not np.any(field.magnitude[:, gap])
    first = _interior(field, (beats > 0.2) & (beats < 0.8))
    last = _interior(field, (beats > 3.2) & (beats < 3.8))
    assert np.any(first) and np.any(last)
    loudest = field.magnitude[:, _interior(field)].max()
    assert field.magnitude[_nearest(field.freqs_hz, 220.0), first].min() > 0.5 * loudest
    assert field.magnitude[_nearest(field.freqs_hz, 440.0), first].max() < 1e-3 * loudest
    assert field.magnitude[_nearest(field.freqs_hz, 440.0), last].min() > 0.5 * loudest
    assert field.magnitude[_nearest(field.freqs_hz, 220.0), last].max() < 1e-3 * loudest


def test_stem_gains_scale_the_reference(tmp_path: Path):
    conn, sid, (ta, _, _) = _song(tmp_path)
    a, _, _ = _three_stems()
    capture = load_capture(_write_capture(tmp_path / "cap", stems={"track:1": a}, master=a))
    sched = constant_schedule(0.0, BEATS, [("track", ta)])
    unity = measured_field(capture, sched, _ConstantTempo(), conn=conn)
    half = measured_field(capture, sched, _ConstantTempo(), conn=conn, stem_gains={"track:1": 0.5})
    np.testing.assert_allclose(half.magnitude, 0.5 * unity.magnitude, rtol=1e-5, atol=1e-7)


def test_fingerprint_names_the_take_the_code_and_the_schedule(tmp_path: Path):
    conn, sid, (ta, _, _) = _song(tmp_path)
    a, _, _ = _three_stems()
    capture = load_capture(
        _write_capture(tmp_path / "cap", stems={"track:1": a}, master=a, captured_at="20260909T130000Z")
    )
    one = measured_field(capture, constant_schedule(0.0, 2.0, [("track", ta)]), _ConstantTempo(), conn=conn)
    two = measured_field(capture, constant_schedule(0.0, 4.0, [("track", ta)]), _ConstantTempo(), conn=conn)
    assert one.fingerprint.startswith(f"measured:20260909T130000Z:{disk_signature()}:")
    assert one.fingerprint != two.fingerprint


# --------------------------------------------------------------------------- #
# refusals — R3.6: never approximate an alignment
# --------------------------------------------------------------------------- #

def test_node_without_a_surface_refuses(tmp_path: Path):
    conn, sid, (ta, tb, tc) = _song(tmp_path)
    a, b, _ = _three_stems()
    capture = load_capture(
        _write_capture(tmp_path / "cap", stems={"track:1": a, "track:2": b}, master=a + b)
    )
    with pytest.raises(ValueError, match="'track:3'.*does not hold"):
        measured_field(capture, constant_schedule(0.0, BEATS, [("track", tc)]), _ConstantTempo(), conn=conn)
    with pytest.raises(ValueError, match="'track:3'.*does not hold"):
        measured_field(capture, constant_schedule(0.0, BEATS, [("minus", tc)]), _ConstantTempo(), conn=conn)


def test_unaligned_surface_refuses(tmp_path: Path):
    conn, sid, (ta, tb, tc) = _song(tmp_path)
    a, b, _ = _three_stems()
    short = sine(880.0, DURATION_S - MAX_STOP_RAMP_S - 0.5, sr=SR)
    capture = load_capture(
        _write_capture(tmp_path / "cap", stems={"track:1": a, "track:2": b, "track:3": short}, master=a + b)
    )
    with pytest.raises(ValueError, match="'track:3'.*not one aligned take"):
        measured_field(capture, constant_schedule(0.0, BEATS, [("track", ta)]), _ConstantTempo(), conn=conn)


def test_a_stop_ramp_is_trimmed_not_refused(tmp_path: Path):
    conn, sid, (ta, tb, _) = _song(tmp_path)
    a, b, _ = _three_stems()
    ramp = int(0.02 * SR)
    capture = load_capture(
        _write_capture(
            tmp_path / "cap", stems={"track:1": a, "track:2": b[:-ramp]}, master=(a + b)[:-2 * ramp]
        )
    )
    field = measured_field(capture, constant_schedule(0.0, BEATS, [("track", ta)]), _ConstantTempo(), conn=conn)
    assert _peak_ratio(field, 220.0) == 1.0


def test_schedule_outside_the_capture_refuses(tmp_path: Path):
    conn, sid, (ta, _, _) = _song(tmp_path)
    a, _, _ = _three_stems()
    capture = load_capture(_write_capture(tmp_path / "cap", stems={"track:1": a}, master=a))
    with pytest.raises(ValueError, match="never captured"):
        measured_field(capture, constant_schedule(0.0, 8.0, [("track", ta)]), _ConstantTempo(), conn=conn)
    with pytest.raises(ValueError, match="never captured"):
        measured_field(capture, constant_schedule(-1.0, 2.0, [("track", ta)]), _ConstantTempo(), conn=conn)


def test_manifest_without_a_span_refuses(tmp_path: Path):
    conn, sid, (ta, _, _) = _song(tmp_path)
    a, _, _ = _three_stems()
    capture = load_capture(
        _write_capture(tmp_path / "cap", stems={"track:1": a}, master=a, start_at_beat=4.0, stop_at_beat=4.0)
    )
    with pytest.raises(ValueError, match="empty beat span"):
        measured_field(capture, constant_schedule(4.0, 4.5, [("track", ta)]), _ConstantTempo(), conn=conn)


def test_capture_alignment_uses_the_manifests_own_beats(tmp_path: Path):
    """A capture that starts at beat 8 places beat 8 at its first sample."""
    conn, sid, (ta, tb, _) = _song(tmp_path)
    a, b, _ = _three_stems()
    capture = load_capture(
        _write_capture(
            tmp_path / "cap", stems={"track:1": a, "track:2": b}, master=a + b,
            start_at_beat=8.0, stop_at_beat=12.0,
        )
    )
    field = measured_field(
        capture, constant_schedule(8.0, 12.0, [("track", ta)]), _ConstantTempo(start_beat=8.0), conn=conn
    )
    assert field.times_s[0] == pytest.approx(0.0)
    assert field.times_s[-1] == pytest.approx(DURATION_S, abs=0.02)
    with pytest.raises(ValueError, match="never captured"):
        measured_field(capture, constant_schedule(0.0, 4.0, [("track", ta)]), _ConstantTempo(), conn=conn)
