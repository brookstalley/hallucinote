"""``hallucinote-mcp install-remote-script`` — atomic Remote Script vendor.

The install skill calls this instead of hand-authoring ``rsync``/``robocopy``: the
copy, the excludes, and the atomic swap all live in tested Python (:mod:`install_ops`).
Emits a JSON result the skill inspects; never crosses into shell glob territory.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from .. import compute_version_for
from .. import install_ops as ops
from .. import install_paths as P


def run_install_remote_script(args: list[str]) -> int:
    """Vendor the Remote Script into ``<user-library>/Remote Scripts/Hallucinote``.

    Returns a process exit code (0 ok, 1 operation failed, 2 bad usage). The JSON
    result goes to stdout for the skill to parse; usage errors go to stderr.

    INS-3W8P: by default the vendor source is the invoking interpreter's package
    (``package_root()``), but in a coexistence setup that copy can differ from the
    one the plugin launches as the server — vendoring it re-creates a handshake
    mismatch. The skill reads ``ableton://server/info`` and passes
    ``--from-package-root`` (the server's package_root, the right source) and
    ``--require-server-version`` (the server's version, asserted against the
    source BEFORE any mutation). A mismatch refuses without touching the install.
    """
    parser = argparse.ArgumentParser(
        prog="hallucinote-mcp install-remote-script",
        description="Atomically vendor the Remote Script into Live's User Library.",
    )
    parser.add_argument(
        "--user-library", required=True,
        help="Path to Live's User Library (from `preflight`'s user_library block).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Replace an existing install (the skill confirms the overwrite first).",
    )
    parser.add_argument(
        "--from-package-root", default=None,
        help=(
            "Vendor source override (INS-3W8P): the hallucinote_mcp package dir "
            "of the copy the SERVER runs, from ableton://server/info's "
            "package_root. Default: the invoking interpreter's copy."
        ),
    )
    parser.add_argument(
        "--require-server-version", default=None,
        help=(
            "Assert the vendor source computes this exact version (the running "
            "server's, from ableton://server/info) BEFORE vendoring; refuse "
            "without mutating if it differs, so a stale/divergent copy can never "
            "be silently vendored into a handshake mismatch."
        ),
    )
    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        # argparse exits 0 on --help, 2 on a usage error; preserve both.
        return exc.code if isinstance(exc.code, int) else 2

    # Resolve + validate the vendor source. A bad --from-package-root (typo,
    # repo root instead of the package dir) computes None — refuse loudly rather
    # than copy a non-package tree.
    source_root = (
        pathlib.Path(ns.from_package_root) if ns.from_package_root else P.package_root()
    )
    source_version = compute_version_for(source_root)
    if source_version is None:
        print(json.dumps({
            "ok": False,
            "error": (
                f"vendor source {source_root} is not a parseable hallucinote_mcp "
                f"package (no __init__.py / BASE_VERSION). Pass --from-package-root "
                f"pointing at the server's package_root (ableton://server/info)."
            ),
        }, indent=2))
        return 1

    # The rock-solid guard (INS-3W8P): never vendor a copy whose version doesn't
    # match the running server. Checked PRE-vendor so a refusal leaves the live
    # install untouched.
    if ns.require_server_version and source_version != ns.require_server_version:
        print(json.dumps({
            "ok": False,
            "error": (
                f"refusing to vendor: the source at {source_root} computes version "
                f"{source_version}, but the running server is "
                f"{ns.require_server_version}. Vendoring it would re-create a "
                f"server↔Remote-Script handshake mismatch. Pass --from-package-root "
                f"pointing at the server's package_root (from ableton://server/info)."
            ),
            "source_version": source_version,
            "server_version": ns.require_server_version,
        }, indent=2))
        return 1

    install_dir = P.remote_script_install_dir(ns.user_library)
    try:
        result = ops.vendor_remote_script(install_dir, source_root=source_root, force=ns.force)
    except ops.InstallError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1

    # Report the version actually ON DISK now (recomputed from the installed
    # tree) — the honest "what did we vendor" the skill confirms against the
    # server version. Equal to source_version by construction (excludes never
    # touch the fingerprinted wire-shape files).
    vendored_version = P.installed_remote_script_version(ns.user_library)
    print(json.dumps({
        "ok": True,
        "install_dir": str(result.install_dir),
        "replaced_existing": result.replaced_existing,
        "source_root": str(source_root),
        "vendored_version": vendored_version,
        "verify": {
            "ok": result.verify.ok,
            "missing": list(result.verify.missing),
            "unexpected": list(result.verify.unexpected),
        },
    }, indent=2))
    return 0


def run_install_analyzer(args: list[str]) -> int:
    """Atomically install the HallucinoteAnalyzer.amxd into the User Library."""
    parser = argparse.ArgumentParser(
        prog="hallucinote-mcp install-analyzer",
        description="Atomically copy HallucinoteAnalyzer.amxd into Live's Max Audio Effect presets.",
    )
    parser.add_argument("--user-library", required=True)
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite an existing device (the skill confirms first — it may be Max-GUI-customized).",
    )
    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 2)

    src = P.analyzer_amxd_source_path()
    dst = P.analyzer_install_target(ns.user_library)
    try:
        result = ops.install_analyzer(src, dst, force=ns.force)
    except ops.InstallError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps({
        "ok": True,
        "target": str(result.target),
        "replaced_existing": result.replaced_existing,
    }, indent=2))
    return 0


def run_uninstall_remote_script(args: list[str]) -> int:
    """Remove the vendored Remote Script directory (idempotent)."""
    parser = argparse.ArgumentParser(prog="hallucinote-mcp uninstall-remote-script")
    parser.add_argument("--user-library", required=True)
    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 2)

    install_dir = P.remote_script_install_dir(ns.user_library)
    try:
        removed = ops.remove_remote_script(install_dir)
    except OSError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "path": str(install_dir)}, indent=2))
        return 1
    print(json.dumps({"ok": True, "removed": removed, "path": str(install_dir)}, indent=2))
    return 0


def run_uninstall_analyzer(args: list[str]) -> int:
    """Remove the installed analyzer .amxd (idempotent)."""
    parser = argparse.ArgumentParser(prog="hallucinote-mcp uninstall-analyzer")
    parser.add_argument("--user-library", required=True)
    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 2)

    target = P.analyzer_install_target(ns.user_library)
    try:
        removed = ops.remove_analyzer(target)
    except OSError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "path": str(target)}, indent=2))
        return 1
    print(json.dumps({"ok": True, "removed": removed, "path": str(target)}, indent=2))
    return 0


__all__ = [
    "run_install_analyzer",
    "run_install_remote_script",
    "run_uninstall_analyzer",
    "run_uninstall_remote_script",
]
