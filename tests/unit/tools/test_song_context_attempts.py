"""`/song-context` rendering of attempt-ledger rows (kind: attempt) — ATL-7K3M.

The `--kind attempt` / `--outcome` filters and the outcome/resolution meta line.
"""
from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.markdown_refs import reindex_corpus
from hallucinote.tools.song_context import main as song_context_main


@pytest.fixture
def repo_with_corpus(tmp_path: Path):
    songs_root = tmp_path / "songs"
    songs_root.mkdir()
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    M.create_song(conn, name="highland", key="Em")
    yield conn, db_path, tmp_path
    conn.close()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _attempt(*, body: str, outcome: str, resolution: str, track: str = "Bagpipes",
             **extra) -> str:
    lines = [
        "date: 2026-06-14", "kind: attempt", "scope: track",
        f"track: {track}", f"outcome: {outcome}", f"resolution: {resolution}",
    ]
    for k, v in extra.items():
        lines.append(f"{k}: {v}")
    return "---\n" + "\n".join(lines) + f"\n---\n{body}\n"


def _seed_two_attempts(conn, root: Path) -> None:
    _write(
        root / "songs/highland/attempts/notch.md",
        _attempt(body="notch still let the bagpipes overwhelm the vocal",
                 outcome="failed", resolution="reverted", tags="[mix, notch]"),
    )
    _write(
        root / "songs/highland/attempts/gate.md",
        _attempt(body="gated the bagpipes under the vocal phrases",
                 outcome="worked", resolution="kept", tags="[mix, gate]"),
    )
    reindex_corpus(conn, songs_root=root / "songs", repo_root=root)
    conn.commit()


def test_kind_attempt_renders_outcome_and_resolution(repo_with_corpus):
    conn, db_path, root = repo_with_corpus
    _seed_two_attempts(conn, root)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = song_context_main(["--db", str(db_path), "--kind", "attempt"])
    assert rc == 0
    out = buf.getvalue()
    assert "2 matches" in out
    assert "outcome: failed" in out and "resolution: reverted" in out
    assert "outcome: worked" in out and "resolution: kept" in out


def test_outcome_filter_narrows_to_failed(repo_with_corpus):
    conn, db_path, root = repo_with_corpus
    _seed_two_attempts(conn, root)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = song_context_main(
            ["--db", str(db_path), "--kind", "attempt", "--outcome", "failed"]
        )
    assert rc == 0
    out = buf.getvalue()
    assert "1 match" in out
    assert "notch.md" in out and "gate.md" not in out
    assert "outcome: failed" in out


def test_fulltext_path_still_renders_outcome_and_resolution(repo_with_corpus):
    # The fulltext branch is a different SELECT (m.*, snippet(...)); confirm
    # outcome/resolution still flow through _format_row on that path, not just
    # the --kind branch.
    conn, db_path, root = repo_with_corpus
    _seed_two_attempts(conn, root)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = song_context_main(["--db", str(db_path), "bagpipes"])
    assert rc == 0
    out = buf.getvalue()
    assert "outcome: failed" in out and "resolution: reverted" in out
    assert "outcome: worked" in out and "resolution: kept" in out
