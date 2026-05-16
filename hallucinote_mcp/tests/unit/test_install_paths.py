"""install_paths — helpers used by the install / uninstall skills."""
from __future__ import annotations

import pathlib
import sys

import pytest

from hallucinote_mcp import install_paths
from hallucinote_mcp.install_paths import (
    REMOTE_SCRIPT_EXCLUDE,
    default_user_library,
    describe_install_layout,
    package_root,
    remote_script_install_dir,
    remote_script_stub_text,
)


def test_package_root_points_at_installed_package():
    root = package_root()
    assert isinstance(root, pathlib.Path)
    assert (root / "__init__.py").exists()
    assert (root / "remote_script" / "__init__.py").exists()
    assert (root / "schema.py").exists()


def test_remote_script_stub_uses_relative_import():
    """Stub must use a RELATIVE import.

    Live's loader puts the ``Remote Scripts`` directory on ``sys.path``,
    so ``Hallucinote`` is the importable package and ``hallucinote_mcp`` is
    its subpackage — *not* a top-level name. An absolute
    ``from hallucinote_mcp.remote_script import ...`` would fail in Live,
    even though it works in our test venv where ``hallucinote_mcp`` IS on
    sys.path. (Critic finding from M-0 review.)
    """
    stub = remote_script_stub_text()
    assert "from .hallucinote_mcp.remote_script import create_instance" in stub, (
        "stub must use a relative import (.hallucinote_mcp.remote_script) "
        "so it resolves in Live's loader environment"
    )
    # Must NOT contain the broken absolute form.
    assert "from hallucinote_mcp.remote_script import" not in stub.replace(
        "from .hallucinote_mcp.remote_script import", ""
    ), "stub must not use absolute hallucinote_mcp import"
    # The stub must be tiny — no further code beyond the re-export and any
    # allowed boilerplate (comments / future imports).
    for line in stub.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("from __future__"):
            continue
        if stripped.startswith("from .hallucinote_mcp.remote_script import"):
            continue
        pytest.fail(
            f"unexpected non-trivial line in stub (skill expects this file to be tiny): {line!r}"
        )


def test_default_user_library_is_platform_appropriate():
    ul = default_user_library()
    assert isinstance(ul, pathlib.Path)
    if sys.platform == "darwin":
        assert ul.parts[-3:] == ("Music", "Ableton", "User Library")
    elif sys.platform == "win32":
        assert ul.parts[-3:] == ("Documents", "Ableton", "User Library")


def test_remote_script_install_dir_is_under_user_library(tmp_path):
    target = remote_script_install_dir(tmp_path)
    assert target == tmp_path / "Remote Scripts" / "Hallucinote"


def test_describe_install_layout_lists_excludes(tmp_path):
    summary = describe_install_layout(tmp_path)
    assert "Hallucinote" in summary
    for excluded in REMOTE_SCRIPT_EXCLUDE:
        assert excluded in summary


def test_exclude_list_keeps_server_py_out_of_remote_script():
    # server.py imports FastMCP, which Live's embedded Python doesn't have —
    # this is load-bearing. The skill MUST NOT copy it.
    assert "server.py" in REMOTE_SCRIPT_EXCLUDE
    # cli pulls in serve.py which transitively imports server.py.
    assert "cli" in REMOTE_SCRIPT_EXCLUDE
