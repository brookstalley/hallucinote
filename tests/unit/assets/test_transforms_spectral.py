"""Carve and vocode as recipe steps: the reference is carved, and it is in the address.

The score lives in a real song DB, the target is synthesized, and every
attenuation is read off the whole-signal spectrum around a tone — so the
assertions are about what the step does to a sample, not how a field is built.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from hallucinote.assets import derive
from hallucinote.assets.derived import DerivedRecord, address, canonical_json, sha256_file
from hallucinote.assets.transforms_spectral import carve, vocode
from hallucinote.assets.types import Source, Transform
from hallucinote.audio.io import load_capture
from hallucinote.audio.section import TempoSegment
from hallucinote.db import init_db, mutations as M
from hallucinote.features.beatmap import beat_map_for_placement
from hallucinote.spectral.schedule import constant_schedule
from hallucinote.spectral.types import MaskParams, Polarity
from tests.unit.audio.fixtures import SAMPLE_RATE, sine

SR = SAMPLE_RATE
BPM = 120.0
BEATS = 4.0
DURATION_S = BEATS * 60.0 / BPM
A4 = 69
A1 = 33  # 55 Hz: below the knee where a 2048-point window cannot place a semitone
DEPTH_DB = 12.0


# --- fixtures ---------------------------------------------------------------


def _song(tmp_path: Path):
    conn = init_db(tmp_path / "carve-song.db")
    sid = str(M.create_song(conn, name="carve-song", key="C"))
    M.add_tempo_point(conn, song_id=sid, start_bar=1.0, tempo_bpm=BPM)
    M.add_time_signature_point(conn, song_id=sid, start_bar=1.0, numerator=4, denominator=4)
    return conn, sid


def _note(pitch: int, start: float = 0.0, dur: float = BEATS) -> dict:
    return {"pitch": pitch, "start_beats": start, "duration_beats": dur, "velocity": 100, "mute": 0}


def _track(conn, sid, *, index: int, name: str, notes: list[dict]):
    tid = str(M.create_track(conn, song_id=sid, track_index=index, name=name))
    cid = str(M.create_clip(conn, track_id=tid, slot=1, length_beats=BEATS, name=f"{name}-clip"))
    M.insert_notes(conn, clip_id=cid, notes=notes)
    M.add_arrangement_clip(conn, song_id=sid, track_id=tid, clip_id=cid, start_bar=1.0, end_bar=2.0)
    return tid, cid


def _write_source(song_dir: Path, name: str, audio: np.ndarray, sr: int = SR) -> Source:
    path = song_dir / "assets" / "sources" / f"{name}.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, sr, subtype="FLOAT")
    return Source(
        name=name, path=path, checksum=sha256_file(path),
        sample_rate=sr, channels=audio.shape[1], duration_s=audio.shape[0] / sr,
    )


def _target(*tones_hz: float, sr: int = SR) -> np.ndarray:
    mix = sum(sine(hz, DURATION_S, amplitude=0.3, sr=sr) for hz in tones_hz)
    return np.asarray(mix, dtype=np.float32)


def _clock(n_samples: int, *, start_beat: float = 0.0, sr: int = SR):
    return beat_map_for_placement(
        [TempoSegment(0.0, BPM)], start_beat=start_beat, n_samples=n_samples, sample_rate=sr
    )


def _params(
    polarity: Polarity = "carve",
    *,
    harmonic_depth: int = 1,
    notch_width_cents: float | np.ndarray = 200.0,
    depth_db: float | np.ndarray = DEPTH_DB,
    smoothing_s: float = 0.0,
) -> MaskParams:
    return MaskParams(
        polarity=polarity, harmonic_depth=harmonic_depth, notch_width_cents=notch_width_cents,
        depth_db=depth_db, smoothing_s=smoothing_s,
    )


def _band_db(audio: np.ndarray, center_hz: float, half_width_hz: float = 30.0) -> float:
    x = np.asarray(audio, dtype=np.float64)[:, 0]
    spec = np.abs(np.fft.rfft(x * np.hanning(x.shape[0]))) ** 2
    freqs = np.fft.rfftfreq(x.shape[0], d=1.0 / SR)
    band = (freqs >= center_hz - half_width_hz) & (freqs <= center_hz + half_width_hz)
    return 10.0 * np.log10(spec[band].sum() + 1e-30)


def _attenuation_db(before: np.ndarray, after: np.ndarray, hz: float) -> float:
    return _band_db(before, hz) - _band_db(after, hz)


def _read(path: Path) -> np.ndarray:
    audio, _ = sf.read(str(path), dtype="float32", always_2d=True)
    return audio


@pytest.fixture
def scored(tmp_path: Path):
    """A song whose one track plays A4 for four beats, and a 440 + 2000 Hz target placed at beat 0."""
    conn, sid = _song(tmp_path)
    tid, cid = _track(conn, sid, index=1, name="lead", notes=[_note(A4)])
    target = _target(440.0, 2000.0)
    src = _write_source(tmp_path, "line", target)
    schedule = constant_schedule(0.0, BEATS, [("track", tid)])
    return dict(
        song_dir=tmp_path, conn=conn, sid=sid, tid=tid, cid=cid, src=src, target=target,
        schedule=schedule, clock=_clock(target.shape[0]),
    )


# --- the operation through the cache ----------------------------------------


def test_carve_attenuates_the_referenced_partial_and_leaves_the_rest(scored):
    step = carve(scored["schedule"], _params("carve"), conn=scored["conn"], beat_map=scored["clock"])
    d = derive(scored["src"], step, song_dir=scored["song_dir"])
    out = _read(d.path)

    assert out.shape == scored["target"].shape
    assert _attenuation_db(scored["target"], out, 440.0) == pytest.approx(DEPTH_DB, abs=1.5)
    assert abs(_attenuation_db(scored["target"], out, 2000.0)) < 1.0


def test_vocode_keeps_the_referenced_partial_and_attenuates_the_rest(scored):
    step = vocode(scored["schedule"], _params("vocode"), conn=scored["conn"], beat_map=scored["clock"])
    d = derive(scored["src"], step, song_dir=scored["song_dir"])
    out = _read(d.path)

    assert _attenuation_db(scored["target"], out, 2000.0) == pytest.approx(DEPTH_DB, abs=1.5)
    assert abs(_attenuation_db(scored["target"], out, 440.0)) < 1.0


def test_the_derived_record_says_what_the_file_was_carved_against(scored):
    step = carve(scored["schedule"], _params("carve"), conn=scored["conn"], beat_map=scored["clock"])
    d = derive(scored["src"], step, song_dir=scored["song_dir"])
    record = DerivedRecord.read(d.record_path)

    assert step.fingerprint().startswith("symbolic:")
    assert d.reference_fingerprint == record.reference_fingerprint == step.fingerprint()
    assert record.chain[0]["kind"] == "carve"
    assert record.chain[0]["params"]["fingerprint"] == step.fingerprint()
    assert record.chain[0]["params"]["field"] == "symbolic"
    assert record.recomputed_address() == d.address
    # A caller that resolved the reference itself is believed over the chain.
    explicit = derive(scored["src"], step, song_dir=scored["song_dir"], reference_fingerprint="mine")
    assert explicit.reference_fingerprint == "mine" and explicit.address != d.address


def test_changing_a_note_in_the_referenced_clip_changes_the_address(scored):
    conn, src = scored["conn"], scored["src"]
    step = carve(scored["schedule"], _params("carve"), conn=conn, beat_map=scored["clock"])
    base = address(src, [step])
    assert address(src, [step]) == base

    # A note on a track the schedule does not name is not the reference.
    _track(conn, scored["sid"], index=2, name="other", notes=[_note(A4 - 12)])
    assert address(src, [step]) == base

    M.insert_notes(conn, clip_id=scored["cid"], notes=[_note(A4 + 7, 2.0, 1.0)])
    assert address(src, [step]) != base


def test_moving_the_sample_on_the_songs_clock_changes_the_address(scored):
    n = scored["target"].shape[0]
    at_zero = carve(scored["schedule"], _params("carve"), conn=scored["conn"], beat_map=_clock(n))
    at_one = carve(scored["schedule"], _params("carve"), conn=scored["conn"], beat_map=_clock(n, start_beat=1.0))

    assert at_zero.fingerprint() == at_one.fingerprint()
    assert at_zero.params()["clock"] != at_one.params()["clock"]
    assert address(scored["src"], [at_zero]) != address(scored["src"], [at_one])


def test_a_spectral_step_is_a_transform_whose_params_are_plain_values(scored):
    step = carve(
        scored["schedule"], _params("carve", depth_db=np.array([12.0, 6.0]), smoothing_s=0.1),
        conn=scored["conn"], beat_map=scored["clock"], n_fft=4096, hop=1024,
    )
    assert isinstance(step, Transform)
    params = step.params()
    assert set(params) == {
        "field", "fingerprint", "schedule", "clock", "harmonic_depth", "notch_width_cents",
        "depth_db", "smoothing_s", "n_fft", "hop", "stem_gains", "tempo_segments",
    }
    assert params["depth_db"] == [12.0, 6.0]
    assert params["n_fft"] == 4096 and params["hop"] == 1024
    assert params["clock"][0] == [0.0, 0.0] and params["clock"][-1] == [BEATS, DURATION_S]
    assert json.loads(canonical_json(params)) == params


# --- refusals ----------------------------------------------------------------


def test_measured_without_a_capture_refuses(scored):
    with pytest.raises(ValueError, match="capture="):
        carve(scored["schedule"], _params("carve"), field="measured",
              conn=scored["conn"], beat_map=scored["clock"])


def test_symbolic_with_a_capture_refuses_rather_than_ignoring_it(scored, tmp_path):
    capture = load_capture(_write_capture(tmp_path / "cap", stems={"track:1": _target(440.0)}))
    with pytest.raises(ValueError, match="never substituted"):
        carve(scored["schedule"], _params("carve"), capture=capture,
              conn=scored["conn"], beat_map=scored["clock"])
    with pytest.raises(ValueError, match="stem_gains"):
        carve(scored["schedule"], _params("carve"), stem_gains={"track:1": 0.5},
              conn=scored["conn"], beat_map=scored["clock"])


def test_the_step_decides_the_polarity(scored):
    with pytest.raises(ValueError, match="polarity='vocode'"):
        carve(scored["schedule"], _params("vocode"), conn=scored["conn"], beat_map=scored["clock"])
    with pytest.raises(ValueError, match="polarity='carve'"):
        vocode(scored["schedule"], _params("carve"), conn=scored["conn"], beat_map=scored["clock"])


def test_the_score_and_the_clock_are_required(scored):
    with pytest.raises(ValueError, match="conn="):
        carve(scored["schedule"], _params("carve"), beat_map=scored["clock"])
    with pytest.raises(ValueError, match="beat_map="):
        carve(scored["schedule"], _params("carve"), conn=scored["conn"])
    with pytest.raises(ValueError, match="'symbolic'"):
        carve(scored["schedule"], _params("carve"), field="rendered",  # type: ignore[arg-type]
              conn=scored["conn"], beat_map=scored["clock"])


def test_a_reference_that_sounds_nothing_over_the_target_refuses(scored):
    silent = constant_schedule(8.0, 12.0, [("track", scored["tid"])])
    step = carve(silent, _params("carve"), conn=scored["conn"], beat_map=scored["clock"])
    with pytest.raises(ValueError, match="sounds nothing"):
        derive(scored["src"], step, song_dir=scored["song_dir"])
    assert list((scored["song_dir"] / "assets" / "derived").glob("*.json")) == []


# --- the measured route ------------------------------------------------------


def _write_capture(captures_dir: Path, *, stems: dict[str, np.ndarray], sr: int = SR) -> Path:
    captures_dir.mkdir(parents=True, exist_ok=True)

    def write(surface_id: str, audio: np.ndarray) -> dict:
        filename = surface_id.replace(":", "-") + ".wav"
        sf.write(str(captures_dir / filename), audio, sr, subtype="FLOAT")
        return {
            "track_id": surface_id,
            "surface_name": surface_id.replace(":", "_"),
            "surface_index": int(surface_id.split(":")[-1]) if ":" in surface_id else 0,
            "device_index": 1,
            "osc_port": 11020,
            "filename": filename,
            "absolute_path": str(captures_dir / filename),
        }

    master = np.sum(np.stack(list(stems.values())), axis=0).astype(np.float32)
    manifest = {
        "schema_version": "1",
        "captured_at": "20260909T120000Z",
        "song_slug": "carve-song",
        "start_at_beat": 0.0,
        "stop_at_beat": BEATS,
        "ring_out_beats": 0.0,
        "analyzer_signature": "hallucinote-analyzer-v1",
        "tracks": [write(k, v) for k, v in stems.items()],
        "returns": [],
        "master": write("master", master),
    }
    path = captures_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def test_carve_against_a_capture_attenuates_and_fingerprints_the_take(scored, tmp_path):
    capture = load_capture(_write_capture(tmp_path / "cap", stems={"track:1": _target(440.0)}))
    step = carve(
        scored["schedule"], _params("carve"), field="measured", capture=capture,
        conn=scored["conn"], beat_map=scored["clock"],
    )
    d = derive(scored["src"], step, song_dir=scored["song_dir"])
    out = _read(d.path)

    assert _attenuation_db(scored["target"], out, 440.0) == pytest.approx(DEPTH_DB, abs=2.0)
    assert abs(_attenuation_db(scored["target"], out, 2000.0)) < 1.0
    assert step.fingerprint().startswith("measured:20260909T120000Z:")
    assert d.reference_fingerprint == step.fingerprint()
    assert DerivedRecord.read(d.record_path).chain[0]["params"]["field"] == "measured"


def test_a_capture_at_another_rate_refuses_rather_than_resampling(scored, tmp_path):
    capture = load_capture(_write_capture(tmp_path / "cap", stems={"track:1": _target(440.0)}))
    slow = _write_source(tmp_path, "slow", _target(440.0, 2000.0, sr=44_100), sr=44_100)
    step = carve(
        scored["schedule"], _params("carve"), field="measured", capture=capture,
        conn=scored["conn"], beat_map=_clock(int(slow.duration_s * 44_100), sr=44_100),
    )
    with pytest.raises(ValueError, match="44100 Hz"):
        derive(slow, step, song_dir=scored["song_dir"])


# --- precision is reported, never implied ------------------------------------


def test_a_bass_carve_reports_the_width_it_achieved(tmp_path, caplog):
    conn, sid = _song(tmp_path)
    tid, _ = _track(conn, sid, index=1, name="bass", notes=[_note(A1)])
    target = _target(55.0, 2000.0)
    src = _write_source(tmp_path, "low", target)
    step = carve(
        constant_schedule(0.0, BEATS, [("track", tid)]), _params("carve", notch_width_cents=100.0),
        conn=conn, beat_map=_clock(target.shape[0]),
    )
    mask = step.mask_for(target.shape[0], SR)
    assert mask.precision is not None
    assert mask.precision.lowest_hz == pytest.approx(55.0, abs=mask.resolution.bin_hz / 2)
    assert not mask.precision.met
    assert mask.precision.achieved_cents > 100.0
    assert "cents" in mask.precision.describe()

    with caplog.at_level(logging.WARNING, logger="hallucinote.assets.transforms_spectral"):
        d = derive(src, step, song_dir=tmp_path)
    assert any("cents" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)
    out = _read(d.path)
    # The notch is a base bin wide, so the partial is reduced — by less than the depth asked for.
    assert 2.0 < _attenuation_db(target, out, 55.0) <= DEPTH_DB + 1.0
    assert abs(_attenuation_db(target, out, 2000.0)) < 1.0
