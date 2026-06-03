"""tools/melody_lens.py — the read-side CLI that brings the melody lens to
`/compose-review`.

Covers the rendering (facts framed as non-verdicts, the degraded no-progression
branch, the empty-section + missing-section branches), the JSON surface, the
section filter, and the three exit codes (printed report / no-such-song /
not-wired). The on-a-real-song path runs against sun-zone-done's `melody_report()`
(DB-free), so it doubles as an end-to-end check of the convention.
"""
from __future__ import annotations

import json

import pytest

from hallucinote.melody import (
    MelodyReport,
    SectionMelody,
    SectionMelodyResult,
    analyze_melody,
)
from hallucinote.theory.model import Progression
from hallucinote.tools.melody_lens import main, render


def _n(pitch: int, start: float) -> dict:
    return {"pitch": pitch, "start_beats": start, "duration_beats": 0.5, "velocity": 80}


def _active_line() -> list[dict]:
    # a line with real range -> classification "active"
    return [_n(p, i * 0.5) for i, p in enumerate([60, 64, 67, 72, 67, 64, 60, 55])]


def _report(*, progression=None) -> MelodyReport:
    sec = SectionMelody(name="verse", length_beats=8.0,
                        layers={"lead": _active_line()}, progression=progression)
    return analyze_melody([sec], song_slug="t")


def test_render_frames_facts_as_non_verdicts_and_degrades_without_harmony():
    out = render(_report())               # no progression declared
    assert "melody lens — t" in out
    assert "NOT a verdict" in out         # the no-universal-good-melody framing
    assert "[verse]" in out
    assert "active" in out
    assert "no declared progression" in out   # graceful harmony degradation


def test_render_shows_harmony_fit_when_progression_present():
    prog = Progression.of("C", "Ionian", ["C"], beats_per_chord=8.0)
    out = render(_report(progression=prog))
    assert "chord-tone" in out
    assert "no declared progression" not in out


def test_render_section_filter_miss_is_explicit():
    out = render(_report(), section_filter="nope")
    assert "no section named 'nope'" in out


def test_render_empty_section_is_labelled():
    rep = MelodyReport(
        song_slug="t",
        sections=(SectionMelodyResult(section="verse", lines=(), findings=()),),
        findings=(),
    )
    assert "no melodic line in this section" in render(rep)


def test_main_runs_on_wired_song(capsys):
    rc = main(["sun-zone-done"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "melody lens — sun-zone-done" in out
    assert "05 Lead" in out


def test_main_json_is_valid_and_structured(capsys):
    rc = main(["sun-zone-done", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["song_slug"] == "sun-zone-done"
    assert isinstance(payload["sections"], list) and payload["sections"]


def test_main_section_filter_limits_output(capsys):
    rc = main(["sun-zone-done", "--section", "chorus1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[chorus1]" in out
    assert "[verse1]" not in out


def test_main_missing_song_exit_2(capsys):
    rc = main(["definitely-not-a-song-xyz"])
    assert rc == 2
    assert "no such song" in capsys.readouterr().err


def test_main_unwired_song_exit_3(capsys):
    # full-band-rock has a build.py but no melody_report() convention yet.
    rc = main(["full-band-rock"])
    assert rc == 3
    assert "has not wired the melody lens" in capsys.readouterr().err
