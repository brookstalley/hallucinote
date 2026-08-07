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
    find_workspaces_below,
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


# ---------------------------------------------------------------------------
# Bounded descent — a workspace BELOW the start directory (precedence step 4)
#
# The start directory is CLAUDE_PROJECT_DIR / cwd, never the song. A workspace
# nested below it (this repo's own `examples/`; an editor rooted a level above
# a songs repo) was invisible to the upward walk, and the legacy fallback then
# handed back `songs/<slug>` — a path naming nothing. Callers treat that as
# authoritative: a render created the phantom tree and wrote ~290 MB of WAVs
# into it, and analysis reported "doesn't name a built song" for a song that
# was built the whole time.
# ---------------------------------------------------------------------------


def test_marker_below_start_is_found(tmp_path):
    """The bug, minimally: marker one level down, resolve from the parent."""
    _write_marker(tmp_path / "examples", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    (tmp_path / "examples" / "demo").mkdir()
    assert resolve_song_dir("demo", start=tmp_path) == (
        tmp_path.resolve() / "examples" / "demo"
    )


def test_marker_below_start_wins_over_the_legacy_path(tmp_path):
    """Markers beat the legacy default (step 4 before step 5) — including when
    a stray `songs/<slug>/` exists, which is exactly what a misresolved render
    leaves behind. The wreckage must not outrank the real workspace."""
    _write_marker(tmp_path / "examples", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    (tmp_path / "examples" / "demo").mkdir()
    (tmp_path / "songs" / "demo" / "captures").mkdir(parents=True)
    assert resolve_song_dir("demo", start=tmp_path) == (
        tmp_path.resolve() / "examples" / "demo"
    )


def test_descent_reaches_two_levels(tmp_path):
    _write_marker(tmp_path / "a" / "b", '[workspace]\nlayout = "monorepo"\n')
    assert resolve_song_dir("x", start=tmp_path) == (
        tmp_path.resolve() / "a" / "b" / "songs" / "x"
    )


def test_descent_stops_before_three_levels(tmp_path):
    """Bounded, not a crawl: past MAX_DESCEND_DEPTH it fails loud instead."""
    _write_marker(tmp_path / "a" / "b" / "c", '[workspace]\nlayout = "monorepo"\n')
    assert resolve_song_dir("x", start=tmp_path) == Path("songs") / "x"


def test_descent_skips_hidden_and_vendor_dirs(tmp_path):
    _write_marker(tmp_path / ".cache", '[workspace]\nlayout = "monorepo"\n')
    _write_marker(tmp_path / "node_modules", '[workspace]\nlayout = "monorepo"\n')
    assert find_workspaces_below(tmp_path) == []


def test_descent_does_not_enter_a_workspace_subtree(tmp_path):
    """A workspace owns what's under it — a marker nested inside one is that
    workspace's business, not a second candidate that makes the choice
    ambiguous."""
    _write_marker(tmp_path / "ws", '[workspace]\nlayout = "monorepo"\n')
    _write_marker(tmp_path / "ws" / "inner", '[workspace]\nlayout = "monorepo"\n')
    below = find_workspaces_below(tmp_path)
    assert [w.root for w in below] == [(tmp_path / "ws").resolve()]


def test_ambiguous_descent_declines_rather_than_guessing(tmp_path):
    """Two workspaces below and no way to choose: fall through to legacy so the
    failure surfaces, rather than silently picking one."""
    _write_marker(tmp_path / "one", '[workspace]\nlayout = "monorepo"\n')
    _write_marker(tmp_path / "two", '[workspace]\nlayout = "monorepo"\n')
    assert resolve_song_dir("x", start=tmp_path) == Path("songs") / "x"


def test_env_and_upward_marker_still_outrank_the_descent(tmp_path, monkeypatch):
    """Precedence is unchanged above step 4."""
    _write_marker(tmp_path, '[workspace]\nlayout = "monorepo"\nsongs_root = "up"\n')
    _write_marker(tmp_path / "down", '[workspace]\nlayout = "monorepo"\n')
    assert resolve_song_dir("x", start=tmp_path) == tmp_path.resolve() / "up" / "x"
    monkeypatch.setenv(ENV_SONGS_ROOT, "/srv/songs")
    assert resolve_song_dir("x", start=tmp_path) == Path("/srv/songs") / "x"


def test_find_workspace_does_not_descend_by_default(tmp_path):
    """`find_workspace` answers "which workspace am I INSIDE?" unless asked to
    descend — `init-workspace`'s refuse-inside-an-existing-workspace guard
    depends on that, and would wrongly refuse in a directory that merely
    CONTAINS a workspace."""
    _write_marker(tmp_path / "ws", '[workspace]\nlayout = "monorepo"\n')
    assert find_workspace(start=tmp_path) is None
    assert find_workspace(start=tmp_path, descend=True).root == (
        tmp_path / "ws"
    ).resolve()


def test_resolution_reports_its_source(tmp_path):
    _write_marker(tmp_path / "ws", '[workspace]\nlayout = "monorepo"\n')
    res = W.resolve_song_dir_explained("x", start=tmp_path)
    assert res.source == W.SOURCE_MARKER_BELOW
    assert W.resolve_song_dir_explained("x", start=tmp_path / "empty").source == (
        W.SOURCE_LEGACY
    )


# ---------------------------------------------------------------------------
# explain_unresolved_song — the three failures a missing DB can mean
# ---------------------------------------------------------------------------


def _build_song(song_dir: Path) -> Path:
    song_dir.mkdir(parents=True, exist_ok=True)
    (song_dir / "build.py").write_text("# built\n")
    return song_dir


def test_explain_names_the_workspace_that_lacks_the_song(tmp_path):
    """"Found a workspace, song isn't in it" — say which workspace, and what
    songs it does have, rather than "doesn't name a built song"."""
    ws = _write_marker(tmp_path / "ws", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    _build_song(ws / "other-song")
    msg = W.explain_unresolved_song("missing-song", start=tmp_path)
    assert str(ws.resolve()) in msg
    assert "other-song" in msg
    assert "no hallucinote.toml workspace marker" not in msg


def test_explain_says_no_marker_was_found_on_the_legacy_fallback(tmp_path):
    """"No marker anywhere" is a different diagnosis from "wrong workspace",
    and the remediation differs too — say so."""
    msg = W.explain_unresolved_song("x", start=tmp_path)
    assert "no hallucinote.toml workspace marker was found at or above" in msg
    assert str(tmp_path.resolve()) in msg
    assert ENV_SONGS_ROOT in msg


def test_explain_names_the_ambiguous_workspaces_it_declined(tmp_path):
    _write_marker(tmp_path / "one", '[workspace]\nlayout = "monorepo"\n')
    _write_marker(tmp_path / "two", '[workspace]\nlayout = "monorepo"\n')
    msg = W.explain_unresolved_song("x", start=tmp_path)
    assert "ambiguous" in msg
    assert str((tmp_path / "one").resolve()) in msg
    assert str((tmp_path / "two").resolve()) in msg


def test_explain_refuses_to_advise_a_rebuild_of_a_song_built_elsewhere(tmp_path):
    """The defect's worst symptom was advice: analysis told the operator to run
    `build.py --reset` on a song that was built and findable one directory
    away. Following it would have scaffolded a duplicate over real work."""
    _write_marker(tmp_path / "one", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    _write_marker(tmp_path / "two", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    built = _build_song(tmp_path / "two" / "demo")  # ambiguous ⇒ resolves legacy
    msg = W.explain_unresolved_song("demo", start=tmp_path)
    assert "--reset" not in msg, f"must not advise a rebuild: {msg}"
    assert str(built.resolve()) in msg
    assert "IS built at" in msg


def test_explain_does_advise_a_build_when_the_song_exists_nowhere(tmp_path):
    """The honest case still gets the honest advice."""
    _write_marker(tmp_path / "ws", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    msg = W.explain_unresolved_song("nowhere", start=tmp_path)
    assert "--reset" in msg


def test_a_bare_captures_dir_is_not_a_built_song(tmp_path):
    """`songs/<slug>/captures/` is the residue a misresolved render leaves. It
    must not be reported as the song, or the wreckage of the bug impersonates
    what it displaced."""
    (tmp_path / "songs" / "demo" / "captures").mkdir(parents=True)
    assert W.find_song_elsewhere("demo", start=tmp_path) == []
