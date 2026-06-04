"""Tests for install_ops.py — the atomic Remote Script vendor.

These lock the load-bearing behaviors the previous shell-based install could not
guarantee: the anchored excludes (package-root server.py out, remote_script/server.py
kept; cli/tests/m4l/__pycache__/*.pyc out), and atomicity (a failed verify or swap
never mutates the live install).
"""
from __future__ import annotations

import json
import os

import pytest

from hallucinote_mcp import install_ops as ops
from hallucinote_mcp import install_paths as P
from hallucinote_mcp.cli import main


def _make_source(tmp_path):
    """A synthetic source package with every exclude/keep shape present."""
    root = tmp_path / "src_pkg"
    root.mkdir()
    # Kept top-level files.
    for name in ("__init__.py", "schema.py", "wire.py", "dispatcher.py",
                 "client.py", "install_paths.py", "device_names.py"):
        (root / name).write_text("# kept\n", encoding="utf-8")
    # Anchored exclude: package-root server.py (FastMCP-dependent) must NOT copy.
    (root / "server.py").write_text("import fastmcp\n", encoding="utf-8")
    # Kept package dirs.
    actions = root / "actions"; actions.mkdir()
    (actions / "__init__.py").write_text("# kept\n", encoding="utf-8")
    # remote_script/ is kept — including its OWN server.py (the Control Surface server).
    rs = root / "remote_script"; rs.mkdir()
    for name in ("__init__.py", "_control_surface.py", "server.py", "dispatch.py"):
        (rs / name).write_text("# kept\n", encoding="utf-8")
    # A nested kept dir with content (resources-like).
    res = root / "resources" / "guides"; res.mkdir(parents=True)
    (res / "error-recovery.md").write_text("# kept\n", encoding="utf-8")
    # Any-position excluded dirs.
    for d in ("cli", "tests", "m4l", "__pycache__"):
        sub = root / d; sub.mkdir()
        (sub / "thing.py").write_text("# excluded\n", encoding="utf-8")
    # Excluded *.pyc at root and nested.
    (root / "stale.pyc").write_text("x", encoding="utf-8")
    (rs / "nested.pyc").write_text("x", encoding="utf-8")
    return root


def _vendor(tmp_path, **kw):
    source = _make_source(tmp_path)
    install_dir = tmp_path / "User Library" / "Remote Scripts" / "Hallucinote"
    result = ops.vendor_remote_script(install_dir, source_root=source, **kw)
    return source, install_dir, result


# --- excludes (the load-bearing correctness) -------------------------------

def test_anchored_server_py_excluded_but_remote_script_server_kept(tmp_path):
    _, install_dir, _ = _vendor(tmp_path)
    pkg = install_dir / "hallucinote_mcp"
    assert not (pkg / "server.py").exists(), "package-root server.py must be excluded"
    assert (pkg / "remote_script" / "server.py").is_file(), "remote_script/server.py must be kept"


def test_any_position_dirs_and_pyc_excluded(tmp_path):
    _, install_dir, _ = _vendor(tmp_path)
    pkg = install_dir / "hallucinote_mcp"
    for d in ("cli", "tests", "m4l", "__pycache__"):
        assert not (pkg / d).exists(), f"{d}/ must be excluded"
    pyc = [os.path.join(r, f) for r, _, fs in os.walk(pkg) for f in fs if f.endswith(".pyc")]
    assert pyc == [], f"no .pyc should survive, found {pyc}"


def test_kept_files_present(tmp_path):
    _, install_dir, _ = _vendor(tmp_path)
    pkg = install_dir / "hallucinote_mcp"
    assert (install_dir / "__init__.py").is_file(), "Control Surface stub must be written"
    for rel in ("__init__.py", "schema.py", "actions/__init__.py",
                "remote_script/__init__.py", "resources/guides/error-recovery.md"):
        assert (pkg / rel).is_file(), f"{rel} should be kept"


def test_stub_text_matches_install_paths(tmp_path):
    _, install_dir, _ = _vendor(tmp_path)
    assert (install_dir / "__init__.py").read_text(encoding="utf-8") == P.remote_script_stub_text()


# --- verify -----------------------------------------------------------------

def test_vendor_result_verifies_ok(tmp_path):
    _, _, result = _vendor(tmp_path)
    assert result.verify.ok
    assert result.verify.missing == ()
    assert result.verify.unexpected == ()
    assert result.replaced_existing is False


def test_verify_detects_missing_file(tmp_path):
    source, install_dir, _ = _vendor(tmp_path)
    (install_dir / "hallucinote_mcp" / "schema.py").unlink()
    result = ops.verify_remote_script(install_dir, source_root=source)
    assert not result.ok
    assert "hallucinote_mcp/schema.py" in result.missing


def test_verify_detects_leaked_exclude(tmp_path):
    source, install_dir, _ = _vendor(tmp_path)
    # Simulate a botched copy that leaked the FastMCP-dependent server.py.
    (install_dir / "hallucinote_mcp" / "server.py").write_text("import fastmcp\n", encoding="utf-8")
    result = ops.verify_remote_script(install_dir, source_root=source)
    assert not result.ok
    assert "hallucinote_mcp/server.py" in result.unexpected


def test_verify_missing_package_dir(tmp_path):
    install_dir = tmp_path / "Hallucinote"
    install_dir.mkdir()
    (install_dir / "__init__.py").write_text("x", encoding="utf-8")
    result = ops.verify_remote_script(install_dir, source_root=_make_source(tmp_path))
    assert not result.ok
    assert "hallucinote_mcp/" in result.missing


# --- atomicity --------------------------------------------------------------

def test_unforced_overwrite_refuses_and_preserves(tmp_path):
    source, install_dir, _ = _vendor(tmp_path)
    sentinel = install_dir / "SENTINEL"
    sentinel.write_text("old", encoding="utf-8")
    with pytest.raises(ops.InstallError):
        ops.vendor_remote_script(install_dir, source_root=source, force=False)
    assert sentinel.read_text(encoding="utf-8") == "old", "existing install must be untouched"


def test_forced_overwrite_replaces_cleanly(tmp_path):
    source, install_dir, _ = _vendor(tmp_path)
    stale = install_dir / "hallucinote_mcp" / "STALE"
    stale.write_text("stale", encoding="utf-8")
    result = ops.vendor_remote_script(install_dir, source_root=source, force=True)
    assert result.replaced_existing is True
    assert result.verify.ok
    assert not stale.exists(), "stale content from the prior install must be gone (replace, not merge)"


def test_verify_failure_aborts_without_mutating_live(tmp_path, monkeypatch):
    source, install_dir, _ = _vendor(tmp_path)
    marker = install_dir / "hallucinote_mcp" / "MARKER"
    marker.write_text("live", encoding="utf-8")

    bad = ops.VerifyResult(ok=False, missing=("hallucinote_mcp/schema.py",), unexpected=())
    monkeypatch.setattr(ops, "verify_remote_script", lambda *a, **k: bad)

    with pytest.raises(ops.InstallError):
        ops.vendor_remote_script(install_dir, source_root=source, force=True)
    assert marker.read_text(encoding="utf-8") == "live", "failed staged verify must not swap the live install"
    # No staging/backup dross left behind.
    leftovers = [p.name for p in install_dir.parent.iterdir() if p.name.startswith(".Hallucinote.")]
    assert leftovers == [], f"temp dirs should be cleaned, found {leftovers}"


def test_swap_failure_rolls_back(tmp_path, monkeypatch):
    source, install_dir, _ = _vendor(tmp_path)
    marker = install_dir / "hallucinote_mcp" / "MARKER"
    marker.write_text("live", encoding="utf-8")

    real_replace = os.replace
    calls = {"into_install_dir": 0}

    def flaky_replace(src, dst, *a, **k):
        # Fail only the FIRST staging -> install_dir move (the swap); allow the
        # move-aside and the rollback (backup -> install_dir) to succeed.
        if os.fspath(dst) == os.fspath(install_dir):
            calls["into_install_dir"] += 1
            if calls["into_install_dir"] == 1:
                raise OSError("simulated swap failure")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(ops.os, "replace", flaky_replace)
    with pytest.raises(OSError):
        ops.vendor_remote_script(install_dir, source_root=source, force=True)
    assert install_dir.is_dir(), "rollback must restore the prior install"
    assert marker.read_text(encoding="utf-8") == "live", "rolled-back install must be the original"


def test_swap_and_rollback_failure_preserves_backup(tmp_path, monkeypatch):
    source, install_dir, _ = _vendor(tmp_path)
    marker = install_dir / "hallucinote_mcp" / "MARKER"
    marker.write_text("live", encoding="utf-8")

    real_replace = os.replace

    def always_fail_into_install(src, dst, *a, **k):
        if os.fspath(dst) == os.fspath(install_dir):
            raise OSError("simulated total swap failure")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(ops.os, "replace", always_fail_into_install)
    with pytest.raises(ops.InstallError) as exc:
        ops.vendor_remote_script(install_dir, source_root=source, force=True)
    # The prior install is preserved under a backup, and the error names it.
    backups = [p for p in install_dir.parent.iterdir() if p.name.startswith(".Hallucinote.backup-")]
    assert len(backups) == 1, f"backup must be preserved on rollback failure, found {backups}"
    assert (backups[0] / "hallucinote_mcp" / "MARKER").read_text(encoding="utf-8") == "live"
    assert str(backups[0]) in str(exc.value)


def test_idempotent_revendor(tmp_path):
    source, install_dir, first = _vendor(tmp_path)
    second = ops.vendor_remote_script(install_dir, source_root=source, force=True)
    assert second.verify.ok
    assert second.replaced_existing is True


# --- real package integration ----------------------------------------------

def test_vendor_real_package_verifies(tmp_path):
    """Vendor the actual running package — the strongest exclude/completeness check."""
    install_dir = tmp_path / "Remote Scripts" / "Hallucinote"
    result = ops.vendor_remote_script(install_dir)
    assert result.verify.ok, f"missing={result.verify.missing} unexpected={result.verify.unexpected}"
    pkg = install_dir / "hallucinote_mcp"
    assert not (pkg / "server.py").exists()
    assert (pkg / "remote_script" / "server.py").is_file()


def test_cli_install_remote_script_dispatch(tmp_path, capsys):
    """The CLI subcommand vendors the real package atomically and reports JSON."""
    user_library = tmp_path / "User Library"
    code = main(["install-remote-script", "--user-library", str(user_library)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["verify"]["ok"] is True
    assert payload["replaced_existing"] is False
    install_dir = user_library / "Remote Scripts" / "Hallucinote"
    assert (install_dir / "hallucinote_mcp" / "remote_script" / "__init__.py").is_file()


# --- analyzer + removals (Chunk 2) -----------------------------------------

def _analyzer_src(tmp_path):
    src = tmp_path / "src.amxd"
    src.write_bytes(b"MAXAMXD-binary-content")
    return src


def test_install_analyzer_fresh(tmp_path):
    src = _analyzer_src(tmp_path)
    dst = tmp_path / "UL" / "Presets" / "Audio Effects" / "Max Audio Effect" / "HallucinoteAnalyzer.amxd"
    result = ops.install_analyzer(src, dst)
    assert result.replaced_existing is False
    assert result.target == dst
    assert dst.read_bytes() == b"MAXAMXD-binary-content"


def test_install_analyzer_refuses_overwrite_without_force(tmp_path):
    src = _analyzer_src(tmp_path)
    dst = tmp_path / "dst.amxd"
    dst.write_bytes(b"user-customized")
    with pytest.raises(ops.InstallError):
        ops.install_analyzer(src, dst, force=False)
    assert dst.read_bytes() == b"user-customized", "existing device must be untouched"


def test_install_analyzer_force_overwrites(tmp_path):
    src = _analyzer_src(tmp_path)
    dst = tmp_path / "dst.amxd"
    dst.write_bytes(b"old")
    result = ops.install_analyzer(src, dst, force=True)
    assert result.replaced_existing is True
    assert dst.read_bytes() == b"MAXAMXD-binary-content"


def test_install_analyzer_missing_source(tmp_path):
    with pytest.raises(ops.InstallError):
        ops.install_analyzer(tmp_path / "nope.amxd", tmp_path / "dst.amxd")


def test_install_analyzer_no_partial_on_copy_failure(tmp_path, monkeypatch):
    src = _analyzer_src(tmp_path)
    dst = tmp_path / "dst.amxd"

    def boom(s, d):
        raise OSError("copy failed")

    monkeypatch.setattr(ops.shutil, "copyfile", boom)
    with pytest.raises(OSError):
        ops.install_analyzer(src, dst)
    assert not dst.exists(), "no partial .amxd left on copy failure"
    assert list(dst.parent.glob(".*.tmp-*")) == [], "temp file should be cleaned"


def test_remove_remote_script_idempotent(tmp_path):
    d = tmp_path / "Hallucinote"
    (d / "hallucinote_mcp").mkdir(parents=True)
    assert ops.remove_remote_script(d) is True
    assert not d.exists()
    assert ops.remove_remote_script(d) is False


def test_remove_analyzer_idempotent(tmp_path):
    f = tmp_path / "HallucinoteAnalyzer.amxd"
    f.write_bytes(b"x")
    assert ops.remove_analyzer(f) is True
    assert not f.exists()
    assert ops.remove_analyzer(f) is False


def test_cli_install_analyzer_real_bundled(tmp_path, capsys):
    """Installs the actual bundled .amxd — catches a missing/renamed source."""
    ul = tmp_path / "UL"
    code = main(["install-analyzer", "--user-library", str(ul)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["ok"] is True
    target = ul / "Presets" / "Audio Effects" / "Max Audio Effect" / "HallucinoteAnalyzer.amxd"
    assert target.is_file()
    assert target.read_bytes() == P.analyzer_amxd_source_path().read_bytes()


def test_cli_uninstall_remote_script_dispatch(tmp_path, capsys):
    ul = tmp_path / "UL"
    main(["install-remote-script", "--user-library", str(ul)])
    capsys.readouterr()
    code = main(["uninstall-remote-script", "--user-library", str(ul)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["ok"] is True and payload["removed"] is True
    assert not (ul / "Remote Scripts" / "Hallucinote").exists()
    main(["uninstall-remote-script", "--user-library", str(ul)])
    assert json.loads(capsys.readouterr().out)["removed"] is False
