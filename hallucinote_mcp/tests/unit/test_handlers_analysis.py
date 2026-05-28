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

from hallucinote.db import mutations as M
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


def _write_captures_with_return(
    captures_dir: Path,
    *,
    song_slug: str,
    track_surface_index: int = 1,
    return_surface_index: int = 1,
    duration_s: float = 2.0,
) -> Path:
    """Variant of ``_write_captures`` that adds one return entry — used to
    exercise the DB-declared reverb-send path.

    Track IDs follow the production manifest convention written by
    ``analyzer.setup.track_id_for_surface`` (``"track:N"`` /
    ``"return:N"``) so ``_collect_declared_sends`` can translate DB
    UUIDs into matching capture-side keys via the same helper.
    """
    captures_dir.mkdir(parents=True)
    dry_audio = _sine(80.0, duration_s, 0.4)
    wet_audio = _sine(80.0, duration_s, 0.05)  # quieter return sim
    master_audio = dry_audio + wet_audio
    sf.write(str(captures_dir / "master.wav"), master_audio,
             SAMPLE_RATE, subtype="FLOAT")
    sf.write(str(captures_dir / "track-01.wav"), dry_audio,
             SAMPLE_RATE, subtype="FLOAT")
    sf.write(str(captures_dir / "return-01.wav"), wet_audio,
             SAMPLE_RATE, subtype="FLOAT")
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
        "tracks": [{
            "track_id": f"track:{track_surface_index}",
            "surface_name": "01 Drums",
            "surface_index": track_surface_index,
            "device_index": 1,
            "osc_port": 11020,
            "filename": "track-01.wav",
            "absolute_path": str(captures_dir / "track-01.wav"),
        }],
        "returns": [{
            "track_id": f"return:{return_surface_index}",
            "surface_name": "A-Reverb",
            "surface_index": return_surface_index,
            "device_index": 1,
            "osc_port": 11120,
            "filename": "return-01.wav",
            "absolute_path": str(captures_dir / "return-01.wav"),
        }],
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


def test_analyze_handler_picks_up_db_declared_reverb_intent(synthetic_song: Path):
    """The handler walks ``sends.intended_rt60_s`` and lifts each row into
    a ``DeclaredReverbSend``, translating DB UUIDs into the capture
    manifest's ``track:N`` / ``return:N`` surface-ID convention. The
    resulting MixReport carries one ``reverb_verifications`` entry per
    declared send rather than the no-intent ``skipped_analyses`` record.
    """
    slug = "test-song"
    db_path = synthetic_song / f"{slug}.db"
    track_surface_index = 1
    return_surface_index = 1
    conn = init_db(db_path)
    try:
        song_row = conn.execute("SELECT id FROM songs WHERE name = ?", (slug,)).fetchone()
        song_id = song_row["id"]
        track_id = M.create_track(
            conn, song_id=song_id, track_index=track_surface_index, name="Drums",
        )
        return_id = M.create_return(
            conn, song_id=song_id, name="A-Reverb", position=return_surface_index,
        )
        M.set_send_level(
            conn, from_track_id=track_id, to_return_id=return_id, level=0.3
        )
        M.set_send_intended_rt60(
            conn,
            from_track_id=track_id,
            to_return_id=return_id,
            intended_rt60_s=0.8,
        )
        conn.commit()
    finally:
        conn.close()

    captures = _write_captures_with_return(
        synthetic_song / "captures" / "20260528T140000Z",
        song_slug=slug,
        track_surface_index=track_surface_index,
        return_surface_index=return_surface_index,
    )
    result = analysis_handlers.analyze_handler(
        None, song_slug=slug, captures_dir=str(captures),
    )
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert len(report["reverb_verifications"]) == 1
    rv = report["reverb_verifications"][0]
    # Verification dry/wet IDs are the capture-side surface IDs, not the
    # DB UUIDs — that's the boundary `_collect_declared_sends` crosses.
    assert rv["dry_track_id"] == f"track:{track_surface_index}"
    assert rv["wet_return_track_id"] == f"return:{return_surface_index}"
    assert rv["declared_rt60_s"] == pytest.approx(0.8)
    # No DB intent → skip; intent present → no skip record.
    skips = [s for s in report["skipped_analyses"]
             if s["kind"] == "reverb_verification"]
    assert skips == []


def test_analyze_handler_picks_up_db_declared_sections(synthetic_song: Path):
    """The handler walks the ``sections`` table, converts each named
    half-open ``[start_bar, end_bar)`` span to song-absolute beats via the
    time_signature_map, and hands the beat windows to ``analyze_mix``. The
    resulting MixReport carries one ``per_section`` entry per declared
    section, keyed by name, with master + per-stem loudness scoped to the
    window.

    The 8-beat capture (4/4 default → 2 bars) is split into two named
    sections; both fall inside the captured window.
    """
    slug = "test-song"
    db_path = synthetic_song / f"{slug}.db"
    conn = init_db(db_path)
    try:
        song_id = conn.execute(
            "SELECT id FROM songs WHERE name = ?", (slug,)
        ).fetchone()["id"]
        # 4/4 default: bar 1 -> beat 0, bar 2 -> beat 4, bar 3 -> beat 8.
        M.create_section(conn, song_id=song_id, name="verse", start_bar=1.0, end_bar=2.0)
        M.create_section(conn, song_id=song_id, name="chorus", start_bar=2.0, end_bar=3.0)
        conn.commit()
    finally:
        conn.close()

    captures = _write_captures(
        synthetic_song / "captures" / "20260528T140000Z",
        song_slug=slug,
    )
    result = analysis_handlers.analyze_handler(
        None, song_slug=slug, captures_dir=str(captures),
    )
    assert result["summary"]["section_count"] == 2
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    names = [s["section_name"] for s in report["per_section"]]
    assert names == ["verse", "chorus"]
    verse = report["per_section"][0]
    assert verse["start_beat"] == 0.0
    assert verse["end_beat"] == 4.0
    assert verse["master"]["track_id"] == "master"
    assert len(verse["stems"]) == 2
    # Declared sections → no section_windowed skip record.
    assert not any(
        s["kind"] == "section_windowed" for s in report["skipped_analyses"]
    )


def test_analyze_handler_emits_skip_when_no_db_sections(synthetic_song: Path):
    """A song with no ``sections`` rows → per_section empty + a teaching
    skip naming ``create_section``."""
    captures = _write_captures(
        synthetic_song / "captures" / "20260528T140000Z",
        song_slug="test-song",
    )
    result = analysis_handlers.analyze_handler(
        None, song_slug="test-song", captures_dir=str(captures),
    )
    assert result["summary"]["section_count"] == 0
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    section_skips = [s for s in report["skipped_analyses"]
                     if s["kind"] == "section_windowed"]
    assert len(section_skips) == 1
    assert "create_section" in section_skips[0]["reason"]


def test_analyze_handler_emits_skip_when_no_db_intent(synthetic_song: Path):
    """When the song has no ``intended_rt60_s`` rows, the report still
    teaches the caller how to declare them — same shape as the
    pre-schema MVP behaviour, but the message now names the mutator."""
    captures = _write_captures(
        synthetic_song / "captures" / "20260528T140000Z",
        song_slug="test-song",
    )
    result = analysis_handlers.analyze_handler(
        None, song_slug="test-song", captures_dir=str(captures),
    )
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    reverb_skips = [s for s in report["skipped_analyses"]
                    if s["kind"] == "reverb_verification"]
    assert len(reverb_skips) == 1
    assert "set_send_intended_rt60" in reverb_skips[0]["reason"]
