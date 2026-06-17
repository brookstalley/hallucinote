"""init-workspace — the write side of the project-root contract.

Authoring a ``hallucinote.toml`` marker must produce something the *reader*
(`hallucinote.workspace.find_workspace`) actually resolves, and must refuse to
silently nest a workspace inside another. These tests pair the author with the
reader so the round-trip — not just the bytes written — is the contract.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hallucinote import workspace as W
from hallucinote.tools import init_workspace as IW
from hallucinote.tools.init_workspace import init_workspace
from hallucinote.workspace import ENV_PROJECT_DIR, ENV_SONGS_ROOT, find_workspace


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """No ambient project-root env leaks into a hermetic test."""
    monkeypatch.delenv(ENV_SONGS_ROOT, raising=False)
    monkeypatch.delenv(ENV_PROJECT_DIR, raising=False)


# ---------------------------------------------------------------------------
# round-trip: author → reader
# ---------------------------------------------------------------------------


def test_monorepo_marker_round_trips(tmp_path):
    res = init_workspace(tmp_path, git=False)
    assert res.written and res.layout == "monorepo" and res.songs_root == "songs"
    assert Path(res.marker_path) == tmp_path / W.MARKER_FILENAME

    ws = find_workspace(start=tmp_path)
    assert ws is not None
    assert ws.layout == "monorepo" and ws.songs_root == "songs"
    assert ws.song_dir("punk-fate") == tmp_path.resolve() / "songs" / "punk-fate"


def test_custom_songs_root(tmp_path):
    init_workspace(tmp_path, songs_root="tracks", git=False)
    ws = find_workspace(start=tmp_path)
    assert ws.songs_root == "tracks"


def test_song_layout_round_trips(tmp_path):
    res = init_workspace(tmp_path, layout="song", slug="midnight-drive", git=False)
    assert res.layout == "song" and res.slug == "midnight-drive" and res.songs_root == "."
    ws = find_workspace(start=tmp_path)
    assert ws.layout == "song" and ws.slug == "midnight-drive"
    # flat: the marker's directory IS the song dir
    assert ws.song_dir("midnight-drive") == tmp_path.resolve()


def test_song_layout_requires_slug(tmp_path):
    with pytest.raises(ValueError, match="requires --slug"):
        init_workspace(tmp_path, layout="song", git=False)


def test_song_layout_validates_slug(tmp_path):
    with pytest.raises(ValueError, match="invalid slug"):
        init_workspace(tmp_path, layout="song", slug="Bad Slug", git=False)


def test_invalid_layout_rejected(tmp_path):
    with pytest.raises(ValueError, match="invalid layout"):
        init_workspace(tmp_path, layout="bananas", git=False)


# ---------------------------------------------------------------------------
# refuse-in-existing-workspace
# ---------------------------------------------------------------------------


def test_refuses_inside_existing_workspace(tmp_path):
    init_workspace(tmp_path, git=False)
    nested = tmp_path / "songs" / "foo"
    nested.mkdir(parents=True)
    with pytest.raises(FileExistsError, match="already inside a workspace"):
        init_workspace(nested, git=False)
    # the refusal wrote nothing
    assert not (nested / W.MARKER_FILENAME).exists()


def test_force_creates_nested_marker(tmp_path):
    init_workspace(tmp_path, git=False)
    nested = tmp_path / "songs" / "foo"
    nested.mkdir(parents=True)
    res = init_workspace(nested, git=False, force=True)
    assert res.written and res.already_workspace
    # the nested marker now shadows: resolution from `nested` finds the inner root
    assert find_workspace(start=nested).root == nested.resolve()


# ---------------------------------------------------------------------------
# --check (dry run)
# ---------------------------------------------------------------------------


def test_check_writes_nothing_when_absent(tmp_path):
    res = init_workspace(tmp_path, check=True)
    assert res.written is False and res.already_workspace is False
    assert res.existing_marker is None
    assert not (tmp_path / W.MARKER_FILENAME).exists()
    assert find_workspace(start=tmp_path) is None


def test_check_reports_existing_workspace(tmp_path):
    init_workspace(tmp_path, git=False)
    nested = tmp_path / "songs" / "foo"
    nested.mkdir(parents=True)
    res = init_workspace(nested, check=True)
    assert res.already_workspace is True
    assert res.existing_marker == str(tmp_path.resolve() / W.MARKER_FILENAME)
    assert res.written is False
    # check never git-inits either
    assert res.git_initialized is False


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


def test_no_git_skips_init(tmp_path):
    res = init_workspace(tmp_path, git=False)
    assert res.git_initialized is False
    assert not (tmp_path / ".git").exists()


def test_git_init_creates_repo(tmp_path):
    res = init_workspace(tmp_path, git=True)
    assert res.already_git is False
    assert res.git_initialized is True
    assert (tmp_path / ".git").exists()


def test_git_skipped_when_already_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    res = init_workspace(tmp_path, git=True)
    assert res.already_git is True and res.git_initialized is False


# ---------------------------------------------------------------------------
# .gitignore (regenerable-artifact stanza)
# ---------------------------------------------------------------------------


def test_gitignore_written_fresh(tmp_path):
    res = init_workspace(tmp_path, git=False)
    assert res.gitignore_written is True and res.gitignore_updated is False
    body = (tmp_path / ".gitignore").read_text()
    assert "Hallucinote" in body
    # covers the artifacts the toolchain regenerates (the filed bug's set)
    for pat in ("*.db", "**/captures/", "**/analysis/", "**/.last-notes-push.json"):
        assert pat in body


def test_gitignore_idempotent(tmp_path):
    init_workspace(tmp_path, git=False)
    first = (tmp_path / ".gitignore").read_text()
    # re-running (force, since the dir is now a workspace) must not duplicate the block
    res = init_workspace(tmp_path, git=False, force=True)
    assert res.gitignore_written is False and res.gitignore_updated is False
    after = (tmp_path / ".gitignore").read_text()
    assert after == first
    assert after.count(IW._GITIGNORE_BEGIN) == 1


def test_gitignore_appends_to_existing(tmp_path):
    gi = tmp_path / ".gitignore"
    gi.write_text("# my own rules\nsecret.env\n")
    res = init_workspace(tmp_path, git=False)
    assert res.gitignore_written is False and res.gitignore_updated is True
    body = gi.read_text()
    assert "secret.env" in body  # user content preserved
    assert IW._GITIGNORE_BEGIN in body and "*.db" in body


def test_no_gitignore_skips(tmp_path):
    res = init_workspace(tmp_path, git=False, gitignore=False)
    assert res.gitignore_written is False and res.gitignore_updated is False
    assert not (tmp_path / ".gitignore").exists()


def test_check_does_not_write_gitignore(tmp_path):
    init_workspace(tmp_path, check=True)
    assert not (tmp_path / ".gitignore").exists()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_writes_and_prints_json(tmp_path, capsys):
    rc = IW.main([str(tmp_path), "--no-git"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["written"] is True and out["layout"] == "monorepo"
    assert find_workspace(start=tmp_path) is not None


def test_cli_check_is_readonly(tmp_path, capsys):
    rc = IW.main([str(tmp_path), "--check"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["written"] is False
    assert not (tmp_path / W.MARKER_FILENAME).exists()


def test_cli_refusal_returns_nonzero(tmp_path, capsys):
    IW.main([str(tmp_path), "--no-git"])
    capsys.readouterr()
    nested = tmp_path / "songs" / "foo"
    nested.mkdir(parents=True)
    rc = IW.main([str(nested), "--no-git"])
    assert rc == 3
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and "already inside a workspace" in out["error"]


def test_cli_song_layout_missing_slug_returns_2(tmp_path, capsys):
    rc = IW.main([str(tmp_path), "--layout", "song", "--no-git"])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and "requires --slug" in out["error"]


def test_dispatcher_routes_init_workspace(monkeypatch):
    """`hallucinote init-workspace <dir>` reaches init_workspace.main."""
    from hallucinote import cli

    seen = {}

    def spy(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(IW, "main", spy)
    assert cli.main(["init-workspace", "/tmp/x", "--no-git"]) == 0
    assert seen["argv"] == ["/tmp/x", "--no-git"]
