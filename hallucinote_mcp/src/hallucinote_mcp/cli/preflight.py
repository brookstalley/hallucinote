"""``hallucinote-mcp preflight`` — JSON report consumed by the install/uninstall skills.

Centralizes every detection the skills need so the SKILL.md bodies only
have to invoke one command and inspect the result. Pure read-only; no
filesystem mutation. Designed to be safe to run repeatedly.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from .. import __version__
from .. import install_paths as P

# The advisory diff names files so the reader can weigh them; past a couple of
# dozen the list stops informing and the exact `differing_count` carries the
# scale instead.
_DIFFERING_PATHS_CAP = 20


def _content_reference(
    *,
    pkg_root: pathlib.Path,
    server_root_override: str | None,
    divergence: bool,
) -> tuple[pathlib.Path | None, str]:
    """Which package copy the vendored-content advisory compares against.

    The advisory answers one question — *is Live running the code the RUNNING
    SERVER ships?* — so its reference is the server's package. Normally that is
    also the copy this CLI process imported and the distinction is invisible.
    Under ``coexistence_divergence`` it is not: the plugin launches one copy and
    this shell imported another, and a fingerprint taken from the invoking copy
    then reports drift that is not real, or misses drift that is.

    ``--server-root`` closes that: it takes the running server's
    ``package_root`` (from ``ableton://server/info``), the same value
    ``install-remote-script --from-package-root`` takes, so the advisory is
    computed against the copy the vendor actually shipped from.

    Returns ``(root, authority)``. A ``None`` root **withholds** the verdict —
    ``matches_vendored_content`` stays ``null`` with the reason beside it —
    because a comparison whose reference the report itself flags as the wrong
    one is worse than no comparison: it is the shape an operator acts on.
    """
    if server_root_override is not None:
        from .. import compute_version_for

        root = pathlib.Path(server_root_override)
        # Same guard `install-remote-script` applies to `--from-package-root`:
        # a typo, or the repo root passed instead of the package dir, computes
        # no version. Withhold rather than fingerprint a non-package tree.
        if compute_version_for(root) is None:
            return None, "server_root_unreadable"
        return root, "server_package_root"
    if divergence:
        return None, "withheld_coexistence_divergence"
    return pkg_root, "invoking_package"


def _build_report(
    *,
    server_version_override: str | None = None,
    server_root_override: str | None = None,
) -> dict:
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

    ``server_root_override`` is the running server's ``package_root`` from the
    same resource read. It is the reference for the vendored-content advisory —
    see :func:`_content_reference` for why the invoking copy cannot be, and what
    the report says when neither is available.
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
    # True ONLY when the server version is confirmed AND differs from the
    # invoking interpreter — the dev+marketplace hazard INS-3W8P fixes.
    coexistence_divergence = server_confirmed and server_version != invoking_version
    remote_script_candidates: list[dict] = []
    analyzer_source_fp = P.analyzer_source_fingerprint()
    analyzer_candidates: list[dict] = []
    # Advisory: the fingerprint of the WHOLE vendored tree, not just the
    # wire-shape files the handshake guards — taken from whichever package copy
    # is the authoritative reference here, which under a divergent coexistence
    # install is NOT the invoking interpreter's.
    content_source_root, content_source_authority = _content_reference(
        pkg_root=pkg_root,
        server_root_override=server_root_override,
        divergence=coexistence_divergence,
    )
    source_content_fp = (
        P.vendored_content_fingerprint(content_source_root)
        if content_source_root is not None
        else None
    )
    # Why the reference side has no fingerprint — one cause for every candidate,
    # and "we withheld it" is not the same news as "we could not read it".
    source_side_error = (
        None if source_content_fp is not None
        else "source_not_authoritative"
        if content_source_authority == "withheld_coexistence_divergence"
        else "server_root_unreadable"
        if content_source_authority == "server_root_unreadable"
        else "source_tree_unreadable"
    )
    for cand in P.candidate_user_libraries():
        rs_dir = P.remote_script_install_dir(cand)
        vendored_pkg = rs_dir / "hallucinote_mcp"
        installed = vendored_pkg.is_dir()
        vendored_version = (
            P.installed_remote_script_version(cand) if installed else None
        )
        content_fp = (
            P.vendored_content_fingerprint(vendored_pkg) if installed else None
        )
        # `None` means "nothing to compare", and the two ways to get there are
        # NOT the same news. No install is benign. An install that exists but
        # cannot be read is the advisory failing silently on the one tree it was
        # built to watch — reported as nothing-to-compare, it reads as benign and
        # Live keeps running stale code, which is the exact silence this advisory
        # exists to end. Keep the never-raise discipline; separate the causes.
        matches_content = (
            content_fp == source_content_fp
            if (content_fp is not None and source_content_fp is not None)
            else None
        )
        content_read_error = (
            "installed_tree_unreadable" if (installed and content_fp is None)
            else source_side_error if (
                content_fp is not None and source_content_fp is None
            )
            else None
        )
        # Which files moved — only worth walking when they did. `None` back
        # means the walk could not read a tree that was readable moments ago
        # when the fingerprints were taken; it is not "no files differ", and
        # the report must not spell it that way.
        differing = (
            P.vendored_content_diff(content_source_root, vendored_pkg)
            if matches_content is False and content_source_root is not None
            else ()
        )
        if differing is None:
            content_read_error = "diff_unreadable"
        remote_script_candidates.append({
            "user_library": str(cand),
            "remote_script_dir": str(rs_dir),
            "installed": installed,
            "version": vendored_version,
            "matches_mcp_server": (
                vendored_version == server_version if vendored_version else None
            ),
            "content_fingerprint": content_fp,
            "matches_vendored_content": matches_content,
            # Non-None whenever a comparison could not be made, and it says
            # WHICH one: the fingerprint-side causes (an install that could not
            # be read, a checkout that could not be read, a server root that is
            # not a package, or a reference deliberately withheld because the
            # only copy this process can read is the wrong one) leave
            # `matches_vendored_content` null, and `diff_unreadable` leaves it
            # False with no usable file list. A consumer can tell them all from
            # benign absence, which is what a plain null could never do.
            "content_read_error": content_read_error,
            # Capped so a wholly-stale install doesn't flood the report; the
            # count stays exact so the reader knows the list was truncated.
            "differing_paths": (
                [] if differing is None
                else list(differing[:_DIFFERING_PATHS_CAP])
            ),
            # `null`, never 0, when the comparison could not run — an empty list
            # beside a 0 count reads as "the trees agree", which is the one
            # thing this branch does NOT know.
            "differing_count": None if differing is None else len(differing),
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
        # When true the install skill MUST vendor from the server's package_root
        # (install-remote-script --from-package-root), not the invoking copy —
        # and must pass that same root to preflight (--server-root) for the
        # vendored-content advisory to have an authoritative reference.
        "coexistence_divergence": coexistence_divergence,
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
            # What the current source WOULD vendor. Compare a candidate's
            # `content_fingerprint` against it: equal means Live is running the
            # code this package holds; different means it is not, even when
            # `matches_mcp_server` is true — the handshake only covers the
            # wire-shape files, and `analyzer/`, `resources/`, `client.py` and
            # the rest ship into Live outside it. Advisory only: a difference is
            # a re-vendor recommendation (`--force`), never a refusal.
            "source_content_fingerprint": source_content_fp,
            # WHICH copy that fingerprint came from, so the advisory is never
            # read against a reference the reader cannot identify.
            # `invoking_package` — this CLI's own package, correct whenever it
            # is the copy the plugin launches; `server_package_root` — the
            # running server's copy, passed with --server-root; and the two
            # no-fingerprint cases, `withheld_coexistence_divergence` (the
            # server's copy diverges and nobody pointed us at it) and
            # `server_root_unreadable` (--server-root is not a package).
            "source_content_authority": content_source_authority,
            "source_content_root": (
                str(content_source_root) if content_source_root is not None else None
            ),
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
            "version + match (with --server-version), whether the vendored "
            "tree matches the copy the server ships (with --server-root), "
            "User Library candidates, "
            "installed Live versions, whether Live is running, whether uv is "
            "present, and which MCP config files mention hallucinote-mcp."
        ),
    )
    parser.add_argument(
        "--server-root",
        default=None,
        help=(
            "The running server's package_root, read from ableton://server/info "
            "— the same value install-remote-script takes as "
            "--from-package-root. The vendored-content advisory is computed "
            "against it. Omit when the server can't be queried: the advisory "
            "then falls back to the invoking package, and withholds its verdict "
            "entirely when that copy is known to diverge from the server's."
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

    report = _build_report(
        server_version_override=ns.server_version,
        server_root_override=ns.server_root,
    )
    print(json.dumps(report, indent=2))
    return 0


__all__ = ["run_preflight"]
