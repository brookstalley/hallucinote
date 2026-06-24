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
