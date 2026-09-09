"""Drift lock for the collaboration turn model's vocabulary and retired promises.

Sibling of `test_song_lifecycle_doc_parity.py`, and it exists for the same
reason: the rules below live on surfaces no single reader sees together, so
nothing but a test notices when one of them drifts back.

Three things this locks, each for a specific reason the build cycle paid for:

**The retired phrases stay retired, matched over collapsed whitespace.** The
promise that elicitation "comes back once" was swept out of nine surfaces. A
plain `git grep` for it could not fail — the phrase wraps across line breaks in
prose, and it did so in two of the files being swept, so the sweep's own
verification came back clean *before* the edit as well as after. Every check
here flattens whitespace and drops emphasis punctuation first.

**The vocabulary is defined in the sanctioned files and nowhere else.** A
definition (what a term *means*) has two homes: the design artifact and the
short definition in `CLAUDE.md`, which is the one surface loaded every session.
`docs/song-workflow.md` carries one one-line gloss as a bounded exception,
because it is human-facing and its reader does not auto-load `CLAUDE.md`. A
*rule* stated in terms already defined is not a definition and is not locked —
it belongs wherever it fires. Three independent reviewers each caught the same
file promising it did not restate and then restating; the promise is what makes
that dangerous, because a maintainer trusts it and never looks for the copy.

**The brief template parses against the live validator.** Not against prose: the
template this replaced carried a `date: <YYYY-MM-DD>` placeholder that the
validator's ISO check would have rejected, and no one noticed for as long as it
shipped. Asserting the block still parses is that lesson as a construction
rather than a one-time check.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

_CLAUDE_MD = _REPO / "CLAUDE.md"
_SONG_BRIEF = _REPO / "skills" / "song-brief" / "SKILL.md"
_SKILLS_DOC = _REPO / "docs" / "skills.md"
_WORKFLOW_DOC = _REPO / "docs" / "song-workflow.md"
_DESIGN_ARTIFACT = (
    _REPO / ".prawduct" / "artifacts" / "collaboration-turn-model.md"
)
_MCP_SERVER = (
    _REPO / "hallucinote_mcp" / "src" / "hallucinote_mcp" / "server.py"
)
_MCP_GUIDE = (
    _REPO
    / "hallucinote_mcp"
    / "src"
    / "hallucinote_mcp"
    / "resources"
    / "guides"
    / "getting-started.md"
)

#: The promises the collaboration turn model retired. Matched against collapsed
#: whitespace, so a phrase that wraps across a line break is still caught.
_RETIRED_PHRASES = (
    "one consolidated turn",
    "exactly one consolidated",
    "comes back once",
    "come back once",
    "collapses 5 other answers into one",
)

#: Paths where a retired phrase is the *record* of something, not a live
#: promise. Each is exempt for a stated reason, because an unexplained exempt
#: list is how a lock quietly stops covering the thing it was written for.
_EXEMPT_FILES = {
    # This file. It holds the phrase table and the definitional cue, so it
    # matches itself the moment it is tracked — self-reference, not drift. It
    # passed while untracked and failed on the commit that added it, which is a
    # fair description of how this class of bug always arrives.
    "tests/unit/test_collaboration_norm_parity.py": "carries the phrase list it scans for",
    # Records of what happened or shipped. Rewriting them falsifies the record.
    "docs/tour.md": "a transcript of a real session, locked by test_tour_freshness",
    "CHANGELOG.md": "the history of shipped releases",
    ".prawduct/change-log.md": "the repo's own change history",
    ".prawduct/change-log-archive.md": "the same history, rolled out of the live log",
    ".prawduct/project-state.yaml": "the norm registry names retired norms",
    # Documents whose subject IS the retired phrase.
    ".prawduct/artifacts/collaboration-turn-model.md": "names the phrases it retires",
    ".prawduct/artifacts/elicitation-and-stage-exit-criteria.md": "quotes the superseded text it is superseded by",
}

_EXEMPT_PREFIXES = (
    ".prawduct/learnings",
    ".prawduct/artifacts/archive/",
    ".prawduct/artifacts/collaboration-corpus/",
    ".prawduct/reflections",
)

#: The six turn kinds. `CLAUDE.md` must name every one: an agent that cannot
#: classify the turn cannot apply the rule that only two kinds authorize a build.
_TURN_KINDS = (
    "directing",
    "reacting",
    "exploring",
    "asking",
    "delegating",
    "handing-off",
)

#: The owner column's ratified values. Written from where the agent sits —
#: `mine` = the agent decides, `yours` = the user decides — with only the middle
#: value phrased the way a user would say it. `options` alone was the build
#: plan's abbreviation of the artifact's ratified wording.
_OWNER_VALUES = ("yours", "offer me options", "mine")

#: The definitional sentence for "hearable unit". Its homes are enumerated
#: rather than counted, so adding a home is a deliberate edit to this list.
_DEFINITION_CUE = "the smallest thing that, once heard"
_DEFINITION_HOMES = {
    ".prawduct/artifacts/collaboration-turn-model.md",
    "CLAUDE.md",
    "docs/song-workflow.md",
}


def _flatten(text: str) -> str:
    """Collapse whitespace and drop markdown emphasis, then lowercase.

    Matching raw text misses `one\\nconsolidated turn` and ``one **consolidated**
    turn`` — both of which occurred in files this lock covers.
    """
    return re.sub(r"\s+", " ", re.sub(r"[*_`]", "", text)).lower()


def _tracked_files() -> list[str]:
    """Every file git would carry: tracked, plus untracked-and-not-ignored.

    `--others --exclude-standard` is the load-bearing half. Scanning only the
    index makes a NEW file invisible until the commit that adds it, so the lock
    passes locally and fails in CI on the same content — which has now happened
    twice to this test (once on the file that carries the phrase table, once on
    `.prawduct/change-log-archive.md`). Ignored paths stay out, so a dirty tree
    costs nothing; what a developer sees is what the branch will.
    """
    out = subprocess.run(
        ["git", "-C", str(_REPO), "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # Drop index entries whose file is gone from disk. `--cached` lists the
    # index, so a file MOVED but not yet staged appears at its old path and
    # `read_text` raises FileNotFoundError -- the lock crashed instead of
    # failing, on a tree that was merely mid-rename. Its new path arrives via
    # `--others`, so nothing escapes the scan; a path with no file cannot
    # carry a phrase.
    return [rel for rel in out.split() if (_REPO / rel).is_file()]


def _is_exempt(rel: str) -> bool:
    return rel in _EXEMPT_FILES or rel.startswith(_EXEMPT_PREFIXES) or _is_archived(rel)


def _is_archived(rel: str) -> bool:
    """True for a plan the `archive-plan` hook has retired.

    `_EXEMPT_PREFIXES` covers `.prawduct/artifacts/archive/`, where a
    root-level plan lands. A plan that lived in its own directory is archived
    in place instead — `plans/<ID>/build-plan.md` becomes
    `plans/<ID>/archive/build-plan.md` — so the prefix rule never saw it, and
    the COLLAB-TURN plan was exempted by exact path until the JANITOR-2026-09
    sweep archived it and the path went stale. Both shapes are the same thing:
    a record of what was built, carrying an "archived — no longer maintained,
    do not edit" banner. Rewriting one to satisfy a live-surface lock would
    falsify the record, which is why every other record in `_EXEMPT_FILES` is
    exempt for that same stated reason.
    """
    return rel.startswith(".prawduct/artifacts/plans/") and "/archive/" in rel


def _frontmatter_description(skill: Path) -> str:
    """The skill's `description:` folded scalar, as one line.

    Stops at the next top-level key; `argument-hint` and friends carry hyphens,
    so a `\\w+` boundary silently swallows the rest of the frontmatter.
    """
    frontmatter = skill.read_text(encoding="utf-8").split("---")[1]
    match = re.search(
        r"^description:\s*(.*?)(?=^[\w-]+:|\Z)", frontmatter, re.M | re.S
    )
    assert match, f"{skill} has no description in its frontmatter"
    description = " ".join(match.group(1).split())
    return description[2:].strip() if description.startswith(">-") else description


def test_no_live_surface_promises_the_brief_comes_back_once():
    """The retired promises survive nowhere a reader takes as current.

    Matched over collapsed whitespace: the plain grep this replaces returned
    clean against files that carried the phrase wrapped across a line break.
    """
    offenders = []
    for rel in _tracked_files():
        if _is_exempt(rel):
            continue
        try:
            text = (_REPO / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable — carries no prose promise
        flat = _flatten(text)
        for phrase in _RETIRED_PHRASES:
            if phrase in flat:
                offenders.append(f"{rel}: {phrase!r}")

    assert not offenders, (
        "a surface still promises what the collaboration turn model retired "
        "(elicitation is a conversation that ends at the user's hand-off):\n  "
        + "\n  ".join(offenders)
    )


def test_claude_md_names_every_turn_kind_and_the_hearable_unit():
    """`CLAUDE.md` is the only surface loaded every session.

    A kind missing here is a kind the agent cannot classify, and the rule that
    only *directing* and *handing-off* authorize building is unusable without
    the full set to classify against.
    """
    flat = _flatten(_CLAUDE_MD.read_text(encoding="utf-8"))
    missing = [kind for kind in _TURN_KINDS if kind not in flat]
    assert not missing, f"CLAUDE.md does not name these turn kinds: {missing}"
    assert "hearable unit" in flat, "CLAUDE.md does not name the hearable unit"


def test_the_brief_template_carries_the_owner_column():
    """The owner column is how the delegation axis exists at all.

    Without it the brief records what was decided and not who owns it, which is
    the gap the design names as the reason "run off and build" survives a brief.
    """
    flat = _flatten(_SONG_BRIEF.read_text(encoding="utf-8"))
    missing = [value for value in _OWNER_VALUES if f"| {value} |" not in flat]
    assert not missing, (
        f"the /song-brief template is missing owner column values: {missing}. "
        "The ratified values are in the user's own voice; `options` alone was "
        "the build plan's abbreviation and breaks that voice."
    )


def test_skills_doc_mirrors_the_song_brief_description():
    """One source for the description: the skill's own frontmatter.

    `docs/skills.md` is a second surface describing the same skill. When they
    drift, the table is what a browsing reader believes and the frontmatter is
    what the agent loads.
    """
    description = _frontmatter_description(_SONG_BRIEF)
    row = f"| `/hallucinote:song-brief` | {description} |"
    assert row in _SKILLS_DOC.read_text(encoding="utf-8"), (
        "docs/skills.md's /song-brief row does not match the skill's own "
        "frontmatter description verbatim"
    )


def test_the_hearable_unit_is_defined_only_where_it_is_sanctioned():
    """A definition has two homes, plus one bounded exception.

    `docs/song-workflow.md` may gloss the term because it is human-facing and
    its reader does not auto-load `CLAUDE.md`. Everywhere else links. A file
    that both promises it does not restate and then restates is worse than one
    that simply restates — the promise is what stops a maintainer looking for
    the second copy.
    """
    homes = {
        rel
        for rel in _tracked_files()
        if rel.endswith((".md", ".py"))
        and not _is_exempt(rel)  # a document *about* the vocabulary may quote it
        and _DEFINITION_CUE in _flatten((_REPO / rel).read_text(encoding="utf-8", errors="ignore"))
    }
    unsanctioned = sorted(homes - _DEFINITION_HOMES)
    assert not unsanctioned, (
        "the hearable unit is defined outside its sanctioned homes "
        f"{sorted(_DEFINITION_HOMES)}: {unsanctioned}. State the rule and link "
        "to the definition instead."
    )


def test_the_brief_template_parses_against_the_live_validator():
    """Validate the template against the validator, never against prose.

    The template this replaced carried `date: <YYYY-MM-DD>`, which the ISO check
    rejects — a brief written from it would have raised at index time. A prose
    review of a template cannot catch that; only the parser can.
    """
    parse_frontmatter = pytest.importorskip(
        "hallucinote.markdown_refs"
    ).parse_frontmatter

    blocks = re.findall(
        r"^```markdown\n(.*?)^```", _SONG_BRIEF.read_text(encoding="utf-8"), re.M | re.S
    )
    templates = [b for b in blocks if b.lstrip().startswith("---")]
    assert templates, "no frontmatter-bearing template block in /song-brief"

    for block in templates:
        frontmatter, _body = parse_frontmatter(block)  # raises on any violation
        assert frontmatter.kind == "annotation", (
            "the brief template must parse as an annotation, got "
            f"{frontmatter.kind!r}"
        )


def test_both_mcp_text_surfaces_describe_the_brief_as_a_conversation():
    """The MCP primer and guide are what an agent reads with no skills loaded.

    Both sit outside `_FINGERPRINT_PATHS`, so a change here ships silently
    without a re-vendor — which is exactly why nothing else would notice them
    drifting back to the one-turn framing.
    """
    for surface in (_MCP_SERVER, _MCP_GUIDE):
        text = surface.read_text(encoding="utf-8")
        # Bound to the /song-brief passage, not the file. `conversation` appearing
        # anywhere in a thousand-line module says nothing about how the brief is
        # described, and would let the one-turn framing back in beside it.
        passage = " ".join(
            line for line in text.splitlines() if "song-brief" in line
        )
        assert passage, f"{surface.relative_to(_REPO)} no longer mentions /song-brief"
        assert "conversation" in _flatten(passage), (
            f"{surface.relative_to(_REPO)} no longer describes /song-brief as a "
            "conversation that runs until the user hands off"
        )


def test_the_workflow_doc_scopes_its_one_gloss_honestly():
    """The bounded exception must be stated where it is taken.

    `docs/song-workflow.md` is the one file allowed to gloss the hearable unit.
    It must not also claim it never restates — that claim is what this lock
    exists to stop a maintainer trusting.
    """
    flat = _flatten(_WORKFLOW_DOC.read_text(encoding="utf-8"))
    for claim in ("defined once", "never restated", "does not redefine"):
        assert claim not in flat, (
            f"docs/song-workflow.md claims {claim!r} while carrying the sanctioned "
            "one-line gloss, and the vocabulary has two homes besides (the design "
            "artifact and CLAUDE.md). Scope the claim to what is true — an "
            "unqualified promise is what stops a maintainer looking for the copy."
        )
