"""Tests for hallucinote.paths (CLP-AUD1 references, AUD-PORTPATH persistence).

The module must stay importable without the numpy-bound
``hallucinote.audio`` package — see the stdlib-only test below.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from hallucinote.paths import (
    portable_path,
    portable_text,
    resolve_audio_path,
    resolve_portable_path,
)


def test_relative_ref_resolves_under_song_dir(tmp_path):
    resolved = resolve_audio_path(tmp_path, "assets/gtr.wav")
    assert resolved == tmp_path / "assets" / "gtr.wav"


def test_relative_ref_accepts_str_song_dir(tmp_path):
    resolved = resolve_audio_path(str(tmp_path), "assets/gtr.wav")
    assert resolved == tmp_path / "assets" / "gtr.wav"


def test_nested_posix_separators_split_into_native_parts(tmp_path):
    """The ref is POSIX by contract; each '/' segment must become a native
    path component (no literal 'a/b' single component on any platform)."""
    resolved = resolve_audio_path(tmp_path, "assets/takes/day2/gtr_take3.wav")
    assert resolved.parts[-4:] == ("assets", "takes", "day2", "gtr_take3.wav")


def test_absolute_ref_passes_through_unchanged(tmp_path):
    abs_ref = "/captures/2026/gtr.wav"
    resolved = resolve_audio_path(tmp_path, abs_ref)
    assert resolved == Path(abs_ref)
    assert str(tmp_path) not in str(resolved)


def test_resolution_is_pure_no_filesystem_dependency(tmp_path):
    """The helper resolves references, it doesn't check existence — the
    push-time existence check is CLP-AUD2 scope."""
    resolved = resolve_audio_path(tmp_path / "no-such-song", "assets/x.wav")
    assert resolved == tmp_path / "no-such-song" / "assets" / "x.wav"


# --- portable_path / resolve_portable_path (AUD-PORTPATH) ------------


def test_path_under_base_is_recorded_base_relative(tmp_path):
    song_dir = tmp_path / "songs" / "angle-of-the-light"
    captures = song_dir / "captures" / "20260807T161909Z"
    assert portable_path(captures, base=song_dir) == "captures/20260807T161909Z"


def test_path_outside_base_but_under_home_collapses_the_account_segment(
    tmp_path, monkeypatch,
):
    """The whole point: whatever else happens, the account name never
    survives into something we write down."""
    fake_home = tmp_path / "Users" / "test-account"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    stray = fake_home / "source" / "other" / "captures" / "x"

    recorded = portable_path(stray, base=tmp_path / "songs" / "some-song")

    assert recorded == "~/source/other/captures/x"
    assert "test-account" not in recorded


def test_path_outside_base_and_outside_home_stays_absolute(tmp_path, monkeypatch):
    """An external volume names no account, so there is nothing to redact —
    rewriting it would only lose information."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    recorded = portable_path("/Volumes/Audio/captures/x", base=tmp_path / "songs")
    assert recorded == "/Volumes/Audio/captures/x"


def test_no_base_still_collapses_home(tmp_path, monkeypatch):
    """base=None (a direct analyze_mix call with no analysis_dir) must not
    reopen the leak — the home fallback still applies."""
    fake_home = tmp_path / "Users" / "test-account"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    assert portable_path(fake_home / "songs" / "s", base=None) == "~/songs/s"


def test_containment_survives_filesystem_normalization(tmp_path, monkeypatch):
    """A resolved path (``/tmp`` → ``/private/tmp`` on macOS) handed against an
    unresolved base must still be recognized as inside it — the analyze handler
    resolves an explicitly-passed captures dir but not the song dir, so a purely
    textual check would silently fall through to the ``~`` form."""
    song_dir = tmp_path / "songs" / "s"
    link_parent = tmp_path / "link"
    (song_dir / "captures").mkdir(parents=True)
    link_parent.symlink_to(song_dir)

    recorded = portable_path((link_parent / "captures").resolve(), base=song_dir)

    assert recorded == "captures"


def test_recorded_forms_all_resolve_back(tmp_path, monkeypatch):
    """The read half tolerates every form the write half emits — plus the
    machine-absolute paths older reports carry."""
    fake_home = tmp_path / "Users" / "test-account"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    song_dir = tmp_path / "songs" / "s"

    assert resolve_portable_path(song_dir, "captures/x") == song_dir / "captures" / "x"
    assert resolve_portable_path(song_dir, "~/a/b") == fake_home / "a" / "b"
    assert resolve_portable_path(song_dir, "/Volumes/A/x") == Path("/Volumes/A/x")


def test_portable_text_collapses_home_inside_free_prose(tmp_path, monkeypatch):
    """The free-text companion: an error message we persist verbatim."""
    fake_home = tmp_path / "Users" / "test-account"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    collapsed = portable_text(
        f"Error opening {fake_home}/songs/s/captures/x/master.wav: System error."
    )

    assert collapsed == "Error opening ~/songs/s/captures/x/master.wav: System error."


def test_portable_text_leaves_a_degenerate_home_alone(monkeypatch):
    """A ``/`` home must not turn every separator into a tilde."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/")))
    assert portable_text("no manifest at /captures/x") == "no manifest at /captures/x"


def test_module_imports_without_heavy_deps():
    """hallucinote.paths must not pull the numpy-bound hallucinote.audio
    package (the reason it lives at the package top level). Verified in a
    fresh interpreter so this test is independent of import order."""
    code = (
        "import sys\n"
        "import hallucinote.paths\n"
        "assert 'hallucinote.audio' not in sys.modules, 'audio package loaded'\n"
        "assert 'numpy' not in sys.modules, 'numpy loaded'\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_subprocesses_resolve_this_checkout_not_the_installed_one():
    """The root conftest exports this checkout's source dirs into PYTHONPATH so
    that tests shelling out to `sys.executable -m hallucinote...` exercise the
    tree under test.

    Without it, a child resolves `hallucinote` through the editable-install
    `.pth` — the PRIMARY checkout. From a worktree that is a different, possibly
    older tree, and the symptom is brutal to diagnose: six `test_restamp_*`
    failures for a feature the worktree HAS and the primary lacks, with the code
    under test correct the whole time. This asserts the mechanism directly so a
    regression names itself instead of resurfacing as phantom failures.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]

    proc = subprocess.run(
        [sys.executable, "-c", "import hallucinote; print(hallucinote.__file__)"],
        capture_output=True, text=True, cwd=repo_root, timeout=120,
    )
    assert proc.returncode == 0, f"child failed to import hallucinote:\n{proc.stderr}"
    resolved = Path(proc.stdout.strip()).resolve()
    expected = (repo_root / "src" / "hallucinote").resolve()

    assert expected in resolved.parents or resolved.parent == expected, (
        f"a subprocess resolved `hallucinote` to {resolved}, outside this "
        f"checkout's {expected}. The root conftest's PYTHONPATH export is not "
        "reaching children, so every CLI test that shells out is exercising "
        "another tree. Check `_export_source_path_for_subprocesses` in "
        "conftest.py and that PYTHONPATH is still in os.environ."
    )
    assert os.environ.get("PYTHONPATH"), (
        "PYTHONPATH is unset in the pytest process — the conftest export was "
        "dropped; subprocess tests are now silently testing the installed tree."
    )
