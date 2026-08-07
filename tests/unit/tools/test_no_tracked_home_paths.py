"""No git-tracked file may carry an absolute home path.

The emission-point guards (`tests/unit/audio/test_analyze.py`,
`hallucinote_mcp/tests/unit/test_handlers_analysis.py`) stop the analyzer from
WRITING an account name into a report. This one is the belt-and-braces companion:
it asserts nothing carrying one is TRACKED, whatever produced it.

Both are needed, and the gap between them is exactly how this got in. Four
analyzer reports were hand-committed while the repo's own redaction tool
(`tools/tour_transcript.py`) was refusing to publish the same strings — one part
of the codebase committing what another part fails closed rather than emit. An
emission guard cannot see a file added by hand, and a scan cannot see a code path
that has not run yet.

The rule is imported from `tour_transcript.FORBIDDEN` rather than restated, so
the write side, the publish side and this scan cannot drift apart. That
disagreement WAS the defect; a second private copy of the rule would rebuild it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from tools.tour_transcript import FORBIDDEN

REPO_ROOT = Path(__file__).resolve().parents[3]


#: Account names documentation uses as stand-ins. Not an allowlist of real
#: accounts — every entry here is a name no human on this project has.
_PLACEHOLDER_ACCOUNTS = frozenset({
    "alice", "bob", "carol", "dave", "eve", "jane", "john",
    "user", "username", "someone", "you", "me", "account", "name", "acct",
    "youruser", "yourname", "example",
})


def _is_placeholder_account(hit: str) -> bool:
    """True when a home-path hit names a placeholder rather than a real account.

    Documentation writes `/Users/<name>` and `/Users/...`; the redaction tests
    write `/Users/test-account` and `/Users/testuser` **because they must** — a
    test that the gate catches an account name needs an account name to catch.
    Flagging those would make the scan unfixable, and the pressure would be to
    delete the scan rather than the leak.

    Only the home-path patterns produce a `/Users/<segment>`-shaped hit; token
    and key patterns never reach here with one, so they are never exempted.
    """
    parts = hit.replace("-Users-", "/Users/").replace("-home-", "/home/")
    segment = parts.rsplit("/", 1)[-1].strip()
    if not segment:
        return True
    if segment.startswith(("<", ".")):        # /Users/<name>, /Users/...
        return True
    low = segment.lower()
    if low.startswith("test"):                # /Users/test-account, testuser
        return True
    if low in _PLACEHOLDER_ACCOUNTS:          # /Users/alice — doc convention
        return True
    if len(segment) <= 2:                     # /Users/x — obviously synthetic
        return True
    return False


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    files = []
    for rel in out.split("\0"):
        if not rel:
            continue
        p = REPO_ROOT / rel
        if p.is_file():
            files.append(p)
    return files


def test_no_tracked_file_carries_an_absolute_home_path():
    """Scan every tracked file against the publish gate's own forbidden set.

    Skips this test file and the tool that defines the patterns — both name the
    patterns on purpose, and gating on them would refuse the rule's own
    definition.
    """
    self_rel = Path(__file__).resolve().relative_to(REPO_ROOT)
    exempt = {
        self_rel,
        Path("tools/tour_transcript.py"),
        Path("tests/unit/tools/test_tour_transcript.py"),
    }

    offenders: list[str] = []
    for path in _tracked_text_files():
        rel = path.relative_to(REPO_ROOT)
        if rel in exempt:
            continue
        # Fixture trees exist to CONTAIN forbidden content — a redaction test
        # needs an unredacted sample to redact. Scanning them would force the
        # fixtures to be defanged, which would quietly disarm the real gate.
        if "fixtures" in rel.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable — no account name to leak as text
        # FORBIDDEN is a tuple of (compiled_pattern, description) pairs.
        for pattern, description in FORBIDDEN:
            for match in pattern.finditer(text):
                hit = match.group(0)
                if _is_placeholder_account(hit):
                    continue
                offenders.append(f"{rel}: {description} — {hit[:80]!r}")
                break
            else:
                continue
            break

    assert not offenders, (
        "tracked file(s) carry an absolute home path — this repo is meant to go "
        "public, and git history is permanent:\n  "
        + "\n  ".join(offenders)
    )
