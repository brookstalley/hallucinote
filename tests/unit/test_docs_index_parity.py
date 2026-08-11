"""Doc-drift lock for the docs index.

`docs/README.md` promises "every doc in this directory, grouped by who it's
for". This bundle's own history shows why a promise like that needs teeth: the
README overhaul was caught by the doc-parity suite the same day it shipped, and
the index was born already missing `docs/research/`. These tests fail the next
time a doc lands (or moves) without the index following.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DOCS = _REPO / "docs"
_INDEX = _DOCS / "README.md"


def _indexed_targets() -> set[str]:
    """Every relative link target in the index, normalized."""
    text = _INDEX.read_text(encoding="utf-8")
    return {m.group(1).rstrip("/") for m in re.finditer(r"\]\(([^)#\s]+)", text)}


def test_every_top_level_doc_is_indexed():
    targets = _indexed_targets()
    missing = [
        p.name
        for p in sorted(_DOCS.glob("*.md"))
        if p.name != "README.md" and p.name not in targets
    ]
    assert not missing, (
        "docs/README.md promises every doc in the directory, but these have no "
        f"index row: {missing}. Add a row (or move the doc out of docs/)."
    )


def test_every_docs_subdirectory_is_indexed():
    targets = _indexed_targets()
    missing = [
        p.name
        for p in sorted(_DOCS.iterdir())
        if p.is_dir()
        and p.name != "assets"  # images, not docs — referenced by the docs themselves
        and p.name not in targets
        and f"{p.name}/README.md" not in targets
    ]
    assert not missing, (
        f"docs/README.md has no row for subdirectories: {missing}."
    )


def test_indexed_docs_all_exist():
    dangling = [
        t
        for t in sorted(_indexed_targets())
        if not (_DOCS / t).exists()
    ]
    assert not dangling, f"docs/README.md links to missing targets: {dangling}"
