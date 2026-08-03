"""`hallucinote captures` — the operator surface over capture retention.

The prune path deletes gigabytes, so these tests pin the safety properties as
hard as the behavior: --dry-run writes nothing, prune refuses an ambiguous
target, and a pinned take survives.
"""
from __future__ import annotations

import json

import pytest

from hallucinote.tools import captures_cli


def _seed_take(captures_root, name, captured_at, *, pinned=False, status_state=None):
    take = captures_root / name
    take.mkdir(parents=True)
    (take / "manifest.json").write_text(
        json.dumps({"schema_version": "1", "captured_at": captured_at}),
        encoding="utf-8",
    )
    (take / "master.wav").write_bytes(b"\0" * 4096)
    if pinned:
        (take / ".pinned").write_text("", encoding="utf-8")
    if status_state is not None:
        (take / "status.json").write_text(
            json.dumps({"state": status_state}), encoding="utf-8"
        )
    return take


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A legacy-layout workspace (songs/<slug>/) rooted at cwd."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HALLUCINOTE_SONGS_ROOT", raising=False)
    monkeypatch.delenv("HALLUCINOTE_CAPTURE_KEEP", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return tmp_path


def _captures(workspace, slug="demo"):
    return workspace / "songs" / slug / "captures"


# --- list ------------------------------------------------------------------


def test_list_reports_takes_with_sizes(workspace, capsys):
    captures = _captures(workspace)
    _seed_take(captures, "take-0", "20260601T000000Z")
    _seed_take(captures, "take-1", "20260602T000000Z")

    assert captures_cli.main(["list", "--song", "demo"]) == 0

    out = capsys.readouterr().out
    assert "demo — 2 take(s)" in out
    assert "take-0" in out and "take-1" in out


def test_list_marks_pinned_and_in_flight_takes(workspace, capsys):
    captures = _captures(workspace)
    _seed_take(captures, "ref", "20260601T000000Z", pinned=True)
    _seed_take(captures, "live", "20260602T000000Z", status_state="running")

    captures_cli.main(["list", "--song", "demo"])

    out = capsys.readouterr().out
    assert "pinned" in out
    assert "in-flight" in out


def test_list_with_no_song_walks_every_song(workspace, capsys):
    _seed_take(_captures(workspace, "alpha"), "t0", "20260601T000000Z")
    _seed_take(_captures(workspace, "beta"), "t0", "20260601T000000Z")

    assert captures_cli.main(["list"]) == 0

    out = capsys.readouterr().out
    assert "alpha" in out and "beta" in out
    assert "total across 2 song(s)" in out


# --- prune -----------------------------------------------------------------


def test_prune_requires_an_explicit_target(workspace, capsys):
    """Deleting gigabytes must not be what a forgotten argument does."""
    _seed_take(_captures(workspace), "take-0", "20260601T000000Z")

    assert captures_cli.main(["prune"]) == 2

    assert "requires --song" in capsys.readouterr().err
    assert (_captures(workspace) / "take-0").exists()


def test_prune_honors_keep(workspace, capsys):
    captures = _captures(workspace)
    for i in range(4):
        _seed_take(captures, f"take-{i}", f"2026060{i}T000000Z")

    assert captures_cli.main(["prune", "--song", "demo", "--keep", "1"]) == 0

    assert {p.name for p in captures.iterdir()} == {"take-3"}


def test_prune_dry_run_removes_nothing_but_names_every_target(workspace, capsys):
    captures = _captures(workspace)
    for i in range(4):
        _seed_take(captures, f"take-{i}", f"2026060{i}T000000Z")

    assert captures_cli.main(
        ["prune", "--song", "demo", "--keep", "1", "--dry-run"]
    ) == 0

    out = capsys.readouterr().out
    assert "dry run — nothing was removed" in out
    for name in ("take-0", "take-1", "take-2"):
        assert name in out
    assert len(list(captures.iterdir())) == 4


def test_prune_keeps_pinned_takes(workspace):
    captures = _captures(workspace)
    _seed_take(captures, "reference", "20260101T000000Z", pinned=True)
    for i in range(3):
        _seed_take(captures, f"take-{i}", f"2026060{i}T000000Z")

    captures_cli.main(["prune", "--song", "demo", "--keep", "1"])

    assert (captures / "reference").exists()
    assert {p.name for p in captures.iterdir()} == {"reference", "take-2"}


def test_prune_skips_in_flight_takes_unless_forced(workspace):
    captures = _captures(workspace)
    _seed_take(captures, "stale", "20260101T000000Z", status_state="running")
    _seed_take(captures, "newer", "20260601T000000Z")

    captures_cli.main(["prune", "--song", "demo", "--keep", "1"])
    assert (captures / "stale").exists()

    captures_cli.main(["prune", "--song", "demo", "--keep", "1", "--force"])
    assert not (captures / "stale").exists()


def test_prune_all_walks_every_song(workspace):
    for slug in ("alpha", "beta"):
        captures = _captures(workspace, slug)
        for i in range(3):
            _seed_take(captures, f"take-{i}", f"2026060{i}T000000Z")

    assert captures_cli.main(["prune", "--all", "--keep", "1"]) == 0

    for slug in ("alpha", "beta"):
        assert {p.name for p in _captures(workspace, slug).iterdir()} == {"take-2"}


def test_prune_reports_nothing_to_do(workspace, capsys):
    _seed_take(_captures(workspace), "take-0", "20260601T000000Z")

    assert captures_cli.main(["prune", "--song", "demo", "--keep", "5"]) == 0

    assert "nothing to prune" in capsys.readouterr().out


def test_prune_rejects_a_negative_keep(workspace, capsys):
    assert captures_cli.main(["prune", "--song", "demo", "--keep", "-1"]) == 2
    assert "--keep must be >= 0" in capsys.readouterr().err


def test_prune_refuses_an_unknown_song(workspace, capsys):
    """A typo'd slug must not read as a successful sweep that found nothing."""
    _seed_take(_captures(workspace, "demo"), "take-0", "20260601T000000Z")

    assert captures_cli.main(["prune", "--song", "demoo", "--keep", "0"]) == 2

    assert "no song directory for 'demoo'" in capsys.readouterr().err
    assert (_captures(workspace, "demo") / "take-0").exists()


def test_list_refuses_an_unknown_song(workspace, capsys):
    assert captures_cli.main(["list", "--song", "nope"]) == 2
    assert "no song directory for 'nope'" in capsys.readouterr().err


def test_prune_never_touches_the_songs_durable_files(workspace):
    song = workspace / "songs" / "demo"
    captures = song / "captures"
    for i in range(3):
        _seed_take(captures, f"take-{i}", f"2026060{i}T000000Z")
    (song / "captured_session.json").write_text("{}", encoding="utf-8")
    (song / "analysis").mkdir()
    (song / "analysis" / "report.json").write_text("{}", encoding="utf-8")

    captures_cli.main(["prune", "--song", "demo", "--keep", "0"])

    assert (song / "captured_session.json").exists()
    assert (song / "analysis" / "report.json").exists()


# --- pin / unpin -----------------------------------------------------------


def test_pin_then_unpin_round_trips(workspace, capsys):
    take = _seed_take(_captures(workspace), "take-0", "20260601T000000Z")

    assert captures_cli.main(["pin", str(take)]) == 0
    assert (take / ".pinned").exists()

    assert captures_cli.main(["unpin", str(take)]) == 0
    assert not (take / ".pinned").exists()


def test_unpin_an_unpinned_take_is_a_no_op(workspace, capsys):
    take = _seed_take(_captures(workspace), "take-0", "20260601T000000Z")

    assert captures_cli.main(["unpin", str(take)]) == 0

    assert "was not pinned" in capsys.readouterr().out


def test_pin_refuses_a_missing_directory(workspace, capsys):
    assert captures_cli.main(["pin", str(workspace / "nope")]) == 2
    assert "not a directory" in capsys.readouterr().err


# --- dispatch --------------------------------------------------------------


def test_registered_on_the_unified_cli():
    from hallucinote import cli

    assert cli._SUBCOMMANDS["captures"] == (
        "hallucinote.tools.captures_cli", "main",
    )
    assert "captures" in cli._SUMMARY
