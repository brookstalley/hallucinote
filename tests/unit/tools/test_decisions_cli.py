"""Tests for tools/decisions_cli.py — the `/decisions` skill's CLI surface.

The query layer is exercised by tests/unit/db/test_queries_decisions.py;
this file pins the CLI shape (argparse, output formatting, exit codes).
"""
from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

from hallucinote.db import init_db, mutations as M

from tools.decisions_cli import main as decisions_main


@pytest.fixture
def db_with_song(tmp_path):
    """Empty song DB at a known path. Returns (db_path, conn, song_id)."""
    db_path = tmp_path / "song.db"
    conn = init_db(db_path)
    sid = M.create_song(conn, name="tunesong", key="Dm")
    return db_path, conn, sid


def _run(*argv) -> tuple[int, str, str]:
    """Invoke the CLI's main(), capturing stdout / stderr."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = decisions_main(list(argv))
    return rc, out.getvalue(), err.getvalue()


def test_no_topic_or_keywords_errors_with_usage_message(db_with_song):
    db_path, conn, _ = db_with_song
    conn.close()
    rc, _out, err = _run("--db", str(db_path))
    assert rc == 2
    assert "topic" in err.lower() or "keywords" in err.lower()


def test_topic_and_keywords_together_errors(db_with_song):
    db_path, conn, _ = db_with_song
    conn.close()
    rc, _out, err = _run("--db", str(db_path), "bridge", "--keywords", "bass")
    assert rc == 2
    assert "topic" in err.lower() and "keywords" in err.lower()


def test_missing_db_returns_exit_1(tmp_path):
    rc, _out, err = _run("--db", str(tmp_path / "nope.db"), "bridge")
    assert rc == 1
    assert "DB not found" in err


def test_empty_db_emits_no_matching_decisions(db_with_song):
    db_path, conn, _ = db_with_song
    conn.close()
    rc, out, _err = _run("--db", str(db_path), "bridge")
    assert rc == 0
    assert "no matching decisions" in out


def test_request_with_prompt_renders_as_markdown_section(db_with_song):
    db_path, conn, sid = db_with_song
    rid = M.create_request(
        conn, actor="llm", intent="compose-bridge", song_id=sid,
        kind="compose",
        prompt_text="add a counter-melody to the bridge in dim7",
    )
    M.close_request(conn, request_id=rid, outcome="ok")
    conn.close()
    rc, out, _err = _run("--db", str(db_path), "bridge")
    assert rc == 0
    assert "### request" in out
    assert rid in out
    assert "counter-melody" in out
    assert "compose-bridge" in out  # intent surfaced


def test_request_with_decision_rationale_surfaces_rationale_section(db_with_song):
    db_path, conn, sid = db_with_song
    rid = M.create_request(
        conn, actor="llm", intent="compose-chorus", song_id=sid,
        kind="compose",
        prompt_text="make it brighter",
        metadata={
            "model": "claude-opus-4-7",
            "decision_rationale": (
                "Added high-pass at 200Hz on the pad chain to open up "
                "the upper register without thinning the bass"
            ),
        },
    )
    M.close_request(conn, request_id=rid, outcome="ok")
    conn.close()
    rc, out, _err = _run("--db", str(db_path), "high-pass")
    assert rc == 0
    assert "**Rationale:**" in out
    assert "200Hz" in out
    # Provenance bag's other keys must NOT leak into the rendered output —
    # only the load-bearing decision_rationale gets surfaced.
    assert "claude-opus-4-7" not in out


def test_keywords_flag_takes_comma_separated_list(db_with_song):
    db_path, conn, sid = db_with_song
    rid = M.create_request(
        conn, actor="llm", intent="r", song_id=sid, kind="compose",
        prompt_text="rework the bridge counter-melody",
    )
    M.close_request(conn, request_id=rid, outcome="ok")
    conn.close()
    rc, out, _err = _run(
        "--db", str(db_path), "--keywords", "bridge,counter-melody",
    )
    assert rc == 0
    assert rid in out


def test_positional_topic_splits_on_whitespace(db_with_song):
    db_path, conn, sid = db_with_song
    rid_match = M.create_request(
        conn, actor="llm", intent="r1", song_id=sid, kind="compose",
        prompt_text="rework the bridge counter-melody",
    )
    M.close_request(conn, request_id=rid_match, outcome="ok")
    rid_partial = M.create_request(
        conn, actor="llm", intent="r2", song_id=sid, kind="compose",
        prompt_text="add a chorus section",  # only matches one keyword
    )
    M.close_request(conn, request_id=rid_partial, outcome="ok")
    conn.close()
    rc, out, _err = _run("--db", str(db_path), "bridge counter-melody")
    assert rc == 0
    assert rid_match in out
    assert rid_partial not in out  # AND filter excludes it


def test_limit_flag_caps_output(db_with_song):
    db_path, conn, sid = db_with_song
    for i in range(5):
        rid = M.create_request(
            conn, actor="llm", intent=f"r{i}", song_id=sid, kind="compose",
            prompt_text=f"bridge iteration {i}",
        )
        M.close_request(conn, request_id=rid, outcome="ok")
    conn.close()
    rc, out, _err = _run("--db", str(db_path), "bridge", "--limit", "2")
    assert rc == 0
    # Count of "### request" sections should equal limit.
    assert out.count("### request") == 2


def test_song_flag_picks_specific_song(db_with_song):
    db_path, conn, sid = db_with_song
    other_sid = M.create_song(conn, name="other-song", key="F")
    rid = M.create_request(
        conn, actor="llm", intent="r", song_id=other_sid, kind="compose",
        prompt_text="rework the bridge in other-song",
    )
    M.close_request(conn, request_id=rid, outcome="ok")
    conn.close()
    rc, out, _err = _run(
        "--db", str(db_path), "bridge", "--song", "other-song",
    )
    assert rc == 0
    assert rid in out


def test_unknown_song_slug_returns_exit_1(db_with_song):
    db_path, conn, _ = db_with_song
    conn.close()
    rc, _out, err = _run("--db", str(db_path), "bridge", "--song", "ghost")
    assert rc == 1
    assert "no song" in err.lower()
