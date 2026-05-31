"""P1 — the symbolic performance lens vertical slice.

The symbolic feed is EXACT (it reads authored onsets, not detected ones), so the
tests assert precise timing-deviation values, not tolerances. They cover the
contract (dataclasses + to_dict + ok/blocking), the timing-deviation core
(push/drag sign, looseness, the mechanical / has-deviation / insufficient-data
split, constant-offset = still mechanical), rhythmic-event dedup (block chord vs
spread strum), and the arrangement -> section_perf_inputs -> analyze_performance
bridge end-to-end.
"""
from __future__ import annotations

import pytest

from hallucinote.arrangement import Arrangement
from hallucinote.performance import (
    PerfFinding,
    PerformanceReport,
    SectionPerf,
    analyze_performance,
)
from hallucinote.performance.lens import (
    _CONFIDENCE_FULL_ONSETS,
    _MECHANICAL_STDEV_MAX,
    _MIN_ONSETS,
    GRID_SUBDIVISION_BEATS,
)


def _note(pitch, start, dur=0.25, vel=80):
    return {"pitch": pitch, "start_beats": start, "duration_beats": dur,
            "velocity": vel, "tags": []}


def _eighths(n, *, offset=0.0, start=0.0):
    """n eighth-note onsets (0.5-beat spacing) shifted by a constant ``offset``."""
    return [_note(60, start + offset + i * 0.5) for i in range(n)]


def _analyze_one(layers, *, name="verse", length=8.0):
    sec = SectionPerf(name=name, length_beats=length, layers=layers)
    return analyze_performance([sec], song_slug="toy")


# ---------------------------------------------------------------------------
# Timing-deviation core — the exact, symbolic measurements
# ---------------------------------------------------------------------------


def test_perfectly_quantized_part_reads_mechanical_with_zero_deviation():
    report = _analyze_one({"drums": _eighths(8)})
    part = report.sections[0].parts[0]
    assert part.onset_count == 8
    assert part.timing_mean == pytest.approx(0.0)
    assert part.timing_stdev == pytest.approx(0.0)
    assert part.classification == "mechanical"
    assert part.confidence == pytest.approx(1.0)


def test_constant_offset_is_still_mechanical_a_shifted_grid_is_not_human():
    # Every onset 0.05 beat BEHIND the grid: nonzero mean, ~zero stdev. Tightness
    # (not lateness) is the mechanical signal (performance-model §7).
    report = _analyze_one({"drums": _eighths(8, offset=0.05)})
    part = report.sections[0].parts[0]
    assert part.timing_mean == pytest.approx(0.05)   # drag (> 0 = behind)
    assert part.timing_stdev == pytest.approx(0.0)
    assert part.classification == "mechanical"


def test_push_reads_negative_mean_drag_reads_positive_mean():
    pushed = _analyze_one({"d": _eighths(8, offset=-0.05)}).sections[0].parts[0]
    dragged = _analyze_one({"d": _eighths(8, offset=0.05)}).sections[0].parts[0]
    assert pushed.timing_mean < 0      # ahead of the beat
    assert dragged.timing_mean > 0     # behind the beat


def test_loose_part_reads_has_deviation():
    # Onsets scattered well past the mechanical tightness floor.
    starts = [1.0, 1.53, 1.97, 2.55, 3.02, 3.46, 3.99]
    report = _analyze_one({"gtr": [_note(60, s) for s in starts]})
    part = report.sections[0].parts[0]
    assert part.timing_stdev > _MECHANICAL_STDEV_MAX
    assert part.classification == "has-deviation"


def test_offset_invariance_a_constant_shift_moves_mean_not_stdev():
    base = _analyze_one({"d": _eighths(8)}).sections[0].parts[0]
    shifted = _analyze_one({"d": _eighths(8, offset=0.07)}).sections[0].parts[0]
    assert shifted.timing_stdev == pytest.approx(base.timing_stdev)
    assert shifted.timing_mean != pytest.approx(base.timing_mean)


# ---------------------------------------------------------------------------
# Rhythmic-event dedup — a chord is one onset; a spread strum is not
# ---------------------------------------------------------------------------


def test_block_chord_notes_collapse_to_one_rhythmic_onset():
    # Four 3-note block chords on the grid = 4 rhythmic onsets, not 12.
    notes = []
    for i in range(4):
        for p in (60, 64, 67):
            notes.append(_note(p, i * 0.5))
    part = _analyze_one({"keys": notes}).sections[0].parts[0]
    assert part.onset_count == 4


def test_spread_strum_is_not_collapsed_its_spread_is_authored_feel():
    # Distinct (non-simultaneous) onsets stay distinct — the micro-spread IS feel.
    notes = [_note(60, 1.0), _note(64, 1.01), _note(67, 1.02),
             _note(60, 2.0), _note(64, 2.01), _note(67, 2.02)]
    part = _analyze_one({"gtr": notes}).sections[0].parts[0]
    assert part.onset_count == 6


# ---------------------------------------------------------------------------
# Sparse parts read low-trust, never confidently wrong
# ---------------------------------------------------------------------------


def test_part_below_min_onsets_reads_insufficient_data():
    notes = [_note(60, i * 1.0) for i in range(_MIN_ONSETS - 1)]
    part = _analyze_one({"pad": notes}).sections[0].parts[0]
    assert part.onset_count == _MIN_ONSETS - 1
    assert part.timing_mean is None
    assert part.timing_stdev is None
    assert part.classification == "insufficient-data"
    assert part.confidence < 1.0


# ---------------------------------------------------------------------------
# Findings — coaching questions, never verdicts (authored feel is not error)
# ---------------------------------------------------------------------------


def test_mechanical_part_emits_an_info_finding_never_blocking():
    report = _analyze_one({"hat": _eighths(_CONFIDENCE_FULL_ONSETS)})
    findings = report.sections[0].findings
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == "mechanical-timing"
    assert f.severity == "info"        # a question, not a verdict
    assert f.track == "hat"
    assert report.ok is True           # info findings never fail the song
    assert report.blocking == ()


def test_few_onset_mechanical_part_does_not_nag():
    # Tight but only a handful of onsets: no finding (too sparse to coach on).
    report = _analyze_one({"clave": _eighths(_MIN_ONSETS)})
    assert report.sections[0].findings == ()


def test_perf_finding_rejects_invalid_severity():
    with pytest.raises(ValueError):
        PerfFinding(kind="x", severity="bogus", section="s", detail="d")


# ---------------------------------------------------------------------------
# Contract — report shape + to_dict boundary
# ---------------------------------------------------------------------------


def test_report_to_dict_round_trips_structure():
    report = _analyze_one({"drums": _eighths(8), "bass": _eighths(6, offset=0.02)})
    d = report.to_dict()
    assert d["song_slug"] == "toy"
    assert len(d["sections"]) == 1
    assert {p["track_name"] for p in d["sections"][0]["parts"]} == {"drums", "bass"}
    assert all("classification" in p for p in d["sections"][0]["parts"])
    assert isinstance(d["findings"], list)


def test_empty_song_is_well_formed_and_ok():
    report = analyze_performance([], song_slug="empty")
    assert isinstance(report, PerformanceReport)
    assert report.sections == ()
    assert report.ok is True


# ---------------------------------------------------------------------------
# The vertical slice — arrangement -> section_perf_inputs -> analyze_performance
# ---------------------------------------------------------------------------


def test_arrangement_bridge_feeds_the_lens_end_to_end():
    arr = Arrangement()
    arr.section("verse", function="verse", bars=2,
                layers={"drums": _eighths(8), "bass": _eighths(8, offset=0.04)})
    arr.section("chorus", function="chorus", bars=2,
                layers={"drums": _eighths(8)})

    inputs = arr.section_perf_inputs()
    assert [s.name for s in inputs] == ["verse", "chorus"]
    assert inputs[0].length_beats == 8.0          # 2 bars * 4 beats

    report = analyze_performance(inputs, song_slug="bridge-song")
    assert [s.section for s in report.sections] == ["verse", "chorus"]
    verse = report.sections[0]
    assert {p.track_name for p in verse.parts} == {"drums", "bass"}
    assert report.ok is True


def test_grid_default_is_a_sixteenth():
    assert GRID_SUBDIVISION_BEATS == 0.25
