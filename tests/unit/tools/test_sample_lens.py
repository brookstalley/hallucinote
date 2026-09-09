"""tools/sample_lens.py — a line read against bars before a note is written to it.

Covers the reading of a synthesized vibrato line at 92 bpm (phrase count,
pitch centre, its degree in the declared key, phrase lengths in beats), the
neutral rendering and the bar strip, the ``--json`` round trip, the two front
doors (a bare file with ``--bpm``; a song whose manifest, DB placement, tempo
and key the lens reads), and the refusals that keep a gate from defaulting.
The line is synthesized here; no audio file is committed.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from hallucinote.assets import ingest, store
from hallucinote.audio.sample_io import load_sample
from hallucinote.audio.section import TempoSegment
from hallucinote.db import init_db, mutations as M
from hallucinote.features.events import Gates
from hallucinote.tools.sample_lens import (
    DetectorSpec,
    Key,
    Placement,
    bar_strip,
    constant_meter_rows,
    main,
    parse_key,
    read_sample,
    render,
)

SR = 22_050
BPM = 92.0
PHRASE_SECONDS = (1.0, 0.8, 1.2)
GAP_S = 0.4
LEAD_S = 0.3
CENTRE_HZ = 220.0  # A3
GATES = ["--voiced-only", "yes", "--energy-floor", "-40", "--dwell", "0.08", "--spacing", "0.25"]


def _vibrato(hz: float, seconds: float, *, depth: float = 0.03, rate_hz: float = 5.0) -> np.ndarray:
    t = np.arange(int(round(seconds * SR)), dtype=np.float64) / SR
    inst = hz * (1.0 + depth * np.sin(2.0 * np.pi * rate_hz * t))
    phase = 2.0 * np.pi * np.cumsum(inst) / SR
    fade = int(0.02 * SR)
    env = np.ones_like(t)
    env[:fade] = np.linspace(0.0, 1.0, fade)
    env[-fade:] = np.linspace(1.0, 0.0, fade)
    return 0.5 * np.sin(phase) * env


def _line() -> np.ndarray:
    """Three vibrato phrases on A3 with silences between — a sung line's shape."""
    parts = [np.zeros(int(LEAD_S * SR))]
    for i, seconds in enumerate(PHRASE_SECONDS):
        if i:
            parts.append(np.zeros(int(GAP_S * SR)))
        parts.append(_vibrato(CENTRE_HZ, seconds))
    parts.append(np.zeros(int(LEAD_S * SR)))
    return np.concatenate(parts).astype(np.float32)


@pytest.fixture(scope="module")
def line_wav(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("lens") / "line.wav"
    sf.write(str(path), _line(), SR)
    return path


def _read(line_wav: Path, *, key: Key | None, detector: DetectorSpec | None = None, start_beat: float = 0.0):
    return read_sample(
        load_sample(line_wav),
        source_name="line",
        tempo_segments=[TempoSegment(0.0, BPM)],
        meter_rows=constant_meter_rows(4, 4),
        start_beat=start_beat,
        key=key,
        detector=detector,
    )


# --- key ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, tonic, mode_name",
    [
        ("Dm", 2, "Minor"),
        ("C", 0, "Major"),
        ("F# minor", 6, "Minor"),
        ("Bb major", 10, "Major"),
        ("E Dorian", 4, "Dorian"),
        ("a", 9, "Major"),
    ],
)
def test_parse_key_reads_the_forms_a_song_declares(text, tonic, mode_name):
    key = parse_key(text)
    assert (key.tonic_pc, key.mode.name) == (tonic, mode_name)


@pytest.mark.parametrize("text", ["H", "C nonsense", ""])
def test_parse_key_refuses_what_it_cannot_read(text):
    with pytest.raises(ValueError):
        parse_key(text)


def test_key_degrees_count_from_the_tonic_and_non_tones_have_none():
    key = parse_key("Dm")
    assert key.name == "D Minor"
    assert key.degree_of(2) == 1   # D
    assert key.degree_of(9) == 5   # A
    assert key.degree_of(10) == 6  # Bb, the natural minor's sixth
    assert key.degree_of(3) is None  # Eb is not in D minor


# --- the reading -----------------------------------------------------------------


def test_vibrato_line_at_92_bpm_reads_three_phrases_on_an_a3_centre(line_wav):
    reading = _read(line_wav, key=parse_key("Dm"))

    assert len(reading.phrases) == 3
    assert reading.pitch.centre_hz == pytest.approx(CENTRE_HZ, rel=0.01)
    assert reading.pitch.centre_note == "A3"
    assert reading.pitch.key == "D Minor"
    assert reading.pitch.centre_degree == 5
    assert reading.pitch.in_scale_fraction is not None and reading.pitch.in_scale_fraction > 0.9
    assert reading.placement.end_beat == pytest.approx(reading.duration_s * BPM / 60.0, abs=1e-6)
    for phrase, seconds in zip(reading.phrases, PHRASE_SECONDS):
        # The envelope smears each edge by about a frame; the beat length is
        # the seconds length at the tempo, never a second grid.
        assert phrase.length_beats == pytest.approx(phrase.length_s * BPM / 60.0, abs=1e-6)
        assert abs(phrase.length_s - seconds) < 0.15
        assert phrase.centre_note == "A3"
    assert reading.tempo == "92 bpm"
    assert reading.meter == "4/4"


def test_without_a_key_the_centre_is_read_on_its_own(line_wav):
    reading = _read(line_wav, key=None)
    assert reading.pitch.centre_note == "A3"
    assert reading.pitch.key is None
    assert reading.pitch.centre_degree is None
    assert reading.pitch.in_scale_fraction is None


def test_a_centre_off_the_scale_names_its_neighbours(line_wav):
    # A3 is not a tone of B major; the nearest scale tones sit a semitone either side.
    reading = _read(line_wav, key=parse_key("B"))
    assert reading.pitch.centre_degree is None
    assert reading.pitch.nearest_scale_tones == ("G#3", "A#3")


def test_render_reads_as_facts_against_bars_never_a_verdict(line_wav):
    out = render(_read(line_wav, key=parse_key("Dm")))

    assert "sample lens — line" in out
    assert "NOT a verdict" in out
    assert "3 phrase(s)" in out
    assert "implied centre A3" in out
    assert "against D Minor: the centre A3 is degree 5" in out
    assert "bar 1 beat 1.00 → bar 2 beat" in out
    assert "detector: none named" in out
    assert "against bars" in out and "bar   1  " in out and "=" in out
    for verdict in ("should", "wrong", "good", "bad"):
        assert verdict not in out.lower()


def test_scale_tone_fires_are_placed_on_bars_and_land_on_the_grid(line_wav):
    gates = Gates(voiced_only=True, energy_floor_db=-40.0, dwell_s=0.08, min_spacing_s=0.25)
    spec = DetectorSpec(name="scale_tone", gates=gates, band_cents=30.0)
    reading = _read(line_wav, key=parse_key("Dm"), detector=spec, start_beat=8.0)

    assert reading.detector is not None and reading.detector.name == "scale_tone"
    assert reading.detector.events, "a ±3 % vibrato re-enters a ±30-cent band every cycle"
    for ev in reading.detector.events:
        assert ev.beat >= 8.0
        assert ev.grid_beat >= ev.beat - 1e-6
        assert ev.grid_beat / 0.25 == pytest.approx(round(ev.grid_beat / 0.25))
        assert ev.payload["midi"] == 57 and ev.payload["degree"] == 4  # A, 0-based from D
        assert ev.bar_beat.startswith("bar 3") or ev.bar_beat.startswith("bar 4")
    assert any("x" in row for row in reading.bar_strip)
    out = render(reading)
    assert "detector scale_tone (band_cents 30" in out
    assert "→ lands bar" in out


def test_energy_threshold_and_onset_detectors_run_through_the_same_door(line_wav):
    gates = Gates(voiced_only=False, energy_floor_db=float("-inf"), dwell_s=0.05, min_spacing_s=0.3)
    energy = _read(line_wav, key=None, detector=DetectorSpec("energy_threshold", gates, threshold_db=-20.0))
    onsets = _read(line_wav, key=None, detector=DetectorSpec("onset", gates))
    assert energy.detector is not None and len(energy.detector.events) == 3  # one rising edge per phrase
    assert onsets.detector is not None and onsets.detector.events
    assert "energy floor off" in render(energy)


def test_detector_spec_refuses_a_missing_musical_parameter():
    gates = Gates(voiced_only=False, energy_floor_db=float("-inf"), dwell_s=0.0, min_spacing_s=0.0)
    with pytest.raises(ValueError, match="--band-cents"):
        DetectorSpec("scale_tone", gates)
    with pytest.raises(ValueError, match="--threshold-db"):
        DetectorSpec("energy_threshold", gates)
    with pytest.raises(ValueError, match="unknown detector"):
        DetectorSpec("vibe", gates)


def test_bar_strip_marks_phrases_and_fires_per_sixteenth():
    rows = constant_meter_rows(4, 4)
    placement = Placement(
        start_beat=0.0, end_beat=8.0, start_bar=1.0, end_bar=3.0,
        start_label="", end_label="", source="s",
    )
    strip = bar_strip(placement, [(1.0, 3.0)], [2.1], rows)
    assert strip == (
        "bar   1  ....|====|x===|....",
        "bar   2  ....|....|....|....",
    )


# --- the bare-file door ----------------------------------------------------------


def test_file_door_json_round_trips_the_reading(capsys, line_wav):
    rc = main(["--file", str(line_wav), "--bpm", "92", "--key", "Dm", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "NaN" not in out
    payload = json.loads(out)
    assert len(payload["phrases"]) == 3
    assert payload["pitch"]["centre_note"] == "A3"
    assert payload["pitch"]["key"] == "D Minor"
    assert payload["pitch"]["centre_degree"] == 5
    assert payload["placement"]["start_label"] == "bar 1 beat 1.00"
    assert payload["detector"] is None
    assert any("bare file" in n for n in payload["notes"])


def test_file_door_prints_the_reading_with_a_detector(capsys, line_wav):
    rc = main(["--file", str(line_wav), "--bpm", "92", "--key", "Dm",
               "--detector", "scale_tone", *GATES, "--band-cents", "30"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "fire(s)" in out and "→ lands bar" in out


def test_a_detector_with_no_gates_refuses(capsys, line_wav):
    rc = main(["--file", str(line_wav), "--bpm", "92", "--detector", "onset"])
    assert rc == 3
    err = capsys.readouterr().err
    for flag in ("--voiced-only", "--energy-floor", "--dwell", "--spacing"):
        assert flag in err

    rc = main(["--file", str(line_wav), "--bpm", "92", "--detector", "onset", "--dwell", "0.05"])
    assert rc == 3
    err = capsys.readouterr().err
    assert "--dwell" not in err.split("missing")[1].split(".")[0]
    assert "--spacing" in err


def test_scale_tone_without_a_key_refuses(capsys, line_wav):
    rc = main(["--file", str(line_wav), "--bpm", "92", "--detector", "scale_tone", *GATES,
               "--band-cents", "30"])
    assert rc == 3
    assert "no key" in capsys.readouterr().err


def test_file_door_needs_bpm_and_a_file_that_exists(capsys, line_wav, tmp_path):
    assert main(["--file", str(line_wav)]) == 3
    assert "--bpm" in capsys.readouterr().err
    assert main(["--file", str(tmp_path / "missing.wav"), "--bpm", "92"]) == 2
    assert "not found" in capsys.readouterr().err
    assert main([]) == 3


# --- the song door ---------------------------------------------------------------


SLUG = "lens-song"
SOURCE = "rivers-01"


@pytest.fixture
def synth_song(tmp_path, monkeypatch, line_wav) -> Path:
    """A songs workspace with one song: the line ingested as a source, a DB at
    92 bpm in D minor, and the source placed twice on an audio track."""
    root = tmp_path / "songs"
    song_dir = root / SLUG
    song_dir.mkdir(parents=True)
    ingest.ingest(song_dir, line_wav, name=SOURCE, note="a synthesized vibrato line", origin="synth")
    ingest.ingest(song_dir, line_wav, name="unplaced", note="the same line, not placed", origin="synth")
    conn = init_db(song_dir / f"{SLUG}.db")
    try:
        sid = M.create_song(conn, name=SLUG, key="Dm")
        M.add_tempo_point(conn, song_id=sid, start_bar=1.0, tempo_bpm=BPM)
        M.add_time_signature_point(conn, song_id=sid, start_bar=1.0, numerator=4, denominator=4)
        tid = M.create_track(conn, song_id=sid, track_index=0, name="Dialogue", kind="audio")
        cid = M.create_audio_clip(
            conn, track_id=tid, slot=1, length_beats=8.0, audio_file=store.source_ref(SOURCE),
        )
        M.add_arrangement_clip(conn, song_id=sid, track_id=tid, clip_id=cid, start_bar=3.0, end_bar=5.0)
        M.add_arrangement_clip(conn, song_id=sid, track_id=tid, clip_id=cid, start_bar=9.0, end_bar=11.0)
        conn.commit()
    finally:
        conn.close()
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("HALLUCINOTE_SONGS_ROOT", str(root))
    return song_dir


def test_song_door_reads_placement_tempo_and_key_from_the_song(capsys, synth_song):
    rc = main([SLUG, SOURCE, "--detector", "scale_tone", *GATES, "--band-cents", "30"])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"sample lens — {SOURCE}" in out
    assert "92 bpm" in out
    assert "placement: bar 3 beat 1.00 → bar 4 beat" in out
    assert "also placed at bar 9" in out
    assert "against D Minor: the centre A3 is degree 5" in out
    assert "bar   3  " in out and "bar   4  " in out


def test_song_door_json_carries_the_placement_in_beats(capsys, synth_song):
    rc = main([SLUG, SOURCE, "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["placement"]["start_beat"] == pytest.approx(8.0)
    assert payload["placement"]["other_placements"] == [9.0]
    assert payload["pitch"]["key"] == "D Minor"
    assert len(payload["phrases"]) == 3


def test_unplaced_source_reads_from_bar_1_and_says_so(capsys, synth_song):
    rc = main([SLUG, "unplaced"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "not placed" in out
    assert "placement: bar 1 beat 1.00" in out


def test_start_bar_and_key_overrides_are_named_in_the_reading(capsys, synth_song):
    rc = main([SLUG, SOURCE, "--start-bar", "5", "--key", "E Dorian"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "placement: bar 5 beat 1.00" in out
    assert "--start-bar 5" in out
    assert "reading against --key E Dorian rather than the song's declared 'Dm'" in out
    assert "against E Dorian" in out


def test_missing_source_and_missing_song_exit_2(capsys, synth_song):
    assert main([SLUG, "nope"]) == 2
    err = capsys.readouterr().err
    assert "no source named 'nope'" in err and SOURCE in err
    assert main(["no-such-song", SOURCE]) == 2
    assert "no such song" in capsys.readouterr().err


def test_song_without_a_tempo_map_refuses_to_read_in_beats(capsys, synth_song):
    conn = init_db(synth_song / f"{SLUG}.db")
    try:
        conn.execute("DELETE FROM tempo_map")
        conn.commit()
    finally:
        conn.close()
    assert main([SLUG, SOURCE]) == 3
    assert "no tempo map" in capsys.readouterr().err
