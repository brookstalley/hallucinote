"""DOC-4F8M — the song overview drifting from the form it describes.

`<slug>.md`'s Structure table is rendered once at scaffold time and
hand-maintained after, so it rots to the scaffold defaults while the real form
grows. Observed on `alien`: the overview still claimed "8x8-bar sections /
composes Intro + Verse 1 only" long after the form had tripled.

Decided: WARN, never regenerate. The table's Feel column is the composer's, so
generating it would clobber real work to fix a bookkeeping problem.
"""
from __future__ import annotations


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


# --- the build.py docstring layout, the OTHER derived surface ----------------


from hallucinote.tools.overview_drift import parse_docstring_layout  # noqa: E402


def _build_py(*layout_lines: str) -> str:
    return (
        '"""Build A Song into a SQLite DB.\n\n'
        "Section bar layout (1-based, 4/4 throughout — adjust if non-4/4):\n"
        + "".join(layout_lines)
        + "\nRun:\n    python build.py\n"
        '"""\n'
        "from hallucinote.db import init_db\n"
        "\n"
        "def melody_report():\n"
        '    """Not the form: bars 99-200 here must not be read as a section."""\n'
    )


def test_parses_the_scaffold_docstring_layout():
    src = _build_py(
        "    Intro        bars  1-8    (8 bars)\n",
        "    Verse 1      bars  9-16   (8 bars)\n",
    )
    assert parse_docstring_layout(src) == {"Intro": 1, "Verse 1": 9}


def test_only_the_module_docstring_is_read():
    """A layout-shaped line in a function docstring further down is not form."""
    src = _build_py("    Intro        bars  1-8    (8 bars)\n")
    assert parse_docstring_layout(src) == {"Intro": 1}


def test_a_build_py_with_no_layout_block_parses_to_nothing():
    assert parse_docstring_layout('"""Just prose."""\nimport os\n') == {}


def test_docstring_layout_drifts_independently_of_the_markdown_table(song, tmp_path):
    """The two surfaces rot separately — the `alien` case had BOTH stale, but
    fixing one must not mask the other."""
    conn, song_id = song
    for name, start, end in [("Intro", 1, 8), ("Verse 1", 9, 16), ("Chorus", 17, 24)]:
        _section(conn, song_id, name, start, end)

    # Markdown is current; the docstring still shows the scaffold's two sections.
    md = tmp_path / "a-song.md"
    md.write_text(_overview(
        "| `Intro` | 1–8 | x |\n",
        "| `Verse 1` | 9–16 | x |\n",
        "| `Chorus` | 17–24 | x |\n",
    ))
    build_py = tmp_path / "build.py"
    build_py.write_text(_build_py(
        "    Intro        bars  1-8    (8 bars)\n",
        "    Verse 1      bars  9-16   (8 bars)\n",
    ))

    from hallucinote.tools.overview_drift import detect_form_drift

    report = detect_form_drift(
        conn, song_id=song_id, overview_path=md, build_py_path=build_py,
    )
    assert not report.overview, "the markdown table is current"
    assert report.docstring, "the docstring is missing Chorus"
    assert report.docstring.missing == ("Chorus",)
    assert "build.py" in report.describe(slug="a-song")


def test_form_drift_is_falsey_when_both_surfaces_match(song, tmp_path):
    conn, song_id = song
    _section(conn, song_id, "Intro", 1, 8)
    md = tmp_path / "a-song.md"
    md.write_text(_overview("| `Intro` | 1–8 | x |\n"))
    build_py = tmp_path / "build.py"
    build_py.write_text(_build_py("    Intro        bars  1-8    (8 bars)\n"))

    from hallucinote.tools.overview_drift import detect_form_drift

    assert not detect_form_drift(
        conn, song_id=song_id, overview_path=md, build_py_path=build_py,
    )


# --- warn_on_form_drift: the wiring, where the failure actually lives --------


def test_warn_on_form_drift_reports_a_drifted_song(song, tmp_path, capsys):
    """The build-close hook is the ONLY thing that fires this check for a
    scaffolded song, so it needs its own coverage — the detector being right
    doesn't help if the wiring never reports."""
    conn, song_id = song
    for name, start, end in [("Intro", 1, 8), ("Verse", 9, 16), ("Chorus", 17, 24)]:
        _section(conn, song_id, name, start, end)
    (tmp_path / "a-song.md").write_text(_overview("| `Intro` | 1–8 | x |\n"))
    (tmp_path / "build.py").write_text(
        _build_py("    Intro        bars  1-8    (8 bars)\n")
    )

    from hallucinote.tools.overview_drift import warn_on_form_drift

    reported = warn_on_form_drift(
        conn, song_id=song_id, slug="a-song", song_dir=tmp_path,
    )
    assert reported is True
    err = capsys.readouterr().err
    assert "Chorus" in err
    assert "build.py" in err, "both surfaces drifted; both must be named"


def test_warn_on_form_drift_is_silent_when_the_surfaces_match(song, tmp_path, capsys):
    conn, song_id = song
    _section(conn, song_id, "Intro", 1, 8)
    (tmp_path / "a-song.md").write_text(_overview("| `Intro` | 1–8 | x |\n"))
    (tmp_path / "build.py").write_text(
        _build_py("    Intro        bars  1-8    (8 bars)\n")
    )

    from hallucinote.tools.overview_drift import warn_on_form_drift

    assert warn_on_form_drift(
        conn, song_id=song_id, slug="a-song", song_dir=tmp_path,
    ) is False
    assert capsys.readouterr().err == ""


def test_warn_on_form_drift_swallows_failures_deliberately(song, tmp_path, monkeypatch):
    """The swallow is intentional — a bookkeeping check must not be able to fail
    the build that ran it — so it is pinned rather than left to be read as an
    accident. The cost is that a dependency drift turns the check into a silent
    no-op, which is exactly why the two tests above exist to catch that."""
    conn, song_id = song
    _section(conn, song_id, "Intro", 1, 8)

    import hallucinote.tools.overview_drift as od

    def _boom(*a, **k):
        raise RuntimeError("schema moved under us")

    monkeypatch.setattr(od, "detect_form_drift", _boom)
    assert od.warn_on_form_drift(
        conn, song_id=song_id, slug="a-song", song_dir=tmp_path,
    ) is False


def test_the_parser_reads_what_the_scaffold_renderer_writes(song, tmp_path):
    """The parser and `scaffold_song`'s renderers agree by COMMENT today. Pin it:
    render both surfaces from the same section list the scaffold would use, and
    assert the parsers read them back as the form. A renderer format change now
    fails here instead of silently turning the check into a no-op."""
    from hallucinote.tools.scaffold_song import (
        ScaffoldRequest, section_layout, section_table,
    )

    req = ScaffoldRequest(
        slug="a-song", title="A Song", tempo=120.0, numerator=4, denominator=4,
        sections=("Intro", "Verse", "Chorus"), section_length_bars=8,
    )
    assert parse_structure_table(
        f"## Structure\n\n{section_table(req)}\n"
    ) == {"Intro": 1, "Verse": 9, "Chorus": 17}
    assert parse_docstring_layout(
        f'"""Doc.\n\nSection bar layout (1-based):\n{section_layout(req)}\n\nRun:\n"""\nimport os\n'
    ) == {"Intro": 1, "Verse": 9, "Chorus": 17}


# --- main(): the on-demand path, and the ONLY one older songs have -----------


@pytest.fixture
def cli_song(tmp_path, monkeypatch):
    """A song dir + DB that `main()` can resolve, with sections seeded."""
    from hallucinote.db import init_db as _init

    song_dir = tmp_path / "a-song"
    song_dir.mkdir()
    db = song_dir / "a-song.db"
    conn = _init(db)
    song_id = M.create_song(conn, name="a-song", title="A Song")
    for name, start, end in [("Intro", 1, 8), ("Verse", 9, 16), ("Chorus", 17, 24)]:
        M.create_section(
            conn, song_id=song_id, name=name, start_bar=start, end_bar=end,
        )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "hallucinote.db.connection.resolve_db_path", lambda slug, **_: db,
    )
    monkeypatch.setattr(
        "hallucinote.workspace.resolve_song_dir", lambda slug, **_: song_dir,
    )
    return song_dir


def test_main_exits_1_and_names_both_drifted_surfaces(cli_song, capsys):
    """`main()` is the only drift check a song scaffolded before 2026-08-11 has,
    so a revert to the markdown-only detector, a wrong build_py_path, or an
    inverted no-op guard must not ship green."""
    from hallucinote.tools.overview_drift import main

    (cli_song / "a-song.md").write_text(_overview("| `Intro` | 1–8 | x |\n"))
    (cli_song / "build.py").write_text(
        _build_py("    Intro        bars  1-8    (8 bars)\n")
    )

    assert main(["a-song"]) == 1
    err = capsys.readouterr().err
    assert "Chorus" in err
    assert "Structure table" in err, "the markdown surface must be named"
    # "build.py" alone would pass on the overview half — OverviewDrift.describe
    # already emits that string. FormDrift rewrites the docstring half's opener,
    # so assert on THAT to actually check the second surface was reported.
    assert "build.py's docstring section layout" in err, (
        "the docstring surface must be named too"
    )


def test_main_exits_0_when_both_surfaces_match(cli_song, capsys):
    from hallucinote.tools.overview_drift import main

    rows = "".join(
        f"| `{n}` | {s}–{e} | x |\n"
        for n, s, e in [("Intro", 1, 8), ("Verse", 9, 16), ("Chorus", 17, 24)]
    )
    (cli_song / "a-song.md").write_text(_overview(rows))
    (cli_song / "build.py").write_text(_build_py(
        "    Intro        bars  1-8    (8 bars)\n",
        "    Verse        bars  9-16   (8 bars)\n",
        "    Chorus       bars 17-24   (8 bars)\n",
    ))

    assert main(["a-song"]) == 0
    assert "match the form" in capsys.readouterr().err


def test_main_still_checks_the_docstring_when_the_overview_is_absent(cli_song, capsys):
    """One surface missing must not read as "nothing to compare" — the other is
    still checkable, and for an older song it may be the only one that exists."""
    from hallucinote.tools.overview_drift import main

    (cli_song / "build.py").write_text(
        _build_py("    Intro        bars  1-8    (8 bars)\n")
    )

    assert main(["a-song"]) == 1
    err = capsys.readouterr().err
    assert "Chorus" in err and "build.py" in err


def test_main_reports_nothing_to_compare_when_neither_surface_parses(cli_song, capsys):
    from hallucinote.tools.overview_drift import main

    (cli_song / "a-song.md").write_text("# A Song\n\n## Structure\n\n_TODO_\n")
    (cli_song / "build.py").write_text('"""Just prose."""\nimport os\n')

    assert main(["a-song"]) == 0
    assert "nothing to compare" in capsys.readouterr().err


def test_main_names_only_the_surface_it_actually_compared(cli_song, capsys):
    """With no build.py, the success message must not claim the docstring
    matched — that comparison never ran."""
    from hallucinote.tools.overview_drift import main

    rows = "".join(
        f"| `{n}` | {s}–{e} | x |\n"
        for n, s, e in [("Intro", 1, 8), ("Verse", 9, 16), ("Chorus", 17, 24)]
    )
    (cli_song / "a-song.md").write_text(_overview(rows))

    assert main(["a-song"]) == 0
    err = capsys.readouterr().err
    assert "a-song.md matches the form" in err
    assert "build.py" not in err


def test_main_opens_the_song_db_through_init_db(cli_song, monkeypatch, capsys):
    """`main()` opens the song DB through `init_db`, never a bare `connect`.

    The ratified Direction (`data-model.md`): the additive-column migration
    runs ONLY inside `init_db`, so a bare open reads whatever schema the DB was
    last written with and the first lookup of a later-added column raises
    `sqlite3.Row`'s `IndexError: No item with that key`. This CLI is the only
    drift check a song scaffolded before 2026-08-11 has, i.e. exactly the
    population with the oldest DBs.

    Pinned as a routing contract rather than a reproduced crash, deliberately:
    today's `_ADDED_COLUMNS` touches `requests` and `devices`, not `songs` or
    `sections`, so no current column lift makes this path raise. The next one
    that touches either table would — and by then nothing would be watching.
    The assertion is what the rule actually says.
    """
    from hallucinote.db import connection as _conn
    from hallucinote.tools.overview_drift import main

    calls: list[str] = []
    real_init = _conn.init_db
    monkeypatch.setattr(
        _conn, "init_db",
        lambda path, *a, **k: (calls.append("init_db"), real_init(path, *a, **k))[1],
    )

    rows = "".join(
        f"| `{n}` | {s}–{e} | x |\n"
        for n, s, e in [("Intro", 1, 8), ("Verse", 9, 16), ("Chorus", 17, 24)]
    )
    (cli_song / "a-song.md").write_text(_overview(rows))

    assert main(["a-song"]) == 0
    assert calls == ["init_db"], (
        "the song DB must be opened exactly once, through init_db — an empty "
        "list means the CLI went back to a bare connect()"
    )
    assert "a-song.md matches the form" in capsys.readouterr().err
