"""install_paths — helpers used by the install / uninstall skills."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import textwrap

import pytest

from hallucinote_mcp import install_paths
from hallucinote_mcp.install_paths import (
    MCPConfigEntry,
    REMOTE_SCRIPT_EXCLUDE,
    candidate_user_libraries,
    default_user_library,
    describe_install_layout,
    existing_mcp_config_files,
    hallucinote_mcp_command,
    installed_live_versions,
    live_is_running,
    live_log_path,
    malformed_mcp_config_files,
    mcp_config_global_path,
    mcp_config_local_path,
    package_root,
    remote_script_install_dir,
    remote_script_stub_text,
)


# --- shared fixtures ------------------------------------------------------

@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Redirect ``pathlib.Path.home()`` and the user-profile env vars to a tmp dir.

    Most helpers in this module derive paths from the user's home, so giving
    each test an isolated home keeps assertions hermetic and lets us simulate
    Windows OneDrive layouts via env vars.
    """
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    # Clear OneDrive / USERPROFILE so tests can opt in deliberately.
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial", "USERPROFILE", "APPDATA"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


# --- package introspection (existing coverage) ----------------------------

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
    assert "from hallucinote_mcp.remote_script import" not in stub.replace(
        "from .hallucinote_mcp.remote_script import", ""
    ), "stub must not use absolute hallucinote_mcp import"
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


# --- User Library detection ----------------------------------------------

def test_default_user_library_is_platform_appropriate():
    """Live native paths on the host platform.

    This is an integration-flavored test against the real platform — the
    Windows OneDrive cases get hammered separately below with monkeypatched
    env vars.
    """
    ul = default_user_library()
    assert isinstance(ul, pathlib.Path)
    if sys.platform == "darwin":
        assert ul.parts[-3:] == ("Music", "Ableton", "User Library")
    elif sys.platform == "win32":
        # Could be either plain Documents or OneDrive/Documents — both valid.
        assert ul.parts[-3:] == ("Documents", "Ableton", "User Library")
        assert "Documents" in ul.parts


def test_candidate_user_libraries_mac_returns_single_path(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    cands = candidate_user_libraries()
    assert cands == [fake_home / "Music" / "Ableton" / "User Library"]


def test_candidate_user_libraries_linux_returns_single_path(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    cands = candidate_user_libraries()
    assert cands == [fake_home / "Ableton" / "User Library"]


def test_candidate_user_libraries_windows_plain_documents(fake_home, monkeypatch):
    """No OneDrive env vars — only plain Documents and home/OneDrive guess."""
    monkeypatch.setattr(sys, "platform", "win32")
    cands = candidate_user_libraries()
    # Should include both home/OneDrive/Documents (guess) and home/Documents.
    assert fake_home / "OneDrive" / "Documents" / "Ableton" / "User Library" in cands
    assert fake_home / "Documents" / "Ableton" / "User Library" in cands


def test_candidate_user_libraries_windows_with_onedrive_env(fake_home, monkeypatch):
    """OneDrive env var takes priority over guessed Documents location."""
    monkeypatch.setattr(sys, "platform", "win32")
    onedrive_dir = fake_home / "OneDrive_Acme"
    monkeypatch.setenv("OneDrive", str(onedrive_dir))
    cands = candidate_user_libraries()
    # OneDrive env-var path should come first.
    assert cands[0] == onedrive_dir / "Documents" / "Ableton" / "User Library"
    # Plain Documents is still a fallback candidate.
    assert fake_home / "Documents" / "Ableton" / "User Library" in cands


def test_candidate_user_libraries_windows_distinct_userprofile(fake_home, monkeypatch):
    """USERPROFILE pointing somewhere other than Path.home() is still probed.

    Rare but real on corp images where the OS shell folder is redirected.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    alt_profile = fake_home / "alt_profile"
    alt_profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(alt_profile))
    cands = candidate_user_libraries()
    assert alt_profile / "Documents" / "Ableton" / "User Library" in cands
    assert alt_profile / "OneDrive" / "Documents" / "Ableton" / "User Library" in cands


def test_candidate_user_libraries_windows_dedupes(fake_home, monkeypatch):
    """No duplicate paths when env vars happen to point at home/OneDrive."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("OneDrive", str(fake_home / "OneDrive"))
    cands = candidate_user_libraries()
    # De-dup by case-insensitive path.
    seen = {str(c).lower() for c in cands}
    assert len(seen) == len(cands), f"duplicates in candidates: {cands}"


def test_default_user_library_prefers_existing_candidate(fake_home, monkeypatch):
    """When one candidate exists on disk and another doesn't, prefer the existing one.

    Critical on Windows: a OneDrive-redirected Documents folder should win
    over the plain Documents fallback even though both are listed.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    onedrive_dir = fake_home / "OneDrive"
    monkeypatch.setenv("OneDrive", str(onedrive_dir))
    target = onedrive_dir / "Documents" / "Ableton" / "User Library"
    target.mkdir(parents=True)
    # Plain Documents path is NOT created.
    assert default_user_library() == target


def test_default_user_library_falls_back_to_first_when_none_exist(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    # Nothing on disk.
    assert default_user_library() == fake_home / "Music" / "Ableton" / "User Library"


# --- Live version + log detection ----------------------------------------

def _make_live_pref_dir(root: pathlib.Path, version: str) -> pathlib.Path:
    p = root / f"Live {version}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_installed_live_versions_mac(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    base = fake_home / "Library" / "Preferences" / "Ableton"
    _make_live_pref_dir(base, "11.3.21")
    _make_live_pref_dir(base, "12.0.5")
    (base / "NotALiveVersion").mkdir()
    assert installed_live_versions() == ["11.3.21", "12.0.5"]


def test_installed_live_versions_windows(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    appdata = fake_home / "AppData" / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    base = appdata / "Ableton"
    _make_live_pref_dir(base, "12.0.5")
    assert installed_live_versions() == ["12.0.5"]


def test_installed_live_versions_empty_when_root_missing(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    # Don't create the preferences root.
    assert installed_live_versions() == []


def test_installed_live_versions_empty_on_windows_without_appdata(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    # APPDATA env var is cleared by the fixture.
    assert installed_live_versions() == []


def test_installed_live_versions_returns_empty_on_linux(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert installed_live_versions() == []


def test_live_log_path_mac(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    path = live_log_path("12.0.5")
    assert path == fake_home / "Library" / "Preferences" / "Ableton" / "Live 12.0.5" / "Log.txt"


def test_live_log_path_returns_none_on_linux(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert live_log_path("12.0.5") is None


# --- Live process detection -----------------------------------------------

class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_live_is_running_mac_true(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _FakeCompleted(returncode=0, stdout="12345\n"),
    )
    assert live_is_running() is True


def test_live_is_running_mac_false(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _FakeCompleted(returncode=1, stdout=""),
    )
    assert live_is_running() is False


def test_live_is_running_mac_unknown_when_pgrep_missing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    def _raise(*a, **kw):
        raise FileNotFoundError("pgrep")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert live_is_running() is None


def test_live_is_running_windows_true(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    fake_out = (
        "Image Name                     PID Session Name        Session#    Mem Usage\n"
        "Ableton Live 12 Suite.exe     1234 Console                    1    500,000 K\n"
    )
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _FakeCompleted(returncode=0, stdout=fake_out),
    )
    assert live_is_running() is True


def test_live_is_running_windows_false(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _FakeCompleted(
            returncode=0,
            stdout="INFO: No tasks are running which match the specified criteria.\n",
        ),
    )
    assert live_is_running() is False


def test_live_is_running_linux_returns_none(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert live_is_running() is None


def test_live_is_running_windows_unknown_when_tasklist_missing(monkeypatch):
    """Locked-down Windows may not expose tasklist — surface as None, not False.

    A spurious False would let the install proceed while Live is open,
    which silently corrupts the copy on Windows (file locks).
    """
    monkeypatch.setattr(sys, "platform", "win32")

    def _raise(*a, **kw):
        raise FileNotFoundError("tasklist")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert live_is_running() is None


def test_live_is_running_windows_unknown_when_tasklist_errors(monkeypatch):
    """Non-zero exit from tasklist (permission denied, malformed filter) → None."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _FakeCompleted(returncode=1, stdout="", stderr="ERROR"),
    )
    assert live_is_running() is None


def test_live_is_running_mac_unknown_on_pgrep_error(monkeypatch):
    """pgrep returncode >= 2 → operational error, not 'not found'."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _FakeCompleted(returncode=2, stdout="", stderr="usage"),
    )
    assert live_is_running() is None


def test_live_is_running_handles_timeout(monkeypatch):
    """Subprocess timeout shouldn't leak as an unhandled exception."""
    monkeypatch.setattr(sys, "platform", "darwin")

    def _timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd=a[0], timeout=5)

    monkeypatch.setattr(subprocess, "run", _timeout)
    assert live_is_running() is None


# --- hallucinote-mcp command resolution -----------------------------------

def test_hallucinote_mcp_command_on_path(monkeypatch, tmp_path):
    fake = tmp_path / "hallucinote-mcp"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setattr(install_paths.shutil, "which", lambda name: str(fake))
    path, on_path = hallucinote_mcp_command()
    assert path == fake.resolve()
    assert on_path is True


def test_hallucinote_mcp_command_venv_fallback(monkeypatch, tmp_path):
    """Found in venv bin/ but not on PATH — caller must use absolute path."""
    monkeypatch.setattr(install_paths.shutil, "which", lambda name: None)
    monkeypatch.setattr(sys, "platform", "darwin")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python"
    fake_python.write_text("")
    fake_script = bin_dir / "hallucinote-mcp"
    fake_script.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "executable", str(fake_python))
    path, on_path = hallucinote_mcp_command()
    assert path == fake_script.resolve()
    assert on_path is False, "venv fallback must signal that bare-name dispatch will fail"


def test_hallucinote_mcp_command_windows_scripts_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(install_paths.shutil, "which", lambda name: None)
    monkeypatch.setattr(sys, "platform", "win32")
    venv = tmp_path / "venv"
    scripts = venv / "Scripts"
    scripts.mkdir(parents=True)
    fake_python = venv / "python.exe"
    fake_python.write_text("")
    fake_exe = scripts / "hallucinote-mcp.exe"
    fake_exe.write_text("")
    monkeypatch.setattr(sys, "executable", str(fake_python))
    path, on_path = hallucinote_mcp_command()
    assert path == fake_exe.resolve()
    assert on_path is False


def test_hallucinote_mcp_command_returns_none_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(install_paths.shutil, "which", lambda name: None)
    monkeypatch.setattr(sys, "platform", "darwin")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python"
    fake_python.write_text("")
    monkeypatch.setattr(sys, "executable", str(fake_python))
    # No hallucinote-mcp anywhere.
    path, on_path = hallucinote_mcp_command()
    assert path is None
    assert on_path is False


# --- MCP config detection -------------------------------------------------

def test_mcp_config_global_path_is_under_home(fake_home):
    assert mcp_config_global_path() == fake_home / ".claude.json"


def test_mcp_config_local_path_defaults_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert mcp_config_local_path() == tmp_path / ".mcp.json"


def test_mcp_config_local_path_respects_explicit_dir(tmp_path):
    assert mcp_config_local_path(tmp_path) == tmp_path / ".mcp.json"


def _write_json(path: pathlib.Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_existing_mcp_config_files_finds_local_entry(fake_home, tmp_path):
    local = tmp_path / ".mcp.json"
    _write_json(local, {"mcpServers": {"hallucinote-mcp": {"command": "hallucinote-mcp"}}})
    found = existing_mcp_config_files(tmp_path)
    assert found == [MCPConfigEntry(local, ("mcpServers", "hallucinote-mcp"))]


def test_existing_mcp_config_files_finds_both_when_both_present(fake_home, tmp_path):
    local = tmp_path / ".mcp.json"
    _write_json(local, {"mcpServers": {"hallucinote-mcp": {"command": "hallucinote-mcp"}}})
    glob = fake_home / ".claude.json"
    _write_json(glob, {"mcpServers": {"hallucinote-mcp": {"command": "hallucinote-mcp"}, "other": {}}})
    found = existing_mcp_config_files(tmp_path)
    paths = {e.path for e in found}
    assert local in paths
    assert glob in paths


def test_existing_mcp_config_files_finds_claude_mcp_add_project_scope(fake_home, tmp_path):
    """The default `claude mcp add` writes to ``projects.<cwd>.mcpServers``.

    A previous version of this helper only looked at the top-level
    ``mcpServers`` and silently missed these entries — uninstall would
    report "no existing entries" while leaving the registration in place.
    """
    glob = fake_home / ".claude.json"
    _write_json(glob, {
        "projects": {
            str(tmp_path): {
                "mcpServers": {
                    "hallucinote-mcp": {"command": "hallucinote-mcp", "args": ["serve"]}
                }
            }
        }
    })
    found = existing_mcp_config_files(tmp_path)
    assert found == [
        MCPConfigEntry(
            glob,
            ("projects", str(tmp_path), "mcpServers", "hallucinote-mcp"),
        )
    ]


def test_existing_mcp_config_files_ignores_other_projects_entries(fake_home, tmp_path):
    """A project-scoped entry under a DIFFERENT cwd is not ours to touch."""
    glob = fake_home / ".claude.json"
    other_project = tmp_path / "other_project"
    _write_json(glob, {
        "projects": {
            str(other_project): {
                "mcpServers": {"hallucinote-mcp": {"command": "hallucinote-mcp"}}
            }
        }
    })
    # Looking from tmp_path — the other project's entry must not appear.
    assert existing_mcp_config_files(tmp_path) == []


def test_existing_mcp_config_files_combines_top_level_and_project_scope(fake_home, tmp_path):
    """Both scopes populated → both reported, distinguished by json_pointer."""
    glob = fake_home / ".claude.json"
    _write_json(glob, {
        "mcpServers": {"hallucinote-mcp": {"command": "hallucinote-mcp"}},
        "projects": {
            str(tmp_path): {
                "mcpServers": {"hallucinote-mcp": {"command": "hallucinote-mcp"}}
            }
        },
    })
    found = existing_mcp_config_files(tmp_path)
    pointers = {e.json_pointer for e in found}
    assert ("mcpServers", "hallucinote-mcp") in pointers
    assert ("projects", str(tmp_path), "mcpServers", "hallucinote-mcp") in pointers


def test_existing_mcp_config_files_ignores_unrelated_entries(fake_home, tmp_path):
    local = tmp_path / ".mcp.json"
    _write_json(local, {"mcpServers": {"other-server": {}}})
    assert existing_mcp_config_files(tmp_path) == []


def test_existing_mcp_config_files_skips_malformed(fake_home, tmp_path):
    """A malformed config should not be treated as 'contains the entry' —
    overwriting it could destroy user state. Use malformed_mcp_config_files
    to surface it separately.
    """
    local = tmp_path / ".mcp.json"
    local.write_text("{ this is not valid json", encoding="utf-8")
    assert existing_mcp_config_files(tmp_path) == []


def test_mcp_config_entry_as_dict_round_trip(tmp_path):
    """as_dict() output is the preflight-report shape — must stay JSON-safe."""
    entry = MCPConfigEntry(tmp_path / ".mcp.json", ("mcpServers", "hallucinote-mcp"))
    d = entry.as_dict()
    assert d == {
        "path": str(tmp_path / ".mcp.json"),
        "json_pointer": ["mcpServers", "hallucinote-mcp"],
    }
    json.dumps(d)  # Must serialize.


def test_malformed_mcp_config_files_returns_only_unparseable(fake_home, tmp_path):
    good = tmp_path / ".mcp.json"
    _write_json(good, {"mcpServers": {}})
    glob = fake_home / ".claude.json"
    glob.write_text(textwrap.dedent("""\
        {
          "mcpServers": {
            "hallucinote-mcp": {,  // hand-edited, trailing comma
          }
        }
        """), encoding="utf-8")
    assert malformed_mcp_config_files(tmp_path) == [glob]


def test_malformed_mcp_config_files_empty_when_all_valid(fake_home, tmp_path):
    _write_json(tmp_path / ".mcp.json", {"mcpServers": {}})
    _write_json(fake_home / ".claude.json", {"mcpServers": {}})
    assert malformed_mcp_config_files(tmp_path) == []


def test_existing_finds_valid_global_when_local_is_malformed(fake_home, tmp_path):
    """Mixed state — local malformed, global has the entry.

    The uninstall skill must still detect and edit the global. If
    `existing_mcp_config_files` short-circuited on the local parse failure,
    the global would silently stay registered.
    """
    (tmp_path / ".mcp.json").write_text("{ broken json", encoding="utf-8")
    glob = fake_home / ".claude.json"
    _write_json(glob, {"mcpServers": {"hallucinote-mcp": {"command": "hallucinote-mcp"}}})
    found = existing_mcp_config_files(tmp_path)
    assert found == [MCPConfigEntry(glob, ("mcpServers", "hallucinote-mcp"))]
    assert malformed_mcp_config_files(tmp_path) == [tmp_path / ".mcp.json"]
