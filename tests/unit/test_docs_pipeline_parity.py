"""Doc-drift lock for the push-pipeline phase list.

The user-facing docs that describe the push pipeline hard-code its phase count
and (some of them) the full phase list. When the pipeline last changed (RTE-1K9T
added the `routing` phase), the same stale 10-phase list was sitting wrong in
FOUR docs at once — exactly the kind of multi-site drift a parity test exists to
catch. These tests fail loudly the next time `_PHASE_NAMES` changes without the
docs following.
"""
from __future__ import annotations

from pathlib import Path

from hallucinote.sync.push.plan import _PHASE_NAMES

_REPO = Path(__file__).resolve().parents[2]

# Docs that print the FULL pipeline (canonical `mix → routing → devices` middle).
_ENUMERATING_DOCS = (
    _REPO / "README.md",
    _REPO / "docs" / "quickstart.md",
    _REPO / "docs" / "skills.md",
)


def test_push_pipeline_phase_count_is_thirteen():
    """Tripwire: when you add/remove a push phase, update the user docs' phase
    count + lists (README / quickstart / skills / collaboration — grep
    'ordered phases') and bump this assertion."""
    assert len(_PHASE_NAMES) == 13


def test_pipeline_docs_include_the_routing_phase():
    """Each doc that enumerates the pipeline must carry the `routing` phase in
    its canonical position — the regression the RTE-1K9T ship introduced when
    all four pipeline docs still listed the pre-routing 10 phases."""
    for doc in _ENUMERATING_DOCS:
        text = doc.read_text(encoding="utf-8")
        assert "mix → routing → devices" in text, (
            f"{doc.relative_to(_REPO)}: push-pipeline list omits the 'routing' "
            "phase (RTE-1K9T) — update it to the current 13-phase order"
        )
