"""End-to-end ``ableton_analysis`` handler tests.

Builds a synthetic ``songs/<slug>/`` layout under a tmp_path, monkey-
patches the handler module's DB-resolution function to point there,
writes a captures dir with manifest + WAVs, runs the handler, asserts
the MixReport JSON lands at the expected place and the summary fields
match the captures.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from hallucinote.db.connection import init_db
from hallucinote_mcp.handlers import analysis as analysis_handlers


SAMPLE_RATE = 48_000


def _make_song_dir(tmp_path: Path, slug: str) -> Path:
    """Build a minimal ``songs/<slug>/`` with a real DB row.

    Uses ``init_db`` to create the schema, then inserts the song row
    directly — keeps the test independent of `build.py` scaffolding.
    """
    song_dir = tmp_path / "songs" / slug
    song_dir.mkdir(parents=True)
    db_path = song_dir / f"{slug}.db"
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO songs (id, name) VALUES (?, ?)",
        (f"song-{slug}", slug),
    )
    conn.commit()
    conn.close()
    return song_dir


def _sine(freq: float, duration_s: float, amplitude: float = 0.3) -> np.ndarray:
    n = int(round(duration_s * SAMPLE_RATE))
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    mono = amplitude * np.sin(2 * np.pi * freq * t)
    return np.stack([mono, mono], axis=1).astype(np.float32)


def _write_captures(
    captures_dir: Path,
    *,
    song_slug: str,
    duration_s: float = 2.0,
) -> Path:
    captures_dir.mkdir(parents=True)
    stems = [
        ("track:1", "01 Drums", "track-01.wav", _sine(80.0, duration_s, 0.4)),
        ("track:2", "02 Bass", "track-02.wav", _sine(120.0, duration_s, 0.3)),
    ]
    master_audio = stems[0][3] + stems[1][3]
    sf.write(str(captures_dir / "master.wav"), master_audio,
             SAMPLE_RATE, subtype="FLOAT")
    track_entries = []
    for track_id, surface_name, filename, audio in stems:
        sf.write(str(captures_dir / filename), audio,
                 SAMPLE_RATE, subtype="FLOAT")
        track_entries.append({
            "track_id": track_id,
            "surface_name": surface_name,
            "surface_index": int(track_id.split(":")[-1]),
            "device_index": 1,
            "osc_port": 11020,
            "filename": filename,
            "absolute_path": str(captures_dir / filename),
        })
    manifest = {
        "schema_version": "1",
        "captured_at": captures_dir.name,
        "song_slug": song_slug,
        "start_at_beat": 0,
        "stop_at_beat": 8,
        "post_roll_beats": 4.0,
        "status": "ok",
        "frames_received": 200,
        "analyzer_signature": "hallucinote-analyzer-v1",
        "tracks": track_entries,
        "returns": [],
        "master": {
            "track_id": "master",
            "surface_name": "Main",
            "surface_index": 0,
            "device_index": 1,
            "osc_port": 11220,
            "filename": "master.wav",
            "absolute_path": str(captures_dir / "master.wav"),
        },
    }
    (captures_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return captures_dir


@pytest.fixture
def synthetic_song(tmp_path: Path, monkeypatch):
    """Build a minimal song dir + captures dir; redirect the handler's
    DB-path resolver to find it.

    Returns the song dir Path. Tests can build additional captures or
    expect the analysis dir under ``song_dir / "analysis"``.
    """
    slug = "test-song"
    song_dir = _make_song_dir(tmp_path, slug)
    db_path = song_dir / f"{slug}.db"

    # Redirect resolve_db_path so the handler finds our tmp song dir.
    def _fake_resolve_db_path(s, **_):
        if s != slug:
            return Path(tmp_path / "songs" / s / f"{s}.db")  # forced miss
        return db_path

    monkeypatch.setattr(analysis_handlers, "resolve_db_path", _fake_resolve_db_path)
    # init_db is fine to leave as-is — it just opens the (real) DB path.
    return song_dir


def test_analyze_handler_produces_mixreport_json(synthetic_song: Path):
    captures_dir = _write_captures(
        synthetic_song / "captures" / "20260528T140000Z",
        song_slug="test-song",
    )

    result = analysis_handlers.analyze_handler(
        None,  # _context — analysis is server-side, no LiveContext
        song_slug="test-song",
        captures_dir=str(captures_dir),
    )

    assert "report_path" in result
    report_path = Path(result["report_path"])
    assert report_path.exists()
    assert report_path.parent == synthetic_song / "analysis"
    assert report_path.suffix == ".json"

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "1"
    assert report["song_slug"] == "test-song"
    assert len(report["stems"]) == 2
    assert report["master"]["track_id"] == "master"


def test_analyze_handler_defaults_to_latest_captures_dir(synthetic_song: Path):
    _write_captures(
        synthetic_song / "captures" / "20260528T120000Z",
        song_slug="test-song",
    )
    _write_captures(
        synthetic_song / "captures" / "20260528T140000Z",  # latest
        song_slug="test-song",
    )
    result = analysis_handlers.analyze_handler(
        None,
        song_slug="test-song",
        captures_dir=None,
    )
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    # The latest captures dir's manifest carries its own ISO timestamp
    # in `captured_at`. Sanity: the report came from the later one.
    assert report["captured_at"] == "20260528T140000Z"


def test_analyze_handler_teaches_when_song_not_found(synthetic_song: Path):
    with pytest.raises(ValueError, match="no song DB"):
        analysis_handlers.analyze_handler(
            None,
            song_slug="nonexistent-slug",
            captures_dir=None,
        )


def test_analyze_handler_teaches_when_no_captures(synthetic_song: Path):
    # song exists but no captures dir
    with pytest.raises(ValueError, match="no captures"):
        analysis_handlers.analyze_handler(
            None,
            song_slug="test-song",
            captures_dir=None,
        )


def test_analyze_handler_teaches_when_explicit_captures_dir_missing_manifest(
    synthetic_song: Path,
):
    empty_dir = synthetic_song / "captures" / "20260528T999999Z"
    empty_dir.mkdir(parents=True)
    with pytest.raises(ValueError, match="manifest"):
        analysis_handlers.analyze_handler(
            None,
            song_slug="test-song",
            captures_dir=str(empty_dir),
        )


def test_get_latest_report_returns_most_recent_json(synthetic_song: Path):
    captures = _write_captures(
        synthetic_song / "captures" / "20260528T140000Z",
        song_slug="test-song",
    )
    # Build one report
    first = analysis_handlers.analyze_handler(
        None, song_slug="test-song", captures_dir=str(captures),
    )
    # Build a second report (handler timestamps the filename — wait a tick
    # to ensure a different ISO second, or write a third manifest with a
    # later captured_at). Since two analyze calls within the same second
    # would collide, force the second's timestamp to be later by writing
    # a sentinel report manually.
    later_path = synthetic_song / "analysis" / "20260528T999999Z.json"
    later_path.write_text(
        json.dumps({"schema_version": "1", "marker": "later"}),
        encoding="utf-8",
    )

    result = analysis_handlers.get_latest_report_handler(
        None, song_slug="test-song",
    )
    assert Path(result["report_path"]) == later_path
    assert result["report"]["marker"] == "later"


def test_get_latest_report_teaches_when_no_reports(synthetic_song: Path):
    with pytest.raises(ValueError, match="no MixReport"):
        analysis_handlers.get_latest_report_handler(
            None, song_slug="test-song",
        )
