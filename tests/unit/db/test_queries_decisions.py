"""Tests for Q.find_related_decisions — compose-time provenance retrieval.

Searches three sources (requests.prompt_text, requests.metadata_json,
annotations.body) for keyword matches scoped to one song. Multi-keyword
is AND-of-keywords on each row. Each result row carries a synthetic
`source` column (`'request'` or `'annotation'`) so the formatter can
route rendering.
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


def test_empty_db_returns_empty_list(conn, song):
    assert Q.find_related_decisions(conn, song, keywords=["bridge"]) == []


def test_empty_keywords_returns_empty_list(conn, song):
    """Empty keyword list is a no-op — broad listing is what
    list_requests_for_song / get_annotations_for_song are for."""
    M.add_annotation(conn, song_id=song, kind="intent", body="bridge in dim7")
    assert Q.find_related_decisions(conn, song, keywords=[]) == []


def test_finds_request_by_prompt_text(conn, song):
    rid = M.create_request(
        conn, actor="llm", intent="compose-bridge",
        song_id=song, kind="compose",
        prompt_text="add a counter-melody to the bridge in dim7",
    )
    M.close_request(conn, request_id=rid, outcome="ok")
    rows = Q.find_related_decisions(conn, song, keywords=["bridge"])
    assert len(rows) == 1
    assert rows[0]["source"] == "request"
    assert rows[0]["id"] == rid
    assert "bridge" in rows[0]["prompt_text"]
    # Annotation-only columns are NULL on request rows.
    assert rows[0]["body"] is None
    assert rows[0]["track_id"] is None


def test_finds_request_by_decision_rationale_in_metadata(conn, song):
    """The load-bearing convention: LLM writes its reasoning into
    requests.metadata_json.decision_rationale. The search has to find
    it even though it's nested in JSON — LIKE on the serialized JSON
    is the v1.0 floor."""
    rid = M.create_request(
        conn, actor="llm", intent="compose-chorus",
        song_id=song, kind="compose",
        prompt_text="make it brighter",
        metadata={
            "model": "claude-opus-4-7",
            "decision_rationale": (
                "Added a high-pass at 200Hz on the pad chain to "
                "open up the upper register without thinning the bass"
            ),
        },
    )
    M.close_request(conn, request_id=rid, outcome="ok")
    # Searches for a word that's ONLY in decision_rationale, not in
    # prompt_text — proves the metadata JSON gets scanned.
    rows = Q.find_related_decisions(conn, song, keywords=["high-pass"])
    assert len(rows) == 1
    assert rows[0]["source"] == "request"


def test_finds_annotation_by_body(conn, song):
    aid = M.add_annotation(
        conn, song_id=song, kind="intent",
        body="don't sidechain the bass on the bridge — let it bloom",
    )
    rows = Q.find_related_decisions(conn, song, keywords=["sidechain"])
    assert len(rows) == 1
    assert rows[0]["source"] == "annotation"
    assert rows[0]["id"] == aid
    assert "sidechain" in rows[0]["body"]
    # Request-only columns are NULL on annotation rows.
    assert rows[0]["prompt_text"] is None
    assert rows[0]["metadata_json"] is None


def test_multi_source_keyword_returns_both_with_correct_source_tag(conn, song):
    rid = M.create_request(
        conn, actor="llm", intent="compose-bridge",
        song_id=song, kind="compose",
        prompt_text="rework the bridge",
    )
    M.close_request(conn, request_id=rid, outcome="ok")
    M.add_annotation(
        conn, song_id=song, kind="structure",
        body="the bridge is the only minor section",
    )
    rows = Q.find_related_decisions(conn, song, keywords=["bridge"])
    sources = sorted(r["source"] for r in rows)
    assert sources == ["annotation", "request"]


def test_and_of_keywords(conn, song):
    """Multi-keyword is AND, not OR. A request matching only one keyword
    is filtered out — every keyword must appear in the row."""
    rid1 = M.create_request(
        conn, actor="llm", intent="r1", song_id=song, kind="compose",
        prompt_text="rework the bridge counter-melody",
    )
    M.close_request(conn, request_id=rid1, outcome="ok")
    rid2 = M.create_request(
        conn, actor="llm", intent="r2", song_id=song, kind="compose",
        prompt_text="add a new chorus section",  # no 'bridge'
    )
    M.close_request(conn, request_id=rid2, outcome="ok")
    rows = Q.find_related_decisions(
        conn, song, keywords=["bridge", "counter-melody"],
    )
    assert len(rows) == 1
    assert rows[0]["id"] == rid1


def test_song_scoping_prevents_cross_song_leak(conn, song, other_song):
    """Decisions on song B don't surface in a song A query — load-bearing
    for cross-song reuse (project_cross_song_reuse memory)."""
    rid = M.create_request(
        conn, actor="llm", intent="compose-bridge",
        song_id=other_song, kind="compose",
        prompt_text="rework the bridge in dim7",
    )
    M.close_request(conn, request_id=rid, outcome="ok")
    M.add_annotation(
        conn, song_id=other_song, kind="intent",
        body="the bridge is sad like weight getting worse",
    )
    assert Q.find_related_decisions(conn, song, keywords=["bridge"]) == []
    # Sanity: the other song's query DOES find them.
    rows = Q.find_related_decisions(conn, other_song, keywords=["bridge"])
    assert len(rows) == 2


def test_orders_most_recent_first_across_types(conn, song):
    """Both sources share a sort_ts column (requests.ts vs
    annotations.created_at); ORDER BY sort_ts DESC interleaves them
    correctly so the most-recent work is at the top."""
    aid_old = M.add_annotation(
        conn, song_id=song, kind="intent", body="bridge feel: heavy",
    )
    time.sleep(0.005)
    rid_mid = M.create_request(
        conn, actor="llm", intent="compose", song_id=song, kind="compose",
        prompt_text="ease the bridge",
    )
    M.close_request(conn, request_id=rid_mid, outcome="ok")
    time.sleep(0.005)
    aid_new = M.add_annotation(
        conn, song_id=song, kind="intent", body="bridge final: bittersweet",
    )
    rows = Q.find_related_decisions(conn, song, keywords=["bridge"])
    ids = [r["id"] for r in rows]
    assert ids == [aid_new, rid_mid, aid_old]


def test_limit_caps_result_count(conn, song):
    for i in range(10):
        rid = M.create_request(
            conn, actor="llm", intent=f"r{i}", song_id=song, kind="compose",
            prompt_text=f"bridge iteration {i}",
        )
        M.close_request(conn, request_id=rid, outcome="ok")
    rows = Q.find_related_decisions(conn, song, keywords=["bridge"], limit=3)
    assert len(rows) == 3


def test_keyword_match_is_case_insensitive_on_substring(conn, song):
    """SQLite LIKE is case-insensitive by default for ASCII — the search
    finds 'Bridge' when queried for 'bridge'. Pinning this so a future
    PRAGMA flip doesn't quietly break compose-time retrieval."""
    rid = M.create_request(
        conn, actor="llm", intent="r", song_id=song, kind="compose",
        prompt_text="The Bridge needs a counter-melody",
    )
    M.close_request(conn, request_id=rid, outcome="ok")
    rows = Q.find_related_decisions(conn, song, keywords=["bridge"])
    assert len(rows) == 1
