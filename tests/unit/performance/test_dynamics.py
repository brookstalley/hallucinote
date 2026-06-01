"""P3 — dynamics + articulation flatness.

The headline is the FLAT-DYNAMICS case (the documented sun-zone-done organ: many
notes at one velocity). Covers the pure dynamics/articulation functions and the
lens integration: a rhythmically-active one-velocity part flags + emits a finding;
a varied part does not; a sustained one-velocity pad flags but is NOT nagged.
"""
from __future__ import annotations

from hallucinote.performance import SectionPerf, analyze_performance
from hallucinote.performance.dynamics import (
    FLAT_DYNAMICS_MIN_NOTES,
    FLAT_VELOCITY_STDEV_MAX,
    articulation_stats,
    is_flat_dynamics,
    velocity_stats,
)


def _note(start, *, vel=80, dur=0.25):
    return {"pitch": 60, "start_beats": start, "duration_beats": dur,
            "velocity": vel, "tags": []}


def _analyze_one(layers, *, length=24.0):
    sec = SectionPerf(name="verse", length_beats=length, layers=layers)
    return analyze_performance([sec], song_slug="t").sections[0]


# ---------------------------------------------------------------------------
# velocity_stats + is_flat_dynamics
# ---------------------------------------------------------------------------


def test_velocity_stats_on_flat_and_varied_parts():
    flat = [_note(i * 0.5, vel=80) for i in range(12)]
    mean, stdev, n = velocity_stats(flat)
    assert mean == 80.0 and stdev == 0.0 and n == 12

    varied = [_note(i * 0.5, vel=v) for i, v in enumerate([60, 80, 100, 70, 90])]
    _, vstdev, _ = velocity_stats(varied)
    assert vstdev > FLAT_VELOCITY_STDEV_MAX


def test_velocity_stats_empty_part():
    assert velocity_stats([]) == (None, None, 0)


def test_is_flat_dynamics_needs_enough_notes_and_low_spread():
    assert is_flat_dynamics(0.0, FLAT_DYNAMICS_MIN_NOTES) is True
    assert is_flat_dynamics(0.0, FLAT_DYNAMICS_MIN_NOTES - 1) is False   # too few notes
    assert is_flat_dynamics(15.0, 50) is False                          # real dynamics
    assert is_flat_dynamics(None, 50) is False                          # no data


# ---------------------------------------------------------------------------
# articulation_stats — duration / inter-onset-interval
# ---------------------------------------------------------------------------


def test_legato_reads_near_one_staccato_reads_low():
    # onsets every 0.5 beat; legato durations fill the gap, staccato are short.
    legato = [(i * 0.5, 0.5) for i in range(8)]
    staccato = [(i * 0.5, 0.1) for i in range(8)]
    leg_med, _ = articulation_stats(legato)
    stac_med, _ = articulation_stats(staccato)
    assert leg_med == 1.0
    assert stac_med < 0.5


def test_articulation_none_below_two_onsets():
    assert articulation_stats([]) == (None, None)
    assert articulation_stats([(0.0, 0.25)]) == (None, None)


def test_articulation_uniform_has_zero_stdev():
    events = [(i * 0.5, 0.25) for i in range(8)]   # every note half-filling the gap
    median, stdev = articulation_stats(events)
    assert median == 0.5
    assert stdev == 0.0


# ---------------------------------------------------------------------------
# Lens integration
# ---------------------------------------------------------------------------


def test_rhythmic_one_velocity_part_flags_flat_dynamics_with_finding():
    sec = _analyze_one({"organ": [_note(i * 0.5, vel=80) for i in range(24)]})
    part = next(p for p in sec.parts if p.track_name == "organ")
    assert part.flat_dynamics is True
    assert part.velocity_stdev == 0.0
    finding = [f for f in sec.findings if f.kind == "flat-dynamics"]
    assert len(finding) == 1
    assert finding[0].severity == "info" and finding[0].track == "organ"


def test_dynamically_varied_part_is_not_flat_and_emits_no_finding():
    import random
    rng = random.Random(4)
    notes = [_note(i * 0.5, vel=int(70 + rng.uniform(-15, 15))) for i in range(24)]
    sec = _analyze_one({"keys": notes})
    part = next(p for p in sec.parts if p.track_name == "keys")
    assert part.flat_dynamics is False
    assert not any(f.kind == "flat-dynamics" for f in sec.findings)


def test_sustained_pad_flags_flat_in_data_but_too_sparse_to_nag():
    # 6 sustained whole-note chords (3 notes each) at one velocity: 18 notes (>=
    # FLAT_DYNAMICS_MIN_NOTES, so the data flag is True) but only 6 rhythmic onsets
    # (< the finding floor) — flagged in the data, no coaching finding. flat_dynamics
    # is a neutral measurement; the finding is the selective coaching surface.
    notes = []
    for i in range(6):
        for pitch in (60, 64, 67):
            notes.append(_note(i * 4.0, vel=72, dur=4.0))
            notes[-1]["pitch"] = pitch
    sec = _analyze_one({"pad": notes}, length=24.0)
    part = next(p for p in sec.parts if p.track_name == "pad")
    assert part.flat_dynamics is True            # genuinely one velocity (18 notes)
    assert part.onset_count == 6                 # but too few rhythmic events to nag
    assert not any(f.kind == "flat-dynamics" for f in sec.findings)


def test_flat_dynamics_is_independent_of_timing_classification():
    # A part can be a human groove in TIME yet flat in DYNAMICS — both reported.
    import random
    rng = random.Random(1)
    # structured (1/f-ish) timing via a smooth drift, one velocity throughout
    drift = 0.0
    notes = []
    for i in range(40):
        drift += rng.uniform(-0.01, 0.01)
        notes.append(_note(i * 0.5 + max(-0.1, min(0.1, drift)), vel=80))
    sec = _analyze_one({"part": notes}, length=24.0)
    part = sec.parts[0]
    assert part.flat_dynamics is True
    # timing is non-mechanical (real, structured deviation) — classification is
    # about TIME, flat_dynamics about VELOCITY; they are orthogonal.
    assert part.classification in ("human", "sloppy")
