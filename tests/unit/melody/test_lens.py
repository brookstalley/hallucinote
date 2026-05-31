"""melody.lens — the build-time symbolic melody lens.

Covers the contract (dataclasses + to_dict + ok/blocking), the monophonic
reduction (a block-chord onset collapses to its top voice), the genre-SAFE
active/static/insufficient classification, the findings (static-line fires with
enough notes; unresolved-NCT fires only on abundant + unresolved dissonance), and
the arrangement -> section_melody_inputs -> analyze_melody bridge.

The crown jewel is the both-sides acceptance test: sun-zone-done's two real
hand-authored hooks — a stepwise/third-based E-Dorian reggae line and an angular,
upper-register E-Phrygian metal line with the ♭2 — BOTH read as valid ``active``
lines with NO findings. One lens, two very different profiles, neither graded
against the other's ideal — the proof that the lens does not impose a universal
"good melody" verdict (melody-model.md §1, §9).
"""
from __future__ import annotations

import pytest

from hallucinote.arrangement import Arrangement
from hallucinote.melody import (
    MelodicLine,
    MelodyFinding,
    MelodyReport,
    SectionMelody,
    analyze_melody,
)
from hallucinote.melody.lens import (
    _MIN_MELODIC_NOTES,
    _STATIC_AMBITUS_MAX,
    _STATIC_FINDING_MIN_NOTES,
    _melodic_sequence,
)
from hallucinote.theory.model import Progression


def _n(pitch: int, start: float, dur: float = 0.5, vel: int = 80) -> dict:
    return {"pitch": pitch, "start_beats": start, "duration_beats": dur, "velocity": vel}


# The real sun-zone-done hooks (pitch, onset) — the forcing function (§9).
def _reggae_chillin() -> list[dict]:
    cells = [(64, 0.0), (62, 1.0), (59, 1.5), (59, 2.0), (55, 2.5), (52, 3.0),
             (59, 8.0), (69, 8.5), (55, 9.0), (52, 10.0), (55, 10.5), (59, 11.0),
             (62, 11.5), (64, 12.0)]
    return [_n(p, t) for p, t in cells]


def _metal_no_time() -> list[dict]:
    cells = [(76, 0.0), (74, 1.0), (72, 2.0), (76, 3.0), (64, 4.0), (65, 4.5),
             (67, 5.0), (71, 6.0), (76, 7.0)]
    return [_n(p, t) for p, t in cells]


def _analyze_one(layers, *, progression=None, beats_per_bar=4.0) -> MelodicLine:
    sec = SectionMelody(name="s", length_beats=16.0, layers=layers,
                        progression=progression, beats_per_bar=beats_per_bar)
    return analyze_melody([sec], song_slug="t").sections[0].lines[0]


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_finding_rejects_bad_severity():
    with pytest.raises(ValueError):
        MelodyFinding(kind="x", severity="bogus", section="s", detail="d")


def test_report_ok_and_to_dict_roundtrip():
    rep = analyze_melody(
        [SectionMelody(name="v", length_beats=8.0, layers={"lead": [_n(60, 0), _n(64, 1), _n(67, 2), _n(72, 3)]})],
        song_slug="song",
    )
    assert isinstance(rep, MelodyReport)
    assert rep.ok is True and rep.blocking == ()
    d = rep.to_dict()
    assert d["song_slug"] == "song"
    assert d["sections"][0]["lines"][0]["track_name"] == "lead"
    # harmony key is present and None when no progression was declared
    assert d["sections"][0]["lines"][0]["harmony"] is None


# ---------------------------------------------------------------------------
# Monophonic reduction
# ---------------------------------------------------------------------------


def test_block_chord_onset_collapses_to_top_voice():
    # three simultaneous notes at t=0 -> the highest (the melody note) is kept
    notes = [_n(60, 0.0), _n(64, 0.0), _n(67, 0.0), _n(62, 1.0)]
    assert _melodic_sequence(notes) == [(0.0, 67), (1.0, 62)]


def test_spread_notes_stay_distinct():
    notes = [_n(60, 0.0), _n(64, 0.5), _n(67, 1.0)]
    assert _melodic_sequence(notes) == [(0.0, 60), (0.5, 64), (1.0, 67)]


# ---------------------------------------------------------------------------
# Classification (genre-safe: active / static / insufficient-data)
# ---------------------------------------------------------------------------


def test_insufficient_data_below_min_notes():
    line = _analyze_one({"lead": [_n(60, 0), _n(64, 1), _n(67, 2)]})  # 3 < 4
    assert _MIN_MELODIC_NOTES == 4
    assert line.classification == "insufficient-data"


def test_static_line_tiny_ambitus():
    line = _analyze_one({"lead": [_n(60, i * 1.0) if i % 2 == 0 else _n(61, i * 1.0)
                                  for i in range(8)]})
    assert _STATIC_AMBITUS_MAX == 2
    assert line.ambitus == 1
    assert line.classification == "static"


def test_active_line_with_real_range():
    line = _analyze_one({"lead": [_n(60, 0), _n(64, 1), _n(67, 2), _n(72, 3)]})
    assert line.classification == "active"


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def test_static_finding_fires_with_enough_notes():
    notes = [_n(60, i * 1.0) if i % 2 == 0 else _n(61, i * 1.0) for i in range(_STATIC_FINDING_MIN_NOTES)]
    rep = analyze_melody([SectionMelody(name="drone", length_beats=8.0, layers={"lead": notes})], song_slug="t")
    kinds = [f.kind for f in rep.findings]
    assert "static-line" in kinds
    assert next(f for f in rep.findings if f.kind == "static-line").metric == 1.0


def test_static_finding_silent_below_note_gate():
    # static, but only 4 notes — too few to nag
    notes = [_n(60, 0), _n(61, 1), _n(60, 2), _n(61, 3)]
    rep = analyze_melody([SectionMelody(name="drone", length_beats=4.0, layers={"lead": notes})], song_slug="t")
    assert rep.findings == ()


def test_unresolved_nct_finding_fires_on_stranded_dissonance():
    # six E-Dorian scale tones, NONE a chord tone of Em, none resolving to one
    prog = Progression.of("E", "Dorian", ["Em"], beats_per_chord=8.0)
    notes = [_n(62, 0), _n(66, 1), _n(69, 2), _n(73, 3), _n(62, 4), _n(66, 5)]
    rep = analyze_melody(
        [SectionMelody(name="v", length_beats=8.0, layers={"lead": notes}, progression=prog)],
        song_slug="t",
    )
    assert "unresolved-nct" in [f.kind for f in rep.findings]


# ---------------------------------------------------------------------------
# Crown jewel — the both-sides acceptance test on the real hooks
# ---------------------------------------------------------------------------


def test_reggae_and_metal_hooks_both_read_active_and_unflagged():
    reggae = analyze_melody(
        [SectionMelody(name="verse", length_beats=16.0, layers={"lead": _reggae_chillin()},
                       progression=Progression.of("E", "Dorian", ["Em7"], beats_per_chord=16.0))],
        song_slug="sun-zone-done",
    )
    metal = analyze_melody(
        [SectionMelody(name="chorus", length_beats=8.0, layers={"lead": _metal_no_time()},
                       progression=Progression.of("E", "Phrygian", ["Em"], beats_per_chord=8.0))],
        song_slug="sun-zone-done",
    )
    rl, ml = reggae.sections[0].lines[0], metal.sections[0].lines[0]

    # Both are valid, very different lines — both read active, neither flagged.
    assert rl.classification == "active" and ml.classification == "active"
    assert reggae.findings == () and metal.findings == ()

    # The reggae line is third-based (low step fraction) yet NOT nagged — the proof
    # that a leap-driven idiom is not judged "wrong" (no universal verdict).
    assert rl.step_fraction < 0.5
    # Its chord tones land on the strong beats (the tonal-metric coupling, §3.A1).
    assert rl.harmony.chord_tone_on_strong_beat == 1.0
    # The metal line's ♭2 color stays a minority and is not flagged.
    assert ml.harmony.non_chord_tone_fraction < 0.4


# ---------------------------------------------------------------------------
# The bridge — arrangement -> section_melody_inputs -> analyze_melody
# ---------------------------------------------------------------------------


def test_arrangement_bridge_feeds_the_lens_end_to_end():
    prog = Progression.of("E", "Dorian", ["Em7"], beats_per_chord=16.0)
    arr = Arrangement()
    arr.section("verse", function="verse", bars=4,
                layers={"lead": _reggae_chillin(), "drums": [_n(36, i * 1.0) for i in range(8)]},
                progression=prog)

    inputs = arr.section_melody_inputs(melody_layers=["lead"])
    assert [s.name for s in inputs] == ["verse"]
    assert inputs[0].length_beats == 16.0           # 4 bars * 4 beats
    assert inputs[0].beats_per_bar == 4.0
    assert inputs[0].progression is prog            # melody's pitch reads harmony

    rep = analyze_melody(inputs, song_slug="bridge-song")
    line = rep.sections[0].lines[0]
    assert line.track_name == "lead"                # drums excluded by melody_layers
    assert line.classification == "active"
    assert line.harmony is not None                 # harmony-fit ran (progression present)
    assert rep.ok is True
