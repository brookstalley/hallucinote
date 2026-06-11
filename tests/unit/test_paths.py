"""Tests for hallucinote.paths.resolve_audio_path (CLP-AUD1).

The module must stay importable without the numpy-bound
``hallucinote.audio`` package — see the stdlib-only test below.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from hallucinote.paths import resolve_audio_path


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
