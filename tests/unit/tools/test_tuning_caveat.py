"""tools/tuning_caveat.py — the gated lens caveat for alt-tuned songs (Chunk 3).

Covers the pure banner (:func:`lens_caveat`) and the DB-backed
:func:`song_tuning_ref` resolver, including its degrade-to-None branches (no DB,
no song row) so a missing signal never produces a spurious caveat. The resolver
reads through the tuning-agnostic core query — no ``hallucinote.tuning`` import on
the core side (that invariant is grep-asserted by the isolation test); the test
*may* use the tuning package to build a realistic stored row.
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.tools.tuning_caveat import lens_caveat, song_tuning_ref
from hallucinote.tuning.model import TuningData


# ---------------------------------------------------------------------------
# lens_caveat — pure banner
# ---------------------------------------------------------------------------
def test_lens_caveat_none_for_12tet():
    assert lens_caveat(None) is None
    assert lens_caveat("") is None


def test_lens_caveat_names_the_tuning_file_and_flags_12tet_relative():
    out = lens_caveat("tunings/19-edo.ascl")
    assert out is not None
    assert "tunings/19-edo.ascl" in out
    assert "12-TET-relative" in out
    assert "non-12 tuning" in out


# ---------------------------------------------------------------------------
# song_tuning_ref — DB-backed resolver
# ---------------------------------------------------------------------------
@pytest.fixture
def songs_root(tmp_path, monkeypatch):
    """A synthetic songs workspace resolved via HALLUCINOTE_SONGS_ROOT (mirrors
    the lens CLI tests). Returns the root; per-song dirs/DBs are made by helpers."""
    root = tmp_path / "songs"
    root.mkdir()
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("HALLUCINOTE_SONGS_ROOT", str(root))
    return root


def _make_song_db(root, slug: str, *, tuning_ref: str | None = None):
    """Create ``<root>/<slug>/<slug>.db`` with a song row named ``slug`` (the
    legacy bare-DB name the resolver falls back to outside a git repo). Optionally
    set a tuning. Returns the song id."""
    song_dir = root / slug
    song_dir.mkdir(parents=True)
    conn = init_db(song_dir / f"{slug}.db")
    try:
        song_id = M.create_song(conn, name=slug, key="C")
        if tuning_ref is not None:
            tuning = TuningData(
                name="19-EDO", step_count=19, period_cents=1200.0,
                reference_note=60,
                step_cents=tuple(round(1200.0 * i / 19, 6) for i in range(1, 20)),
            )
            M.set_song_tuning(
                conn, song_id=song_id,
                tuning_ref=tuning_ref, tuning_data=tuning.to_blob(),
            )
        return song_id
    finally:
        conn.close()


def test_song_tuning_ref_returns_ref_for_alt_tuned_song(songs_root):
    _make_song_db(songs_root, "micro-song", tuning_ref="tunings/19-edo.ascl")
    assert song_tuning_ref("micro-song") == "tunings/19-edo.ascl"


def test_song_tuning_ref_none_for_12tet_song(songs_root):
    _make_song_db(songs_root, "plain-song", tuning_ref=None)
    assert song_tuning_ref("plain-song") is None


def test_song_tuning_ref_none_when_no_db_yet(songs_root):
    # Song dir doesn't exist at all — the common pre-build path must not error.
    assert song_tuning_ref("never-built") is None


def test_song_tuning_ref_none_when_song_row_absent(songs_root):
    # A DB exists but holds no row named after the slug.
    song_dir = songs_root / "empty-db"
    song_dir.mkdir(parents=True)
    init_db(song_dir / "empty-db.db").close()
    assert song_tuning_ref("empty-db") is None


def test_lens_caveat_composes_with_resolver(songs_root):
    _make_song_db(songs_root, "micro2", tuning_ref="tunings/bohlen-pierce.ascl")
    caveat = lens_caveat(song_tuning_ref("micro2"))
    assert caveat is not None and "tunings/bohlen-pierce.ascl" in caveat


def test_song_tuning_ref_degrades_to_none_on_unreadable_db(songs_root, caplog):
    # A file exists at the DB path but isn't a valid SQLite DB. The OPTIONAL
    # caveat lookup must degrade to None (not crash the lens, whose real job
    # never touches this DB) and log the skip.
    song_dir = songs_root / "broken-db"
    song_dir.mkdir(parents=True)
    (song_dir / "broken-db.db").write_bytes(b"this is not a sqlite database")
    import logging
    with caplog.at_level(logging.WARNING):
        assert song_tuning_ref("broken-db") is None
    assert any("caveat lookup skipped" in r.message for r in caplog.records)
