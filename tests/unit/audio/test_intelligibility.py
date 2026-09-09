"""The intelligibility measurement — the speech band over the bed, per turn.

There is no labelled ground truth for "was the line audible", so like the
masking corpus these fixtures DEFINE correctness: a voiced band over pink
noise must read more masked as the noise rises, a turn over silence must read
zero, and a turn the analyzer cannot transform must come back honestly
unmeasured rather than dropped. The report round-trips are pinned here rather
than in ``test_report.py`` because the field is new and the two states it
must keep distinct — not measured (``null``) and measured, nothing here
(``[]``) — are this lens's contract with the reader.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from hallucinote.audio.analyze import DeclaredSpeech, analyze_mix
from hallucinote.audio.bark import bark_band_map
from hallucinote.audio.intelligibility import (
    BED_SURFACE_ID,
    SPEECH_BAND_HZ,
    measure_intelligibility,
    speech_bark_bands,
    sum_bed,
)
from hallucinote.audio.io import Surface
from hallucinote.audio.report import (
    IntelligibilityBand,
    LoudnessMetrics,
    MixReport,
    SectionMetrics,
    StemMetrics,
    TurnIntelligibility,
)
from hallucinote.audio.section import SectionWindow
from hallucinote.db import mutations as M
from hallucinote.db.connection import init_db
from hallucinote.features.types import Segment
from hallucinote_mcp.server_side.analysis import (
    _AnalysisError,
    _collect_declared_speech,
)

from .fixtures import SAMPLE_RATE, concat, pink_noise, silence

SR = SAMPLE_RATE
TURN_S = 2.0

# A voice at 0.05 peak against beds at these peaks gives, by measurement, a
# clear turn, a partly covered turn and a buried turn — about +6, -9 and -20 dB
# of speech over bed in the speech band.
BED_LEVELS = (0.05, 0.3, 1.0)
VOICE_LEVEL = 0.05


def _voiced(duration_s: float, *, f0_hz: float = 120.0, amplitude: float = VOICE_LEVEL) -> np.ndarray:
    """A voiced band: a low male fundamental with 1/k harmonics to ~3.6 kHz.

    120 Hz spacing puts at least one harmonic in every Bark band of the speech
    band (the narrowest is 100 Hz wide), so every band has speech energy to be
    masked or not; the 1/k rolloff means the top of the band is the quietest,
    which is what a real bed covers first.
    """
    n = int(round(duration_s * SR))
    t = np.arange(n, dtype=np.float64) / SR
    mono = np.zeros(n, dtype=np.float64)
    for k in range(1, 31):
        mono += np.sin(2.0 * np.pi * f0_hz * k * t) / k
    mono = mono / np.max(np.abs(mono)) * amplitude
    return np.stack([mono, mono], axis=1).astype(np.float32)


def _surface(track_id: str, audio: np.ndarray, *, sr: int = SR) -> Surface:
    return Surface(track_id, "track", track_id, audio, sr)


def _bed_sweep(levels: tuple[float, ...]) -> np.ndarray:
    return concat(*(
        pink_noise(TURN_S, amplitude=level, rng=np.random.default_rng(i))
        for i, level in enumerate(levels)
    ))


def _turns(n: int) -> list[Segment]:
    return [Segment(i * TURN_S, (i + 1) * TURN_S, "turn") for i in range(n)]


# --------------------------------------------------------------------------- #
# the band split
# --------------------------------------------------------------------------- #

def test_speech_bark_bands_tile_the_telephone_band_contiguously():
    bark = bark_band_map(SR, 2048)
    bands = speech_bark_bands(bark)
    edges = [(float(bark.edges_hz[b]), float(bark.edges_hz[b + 1])) for b in bands]
    lo_hz, hi_hz = SPEECH_BAND_HZ
    assert edges[0][0] == 300.0 and edges[0][0] <= lo_hz
    # The top band overlaps the edge rather than stopping short of it.
    assert edges[-1][0] < hi_hz <= edges[-1][1]
    for (_, hi), (lo, _) in zip(edges, edges[1:]):
        assert hi == lo


# --------------------------------------------------------------------------- #
# the measurement
# --------------------------------------------------------------------------- #

def test_masked_fraction_rises_monotonically_with_the_bed():
    speech = _voiced(3 * TURN_S)
    rows = measure_intelligibility(
        _surface("track:1", speech), _surface(BED_SURFACE_ID, _bed_sweep(BED_LEVELS)),
        SR, turns=_turns(3),
    )
    fractions = [r.masked_fraction for r in rows]
    over_bed = [r.speech_over_bed_db for r in rows]
    assert fractions[0] < fractions[1] < fractions[2]
    assert over_bed[0] > over_bed[1] > over_bed[2]
    # The ends of the sweep are unambiguous: clear, and buried.
    assert fractions[0] == 0.0
    assert fractions[2] > 0.9
    assert over_bed[0] > 0.0 > over_bed[2]
    assert all(r.n_frames > 0 for r in rows)
    assert [r.turn_index for r in rows] == [0, 1, 2]


def test_each_turn_is_judged_against_its_own_bed():
    """The energy gate is per turn, so the order of the sweep cannot leak: a
    buried line before a clear one reads the same two numbers, swapped."""
    speech = _voiced(3 * TURN_S)
    forward = measure_intelligibility(
        _surface("track:1", speech), _surface(BED_SURFACE_ID, _bed_sweep(BED_LEVELS)),
        SR, turns=_turns(3),
    )
    reverse_levels = tuple(reversed(BED_LEVELS))
    backward = measure_intelligibility(
        _surface("track:1", speech),
        _surface(BED_SURFACE_ID, _bed_sweep(reverse_levels)),
        SR, turns=_turns(3),
    )
    # Same levels, different noise draws per slot — the fractions agree to a
    # few percent, the ordering exactly.
    assert backward[2].masked_fraction == pytest.approx(forward[0].masked_fraction, abs=0.05)
    assert backward[0].masked_fraction == pytest.approx(forward[2].masked_fraction, abs=0.05)
    assert backward[0].masked_fraction > backward[1].masked_fraction > backward[2].masked_fraction


def test_per_band_rows_show_where_the_bed_covers_the_voice():
    """The partly-covered turn is the one the per-band split exists for: the
    1/k harmonics are quietest at the top of the band, so the bed takes the
    consonant region before the vowels."""
    speech = _voiced(3 * TURN_S)
    rows = measure_intelligibility(
        _surface("track:1", speech), _surface(BED_SURFACE_ID, _bed_sweep(BED_LEVELS)),
        SR, turns=_turns(3),
    )
    mid = rows[1]
    assert len(mid.bands) == len(speech_bark_bands(bark_band_map(SR, 2048)))
    assert mid.bands[0].lo_hz == 300.0
    assert 0.0 < mid.masked_fraction < 1.0
    assert mid.bands[-1].masked_fraction > mid.bands[0].masked_fraction
    assert mid.bands[-1].speech_over_bed_db < mid.bands[0].speech_over_bed_db
    for band in mid.bands:
        assert band.speech_over_bed_db == pytest.approx(band.speech_db - band.bed_db)
        assert 0.0 <= band.masked_fraction <= 1.0


def test_a_turn_with_no_bed_reads_zero_masking():
    speech = _voiced(TURN_S)
    rows = measure_intelligibility(
        _surface("track:1", speech), _surface(BED_SURFACE_ID, silence(TURN_S)),
        SR, turns=_turns(1),
    )
    (row,) = rows
    assert row.masked_fraction == 0.0
    assert all(b.masked_fraction == 0.0 for b in row.bands)
    assert row.speech_over_bed_db > 0.0
    assert row.n_frames > 0


def test_a_silent_speech_turn_is_unmeasurable_not_zero():
    """Nothing to mask is not the same as nothing masked: the fraction is NaN
    (the report's unmeasured sentinel), while the levels stay numbers."""
    rows = measure_intelligibility(
        _surface("track:1", silence(TURN_S)),
        _surface(BED_SURFACE_ID, pink_noise(TURN_S)),
        SR, turns=_turns(1),
    )
    (row,) = rows
    assert math.isnan(row.masked_fraction)
    assert all(math.isnan(b.masked_fraction) for b in row.bands)
    assert math.isfinite(row.speech_db) and math.isfinite(row.bed_db)
    assert row.n_frames > 0


def test_a_turn_too_short_to_transform_is_present_and_unmeasured():
    rows = measure_intelligibility(
        _surface("track:1", _voiced(TURN_S)),
        _surface(BED_SURFACE_ID, silence(TURN_S)),
        SR, turns=[Segment(0.0, 0.01, "turn", label="blip"), Segment(0.0, TURN_S, "turn")],
    )
    short, full = rows
    assert short.n_frames == 0
    assert short.label == "blip"
    assert math.isnan(short.masked_fraction) and math.isnan(short.speech_over_bed_db)
    assert short.bands and all(math.isnan(b.masked_fraction) for b in short.bands)
    assert full.n_frames > 0 and full.masked_fraction == 0.0


def test_a_turn_beyond_the_audio_is_clamped_or_unmeasured():
    speech = _voiced(TURN_S)
    rows = measure_intelligibility(
        _surface("track:1", speech), _surface(BED_SURFACE_ID, silence(TURN_S)),
        SR, turns=[Segment(TURN_S - 0.5, TURN_S + 5.0, "turn"), Segment(TURN_S + 1.0, TURN_S + 2.0, "turn")],
    )
    overhanging, beyond = rows
    assert overhanging.n_frames > 0 and overhanging.masked_fraction == 0.0
    assert beyond.n_frames == 0 and math.isnan(beyond.masked_fraction)


def test_sample_rate_mismatch_is_refused_with_the_fix():
    with pytest.raises(ValueError, match="resample"):
        measure_intelligibility(
            _surface("track:1", _voiced(TURN_S)),
            _surface(BED_SURFACE_ID, silence(TURN_S), sr=44_100),
            SR, turns=_turns(1),
        )
    with pytest.raises(ValueError, match="sr must be > 0"):
        measure_intelligibility(
            _surface("track:1", _voiced(TURN_S)),
            _surface(BED_SURFACE_ID, silence(TURN_S)),
            0, turns=_turns(1),
        )


def test_sum_bed_sums_the_other_stems_and_is_silent_alone():
    a = pink_noise(TURN_S, amplitude=0.2, rng=np.random.default_rng(1))
    b = pink_noise(TURN_S, amplitude=0.2, rng=np.random.default_rng(2))
    bed = sum_bed([("track:2", a), ("track:3", b)], sample_rate=SR, like=a)
    assert bed.track_id == BED_SURFACE_ID
    assert bed.sample_rate == SR
    np.testing.assert_allclose(bed.audio, a + b, atol=1e-6)
    alone = sum_bed([], sample_rate=SR, like=a)
    assert alone.audio.shape == a.shape and not np.any(alone.audio)


# --------------------------------------------------------------------------- #
# the report field
# --------------------------------------------------------------------------- #

def _stem(track_id: str = "track:1") -> StemMetrics:
    return StemMetrics(
        track_id=track_id, surface_kind="track", surface_name=track_id,
        loudness=LoudnessMetrics(-23.0, -22.8, -21.0, -1.0),
    )


def _report(intelligibility: list[TurnIntelligibility] | None) -> MixReport:
    return MixReport(
        song_slug="s", captures_dir="captures/x", captured_at="20260909T120000Z",
        analyzer_signature="sig", stems=[_stem()], master=_stem("master"),
        per_section=[SectionMetrics(
            section_name="scene1", start_beat=0.0, end_beat=16.0,
            master=_stem("master"), intelligibility=intelligibility,
        )],
    )


def test_section_intelligibility_round_trips_absent_empty_and_present():
    absent = json.loads(json.dumps(_report(None).to_json_dict(), allow_nan=False))
    assert absent["per_section"][0]["intelligibility"] is None

    empty = json.loads(json.dumps(_report([]).to_json_dict(), allow_nan=False))
    assert empty["per_section"][0]["intelligibility"] == []

    row = TurnIntelligibility(
        turn_index=3, start_s=1.5, end_s=2.25, speech_db=-30.0, bed_db=-36.0,
        speech_over_bed_db=6.0, masked_fraction=0.125, n_frames=71,
        bands=[
            IntelligibilityBand(300.0, 400.0, -31.0, -40.0, 9.0, 0.0),
            IntelligibilityBand(3150.0, 3700.0, -48.0, -38.0, -10.0, math.nan),
        ],
        label="I never said that", start_beat=6.0, end_beat=9.0,
    )
    present = json.loads(json.dumps(_report([row]).to_json_dict(), allow_nan=False))
    (turn,) = present["per_section"][0]["intelligibility"]
    assert turn["turn_index"] == 3
    assert turn["label"] == "I never said that"
    assert (turn["start_beat"], turn["end_beat"]) == (6.0, 9.0)
    assert (turn["start_s"], turn["end_s"]) == (1.5, 2.25)
    assert turn["speech_over_bed_db"] == 6.0 and turn["masked_fraction"] == 0.125
    assert turn["n_frames"] == 71
    assert turn["bands"][0]["masked_fraction"] == 0.0
    # A band the speech never sounded in carries the unmeasured sentinel as
    # null, never as a NaN token that would break a strict consumer.
    assert turn["bands"][1]["masked_fraction"] is None
    assert turn["bands"][1]["lo_hz"] == 3150.0


def test_unmeasured_turn_serializes_every_measurement_as_null():
    rows = measure_intelligibility(
        _surface("track:1", _voiced(TURN_S)), _surface(BED_SURFACE_ID, silence(TURN_S)),
        SR, turns=[Segment(0.0, 0.001, "turn")],
    )
    (turn,) = json.loads(
        json.dumps(_report(rows).to_json_dict(), allow_nan=False)
    )["per_section"][0]["intelligibility"]
    assert turn["n_frames"] == 0
    assert turn["masked_fraction"] is None and turn["speech_db"] is None
    assert all(b["speech_over_bed_db"] is None for b in turn["bands"])


# --------------------------------------------------------------------------- #
# the orchestrator
# --------------------------------------------------------------------------- #

def _write_capture(
    tmp_path: Path,
    *,
    stems: list[tuple[str, str, np.ndarray]],
    master_audio: np.ndarray,
    stop_at_beat: float,
) -> Path:
    captures_dir = tmp_path / "captures" / "20260909T130000Z"
    captures_dir.mkdir(parents=True)

    def _entry(track_id: str, surface_name: str, filename: str) -> dict:
        return {
            "track_id": track_id, "surface_name": surface_name, "surface_index": 0,
            "device_index": 1, "osc_port": 11020, "filename": filename,
            "absolute_path": str(captures_dir / filename),
        }

    sf.write(str(captures_dir / "master.wav"), master_audio, SR, subtype="FLOAT")
    entries = []
    for track_id, surface_name, audio in stems:
        filename = f"{track_id.replace(':', '-')}.wav"
        sf.write(str(captures_dir / filename), audio, SR, subtype="FLOAT")
        entries.append(_entry(track_id, surface_name, filename))
    (captures_dir / "manifest.json").write_text(json.dumps({
        "schema_version": "1", "captured_at": "20260909T130100Z",
        "song_slug": "test-song", "start_at_beat": 0.0, "stop_at_beat": stop_at_beat,
        "ring_out_beats": 0.0, "post_roll_beats": 4.0, "status": "ok",
        "frames_received": 400, "analyzer_signature": "hallucinote-analyzer-v1",
        "tracks": entries, "returns": [],
        "master": _entry("master", "Main", "master.wav"),
    }), encoding="utf-8")
    return captures_dir


# Four seconds of audio over sixteen beats: four beats a second, two sections
# of two seconds each, three turns — one inside A, one straddling the A/B
# boundary, one inside B.
_STOP_BEAT = 16.0
_SECTIONS = [
    SectionWindow("A", 0.0, 8.0, section_id="sec-a"),
    SectionWindow("B", 8.0, 16.0, section_id="sec-b"),
]
_TURNS = ((1.0, 3.0), (6.0, 10.0), (12.0, 14.0))


def _dialogue_capture(tmp_path: Path) -> Path:
    speech = _voiced(4.0)
    bed = pink_noise(4.0, amplitude=0.3)
    return _write_capture(
        tmp_path,
        stems=[("track:1", "Dialogue", speech), ("track:2", "Score", bed)],
        master_audio=(speech + bed).astype(np.float32),
        stop_at_beat=_STOP_BEAT,
    )


def _skips(report: MixReport, kind: str = "intelligibility") -> list[str]:
    return [s["reason"] for s in report.skipped_analyses if s["kind"] == kind]


def test_analyze_mix_reports_each_turn_under_the_section_it_falls_in(tmp_path: Path):
    report = analyze_mix(
        _dialogue_capture(tmp_path), sections=_SECTIONS,
        declared_speech=DeclaredSpeech("track:1", _TURNS),
    )
    assert _skips(report) == []
    a, b = report.per_section
    assert a.intelligibility is not None and b.intelligibility is not None
    assert [t.turn_index for t in a.intelligibility] == [0, 1]
    assert [t.turn_index for t in b.intelligibility] == [1, 2]
    # The straddling turn is clipped to each section's half of it.
    assert (a.intelligibility[1].start_beat, a.intelligibility[1].end_beat) == (6.0, 8.0)
    assert (b.intelligibility[0].start_beat, b.intelligibility[0].end_beat) == (8.0, 10.0)
    assert (a.intelligibility[0].start_beat, a.intelligibility[0].end_beat) == (1.0, 3.0)
    # Beats and seconds describe the same span at four beats a second.
    assert a.intelligibility[0].start_s == pytest.approx(0.25)
    assert a.intelligibility[0].end_s == pytest.approx(0.75)
    for section in (a, b):
        for turn in section.intelligibility or []:
            assert turn.n_frames > 0
            assert 0.0 <= turn.masked_fraction <= 1.0
            assert len(turn.bands) == 14
    # And it survives the JSON boundary the handler writes through.
    out = json.loads(json.dumps(report.to_json_dict(), allow_nan=False))
    assert len(out["per_section"][0]["intelligibility"]) == 2


def test_analyze_mix_speech_alone_in_the_capture_reads_a_silent_bed(tmp_path: Path):
    speech = _voiced(4.0)
    captures_dir = _write_capture(
        tmp_path, stems=[("track:1", "Dialogue", speech)],
        master_audio=speech, stop_at_beat=_STOP_BEAT,
    )
    report = analyze_mix(
        captures_dir, sections=_SECTIONS[:1],
        declared_speech=DeclaredSpeech("track:1", ((0.0, 4.0),)),
    )
    (section,) = report.per_section
    assert section.intelligibility is not None
    (turn,) = section.intelligibility
    assert turn.masked_fraction == 0.0


def test_analyze_mix_without_a_declared_speech_track_leaves_the_field_null(tmp_path: Path):
    report = analyze_mix(_dialogue_capture(tmp_path), sections=_SECTIONS)
    assert all(s.intelligibility is None for s in report.per_section)
    (reason,) = _skips(report)
    assert "speech_track" in reason


def test_analyze_mix_declared_surface_missing_from_the_capture_is_a_skip(tmp_path: Path):
    report = analyze_mix(
        _dialogue_capture(tmp_path), sections=_SECTIONS,
        declared_speech=DeclaredSpeech("track:9", _TURNS),
    )
    assert all(s.intelligibility is None for s in report.per_section)
    (reason,) = _skips(report)
    assert "track:9" in reason and "track:1" in reason


def test_analyze_mix_declared_speech_with_no_turns_is_a_skip(tmp_path: Path):
    report = analyze_mix(
        _dialogue_capture(tmp_path), sections=_SECTIONS,
        declared_speech=DeclaredSpeech("track:1", ()),
    )
    assert all(s.intelligibility is None for s in report.per_section)
    (reason,) = _skips(report)
    assert "no turns" in reason


def test_analyze_mix_speech_declared_without_sections_is_a_skip(tmp_path: Path):
    report = analyze_mix(
        _dialogue_capture(tmp_path), declared_speech=DeclaredSpeech("track:1", _TURNS),
    )
    assert report.per_section == []
    (reason,) = _skips(report)
    assert "create_section" in reason


def test_analyze_mix_speech_lens_applies_mix_level_gains(tmp_path: Path):
    """Captures are pre-fader; a bed faded down in the mix must read as the
    quieter bed the listener hears, exactly as masking does."""
    captures_dir = _dialogue_capture(tmp_path)
    loud = analyze_mix(
        captures_dir, sections=_SECTIONS[:1],
        declared_speech=DeclaredSpeech("track:1", ((0.0, 8.0),)),
    )
    faded = analyze_mix(
        captures_dir, sections=_SECTIONS[:1],
        declared_speech=DeclaredSpeech("track:1", ((0.0, 8.0),)),
        stem_gains={"track:2": 0.01},
    )
    assert loud.per_section[0].intelligibility is not None
    assert faded.per_section[0].intelligibility is not None
    loud_turn = loud.per_section[0].intelligibility[0]
    faded_turn = faded.per_section[0].intelligibility[0]
    assert faded_turn.speech_over_bed_db > loud_turn.speech_over_bed_db + 30.0
    assert faded_turn.masked_fraction <= loud_turn.masked_fraction


def test_declared_speech_refuses_an_inverted_turn():
    with pytest.raises(ValueError, match="half-open"):
        DeclaredSpeech("track:1", ((4.0, 4.0),))
    with pytest.raises(ValueError, match="surface"):
        DeclaredSpeech("", ((0.0, 4.0),))


# --------------------------------------------------------------------------- #
# the handler's DB walk
# --------------------------------------------------------------------------- #

def _song_with_dialogue(tmp_path: Path):
    conn = init_db(tmp_path / "s.db")
    conn.execute("INSERT INTO songs (id, name) VALUES (?, ?)", ("song-1", "s"))
    dialogue = M.create_track(
        conn, song_id="song-1", track_index=2, name="Dialogue", kind="audio",
    )
    line1 = M.create_audio_clip(
        conn, track_id=dialogue, slot=1, length_beats=4.0,
        audio_file="assets/sources/line-01.wav", name="line-01",
    )
    line2 = M.create_audio_clip(
        conn, track_id=dialogue, slot=2, length_beats=6.0,
        audio_file="assets/sources/line-02.wav", name="line-02",
    )
    # Placed out of order on purpose: the walk must come back in bar order.
    M.add_arrangement_clip(
        conn, song_id="song-1", track_id=dialogue, clip_id=line2,
        start_bar=3.0, end_bar=4.5,
    )
    M.add_arrangement_clip(
        conn, song_id="song-1", track_id=dialogue, clip_id=line1,
        start_bar=1.0, end_bar=2.0,
    )
    piano = M.create_track(conn, song_id="song-1", track_index=0, name="Piano")
    riff = M.create_clip(conn, track_id=piano, slot=1, length_beats=4.0)
    M.add_arrangement_clip(
        conn, song_id="song-1", track_id=piano, clip_id=riff,
        start_bar=1.0, end_bar=2.0,
    )
    conn.commit()
    return conn


def test_collect_declared_speech_lifts_audio_placements_to_beat_turns(tmp_path: Path):
    conn = _song_with_dialogue(tmp_path)
    declared = _collect_declared_speech(conn, "song-1", "Dialogue")
    # DB UUID → capture surface id, by track index.
    assert declared.surface_id == "track:2"
    # Bars → song-absolute beats in 4/4, in arrangement order.
    assert declared.turns_beats == ((0.0, 4.0), (8.0, 14.0))


def test_collect_declared_speech_teaches_when_the_name_is_wrong(tmp_path: Path):
    conn = _song_with_dialogue(tmp_path)
    with pytest.raises(_AnalysisError, match="Dialogue") as excinfo:
        _collect_declared_speech(conn, "song-1", "Dialog")
    assert "'Dialog'" in str(excinfo.value)


def test_collect_declared_speech_refuses_a_track_with_only_midi_placements(tmp_path: Path):
    conn = _song_with_dialogue(tmp_path)
    with pytest.raises(_AnalysisError, match="no audio-clip placements"):
        _collect_declared_speech(conn, "song-1", "Piano")
