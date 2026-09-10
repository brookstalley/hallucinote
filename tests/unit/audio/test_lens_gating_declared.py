"""Every measurement block on a MixReport declares whether it gates.

The tripwire for a lens that ships inert. `sum_reconciliation` was computed on
every report, serialized on every report and read by nothing for the life of
the render-integrity work — and the suite was green throughout, because its
tests asserted the number existed and was correct, which is indistinguishable
from a lens that gates nothing.

These tests make the distinction explicit rather than inferable: a block is
either wired to a `_derive_findings` parameter or it is on the evidence-only
list with a stated reason. A new lens that is neither fails here.
"""
from __future__ import annotations

import dataclasses
import inspect

import pytest

from hallucinote.audio.analyze import _derive_findings
from hallucinote.audio.report import (
    EVIDENCE_ONLY_BLOCKS,
    FINDING_BEARING_BLOCKS,
    MixReport,
)

# Identity, provenance and derived payloads — not measurements, so the
# gates-or-evidence question does not apply to them.
_NOT_A_MEASUREMENT = frozenset({
    "song_slug", "captures_dir", "captured_at", "analyzer_signature",
    "schema_version", "findings", "skipped_analyses", "compare_to", "db_seq",
    "measurement_basis", "master_fader_volume", "master_fader_db",
    "delivered_true_peak_dbtp", "master_fader_source", "master_fader_verified",
    "master_fader_note",
})


def _measurement_blocks() -> set[str]:
    return {
        f.name for f in dataclasses.fields(MixReport)
        if f.name not in _NOT_A_MEASUREMENT
    }


def test_every_lens_block_declares_whether_it_gates():
    """A block in neither map is a lens nobody decided about — which is the
    state `sum_reconciliation` shipped in."""
    classified = set(FINDING_BEARING_BLOCKS) | set(EVIDENCE_ONLY_BLOCKS)
    undeclared = _measurement_blocks() - classified
    assert not undeclared, (
        f"MixReport blocks {sorted(undeclared)} are neither wired to a finding "
        f"nor declared evidence-only. Add each to FINDING_BEARING_BLOCKS (with "
        f"the _derive_findings parameter that reads it) or to "
        f"EVIDENCE_ONLY_BLOCKS (with the reason it does not gate)."
    )


def test_no_block_is_declared_both_ways():
    overlap = set(FINDING_BEARING_BLOCKS) & set(EVIDENCE_ONLY_BLOCKS)
    assert not overlap, f"{sorted(overlap)} declared as both gating and evidence"


def test_every_declared_block_is_a_real_field():
    """The maps cannot outlive the fields they classify."""
    fields = {f.name for f in dataclasses.fields(MixReport)}
    for name in (*FINDING_BEARING_BLOCKS, *EVIDENCE_ONLY_BLOCKS):
        assert name in fields, f"{name!r} is classified but is not a MixReport field"


@pytest.mark.parametrize(
    ("block", "param"), sorted(FINDING_BEARING_BLOCKS.items())
)
def test_a_finding_bearing_block_actually_reaches_the_deriver(block, param):
    """Declaring a block finding-bearing is a claim `_derive_findings` reads
    it. If the parameter is gone, the claim is stale and the block is inert
    again — exactly the state this file exists to prevent."""
    params = inspect.signature(_derive_findings).parameters
    assert param in params, (
        f"MixReport.{block} is declared finding-bearing via the "
        f"_derive_findings parameter {param!r}, which no longer exists"
    )


def test_every_evidence_only_block_states_a_reason():
    for block, reason in EVIDENCE_ONLY_BLOCKS.items():
        assert reason and len(reason.split()) >= 8, (
            f"{block!r} is declared evidence-only without a reason that says "
            f"why — a bare exemption is how a lens that should gate hides"
        )
