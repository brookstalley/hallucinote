"""tools/melody_lens.py — the read-side CLI that brings the melody lens to
`/compose-review`.

Covers the rendering (facts framed as non-verdicts, the degraded no-progression
branch, the empty-section + missing-section branches), the JSON surface, the
section filter, and the three exit codes (printed report / no-such-song /
not-wired). The on-a-real-song path runs against a synthetic in-tmp song (songs live in
their own repo now), exercising the build.py-loading + melody_report convention.
"""
from __future__ import annotations

import json
import textwrap

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


def test_render_shows_profile_name_and_relative_finding():
    """Phase 2b: when a line declares a MelodicProfile, render() shows the profile
    tag on the line + the profile-relative coaching question."""
    from hallucinote.melody import MelodicProfile

    prog = Progression.of("C", "Ionian", ["C"], beats_per_chord=16.0)
    # an NCT-heavy line declared chord-tone-locked -> harmonic-freedom-mismatch
    nct = [_n(p, i * 0.5) for i, p in enumerate([60, 61, 63, 66, 69, 70, 71, 66, 63, 61])]
    sec = SectionMelody(
        name="verse", length_beats=8.0, layers={"05 Lead": nct}, progression=prog,
        profiles={"05 Lead": MelodicProfile(name="locked", harmonic_freedom="low")},
    )
    out = render(analyze_melody([sec], song_slug="t"))
    assert "profile 'locked'" in out
    assert "harmonic_freedom=low" in out   # the profile-relative coaching question


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


@pytest.fixture
def synth_songs(tmp_path, monkeypatch):
    """A synthetic songs workspace so the CLI's build.py-loading path is tested
    without depending on a real committed song (songs live in their own repo now).
    Resolved via the project-root contract's HALLUCINOTE_SONGS_ROOT.

    - `synth-wired`:   build.py defines `melody_report()` (sections verse1+chorus1,
      each with a `05 Lead` layer).
    - `synth-unwired`: build.py exists but defines no `melody_report()` (exit-3 case).
    """
    root = tmp_path / "songs"
    wired = root / "synth-wired"
    wired.mkdir(parents=True)
    (wired / "build.py").write_text(textwrap.dedent('''
        from hallucinote.melody import SectionMelody, analyze_melody

        def _line():
            return [{"pitch": p, "start_beats": i * 0.5, "duration_beats": 0.5,
                     "velocity": 80}
                    for i, p in enumerate([60, 64, 67, 72, 67, 64, 60, 55])]

        def melody_report():
            secs = [
                SectionMelody(name="verse1", length_beats=8.0,
                              layers={"05 Lead": _line()}, progression=None),
                SectionMelody(name="chorus1", length_beats=8.0,
                              layers={"05 Lead": _line()}, progression=None),
            ]
            return analyze_melody(secs, song_slug="synth-wired")
    '''))
    unwired = root / "synth-unwired"
    unwired.mkdir(parents=True)
    (unwired / "build.py").write_text("# build.py with no melody_report() yet\nX = 1\n")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("HALLUCINOTE_SONGS_ROOT", str(root))
    return root


def test_main_runs_on_wired_song(capsys, synth_songs):
    rc = main(["synth-wired"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "melody lens — synth-wired" in out
    assert "05 Lead" in out


def test_main_json_is_valid_and_structured(capsys, synth_songs):
    rc = main(["synth-wired", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["song_slug"] == "synth-wired"
    assert isinstance(payload["sections"], list) and payload["sections"]


def test_main_section_filter_limits_output(capsys, synth_songs):
    rc = main(["synth-wired", "--section", "chorus1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[chorus1]" in out
    assert "[verse1]" not in out


def test_main_missing_song_exit_2(capsys, synth_songs):
    rc = main(["definitely-not-a-song-xyz"])
    assert rc == 2
    assert "no such song" in capsys.readouterr().err


def test_main_unwired_song_exit_3(capsys, synth_songs):
    # synth-unwired has a build.py but no melody_report() convention.
    rc = main(["synth-unwired"])
    assert rc == 3
    assert "has not wired the melody lens" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# MICROTUNE Chunk 3: the gated non-12-tuning caveat
# ---------------------------------------------------------------------------
def _set_song_tuning_db(songs_root, slug: str) -> None:
    """Give the synth song a DB (named slug) carrying a tuning_ref, so the
    lens's caveat lookup fires. Legacy bare-DB name (tmp isn't a git repo)."""
    from hallucinote.db import init_db, mutations as M
    from hallucinote.tuning.model import TuningData

    conn = init_db(songs_root / slug / f"{slug}.db")
    try:
        sid = M.create_song(conn, name=slug, key="C")
        tuning = TuningData(
            name="19-EDO", step_count=19, period_cents=1200.0, reference_note=60,
            step_cents=tuple(round(1200.0 * i / 19, 6) for i in range(1, 20)),
        )
        M.set_song_tuning(
            conn, song_id=sid,
            tuning_ref="tunings/19-edo.ascl", tuning_data=tuning.to_blob(),
        )
    finally:
        conn.close()


def test_main_emits_tuning_caveat_for_alt_tuned_song(capsys, synth_songs):
    _set_song_tuning_db(synth_songs, "synth-wired")
    rc = main(["synth-wired"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "12-TET-relative" in out
    assert "tunings/19-edo.ascl" in out


def test_main_no_caveat_for_12tet_song(capsys, synth_songs):
    # synth-wired has no DB at all -> resolver returns None -> no caveat.
    rc = main(["synth-wired"])
    assert rc == 0
    assert "12-TET-relative" not in capsys.readouterr().out


def test_main_json_carries_tuning_caveat_field(capsys, synth_songs):
    _set_song_tuning_db(synth_songs, "synth-wired")
    rc = main(["synth-wired", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "tuning_caveat" in payload
    assert "tunings/19-edo.ascl" in payload["tuning_caveat"]
