"""SYN-8Q3F complexity-budget rule 1 (artifact half): every push phase must have
a contract section in ``.prawduct/artifacts/sync-boundary-contract.md``.

The artifact records what each phase ASSUMES vs RE-PROBES and its failure/halt
policy. Adding a phase to ``_PHASE_NAMES`` without documenting its contract is
exactly the quirk-first growth the audit flagged — so it fails the suite instead
of rotting silently. (The dependency half of the rule is ``_PHASE_DEPS`` +
``validate_phase_order``, tested in ``test_push_song.py``.)
"""
from __future__ import annotations

import re
from pathlib import Path

from hallucinote.sync.push.plan import _PHASE_NAMES

_ARTIFACT = (
    Path(__file__).resolve().parents[3]
    / ".prawduct" / "artifacts" / "sync-boundary-contract.md"
)

# One phase section per phase: "### <ordinal>. `<phase_name>`".
_SECTION_RE = re.compile(r"^### (\d+)\. `([a-z_]+)`", re.MULTILINE)


def test_contract_artifact_exists():
    assert _ARTIFACT.is_file(), (
        f"{_ARTIFACT} is missing — the sync boundary contract is a Tier-1 "
        "artifact (SYN-8Q3F); restore it or update this test's path."
    )


def test_every_push_phase_has_a_contract_section():
    text = _ARTIFACT.read_text()
    documented = {m.group(2) for m in _SECTION_RE.finditer(text)}

    missing = set(_PHASE_NAMES) - documented
    assert not missing, (
        f"push phase(s) {sorted(missing)} have no section in "
        f"{_ARTIFACT.name}. A new phase must document its ASSUME / RE-PROBE / "
        "failure-policy contract there (SYN-8Q3F complexity-budget rule 1)."
    )

    stale = documented - set(_PHASE_NAMES)
    assert not stale, (
        f"{_ARTIFACT.name} documents phase(s) {sorted(stale)} that are not in "
        "_PHASE_NAMES — remove or rename the stale section(s)."
    )


def test_contract_sections_are_ordered_like_the_phase_tuple():
    """The artifact lists phases in execution order — a reader must be able to
    trust the ordinals. Pin section order (and ordinals) to ``_PHASE_NAMES``."""
    text = _ARTIFACT.read_text()
    sections = [(int(m.group(1)), m.group(2)) for m in _SECTION_RE.finditer(text)]
    assert sections == [
        (i + 1, name) for i, name in enumerate(_PHASE_NAMES)
    ], (
        "sync-boundary-contract.md phase sections are out of order or "
        "mis-numbered relative to _PHASE_NAMES."
    )
