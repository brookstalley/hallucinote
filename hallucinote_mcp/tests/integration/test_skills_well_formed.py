"""Sanity checks on the two install/uninstall skills.

The skills live at the Hallucinote repo's ``skills/`` (the de facto
slash-command home). These tests verify the structural contract Claude Code
expects (a name, a description, and a body that follows). If the frontmatter
shape changes, this catches it at test time rather than at first
``/ableton-mcp-install`` invocation.
"""
from __future__ import annotations

import pathlib
import re

import pytest


# The repo's skills/ — three parents up from this test file:
# tests/integration/test_skills_well_formed.py → tests/ → hallucinote_mcp/ → <repo>
SKILLS_DIR = pathlib.Path(__file__).resolve().parents[3] / "skills"

EXPECTED_SKILLS = ("ableton-mcp-install", "ableton-mcp-uninstall")


_FRONTMATTER_PATTERN = re.compile(
    r"\A---\n(.*?)\n---\n(.*)\Z",
    re.DOTALL,
)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_PATTERN.match(text)
    if match is None:
        raise AssertionError("skill missing YAML frontmatter delimited by ---")
    fm_text, body = match.group(1), match.group(2)
    fields: dict[str, str] = {}
    for line in fm_text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, body


@pytest.mark.parametrize("slug", EXPECTED_SKILLS)
def test_skill_directory_present(slug: str):
    skill_dir = SKILLS_DIR / slug
    assert skill_dir.is_dir(), f"missing {skill_dir}"
    assert (skill_dir / "SKILL.md").exists(), f"missing {skill_dir / 'SKILL.md'}"


@pytest.mark.parametrize("slug", EXPECTED_SKILLS)
def test_skill_has_name_and_description(slug: str):
    text = (SKILLS_DIR / slug / "SKILL.md").read_text(encoding="utf-8")
    fields, body = _parse_frontmatter(text)
    assert fields.get("name") == slug, f"frontmatter name must match folder slug for {slug}"
    description = fields.get("description", "")
    assert description, f"{slug} description is empty"
    # Description guidance: should be specific about when to use the skill,
    # not just "installs/removes things". A meaningful description is at
    # least a sentence with the word "use" or "when".
    assert any(w in description.lower() for w in ("use", "when")), (
        f"{slug} description should explain when to use it: got {description!r}"
    )
    assert body.strip(), f"{slug} body is empty"


@pytest.mark.parametrize("slug", EXPECTED_SKILLS)
def test_skill_body_mentions_required_steps(slug: str):
    text = (SKILLS_DIR / slug / "SKILL.md").read_text(encoding="utf-8")
    # Skill bodies should mention the User Library and the MCP config —
    # those are the two filesystem changes the install touches.
    assert "User Library" in text, f"{slug} should mention the Ableton User Library"
    assert ".mcp.json" in text or "claude.json" in text, (
        f"{slug} should mention the MCP config file path"
    )
