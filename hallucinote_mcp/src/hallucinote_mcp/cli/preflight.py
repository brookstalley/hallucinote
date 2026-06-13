"""``hallucinote-mcp preflight`` — JSON report consumed by the install/uninstall skills.

Centralizes every detection the skills need so the SKILL.md bodies only
have to invoke one command and inspect the result. Pure read-only; no
filesystem mutation. Designed to be safe to run repeatedly.
"""
from __future__ import annotations

import argparse
import json
import sys

from .. import __version__
from .. import install_paths as P


def _build_report(*, server_version_override: str | None = None) -> dict:
    """Collect every detection the install / uninstall skills consume.

    Values are JSON-encodable: ``Path``s become strings, ``None`` is preserved
    so the consumer can tell "not detected" from "empty string".

    ``server_version_override`` (INS-3W8P) is the version the install skill read
    from ``ableton://server/info`` — the version the **running** server reports.
    When given, ``matches_mcp_server`` is computed against IT (the authoritative
    reference), not the invoking interpreter's ``__version__``. Without it,
    matches falls back to the invoking copy and ``server.confirmed`` is ``false``
    so the consumer treats it as advisory (the old, possibly-lying behavior, now
    flagged honestly). See the ``server`` / ``coexistence_divergence`` keys below.
    """
    cmd_path, cmd_on_path = P.hallucinote_mcp_command()
    uv_path, uv_version = P.uv_runtime()
    pkg_root = P.package_root()
    # The invoking interpreter's version — the copy THIS CLI process imported,
    # which is NOT necessarily the copy the plugin launches as the server.
    invoking_version = __version__
    # The authoritative reference for the handshake match: the running server's
    # version when the skill confirmed it, else the invoking copy (advisory).
    server_version = server_version_override or invoking_version
    server_confirmed = server_version_override is not None
    remote_script_candidates: list[dict] = []
    analyzer_source_fp = P.analyzer_source_fingerprint()
    analyzer_candidates: list[dict] = []
    for cand in P.candidate_user_libraries():
        rs_dir = P.remote_script_install_dir(cand)
        installed = (rs_dir / "hallucinote_mcp").is_dir()
        vendored_version = (
            P.installed_remote_script_version(cand) if installed else None
        )
        remote_script_candidates.append({
            "user_library": str(cand),
            "remote_script_dir": str(rs_dir),
            "installed": installed,
            "version": vendored_version,
            "matches_mcp_server": (
                vendored_version == server_version if vendored_version else None
            ),
        })
        installed_fp = P.installed_analyzer_fingerprint(cand)
        analyzer_candidates.append({
            "user_library": str(cand),
            "target": str(P.analyzer_install_target(cand)),
            "installed": installed_fp is not None,
            "installed_fingerprint": installed_fp,
            # True/False only when the device is installed *and* we have a
            # source to compare against; None means "nothing to compare"
            # (no install, or the bundled source is unreadable).
            "matches": (
                installed_fp == analyzer_source_fp
                if (installed_fp is not None and analyzer_source_fp is not None)
                else None
            ),
        })
    return {
        # The INVOKING interpreter's package — the copy this CLI process
        # imported. INS-3W8P: in a coexistence setup (installed plugin +
        # editable clone) this can DIFFER from the copy the plugin launches as
        # the server; see `server` + `coexistence_divergence` below.
        "package": {
            "version": invoking_version,
            "root": str(pkg_root),
        },
        # The RUNNING server's identity (INS-3W8P). `version` is authoritative
        # only when `confirmed` is true (the skill passed --server-version, read
        # from ableton://server/info). When false the skill couldn't confirm it
        # (old server lacking the resource, or disconnected) and `version` mirrors
        # the invoking copy — matches_mcp_server is then advisory; the runtime
        # handshake remains the ultimate check.
        "server": {
            "version": server_version,
            "confirmed": server_confirmed,
        },
        # True ONLY when the server version is confirmed AND differs from the
        # invoking interpreter — the dev+marketplace hazard INS-3W8P fixes. When
        # true the install skill MUST vendor from the server's package_root
        # (install-remote-script --from-package-root), not the invoking copy.
        "coexistence_divergence": (
            server_confirmed and server_version != invoking_version
        ),
        "user_library": {
            "default": str(P.default_user_library()),
            "default_exists": P.default_user_library().exists(),
            "candidates": [
                {"path": str(c), "exists": c.exists()}
                for c in P.candidate_user_libraries()
            ],
        },
        "live": {
            "installed_versions": P.installed_live_versions(),
            "is_running": P.live_is_running(),
        },
        "mcp_command": {
            "path": str(cmd_path) if cmd_path else None,
            "on_path": cmd_on_path,
        },
        # uv is the one prerequisite for the plugin-bundled server launch
        # (`uv run --frozen --all-packages`, INS-7V2D). `present: false` →
        # the install skill tells the user to `brew install uv` / curl-bootstrap
        # before the bridge can start. (Probes the install-process PATH; the
        # live MCP-spawn PATH is the authoritative check — see operator-verification.)
        "uv": {
            "present": uv_path is not None,
            "path": str(uv_path) if uv_path else None,
            "version": uv_version,
        },
        # MCP/Remote Script version-match per User Library candidate.
        # Surfaces drift BEFORE the runtime handshake fires — the install
        # skill uses ``matches_mcp_server`` to suggest re-running install
        # when the vendored copy is stale (W12-D MCP/Live drift visibility).
        "remote_script": {
            "candidates": remote_script_candidates,
        },
        # M4L analyzer device drift, parity with `remote_script` above. The
        # `.amxd` is binary, so the fingerprint is a raw-byte sha256 (not the
        # text-normalizing version path). The install skill uses `matches` to
        # skip the copy + overwrite prompt when the installed device is
        # byte-identical to the bundled source (INS-4H8M).
        "analyzer": {
            "source_fingerprint": analyzer_source_fp,
            "candidates": analyzer_candidates,
        },
        "mcp_configs": {
            "local_path": str(P.mcp_config_local_path()),
            "global_path": str(P.mcp_config_global_path()),
            "containing_entry": [e.as_dict() for e in P.existing_mcp_config_files()],
            "malformed": [str(p) for p in P.malformed_mcp_config_files()],
        },
        "platform": sys.platform,
    }


def run_preflight(args: list[str]) -> int:
    """Print a JSON detection report. Exit 0 on success — failure modes live in the report."""
    parser = argparse.ArgumentParser(
        prog="hallucinote-mcp preflight",
        description=(
            "Print a JSON report of everything the install / uninstall skills "
            "need to decide: invoking-package version, the running server's "
            "version + match (with --server-version), User Library candidates, "
            "installed Live versions, whether Live is running, whether uv is "
            "present, and which MCP config files mention hallucinote-mcp."
        ),
    )
    parser.add_argument(
        "--server-version",
        default=None,
        help=(
            "The running server's version, read from ableton://server/info "
            "(INS-3W8P). When given, matches_mcp_server is computed against it "
            "(the authoritative reference) and coexistence_divergence is "
            "detected. Omit only when the server can't be queried."
        ),
    )
    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        # argparse exits 0 on --help, 2 on a usage error; preserve both.
        return exc.code if isinstance(exc.code, int) else 2

    print(json.dumps(_build_report(server_version_override=ns.server_version), indent=2))
    return 0


__all__ = ["run_preflight"]
