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


# --- The identity/craft contract ------------------------------------------
#
# The elicitation stage was rebuilt around an owner test: identity (what the
# song IS) belongs to the composer and is asked openly; craft (the numbers that
# realize it) belongs to the agent and is never asked. That contract is now
# restated across eight instruction surfaces, which is a deliberate trade for
# LLM-read files — an agent that loads only CLAUDE.md still has to get it right.
# The trade only holds if the restatements cannot drift apart, and the previous
# landing of this same stage drifted three surfaces before anyone noticed.

_OWNER_TEST_SURFACES = (
    # CLAUDE.md auto-loads every session; the skills do not. A contract missing
    # from here is a contract that does not bind, whatever the skills say.
    _REPO / "CLAUDE.md",
    _REPO / "docs" / "song-workflow.md",
    _REPO / "docs" / "song-new-checklist.md",
    _REPO / "docs" / "song-authoring-conventions.md",
    _REPO / "skills" / "song-brief" / "SKILL.md",
    _REPO / "skills" / "song-workflow" / "SKILL.md",
)

# The five dimensions the composer owns, each keyed by a phrase that must
# survive rewording. Vocals is the one that matters most: the pre-amendment
# sweep table omitted it entirely, a 45-second song with a verse and a chorus
# got briefed with nobody asking about the voice, and that is the defect the
# floor exists to make impossible.
_IDENTITY_MARKERS = ("singing", "harmonic world", "sounds like", "shape")


def test_owner_test_reaches_every_instruction_surface():
    """Identity-vs-craft has to be findable from whichever surface an agent
    happens to load, or it binds only the agents that read the right file."""
    for surface in _OWNER_TEST_SURFACES:
        text = surface.read_text("utf-8").lower()
        # Both nouns AND the instruction that makes them actionable. "identity"
        # and "craft" are common enough words that presence alone would pass on
        # a surface that merely mentions them; "openly" is the behaviour.
        missing = [w for w in ("identity", "craft", "openly") if w not in text]
        assert not missing, (
            f"{surface.relative_to(_REPO)} carries song-authoring instructions "
            f"but is missing {missing} — an agent reading only this surface can "
            "author the composer's choices and never know it"
        )


def test_identity_floor_names_vocals_and_the_rest():
    """The floor is five dimensions; the skill is where they are enumerated."""
    text = (_REPO / "skills" / "song-brief" / "SKILL.md").read_text("utf-8").lower()
    for marker in _IDENTITY_MARKERS:
        assert marker in text, (
            f"skills/song-brief lost the identity dimension matching {marker!r} "
            "— the floor is what stops a must-have falling out of the sweep"
        )


def test_vocals_is_on_the_identity_floor():
    """Separate from the loop above so the failure names the actual defect.

    The pre-amendment sweep table was derived from what had already gone wrong
    once, so it held only should-haves and gap-closers. Questions that have
    always been answered by accident never become defects, and therefore never
    earn a row on a defect-derived agenda."""
    text = (_REPO / "skills" / "song-brief" / "SKILL.md").read_text("utf-8").lower()
    assert "is anyone singing" in text, (
        "skills/song-brief no longer asks whether anyone is singing — this is "
        "the exact omission the identity floor was built to prevent"
    )


def test_the_over_argued_proposal_is_still_named_as_a_failure():
    """Warning only against the blank question is what produced the wall: an
    agent avoiding 'what tempo?' lands on a recommendation plus its full
    justification, which closes the fork instead of opening it. Both failures
    have to be named or the skill teaches one by omitting the other."""
    text = (_REPO / "skills" / "song-brief" / "SKILL.md").read_text("utf-8")
    assert "over-argued proposal" in text, (
        "skills/song-brief dropped the over-argued-proposal anti-pattern — "
        "leaving only the blank-question warning steers straight into it"
    )


def test_no_surface_reinstates_the_one_turn_bound():
    """Counting turns is what caused the cram it was meant to prevent; the
    bound is now on shape (every turn carries new work, <=2 questions).

    `.prawduct/change-log.md` is exempt: it is an append-only historical record
    and its older entries legitimately describe the superseded rule. The design
    artifact is exempt because it preserves the ratified text under explicit
    `→ amended by Amendment 1` markers, which is how a norm amendment is
    supposed to read."""
    exempt = {"change-log.md", "elicitation-and-stage-exit-criteria.md"}
    offenders = [
        md.relative_to(_REPO)
        for md in _markdown_files()
        if md.name not in exempt
        and "plans/" not in md.relative_to(_REPO).as_posix()
        and "one consolidated turn" in md.read_text("utf-8").lower()
    ]
    assert not offenders, (
        "the one-consolidated-turn bound was reinstated in: "
        + "; ".join(str(o) for o in offenders)
    )


def test_decider_vocabulary_is_consistent_in_the_worked_example():
    """The brief's `Decided by` column is the only audit trail this stage
    ships, and it only works if the legitimate paths and the defect write
    DIFFERENT values: `agent-read` (a read with an exit, offered because the
    two-question budget overflowed), `agent-handback` (they said "just go"),
    and a bare `agent`, which on an identity row IS the substitution the stage
    exists to prevent — deliberately greppable.

    The canonical Good example is where an agent will copy from, so a bare
    `agent` there teaches the defect regardless of what the rule says. That is
    exactly how this drifted once: the vocabulary was split into three values
    and the worked example kept the old one."""
    text = (_REPO / "skills" / "song-brief" / "SKILL.md").read_text("utf-8")
    good, _, rest = text.partition("### Bad — and why")
    _, _, good_example = good.partition("### Good")
    assert good_example, "skills/song-brief lost its Good worked example"
    assert "`agent-read`" in good_example, (
        "the Good example's overflowed-identity row must be recorded as "
        "`agent-read` — a bare `agent` is the defect the column exists to expose"
    )
    for value in ("agent-read", "agent-handback"):
        assert f"| `{value}` |" in text, (
            f"skills/song-brief no longer defines `{value}` in the Decided-by "
            "table, so the audit trail cannot distinguish the legitimate path "
            "from the substitution defect"
        )
