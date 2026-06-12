"""WFL-7Q2N: session-ID auto-discovery — resolver matrix + CLI wiring.

The resolver's contract: explicit id wins untouched; omitted id resolves to
the only session, or the most recent of several (always echoed on stderr,
alternatives listed); zero sessions and multi-song DBs are actionable
errors, never guesses.
"""
from __future__ import annotations

import json

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.sync import push_cli
from hallucinote.sync.session_resolve import resolve_session_id


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "t.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


def test_explicit_id_passes_through_untouched(conn, song, capsys):
    sid = M.create_ableton_session(conn, song_id=song, name="draft")
    assert resolve_session_id(conn, sid, prog="x") == sid
    # No echo for explicit ids — nothing was decided on the user's behalf.
    assert capsys.readouterr().err == ""


def test_only_session_auto_selected_and_echoed(conn, song, capsys):
    sid = M.create_ableton_session(conn, song_id=song, name="draft")
    assert resolve_session_id(conn, None, prog="push_cli phases") == sid
    err = capsys.readouterr().err
    assert sid in err
    assert "only session" in err


def test_most_recent_of_several_chosen_with_alternatives_listed(
    conn, song, capsys,
):
    older = M.create_ableton_session(conn, song_id=song, name="draft")
    # created_at has ms resolution; force distinct ordering explicitly so the
    # test doesn't depend on wall-clock granularity.
    newer = M.create_ableton_session(conn, song_id=song, name="render")
    conn.execute(
        "UPDATE ableton_sessions SET created_at = '2099-01-01T00:00:00.000Z' "
        "WHERE id = ?",
        (newer,),
    )
    assert resolve_session_id(conn, None, prog="push_cli execute") == newer
    err = capsys.readouterr().err
    assert "most recent of 2" in err
    assert newer in err
    assert "alternative" in err
    assert older in err


def test_plan_session_preferred_when_id_omitted(conn, song, capsys):
    """An apply command handed a plan file binds to the plan's session, not
    most-recent — the plan was produced against that session."""
    older = M.create_ableton_session(conn, song_id=song, name="draft")
    newer = M.create_ableton_session(conn, song_id=song, name="render")
    conn.execute(
        "UPDATE ableton_sessions SET created_at = '2099-01-01T00:00:00.000Z' "
        "WHERE id = ?",
        (newer,),
    )
    got = resolve_session_id(
        conn, None, prog="push_cli apply", plan_session_id=older,
    )
    assert got == older
    assert "taken from the plan file" in capsys.readouterr().err


def test_explicit_id_conflicting_with_plan_session_is_refused(conn, song):
    a = M.create_ableton_session(conn, song_id=song, name="a")
    b = M.create_ableton_session(conn, song_id=song, name="b")
    with pytest.raises(SystemExit) as exc:
        resolve_session_id(
            conn, a, prog="pull_cli apply", plan_session_id=b,
        )
    assert "conflicts with the plan file" in str(exc.value)


def test_explicit_id_matching_plan_session_passes(conn, song, capsys):
    a = M.create_ableton_session(conn, song_id=song, name="a")
    assert resolve_session_id(
        conn, a, prog="pull_cli apply", plan_session_id=a,
    ) == a
    assert capsys.readouterr().err == ""


def test_no_sessions_is_actionable_error(conn, song):
    with pytest.raises(SystemExit) as exc:
        resolve_session_id(conn, None, prog="push_cli phases")
    assert "--auto-session" in str(exc.value)


def test_multi_song_db_refuses_to_guess(conn):
    song_a = M.create_song(conn, name="a", key="C")
    song_b = M.create_song(conn, name="b", key="G")
    M.create_ableton_session(conn, song_id=song_a, name="a-draft")
    M.create_ableton_session(conn, song_id=song_b, name="b-draft")
    with pytest.raises(SystemExit) as exc:
        resolve_session_id(conn, None, prog="push_cli phases")
    msg = str(exc.value)
    assert "2 different songs" in msg
    assert "a-draft" in msg and "b-draft" in msg


# ---------------------------------------------------------------------------
# CLI wiring — the daily-loop commands resolve without a positional id
# ---------------------------------------------------------------------------


def test_push_cli_phases_resolves_without_session_id(
    tmp_path, capsys, monkeypatch,
):
    db = tmp_path / "song.db"
    conn = init_db(db)
    song = M.create_song(conn, name="t", key="Dm")
    sid = M.create_ableton_session(conn, song_id=song, name="draft")
    conn.commit()
    conn.close()

    rc = push_cli.main(["phases", "--db", str(db)])
    assert rc == 0
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["session_id"] == sid
    assert sid in captured.err  # the auto-selection is echoed


def test_push_cli_phases_explicit_id_still_works(tmp_path, capsys):
    db = tmp_path / "song.db"
    conn = init_db(db)
    song = M.create_song(conn, name="t", key="Dm")
    sid = M.create_ableton_session(conn, song_id=song, name="draft")
    conn.commit()
    conn.close()

    rc = push_cli.main(["phases", sid, "--db", str(db)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["session_id"] == sid
