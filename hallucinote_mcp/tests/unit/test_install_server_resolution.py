"""INS-3W8P — install-remote-script vendors the copy the SERVER runs, not the
invoking interpreter.

Two CLI levers make this safe and provable in a coexistence setup (installed
plugin + editable clone whose versions diverge):

  --from-package-root PATH      vendor source override (the server's package_root,
                                read from ableton://server/info)
  --require-server-version V    pre-vendor assertion: refuse without mutating if
                                the source doesn't compute V (the running server)

These tests prove the right source is used and that a divergent/typo'd source can
never be silently vendored into a handshake mismatch.
"""
from __future__ import annotations

import json

from hallucinote_mcp import compute_version_for
from hallucinote_mcp.cli import main


def _make_parseable_source(tmp_path, base="9.9.9"):
    """A minimal but *parseable* hallucinote_mcp package (compute_version_for
    returns a real version): a BASE_VERSION literal + the fingerprinted wire-shape
    files + a Control Surface stub. No excluded shapes, so verify passes cleanly.
    """
    root = tmp_path / "server_copy" / "hallucinote_mcp"
    root.mkdir(parents=True)
    (root / "__init__.py").write_text(f'BASE_VERSION = "{base}"\n', encoding="utf-8")
    for name in ("wire.py", "schema.py", "dispatcher.py"):
        (root / name).write_text(f"# {name} marker\n", encoding="utf-8")
    for d in ("actions", "handlers"):
        sub = root / d
        sub.mkdir()
        (sub / "__init__.py").write_text(f"# {d}\n", encoding="utf-8")
    rs = root / "remote_script"
    rs.mkdir()
    (rs / "__init__.py").write_text(
        "def create_instance(c):\n    return None\n", encoding="utf-8"
    )
    (rs / "server.py").write_text("# control-surface server (kept)\n", encoding="utf-8")
    return root


def _run(capsys, *argv):
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_from_package_root_vendors_the_override_source(tmp_path, capsys):
    """--from-package-root copies THAT tree, not the invoking package."""
    source = _make_parseable_source(tmp_path, base="9.9.9")
    ul = tmp_path / "User Library"
    code, payload = _run(
        capsys,
        "install-remote-script",
        "--user-library", str(ul),
        "--from-package-root", str(source),
    )
    assert code == 0 and payload["ok"] is True
    assert payload["source_root"] == str(source)
    vendored = ul / "Remote Scripts" / "Hallucinote" / "hallucinote_mcp"
    # The override's distinctive content landed (not the real package's).
    assert (vendored / "wire.py").read_text() == "# wire.py marker\n"
    assert (vendored / "remote_script" / "__init__.py").is_file()
    # vendored_version reflects the override copy.
    assert payload["vendored_version"] == compute_version_for(source)


def test_require_server_version_match_vendors_and_reports_it(tmp_path, capsys):
    """When the source computes the required server version, vendor proceeds and
    reports the on-disk version == the server's."""
    source = _make_parseable_source(tmp_path, base="9.9.9")
    expected = compute_version_for(source)
    ul = tmp_path / "User Library"
    code, payload = _run(
        capsys,
        "install-remote-script",
        "--user-library", str(ul),
        "--from-package-root", str(source),
        "--require-server-version", expected,
    )
    assert code == 0 and payload["ok"] is True
    assert payload["vendored_version"] == expected


def test_require_server_version_mismatch_refuses_without_mutating(tmp_path, capsys):
    """The rock-solid guard: a source whose version != the running server is
    REFUSED before any filesystem mutation (no half-install, no wrong vendor)."""
    source = _make_parseable_source(tmp_path, base="9.9.9")
    ul = tmp_path / "User Library"
    install_dir = ul / "Remote Scripts" / "Hallucinote"
    code, payload = _run(
        capsys,
        "install-remote-script",
        "--user-library", str(ul),
        "--from-package-root", str(source),
        "--require-server-version", "0.1.0+totally-different",
    )
    assert code == 1 and payload["ok"] is False
    assert "refusing to vendor" in payload["error"]
    assert payload["server_version"] == "0.1.0+totally-different"
    # Nothing was written — the live install is untouched.
    assert not install_dir.exists()


def test_bad_from_package_root_refuses(tmp_path, capsys):
    """A --from-package-root that isn't a parseable hallucinote_mcp package (typo,
    repo root) computes None — refuse loudly rather than vendor a non-package tree."""
    not_a_pkg = tmp_path / "not_a_package"
    not_a_pkg.mkdir()
    (not_a_pkg / "random.txt").write_text("hi\n", encoding="utf-8")
    ul = tmp_path / "User Library"
    code, payload = _run(
        capsys,
        "install-remote-script",
        "--user-library", str(ul),
        "--from-package-root", str(not_a_pkg),
    )
    assert code == 1 and payload["ok"] is False
    assert "not a parseable hallucinote_mcp package" in payload["error"]
    assert not (ul / "Remote Scripts" / "Hallucinote").exists()


def test_default_source_still_works_without_flags(tmp_path, capsys):
    """No flags → vendor the invoking package (back-compat), now also reporting
    source_root + vendored_version."""
    ul = tmp_path / "User Library"
    code, payload = _run(
        capsys, "install-remote-script", "--user-library", str(ul),
    )
    assert code == 0 and payload["ok"] is True
    assert payload["verify"]["ok"] is True
    # vendored_version is the real package's version (a non-empty string).
    assert isinstance(payload["vendored_version"], str) and payload["vendored_version"]
    assert payload["source_root"]  # the invoking package_root
