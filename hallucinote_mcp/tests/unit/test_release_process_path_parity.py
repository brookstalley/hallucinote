"""``docs/release-process.md`` step 5 restates three code constants as greps.

The release cutter runs those two commands and writes the consumer-facing
``Re-vendor:`` verdict from what they print. The path sets they encode —
``_FINGERPRINT_PATHS`` for the hard question, ``REMOTE_SCRIPT_EXCLUDE_DIRS_ANY``
and ``REMOTE_SCRIPT_EXCLUDE_TOP_LEVEL_FILES`` for the advisory one — live in
code and change there. Add a directory to the excludes or a path to the
fingerprint tuple and the doc keeps answering with the old set, so a cutter
records ``Re-vendor: not required`` when the honest verdict is ``recommended``
or ``required``: a wrong verdict derived from a stale path list, which is #310's
own failure one layer up.

Nothing else pins them, so this does. The greps are read out of the document
itself rather than copied here — a copy would be a fourth carrier of the same
rule, and the drift would just move.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from hallucinote_mcp import _FINGERPRINT_PATHS, install_paths as P

_DOC = (
    pathlib.Path(__file__).resolve().parents[3] / "docs" / "release-process.md"
)
_VENDOR_PREFIX = "hallucinote_mcp/src/hallucinote_mcp/"


def _doc_text() -> str:
    return _DOC.read_text(encoding="utf-8")


def _extract_greps() -> tuple[re.Pattern[str], re.Pattern[str]]:
    """The step-5 hard `grep -E` and advisory `grep -vE` expressions, in order.

    A ``grep -E`` line in this document ends with a backslash and continues on
    the next line inside single quotes, so the pattern is the quoted run.
    """
    text = _doc_text()
    quoted = re.findall(r"grep\s+-v?E\s*\\\n\s*'([^']+)'", text)
    assert len(quoted) >= 2, (
        f"expected step 5's two grep expressions in {_DOC.name}; found {quoted}"
    )
    return re.compile(quoted[0]), re.compile(quoted[1])


def _is_fingerprinted(rel: str) -> bool:
    """The code's answer to the hard question, for a path relative to the
    vendored package root."""
    head = rel.split("/", 1)[0]
    return head in _FINGERPRINT_PATHS


def _is_vendored(rel: str) -> bool:
    """The code's answer to "does the install ship this file into Live", read
    from the same predicate the copy itself uses."""
    parts = rel.split("/")
    if parts[0] in P.REMOTE_SCRIPT_EXCLUDE_DIRS_ANY:
        return False
    if len(parts) == 1 and parts[0] in P.REMOTE_SCRIPT_EXCLUDE_TOP_LEVEL_FILES:
        return False
    return True


# The greps' input is `git diff --name-only`, so their domain is TRACKED paths.
# `__pycache__/` and `*.pyc` are gitignored, so they can never appear there and
# the doc is under no obligation to exclude them — asserting it does would fail
# the doc over a case it cannot meet. Every other vendor exclude is a directory
# of real tracked source, which is exactly what the grep has to get right.
_UNTRACKABLE_EXCLUDES = ("__pycache__",)


def _corpus() -> list[str]:
    """Representative paths generated FROM the constants, so adding an element
    to any of them adds a case here without anyone editing this file."""
    rels: list[str] = []
    for entry in _FINGERPRINT_PATHS:
        rels.append(entry if entry.endswith(".py") else f"{entry}/thing.py")
    for excluded in P.REMOTE_SCRIPT_EXCLUDE_DIRS_ANY:
        if excluded in _UNTRACKABLE_EXCLUDES:
            continue
        rels.append(f"{excluded}/thing.py")
    for excluded in P.REMOTE_SCRIPT_EXCLUDE_TOP_LEVEL_FILES:
        rels.append(excluded)
    # Vendored, executed in Live, outside the handshake — the class the advisory
    # grep exists for. Named literally because they are not derivable from a
    # constant; the assertion below is what makes them load-bearing.
    rels += [
        "analyzer/setup.py",
        "resources/guides/conventions.md",
        "client.py",
        "install_paths.py",
        "server_side/analysis.py",
    ]
    return rels


@pytest.mark.parametrize("rel", _corpus())
def test_the_step_5_greps_agree_with_the_constants(rel):
    hard_grep, advisory_exclude = _extract_greps()
    path = _VENDOR_PREFIX + rel

    assert bool(hard_grep.search(path)) is _is_fingerprinted(rel), (
        f"docs/release-process.md's hard grep and _FINGERPRINT_PATHS disagree "
        f"about {path!r}: the doc says "
        f"{'fingerprinted' if hard_grep.search(path) else 'not fingerprinted'}, "
        f"the constant says the opposite. Update the grep in step 5."
    )

    # The advisory command is `grep <prefix> | grep -vE <exclude>`: a path is
    # advisory-reported when it is under the package AND survives the exclude
    # AND is not already a hard hit.
    doc_advisory = (
        not advisory_exclude.search(path) and not hard_grep.search(path)
    )
    code_advisory = _is_vendored(rel) and not _is_fingerprinted(rel)
    assert doc_advisory is code_advisory, (
        f"docs/release-process.md's advisory grep and the vendor excludes "
        f"disagree about {path!r}: doc says "
        f"{'reported' if doc_advisory else 'not reported'}, code says "
        f"{'vendored-and-not-fingerprinted' if code_advisory else 'not'}. "
        "Update the `grep -vE` in step 5."
    )


def test_the_extractor_finds_the_greps_it_claims_to_read():
    """Guard the guard: if the document is reformatted so the regex above finds
    nothing, every parametrized case would vanish and the file would still be
    green — a parity test that pins nothing."""
    hard_grep, advisory_exclude = _extract_greps()
    assert "wire" in hard_grep.pattern and "handlers" in hard_grep.pattern
    assert "cli" in advisory_exclude.pattern and "tests" in advisory_exclude.pattern


def test_the_version_table_row_names_the_helper_not_a_path_list():
    """The *Vendored content* row is the third carrier of the same rule. It is
    correct while it points at the helper that computes the answer; a path list
    there would drift like the greps."""
    text = _doc_text()
    row = next(
        line for line in text.splitlines()
        if line.startswith("| **Vendored content**")
    )
    assert "vendored_content_fingerprint" in row, row
    assert "preflight" in row, row
