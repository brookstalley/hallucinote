"""Doc-drift lock for the song lifecycle map and its stage exit criteria.

The lifecycle is enumerated across every surface in `_LIFECYCLE_SURFACES` below
— CLAUDE.md, the README, three docs pages, the `/song-workflow` skill, the MCP
primer string and the MCP getting-started resource — and skills across the repo
deep-link into one anchor for the per-stage definitions of done. When stage 0
(`/song-brief`) was added, three of those surfaces kept the pre-brief arc and one
skill contradicted itself inside a single file — the same multi-site drift
`test_docs_pipeline_parity.py` exists to catch for the push pipeline.

The exit-criteria table also shipped in TWO places at once and had already
diverged on arrival, which is what the repo's "link, don't summarize" learning
is about. `test_stage_criteria_table_has_exactly_one_home` is the lock on that.
"""
from __future__ import annotations

import re
from collections.abc import Callable
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
    """GitHub's heading->anchor slug: lowercase, drop punctuation, then one
    hyphen per remaining space.

    Each space maps to its own hyphen — runs are NOT collapsed. That matters
    here because dropping an em-dash from `Foo — bar` leaves two spaces, and
    GitHub's real slug is `foo--bar`. Collapsing them produced `foo-bar`, which
    marked a correct link as dangling and, worse, would have accepted a link
    that GitHub resolves to nothing.
    """
    slug = heading_text.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    return re.sub(r"\s", "-", slug)


def _anchors_in(doc: Path) -> set[str]:
    return {
        _github_anchor(m.group(1))
        for m in re.finditer(r"^#{1,6}\s+(.+?)\s*$", doc.read_text("utf-8"), re.M)
    }


# Append-only records: a change-log entry, a shipped release note or an archived
# doc states what was true when it was written and is never edited afterwards, so
# a heading renamed later would strand a link there permanently and the only way
# to green the suite would be to rewrite history. Living docs are policed; the
# record of the past is not.
_APPEND_ONLY = (
    "CHANGELOG.md",
    ".prawduct/change-log.md",
    ".prawduct/release-notes.md",
    ".prawduct/reflections.md",
    # The backlog cut over to GitHub Issues and its own header now reads
    # "FROZEN HISTORY ... Preserve it verbatim" — it is the migration's source
    # corpus, which `verify-migration` and any rollback read. Its references
    # therefore cannot be repaired even when a heading they cite is renamed
    # later, which is the same bind the entries above are exempted for.
    ".prawduct/backlog.md",
)
_APPEND_ONLY_DIRS = ("archive", "reflections-archive")


def _markdown_files() -> list[Path]:
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "songs"}
    out = []
    for p in _REPO.rglob("*.md"):
        rel = p.relative_to(_REPO)
        if any(part in skip for part in rel.parts):
            continue
        if rel.as_posix() in _APPEND_ONLY:
            continue
        if any(d in part for part in rel.parts for d in _APPEND_ONLY_DIRS):
            continue
        out.append(p)
    return out


def _resolve_refs(
    pattern: re.Pattern[str],
    resolve: "Callable[[Path, str], Path]",
) -> list[str]:
    """Report every `<doc>.md#<anchor>` reference `pattern` finds that does not
    land on a real heading in a real file. `resolve` turns a reference's path
    text into an absolute path — the two callers differ only there (one link
    form is relative to the citing file, the other to the repo root)."""
    cache: dict[Path, set[str]] = {}
    broken: list[str] = []
    for md in _markdown_files():
        for m in pattern.finditer(md.read_text("utf-8")):
            rel, anchor = m.group(1), m.group(2)
            here = md.relative_to(_REPO)
            target = resolve(md, rel)
            if not target.exists():
                broken.append(f"{here} -> {rel} (no such file)")
                continue
            if target not in cache:
                cache[target] = _anchors_in(target)
            if anchor not in cache[target]:
                broken.append(f"{here} -> {rel}#{anchor}")
    return broken


def test_song_workflow_doc_carries_both_linked_anchors():
    """Nine skills + three docs deep-link into these two headings. Renaming
    either silently breaks every one of those links."""
    anchors = _anchors_in(_WORKFLOW_DOC)
    for required in ("stage-exit-criteria", "definitions-of-done"):
        assert required in anchors, (
            f"docs/song-workflow.md lost the '#{required}' heading — the skills "
            "and docs that deep-link to it now point at nothing"
        )


_MARKDOWN_LINK = re.compile(r"\]\((?!https?:)([^)\s]+\.md)#([\w-]+)\)")


def test_every_markdown_deeplink_resolves():
    """Every relative `some-doc.md#anchor` link in the repo must hit a real
    heading in a real file.

    Scoped to `song-workflow.md` originally, which is why a renamed heading in
    a design artifact sat dangling: the link that pointed at it lived in the
    backlog and named a different file. A cross-file rename breaks links
    wherever they happen to live, so the check has to be repo-wide.
    """
    broken = _resolve_refs(_MARKDOWN_LINK, lambda md, rel: (md.parent / rel).resolve())
    assert not broken, "dangling markdown anchors: " + "; ".join(broken)


# Bare repo-root-relative doc references — the shape the backlog's `refs:` field
# uses. They carry no link syntax, so the check above cannot see them, and both
# of the dangling anchors this test was widened for lived in exactly this form.
_BARE_DOC_REF = re.compile(
    r"(?<![(\w/])"
    r"((?:\.prawduct|docs|skills|examples)/[\w./-]+\.md)"
    r"#([\w-]+)"
)


def test_every_bare_doc_reference_resolves():
    """A `path/to/doc.md#anchor` written as bare text — the backlog's `refs:`
    idiom — must resolve too."""
    broken = _resolve_refs(_BARE_DOC_REF, lambda md, rel: _REPO / rel)
    assert not broken, "dangling bare doc references: " + "; ".join(broken)


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
