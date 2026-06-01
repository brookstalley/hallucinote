"""Drift guard: every song's decisions/ + annotations/ markdown must parse.

`/song-context` reindexes the markdown corpus into the song DB via
`reindex_corpus`, which calls `load_markdown_doc` on every file and raises on
the first one with malformed/missing frontmatter or a disallowed key. Because
the reindex is atomic, ONE bad file silently breaks `/song-context` for the
whole repo — exactly what happened (sun-zone-done's decision files shipped with
no frontmatter; punk-fate carried `decided_by`/`topic` keys outside the schema).

This is Living Documentation as a test: the corpus is the deliverable that
`/song-context` reads, so we lock its parseability the same way
`test_authoring_api_surface` locks the generator index. A new song with bad
frontmatter fails here, loudly, instead of at recall time.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hallucinote.markdown_refs import discover_corpus, load_markdown_doc

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SONGS_ROOT = _REPO_ROOT / "songs"

_CORPUS = discover_corpus(_SONGS_ROOT) if _SONGS_ROOT.is_dir() else []


@pytest.mark.skipif(not _CORPUS, reason="no songs/ corpus in this checkout")
@pytest.mark.parametrize("path", _CORPUS, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
def test_corpus_markdown_parses(path: Path):
    """Each decisions/annotations markdown file loads with valid frontmatter."""
    load_markdown_doc(path, repo_root=_REPO_ROOT)


@pytest.mark.skipif(not _CORPUS, reason="no songs/ corpus in this checkout")
def test_corpus_is_nonempty_and_discovered():
    """Guard against the discovery glob silently returning nothing (which would
    make the parametrized test vacuously pass)."""
    assert len(_CORPUS) >= 1
