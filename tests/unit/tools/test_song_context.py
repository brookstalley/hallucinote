"""Arc 2 / Chunk 4 — `--defensive` and `--generative` modes on
`tools/song_context.py`.

The existing topic/filters/output-shape behavior is exercised by the
reindex + parser test files plus manual use; this file focuses on the
new modes specifically.
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.markdown_refs import reindex_corpus

from tools.song_context import (
    _has_negation,
    _related_by_tags,
    main as song_context_main,
)


@pytest.fixture
def repo_with_corpus(tmp_path: Path):
    """A mini songs/ tree + reindexed DB. Returns (conn, db_path)."""
    songs_root = tmp_path / "songs"
    songs_root.mkdir()
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    M.create_song(conn, name="tunesong", key="Dm")
    yield conn, db_path, tmp_path
    conn.close()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _doc(kind: str, scope: str, *, body: str, **extra) -> str:
    fm_lines = [f"kind: {kind}", f"scope: {scope}"]
    for k, v in extra.items():
        fm_lines.append(f"{k}: {v}")
    fm = "\n".join(fm_lines)
    return f"---\n{fm}\n---\n{body}\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("don't sidechain the bass", True),
        ("avoid heavy compression on this", True),
        ("Never use the chorus pad here", True),
        ("Make this section bloom into the bridge", False),
        ("Standard rock beat with light swing", False),
        ("", False),
        (None, False),
    ],
)
def test_has_negation_catches_constraint_language(text, expected):
    assert _has_negation(text) is expected


# ---------------------------------------------------------------------------
# --defensive mode (rendering layer)
# ---------------------------------------------------------------------------


def test_defensive_mode_prints_framing_header(repo_with_corpus):
    conn, db_path, root = repo_with_corpus
    _write(
        root / "songs/tunesong/decisions/2026-01-01-bass.md",
        _doc(
            "decision",
            "song",
            date="2026-01-01",
            tags="[bass, sidechain]",
            body="Don't sidechain the bass on the bridge — let it bloom.",
        ),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    conn.commit()

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = song_context_main(
            ["--db", str(db_path), "bass", "--defensive"]
        )
    assert rc == 0
    out = buf.getvalue()
    assert "Defensive mode" in out
    assert "MAY CONTRADICT your plan" in out
    # The negation flag should fire on the seeded row (snippet will contain
    # the matched "bass" with surrounding context including "Don't").
    assert "contradiction signal" in out


def test_defensive_mode_does_not_flag_non_negated_rows(repo_with_corpus):
    conn, db_path, root = repo_with_corpus
    _write(
        root / "songs/tunesong/annotations/bass-feel.md",
        _doc(
            "annotation",
            "song",
            tags="[bass]",
            body="Bass plays a relaxed, swingy walking line.",
        ),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    conn.commit()

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = song_context_main(
            ["--db", str(db_path), "bass", "--defensive"]
        )
    assert rc == 0
    out = buf.getvalue()
    assert "Defensive mode" in out
    # No negation in the row body, so the warning marker stays absent.
    assert "contradiction signal" not in out


# ---------------------------------------------------------------------------
# --generative mode (related-by-tags second query)
# ---------------------------------------------------------------------------


def test_generative_mode_surfaces_related_rows_by_shared_tag(repo_with_corpus):
    conn, db_path, root = repo_with_corpus
    # Seed row: shared tag "groove"
    _write(
        root / "songs/tunesong/annotations/feel.md",
        _doc(
            "annotation",
            "song",
            tags="[groove, swing]",
            body="Lazy walking groove on the verse.",
        ),
    )
    # Related-by-tag row: shares "groove" but doesn't mention "walking"
    _write(
        root / "songs/tunesong/annotations/drum-feel.md",
        _doc(
            "annotation",
            "song",
            tags="[groove, drums]",
            body="Drums are loose, dragging behind the beat slightly.",
        ),
    )
    # Unrelated row: different tags
    _write(
        root / "songs/tunesong/annotations/synth.md",
        _doc(
            "annotation",
            "song",
            tags="[synth, pad]",
            body="Pad rises into the chorus.",
        ),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    conn.commit()

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = song_context_main(
            ["--db", str(db_path), "walking", "--generative"]
        )
    assert rc == 0
    out = buf.getvalue()
    # Topic match heading and Related context heading both present.
    assert "match" in out
    assert "Related context" in out
    # The drum-feel.md should appear under Related context (shared tag),
    # the synth.md should NOT (no shared tag).
    assert "drum-feel.md" in out
    assert "synth.md" not in out


def test_generative_mode_handles_no_tags_gracefully(repo_with_corpus):
    """When top matches have no tags, the related-context section says so
    rather than dumping unrelated rows."""
    conn, db_path, root = repo_with_corpus
    _write(
        root / "songs/tunesong/annotations/no-tags.md",
        _doc("annotation", "song", body="Bass is a thing."),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    conn.commit()

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = song_context_main(
            ["--db", str(db_path), "bass", "--generative"]
        )
    assert rc == 0
    out = buf.getvalue()
    assert "Related context" in out
    assert "none — top matches had no tags" in out


def test_related_by_tags_excludes_seed_rows(repo_with_corpus):
    """Direct helper test: the related query must not echo back the seeds
    themselves (otherwise generative mode is just "show the search result
    a second time")."""
    conn, _db, root = repo_with_corpus
    _write(
        root / "songs/tunesong/annotations/a.md",
        _doc("annotation", "song", tags="[t1, t2]", body="A"),
    )
    _write(
        root / "songs/tunesong/annotations/b.md",
        _doc("annotation", "song", tags="[t1]", body="B"),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    conn.commit()
    # Use a.md as the seed; b.md should be the only related result.
    seed = conn.execute(
        "SELECT * FROM markdown_refs WHERE path LIKE '%/a.md'"
    ).fetchone()
    related = _related_by_tags(conn, [seed], limit=5)
    related_paths = [r["path"] for r in related]
    assert any(p.endswith("/b.md") for p in related_paths)
    assert not any(p.endswith("/a.md") for p in related_paths)
