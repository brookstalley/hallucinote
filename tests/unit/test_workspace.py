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


@pytest.fixture
def proj(tmp_path):
    """An isolated start directory, one level inside `tmp_path`.

    Resolution consults the start directory's SIBLINGS (precedence step 4), and
    pytest's `tmp_path` siblings are other tests' `tmp_path`s — several of which
    plant workspace markers and build songs. Nesting one level gives every test
    its own neighbourhood, so no test's answer can be steered by another test's
    fixtures, and the module's hermeticity claim stays true.
    """
    d = tmp_path / "proj"
    d.mkdir()
    return d


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


def test_env_songs_root_wins(proj, monkeypatch):
    # marker present, but the env override takes precedence
    _write_marker(proj, '[workspace]\nlayout = "song"\nslug = "x"\n')
    monkeypatch.setenv(ENV_SONGS_ROOT, "/srv/songs")
    assert resolve_song_dir("x", start=proj) == Path("/srv/songs") / "x"


def test_marker_used_when_no_env(proj):
    _write_marker(proj, '[workspace]\nlayout = "monorepo"\n')
    assert resolve_song_dir("x", start=proj) == proj.resolve() / "songs" / "x"


def test_legacy_fallback_when_nothing(proj):
    assert resolve_song_dir("x", start=proj) == Path("songs") / "x"


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


def test_marker_below_start_is_found(proj):
    """The bug, minimally: marker one level down, resolve from the parent."""
    _write_marker(proj / "examples", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    (proj / "examples" / "demo").mkdir()
    assert resolve_song_dir("demo", start=proj) == (
        proj.resolve() / "examples" / "demo"
    )


def test_marker_below_start_wins_over_the_legacy_path(proj):
    """Markers beat the legacy default (step 4 before step 5) — including when
    a stray `songs/<slug>/` exists, which is exactly what a misresolved render
    leaves behind. The wreckage must not outrank the real workspace."""
    _write_marker(proj / "examples", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    (proj / "examples" / "demo").mkdir()
    (proj / "songs" / "demo" / "captures").mkdir(parents=True)
    assert resolve_song_dir("demo", start=proj) == (
        proj.resolve() / "examples" / "demo"
    )


def test_descent_reaches_two_levels(proj):
    _write_marker(proj / "a" / "b", '[workspace]\nlayout = "monorepo"\n')
    assert resolve_song_dir("x", start=proj) == (
        proj.resolve() / "a" / "b" / "songs" / "x"
    )


def test_descent_stops_before_three_levels(proj):
    """Bounded, not a crawl: past MAX_DESCEND_DEPTH it fails loud instead."""
    _write_marker(proj / "a" / "b" / "c", '[workspace]\nlayout = "monorepo"\n')
    assert resolve_song_dir("x", start=proj) == Path("songs") / "x"


def test_descent_skips_hidden_and_vendor_dirs(proj):
    _write_marker(proj / ".cache", '[workspace]\nlayout = "monorepo"\n')
    _write_marker(proj / "node_modules", '[workspace]\nlayout = "monorepo"\n')
    assert find_workspaces_below(proj) == []


def test_descent_does_not_enter_a_workspace_subtree(proj):
    """A workspace owns what's under it — a marker nested inside one is that
    workspace's business, not a second candidate that makes the choice
    ambiguous."""
    _write_marker(proj / "ws", '[workspace]\nlayout = "monorepo"\n')
    _write_marker(proj / "ws" / "inner", '[workspace]\nlayout = "monorepo"\n')
    below = find_workspaces_below(proj)
    assert [w.root for w in below] == [(proj / "ws").resolve()]


def test_ambiguous_descent_declines_rather_than_guessing(proj):
    """Two workspaces below and no way to choose: fall through to legacy so the
    failure surfaces, rather than silently picking one."""
    _write_marker(proj / "one", '[workspace]\nlayout = "monorepo"\n')
    _write_marker(proj / "two", '[workspace]\nlayout = "monorepo"\n')
    assert resolve_song_dir("x", start=proj) == Path("songs") / "x"


def test_env_and_upward_marker_still_outrank_the_descent(proj, monkeypatch):
    """Precedence is unchanged above step 4."""
    _write_marker(proj, '[workspace]\nlayout = "monorepo"\nsongs_root = "up"\n')
    _write_marker(proj / "down", '[workspace]\nlayout = "monorepo"\n')
    assert resolve_song_dir("x", start=proj) == proj.resolve() / "up" / "x"
    monkeypatch.setenv(ENV_SONGS_ROOT, "/srv/songs")
    assert resolve_song_dir("x", start=proj) == Path("/srv/songs") / "x"


def test_find_workspace_does_not_descend_by_default(proj):
    """`find_workspace` answers "which workspace am I INSIDE?" unless asked to
    descend — `init-workspace`'s refuse-inside-an-existing-workspace guard
    depends on that, and would wrongly refuse in a directory that merely
    CONTAINS a workspace."""
    _write_marker(proj / "ws", '[workspace]\nlayout = "monorepo"\n')
    assert find_workspace(start=proj) is None
    assert find_workspace(start=proj, descend=True).root == (
        proj / "ws"
    ).resolve()


def test_resolution_reports_its_source(proj):
    _write_marker(proj / "ws", '[workspace]\nlayout = "monorepo"\n')
    res = W.resolve_song_dir_explained("x", start=proj)
    assert res.source == W.SOURCE_MARKER_BELOW
    assert W.resolve_song_dir_explained("x", start=proj / "empty").source == (
        W.SOURCE_LEGACY
    )


def _build_song(song_dir: Path) -> Path:
    song_dir.mkdir(parents=True, exist_ok=True)
    (song_dir / "build.py").write_text("# built\n")
    return song_dir


# ---------------------------------------------------------------------------
# Precedence step 4 — the workspace that HOLDS the slug
#
# Discovery answering "which workspace is near me?" is the wrong question. The
# framework repo ships a demo workspace at `examples/`, so a session rooted at
# the framework repo found exactly ONE marker below, took it as unambiguous,
# and resolved every slug into the demo workspace — including songs living in a
# separate songs repo, which is the supported two-repo topology. `ableton_render`
# then wrote captures into the demo workspace and `ableton_analysis`, which has
# no output_dir escape hatch, hard-failed with "no song DB at
# .../examples/<slug>/...". A lone candidate is not the same as a correct one.
# ---------------------------------------------------------------------------


def _songs_workspace(root: Path, *slugs: str) -> Path:
    """A monorepo workspace at `root` holding a built song per slug."""
    _write_marker(root, '[workspace]\nlayout = "monorepo"\nsongs_root = "songs"\n')
    for slug in slugs:
        _build_song(root / "songs" / slug)
    return root


def test_a_sibling_workspace_that_holds_the_song_beats_a_nearer_one_that_does_not(proj):
    """THE BUG. Session rooted at the framework repo (a demo workspace nested
    below it), song living in the sibling songs repo. The nested demo workspace
    must not capture a slug it has never heard of."""
    _write_marker(proj / "examples", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    _build_song(proj / "examples" / "b-natural")
    songs_repo = _songs_workspace(proj.parent / "songs-repo", "the-argument")

    res = W.resolve_song_dir_explained("the-argument", start=proj)
    assert res.song_dir == songs_repo.resolve() / "songs" / "the-argument"
    assert res.source == W.SOURCE_MARKER_BESIDE


def test_the_demo_workspace_still_resolves_the_songs_it_actually_holds(proj):
    """The fix is slug-aware, not a demotion of nested workspaces: `examples/`
    keeps resolving its own songs, so the in-repo demo marker stays useful and
    does not have to be deleted to unshadow real workspaces."""
    _write_marker(proj / "examples", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    _build_song(proj / "examples" / "b-natural")
    _songs_workspace(proj.parent / "songs-repo", "the-argument")

    res = W.resolve_song_dir_explained("b-natural", start=proj)
    assert res.song_dir == (proj / "examples" / "b-natural").resolve()
    assert res.source == W.SOURCE_MARKER_BELOW


def test_a_holder_below_beats_a_workspace_that_merely_sits_below(proj):
    """Two workspaces below, one holding the song: no longer ambiguous, because
    the question is who HOLDS it, not who is nearest."""
    _write_marker(proj / "one", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    _write_marker(proj / "two", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    built = _build_song(proj / "two" / "demo")
    assert resolve_song_dir("demo", start=proj) == built.resolve()


def test_below_outranks_beside_when_both_hold_the_song(proj):
    """A workspace inside the session's own tree is the better answer when both
    carry the song — adjacency is the last resort, not a peer."""
    _write_marker(proj / "examples", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    _build_song(proj / "examples" / "demo")
    _songs_workspace(proj.parent / "songs-repo", "demo")

    res = W.resolve_song_dir_explained("demo", start=proj)
    assert res.song_dir == (proj / "examples" / "demo").resolve()
    assert res.source == W.SOURCE_MARKER_BELOW


def test_a_not_yet_created_song_still_scaffolds_into_the_lone_workspace(proj):
    """Step 5. Nothing can hold a song that doesn't exist yet, so `/song-new`
    must still land in the one workspace this session can see — the slug-aware
    rung tightens resolution without breaking creation."""
    _write_marker(proj / "examples", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    res = W.resolve_song_dir_explained("brand-new", start=proj)
    assert res.song_dir == (proj / "examples" / "brand-new").resolve()
    assert res.source == W.SOURCE_MARKER_BELOW


def test_two_holders_decline_rather_than_guess(proj):
    """Ambiguity is answered honestly, not by picking. Silently choosing one of
    two real candidates would be the same confident-wrong answer as before."""
    _songs_workspace(proj.parent / "repo-a", "demo")
    _songs_workspace(proj.parent / "repo-b", "demo")
    res = W.resolve_song_dir_explained("demo", start=proj)
    assert res.song_dir == Path("songs") / "demo"
    assert res.source == W.SOURCE_LEGACY
    assert {w.root for w in res.ambiguous_holders} == {
        (proj.parent / "repo-a").resolve(), (proj.parent / "repo-b").resolve(),
    }


def test_explain_names_both_candidate_workspaces_when_holders_are_ambiguous(proj):
    """The teaching error: name the candidates and how to choose, rather than
    resolve to a path that names nothing."""
    a = _songs_workspace(proj.parent / "repo-a", "demo")
    b = _songs_workspace(proj.parent / "repo-b", "demo")
    msg = W.explain_unresolved_song("demo", start=proj)
    assert "ambiguous" in msg
    assert str(a.resolve()) in msg
    assert str(b.resolve()) in msg
    assert ENV_SONGS_ROOT in msg
    assert "--reset" not in msg, f"must not advise a rebuild: {msg}"


def test_env_and_upward_marker_still_outrank_a_sibling_holder(proj, monkeypatch):
    """Adjacency is inference; the env var and the workspace the session is
    INSIDE are statements. Statements win."""
    _songs_workspace(proj.parent / "songs-repo", "demo")
    _write_marker(proj, '[workspace]\nlayout = "monorepo"\nsongs_root = "up"\n')
    assert resolve_song_dir("demo", start=proj) == proj.resolve() / "up" / "demo"
    monkeypatch.setenv(ENV_SONGS_ROOT, "/srv/songs")
    assert resolve_song_dir("demo", start=proj) == Path("/srv/songs") / "demo"


def test_the_sibling_scan_is_one_level_and_never_includes_the_start_dir(proj):
    """Bounded on purpose: a sideways *descent* would turn every unresolved slug
    into a crawl of the operator's whole source tree."""
    _songs_workspace(proj.parent / "deep" / "songs-repo", "demo")
    assert W.find_workspaces_beside(proj) == []
    assert resolve_song_dir("demo", start=proj) == Path("songs") / "demo"

    _write_marker(proj, '[workspace]\nlayout = "monorepo"\n')
    assert [w.root for w in W.find_workspaces_beside(proj)] == []


def test_a_sibling_holding_only_render_residue_is_not_a_holder(proj):
    """A bare `captures/` is what a misresolved render leaves behind. It must
    not vote itself into being the answer — the wreckage of this bug cannot
    impersonate the song it displaced."""
    sib = _write_marker(
        proj.parent / "songs-repo", '[workspace]\nlayout = "monorepo"\nsongs_root = "songs"\n'
    )
    (sib / "songs" / "demo" / "captures").mkdir(parents=True)
    assert resolve_song_dir("demo", start=proj) == Path("songs") / "demo"


# ---------------------------------------------------------------------------
# explain_unresolved_song — the failures a missing DB can mean
# ---------------------------------------------------------------------------


def test_explain_names_the_workspace_that_lacks_the_song(proj):
    """"Found a workspace, song isn't in it" — say which workspace, and what
    songs it does have, rather than "doesn't name a built song"."""
    ws = _write_marker(proj / "ws", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    _build_song(ws / "other-song")
    msg = W.explain_unresolved_song("missing-song", start=proj)
    assert str(ws.resolve()) in msg
    assert "other-song" in msg
    assert "no hallucinote.toml workspace marker" not in msg


def test_explain_says_no_marker_was_found_on_the_legacy_fallback(proj):
    """"No marker anywhere" is a different diagnosis from "wrong workspace",
    and the remediation differs too — say so."""
    msg = W.explain_unresolved_song("x", start=proj)
    assert "no hallucinote.toml workspace marker was found at or above" in msg
    assert str(proj.resolve()) in msg
    assert ENV_SONGS_ROOT in msg


def test_explain_names_the_ambiguous_workspaces_it_declined(proj):
    _write_marker(proj / "one", '[workspace]\nlayout = "monorepo"\n')
    _write_marker(proj / "two", '[workspace]\nlayout = "monorepo"\n')
    msg = W.explain_unresolved_song("x", start=proj)
    assert "ambiguous" in msg
    assert str((proj / "one").resolve()) in msg
    assert str((proj / "two").resolve()) in msg


def test_explain_refuses_to_advise_a_rebuild_of_a_song_built_elsewhere(proj):
    """The defect's worst symptom was advice: analysis told the operator to run
    `build.py --reset` on a song that was built and findable one directory
    away. Following it would have scaffolded a duplicate over real work.

    Staged as two workspaces that BOTH hold the song: the choice is genuinely
    ambiguous, so resolution declines (precedence step 4) — and the advice must
    still name where the song is instead of telling the operator to make
    another one. (A single holder is no longer an "elsewhere" at all; step 4
    resolves it, which is the fix this test's original one-holder staging now
    exercises directly in `test_a_holder_below_beats_a_workspace_that_merely_
    sits_below`.)"""
    one = _write_marker(proj / "one", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    two = _write_marker(proj / "two", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    _build_song(one / "demo")
    built = _build_song(two / "demo")
    msg = W.explain_unresolved_song("demo", start=proj)
    assert "--reset" not in msg, f"must not advise a rebuild: {msg}"
    assert str(built.resolve()) in msg
    assert "IS built at" in msg


def test_explain_does_advise_a_build_when_the_song_exists_nowhere(proj):
    """The honest case still gets the honest advice."""
    _write_marker(proj / "ws", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    msg = W.explain_unresolved_song("nowhere", start=proj)
    assert "--reset" in msg


def test_explain_never_claims_a_resolvable_song_is_absent(proj):
    """Called on a song that DOES resolve, it must not run the absence wording.

    The bug it forecloses: the "workspace has no song 'x'" branch listing 'x'
    among the songs that workspace does have — a sentence that contradicts
    itself inside one line. The function is documented for the failure path,
    but a caller reaching it on a stale check or a race would print nonsense,
    which is the very class of misleading error this module exists to kill.
    """
    ws = _write_marker(proj / "ws", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    song = _build_song(ws / "demo")
    (song / "demo-main.db").write_bytes(b"")

    msg = W.explain_unresolved_song("demo", start=proj)
    assert "DOES resolve" in msg, msg
    assert "has no song" not in msg, msg
    assert "holds no song" not in msg
    assert "doesn't exist yet" not in msg
    assert str(song.resolve()) in msg
    assert "demo-main.db" in msg


def test_explain_calls_a_scaffolded_but_unbuilt_song_what_it_is(proj):
    """Song dir + build.py but no DB is neither "absent" nor "built" — it is
    scaffolded, and `build.py --reset` is the right advice for exactly it."""
    ws = _write_marker(proj / "ws", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    song = _build_song(ws / "demo")  # build.py, no DB

    msg = W.explain_unresolved_song("demo", start=proj)
    assert "scaffolded, not yet built" in msg, msg
    assert "has no song" not in msg, msg
    assert "--reset" in msg
    assert str(song.resolve()) in msg


def test_sibling_list_never_includes_the_slug_being_diagnosed(proj):
    """Second, structural guard: even if a future caller reached the absence
    branch with a present slug, the "did you mean" list cannot echo it back."""
    ws = _write_marker(proj / "ws", '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n')
    _build_song(ws / "demo")
    _build_song(ws / "other")
    workspace = W.find_workspace(start=proj, descend=True)
    assert W._sibling_slugs(workspace, exclude="demo") == ["other"]


def test_a_bare_captures_dir_is_not_a_built_song(proj):
    """`songs/<slug>/captures/` is the residue a misresolved render leaves. It
    must not be reported as the song, or the wreckage of the bug impersonates
    what it displaced."""
    (proj / "songs" / "demo" / "captures").mkdir(parents=True)
    assert W.find_song_elsewhere("demo", start=proj) == []
