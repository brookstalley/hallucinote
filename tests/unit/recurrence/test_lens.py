"""Unit tests for the recurrence lens — SYNTHETIC fixtures only (test-location
convention: NO song-specific data in tests/unit/). Pins the lens contract (frozen
dataclasses, info-only `ok`/`blocking` parity, `to_dict()` boundary), the
per-(motif × section × layer × variation) recall reporting (incl. the all-layers
scan + containment), and the synthetic `analyze_arrangement` path."""
from __future__ import annotations

import hallucinote.generators.variations as V
from hallucinote.arrangement import Arrangement
from hallucinote.recurrence.lens import (
    RecurrenceFinding,
    SectionRecurrenceInput,
    analyze_arrangement,
    analyze_recurrence,
)


def _n(pitch: int, start: float, dur: float, vel: int = 80, tags=None) -> dict:
    return {"pitch": pitch, "start_beats": start, "duration_beats": dur,
            "velocity": vel, "tags": list(tags or [])}


_MOTIF = [_n(60, 0.0, 0.5), _n(64, 1.0, 0.5), _n(67, 2.0, 0.5), _n(72, 3.0, 1.0)]


class _M:
    """A minimal motif stand-in (name + notes) — the lens only reads `.notes`."""
    def __init__(self, name, notes):
        self.name = name
        self.notes = notes


def _tile(notes, *offsets):
    out: list[dict] = []
    for off in offsets:
        out.extend(V.shift(notes, off))
    return out


def _registry(*pairs):
    """An ordered name->motif mapping (dicts preserve insertion order = home order)."""
    return {name: _M(name, notes) for name, notes in pairs}


# --------------------------------------------------------------------------
# Contract: info-only, ok/blocking parity, to_dict boundary
# --------------------------------------------------------------------------


def test_report_is_info_only_and_ok():
    """The lens emits only `info` findings (authored recurrence is not error), so
    `ok` is always True and `blocking` always empty — parity with the sibling lenses."""
    sections = [
        SectionRecurrenceInput("home", 16.0, {"lead": _tile(_MOTIF, 0.0)}),
        SectionRecurrenceInput("recap", 16.0, {"lead": _tile(_MOTIF, 0.0)}),
    ]
    rep = analyze_recurrence(sections, _registry(("m", _MOTIF)), song_slug="syn")
    assert rep.ok is True
    assert rep.blocking == ()
    assert all(f.severity == "info" for f in rep.findings)


def test_finding_rejects_non_severity():
    import pytest
    with pytest.raises(ValueError):
        RecurrenceFinding(kind="x", severity="bogus", section=None, detail="d")


def test_to_dict_round_trips_structure():
    sections = [
        SectionRecurrenceInput("home", 16.0, {"lead": _tile(_MOTIF, 0.0)}),
        SectionRecurrenceInput("recap", 16.0, {"lead": _tile(V.transpose(_MOTIF, 5), 0.0)}),
    ]
    rep = analyze_recurrence(sections, _registry(("m", _MOTIF)), song_slug="syn")
    d = rep.to_dict()
    assert d["song_slug"] == "syn"
    assert {"sections", "economy", "findings"} <= set(d)
    assert d["sections"][0]["section"] == "home"
    assert "compression_ratio" in d["economy"]
    # every recall dict carries section + layer + variation
    for s in d["sections"]:
        for r in s["recalls"]:
            assert {"motif", "section", "layer", "variation", "coverage", "is_home",
                    "duration_match"} <= set(r)


# --------------------------------------------------------------------------
# Recall reporting: section + layer + variation, home vs recall, all-layers scan
# --------------------------------------------------------------------------


def test_recall_reports_section_layer_variation():
    """A transposed recall in a later section reports section + layer + the specific
    variation, and is NOT marked home (the home is the first appearance)."""
    sections = [
        SectionRecurrenceInput("home", 16.0, {"lead": _tile(_MOTIF, 0.0)}),
        SectionRecurrenceInput("recap", 16.0, {"lead": _tile(V.transpose(_MOTIF, 7), 0.0)}),
    ]
    rep = analyze_recurrence(sections, _registry(("m", _MOTIF)), song_slug="syn")
    recap = [r for r in rep.recalls if r.section == "recap"]
    assert len(recap) == 1
    r = recap[0]
    assert r.layer == "lead"
    assert r.variation == "transpose +7"
    assert r.is_home is False
    # the first appearance is the home occurrence
    home = [r for r in rep.recalls if r.section == "home"]
    assert home and all(h.is_home for h in home)


def test_all_layers_scanned_no_layer_filter():
    """W2: the lens scans EVERY layer — a recall on a NON-lead layer (the polyrhythm-
    on-organ shape) is found. A lead-only filter would miss it."""
    sections = [
        SectionRecurrenceInput("home", 16.0, {"organ": _tile(_MOTIF, 0.0)}),
        SectionRecurrenceInput(
            "climax", 16.0,
            {"lead": [_n(40, 0, 1)], "organ": _tile(_MOTIF, 0.0, 4.0)}),
    ]
    rep = analyze_recurrence(sections, _registry(("m", _MOTIF)), song_slug="syn")
    climax = [r for r in rep.recalls if r.section == "climax"]
    assert any(r.layer == "organ" and r.variation == "exact" for r in climax)


def test_containment_superset_layer_reads_exact_not_derived():
    """W3 regression: a layer that tiles the motif AND carries extra non-motif notes
    (the climax-organ FUSION_CHORD superset shape) reads `exact` via containment —
    not `derived`."""
    busy = _tile(_MOTIF, 0.0, 4.0) + [_n(48, 0, 8.0), _n(55, 0, 8.0), _n(50, 4, 4.0)]
    sections = [
        SectionRecurrenceInput("home", 16.0, {"organ": _tile(_MOTIF, 0.0)}),
        SectionRecurrenceInput("climax", 16.0, {"organ": busy}),
    ]
    rep = analyze_recurrence(sections, _registry(("m", _MOTIF)), song_slug="syn")
    climax = [r for r in rep.recalls if r.section == "climax" and r.layer == "organ"]
    assert any(r.variation == "exact" and r.coverage == 1.0 for r in climax)
    assert not any(r.variation == "derived" for r in climax)


def test_distinct_variations_both_reported_on_one_layer():
    """N1: a layer quoting the motif as BOTH a bare fragment AND a diminish∘fragment
    reports BOTH — the integration-trade shape; neither silently dropped."""
    frag = V.fragment(_MOTIF, 0.0, 2.0)
    layer = _tile(frag, 0.0) + _tile(V.diminish(frag, 2.0), 8.0)
    sections = [
        SectionRecurrenceInput("home", 16.0, {"lead": _tile(_MOTIF, 0.0)}),
        SectionRecurrenceInput("trade", 16.0, {"lead": layer}),
    ]
    rep = analyze_recurrence(sections, _registry(("m", _MOTIF)), song_slug="syn")
    trade = {r.variation for r in rep.recalls if r.section == "trade"}
    assert any(v.startswith("fragment[") for v in trade)
    assert "diminish∘fragment ×2" in trade


def test_no_recall_in_unrelated_section():
    """A section with no quote of the motif reports no recall for it (no false pos)."""
    sections = [
        SectionRecurrenceInput("home", 16.0, {"lead": _tile(_MOTIF, 0.0)}),
        SectionRecurrenceInput(
            "other", 16.0,
            {"lead": [_n(40, 0, 1), _n(41, 1, 1), _n(38, 2, 1), _n(39, 3, 1)]}),
    ]
    rep = analyze_recurrence(sections, _registry(("m", _MOTIF)), song_slug="syn")
    assert not [r for r in rep.recalls if r.section == "other"]


# --------------------------------------------------------------------------
# analyze_arrangement over a synthetic Arrangement (the build-time entry point)
# --------------------------------------------------------------------------


def test_analyze_arrangement_synthetic():
    """The build-time entry point over an in-memory Arrangement: a motif registered
    and recalled (augmented) in a later section is reported with section + layer +
    `augment ×2`, scanning all layers, no filter."""
    arr = Arrangement(beats_per_bar=4.0)
    m = arr.motif("theme", _MOTIF)
    arr.section("a", function="intro", bars=4, layers={"organ": _tile(m.notes, 0.0)})
    arr.section(
        "b", function="outro", bars=4,
        layers={"organ": V.augment(m.notes, 2.0)})
    rep = analyze_arrangement(arr, song_slug="syn")
    assert rep.song_slug == "syn"
    b = [r for r in rep.recalls if r.section == "b"]
    assert any(r.variation == "augment ×2" and r.layer == "organ" for r in b)
    # the recall's section-relative offset is anchored at section b's start (16 beats)
    assert all(r.cell_offset_beats >= 16.0 for r in b)


def test_duration_match_reaches_to_dict_for_a_free_duration_recall():
    """A recall whose onsets and pitches land but whose durations were freely re-sung
    reaches the JSON boundary with the relaxation visible: the `(durations free)`
    qualifier on the label AND `duration_match: False` on the recall dict. Without it
    a reader could not tell an augmentation (durations scaled with the onsets) from an
    onset-only compression."""
    reach = [_n(59, 0.0, 1.5), _n(63, 4.0, 2.0), _n(66, 8.0, 1.5)]
    coda = [_n(71, 0.0, 1.5), _n(75, 2.0, 1.5), _n(78, 4.0, 1.0)]
    sections = [
        SectionRecurrenceInput("verse1", 16.0, {"lead": reach}),
        SectionRecurrenceInput("coda", 16.0, {"lead": coda}, start_beat=16.0),
    ]
    rep = analyze_recurrence(sections, _registry(("reach", reach)), song_slug="syn")
    coda_recalls = [r for r in rep.recalls if r.section == "coda"]
    assert coda_recalls, "the composed transpose+diminish recall must be reported"
    r = coda_recalls[0]
    assert r.variation == "transpose +12 ∘ diminish ×2 (durations free)"
    assert r.duration_match is False
    d = rep.to_dict()["sections"][1]["recalls"][0]
    assert d["duration_match"] is False
    assert d["variation"] == "transpose +12 ∘ diminish ×2 (durations free)"

    # A recall whose durations DO scale with its onsets keeps `duration_match: True`.
    home = [_n(60, 0.0, 0.5), _n(64, 1.0, 0.5), _n(67, 2.0, 0.5)]
    sections = [
        SectionRecurrenceInput("home", 16.0, {"lead": home}),
        SectionRecurrenceInput("outro", 16.0, {"lead": V.augment(home, 2.0)},
                               start_beat=16.0),
    ]
    rep = analyze_recurrence(sections, _registry(("m", home)), song_slug="syn")
    outro = [r for r in rep.recalls if r.section == "outro"]
    assert outro and outro[0].variation == "augment ×2"
    assert all(r.duration_match is True for r in outro)


# --------------------------------------------------------------------------
# The coverage floor: which readings count as recall (min_coverage / partial)
# --------------------------------------------------------------------------


def _derived_half(motif):
    """A layer that matches `motif` under a transpose for only half its notes —
    the tier-4 derived reading (`derived (<op>, <coverage>)`), which is what the
    matcher reports when NO clean op was recoverable."""
    return [_n(65, 0.0, 0.5), _n(69, 1.0, 0.5), _n(70, 2.0, 0.5), _n(71, 3.0, 0.5)]


def test_a_sub_threshold_derived_reading_is_marked_partial_and_still_reported():
    sections = [
        SectionRecurrenceInput("home", 0.0, {"lead": list(_MOTIF)}),
        SectionRecurrenceInput("later", 16.0, {"lead": _derived_half(_MOTIF)}),
    ]
    rep = analyze_recurrence(sections, _registry(("m", _MOTIF)), song_slug="syn")
    later = [r for r in rep.recalls if r.section == "later"]
    assert len(later) == 1
    assert later[0].variation.startswith("derived (")
    assert later[0].coverage == 0.5
    assert later[0].partial is True
    # Reported, never dropped — REC-4Z8Q. It reaches to_dict() too.
    assert rep.to_dict()["sections"][1]["recalls"][0]["partial"] is True


def test_a_partial_does_not_make_its_motif_recur():
    """The consequence that matters: a motif whose only later reading is a
    sub-threshold derived one still raises its coaching question, instead of
    reading as recurring and silencing it."""
    sections = [
        SectionRecurrenceInput("home", 0.0, {"lead": list(_MOTIF)}),
        SectionRecurrenceInput("later", 16.0, {"lead": _derived_half(_MOTIF)}),
    ]
    rep = analyze_recurrence(sections, _registry(("m", _MOTIF)), song_slug="syn")
    assert rep.economy.recurring_motifs == 0
    assert rep.economy.never_recalled == ("m",)
    assert [f.kind for f in rep.findings] == ["registered-never-recalled"]


def test_a_clean_fragment_counts_as_recall_at_any_coverage():
    """A `fragment[a,b)` is the matcher's STRUCTURED claim that the layer contains
    that named sub-window of M — the quoted answering cell, a real recall — not the
    tier-4 "most of M any op could explain". The floor must not demote it."""
    sections = [
        SectionRecurrenceInput("home", 0.0, {"lead": list(_MOTIF)}),
        SectionRecurrenceInput("answer", 16.0,
                               {"lead": [_n(60, 0.0, 0.5), _n(64, 1.0, 0.5)]}),
    ]
    rep = analyze_recurrence(sections, _registry(("m", _MOTIF)), song_slug="syn")
    answer = [r for r in rep.recalls if r.section == "answer"]
    assert len(answer) == 1
    assert answer[0].variation.startswith("fragment[")
    assert answer[0].coverage < 0.75
    assert answer[0].partial is False
    assert rep.economy.recurring_motifs == 1


def test_min_coverage_is_a_parameter_not_a_constant():
    """Lowering the floor below the reading's coverage makes it count again."""
    sections = [
        SectionRecurrenceInput("home", 0.0, {"lead": list(_MOTIF)}),
        SectionRecurrenceInput("later", 16.0, {"lead": _derived_half(_MOTIF)}),
    ]
    rep = analyze_recurrence(sections, _registry(("m", _MOTIF)), song_slug="syn",
                             min_coverage=0.25)
    later = [r for r in rep.recalls if r.section == "later"]
    assert later[0].partial is False
    assert rep.economy.recurring_motifs == 1
    assert rep.min_coverage == 0.25
    assert rep.to_dict()["min_coverage"] == 0.25


def test_report_carries_the_floor_it_applied():
    """The render names the threshold it folded at; it must read it from the
    report rather than print a number that could drift from the one used."""
    from hallucinote.recurrence.lens import DEFAULT_MIN_RECALL_COVERAGE
    rep = analyze_recurrence(
        [SectionRecurrenceInput("home", 0.0, {"lead": list(_MOTIF)})],
        _registry(("m", _MOTIF)), song_slug="syn")
    assert rep.min_coverage == DEFAULT_MIN_RECALL_COVERAGE
