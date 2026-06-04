"""Structural check: the install/uninstall skills orchestrate via the CLI.

Every filesystem mutation now runs through tested, atomic CLI subcommands
(``install-remote-script`` / ``install-analyzer`` and their uninstall mirrors); the
skill bodies must *invoke* those, not hand-author
``rsync``/``robocopy``/``rm``/``Move-Item`` or manual JSON edits. The install skill
no longer writes MCP config at all — since INS-7V2D the plugin provides the server
via its bundled uv launch, so there is no ``configure-mcp`` counterpart; uninstall
still mirrors with ``remove-mcp-config`` to clear legacy entries.

This file used to assert the SKILL.md's rsync/robocopy exclude *strings* were
anchored correctly. That contract MOVED — the excludes are now applied in Python
and verified behaviorally in ``test_install_ops.py`` (anchored package-root
``server.py`` out, ``remote_script/server.py`` kept, dirs/globs out, plus
atomicity). Asserting a real behavior beats asserting a doc string, so the old
string-drift tests are consolidated here into "the skill calls the CLI and ships
no hand-authored mutation shell." (Test consolidation, build-plan Chunk 4.)
"""
from __future__ import annotations

import pathlib

import pytest

_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[3] / "skills"
INSTALL_SKILL = _SKILLS_ROOT / "ableton-mcp-install" / "SKILL.md"
UNINSTALL_SKILL = _SKILLS_ROOT / "ableton-mcp-uninstall" / "SKILL.md"


@pytest.fixture(scope="module")
def install_text() -> str:
    assert INSTALL_SKILL.exists(), f"install SKILL.md missing at {INSTALL_SKILL}"
    return INSTALL_SKILL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def uninstall_text() -> str:
    assert UNINSTALL_SKILL.exists(), f"uninstall SKILL.md missing at {UNINSTALL_SKILL}"
    return UNINSTALL_SKILL.read_text(encoding="utf-8")


# Hand-authored mutation shell that must NOT appear in the skills' COMMAND blocks
# — the whole point of the redesign is that none of this lives in the doc anymore.
# (Prose may still *mention* these to explain what the skill deliberately avoids;
# the contract is about fenced command blocks, not the narrative.)
_FORBIDDEN_MUTATION_SHELL = (
    "rsync",
    "robocopy",
    "Copy-Item",
    "--exclude=",
    "/XF",
    "/XD",
    "rm -rf",
    "Remove-Item",
    "Move-Item",
)


def _fenced_blocks(text: str) -> str:
    """Join every fenced code block in `text` (the actual commands, not prose)."""
    blocks: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("```"):
            start = i + 1
            end = next((j for j in range(start, len(lines)) if lines[j].lstrip().startswith("```")), None)
            if end is None:
                break
            blocks.append("\n".join(lines[start:end]))
            i = end + 1
        else:
            i += 1
    return "\n".join(blocks)


def _assert_no_mutation_shell(text: str, label: str) -> None:
    code = _fenced_blocks(text)
    for token in _FORBIDDEN_MUTATION_SHELL:
        assert token not in code, (
            f"{label} SKILL.md must not hand-author mutation shell ({token!r}) in a "
            "command block — the atomic CLI subcommands own every mutation now"
        )


def test_install_skill_invokes_cli_subcommands(install_text):
    for cmd in ("install-remote-script", "install-analyzer"):
        assert cmd in install_text, f"install SKILL.md must invoke `{cmd}`"


def test_install_skill_does_not_resurrect_configure_mcp(install_text):
    """The plugin provides the server now — the install skill must NOT call a
    config-writing subcommand (the retired PATH-override hack)."""
    assert "configure-mcp" not in install_text, (
        "install SKILL.md must not invoke `configure-mcp` — the plugin provides the "
        "server via uv; the skill writes no MCP config (INS-7V2D)"
    )


def test_install_skill_has_no_handauthored_mutation_shell(install_text):
    _assert_no_mutation_shell(install_text, "install")


def test_uninstall_skill_invokes_cli_subcommands(uninstall_text):
    for cmd in ("uninstall-remote-script", "uninstall-analyzer", "remove-mcp-config"):
        assert cmd in uninstall_text, f"uninstall SKILL.md must invoke `{cmd}`"


def test_uninstall_skill_has_no_handauthored_removal_shell(uninstall_text):
    _assert_no_mutation_shell(uninstall_text, "uninstall")


def test_install_skill_documents_analyzer_and_suite(install_text):
    """The analyzer step must still name the device, its Live directory, and the
    Suite/Max-for-Live requirement (the user-facing facts the CLI doesn't surface)."""
    assert "HallucinoteAnalyzer.amxd" in install_text
    assert "Max Audio Effect" in install_text
    assert "max_for_live_available" in install_text
    assert "Live Suite" in install_text


# --- structural skills auto-load the analyzer (unchanged; unrelated to the rewrite) ---

_SKILLS_WITH_AUTOLOAD_POSTLUDE = (
    "track-new-with-instrument",
    "return-new",
    "song-new",
)


@pytest.mark.parametrize("skill_name", _SKILLS_WITH_AUTOLOAD_POSTLUDE)
def test_structural_skill_has_analyzer_autoload_postlude(skill_name):
    """Every skill that mutates structural surfaces must end with
    ``ableton_render(action='ensure_loaded')`` so analyzer placement keeps up."""
    path = _SKILLS_ROOT / skill_name / "SKILL.md"
    assert path.exists(), f"missing SKILL.md at {path}"
    text = path.read_text(encoding="utf-8")
    assert "ableton_render(action='ensure_loaded')" in text, (
        f"{skill_name} SKILL.md must invoke ableton_render(action='ensure_loaded') "
        "as its postlude — see audio-analysis MVP Chunk 2 spec"
    )
