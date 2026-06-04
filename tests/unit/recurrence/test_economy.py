"""Unit tests for the motivic-economy summary — SYNTHETIC fixtures only. Pins the
description-length facts (cell-set size, coverage, compression proxy), the
registered-never-recalled INFO question, and the info-only / no-verdict contract
(DR-3: there is deliberately NO 'be more economical' finding)."""
from __future__ import annotations

from hallucinote.recurrence.economy import (
    MotivicEconomy,
    economy_finding,
    summarize_economy,
)
from hallucinote.recurrence.lens import MotifRecall


def _recall(motif, section, *, is_home, coverage=1.0, variation="exact"):
    return MotifRecall(
        motif=motif, section=section, layer="lead", variation=variation,
        cell_offset_beats=0.0, coverage=coverage, is_home=is_home)


def test_cell_set_size_and_coverage():
    """One recalled motif, one never-recalled: cell-set size 1, coverage 1/2."""
    registered = ["recalled", "lonely"]
    recalls = [
        _recall("recalled", "home", is_home=True),
        _recall("recalled", "recap", is_home=False),
        _recall("lonely", "home", is_home=True),   # appears once, never recurs
    ]
    econ = summarize_economy(registered, recalls, {"recalled": 9, "lonely": 4})
    assert econ.registered_motifs == 2
    assert econ.recurring_motifs == 1          # only "recalled" recurs beyond home
    assert econ.recall_coverage == 0.5
    assert econ.never_recalled == ("lonely",)


def test_compression_ratio_is_a_fact_in_range():
    """The compression proxy = recalled note-mass ÷ (library mass + occurrence
    records). With a tight reused cell-set it sits in COSIATEC's empirical 2-4 band
    (research.md §2) — reported as a raw fact, no target."""
    registered = ["m"]
    recalls = [_recall("m", "home", is_home=True)] + [
        _recall("m", f"recap{i}", is_home=False) for i in range(6)
    ]
    econ = summarize_economy(registered, recalls, {"m": 9})
    # library 9 + 6 records = 15 encoded; recalled mass 6*9 = 54 -> 3.6
    assert econ.occurrence_records == 6
    assert econ.library_note_mass == 9
    assert abs(econ.compression_ratio - 54 / 15) < 1e-9


def test_fragment_recall_contributes_fractional_note_mass():
    """A fragment recall (coverage < 1) realizes only its sub-window's note share, so
    it adds proportionally less recalled note-mass — the proxy stays honest."""
    econ = summarize_economy(
        ["m"],
        [_recall("m", "home", is_home=True),
         _recall("m", "recap", is_home=False, coverage=0.5, variation="fragment[0,4)")],
        {"m": 8},
    )
    # one non-home recall at coverage 0.5 over 8 notes -> 4 recalled note-mass
    assert econ.recalled_note_mass == 4
    assert econ.occurrence_records == 1


def test_never_recalled_emits_info_question():
    """The ONLY finding the economy path emits: a registered-but-never-recalled INFO
    coaching question (mirrors melody's static-line question)."""
    findings = economy_finding(
        ["recalled", "lonely"],
        [_recall("recalled", "home", is_home=True),
         _recall("recalled", "recap", is_home=False),
         _recall("lonely", "home", is_home=True)],
    )
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == "registered-never-recalled"
    assert f.severity == "info"
    assert f.motif == "lonely"
    assert "?" in f.detail


def test_no_economy_verdict_finding_exists():
    """DR-3: there is deliberately NO 'be more economical' / 'material is scattered'
    finding — economy is style-relative (Temperley). Even a song that recalls NOTHING
    emits only the per-motif never-recalled questions, never a global verdict."""
    registered = ["a", "b"]
    recalls = [_recall("a", "home", is_home=True), _recall("b", "home", is_home=True)]
    findings = economy_finding(registered, recalls)
    kinds = {f.kind for f in findings}
    assert kinds == {"registered-never-recalled"}
    assert all(f.severity == "info" for f in findings)
    # no finding mentions a prescriptive verdict
    assert not any(
        "more economical" in f.detail or "scattered" in f.detail for f in findings)


def test_all_recalled_emits_no_finding():
    """When every registered motif recurs, the economy path emits no finding."""
    findings = economy_finding(
        ["a", "b"],
        [_recall("a", "h", is_home=True), _recall("a", "r", is_home=False),
         _recall("b", "h", is_home=True), _recall("b", "r", is_home=False)],
    )
    assert findings == []


def test_empty_registry_is_well_defined():
    """No registered motifs: a well-defined zero summary, no divide-by-zero."""
    econ = summarize_economy([], [], {})
    assert econ.registered_motifs == 0
    assert econ.recall_coverage == 0.0
    assert econ.compression_ratio == 0.0


def test_economy_to_dict():
    econ = summarize_economy(
        ["m"], [_recall("m", "h", is_home=True), _recall("m", "r", is_home=False)],
        {"m": 9})
    d = econ.to_dict()
    assert {"registered_motifs", "recurring_motifs", "recall_coverage",
            "recalled_note_mass", "library_note_mass", "occurrence_records",
            "compression_ratio", "never_recalled"} == set(d)
    assert isinstance(econ, MotivicEconomy)
