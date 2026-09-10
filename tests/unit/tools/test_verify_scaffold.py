"""`hallucinote verify-scaffold` — the in-process replacement for `/song-new` step 4.

The step was `pytest songs/<slug>/tests/ -v`, run with the one interpreter the skill
resolves (`$PY`, the plugin's inline env) — which has neither pytest nor pip, so the
stage's exit criterion was unmeetable as written. These tests pin that the subcommand
runs the SAME shape checks the scaffolded test file runs, that it never touches the
song's real DB, and that it fails (non-zero) when the scaffold is actually broken.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hallucinote.tools.scaffold_song import ScaffoldRequest, scaffold_song
from hallucinote.tools.verify_scaffold import (
    FAILED,
    OK,
    SKIPPED,
    main,
    verify_scaffold,
)


def _scaffold(tmp_path: Path, **overrides) -> Path:
    base = {
        "slug": "verify-song",
        "title": "Verify Song",
        "tempo": 128.0,
        "numerator": 4,
        "denominator": 4,
        "sections": ("intro", "verse", "chorus", "outro"),
    }
    base.update(overrides)
    req = ScaffoldRequest(**base)
    return scaffold_song(req, songs_root=tmp_path).song_dir


def _by_name(report) -> dict[str, object]:
    return {c.name: c for c in report.checks}


# ---------------------------------------------------------------------------
# The happy path — parity with the scaffolded test file
# ---------------------------------------------------------------------------


def test_verifies_a_freshly_scaffolded_song(tmp_path):
    _scaffold(tmp_path)
    report = verify_scaffold("verify-song", songs_root=tmp_path)

    assert report.ok, report.describe()
    checks = _by_name(report)
    assert set(checks) == {
        "files", "build", "sections", "tracks", "tempo", "signature", "converger",
    }
    # Structural checks run without any declared value.
    for name in ("files", "build", "tracks", "converger"):
        assert checks[name].status == OK, checks[name]


def test_declared_values_are_compared_when_given(tmp_path):
    """The equality assertions the scaffolded test hard-codes, supplied by the caller."""
    _scaffold(tmp_path, slug="declared-song", tempo=93.0, numerator=7, denominator=8,
              sections=("intro", "a", "b"))
    report = verify_scaffold(
        "declared-song",
        songs_root=tmp_path,
        expect_sections=("intro", "a", "b"),
        expect_tempo=93.0,
        expect_signature=(7, 8),
    )

    assert report.ok, report.describe()
    checks = _by_name(report)
    assert checks["sections"].status == OK
    assert checks["tempo"].status == OK
    assert checks["signature"].status == OK


def test_undeclared_values_are_reported_skipped_not_passed(tmp_path):
    """Nothing pretends to have checked a value it was never given."""
    _scaffold(tmp_path)
    report = verify_scaffold("verify-song", songs_root=tmp_path)

    checks = _by_name(report)
    for name in ("sections", "tempo", "signature"):
        assert checks[name].status == SKIPPED, checks[name]
        assert "--expect-" in checks[name].detail
    # A skipped check does not fail the run.
    assert report.ok


@pytest.mark.parametrize(
    "kwargs, failing",
    [
        ({"expect_sections": ("intro", "verse")}, "sections"),
        ({"expect_tempo": 999.0}, "tempo"),
        ({"expect_signature": (3, 4)}, "signature"),
    ],
)
def test_a_mismatched_declared_value_fails_that_check(tmp_path, kwargs, failing):
    _scaffold(tmp_path)
    report = verify_scaffold("verify-song", songs_root=tmp_path, **kwargs)

    assert not report.ok
    assert _by_name(report)[failing].status == FAILED


# ---------------------------------------------------------------------------
# Non-destructive: the song's real DB is never opened
# ---------------------------------------------------------------------------


def test_does_not_write_the_songs_own_db(tmp_path):
    """`build(reset=True)` wipes build-owned content — verification must not do that
    to the song being verified, so the build is redirected to a throwaway DB."""
    song_dir = _scaffold(tmp_path)
    before = {p.name for p in tmp_path.rglob("*") if p.suffix == ".db"}
    assert not before

    assert verify_scaffold("verify-song", songs_root=tmp_path).ok

    after = {p for p in tmp_path.rglob("*") if p.suffix == ".db"}
    assert not after, f"verify-scaffold left DB files behind: {after}"
    assert song_dir.is_dir()


# ---------------------------------------------------------------------------
# Failure + refusal paths
# ---------------------------------------------------------------------------


def test_a_broken_build_fails_and_skips_the_downstream_checks(tmp_path):
    song_dir = _scaffold(tmp_path)
    build_py = song_dir / "build.py"
    build_py.write_text(build_py.read_text() + "\nraise RuntimeError('boom')\n")

    report = verify_scaffold("verify-song", songs_root=tmp_path)

    assert not report.ok
    checks = _by_name(report)
    assert checks["build"].status == FAILED
    assert "boom" in checks["build"].detail
    for name in ("sections", "tracks", "tempo", "signature", "converger"):
        assert checks[name].status == SKIPPED


def test_a_missing_scaffold_file_fails_the_files_check(tmp_path):
    song_dir = _scaffold(tmp_path)
    (song_dir / "tests" / "test_verify_song_build.py").unlink()

    report = verify_scaffold("verify-song", songs_root=tmp_path)

    assert not report.ok
    files = _by_name(report)["files"]
    assert files.status == FAILED
    assert "test_verify_song_build.py" in files.detail


def test_refuses_an_unscaffolded_slug(tmp_path):
    with pytest.raises(FileNotFoundError):
        verify_scaffold("nope", songs_root=tmp_path)


def test_refuses_a_directory_without_build_py(tmp_path):
    (tmp_path / "half-song").mkdir()
    with pytest.raises(FileNotFoundError):
        verify_scaffold("half-song", songs_root=tmp_path)


def test_refuses_an_invalid_slug(tmp_path):
    with pytest.raises(ValueError):
        verify_scaffold("Not A Slug", songs_root=tmp_path)


# ---------------------------------------------------------------------------
# CLI entry point — what the dispatcher will forward to
# ---------------------------------------------------------------------------


def test_cli_returns_zero_and_prints_the_report(tmp_path, capsys):
    _scaffold(tmp_path)
    rc = main([
        "verify-song", "--root", str(tmp_path),
        "--expect-sections", "intro,verse,chorus,outro",
        "--expect-tempo", "128",
        "--expect-signature", "4/4",
    ])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "verify-scaffold verify-song" in out
    assert "scaffold verified" in out
    for name in ("files", "build", "sections", "tracks", "tempo", "signature",
                 "converger"):
        assert name in out


def test_cli_returns_one_when_a_check_fails(tmp_path, capsys):
    _scaffold(tmp_path)
    rc = main(["verify-song", "--root", str(tmp_path), "--expect-tempo", "60"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "FAILED: tempo" in out


def test_cli_returns_two_on_a_refusal(tmp_path, capsys):
    rc = main(["missing-song", "--root", str(tmp_path)])
    assert rc == 2
    assert "verify-scaffold:" in capsys.readouterr().err


def test_cli_returns_two_on_a_malformed_expect_signature(tmp_path, capsys):
    _scaffold(tmp_path)
    rc = main(["verify-song", "--root", str(tmp_path), "--expect-signature", "four"])
    assert rc == 2
    assert "invalid signature" in capsys.readouterr().err


def test_cli_keeps_build_chatter_off_stdout(tmp_path, capsys):
    """stdout is the report; build.py's own printing goes to stderr so a caller
    reading stdout gets only check results."""
    _scaffold(tmp_path)
    assert main(["verify-song", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("verify-scaffold verify-song")
