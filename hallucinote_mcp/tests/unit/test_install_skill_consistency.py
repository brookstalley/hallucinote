"""Structural drift check: SKILL.md copy commands must use anchored excludes.

The install SKILL.md hard-codes example rsync ``--exclude=...`` flags and
robocopy ``/XF`` / ``/XD`` arguments for the Remote Script copy. The
authoritative source is :mod:`hallucinote_mcp.install_paths` — losing an
entry, OR using an unanchored form of ``server.py``, silently breaks the
install:

- Unanchored rsync ``--exclude='server.py'`` also strips
  ``remote_script/server.py`` (the Control Surface entrypoint Live LOADS).
- Unanchored robocopy ``/XF server.py`` does the same.

Per ``project-preferences.md`` (Enforcement section), drift surfaces like
this are enforced via tests, not Critic.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from hallucinote_mcp.install_paths import (
    REMOTE_SCRIPT_EXCLUDE_DIRS_ANY,
    REMOTE_SCRIPT_EXCLUDE_FILE_GLOBS_ANY,
    REMOTE_SCRIPT_EXCLUDE_TOP_LEVEL_FILES,
)


SKILL_PATH = (
    pathlib.Path(__file__).resolve().parents[3]
    / ".claude" / "skills"
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


def _extract_all_rsync_blocks(text: str) -> list[str]:
    """Every fenced block in Step 3b that contains an `rsync` invocation.

    The skill ships two: a templated form (``<package.rsync_exclude_args ...>``)
    and an expanded example. The drift check below scans only the
    EXPANDED example, since the templated form is intentionally
    unevaluated placeholder text.
    """
    blocks: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("```"):
            start = i + 1
            end = next(
                (j for j in range(start, len(lines)) if lines[j].lstrip().startswith("```")),
                None,
            )
            if end is None:
                break
            body = "\n".join(lines[start:end])
            if "rsync" in body:
                blocks.append(body)
            i = end + 1
        else:
            i += 1
    return blocks


def test_rsync_example_uses_anchored_server_py_exclude(skill_text):
    """The expanded rsync example must show ``--exclude=/server.py``
    (with the leading slash). An unanchored form would strip
    ``remote_script/server.py`` — the very file Live loads."""
    rsync_blocks = _extract_all_rsync_blocks(skill_text)
    # We only care about blocks that show real example flags (not the
    # placeholder ``<package.rsync_exclude_args joined by space>`` form).
    example_blocks = [
        b for b in rsync_blocks if re.search(r"--exclude=[^<]", b)
    ]
    assert example_blocks, "no rsync example block with literal --exclude flags found"
    for block in example_blocks:
        # Anchored form must appear for every top-level file.
        for name in REMOTE_SCRIPT_EXCLUDE_TOP_LEVEL_FILES:
            assert re.search(rf"--exclude=/{re.escape(name)}\b", block), (
                f"rsync example must anchor {name!r} with a leading slash "
                "(otherwise it strips remote_script/server.py too):\n" + block
            )
            # Unanchored form must NOT appear (anti-regression).
            unanchored_pat = rf"--exclude=(?P<q>['\"]?){re.escape(name)}(?P=q)(?!\S)"
            unanchored_matches = [
                m for m in re.finditer(unanchored_pat, block)
                # A '/' immediately before the name means it WAS anchored
                # — those matches don't count as the unanchored shape.
                if block[max(0, m.start() - 1)] != "/"
            ]
            assert not unanchored_matches, (
                f"rsync example must not include an unanchored {name!r} exclude "
                "(would strip remote_script/server.py):\n" + block
            )
        # Any-position excludes must still appear.
        for name in REMOTE_SCRIPT_EXCLUDE_DIRS_ANY:
            assert re.search(rf"--exclude={re.escape(name)}\b", block), (
                f"rsync example missing --exclude={name}:\n" + block
            )
        for glob in REMOTE_SCRIPT_EXCLUDE_FILE_GLOBS_ANY:
            assert re.search(rf"--exclude={re.escape(glob)}\b", block), (
                f"rsync example missing --exclude={glob}:\n" + block
            )


def test_robocopy_example_uses_full_path_for_server_py(skill_text):
    """robocopy ``/XF`` matches basenames anywhere unless given an absolute
    path. The example must show the package-rooted path
    ``<package.root>\\server.py`` so ``remote_script\\server.py`` survives."""
    robocopy_blocks = [
        _extract_fenced_block(skill_text, h)
        for h in ("robocopy",)
    ]
    # Filter to the EXPANDED example (the one with literal /XF, not the
    # ``<package.robocopy_exclude_args ...>`` placeholder).
    examples = [b for b in robocopy_blocks if re.search(r"/XF\s+\S", b)]
    # The doc has both a placeholder form and an expanded example; pull
    # any expanded example out of the page.
    all_blocks: list[str] = []
    lines = skill_text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("```"):
            start = i + 1
            end = next(
                (j for j in range(start, len(lines)) if lines[j].lstrip().startswith("```")),
                None,
            )
            if end is None:
                break
            body = "\n".join(lines[start:end])
            if "robocopy" in body and "/XF" in body and "<package.robocopy" not in body:
                all_blocks.append(body)
            i = end + 1
        else:
            i += 1
    assert all_blocks, "no expanded robocopy example with /XF found"
    for block in all_blocks:
        for name in REMOTE_SCRIPT_EXCLUDE_TOP_LEVEL_FILES:
            # Must reference the package root path with this filename.
            # The skill writes ``<package.root>\server.py`` as a literal
            # placeholder + literal backslash + filename.
            pat = rf"<package\.root>[\\/]+{re.escape(name)}\b"
            assert re.search(pat, block), (
                f"robocopy example must use absolute path for {name!r} so "
                f"only the package-root file is excluded:\n{block}"
            )
            # The bare unanchored ``/XF server.py`` form must NOT appear
            # — that would strip every server.py at any depth.
            bare_pat = rf"/XF\s+(?:\S+\s+)*{re.escape(name)}\b(?![\\/])"
            assert not re.search(bare_pat, block), (
                f"robocopy example must not pass bare basename {name!r} to /XF "
                f"(would strip remote_script\\server.py too):\n{block}"
            )
        for name in REMOTE_SCRIPT_EXCLUDE_DIRS_ANY:
            assert re.search(rf"/XD\s+(?:\S+\s+)*{re.escape(name)}\b", block), (
                f"robocopy example missing /XD ... {name}:\n{block}"
            )
        for glob in REMOTE_SCRIPT_EXCLUDE_FILE_GLOBS_ANY:
            assert re.search(rf"/XF\s+(?:\S+\s+)*{re.escape(glob)}", block), (
                f"robocopy example missing {glob!r} under /XF:\n{block}"
            )


def test_copy_item_fallback_removes_top_level_server_py_explicitly(skill_text):
    """The PowerShell fallback (Copy-Item + Remove-Item) is the third command
    surface. The Remove-Item for ``server.py`` must target the package-root
    file by full path — and must NOT recursively strip every ``server.py``."""
    fallback_block = _extract_fenced_block(skill_text, "robocopy isn't available")
    # Explicit single-file remove of the top-level server.py.
    for name in REMOTE_SCRIPT_EXCLUDE_TOP_LEVEL_FILES:
        # Some path that ends in \server.py at the hallucinote_mcp root,
        # NOT inside remote_script.
        assert re.search(
            rf"hallucinote_mcp[\\/]+{re.escape(name)}\b",
            fallback_block,
        ), f"PowerShell fallback must remove {name!r} at the package root:\n{fallback_block}"
        # Anti-regression: no recursive removal of server.py from any depth.
        bad = re.search(
            rf"Get-ChildItem[^\n]*-Filter\s+{re.escape(name)}",
            fallback_block,
        )
        assert not bad, (
            f"PowerShell fallback must not recursively remove {name!r} "
            f"(would strip remote_script\\server.py):\n{fallback_block}"
        )
    # Dirs / globs still need to be cleaned up.
    for name in REMOTE_SCRIPT_EXCLUDE_DIRS_ANY:
        assert name in fallback_block, (
            f"PowerShell fallback missing cleanup for {name!r}:\n{fallback_block}"
        )
    for glob in REMOTE_SCRIPT_EXCLUDE_FILE_GLOBS_ANY:
        assert glob in fallback_block, (
            f"PowerShell fallback missing cleanup for {glob!r}:\n{fallback_block}"
        )


def test_sanity_check_lists_specific_disallowed_paths(skill_text):
    """The Step 3c warning must name each excluded entry explicitly.

    Earlier draft asserted only ``"no" in text.lower()`` which is true for
    any English prose. This version pins the actual contract: each
    excluded name must appear in the warning narrative so an agent
    debugging a broken install knows what to look for.
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
    every_excluded = (
        *REMOTE_SCRIPT_EXCLUDE_TOP_LEVEL_FILES,
        *REMOTE_SCRIPT_EXCLUDE_DIRS_ANY,
    )
    for name in every_excluded:
        assert name in section, (
            f"Step 3c sanity-check narrative must mention {name!r} "
            f"so an agent debugging a broken install knows what to check"
        )
    assert "FastMCP" in section, (
        "skill must explain why server.py is excluded (FastMCP-dependent)"
    )
