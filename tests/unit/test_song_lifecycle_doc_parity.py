"""Doc-drift lock for the song lifecycle map and its stage exit criteria.

The lifecycle is enumerated across seven surfaces (README, two docs pages, the
`/song-workflow` skill, the MCP primer string, the MCP getting-started resource,
and `docs/skills.md`), and nine skills deep-link into one anchor for the
per-stage definitions of done. When stage 0 (`/song-brief`) was added, three of
those surfaces kept the pre-brief arc and one skill contradicted itself inside a
single file — the same multi-site drift `test_docs_pipeline_parity.py` exists to
catch for the push pipeline.

The exit-criteria table also shipped in TWO places at once and had already
diverged on arrival, which is what the repo's "link, don't summarize" learning
is about. `test_stage_criteria_table_has_exactly_one_home` is the lock on that.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

_WORKFLOW_DOC = _REPO / "docs" / "song-workflow.md"
_DESIGN_ARTIFACT = (
    _REPO / ".prawduct" / "artifacts" / "elicitation-and-stage-exit-criteria.md"
)

# Every surface that enumerates the lifecycle for an agent or a reader. Stage 0
# must be reachable from all of them: an agent that only ever loads one of these
# still has to find `/song-brief`.
_LIFECYCLE_SURFACES = (
    # CLAUDE.md first, and it matters most: it auto-loads every session while
    # the skills do not, so a stage missing from here is a stage that does not
    # happen — whatever the skills say.
    _REPO / "CLAUDE.md",
    _REPO / "README.md",
    _REPO / "docs" / "quickstart.md",
    _REPO / "docs" / "skills.md",
    _REPO / "docs" / "song-workflow.md",
    _REPO / "skills" / "song-workflow" / "SKILL.md",
    _REPO / "hallucinote_mcp" / "src" / "hallucinote_mcp" / "server.py",
    _REPO
    / "hallucinote_mcp"
    / "src"
    / "hallucinote_mcp"
    / "resources"
    / "guides"
    / "getting-started.md",
)

# The eight stages, in order. Index IS the stage number.
_STAGES = (
    "song-brief",
    "song-new",
    "song-pick-instruments",
    "compose-part",
    "compose-review",
    "ableton-push",
    "render-analyze",
    "mix-review",
)


def _github_anchor(heading_text: str) -> str:
    """GitHub's heading->anchor slug: lowercase, drop punctuation, spaces to
    hyphens. Good enough for the plain ASCII headings this repo uses."""
    slug = heading_text.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    return re.sub(r"\s+", "-", slug)


def _anchors_in(doc: Path) -> set[str]:
    return {
        _github_anchor(m.group(1))
        for m in re.finditer(r"^#{1,6}\s+(.+?)\s*$", doc.read_text("utf-8"), re.M)
    }


def _markdown_files() -> list[Path]:
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "songs"}
    return [
        p
        for p in _REPO.rglob("*.md")
        if not any(part in skip for part in p.relative_to(_REPO).parts)
    ]


def test_song_workflow_doc_carries_both_linked_anchors():
    """Nine skills + three docs deep-link into these two headings. Renaming
    either silently breaks every one of those links."""
    anchors = _anchors_in(_WORKFLOW_DOC)
    for required in ("stage-exit-criteria", "definitions-of-done"):
        assert required in anchors, (
            f"docs/song-workflow.md lost the '#{required}' heading — the skills "
            "and docs that deep-link to it now point at nothing"
        )


def test_every_song_workflow_deeplink_resolves():
    """Any `song-workflow.md#some-anchor` link anywhere in the repo must hit a
    real heading."""
    anchors = _anchors_in(_WORKFLOW_DOC)
    broken: list[str] = []
    for md in _markdown_files():
        for m in re.finditer(r"song-workflow\.md#([\w-]+)", md.read_text("utf-8")):
            if m.group(1) not in anchors:
                broken.append(f"{md.relative_to(_REPO)} -> #{m.group(1)}")
    assert not broken, "dangling song-workflow.md anchors: " + "; ".join(broken)


def test_every_lifecycle_surface_names_the_brief_stage():
    """Stage 0 has to be reachable from every surface that lays out the arc.
    Three of these kept the pre-brief enumeration when `/song-brief` landed."""
    for surface in _LIFECYCLE_SURFACES:
        assert "song-brief" in surface.read_text("utf-8"), (
            f"{surface.relative_to(_REPO)} enumerates the song lifecycle but "
            "never names /song-brief — an agent reading only this surface will "
            "start at the scaffold and invent tempo/meter/sections"
        )


def test_song_workflow_skill_does_not_undercount_the_checkpoints():
    """The skill claimed 'three checkpoints' in its frontmatter and 'the two
    review checkpoints' in its body and heading, in the same file."""
    text = (_REPO / "skills" / "song-workflow" / "SKILL.md").read_text("utf-8")
    # The attempt-ledger sentence legitimately says "two review checkpoints"
    # (compose-review + mix-review propose the entries); the lifecycle-map
    # claims are the ones that must say three.
    assert "## The three checkpoints agents miss" in text, (
        "skills/song-workflow: the checkpoints heading must count three "
        "(/song-brief, /compose-review, /mix-review)"
    )
    assert "the two review checkpoints that are easy to skip" not in text, (
        "skills/song-workflow: the opening still describes two checkpoints "
        "while the frontmatter and the arc describe three"
    )


def test_workflow_doc_defines_done_for_every_authoring_stage():
    """Stages 0-7 each need a row. Stage 8 is the loop-back and deliberately
    has none — the doc says so explicitly, and that sentence is the thing
    keeping 'every stage has a definition of done' honest."""
    text = _WORKFLOW_DOC.read_text("utf-8")
    _, _, criteria = text.partition("### Definitions of done")
    assert criteria, "docs/song-workflow.md lost its 'Definitions of done' table"
    for number, stage in enumerate(_STAGES):
        assert f"{number} · `/{stage}`" in criteria, (
            f"docs/song-workflow.md: no definition of done for stage {number} "
            f"(/{stage})"
        )
    assert "Stage 8" in criteria, (
        "docs/song-workflow.md must say why stage 8 has no criterion, or the "
        "'each stage's definition of done' claim is false"
    )


def test_stage_criteria_table_has_exactly_one_home():
    """The eight-row table shipped in the design artifact AND the doc, and the
    two had already diverged in the same commit. The artifact links now."""
    artifact = _DESIGN_ARTIFACT.read_text("utf-8")
    restated = [s for s in _STAGES if f"· `/{s}`" in artifact]
    assert not restated, (
        "the design artifact is restating the stage exit-criteria table "
        f"({', '.join(restated)}) — docs/song-workflow.md#definitions-of-done "
        "is the canonical copy; link to it instead (see the repo learning "
        "'link, don't summarize')"
    )
    assert "definitions-of-done" in artifact, (
        "the design artifact must link to the canonical criteria table"
    )
