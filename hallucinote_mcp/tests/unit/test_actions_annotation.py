"""``ableton_annotation`` action surface.

Tests focus on the MCP-layer wrapping: schema correctness and the
song_slug → DB → song_id resolution path. The underlying W8-C mutators/
queries are covered in tests/unit/db/test_mutations.py — we don't re-test
their semantics here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from hallucinote.db import mutations as M
from hallucinote.db.connection import init_db
from hallucinote_mcp.handlers import ableton_annotation as annotation_handlers


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def song_db(tmp_path: Path) -> tuple[Path, str, str]:
    """Build a minimal per-song DB at a temp path: one song row + two tracks.

    Returns (db_path, song_id, slug). The slug matches the song's
    ``name`` column (handlers look up by name).
    """
    db_path = tmp_path / "fake-slug.db"
    conn = init_db(db_path)
    slug = "fake-slug"
    song_id = str(M.create_song(conn, name=slug))
    M.create_track(conn, song_id=song_id, track_index=1, name="Drums")
    M.create_track(conn, song_id=song_id, track_index=2, name="Bass")
    conn.commit()
    conn.close()
    return db_path, song_id, slug


@pytest.fixture(autouse=True)
def _route_resolver(song_db, monkeypatch):
    """Redirect ``_resolve_song_db`` to the test fixture's DB path for the
    duration of every test in this module — handlers think they're
    resolving a real songs/<slug>/ layout but actually use tmp_path.
    """
    db_path, _song_id, _slug = song_db
    monkeypatch.setattr(
        annotation_handlers, "_resolve_song_db", lambda _slug: db_path
    )


# ---------------------------------------------------------------------------
# Schema sanity
# ---------------------------------------------------------------------------


def test_action_registry_has_six_annotation_actions():
    from hallucinote_mcp import schema

    names = {a.name for a in schema.actions_for("ableton_annotation")}
    assert names == {"help", "add", "list", "get_at_bar", "update", "delete"}


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


def test_add_song_scoped_returns_dict_with_id(song_db):
    _db, song_id, slug = song_db
    result = annotation_handlers.add_handler(
        None,
        song_slug=slug,
        kind="intent",
        body="this song is sad",
    )
    assert "error" not in result
    assert result["body"] == "this song is sad"
    assert result["kind"] == "intent"
    assert result["song_id"] == song_id
    # Song-scoped: track + bars all NULL.
    assert result["track_id"] is None
    assert result["start_bar"] is None
    assert result["end_bar"] is None


def test_add_time_scoped_writes_bar_range(song_db):
    _db, _song_id, slug = song_db
    result = annotation_handlers.add_handler(
        None,
        song_slug=slug,
        kind="stylistic",
        body="bloom the reverb here",
        start_bar=16.0,
        end_bar=24.0,
    )
    assert result["start_bar"] == 16.0
    assert result["end_bar"] == 24.0
    assert result["track_id"] is None


def test_add_track_scoped_resolves_index_to_id(song_db):
    _db, song_id, slug = song_db
    result = annotation_handlers.add_handler(
        None,
        song_slug=slug,
        kind="structure",
        body="play softer on the bridge",
        track_index=2,
    )
    assert result["track_id"] is not None
    # Resolution sanity: round-trip via the queries layer.
    import sqlite3
    db_path = annotation_handlers._resolve_song_db(slug)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    track_row = conn.execute(
        "SELECT name FROM tracks WHERE id = ?", (result["track_id"],)
    ).fetchone()
    conn.close()
    assert track_row["name"] == "Bass"


def test_add_unknown_track_index_returns_teaching_error(song_db):
    _db, _song_id, slug = song_db
    result = annotation_handlers.add_handler(
        None,
        song_slug=slug,
        kind="todo",
        body="nope",
        track_index=99,
    )
    assert "error" in result
    assert "no track at index 99" in result["error"]
    assert "ableton_track(action='list')" in result["error"]


def test_add_unknown_slug_returns_teaching_error(tmp_path: Path, monkeypatch):
    """Override the resolver to point at a path that doesn't exist."""
    bogus = tmp_path / "does-not-exist.db"
    monkeypatch.setattr(
        annotation_handlers, "_resolve_song_db", lambda _slug: bogus
    )
    result = annotation_handlers.add_handler(
        None,
        song_slug="ghost-song",
        kind="intent",
        body="x",
    )
    assert "error" in result
    assert "ghost-song" in result["error"]


def test_add_rejects_invalid_kind_via_w8c_mutator(song_db):
    """Invalid kind reaches M.add_annotation, which raises; the dispatcher
    layer would translate that. Here at the handler level we expect a
    raised ValueError — the dispatcher's existing try/except catches it
    in the actual MCP flow."""
    _db, _song_id, slug = song_db
    with pytest.raises(ValueError, match="invalid annotation kind"):
        annotation_handlers.add_handler(
            None, song_slug=slug, kind="bogus", body="x"
        )


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_returns_annotations_in_canonical_order(song_db):
    _db, _song_id, slug = song_db
    annotation_handlers.add_handler(None, song_slug=slug, kind="intent", body="song A")
    annotation_handlers.add_handler(
        None, song_slug=slug, kind="structure", body="time A", start_bar=4.0
    )
    annotation_handlers.add_handler(
        None, song_slug=slug, kind="stylistic", body="time B", start_bar=12.0
    )
    result = annotation_handlers.list_handler(None, song_slug=slug)
    bodies = [a["body"] for a in result["annotations"]]
    # Song-scoped first, then time-scoped by start_bar.
    assert bodies == ["song A", "time A", "time B"]


def test_list_filters_by_kind(song_db):
    _db, _song_id, slug = song_db
    annotation_handlers.add_handler(None, song_slug=slug, kind="intent", body="i1")
    annotation_handlers.add_handler(None, song_slug=slug, kind="todo", body="t1")
    annotation_handlers.add_handler(None, song_slug=slug, kind="intent", body="i2")
    result = annotation_handlers.list_handler(None, song_slug=slug, kind="todo")
    assert {a["body"] for a in result["annotations"]} == {"t1"}


# ---------------------------------------------------------------------------
# get_at_bar
# ---------------------------------------------------------------------------


def test_get_at_bar_returns_overlapping_and_song_scoped(song_db):
    _db, _song_id, slug = song_db
    annotation_handlers.add_handler(None, song_slug=slug, kind="intent", body="always")
    annotation_handlers.add_handler(
        None,
        song_slug=slug,
        kind="stylistic",
        body="bars 4-12",
        start_bar=4.0,
        end_bar=12.0,
    )
    annotation_handlers.add_handler(
        None,
        song_slug=slug,
        kind="stylistic",
        body="bars 20-28",
        start_bar=20.0,
        end_bar=28.0,
    )
    result = annotation_handlers.get_at_bar_handler(None, song_slug=slug, bar=8.0)
    bodies = {a["body"] for a in result["annotations"]}
    assert bodies == {"always", "bars 4-12"}


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


def test_update_patches_body_only(song_db):
    _db, _song_id, slug = song_db
    created = annotation_handlers.add_handler(
        None, song_slug=slug, kind="intent", body="original"
    )
    result = annotation_handlers.update_handler(
        None,
        song_slug=slug,
        annotation_id=created["id"],
        body="revised",
    )
    assert result["body"] == "revised"
    assert result["kind"] == "intent"  # unchanged


def test_update_with_no_fields_returns_teaching_error(song_db):
    _db, _song_id, slug = song_db
    created = annotation_handlers.add_handler(
        None, song_slug=slug, kind="intent", body="x"
    )
    result = annotation_handlers.update_handler(
        None, song_slug=slug, annotation_id=created["id"]
    )
    assert "error" in result
    assert "at least one of" in result["error"]


def test_update_unknown_id_returns_teaching_error(song_db):
    _db, _song_id, slug = song_db
    result = annotation_handlers.update_handler(
        None,
        song_slug=slug,
        annotation_id="0" * 32,
        body="x",
    )
    assert "error" in result
    assert "no annotation with id" in result["error"]


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_removes_annotation(song_db):
    _db, _song_id, slug = song_db
    created = annotation_handlers.add_handler(
        None, song_slug=slug, kind="intent", body="going away"
    )
    result = annotation_handlers.delete_handler(
        None, song_slug=slug, annotation_id=created["id"]
    )
    assert result["deleted"] is True
    listed = annotation_handlers.list_handler(None, song_slug=slug)
    assert listed["annotations"] == []


def test_delete_unknown_id_is_idempotent(song_db):
    """M.delete_annotation is documented as no-op on missing id; the
    handler must surface that as a clean success, not an error."""
    _db, _song_id, slug = song_db
    result = annotation_handlers.delete_handler(
        None, song_slug=slug, annotation_id="0" * 32
    )
    assert result["deleted"] is True
    assert "error" not in result
