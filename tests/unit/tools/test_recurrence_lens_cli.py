"""tools/recurrence_lens.py — the read-side CLI for the recurrence lens.

Focused on the MICROTUNE Chunk 3 gated tuning caveat (recurrence variations are
read in 12-TET semitones), plus a smoke that the build.py-loading + exit-code
contract still holds. The lens engine itself is covered by
``tests/unit/recurrence/test_lens.py``; this file pins the new CLI surface.
"""
from __future__ import annotations

import json
import textwrap

import pytest

from hallucinote.tools.recurrence_lens import main


@pytest.fixture
def synth_songs(tmp_path, monkeypatch):
    """A synthetic songs workspace whose `synth-rec` build.py wires
    `recurrence_report()` via the lightweight `analyze_recurrence` path (no full
    Arrangement needed)."""
    root = tmp_path / "songs"
    wired = root / "synth-rec"
    wired.mkdir(parents=True)
    (wired / "build.py").write_text(textwrap.dedent('''
        from hallucinote.recurrence.lens import (
            SectionRecurrenceInput, analyze_recurrence,
        )

        def _n(p, s):
            return {"pitch": p, "start_beats": s, "duration_beats": 0.5,
                    "velocity": 80, "tags": []}

        _MOTIF = [_n(60, 0.0), _n(64, 1.0), _n(67, 2.0)]

        class _M:
            def __init__(self, name, notes):
                self.name, self.notes = name, notes

        def recurrence_report():
            secs = [
                SectionRecurrenceInput("home", 8.0, {"lead": list(_MOTIF)}),
                SectionRecurrenceInput("recap", 8.0, {"lead": list(_MOTIF)}),
            ]
            return analyze_recurrence(secs, {"m": _M("m", _MOTIF)},
                                      song_slug="synth-rec")
    '''))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("HALLUCINOTE_SONGS_ROOT", str(root))
    return root


def _set_song_tuning_db(songs_root, slug: str) -> None:
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


def test_main_runs_on_wired_song(capsys, synth_songs):
    rc = main(["synth-rec"])
    assert rc == 0
    assert "recurrence lens — synth-rec" in capsys.readouterr().out


def test_main_emits_tuning_caveat_for_alt_tuned_song(capsys, synth_songs):
    _set_song_tuning_db(synth_songs, "synth-rec")
    rc = main(["synth-rec"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "12-TET-relative" in out and "tunings/19-edo.ascl" in out


def test_main_no_caveat_for_12tet_song(capsys, synth_songs):
    rc = main(["synth-rec"])
    assert rc == 0
    assert "12-TET-relative" not in capsys.readouterr().out


def test_main_json_carries_tuning_caveat_field(capsys, synth_songs):
    _set_song_tuning_db(synth_songs, "synth-rec")
    rc = main(["synth-rec", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "tuning_caveat" in payload and "19-edo" in payload["tuning_caveat"]


@pytest.fixture
def partial_heavy_songs(tmp_path, monkeypatch):
    """A synthetic song whose later section yields a SUB-THRESHOLD DERIVED reading
    (half of the motif's notes recoverable under a transpose, no clean op) — the
    shape that, unfolded, outnumbers the real recalls in the render."""
    root = tmp_path / "songs"
    song = root / "synth-partial"
    song.mkdir(parents=True)
    (song / "build.py").write_text(textwrap.dedent('''
        from hallucinote.recurrence.lens import (
            SectionRecurrenceInput, analyze_recurrence,
        )

        def _n(p, s):
            return {"pitch": p, "start_beats": s, "duration_beats": 0.5,
                    "velocity": 80, "tags": []}

        _MOTIF = [_n(60, 0.0), _n(64, 1.0), _n(67, 2.0), _n(72, 3.0)]
        _HALF = [_n(65, 0.0), _n(69, 1.0), _n(70, 2.0), _n(71, 3.0)]

        class _M:
            def __init__(self, name, notes):
                self.name, self.notes = name, notes

        def recurrence_report():
            secs = [
                SectionRecurrenceInput("home", 0.0, {"lead": list(_MOTIF)}),
                SectionRecurrenceInput("recap", 16.0, {"lead": list(_MOTIF)}),
                SectionRecurrenceInput("haze", 32.0, {"lead": list(_HALF)}),
            ]
            return analyze_recurrence(secs, {"m": _M("m", _MOTIF)},
                                      song_slug="synth-partial")
    '''))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("HALLUCINOTE_SONGS_ROOT", str(root))
    return root


def test_partials_are_folded_into_a_count_by_default(capsys, partial_heavy_songs):
    rc = main(["synth-partial"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 partial(s) folded" in out
    assert "--all to list" in out
    # The threshold is NAMED, and read from the report rather than hardcoded here.
    assert "below 75% coverage" in out
    # The folded reading's own line is not printed.
    assert "derived (transpose +5" not in out
    # ...while the real recall still is.
    assert "recurs on lead as exact" in out


def test_all_expands_the_folded_partials(capsys, partial_heavy_songs):
    rc = main(["synth-partial", "--all"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "derived (transpose +5" in out
    assert "folded" not in out
    assert "1 partial(s) listed" in out


def test_json_always_carries_every_partial(capsys, partial_heavy_songs):
    """What the render filters is the READING; --json stays complete."""
    rc = main(["synth-partial", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    haze = [s for s in payload["sections"] if s["section"] == "haze"][0]
    assert len(haze["recalls"]) == 1
    assert haze["recalls"][0]["partial"] is True
    assert payload["min_coverage"] == 0.75


def test_unwired_song_hint_carries_both_authoring_shapes(capsys, tmp_path,
                                                         monkeypatch):
    """The old hint named one song that defines no recurrence_report() and one
    entry point a DB-authored song cannot use. Both shapes belong in the message,
    not behind a pointer to a workspace this package does not ship."""
    root = tmp_path / "songs"
    (root / "bare").mkdir(parents=True)
    (root / "bare" / "build.py").write_text("def melody_report():\n    return None\n")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("HALLUCINOTE_SONGS_ROOT", str(root))

    rc = main(["bare"])
    assert rc == 3
    err = capsys.readouterr().err
    assert "defines no recurrence_report()" in err
    assert "analyze_arrangement" in err
    assert "analyze_recurrence" in err
    assert "SectionRecurrenceInput" in err
    assert "sun-zone-done" not in err
