"""Tests for the schema-vs-_ADDED_COLUMNS consistency canary.

Convention: every additive column gets two declarations — one in
``schema.sql`` (fresh DB CREATE TABLE) and one in ``_ADDED_COLUMNS``
(the ALTER pass for existing DBs). The canary verifies the schema.sql
side hasn't drifted; missing entries there would be papered over by
the ALTER pass on fresh DBs, hiding the bug.

Most recent drift: ``devices.browser_path_json`` (Arc 7-tail / E3,
2026-05-22).
"""
from __future__ import annotations

import re
import sqlite3

import pytest

from hallucinote.db import connection as conn_mod
from hallucinote.db import init_db
from hallucinote.db.mutations.tracks import (
    OUTPUT_ROUTING_KINDS,
    INPUT_ROUTING_KINDS,
    MONITORING_STATES,
)
from hallucinote.sync import routing_names


@pytest.fixture(autouse=True)
def _reset_canary_flag():
    """Reset the once-per-process flag so each test exercises the check."""
    original = conn_mod._SCHEMA_CANARY_CHECKED
    conn_mod._SCHEMA_CANARY_CHECKED = False
    yield
    conn_mod._SCHEMA_CANARY_CHECKED = original


def test_canary_passes_on_current_schema(tmp_path):
    """The current schema.sql declares every _ADDED_COLUMNS column.
    Round-trip: init_db succeeds without raising and the canary flag
    flips to True.
    """
    conn = init_db(tmp_path / "ok.db")
    try:
        assert conn_mod._SCHEMA_CANARY_CHECKED is True
    finally:
        conn.close()


def test_canary_raises_when_added_columns_declares_a_missing_column(
    tmp_path, monkeypatch,
):
    """If _ADDED_COLUMNS declares a column that schema.sql's CREATE TABLE
    doesn't include, the canary names the missing (table, col) pair and
    refuses to proceed. The drift case the canary was built to catch.
    """
    phantom = ("devices", "phantom_column", "TEXT")
    monkeypatch.setattr(
        conn_mod, "_ADDED_COLUMNS",
        conn_mod._ADDED_COLUMNS + (phantom,),
    )
    with pytest.raises(RuntimeError) as exc:
        init_db(tmp_path / "drifted.db")
    msg = str(exc.value)
    assert "devices.phantom_column" in msg
    assert "schema.sql" in msg


def _make_pre_energy_db(db_path) -> None:
    """Build a full schema DB but with the ARR-7M3D ``sections.energy`` column
    stripped from the CREATE TABLE — the exact shape of a DB built before the
    column was added. Built from the real ``schema.sql`` (minus the one column
    line + its trailing comment block) so every OTHER ``_ADDED_COLUMNS`` table
    is present, matching what ``_ensure_added_columns`` walks.
    """
    schema = conn_mod._SCHEMA_PATH.read_text()
    # Drop only the energy column declaration line (and its leading comment
    # block) so the rest of the sections CREATE TABLE — and every other table —
    # is byte-identical to today's schema.
    lines = schema.splitlines(keepends=True)
    kept = []
    skip_comment = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("-- Authored per-section energy"):
            skip_comment = True
            continue
        if skip_comment:
            # The energy comment block ends at the energy column line itself.
            if stripped.startswith("energy"):
                skip_comment = False
                continue
            continue
        kept.append(line)
    pre_schema = "".join(kept)
    assert "energy" not in pre_schema, "energy column not fully stripped"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(pre_schema)
        conn.commit()
    finally:
        conn.close()


def test_added_column_migration_lands_once_on_pre_column_db(tmp_path):
    """ARR-7M3D's ``sections.energy`` ALTER lands exactly once on a pre-column
    DB and is a no-op on re-open. Exercises ``_ensure_added_columns`` directly
    (it's the idempotent ALTER pass) against a full schema that predates the
    energy column — the migration the dual-declaration convention requires.
    """
    db_path = tmp_path / "pre_column.db"
    _make_pre_energy_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        # Pre-migration: no energy column.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(sections)")}
        assert "energy" not in cols

        # First migration: ALTER lands.
        conn_mod._ensure_added_columns(conn)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(sections)")}
        assert "energy" in cols

        # Re-open / re-run: no-op (no duplicate-column error, column still there).
        conn_mod._ensure_added_columns(conn)
        cols2 = {r["name"] for r in conn.execute("PRAGMA table_info(sections)")}
        assert cols2 == cols

        # The migrated column accepts NULL and rejects out-of-range energy
        # (the CHECK rode the ALTER definition).
        conn.execute("INSERT INTO songs (id, name) VALUES ('s1', 'migrated-song')")
        conn.execute(
            "INSERT INTO sections (id, song_id, name, start_bar, end_bar, energy) "
            "VALUES ('x', 's1', 'v', 1.0, 9.0, NULL)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO sections (id, song_id, name, start_bar, end_bar, energy) "
                "VALUES ('y', 's1', 'c', 1.0, 9.0, 2.0)"
            )
    finally:
        conn.close()


_CLIP_AUDIO_COLUMNS = {
    "kind", "audio_file", "audio_gain", "pitch_coarse", "pitch_fine",
    "warping", "warp_mode", "start_marker", "end_marker",
}


def _make_pre_audio_clip_db(db_path) -> None:
    """Build a full schema DB with the CLP-AUD1 clips columns stripped from
    the CREATE TABLE — the exact shape of a DB built before the audio-clip
    model landed. Same construction as ``_make_pre_energy_db``: built from
    the real ``schema.sql`` minus the one block, so every other table is
    byte-identical to today's schema.
    """
    schema = conn_mod._SCHEMA_PATH.read_text()
    # The CLP-AUD1 block runs from its leading comment through the last
    # column it declares (end_marker); everything else is kept verbatim.
    lines = schema.splitlines(keepends=True)
    kept = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("-- CLP-AUD1"):
            skipping = True
            continue
        if skipping:
            if stripped.startswith("end_marker"):
                skipping = False
            continue
        kept.append(line)
    pre_schema = "".join(kept)
    assert "audio_file" not in pre_schema, "audio columns not fully stripped"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(pre_schema)
        conn.commit()
    finally:
        conn.close()


def test_clip_audio_columns_land_on_pre_column_db_and_default_legacy_rows(tmp_path):
    """CLP-AUD1's clips ALTERs land idempotently on a pre-column DB, and a
    legacy MIDI clip row written BEFORE the migration is valid afterwards:
    kind defaults to 'midi', every audio column reads NULL.
    """
    db_path = tmp_path / "pre_audio.db"
    _make_pre_audio_clip_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        # Seed a legacy clip in the pre-column shape (raw SQL is the point —
        # this row predates the mutator that knows about kind).
        conn.execute("INSERT INTO songs (id, name) VALUES ('s1', 'legacy-song')")
        conn.execute(
            "INSERT INTO tracks (id, song_id, track_index, name) "
            "VALUES ('t1', 's1', 1, 'Drums')"
        )
        conn.execute(
            "INSERT INTO clips (id, track_id, slot, length_beats) "
            "VALUES ('c1', 't1', 1, 16.0)"
        )
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(clips)")}
        assert not (_CLIP_AUDIO_COLUMNS & cols)

        # Migration lands all nine columns; re-run is a no-op.
        conn_mod._ensure_added_columns(conn)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(clips)")}
        assert _CLIP_AUDIO_COLUMNS <= cols
        conn_mod._ensure_added_columns(conn)
        cols2 = {r["name"] for r in conn.execute("PRAGMA table_info(clips)")}
        assert cols2 == cols

        # The legacy row is valid under the DEFAULT: kind='midi', audio NULL.
        row = conn.execute("SELECT * FROM clips WHERE id = 'c1'").fetchone()
        assert row["kind"] == "midi"
        for col in _CLIP_AUDIO_COLUMNS - {"kind"}:
            assert row[col] is None
    finally:
        conn.close()


def test_clip_audio_columns_present_on_fresh_db(tmp_path):
    """A fresh init_db (schema.sql path, no ALTER needed) has the same nine
    columns — the dual-declaration convention's other half.
    """
    conn = init_db(tmp_path / "fresh.db")
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(clips)")}
        assert _CLIP_AUDIO_COLUMNS <= cols
    finally:
        conn.close()


_ROUTING_COLUMNS = {
    "output_routing_kind", "output_routing_target_id", "output_routing_channel",
    "input_routing_kind", "input_routing_target_id", "input_routing_channel",
    "monitoring_state",
}


def _make_pre_routing_db(db_path) -> None:
    """Build a full schema DB with the RTE-1K9T routing columns stripped from the
    tracks CREATE TABLE — the exact shape of a DB built before track routing
    landed. Same construction as ``_make_pre_audio_clip_db``: the real
    ``schema.sql`` minus the one block, every other table byte-identical."""
    schema = conn_mod._SCHEMA_PATH.read_text()
    kept = []
    skipping = False
    for line in schema.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("-- RTE-1K9T: track signal routing"):
            skipping = True
            continue
        if skipping:
            # The monitoring_state CHECK's close is the last routing line.
            if "'Off'))" in stripped:
                skipping = False
            continue
        kept.append(line)
    pre_schema = "".join(kept)
    for marker in ("routing_kind", "routing_target_id", "routing_channel",
                   "monitoring_state"):
        assert marker not in pre_schema, f"routing not fully stripped ({marker})"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(pre_schema)
        conn.commit()
    finally:
        conn.close()


def test_routing_columns_land_on_pre_column_db_and_default_legacy_rows(tmp_path):
    """RTE-1K9T's seven routing ALTERs land idempotently on a pre-column DB, a
    legacy track written BEFORE the migration stays valid (every routing column
    NULL), and the CHECK that rode the ALTER definition is enforced."""
    db_path = tmp_path / "pre_routing.db"
    _make_pre_routing_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        # Seed a legacy track in the pre-column shape (raw SQL is the point).
        conn.execute("INSERT INTO songs (id, name) VALUES ('s1', 'legacy-song')")
        conn.execute(
            "INSERT INTO tracks (id, song_id, track_index, name) "
            "VALUES ('t1', 's1', 1, 'Drums')"
        )
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tracks)")}
        assert not (_ROUTING_COLUMNS & cols)

        # Migration lands all seven; re-run is a no-op.
        conn_mod._ensure_added_columns(conn)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tracks)")}
        assert _ROUTING_COLUMNS <= cols
        conn_mod._ensure_added_columns(conn)
        assert {r["name"] for r in conn.execute("PRAGMA table_info(tracks)")} == cols

        # The legacy row is valid: every routing column reads NULL.
        row = conn.execute("SELECT * FROM tracks WHERE id = 't1'").fetchone()
        for col in _ROUTING_COLUMNS:
            assert row[col] is None

        # The CHECK rode the ALTER: bad kind / monitor rejected, valid accepted.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE tracks SET output_routing_kind = 'bogus' WHERE id = 't1'")
        conn.execute("UPDATE tracks SET output_routing_kind = 'master' WHERE id = 't1'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE tracks SET monitoring_state = 'Bogus' WHERE id = 't1'")
    finally:
        conn.close()


def test_routing_columns_present_on_fresh_db(tmp_path):
    """The dual-declaration convention's other half: a fresh init_db (schema.sql
    path, no ALTER) carries the same seven routing columns."""
    conn = init_db(tmp_path / "fresh_routing.db")
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tracks)")}
        assert _ROUTING_COLUMNS <= cols
    finally:
        conn.close()


def test_routing_vocabulary_parity_across_all_four_sites():
    """RTE-1K9T (Critic W3): the closed routing vocabulary is hand-synced across
    FOUR sites — schema.sql's CHECK, the ``_ADDED_COLUMNS`` ALTER CHECK, the
    mutator frozensets, and ``routing_names``' display maps. The schema canary
    only checks column PRESENCE, not the CHECK vocab, so lock the vocab here: a
    drift in any one site breaks this test."""
    schema = conn_mod._SCHEMA_PATH.read_text()
    alter = "\n".join(
        defn for (table, _col, defn) in conn_mod._ADDED_COLUMNS if table == "tracks"
    )

    def _in_list(sql: str, column: str) -> set[str]:
        m = re.search(rf"{column}\s+IN\s*\(([^)]*)\)", sql)
        assert m, f"no CHECK IN-list found for {column}"
        return {tok.strip().strip("'") for tok in m.group(1).split(",")}

    # OUTPUT kind + MONITOR state: schema.sql == ALTER == mutator frozenset.
    assert _in_list(schema, "output_routing_kind") == set(OUTPUT_ROUTING_KINDS)
    assert _in_list(alter, "output_routing_kind") == set(OUTPUT_ROUTING_KINDS)
    assert _in_list(schema, "monitoring_state") == set(MONITORING_STATES)
    assert _in_list(alter, "monitoring_state") == set(MONITORING_STATES)
    # routing_names' display maps cover exactly the non-'track' kinds.
    assert set(routing_names.OUTPUT_KIND_DISPLAY_NAME) | {"track"} == set(OUTPUT_ROUTING_KINDS)
    assert set(routing_names.INPUT_KIND_DISPLAY_NAME) | {"track"} == set(INPUT_ROUTING_KINDS)


def test_canary_runs_once_per_process(tmp_path, monkeypatch):
    """The canary caches its result via a module-level flag so it runs
    once per process regardless of how many DBs init_db opens. After the
    first init_db, _SCHEMA_CANARY_CHECKED is True; a second init_db with
    drifted _ADDED_COLUMNS would normally raise, but the flag short-
    circuits the check — proving the cache works.
    """
    conn = init_db(tmp_path / "first.db")
    conn.close()
    assert conn_mod._SCHEMA_CANARY_CHECKED is True
    # Now drift _ADDED_COLUMNS; the second init_db skips the canary check.
    phantom = ("devices", "phantom_column", "TEXT")
    monkeypatch.setattr(
        conn_mod, "_ADDED_COLUMNS",
        conn_mod._ADDED_COLUMNS + (phantom,),
    )
    conn = init_db(tmp_path / "second.db")
    conn.close()


def test_disposable_rebuild_drops_session_blind_performed_automation(tmp_path):
    """ENV-7G4K cumulative fix: a DB carrying the original session-blind
    ``performed_automation`` shape (UNIQUE(envelope_id), no session_id) is
    rebuilt on open — old table dropped, new session-keyed shape created
    by schema.sql. Dropped fingerprints are safe by design (the next push
    re-performs). Idempotent on re-open."""
    db_path = tmp_path / "session_blind.db"
    conn = init_db(db_path)
    conn.close()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("DROP TABLE performed_automation")
        conn.execute(
            """CREATE TABLE performed_automation (
                   id            TEXT PRIMARY KEY,
                   envelope_id   TEXT NOT NULL UNIQUE
                                     REFERENCES envelopes(id) ON DELETE CASCADE,
                   fingerprint   TEXT NOT NULL,
                   performed_at  TEXT NOT NULL DEFAULT
                       (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
               )"""
        )
        conn.execute(
            "INSERT INTO performed_automation (id, envelope_id, fingerprint) "
            "VALUES ('p1', 'e1', 'fp-old')"
        )
        conn.commit()
    finally:
        conn.close()

    conn = init_db(db_path)
    try:
        cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(performed_automation)")
        }
        assert "session_id" in cols
        # The old session-blind row is gone — disposable state, re-derived
        # by the next push.
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM performed_automation"
        ).fetchone()["n"] == 0
    finally:
        conn.close()

    # Re-open: the rebuild sniff is a no-op on the new shape.
    conn = init_db(db_path)
    try:
        cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(performed_automation)")
        }
        assert "session_id" in cols
    finally:
        conn.close()
