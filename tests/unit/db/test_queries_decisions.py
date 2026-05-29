"""Tests for Q.find_related_decisions — compose-time provenance retrieval.

Searches the compose-time audit log (requests.prompt_text and
requests.metadata_json) for keyword matches scoped to one song.
Multi-keyword is AND-of-keywords on each row. Durable prose-shaped
composer intent lives in the markdown corpus (/song-context), not here.
"""
from __future__ import annotations

import time

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "decisions.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="song-a", key="Dm")


@pytest.fixture
def other_song(conn):
    return M.create_song(conn, name="song-b", key="F")


def _seed_request(conn, song_id, *, intent, prompt_text, metadata=None):
    rid = M.create_request(
        conn, actor="llm", intent=intent, song_id=song_id, kind="compose",
        prompt_text=prompt_text, metadata=metadata,
    )
    M.close_request(conn, request_id=rid, outcome="ok")
    return rid


def test_empty_db_returns_empty_list(conn, song):
    assert Q.find_related_decisions(conn, song, keywords=["bridge"]) == []


def test_empty_keywords_returns_empty_list(conn, song):
    """Empty keyword list is a no-op — broad listing is what
    list_requests_for_song is for."""
    _seed_request(conn, song, intent="r", prompt_text="rework the bridge")
    assert Q.find_related_decisions(conn, song, keywords=[]) == []


def test_finds_request_by_prompt_text(conn, song):
    rid = _seed_request(
        conn, song, intent="compose-bridge",
        prompt_text="add a counter-melody to the bridge in dim7",
    )
    rows = Q.find_related_decisions(conn, song, keywords=["bridge"])
    assert len(rows) == 1
    assert rows[0]["id"] == rid
    assert "bridge" in rows[0]["prompt_text"]
    assert rows[0]["intent"] == "compose-bridge"


def test_finds_request_by_decision_rationale_in_metadata(conn, song):
    """The load-bearing convention: LLM writes its reasoning into
    requests.metadata_json.decision_rationale. The search has to find
    it even though it's nested in JSON — LIKE on the serialized JSON
    is the v1.0 floor."""
    rid = _seed_request(
        conn, song, intent="compose-chorus",
        prompt_text="make it brighter",
        metadata={
            "model": "claude-opus-4-7",
            "decision_rationale": (
                "Added a high-pass at 200Hz on the pad chain to "
                "open up the upper register without thinning the bass"
            ),
        },
    )
    # Searches for a word that's ONLY in decision_rationale, not in
    # prompt_text — proves the metadata JSON gets scanned.
    rows = Q.find_related_decisions(conn, song, keywords=["high-pass"])
    assert len(rows) == 1
    assert rows[0]["id"] == rid


def test_and_of_keywords(conn, song):
    """Multi-keyword is AND, not OR. A request matching only one keyword
    is filtered out — every keyword must appear in the row."""
    rid1 = _seed_request(
        conn, song, intent="r1",
        prompt_text="rework the bridge counter-melody",
    )
    _seed_request(
        conn, song, intent="r2",
        prompt_text="add a new chorus section",  # no 'bridge'
    )
    rows = Q.find_related_decisions(
        conn, song, keywords=["bridge", "counter-melody"],
    )
    assert len(rows) == 1
    assert rows[0]["id"] == rid1


def test_song_scoping_prevents_cross_song_leak(conn, song, other_song):
    """Decisions on song B don't surface in a song A query — load-bearing
    for cross-song reuse (project_cross_song_reuse memory)."""
    _seed_request(
        conn, other_song, intent="compose-bridge",
        prompt_text="rework the bridge in dim7",
    )
    _seed_request(
        conn, other_song, intent="note-bridge",
        prompt_text="the bridge is the only minor section",
    )
    assert Q.find_related_decisions(conn, song, keywords=["bridge"]) == []
    # Sanity: the other song's query DOES find them.
    rows = Q.find_related_decisions(conn, other_song, keywords=["bridge"])
    assert len(rows) == 2


def test_orders_most_recent_first(conn, song):
    """Rows order by ts DESC so the most-recent work is at the top."""
    rid_old = _seed_request(conn, song, intent="r1", prompt_text="bridge v1")
    time.sleep(0.005)
    rid_mid = _seed_request(conn, song, intent="r2", prompt_text="ease the bridge")
    time.sleep(0.005)
    rid_new = _seed_request(conn, song, intent="r3", prompt_text="bridge final")
    rows = Q.find_related_decisions(conn, song, keywords=["bridge"])
    ids = [r["id"] for r in rows]
    assert ids == [rid_new, rid_mid, rid_old]


def test_limit_caps_result_count(conn, song):
    for i in range(10):
        _seed_request(conn, song, intent=f"r{i}", prompt_text=f"bridge iteration {i}")
    rows = Q.find_related_decisions(conn, song, keywords=["bridge"], limit=3)
    assert len(rows) == 3


def test_keyword_match_is_case_insensitive_on_substring(conn, song):
    """SQLite LIKE is case-insensitive by default for ASCII — the search
    finds 'Bridge' when queried for 'bridge'. Pinning this so a future
    PRAGMA flip doesn't quietly break compose-time retrieval."""
    _seed_request(
        conn, song, intent="r",
        prompt_text="The Bridge needs a counter-melody",
    )
    rows = Q.find_related_decisions(conn, song, keywords=["bridge"])
    assert len(rows) == 1
