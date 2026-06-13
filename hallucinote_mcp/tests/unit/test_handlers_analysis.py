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


def test_analyze_handler_surfaces_analysis_code_version(synthetic_song: Path):
    """The response carries the loaded analysis-pipeline signature + a stale
    flag so a stale MCP subprocess is obvious without reading the report."""
    captures_dir = _write_captures(
        synthetic_song / "captures" / "20260528T140000Z",
        song_slug="test-song",
    )

    result = analysis_handlers.analyze_handler(
        None,
        song_slug="test-song",
        captures_dir=str(captures_dir),
    )

    code = result["analysis_code"]
    assert isinstance(code["signature"], str) and code["signature"]
    # Un-edited tree under test: loaded code matches disk.
    assert code["stale"] is False


def test_get_latest_report_surfaces_analysis_code_version(synthetic_song: Path):
    captures_dir = _write_captures(
        synthetic_song / "captures" / "20260528T140000Z",
        song_slug="test-song",
    )
    analysis_handlers.analyze_handler(
        None, song_slug="test-song", captures_dir=str(captures_dir)
    )

    result = analysis_handlers.get_latest_report_handler(
        None, song_slug="test-song"
    )

    code = result["analysis_code"]
    assert isinstance(code["signature"], str) and code["signature"]
    assert code["stale"] is False


def test_analyze_handler_opens_db_once(synthetic_song: Path, monkeypatch):
    """Regression: analyze_handler used to open the DB three times (verify +
    each collector). It must open exactly once per invocation now."""
    captures_dir = _write_captures(
        synthetic_song / "captures" / "20260528T140000Z",
        song_slug="test-song",
    )
    real_init_db = analysis_handlers.init_db
    calls = {"n": 0}

    def _counting_init_db(path):
        calls["n"] += 1
        return real_init_db(path)

    monkeypatch.setattr(analysis_handlers, "init_db", _counting_init_db)
    analysis_handlers.analyze_handler(
        None, song_slug="test-song", captures_dir=str(captures_dir),
    )
    assert calls["n"] == 1


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
    # a sentinel report manually. The sentinel uses a far-future timestamp
    # so it sorts last regardless of the real wall-clock: _latest_report_path
    # sorts by filename, and analyze_handler stamps the live UTC clock — a
    # same-year sentinel would lose once the clock rolls past it.
    later_path = synthetic_song / "analysis" / "99991231T235959Z.json"
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


def test_collect_stem_gains_keys_by_capture_surface_id_not_db_uuid():
    """Regression (Critic BLOCKING): the gains dict MUST be keyed by the
    capture surface ID (``track:N``) so ``apply_stem_gains`` matches the stems
    from the manifest. Keying by the DB UUID silently never matches → the F1
    level correction becomes a no-op on every real song.
    """
    from hallucinote.audio.levels import live_fader_gain
    from hallucinote.db.connection import init_db as _init

    conn = _init(":memory:")
    conn.execute("INSERT INTO songs (id, name) VALUES ('s1', 'demo')")
    # Two tracks with non-unity, NULL-distinct volumes + a UUID id distinct
    # from the surface index.
    conn.execute(
        "INSERT INTO tracks (id, song_id, track_index, name, kind, volume) "
        "VALUES ('uuid-aaa', 's1', 1, '01 Drums', 'midi', 0.85)"
    )
    conn.execute(
        "INSERT INTO tracks (id, song_id, track_index, name, kind, volume) "
        "VALUES ('uuid-bbb', 's1', 2, '02 Bass', 'midi', 0.5)"
    )
    conn.execute(  # NULL volume → omitted (no guess)
        "INSERT INTO tracks (id, song_id, track_index, name, kind, volume) "
        "VALUES ('uuid-ccc', 's1', 3, '03 Pad', 'midi', NULL)"
    )
    conn.commit()

    gains = analysis_handlers._collect_stem_gains(conn, "s1")
    conn.close()

    # Keyed by track:N, NOT the UUIDs.
    assert set(gains) == {"track:1", "track:2"}
    assert "uuid-aaa" not in gains
    assert gains["track:1"] == pytest.approx(live_fader_gain(0.85))  # ~unity
    assert gains["track:2"] == pytest.approx(live_fader_gain(0.5))   # ~-14 dB


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
    # One verification PER RETURN. The surface IDs are capture-side, not DB
    # UUIDs — the boundary `_collect_declared_sends` crosses. (This fixture's
    # return is a continuous sine with no ring-out, so the RT60 itself is an
    # honest insufficient-tail skip; the lift — surface IDs + declared value —
    # is what this test pins.)
    assert rv["return_track_id"] == f"return:{return_surface_index}"
    assert rv["contributing_track_ids"] == [f"track:{track_surface_index}"]
    assert rv["declared_rt60_s"] == pytest.approx(0.8)
    # No DB intent → skip; intent present → no skip record.
    skips = [s for s in report["skipped_analyses"]
             if s["kind"] == "reverb_verification"]
    assert skips == []


def test_collect_declared_envelopes_resolves_surfaces(synthetic_song: Path):
    """`_collect_declared_envelopes` resolves each verifiable envelope kind to
    its capture surface (the DB-UUID → track:N / return:N boundary):
    device_parameter → the device's host track (device→chain→track),
    send_level → the return it feeds, mixer_volume → the track (passed through
    so the audio module reports it unverifiable rather than dropping it).
    """
    slug = "test-song"
    db_path = synthetic_song / f"{slug}.db"
    conn = init_db(db_path)
    try:
        song_id = conn.execute(
            "SELECT id FROM songs WHERE name = ?", (slug,)
        ).fetchone()["id"]
        track_id = M.create_track(
            conn, song_id=song_id, track_index=3, name="Rhythm Gtr")
        return_id = M.create_return(
            conn, song_id=song_id, name="A-Plate", position=1)
        chain_id = M.create_device_chain(
            conn, parent_track_id=track_id, position=0)
        device_id = M.create_device(
            conn, chain_id=chain_id, position=1, kind="Amp", display_name="Amp")

        env_dev = M.create_envelope(
            conn, song_id=song_id, target_kind="device_parameter",
            target_device_id=device_id, parameter_path="Amp Type")
        M.add_breakpoint(conn, envelope_id=env_dev, time_beats=0.0, value=0.0,
                         curve_kind="hold")
        M.add_breakpoint(conn, envelope_id=env_dev, time_beats=8.0, value=1.0,
                         curve_kind="hold")

        M.set_send_level(conn, from_track_id=track_id, to_return_id=return_id,
                         level=0.3)
        env_send = M.create_envelope(
            conn, song_id=song_id, target_kind="send_level",
            target_track_id=track_id, target_send_return_id=return_id)
        M.add_breakpoint(conn, envelope_id=env_send, time_beats=0.0, value=0.2)
        M.add_breakpoint(conn, envelope_id=env_send, time_beats=8.0, value=0.8)

        env_vol = M.create_envelope(
            conn, song_id=song_id, target_kind="mixer_volume",
            target_track_id=track_id)
        M.add_breakpoint(conn, envelope_id=env_vol, time_beats=0.0, value=0.5)
        M.add_breakpoint(conn, envelope_id=env_vol, time_beats=8.0, value=0.9)
        conn.commit()

        declared = analysis_handlers._collect_declared_envelopes(conn, song_id)
    finally:
        conn.close()

    by_kind = {e.target_kind: e for e in declared}
    assert by_kind["device_parameter"].target_surface_id == "track:3"
    assert by_kind["device_parameter"].parameter_path == "Amp Type"
    assert by_kind["device_parameter"].breakpoints == ((0.0, 0.0), (8.0, 1.0))
    assert by_kind["send_level"].target_surface_id == "return:1"
    assert by_kind["mixer_volume"].target_surface_id == "track:3"


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
        verse_id = M.create_section(
            conn, song_id=song_id, name="verse", start_bar=1.0, end_bar=2.0
        )
        chorus_id = M.create_section(
            conn, song_id=song_id, name="chorus", start_bar=2.0, end_bar=3.0
        )
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
    # AUD-2N6K: each per_section entry carries the DB sections row id, so a
    # finding can correlate back to its row (not just by name/beat).
    section_ids = [s["section_id"] for s in report["per_section"]]
    assert section_ids == [verse_id, chorus_id]
    assert all(sid is not None for sid in section_ids)
    verse = report["per_section"][0]
    assert verse["start_beat"] == 0.0
    assert verse["end_beat"] == 4.0
    assert verse["master"]["track_id"] == "master"
    assert len(verse["stems"]) == 2
    # Declared sections → no section_windowed skip record.
    assert not any(
        s["kind"] == "section_windowed" for s in report["skipped_analyses"]
    )


def test_collect_declared_energy_lifts_section_energy_excluding_null(synthetic_song: Path):
    """_collect_declared_energy reads the sections.energy column and lifts the
    NON-NULL rows into SectionEnergy carrying start_beat (the lens join key); a
    NULL-energy section is EXCLUDED (never coerced) — ARR-7M3D chunk 4."""
    slug = "test-song"
    db_path = synthetic_song / f"{slug}.db"
    conn = init_db(db_path)
    try:
        song_id = conn.execute(
            "SELECT id FROM songs WHERE name = ?", (slug,)
        ).fetchone()["id"]
        # 4/4 default: bar 1 -> beat 0, bar 2 -> beat 4, bar 3 -> beat 8.
        M.create_section(
            conn, song_id=song_id, name="verse", start_bar=1.0, end_bar=2.0,
            energy=0.4,
        )
        M.create_section(
            conn, song_id=song_id, name="chorus", start_bar=2.0, end_bar=3.0,
            energy=0.9,
        )
        # A NULL-energy section is excluded from the lift entirely.
        M.create_section(
            conn, song_id=song_id, name="outro", start_bar=3.0, end_bar=4.0,
        )
        conn.commit()
        declared = analysis_handlers._collect_declared_energy(conn, song_id)
    finally:
        conn.close()

    assert [(s.name, s.start_beat, s.energy) for s in declared] == [
        ("verse", 0.0, 0.4),
        ("chorus", 4.0, 0.9),
    ]


def test_collect_declared_energy_keeps_same_named_sections_distinct(synthetic_song: Path):
    """B2 at the handler layer: a song with two same-named sections at different
    start_bar / energy lifts to two distinct SectionEnergy rows with distinct
    start_beat — the handler does NOT collapse repeated names (the Nobile
    energy-drop two-Chorus case)."""
    slug = "test-song"
    db_path = synthetic_song / f"{slug}.db"
    conn = init_db(db_path)
    try:
        song_id = conn.execute(
            "SELECT id FROM songs WHERE name = ?", (slug,)
        ).fetchone()["id"]
        # Two "Chorus" sections at different bars and energies.
        M.create_section(
            conn, song_id=song_id, name="Chorus", start_bar=1.0, end_bar=3.0,
            energy=0.9,
        )
        M.create_section(
            conn, song_id=song_id, name="Verse", start_bar=3.0, end_bar=5.0,
            energy=0.5,
        )
        M.create_section(
            conn, song_id=song_id, name="Chorus", start_bar=5.0, end_bar=7.0,
            energy=0.4,
        )
        conn.commit()
        declared = analysis_handlers._collect_declared_energy(conn, song_id)
    finally:
        conn.close()

    # 4/4 default: bar 1 -> beat 0, bar 3 -> beat 8, bar 5 -> beat 16.
    chorus_rows = [s for s in declared if s.name == "Chorus"]
    assert len(chorus_rows) == 2
    assert {s.start_beat for s in chorus_rows} == {0.0, 16.0}
    assert {s.energy for s in chorus_rows} == {0.9, 0.4}


def test_analyze_handler_populates_energy_realization(synthetic_song: Path):
    """A song whose sections declare energy → the report carries
    energy_realization (the lens ran on the real handler path), and the on-disk
    JSON parses (allow_nan=False backstop — ρ is None-or-finite, never nan).

    The two 80/120 Hz sine stems read near-constant loudness across the two
    sections, so the loudness ρ is None (tied/constant) WITH a reason in
    skipped — which is exactly the B1 contract: None, never nan. This test
    proves the wiring + the tied-correlate path on a real handler call."""
    slug = "test-song"
    db_path = synthetic_song / f"{slug}.db"
    conn = init_db(db_path)
    try:
        song_id = conn.execute(
            "SELECT id FROM songs WHERE name = ?", (slug,)
        ).fetchone()["id"]
        M.create_section(
            conn, song_id=song_id, name="verse", start_bar=1.0, end_bar=2.0,
            energy=0.4,
        )
        M.create_section(
            conn, song_id=song_id, name="chorus", start_bar=2.0, end_bar=3.0,
            energy=0.9,
        )
        conn.commit()
    finally:
        conn.close()

    captures = _write_captures(
        synthetic_song / "captures" / "20260528T141500Z", song_slug=slug,
    )
    result = analysis_handlers.analyze_handler(
        None, song_slug=slug, captures_dir=str(captures),
    )
    # The on-disk report parses (proves allow_nan=False didn't choke).
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    er = report["energy_realization"]
    assert er is not None
    # Two energy-declared sections lifted + ranked.
    assert {s["start_beat"] for s in er["sections_ranked"]} == {0.0, 4.0}
    # ρ values are None-or-finite (JSON null or a number), never NaN.
    for rho in er["correlate_rho"].values():
        assert rho is None or isinstance(rho, (int, float))
    # No fabricated energy_realization skip (energy WAS declared).
    assert not any(
        s["kind"] == "energy_realization" and "no per-section energy" in s["reason"]
        for s in report["skipped_analyses"]
    )


def test_analyze_handler_skips_energy_realization_when_no_energy_declared(
    synthetic_song: Path,
):
    """A song whose sections declare NO energy → energy_realization is null +
    a structured skipped_analyses entry (never a fabricated ρ)."""
    slug = "test-song"
    db_path = synthetic_song / f"{slug}.db"
    conn = init_db(db_path)
    try:
        song_id = conn.execute(
            "SELECT id FROM songs WHERE name = ?", (slug,)
        ).fetchone()["id"]
        # Sections declared, but no energy on any of them.
        M.create_section(conn, song_id=song_id, name="verse", start_bar=1.0, end_bar=2.0)
        M.create_section(conn, song_id=song_id, name="chorus", start_bar=2.0, end_bar=3.0)
        conn.commit()
    finally:
        conn.close()

    captures = _write_captures(
        synthetic_song / "captures" / "20260528T142000Z", song_slug=slug,
    )
    result = analysis_handlers.analyze_handler(
        None, song_slug=slug, captures_dir=str(captures),
    )
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["energy_realization"] is None
    assert any(
        s["kind"] == "energy_realization" for s in report["skipped_analyses"]
    )


def test_analyze_handler_always_emits_energy_realization_key(synthetic_song: Path):
    """ARR-7M3D chunk-5 verify-api (deferred-render): the render→analyze handler
    path ALWAYS writes the energy_realization key to the on-disk report — null
    when no energy is declared, an object when it is. This is the UNIT proof that
    the new report key reaches disk through the real handler, standing in for the
    live render (Live unattended this run; see operator-verification.md)."""
    slug = "test-song"
    captures = _write_captures(
        synthetic_song / "captures" / "20260528T143000Z", song_slug=slug,
    )
    result = analysis_handlers.analyze_handler(
        None, song_slug=slug, captures_dir=str(captures),
    )
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    # Key is always present in the wire format (the song here declares no
    # sections/energy, so it's null with a skip entry — never absent).
    assert "energy_realization" in report
    assert report["energy_realization"] is None


def test_collect_tempo_map_lifts_db_rows_to_beat_segments(synthetic_song: Path):
    """_collect_tempo_map reads the tempo_map table and converts each row's
    start_bar to a song-absolute beat (via the 4/4-default meter walk),
    yielding the beat-domain TempoSegments analyze_mix needs for accurate
    windowing."""
    slug = "test-song"
    db_path = synthetic_song / f"{slug}.db"
    conn = init_db(db_path)
    try:
        song_id = conn.execute(
            "SELECT id FROM songs WHERE name = ?", (slug,)
        ).fetchone()["id"]
        M.add_tempo_point(conn, song_id=song_id, start_bar=1.0, tempo_bpm=120.0)
        M.add_tempo_point(conn, song_id=song_id, start_bar=3.0, tempo_bpm=90.0)
        conn.commit()
        segs = analysis_handlers._collect_tempo_map(conn, song_id)
    finally:
        conn.close()

    # 4/4 default: bar 1 -> beat 0, bar 3 -> beat 8.
    assert [(s.start_beat, s.bpm) for s in segs] == [(0.0, 120.0), (8.0, 90.0)]


def test_collect_tempo_map_carries_ramp_kind(synthetic_song: Path):
    """The DB row's ``ramp`` rides onto the TempoSegment so BeatSampleMap can
    integrate a linear glide instead of stepping it."""
    slug = "test-song"
    db_path = synthetic_song / f"{slug}.db"
    conn = init_db(db_path)
    try:
        song_id = conn.execute(
            "SELECT id FROM songs WHERE name = ?", (slug,)
        ).fetchone()["id"]
        M.add_tempo_point(
            conn, song_id=song_id, start_bar=1.0, tempo_bpm=90.0, ramp="linear",
        )
        M.add_tempo_point(conn, song_id=song_id, start_bar=5.0, tempo_bpm=140.0)
        conn.commit()
        segs = analysis_handlers._collect_tempo_map(conn, song_id)
    finally:
        conn.close()

    assert [s.ramp for s in segs] == ["linear", "hold"]


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


# ---------------------------------------------------------------------------
# extract_structure_handler — raw structural-dump tier
# ---------------------------------------------------------------------------


def _seed_full_song(db_path: Path, slug: str) -> None:
    """Populate a song DB with one of each structural element so the
    extract handler's nesting is exercised end-to-end: a track with a clip
    (two notes), a device (one parameter), an arrangement placement, a
    return, a send, a section, a cue point, and tempo/meter rows.
    """
    conn = init_db(db_path)
    try:
        song_id = M.create_song(conn, name=slug, title="Extract Test", key="E min")
        M.add_tempo_point(conn, song_id=song_id, start_bar=1.0, tempo_bpm=120.0)
        M.create_section(
            conn, song_id=song_id, name="A", start_bar=1.0, end_bar=5.0
        )
        M.add_cue_point(conn, song_id=song_id, position_bar=1.0, name="Top")
        ret_id = M.create_return(conn, song_id=song_id, name="A-Reverb", position=0)
        track_id = M.create_track(
            conn, song_id=song_id, track_index=1, name="Lead"
        )
        clip_id = M.create_clip(
            conn, track_id=track_id, slot=0, length_beats=4.0, name="riff"
        )
        M.insert_notes(
            conn,
            clip_id=clip_id,
            notes=[
                {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0,
                 "velocity": 100},
                {"pitch": 64, "start_beats": 1.0, "duration_beats": 1.0,
                 "velocity": 90},
            ],
        )
        M.add_arrangement_clip(
            conn, song_id=song_id, track_id=track_id, clip_id=clip_id,
            start_bar=1.0, end_bar=2.0,
        )
        M.set_send_level(
            conn, from_track_id=track_id, to_return_id=ret_id, level=0.3
        )
        chain_id = M.create_device_chain(conn, parent_track_id=track_id, position=0)
        device_id = M.create_device(
            conn, chain_id=chain_id, position=1, kind="Reverb",
            display_name="Reverb",
        )
        M.set_device_parameter(
            conn, device_id=device_id, name="Decay Time", value_display="2.0 s",
            value_normalized=0.5,
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def populated_song(tmp_path: Path, monkeypatch):
    """A song dir whose DB carries one of every structural element, with the
    handler's DB resolver redirected at it. Returns the slug."""
    slug = "extract-song"
    song_dir = tmp_path / "songs" / slug
    song_dir.mkdir(parents=True)
    db_path = song_dir / f"{slug}.db"
    _seed_full_song(db_path, slug)

    def _fake_resolve_db_path(s, **_):
        if s != slug:
            return Path(tmp_path / "songs" / s / f"{s}.db")  # forced miss
        return db_path

    monkeypatch.setattr(analysis_handlers, "resolve_db_path", _fake_resolve_db_path)
    return slug


def test_extract_returns_full_nested_structure(populated_song: str):
    result = analysis_handlers.extract_structure_handler(
        None, song_slug=populated_song
    )
    assert result["song_slug"] == populated_song
    extract = result["extract"]
    assert set(extract) == {
        "song", "tempo_map", "time_signature_map", "sections",
        "cue_points", "tracks", "returns",
    }
    assert extract["song"]["name"] == populated_song
    assert extract["song"]["key"] == "E min"
    assert len(extract["sections"]) == 1
    assert extract["sections"][0]["name"] == "A"
    assert len(extract["cue_points"]) == 1
    assert len(extract["tempo_map"]) == 1
    assert extract["tempo_map"][0]["tempo_bpm"] == 120.0

    assert len(extract["tracks"]) == 1
    track = extract["tracks"][0]
    assert {"clips", "arrangement_clips", "devices", "sends"} <= set(track)
    assert track["name"] == "Lead"
    assert len(track["clips"]) == 1
    assert len(track["arrangement_clips"]) == 1
    assert len(track["sends"]) == 1
    assert track["sends"][0]["level"] == 0.3
    assert len(track["devices"]) == 1
    device = track["devices"][0]
    assert device["display_name"] == "Reverb"
    assert len(device["parameters"]) == 1
    assert device["parameters"][0]["name"] == "Decay Time"

    assert len(extract["returns"]) == 1
    assert extract["returns"][0]["name"] == "Reverb"
    assert extract["returns"][0]["devices"] == []


def test_extract_includes_exact_note_timings(populated_song: str):
    # The cliff tier: compose-review is blind to exact note timings; the
    # extract must carry them so the judge can read phase relationships.
    result = analysis_handlers.extract_structure_handler(
        None, song_slug=populated_song
    )
    notes = result["extract"]["tracks"][0]["clips"][0]["notes"]
    assert [n["pitch"] for n in notes] == [60, 64]
    assert [n["start_beats"] for n in notes] == [0.0, 1.0]
    assert [n["velocity"] for n in notes] == [100, 90]
    # Notes round-trip through get_notes_for_clip — tags deserialized to a list.
    assert all(isinstance(n["tags"], list) for n in notes)


def test_extract_is_json_serializable(populated_song: str):
    # The judge consumes the extract as a JSON file; every value must
    # serialize (no raw sqlite3.Row leaking through).
    result = analysis_handlers.extract_structure_handler(
        None, song_slug=populated_song
    )
    json.dumps(result)  # raises TypeError if any Row survived


def test_extract_teaches_when_song_db_missing(populated_song: str):
    with pytest.raises(ValueError, match="no song DB"):
        analysis_handlers.extract_structure_handler(
            None, song_slug="nonexistent-slug"
        )


def test_extract_bare_song_has_empty_collections(tmp_path: Path, monkeypatch):
    # A song with no tracks/sections still returns the full key set.
    slug = "bare-song"
    song_dir = tmp_path / "songs" / slug
    song_dir.mkdir(parents=True)
    db_path = song_dir / f"{slug}.db"
    conn = init_db(db_path)
    try:
        M.create_song(conn, name=slug, title="Bare")
        conn.commit()
    finally:
        conn.close()

    def _fake_resolve_db_path(s, **_):
        return db_path

    monkeypatch.setattr(analysis_handlers, "resolve_db_path", _fake_resolve_db_path)
    result = analysis_handlers.extract_structure_handler(None, song_slug=slug)
    extract = result["extract"]
    assert extract["tracks"] == []
    assert extract["sections"] == []
    assert extract["returns"] == []
    assert extract["cue_points"] == []
    assert extract["song"]["name"] == slug


def _tag_manifest_db_seq(captures_dir: Path, db_seq: int) -> None:
    manifest_file = captures_dir / "manifest.json"
    raw = json.loads(manifest_file.read_text(encoding="utf-8"))
    raw["db_seq"] = db_seq
    manifest_file.write_text(json.dumps(raw), encoding="utf-8")


def test_analyze_handler_compare_to_seq_end_to_end(synthetic_song: Path):
    """AUD-4W7K full loop at the handler level: analyze a db_seq=1 capture
    (report written with db_seq=1), then analyze a second capture with
    compare_to=1 — the new report diffs against the first and the summary
    carries the significant-delta count."""
    first = _write_captures(
        synthetic_song / "captures" / "20260610T010000Z",
        song_slug="test-song",
    )
    _tag_manifest_db_seq(first, 1)
    baseline_result = analysis_handlers.analyze_handler(
        None, song_slug="test-song", captures_dir=str(first),
    )
    baseline = json.loads(
        Path(baseline_result["report_path"]).read_text(encoding="utf-8")
    )
    assert baseline["db_seq"] == 1
    assert "compare_to" not in baseline_result["summary"]

    second = _write_captures(
        synthetic_song / "captures" / "20260610T020000Z",
        song_slug="test-song",
    )
    _tag_manifest_db_seq(second, 2)
    result = analysis_handlers.analyze_handler(
        None, song_slug="test-song", captures_dir=str(second), compare_to=1,
    )
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["db_seq"] == 2
    assert report["compare_to"]["baseline"]["ref"] == baseline_result["report_path"]
    # Identical synthetic captures → nothing significant; the overshoot
    # delta rides the summary so a count change can't hide in the report.
    assert result["summary"]["compare_to"] == {
        "baseline_ref": baseline_result["report_path"],
        "significant_delta_count": 0,
        "overshoot_delta": 0,
        "added_surfaces": [],
        "missing_surfaces": [],
    }


def test_analyze_handler_compare_to_unknown_seq_teaches(synthetic_song: Path):
    """A seq nothing matches refuses with the available seqs — before any
    DSP runs (the analysis dir is resolved up front)."""
    captures = _write_captures(
        synthetic_song / "captures" / "20260610T030000Z",
        song_slug="test-song",
    )
    _tag_manifest_db_seq(captures, 5)
    analysis_handlers.analyze_handler(
        None, song_slug="test-song", captures_dir=str(captures),
    )
    with pytest.raises(ValueError, match="db_seq=99"):
        analysis_handlers.analyze_handler(
            None, song_slug="test-song", captures_dir=str(captures),
            compare_to=99,
        )
