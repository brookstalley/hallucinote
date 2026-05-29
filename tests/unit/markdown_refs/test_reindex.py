"""Reindex tests — disk walk, upsert, tombstone, FTS5 search end-to-end."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.markdown_refs import reindex_corpus


@pytest.fixture
def repo(tmp_path: Path):
    """A synthetic mini-repo with a `songs/` tree + DB. Returns (conn, root)."""
    songs_root = tmp_path / "songs"
    songs_root.mkdir()
    conn = init_db(tmp_path / "test.db")
    yield conn, tmp_path
    conn.close()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_song(conn, name: str = "tunesong") -> str:
    return M.create_song(conn, name=name, key="Dm")


def _doc(kind: str, scope: str, *, body: str, **extra) -> str:
    fm_lines = [f"kind: {kind}", f"scope: {scope}"]
    for k, v in extra.items():
        fm_lines.append(f"{k}: {v}")
    fm = "\n".join(fm_lines)
    return f"---\n{fm}\n---\n{body}\n"


def test_reindex_creates_rows_for_corpus(repo):
    conn, root = repo
    song_id = _seed_song(conn)
    _write(
        root / "songs/tunesong/decisions/2026-01-01-foo.md",
        _doc("decision", "song", date="2026-01-01", body="The why."),
    )
    _write(
        root / "songs/tunesong/annotations/verse-feel.md",
        _doc("annotation", "song", body="Verse is sad."),
    )

    counts = reindex_corpus(conn, songs_root=root / "songs", repo_root=root)

    assert counts == {"upserted": 2, "tombstoned": 0, "unchanged": 0}
    rows = conn.execute(
        "SELECT path, kind, song_id FROM markdown_refs ORDER BY kind"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["kind"] == "annotation"
    assert rows[0]["path"].endswith("verse-feel.md")
    assert rows[0]["song_id"] == song_id
    assert rows[1]["kind"] == "decision"
    assert rows[1]["path"].endswith("2026-01-01-foo.md")


def test_single_song_reindex_scopes_to_that_song(repo):
    # Two songs on disk; a single-song reindex must index ONLY that song's
    # corpus (recall-on-read in /song-context relies on this — it doesn't
    # filter by song_id).
    conn, root = repo
    _seed_song(conn, "alpha")
    _seed_song(conn, "beta")
    _write(
        root / "songs/alpha/annotations/a.md",
        _doc("annotation", "song", body="alpha note"),
    )
    _write(
        root / "songs/beta/annotations/b.md",
        _doc("annotation", "song", body="beta note"),
    )
    counts = reindex_corpus(
        conn, song_dir=root / "songs/alpha", repo_root=root
    )
    assert counts == {"upserted": 1, "tombstoned": 0, "unchanged": 0}
    paths = [r["path"] for r in conn.execute("SELECT path FROM markdown_refs")]
    assert paths == ["songs/alpha/annotations/a.md"]


def test_single_song_reindex_does_not_tombstone_other_songs(repo):
    # Full reindex first (both songs indexed), then a single-song reindex of
    # alpha must NOT tombstone beta's rows.
    conn, root = repo
    _seed_song(conn, "alpha")
    _seed_song(conn, "beta")
    _write(root / "songs/alpha/annotations/a.md", _doc("annotation", "song", body="a"))
    _write(root / "songs/beta/annotations/b.md", _doc("annotation", "song", body="b"))
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    reindex_corpus(conn, song_dir=root / "songs/alpha", repo_root=root)
    live = conn.execute(
        "SELECT path FROM markdown_refs WHERE tombstoned_at IS NULL ORDER BY path"
    ).fetchall()
    assert [r["path"] for r in live] == [
        "songs/alpha/annotations/a.md",
        "songs/beta/annotations/b.md",
    ]


def test_reindex_requires_exactly_one_source(repo):
    conn, root = repo
    with pytest.raises(ValueError):
        reindex_corpus(conn, repo_root=root)
    with pytest.raises(ValueError):
        reindex_corpus(
            conn, songs_root=root / "songs", song_dir=root / "songs/x",
            repo_root=root,
        )


def test_reindex_is_idempotent(repo):
    conn, root = repo
    _seed_song(conn)
    _write(
        root / "songs/tunesong/annotations/x.md",
        _doc("annotation", "song", body="content"),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    counts = reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    assert counts == {"upserted": 0, "tombstoned": 0, "unchanged": 1}


def test_reindex_updates_changed_file(repo):
    conn, root = repo
    _seed_song(conn)
    path = root / "songs/tunesong/annotations/x.md"
    _write(path, _doc("annotation", "song", body="v1"))
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    _write(path, _doc("annotation", "song", body="v2 evolved"))
    counts = reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    assert counts["upserted"] == 1
    rows = conn.execute(
        "SELECT body FROM markdown_refs_fts WHERE path LIKE '%/x.md'"
    ).fetchall()
    assert len(rows) == 1
    assert "v2 evolved" in rows[0]["body"]


def test_reindex_tombstones_vanished_file(repo):
    conn, root = repo
    _seed_song(conn)
    path = root / "songs/tunesong/annotations/x.md"
    _write(path, _doc("annotation", "song", body="hello"))
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)

    path.unlink()
    counts = reindex_corpus(conn, songs_root=root / "songs", repo_root=root)

    assert counts["tombstoned"] == 1
    row = conn.execute(
        "SELECT tombstoned_at FROM markdown_refs WHERE path LIKE '%/x.md'"
    ).fetchone()
    assert row["tombstoned_at"] is not None
    # FTS5 no longer returns the row
    fts_rows = conn.execute(
        "SELECT * FROM markdown_refs_fts WHERE path LIKE '%/x.md'"
    ).fetchall()
    assert fts_rows == []


def test_reindex_revives_tombstoned_file(repo):
    conn, root = repo
    _seed_song(conn)
    path = root / "songs/tunesong/annotations/x.md"
    _write(path, _doc("annotation", "song", body="alive"))
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    path.unlink()
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    # restore
    _write(path, _doc("annotation", "song", body="returned"))
    counts = reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    assert counts["upserted"] == 1
    row = conn.execute(
        "SELECT tombstoned_at FROM markdown_refs WHERE path LIKE '%/x.md'"
    ).fetchone()
    assert row["tombstoned_at"] is None


def test_reindex_resolves_track_id_when_track_name_matches(repo):
    conn, root = repo
    song_id = _seed_song(conn)
    track_id = M.create_track(
        conn, song_id=song_id, track_index=1, name="03 Synth Bass",
        instrument_uri="x",
    )
    _write(
        root / "songs/tunesong/annotations/bass-feel.md",
        _doc(
            "annotation", "track", body="bass walks down",
            track="03 Synth Bass",
        ),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    row = conn.execute(
        "SELECT track_id FROM markdown_refs WHERE path LIKE '%/bass-feel.md'"
    ).fetchone()
    assert row["track_id"] == track_id


def test_reindex_leaves_track_id_null_when_track_not_found(repo):
    conn, root = repo
    _seed_song(conn)
    _write(
        root / "songs/tunesong/annotations/missing-track.md",
        _doc(
            "annotation", "track", body="x",
            track="99 Nonexistent",
        ),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    row = conn.execute(
        "SELECT track_id FROM markdown_refs WHERE path LIKE '%/missing-track.md'"
    ).fetchone()
    assert row["track_id"] is None


def test_reindex_parse_error_raises_before_writes(repo):
    conn, root = repo
    _seed_song(conn)
    _write(
        root / "songs/tunesong/annotations/good.md",
        _doc("annotation", "song", body="ok"),
    )
    _write(
        root / "songs/tunesong/annotations/broken.md",
        "---\nkind: annotation\nfeeling: sad\n---\nbody\n",
    )
    with pytest.raises(ValueError, match="failed to parse"):
        reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    # No writes happened
    count = conn.execute("SELECT COUNT(*) FROM markdown_refs").fetchone()[0]
    assert count == 0


def test_reindex_handles_song_id_resolution_for_unknown_song(repo):
    conn, root = repo
    # No song row created for "ghostsong"
    _write(
        root / "songs/ghostsong/annotations/x.md",
        _doc("annotation", "song", body="content"),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    row = conn.execute("SELECT song_id FROM markdown_refs").fetchone()
    assert row["song_id"] is None


def test_reindex_stores_bars_and_tags_as_json(repo):
    conn, root = repo
    _seed_song(conn)
    _write(
        root / "songs/tunesong/decisions/2026-05-26-something.md",
        _doc(
            "decision", "time", body="x",
            date="2026-05-26", bars="[33, 40]", tags="[dim7, bridge]",
        ),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    row = conn.execute(
        "SELECT bars_json, tags_json FROM markdown_refs"
    ).fetchone()
    assert json.loads(row["bars_json"]) == [33.0, 40.0]
    assert json.loads(row["tags_json"]) == ["dim7", "bridge"]


# ---------- query surface (FTS5 + filters) ----------


def test_find_by_fulltext_returns_snippet(repo):
    conn, root = repo
    _seed_song(conn)
    _write(
        root / "songs/tunesong/decisions/2026-05-26-bass.md",
        _doc(
            "decision", "song", body="The bass walks in fifths to bloom.",
            date="2026-05-26",
        ),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    rows = Q.find_markdown_refs(conn, fulltext="bloom")
    assert len(rows) == 1
    assert "<<bloom>>" in rows[0]["snippet"]


def test_find_by_kind(repo):
    conn, root = repo
    _seed_song(conn)
    _write(
        root / "songs/tunesong/decisions/2026-05-26-a.md",
        _doc("decision", "song", body="a", date="2026-05-26"),
    )
    _write(
        root / "songs/tunesong/annotations/b.md",
        _doc("annotation", "song", body="b"),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    rows = Q.find_markdown_refs(conn, kind="decision")
    assert len(rows) == 1
    assert rows[0]["path"].endswith("a.md")


def test_find_by_tags_contains_any(repo):
    conn, root = repo
    _seed_song(conn)
    _write(
        root / "songs/tunesong/annotations/x.md",
        _doc("annotation", "song", body="x", tags="[dim7, bridge]"),
    )
    _write(
        root / "songs/tunesong/annotations/y.md",
        _doc("annotation", "song", body="y", tags="[chorus]"),
    )
    _write(
        root / "songs/tunesong/annotations/z.md",
        _doc("annotation", "song", body="z", tags="[verse]"),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    rows = Q.find_markdown_refs(conn, tags=["bridge", "chorus"])
    paths = {r["path"] for r in rows}
    assert any(p.endswith("x.md") for p in paths)
    assert any(p.endswith("y.md") for p in paths)
    assert not any(p.endswith("z.md") for p in paths)


def test_find_by_bar_overlap_range_row(repo):
    conn, root = repo
    _seed_song(conn)
    _write(
        root / "songs/tunesong/annotations/a.md",
        _doc("annotation", "time", body="a", bars="[33, 40]"),
    )
    _write(
        root / "songs/tunesong/annotations/b.md",
        _doc("annotation", "time", body="b", bars="[10, 20]"),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    rows = Q.find_markdown_refs(conn, bars=(35.0, 50.0))
    assert len(rows) == 1
    assert rows[0]["path"].endswith("a.md")


def test_find_by_bar_overlap_point_row(repo):
    conn, root = repo
    _seed_song(conn)
    _write(
        root / "songs/tunesong/annotations/p.md",
        _doc("annotation", "time", body="p", bars="[33]"),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    rows = Q.find_markdown_refs(conn, bars=(30.0, 40.0))
    assert len(rows) == 1
    rows = Q.find_markdown_refs(conn, bars=(40.0, 50.0))
    assert rows == []


def test_find_excludes_tombstoned_by_default(repo):
    conn, root = repo
    _seed_song(conn)
    path = root / "songs/tunesong/annotations/x.md"
    _write(path, _doc("annotation", "song", body="hi"))
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    path.unlink()
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    assert Q.find_markdown_refs(conn) == []
    rows = Q.find_markdown_refs(conn, include_tombstoned=True)
    assert len(rows) == 1


def test_find_orders_by_frontmatter_date_desc(repo):
    conn, root = repo
    _seed_song(conn)
    for d in ("2026-01-01", "2026-05-26", "2026-03-15"):
        _write(
            root / f"songs/tunesong/decisions/{d}-x.md",
            _doc("decision", "song", body=d, date=d),
        )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    rows = Q.find_markdown_refs(conn, kind="decision")
    dates = [r["frontmatter_date"] for r in rows]
    assert dates == ["2026-05-26", "2026-03-15", "2026-01-01"]


def test_get_markdown_ref_returns_row(repo):
    conn, root = repo
    _seed_song(conn)
    _write(
        root / "songs/tunesong/annotations/x.md",
        _doc("annotation", "song", body="x"),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    row = Q.get_markdown_ref(conn, "songs/tunesong/annotations/x.md")
    assert row is not None
    assert row["kind"] == "annotation"
    missing = Q.get_markdown_ref(conn, "songs/tunesong/decisions/never.md")
    assert missing is None
