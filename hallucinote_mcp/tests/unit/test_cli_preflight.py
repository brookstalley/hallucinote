"""``hallucinote-mcp preflight`` — JSON report for the install / uninstall skills."""
from __future__ import annotations

import json
import sys


from hallucinote_mcp.cli import main as cli_main
from hallucinote_mcp.cli.preflight import _build_report


def test_preflight_report_has_expected_top_level_keys():
    """The skills consume these keys by name — keep this contract stable."""
    report = _build_report()
    assert set(report.keys()) == {
        "package",
        "server",                 # INS-3W8P: the running server's identity
        "coexistence_divergence",  # INS-3W8P: invoking != confirmed server
        "user_library",
        "live",
        "mcp_command",
        "uv",
        "mcp_configs",
        "remote_script",
        "analyzer",
        "platform",
    }


def test_preflight_report_uv_block_shape():
    """uv is the bundled-server prerequisite (INS-7V2D); the install skill reads
    `uv.present` to decide whether to prompt a `brew install uv`."""
    report = _build_report()
    uv = report["uv"]
    assert set(uv.keys()) == {"present", "path", "version"}
    assert isinstance(uv["present"], bool)
    assert uv["path"] is None or isinstance(uv["path"], str)
    assert uv["version"] is None or isinstance(uv["version"], str)
    # Coherence: a path is reported iff uv is present.
    assert uv["present"] == (uv["path"] is not None)


def test_preflight_report_remote_script_block_has_per_candidate_match_status():
    """The install skill uses `matches_mcp_server` to suggest re-running
    install when the vendored copy is stale (W12-D). The block carries
    one entry per User Library candidate; absent installs report
    `installed: false` + `version: null` + `matches_mcp_server: null`.

    Note: this test does NOT depend on whether the real test environment
    has a vendored install — it only asserts the shape contract.
    """
    report = _build_report()
    rs = report["remote_script"]
    assert "candidates" in rs
    assert isinstance(rs["candidates"], list)
    # One entry per User Library candidate.
    assert len(rs["candidates"]) == len(report["user_library"]["candidates"])
    for entry in rs["candidates"]:
        assert set(entry.keys()) == {
            "user_library",
            "remote_script_dir",
            "installed",
            "version",
            "matches_mcp_server",
            # The advisory half — vendored content, not just wire shape.
            "content_fingerprint",
            # Separates "no install" from "installed but unreadable"; without it
            # a blind advisory reports as benign absence.
            "content_read_error",
            "matches_vendored_content",
            "differing_paths",
            "differing_count",
        }
        assert isinstance(entry["installed"], bool)
        # version is either None or a non-empty string.
        assert entry["version"] is None or (
            isinstance(entry["version"], str) and entry["version"]
        )
        # matches_mcp_server is True/False (install present) or None (no install).
        assert entry["matches_mcp_server"] in (True, False, None)
        # An absent install must report None for both version + match.
        if not entry["installed"]:
            assert entry["version"] is None
            assert entry["matches_mcp_server"] is None


def test_preflight_report_is_json_serializable():
    report = _build_report()
    # Round-trip must succeed (no Path objects leaking through).
    json.dumps(report)


# ---------- INS-3W8P: running-server resolution ----------


def test_preflight_server_block_unconfirmed_by_default():
    """No --server-version → the server identity is UNconfirmed and mirrors the
    invoking copy; no divergence is claimed. matches_mcp_server is then advisory."""
    report = _build_report()
    assert report["server"]["confirmed"] is False
    assert report["server"]["version"] == report["package"]["version"]
    assert report["coexistence_divergence"] is False


def test_preflight_server_version_override_confirmed_no_divergence():
    """Passing the invoking version as the server version → confirmed, no divergence."""
    invoking = _build_report()["package"]["version"]
    report = _build_report(server_version_override=invoking)
    assert report["server"] == {"version": invoking, "confirmed": True}
    assert report["coexistence_divergence"] is False


def test_preflight_coexistence_divergence_detected():
    """A confirmed server version that DIFFERS from the invoking copy is the
    dev+marketplace hazard — flagged so the skill vendors from the server's copy."""
    report = _build_report(server_version_override="0.1.0+server-side-different")
    assert report["server"]["confirmed"] is True
    assert report["server"]["version"] == "0.1.0+server-side-different"
    assert report["coexistence_divergence"] is True


def test_preflight_matches_mcp_server_compares_against_confirmed_server(tmp_path, monkeypatch):
    """Defect-2 fix: matches_mcp_server is computed against the SERVER version, not
    the invoking interpreter. A vendored copy equal to the server reads True; equal
    to the invoking copy but not the server reads False."""
    from hallucinote_mcp.cli import preflight as pf

    # A candidate User Library with a (fake) vendored Remote Script present.
    vendored_pkg = tmp_path / "Remote Scripts" / "Hallucinote" / "hallucinote_mcp"
    vendored_pkg.mkdir(parents=True)
    monkeypatch.setattr(pf.P, "candidate_user_libraries", lambda: [tmp_path])
    monkeypatch.setattr(pf.P, "default_user_library", lambda: tmp_path)
    # The vendored copy's computed version is the SERVER's version.
    monkeypatch.setattr(
        pf.P, "installed_remote_script_version", lambda ul: "0.1.0+SERVER"
    )

    # Confirmed against the matching server → True.
    report = _build_report(server_version_override="0.1.0+SERVER")
    cand = report["remote_script"]["candidates"][0]
    assert cand["installed"] is True
    assert cand["version"] == "0.1.0+SERVER"
    assert cand["matches_mcp_server"] is True

    # Confirmed against a DIFFERENT server → False, even though the vendored copy
    # might equal the invoking interpreter.
    report2 = _build_report(server_version_override="0.1.0+OTHER")
    assert report2["remote_script"]["candidates"][0]["matches_mcp_server"] is False
    assert report2["coexistence_divergence"] is True


def test_cli_preflight_accepts_server_version_flag(capsys):
    """End-to-end through the dispatcher: --server-version flows into the report."""
    rc = cli_main(["preflight", "--server-version", "0.1.0+from-resource"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["server"] == {"version": "0.1.0+from-resource", "confirmed": True}


def test_preflight_report_package_block_includes_version_and_root():
    report = _build_report()
    assert "version" in report["package"]
    assert "root" in report["package"]


def test_preflight_report_user_library_candidates_have_exists_flag():
    """Skill picks the first candidate whose ``exists`` is True."""
    report = _build_report()
    for cand in report["user_library"]["candidates"]:
        assert "path" in cand
        assert "exists" in cand
        assert isinstance(cand["exists"], bool)


def test_preflight_report_live_block_uses_tri_state_running():
    """``is_running`` is True / False / None — None means "unknown, ask the user"."""
    report = _build_report()
    assert "is_running" in report["live"]
    assert report["live"]["is_running"] in (True, False, None)


def test_preflight_report_mcp_command_block_signals_on_path():
    report = _build_report()
    assert "path" in report["mcp_command"]
    assert "on_path" in report["mcp_command"]
    assert isinstance(report["mcp_command"]["on_path"], bool)


def test_preflight_report_platform_matches_runtime():
    report = _build_report()
    assert report["platform"] == sys.platform


def test_preflight_containing_entry_includes_json_pointer():
    """Schema contract: each entry has {path, json_pointer}.

    `claude mcp add` writes to a nested project scope; the json_pointer
    tells the uninstall skill where to delete the entry. A flat string
    list would silently drop that.
    """
    report = _build_report()
    for entry in report["mcp_configs"]["containing_entry"]:
        assert isinstance(entry, dict)
        assert "path" in entry
        assert "json_pointer" in entry
        assert isinstance(entry["json_pointer"], list)
        # Last segment is always the entry key itself.
        assert entry["json_pointer"][-1] == "hallucinote-mcp"


def test_cli_preflight_prints_valid_json(capsys):
    rc = cli_main(["preflight"])
    assert rc == 0
    out = capsys.readouterr().out
    # Should be a single JSON object, indented.
    parsed = json.loads(out)
    assert "platform" in parsed


def test_cli_preflight_help(capsys):
    rc = cli_main(["preflight", "--help"])
    assert rc == 0
    out = capsys.readouterr().out
    # argparse prints lowercase "usage:"; assert the behavioral contract (help
    # mentions usage + the subcommand + the INS-3W8P --server-version flag).
    assert "usage" in out.lower()
    assert "preflight" in out
    assert "--server-version" in out


def test_cli_unknown_command_still_reported(capsys):
    rc = cli_main(["nope"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown command" in err
    # Help should still list preflight.
    assert "preflight" in err


# ---------- the advisory vendored-content report ----------


def test_preflight_reports_the_source_vendored_content_fingerprint():
    """The reference a candidate's `content_fingerprint` is compared against —
    what the current source WOULD vendor, spanning the whole vendored tree
    rather than the handshake's wire-shape subset."""
    report = _build_report()
    fp = report["remote_script"]["source_content_fingerprint"]
    assert isinstance(fp, str) and len(fp) == 12


def test_preflight_advisory_is_null_when_nothing_is_installed(tmp_path, monkeypatch):
    """No Remote Script in a candidate User Library → nothing to compare, so the
    advisory reports null rather than fabricating a verdict."""
    from hallucinote_mcp.cli import preflight as pf

    monkeypatch.setattr(pf.P, "candidate_user_libraries", lambda: [tmp_path])
    monkeypatch.setattr(pf.P, "default_user_library", lambda: tmp_path)
    cand = _build_report()["remote_script"]["candidates"][0]
    assert cand["installed"] is False
    assert cand["content_fingerprint"] is None
    assert cand["matches_vendored_content"] is None
    assert cand["differing_paths"] == []
    assert cand["differing_count"] == 0


def test_preflight_advisory_flags_stale_vendored_content_without_touching_the_handshake(
    tmp_path, monkeypatch,
):
    """The whole point: an edit to vendored-but-unfingerprinted code (Live runs
    `analyzer/setup.py` during a render) reads as `matches_vendored_content:
    false` with the file named, while `matches_mcp_server` stays true."""
    import shutil

    from hallucinote_mcp import install_paths as P
    from hallucinote_mcp.cli import preflight as pf

    source = P.package_root()
    vendored_pkg = tmp_path / "Remote Scripts" / "Hallucinote" / "hallucinote_mcp"
    vendored_pkg.parent.mkdir(parents=True)
    shutil.copytree(source, vendored_pkg, ignore=P.vendor_ignore(source))

    monkeypatch.setattr(pf.P, "candidate_user_libraries", lambda: [tmp_path])
    monkeypatch.setattr(pf.P, "default_user_library", lambda: tmp_path)

    fresh = _build_report()["remote_script"]["candidates"][0]
    assert fresh["matches_vendored_content"] is True
    assert fresh["differing_paths"] == []

    stale_file = vendored_pkg / "analyzer" / "setup.py"
    stale_file.write_text(
        stale_file.read_text(encoding="utf-8") + "\n# drifted\n", encoding="utf-8",
    )

    stale = _build_report()["remote_script"]["candidates"][0]
    assert stale["matches_vendored_content"] is False
    assert stale["differing_paths"] == ["analyzer/setup.py"]
    assert stale["differing_count"] == 1
    # Non-blocking: the handshake is untouched by an advisory-only difference.
    assert stale["matches_mcp_server"] is True


def test_preflight_caps_the_named_paths_but_not_the_count(tmp_path, monkeypatch):
    """A wholly-stale install must not flood the report — the list truncates
    while the count stays exact, so the reader knows the scale."""
    from hallucinote_mcp import install_paths as P
    from hallucinote_mcp.cli import preflight as pf

    # An install carrying nothing the source ships: every source file differs.
    vendored_pkg = tmp_path / "Remote Scripts" / "Hallucinote" / "hallucinote_mcp"
    vendored_pkg.mkdir(parents=True)
    (vendored_pkg / "__init__.py").write_text("# empty\n", encoding="utf-8")

    monkeypatch.setattr(pf.P, "candidate_user_libraries", lambda: [tmp_path])
    monkeypatch.setattr(pf.P, "default_user_library", lambda: tmp_path)

    cand = _build_report()["remote_script"]["candidates"][0]
    assert cand["matches_vendored_content"] is False
    total = len(P.vendored_content_diff(P.package_root(), vendored_pkg))
    assert cand["differing_count"] == total > pf._DIFFERING_PATHS_CAP
    assert len(cand["differing_paths"]) == pf._DIFFERING_PATHS_CAP


def test_an_unreadable_installed_tree_is_not_reported_as_no_install(tmp_path, monkeypatch):
    """The advisory's whole purpose is to break a silence: a green handshake over
    a stale vendored copy. An install that exists but cannot be read makes the
    advisory blind, and collapsing that into the same `null` as "no install"
    hands the operator the benign reading of the one case that is not benign.
    """
    from hallucinote_mcp.cli import preflight as PF
    from hallucinote_mcp import install_paths as P

    lib = tmp_path / "UserLib"
    rs = P.remote_script_install_dir(lib)
    (rs / "hallucinote_mcp").mkdir(parents=True)

    monkeypatch.setattr(P, "candidate_user_libraries", lambda: [lib])
    # The tree is there; reading it fails. Never raise, but never lie either.
    monkeypatch.setattr(P, "vendored_content_fingerprint",
                        lambda pkg_root: None if pkg_root != P.package_root() else "src-fp")

    entry = next(
        c for c in PF._build_report()["remote_script"]["candidates"]
        if c["user_library"] == str(lib)
    )
    assert entry["installed"] is True
    assert entry["matches_vendored_content"] is None
    assert entry["content_read_error"] == "installed_tree_unreadable", entry


def test_a_diff_that_could_not_run_is_not_reported_as_no_files_differ(tmp_path, monkeypatch):
    """Both fingerprints read, and they disagree — so the trees DO differ. If
    the walk that names the files then fails, `differing_paths: []` beside
    `differing_count: 0` would read as "nothing differs" while
    `matches_vendored_content` says False: a report contradicting itself, and
    the half a reader believes is the concrete list.
    """
    from hallucinote_mcp.cli import preflight as PF
    from hallucinote_mcp import install_paths as P

    lib = tmp_path / "UserLib"
    rs = P.remote_script_install_dir(lib)
    (rs / "hallucinote_mcp").mkdir(parents=True)

    monkeypatch.setattr(P, "candidate_user_libraries", lambda: [lib])
    monkeypatch.setattr(P, "vendored_content_fingerprint",
                        lambda pkg_root: "src-fp" if pkg_root == P.package_root() else "other-fp")
    monkeypatch.setattr(P, "vendored_content_diff", lambda source, installed: None)

    entry = next(
        c for c in PF._build_report()["remote_script"]["candidates"]
        if c["user_library"] == str(lib)
    )
    assert entry["matches_vendored_content"] is False
    assert entry["content_read_error"] == "diff_unreadable", entry
    assert entry["differing_count"] is None, entry
    assert entry["differing_paths"] == [], entry


def test_an_unreadable_source_tree_is_named_as_the_source_side(tmp_path, monkeypatch):
    """The mirror of the installed-tree case, and it points the other way: if
    the SOURCE cannot be read, re-vendoring from it would ship whatever could
    not be read, so the operator must not be sent to `--force`."""
    from hallucinote_mcp.cli import preflight as PF
    from hallucinote_mcp import install_paths as P

    lib = tmp_path / "UserLib"
    rs = P.remote_script_install_dir(lib)
    (rs / "hallucinote_mcp").mkdir(parents=True)

    monkeypatch.setattr(P, "candidate_user_libraries", lambda: [lib])
    monkeypatch.setattr(P, "vendored_content_fingerprint",
                        lambda pkg_root: None if pkg_root == P.package_root() else "installed-fp")

    entry = next(
        c for c in PF._build_report()["remote_script"]["candidates"]
        if c["user_library"] == str(lib)
    )
    assert entry["matches_vendored_content"] is None
    assert entry["content_read_error"] == "source_tree_unreadable", entry
