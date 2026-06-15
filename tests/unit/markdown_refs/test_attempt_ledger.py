"""Attempt-ledger (kind: attempt) tests — ATL-7K3M.

Covers the new `kind: attempt` end to end: parse/validate (outcome + resolution),
disk reindex, write_markdown_ref round-trip, the stale-projection migration
(CHECK-domain change → drop-and-recreate), and the outcome query filter.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.markdown_refs import (
    KINDS,
    discover_song_corpus,
    parse_frontmatter,
    reindex_corpus,
    write_markdown_ref,
)


# ---------------------------------------------------------------------------
# Parser / validation (no DB)
# ---------------------------------------------------------------------------


def test_attempt_is_a_valid_kind():
    assert "attempt" in KINDS


def test_parses_attempt_with_outcome_and_resolution():
    text = (
        "---\n"
        "date: 2026-06-14\n"
        "kind: attempt\n"
        "scope: track\n"
        "track: Bagpipes\n"
        "outcome: failed\n"
        "resolution: reverted\n"
        "tags: [mix, notch-filter, masking]\n"
        "related: [songs/highland/attempts/gate.md]\n"
        "---\n"
        "v12: notch at 2.2 kHz still let the chanter overwhelm the vocal. Reverted.\n"
    )
    fm, body = parse_frontmatter(text)
    assert fm.kind == "attempt"
    assert fm.scope == "track"
    assert fm.track == "Bagpipes"
    assert fm.outcome == "failed"
    assert fm.resolution == "reverted"
    assert fm.related == ["songs/highland/attempts/gate.md"]
    assert "notch" in body


def test_attempt_missing_outcome_raises():
    text = (
        "---\nkind: attempt\nscope: track\ntrack: B\nresolution: reverted\n---\nbody\n"
    )
    with pytest.raises(ValueError, match="attempt requires both 'outcome' and 'resolution'"):
        parse_frontmatter(text)


def test_attempt_missing_resolution_raises():
    text = "---\nkind: attempt\nscope: track\ntrack: B\noutcome: failed\n---\nbody\n"
    with pytest.raises(ValueError, match="attempt requires both 'outcome' and 'resolution'"):
        parse_frontmatter(text)


def test_attempt_invalid_outcome_raises():
    text = (
        "---\nkind: attempt\nscope: track\ntrack: B\n"
        "outcome: meh\nresolution: reverted\n---\nbody\n"
    )
    with pytest.raises(ValueError, match="invalid outcome 'meh'"):
        parse_frontmatter(text)


def test_attempt_invalid_resolution_raises():
    text = (
        "---\nkind: attempt\nscope: track\ntrack: B\n"
        "outcome: failed\nresolution: yeeted\n---\nbody\n"
    )
    with pytest.raises(ValueError, match="invalid resolution 'yeeted'"):
        parse_frontmatter(text)


def test_outcome_on_non_attempt_kind_raises():
    text = "---\nkind: annotation\nscope: song\noutcome: worked\n---\nbody\n"
    with pytest.raises(ValueError, match="valid only on kind 'attempt'"):
        parse_frontmatter(text)


def test_resolution_on_non_attempt_kind_raises():
    text = (
        "---\ndate: 2026-06-14\nkind: decision\nscope: song\n"
        "resolution: kept\n---\nbody\n"
    )
    with pytest.raises(ValueError, match="valid only on kind 'attempt'"):
        parse_frontmatter(text)


# ---------------------------------------------------------------------------
# Disk reindex + query (DB-backed)
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path):
    songs_root = tmp_path / "songs"
    songs_root.mkdir()
    conn = init_db(tmp_path / "test.db")
    yield conn, tmp_path
    conn.close()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _attempt_doc(*, body: str, track: str, outcome: str, resolution: str,
                 **extra) -> str:
    lines = [
        "date: 2026-06-14", "kind: attempt", "scope: track",
        f"track: {track}", f"outcome: {outcome}", f"resolution: {resolution}",
    ]
    for k, v in extra.items():
        lines.append(f"{k}: {v}")
    return "---\n" + "\n".join(lines) + f"\n---\n{body}\n"


def test_discover_song_corpus_includes_attempts(tmp_path: Path):
    song = tmp_path / "songs" / "s"
    (song / "attempts").mkdir(parents=True)
    (song / "decisions").mkdir()
    (song / "attempts" / "a.md").write_text("x", encoding="utf-8")
    (song / "decisions" / "d.md").write_text("y", encoding="utf-8")
    names = {p.name for p in discover_song_corpus(song)}
    assert "a.md" in names and "d.md" in names
    assert any("attempts" in str(p) for p in discover_song_corpus(song))


def test_attempt_reindexes_with_outcome_and_is_searchable(repo):
    conn, root = repo
    M.create_song(conn, name="highland", key="Em")
    _write(
        root / "songs/highland/attempts/notch.md",
        _attempt_doc(
            body="notch filter on the bagpipes still overwhelmed the vocal",
            track="Bagpipes", outcome="failed", resolution="reverted",
            tags="[mix, notch-filter]",
        ),
    )
    counts = reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    assert counts["upserted"] == 1

    rows = Q.find_markdown_refs(conn, kind="attempt")
    assert len(rows) == 1
    assert rows[0]["outcome"] == "failed"
    assert rows[0]["resolution"] == "reverted"
    # FTS body search reaches an attempt row.
    hits = Q.find_markdown_refs(conn, fulltext="bagpipes")
    assert any(r["kind"] == "attempt" for r in hits)


def test_find_markdown_refs_filters_by_outcome(repo):
    conn, root = repo
    M.create_song(conn, name="s", key="C")
    _write(root / "songs/s/attempts/a.md",
           _attempt_doc(body="reverted", track="B", outcome="failed",
                        resolution="reverted"))
    _write(root / "songs/s/attempts/b.md",
           _attempt_doc(body="kept", track="B", outcome="worked",
                        resolution="kept"))
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)

    failed = Q.find_markdown_refs(conn, kind="attempt", outcome="failed")
    assert [r["path"] for r in failed] == ["songs/s/attempts/a.md"]
    assert len(Q.find_markdown_refs(conn, kind="attempt")) == 2


def test_write_markdown_ref_round_trips_an_attempt(repo):
    conn, root = repo
    M.create_song(conn, name="highland", key="Em")
    fm = {
        "date": "2026-06-14", "kind": "attempt", "scope": "track",
        "track": "Bagpipes", "outcome": "failed", "resolution": "superseded",
        "tags": ["mix", "notch-filter"],
        "related": ["songs/highland/attempts/gate.md"],
    }
    doc = write_markdown_ref(
        conn,
        path=Path("songs/highland/attempts/notch.md"),
        repo_root=root,
        body="v12 notch reverted; superseded by the gate.",
        frontmatter=fm,
    )
    assert doc.frontmatter.outcome == "failed"
    assert doc.frontmatter.resolution == "superseded"

    # Indexed immediately by the write path.
    rows = Q.find_markdown_refs(conn, kind="attempt")
    assert len(rows) == 1 and rows[0]["resolution"] == "superseded"

    # On disk and reparses cleanly (serialize round-trip).
    on_disk = (root / "songs/highland/attempts/notch.md").read_text("utf-8")
    fm2, _ = parse_frontmatter(on_disk)
    assert fm2.outcome == "failed" and fm2.resolution == "superseded"
    assert fm2.related == ["songs/highland/attempts/gate.md"]


# ---------------------------------------------------------------------------
# Migration: a pre-ATL markdown_refs (old CHECK, no outcome col) is rebuilt
# ---------------------------------------------------------------------------


def test_stale_markdown_refs_projection_is_rebuilt_for_attempt(tmp_path: Path):
    db = tmp_path / "legacy.db"
    conn = init_db(db)
    # Simulate a pre-ATL DB: replace markdown_refs with its OLD shape — the
    # kind CHECK lacks 'attempt' and there are no outcome/resolution columns.
    conn.execute("DROP TABLE markdown_refs")
    conn.execute("DROP TABLE IF EXISTS markdown_refs_fts")
    conn.execute(
        "CREATE TABLE markdown_refs ("
        "  path TEXT PRIMARY KEY,"
        "  kind TEXT NOT NULL CHECK (kind IN "
        "       ('decision', 'annotation', 'structural-fact')),"
        "  scope TEXT NOT NULL CHECK (scope IN "
        "       ('song', 'time', 'track', 'track-time')),"
        "  song_id TEXT, track_id TEXT, bars_json TEXT, tags_json TEXT,"
        "  related_json TEXT, frontmatter_date TEXT,"
        "  content_hash TEXT NOT NULL,"
        "  indexed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),"
        "  tombstoned_at TEXT)"
    )
    conn.commit()
    conn.close()

    # Reopen via init_db: the disposable-table rebuild must drop the stale
    # projection so schema.sql recreates the new shape.
    conn = init_db(db)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(markdown_refs)")}
    assert "outcome" in cols and "resolution" in cols

    # And an attempt row now inserts without a CHECK violation (old CHECK would
    # have rejected kind='attempt').
    conn.execute(
        "INSERT INTO markdown_refs "
        "(path, kind, scope, outcome, resolution, content_hash) "
        "VALUES ('songs/x/attempts/a.md','attempt','track','failed','reverted','h')"
    )
    conn.commit()
    row = conn.execute(
        "SELECT kind, outcome, resolution FROM markdown_refs"
    ).fetchone()
    assert row["kind"] == "attempt"
    assert row["outcome"] == "failed" and row["resolution"] == "reverted"
    conn.close()
