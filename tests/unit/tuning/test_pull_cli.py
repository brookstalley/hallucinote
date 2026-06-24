"""/tuning-pull apply: the orchestration over read → cache → persist.

Exercises the CLI end-to-end against a real song DB (no Live, no MCP): the agent
already turned the ``song.tuning_system`` probes into a JSON file; this is the
pure ``apply`` half. The probe fixture is the verify-api capture
(``GAMMA_LOADED_RAW``) so the test rides the same real shapes the live pull does.
"""
from __future__ import annotations

import json

import pytest

from hallucinote.db import events as E
from hallucinote.db import init_db
from hallucinote.db import mutations as M
from hallucinote.db import queries as Q
from hallucinote.tuning import pull_cli
from hallucinote.tuning.model import TuningData
from hallucinote.tuning.read import TuningReadError
from hallucinote.tuning.store import load_song_tuning

from .fixtures import GAMMA_EXPECTED, GAMMA_LOADED_RAW


def _song_db(tmp_path, slug="gammatune"):
    db_path = tmp_path / f"{slug}.db"
    conn = init_db(db_path)
    M.create_song(conn, name=slug, key="C")
    conn.close()
    return db_path


def _write_probe(tmp_path, payload):
    p = tmp_path / "probe.json"
    p.write_text(json.dumps(payload))
    return p


def _events_of_kind(db_path, kind):
    conn = init_db(db_path)
    try:
        return conn.execute(
            "SELECT payload_json FROM events WHERE kind = ? ORDER BY seq", (kind,)
        ).fetchall()
    finally:
        conn.close()


def _run(tmp_path, db_path, probe, slug="gammatune"):
    return pull_cli.main(
        ["apply", "--song", slug, "--db", str(db_path), "--probe", str(probe)]
    )


def test_loaded_tuning_pulls_caches_and_persists(tmp_path, capsys):
    db_path = _song_db(tmp_path)
    probe = _write_probe(tmp_path, GAMMA_LOADED_RAW)

    assert _run(tmp_path, db_path, probe) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "pulled"
    assert report["tuning"]["name"] == "Wendy Carlos gamma"
    assert report["tuning"]["step_count"] == 20
    assert report["tuning"]["reference_note"] == 60
    assert report["tuning_ref"] == "tunings/wendy-carlos-gamma.ascl"
    assert "Tuning section" in report["reload_instruction"]

    # The cached .ascl is on disk under the song dir...
    assert (tmp_path / "tunings" / "wendy-carlos-gamma.ascl").is_file()
    # ...and the song row carries the ref + a blob that round-trips to the
    # verify-api-derived TuningData.
    conn = init_db(db_path)
    try:
        assert Q.get_song_tuning(conn, _only_song_id(conn))["tuning_ref"] == report["tuning_ref"]
        assert load_song_tuning(conn, _only_song_id(conn)) == GAMMA_EXPECTED
    finally:
        conn.close()


def test_pull_emits_exactly_one_tuning_event(tmp_path, capsys):
    db_path = _song_db(tmp_path)
    probe = _write_probe(tmp_path, GAMMA_LOADED_RAW)
    _run(tmp_path, db_path, probe)
    capsys.readouterr()
    assert len(_events_of_kind(db_path, E.SONG_TUNING_SET)) == 1


def test_re_pull_is_idempotent(tmp_path, capsys):
    db_path = _song_db(tmp_path)
    probe = _write_probe(tmp_path, GAMMA_LOADED_RAW)

    _run(tmp_path, db_path, probe)
    first = (tmp_path / "tunings" / "wendy-carlos-gamma.ascl").read_bytes()
    capsys.readouterr()

    assert _run(tmp_path, db_path, probe) == 0
    second = (tmp_path / "tunings" / "wendy-carlos-gamma.ascl").read_bytes()

    # The immutable cache overwrites byte-identically, and set_song_tuning is a
    # no-op on the identical second write → still exactly one event.
    assert first == second
    assert len(_events_of_kind(db_path, E.SONG_TUNING_SET)) == 1


def test_no_tuning_loaded_is_a_clean_no_op(tmp_path, capsys):
    db_path = _song_db(tmp_path)
    probe = _write_probe(tmp_path, {"type": "NoneType", "value": None})

    assert _run(tmp_path, db_path, probe) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "no-tuning-loaded"
    assert report["tuning_ref"] is None
    # No tuning was written, and no event emitted.
    assert _events_of_kind(db_path, E.SONG_TUNING_SET) == []
    assert not (tmp_path / "tunings").exists()


def test_no_tuning_loaded_does_not_clear_an_existing_tuning(tmp_path, capsys):
    # Pulling with nothing loaded is an "I forgot to load it" slip, not intent to
    # revert to 12-TET — a previously captured tuning must survive.
    db_path = _song_db(tmp_path)
    _run(tmp_path, db_path, _write_probe(tmp_path, GAMMA_LOADED_RAW))
    capsys.readouterr()

    none_probe = tmp_path / "none.json"
    none_probe.write_text(json.dumps({"type": "NoneType", "value": None}))
    assert pull_cli.main(
        ["apply", "--song", "gammatune", "--db", str(db_path), "--probe", str(none_probe)]
    ) == 0
    capsys.readouterr()

    conn = init_db(db_path)
    try:
        assert load_song_tuning(conn, _only_song_id(conn)) == GAMMA_EXPECTED
    finally:
        conn.close()


def test_unknown_song_errors(tmp_path):
    db_path = _song_db(tmp_path)
    probe = _write_probe(tmp_path, GAMMA_LOADED_RAW)
    with pytest.raises(SystemExit, match="no song named"):
        pull_cli.main(
            ["apply", "--song", "ghost", "--db", str(db_path), "--probe", str(probe)]
        )


def test_malformed_probe_raises(tmp_path):
    db_path = _song_db(tmp_path)
    bad = {k: v for k, v in GAMMA_LOADED_RAW.items() if k != "reference_pitch"}
    probe = _write_probe(tmp_path, bad)
    with pytest.raises(TuningReadError, match="reference_pitch"):
        _run(tmp_path, db_path, probe)


def _only_song_id(conn):
    return conn.execute("SELECT id FROM songs").fetchone()["id"]
