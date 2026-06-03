"""Project-root contract — workspace marker discovery + song-dir resolution.

`hallucinote.workspace` lets a song live in its own repo, outside the engine
monorepo. See `.prawduct/artifacts/project-root-contract.md`. These tests are
hermetic: they pass `start=` explicitly (or monkeypatch the env) so they never
depend on the working tree's real cwd / CLAUDE_PROJECT_DIR.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hallucinote import workspace as W
from hallucinote.workspace import (
    ENV_PROJECT_DIR,
    ENV_SONGS_ROOT,
    Workspace,
    find_workspace,
    resolve_song_dir,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """No ambient project-root env leaks into a hermetic test."""
    monkeypatch.delenv(ENV_SONGS_ROOT, raising=False)
    monkeypatch.delenv(ENV_PROJECT_DIR, raising=False)


def _write_marker(d: Path, body: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / W.MARKER_FILENAME).write_text(body)
    return d


# ---------------------------------------------------------------------------
# find_workspace
# ---------------------------------------------------------------------------


def test_no_marker_returns_none(tmp_path):
    assert find_workspace(start=tmp_path) is None


def test_monorepo_marker_defaults(tmp_path):
    _write_marker(tmp_path, '[workspace]\nlayout = "monorepo"\n')
    ws = find_workspace(start=tmp_path)
    assert ws == Workspace(
        root=tmp_path.resolve(), layout="monorepo", songs_root="songs", slug=None
    )
    assert ws.song_dir("falling-walking") == tmp_path.resolve() / "songs" / "falling-walking"


def test_monorepo_custom_songs_root(tmp_path):
    _write_marker(tmp_path, '[workspace]\nlayout = "monorepo"\nsongs_root = "tracks"\n')
    ws = find_workspace(start=tmp_path)
    assert ws.songs_root == "tracks"
    assert ws.song_dir("x") == tmp_path.resolve() / "tracks" / "x"


def test_song_layout_is_flat(tmp_path):
    _write_marker(tmp_path, '[workspace]\nlayout = "song"\nslug = "midnight-drive"\n')
    ws = find_workspace(start=tmp_path)
    assert ws.layout == "song"
    assert ws.slug == "midnight-drive"
    assert ws.songs_root == "."
    # flat: the marker's directory IS the song dir, regardless of slug
    assert ws.song_dir("midnight-drive") == tmp_path.resolve()


def test_marker_found_by_walking_up(tmp_path):
    _write_marker(tmp_path, '[workspace]\nlayout = "monorepo"\n')
    nested = tmp_path / "songs" / "foo" / "subdir"
    nested.mkdir(parents=True)
    ws = find_workspace(start=nested)
    assert ws is not None and ws.root == tmp_path.resolve()


def test_invalid_layout_falls_back_to_monorepo(tmp_path):
    _write_marker(tmp_path, '[workspace]\nlayout = "bananas"\n')
    ws = find_workspace(start=tmp_path)
    assert ws.layout == "monorepo"


def test_top_level_keys_tolerated(tmp_path):
    """A marker without the [workspace] table — keys at the top level."""
    _write_marker(tmp_path, 'layout = "song"\nslug = "solo"\n')
    ws = find_workspace(start=tmp_path)
    assert ws.layout == "song" and ws.slug == "solo"


def test_malformed_toml_is_ignored(tmp_path):
    _write_marker(tmp_path, "this is = = not toml [[[")
    assert find_workspace(start=tmp_path) is None


def test_no_toml_parser_degrades_to_none(tmp_path, monkeypatch):
    """On Python < 3.11 without `tomli`, the marker is ignored (not raised)."""
    _write_marker(tmp_path, '[workspace]\nlayout = "song"\n')
    import builtins

    real_import = builtins.__import__

    def _no_toml(name, *args, **kwargs):
        if name in ("tomllib", "tomli"):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_toml)
    # both parsers unavailable → marker can't be parsed → no workspace, no raise
    assert find_workspace(start=tmp_path) is None


def test_start_from_project_dir_env(tmp_path, monkeypatch):
    _write_marker(tmp_path, '[workspace]\nlayout = "monorepo"\n')
    monkeypatch.setenv(ENV_PROJECT_DIR, str(tmp_path))
    ws = find_workspace()  # no explicit start → uses CLAUDE_PROJECT_DIR
    assert ws is not None and ws.root == tmp_path.resolve()


# ---------------------------------------------------------------------------
# resolve_song_dir — precedence
# ---------------------------------------------------------------------------


def test_env_songs_root_wins(tmp_path, monkeypatch):
    # marker present, but the env override takes precedence
    _write_marker(tmp_path, '[workspace]\nlayout = "song"\nslug = "x"\n')
    monkeypatch.setenv(ENV_SONGS_ROOT, "/srv/songs")
    assert resolve_song_dir("x", start=tmp_path) == Path("/srv/songs") / "x"


def test_marker_used_when_no_env(tmp_path):
    _write_marker(tmp_path, '[workspace]\nlayout = "monorepo"\n')
    assert resolve_song_dir("x", start=tmp_path) == tmp_path.resolve() / "songs" / "x"


def test_legacy_fallback_when_nothing(tmp_path):
    assert resolve_song_dir("x", start=tmp_path) == Path("songs") / "x"
