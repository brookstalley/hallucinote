"""W9-A: tests for `tools.scaffold_song`.

The scaffold tool is the testable core; the `/song-new` skill is just an
interactive wrapper. Covers: slug validation, signature parsing, section
parsing, template rendering, atomic write + rollback, refusal cases,
generated file shape (build.py imports + runs the converger on the
synthetic snapshot).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from hallucinote.tools.scaffold_song import (
    ScaffoldRequest,
    parse_sections,
    parse_signature,
    render_template,
    scaffold_song,
    section_constants,
    slug_to_python,
    validate_slug,
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug", [
    "punk-fate", "solo-piano", "x", "a1", "a_b_c", "song-2026",
])
def test_validate_slug_accepts_valid_slugs(slug):
    validate_slug(slug)  # no raise


@pytest.mark.parametrize("slug", [
    "Punk-Fate",        # uppercase
    "with space",        # space
    "song.dot",          # dot
    "-leading-hyphen",   # leading hyphen
    "_leading_under",    # leading underscore
    "song!",             # special char
    "",                  # empty
    "song/path",         # slash
])
def test_validate_slug_rejects_bad_slugs(slug):
    with pytest.raises(ValueError, match="invalid slug"):
        validate_slug(slug)


def test_parse_signature_standard():
    assert parse_signature("4/4") == (4, 4)
    assert parse_signature("7/8") == (7, 8)
    assert parse_signature("12/16") == (12, 16)


def test_parse_signature_strips_whitespace():
    assert parse_signature("  4/4  ") == (4, 4)


@pytest.mark.parametrize("sig", ["4", "4-4", "4/", "/4", "0/4", "4/0", "abc/4"])
def test_parse_signature_rejects_bad(sig):
    with pytest.raises(ValueError):
        parse_signature(sig)


def test_parse_sections_strips_whitespace():
    assert parse_sections("intro, verse, chorus") == ["intro", "verse", "chorus"]


def test_parse_sections_drops_empty():
    assert parse_sections("intro,,verse,") == ["intro", "verse"]


def test_parse_sections_rejects_empty_list():
    with pytest.raises(ValueError, match="empty"):
        parse_sections(",,,")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _basic_req(**overrides) -> ScaffoldRequest:
    base = {
        "slug": "test-song",
        "title": "Test Song",
        "tempo": 120.0,
        "numerator": 4,
        "denominator": 4,
        "sections": ("intro", "verse", "chorus", "outro"),
    }
    base.update(overrides)
    return ScaffoldRequest(**base)


def test_section_constants_renders_in_order():
    req = _basic_req()
    out = section_constants(req)
    assert "INTRO_BAR = 1" in out
    assert "VERSE_BAR = 9" in out
    assert "CHORUS_BAR = 17" in out
    assert "OUTRO_BAR = 25" in out
    assert "END_BAR = 33" in out


def test_section_constants_slugified_section_names():
    """`chorus_twist` should produce CHORUS_TWIST_BAR (snake_case → SNAKE_CASE)."""
    req = _basic_req(sections=("intro", "chorus_twist"))
    out = section_constants(req)
    assert "INTRO_BAR = 1" in out
    assert "CHORUS_TWIST_BAR = 9" in out


def test_render_template_substitutes_placeholders():
    req = _basic_req(slug="my-song", title="My Song", tempo=132.0)
    template = "Building {{title}} (slug={{slug}}) at {{tempo}} BPM."
    assert render_template(template, req) == "Building My Song (slug=my-song) at 132.0 BPM."


def test_render_template_handles_key_none():
    req = _basic_req(key=None)
    template = "key={{key_literal}} display={{key_display}}"
    out = render_template(template, req)
    assert out == "key=None display=_unset_"


def test_render_template_handles_key_set():
    req = _basic_req(key="Dm")
    template = "key={{key_literal}} display={{key_display}}"
    assert render_template(template, req) == "key='Dm' display=Dm"


def test_slug_to_python_hyphens_to_underscores():
    assert slug_to_python("solo-piano") == "solo_piano"
    assert slug_to_python("song") == "song"
    assert slug_to_python("a-b-c") == "a_b_c"


# ---------------------------------------------------------------------------
# Scaffold (filesystem)
# ---------------------------------------------------------------------------


def test_scaffold_writes_expected_files(tmp_path):
    req = _basic_req(slug="punk-fate")
    result = scaffold_song(req, songs_root=tmp_path)
    assert result.song_dir == tmp_path / "punk-fate"
    assert result.song_dir.is_dir()
    names = {p.name for p in result.song_dir.rglob("*") if p.is_file()}
    assert "build.py" in names
    assert "captured_session.json" in names
    assert "punk-fate.md" in names
    assert "test_punk_fate_build.py" in names  # slug → snake_case in test name
    # gitkeeps for the convention dirs (decisions / annotations / attempts)
    assert (result.song_dir / "decisions" / ".gitkeep").is_file()
    assert (result.song_dir / "annotations" / ".gitkeep").is_file()
    assert (result.song_dir / "attempts" / ".gitkeep").is_file()  # ATL-7K3M


def test_scaffold_refuses_existing_dir(tmp_path):
    req = _basic_req(slug="punk-fate")
    scaffold_song(req, songs_root=tmp_path)
    with pytest.raises(FileExistsError, match="already exists"):
        scaffold_song(req, songs_root=tmp_path)


def test_scaffold_refuses_invalid_slug(tmp_path):
    req = _basic_req(slug="Bad-Slug")
    with pytest.raises(ValueError, match="invalid slug"):
        scaffold_song(req, songs_root=tmp_path)


def test_scaffold_refuses_missing_template_dir(tmp_path):
    req = _basic_req()
    with pytest.raises(FileNotFoundError, match="template directory"):
        scaffold_song(req, songs_root=tmp_path, template_dir=tmp_path / "nope")


def test_scaffolded_captured_session_is_valid_json(tmp_path):
    req = _basic_req(slug="json-song", tempo=120.0, numerator=4, denominator=4)
    result = scaffold_song(req, songs_root=tmp_path)
    snap = json.loads((result.song_dir / "captured_session.json").read_text())
    assert snap["song"]["tempo"] == 120.0
    assert snap["song"]["signature"] == "4/4"
    assert len(snap["tracks"]) == 4
    assert len(snap["returns"]) == 2
    # SNP-8R4K: a freshly-scaffolded snapshot is version-stamped so its first
    # build doesn't false-trigger the pre-SNP-8R4K migration warning.
    assert snap["snapshot_version"] == 1


def test_scaffolded_build_py_imports_cleanly(tmp_path):
    """Generated build.py must compile + import without error."""
    req = _basic_req(slug="import-test")
    result = scaffold_song(req, songs_root=tmp_path)
    build_path = result.song_dir / "build.py"
    spec = importlib.util.spec_from_file_location("import_test_build", build_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.build)
    assert callable(mod.report)
    assert callable(mod.melody_report)


def test_scaffolded_build_py_carries_the_melodic_profile_example(tmp_path):
    """MEL-1A7K: the scaffold seeds the declared-profile authoring path so new songs
    see it. The template-as-deliverable lock (learnings: "when a doc/template IS the
    deliverable, lock it with a parity test") — `melody_report()`'s docstring carries
    a commented-out `profiles={...}` / `MelodicProfile` example."""
    req = _basic_req(slug="profile-example")
    result = scaffold_song(req, songs_root=tmp_path)
    src = (result.song_dir / "build.py").read_text()
    assert "MelodicProfile" in src
    assert "profiles=" in src
    assert "repetition_appetite" in src   # a v1 profile field, in the example


def test_scaffolded_build_py_runs_against_synthetic_snapshot(tmp_path, monkeypatch):
    """End-to-end: scaffold a song, run its build.py, verify shape."""
    req = _basic_req(slug="e2e-song", tempo=128.0, numerator=4, denominator=4,
                     sections=("intro", "verse", "chorus", "outro"))
    result = scaffold_song(req, songs_root=tmp_path)
    build_path = result.song_dir / "build.py"
    spec = importlib.util.spec_from_file_location("e2e_song_build", build_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Redirect DB to a clean temp path.
    monkeypatch.setattr(mod, "DB_PATH", tmp_path / "e2e.db")
    song_id = mod.build(reset=True)
    assert song_id

    # Verify the converger discipline: re-run produces zero new state events.
    from hallucinote.db import init_db
    conn = init_db(mod.DB_PATH)
    try:
        n_first = conn.execute(
            "SELECT COUNT(*) AS n FROM events "
            "WHERE kind NOT IN ('request_created','request_closed')"
        ).fetchone()["n"]
    finally:
        conn.close()

    mod.build(reset=False)
    conn = init_db(mod.DB_PATH)
    try:
        n_second = conn.execute(
            "SELECT COUNT(*) AS n FROM events "
            "WHERE kind NOT IN ('request_created','request_closed')"
        ).fetchone()["n"]
    finally:
        conn.close()

    assert n_second == n_first, (
        f"Scaffolded build.py is not converger-clean: re-run added "
        f"{n_second - n_first} extra state events"
    )


def test_scaffolded_test_file_runs_under_pytest(tmp_path, monkeypatch):
    """Scaffolded test_<slug>_build.py runs and passes against the generated build.py."""
    req = _basic_req(slug="ptest-song", tempo=120.0, numerator=4, denominator=4,
                     sections=("intro", "verse", "outro"))
    result = scaffold_song(req, songs_root=tmp_path)
    test_path = result.song_dir / "tests" / "test_ptest_song_build.py"
    assert test_path.is_file()

    # Run the scaffolded test in a subprocess (avoids polluting our pytest session).
    # Add the project root to PYTHONPATH so hallucinote is importable.
    project_root = Path(__file__).resolve().parents[3]
    env = {"PYTHONPATH": str(project_root / "src"), "PATH": "/usr/bin:/bin"}
    result_proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_path), "-q", "--no-header"],
        capture_output=True, text=True, env={**dict(__import__("os").environ), **env},
        timeout=60,
    )
    assert result_proc.returncode == 0, (
        f"Scaffolded test suite failed:\n"
        f"STDOUT:\n{result_proc.stdout}\n"
        f"STDERR:\n{result_proc.stderr}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_scaffolds_via_main(tmp_path, monkeypatch):
    """The argparse CLI plumbs through to scaffold_song correctly."""
    from hallucinote.tools.scaffold_song import main
    code = main([
        "cli-song",
        "--title", "CLI Song",
        "--tempo", "100",
        "--signature", "3/4",
        "--sections", "a,b,c",
        "--root", str(tmp_path),
    ])
    assert code == 0
    assert (tmp_path / "cli-song").is_dir()


def test_cli_returns_nonzero_on_bad_slug(tmp_path, capsys):
    from hallucinote.tools.scaffold_song import main
    code = main([
        "Bad-Slug", "--title", "x", "--tempo", "120",
        "--signature", "4/4", "--sections", "intro",
        "--root", str(tmp_path),
    ])
    assert code == 2
    captured = capsys.readouterr()
    assert "invalid slug" in captured.err


def test_cli_returns_nonzero_on_existing_dir(tmp_path, capsys):
    from hallucinote.tools.scaffold_song import main
    args = [
        "dup-song", "--title", "x", "--tempo", "120",
        "--signature", "4/4", "--sections", "intro",
        "--root", str(tmp_path),
    ]
    assert main(args) == 0
    assert main(args) == 3
    captured = capsys.readouterr()
    assert "already exists" in captured.err
