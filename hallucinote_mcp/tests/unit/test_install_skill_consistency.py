"""Structural drift check: SKILL.md copy commands must respect REMOTE_SCRIPT_EXCLUDE.

The install SKILL.md hard-codes rsync ``--exclude=...`` flags and robocopy
``/XD`` / ``/XF`` arguments for the Remote Script copy. The authoritative
list is :data:`hallucinote_mcp.install_paths.REMOTE_SCRIPT_EXCLUDE` —
losing an entry from the SKILL silently lets ``server.py`` (FastMCP-
dependent) or ``cli/`` (imports the same) into the Remote Script tree,
where Live's embedded Python fails to import them and aborts the Control
Surface load.

Per ``project-preferences.md`` (Enforcement section), drift surfaces like
this are enforced via tests, not Critic.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from hallucinote_mcp.install_paths import REMOTE_SCRIPT_EXCLUDE


SKILL_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "hallucinote_mcp" / "skills"
    / "ableton-install-mcp" / "SKILL.md"
)


@pytest.fixture(scope="module")
def skill_text() -> str:
    assert SKILL_PATH.exists(), f"install SKILL.md missing at {SKILL_PATH}"
    return SKILL_PATH.read_text(encoding="utf-8")


def _extract_fenced_block(text: str, header_substring: str) -> str:
    """Return the fenced code block following a heading containing the given substring.

    Used to isolate the rsync / robocopy snippets so unrelated text (e.g.
    Step 3c's sanity-check tree, which mentions ``server.py`` in prose)
    doesn't pollute the check.
    """
    lines = text.splitlines()
    idx = next(
        (i for i, line in enumerate(lines) if header_substring in line),
        None,
    )
    assert idx is not None, f"no heading containing {header_substring!r}"
    # Walk forward to the next fenced block.
    start = next(
        (j for j in range(idx + 1, len(lines)) if lines[j].lstrip().startswith("```")),
        None,
    )
    assert start is not None, f"no fenced block after {header_substring!r}"
    end = next(
        (j for j in range(start + 1, len(lines)) if lines[j].lstrip().startswith("```")),
        None,
    )
    assert end is not None, f"unterminated fenced block after {header_substring!r}"
    return "\n".join(lines[start + 1 : end])


def test_rsync_command_excludes_every_remote_script_exclude(skill_text):
    rsync_block = _extract_fenced_block(skill_text, "rsync")
    rsync_excludes = set(re.findall(r"--exclude='([^']+)'", rsync_block))
    missing = [name for name in REMOTE_SCRIPT_EXCLUDE if name not in rsync_excludes]
    assert not missing, (
        f"rsync command is missing excludes from REMOTE_SCRIPT_EXCLUDE: {missing}. "
        f"Found: {sorted(rsync_excludes)}. Authoritative: {sorted(REMOTE_SCRIPT_EXCLUDE)}."
    )


def test_robocopy_command_excludes_every_remote_script_exclude(skill_text):
    robocopy_block = _extract_fenced_block(skill_text, "robocopy")
    # robocopy splits exclusions: /XD <dirs...> and /XF <files...> (each
    # takes a space-separated list of names that ends at the next switch
    # starting with ``/``).
    tokens = set()
    parts = re.split(r"\s+", robocopy_block)
    in_excludes = False
    for tok in parts:
        if tok.startswith("/XD") or tok.startswith("/XF"):
            in_excludes = True
            continue
        if tok.startswith("/"):
            in_excludes = False
            continue
        if in_excludes and tok:
            tokens.add(tok.strip('"'))
    missing = [name for name in REMOTE_SCRIPT_EXCLUDE if name not in tokens]
    assert not missing, (
        f"robocopy command is missing excludes from REMOTE_SCRIPT_EXCLUDE: {missing}. "
        f"Found: {sorted(tokens)}. Authoritative: {sorted(REMOTE_SCRIPT_EXCLUDE)}."
    )


def test_copy_item_fallback_removes_every_remote_script_exclude(skill_text):
    """The PowerShell fallback (Copy-Item + Remove-Item) is the third command surface.

    Old Windows boxes without robocopy hit this path; the previous drift
    test only covered rsync and robocopy. Critic round 2 finding #2.
    """
    # Pick the block immediately after the "If robocopy isn't available"
    # prose. _extract_fenced_block finds the next fenced block after that
    # phrase.
    fallback_block = _extract_fenced_block(skill_text, "robocopy isn't available")
    # The fallback uses Remove-Item with a comma-separated list and a
    # Get-ChildItem ... -Filter loop. Combine both into one token set —
    # the load-bearing assertion is just "every excluded name appears".
    missing = [name for name in REMOTE_SCRIPT_EXCLUDE if name not in fallback_block]
    assert not missing, (
        f"PowerShell Copy-Item fallback is missing exclude removals for: {missing}. "
        f"Block:\n{fallback_block}"
    )


def test_sanity_check_lists_specific_disallowed_paths(skill_text):
    """The Step 3c warning must name each excluded entry explicitly.

    Earlier draft asserted only ``"no" in text.lower()`` which is true for
    any English prose. This version pins the actual contract: each
    REMOTE_SCRIPT_EXCLUDE name must appear in the warning narrative so an
    agent debugging a broken install knows what to look for.
    """
    # Sanity-check narrative lives after the "should contain at minimum" heading.
    # Pull from there to the next H2 / H3 heading.
    lines = skill_text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if "contain at minimum" in line),
        None,
    )
    assert start is not None, "Step 3c narrative not found"
    end = next(
        (j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")),
        len(lines),
    )
    section = "\n".join(lines[start:end])
    for name in REMOTE_SCRIPT_EXCLUDE:
        assert name in section, (
            f"Step 3c sanity-check narrative must mention {name!r} "
            f"so an agent debugging a broken install knows what to check"
        )
    assert "FastMCP" in section, (
        "skill must explain why server.py is excluded (FastMCP-dependent)"
    )
