"""DOC-4F8M — the song overview drifting from the form it describes.

`<slug>.md`'s Structure table is rendered once at scaffold time and
hand-maintained after, so it rots to the scaffold defaults while the real form
grows. Observed on `alien`: the overview still claimed "8x8-bar sections /
composes Intro + Verse 1 only" long after the form had tripled.

Decided: WARN, never regenerate. The table's Feel column is the composer's, so
generating it would clobber real work to fix a bookkeeping problem.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.tools.overview_drift import (
    detect_overview_drift,
    parse_structure_table,
)


def _overview(*rows: str) -> str:
    head = "# A Song\n\n## Concept\n\nsomething\n\n## Structure\n\n"
    table = "| Section | Bars | Feel |\n|---------|------|------|\n"
    return head + table + "".join(rows) + "\n## Build\n\nstuff\n"


@pytest.fixture
def song(tmp_path):
    conn = init_db(tmp_path / "s.db")
    song_id = M.create_song(conn, name="a-song", title="A Song")
    return conn, song_id


def _section(conn, song_id, name, start, end):
    M.create_section(
        conn, song_id=song_id, name=name, start_bar=start, end_bar=end,
    )


# --- the parser --------------------------------------------------------------


def test_parses_the_scaffold_table_shape():
    md = _overview(
        "| `Intro` | 1–8 | sparse |\n",
        "| `Verse 1` | 9–16 | _TODO: fill in_ |\n",
    )
    assert parse_structure_table(md) == {"Intro": 1, "Verse 1": 9}


def test_accepts_a_hand_typed_hyphen_as_well_as_the_scaffold_en_dash():
    """The scaffold writes an en-dash; a human editing the table types a
    hyphen. A hyphen must not read as drift."""
    md = _overview("| `Intro` | 1-8 | sparse |\n")
    assert parse_structure_table(md) == {"Intro": 1}


def test_a_table_outside_the_structure_section_is_not_the_form():
    """An arrangement sketch or device table elsewhere in the overview must not
    be mistaken for the structure table."""
    md = _overview("| `Intro` | 1–8 | sparse |\n")
    md += "\n## Devices\n\n| Track | Bars | Note |\n|--|--|--|\n| `Drums` | 99–200 | x |\n"
    assert parse_structure_table(md) == {"Intro": 1}


def test_no_structure_section_parses_to_nothing():
    assert parse_structure_table("# A Song\n\njust prose\n") == {}


# --- the comparison ----------------------------------------------------------


def test_matching_overview_reports_no_drift(song, tmp_path):
    conn, song_id = song
    _section(conn, song_id, "Intro", 1, 8)
    _section(conn, song_id, "Verse 1", 9, 16)
    path = tmp_path / "a-song.md"
    path.write_text(_overview(
        "| `Intro` | 1–8 | sparse |\n",
        "| `Verse 1` | 9–16 | driving |\n",
    ))

    drift = detect_overview_drift(conn, song_id=song_id, overview_path=path)
    assert drift is not None
    assert not drift


def test_sections_composed_after_the_overview_are_reported_missing(song, tmp_path):
    """The `alien` case: the form tripled, the table didn't."""
    conn, song_id = song
    for name, start, end in [
        ("Intro", 1, 8), ("Verse 1", 9, 16), ("Chorus", 17, 24), ("Bridge", 25, 32),
    ]:
        _section(conn, song_id, name, start, end)
    path = tmp_path / "a-song.md"
    path.write_text(_overview("| `Intro` | 1–8 | sparse |\n"))

    drift = detect_overview_drift(conn, song_id=song_id, overview_path=path)
    assert drift
    assert set(drift.missing) == {"Verse 1", "Chorus", "Bridge"}
    assert drift.extra == ()
    report = drift.describe(slug="a-song")
    assert "Chorus" in report
    assert "nothing rewrites it for you" in report


def test_a_dropped_or_renamed_section_is_reported_extra(song, tmp_path):
    conn, song_id = song
    _section(conn, song_id, "Intro", 1, 8)
    path = tmp_path / "a-song.md"
    path.write_text(_overview(
        "| `Intro` | 1–8 | sparse |\n",
        "| `Outro` | 9–16 | gone |\n",
    ))

    drift = detect_overview_drift(conn, song_id=song_id, overview_path=path)
    assert drift
    assert drift.extra == ("Outro",)


def test_a_moved_section_reports_both_bars(song, tmp_path):
    conn, song_id = song
    _section(conn, song_id, "Chorus", 17, 24)
    path = tmp_path / "a-song.md"
    path.write_text(_overview("| `Chorus` | 9–16 | lifts |\n"))

    drift = detect_overview_drift(conn, song_id=song_id, overview_path=path)
    assert drift
    assert drift.moved == (("Chorus", 9, 17.0),)
    assert "table says bar 9" in drift.describe(slug="a-song")
    assert "song says 17" in drift.describe(slug="a-song")


def test_a_fractional_start_bar_is_not_truncated_into_a_false_match(song, tmp_path):
    """`sections.start_bar` is REAL. Truncating to int would make a section at
    bar 1.5 silently agree with a table row saying 1."""
    conn, song_id = song
    _section(conn, song_id, "Intro", 1.5, 8)
    path = tmp_path / "a-song.md"
    path.write_text(_overview("| `Intro` | 1–8 | sparse |\n"))

    drift = detect_overview_drift(conn, song_id=song_id, overview_path=path)
    assert drift
    assert drift.moved == (("Intro", 1, 1.5),)


# --- "nothing to say" is not drift -------------------------------------------


def test_a_missing_overview_file_says_nothing(song, tmp_path):
    conn, song_id = song
    _section(conn, song_id, "Intro", 1, 8)
    assert detect_overview_drift(
        conn, song_id=song_id, overview_path=tmp_path / "absent.md",
    ) is None


def test_a_freshly_scaffolded_song_with_no_rows_yet_is_not_drifted(song, tmp_path):
    conn, song_id = song
    _section(conn, song_id, "Intro", 1, 8)
    path = tmp_path / "a-song.md"
    path.write_text("# A Song\n\n## Structure\n\n_TODO_\n")
    assert detect_overview_drift(
        conn, song_id=song_id, overview_path=path,
    ) is None


def test_a_song_with_no_sections_yet_is_not_drifted(song, tmp_path):
    conn, song_id = song
    path = tmp_path / "a-song.md"
    path.write_text(_overview("| `Intro` | 1–8 | sparse |\n"))
    assert detect_overview_drift(
        conn, song_id=song_id, overview_path=path,
    ) is None
