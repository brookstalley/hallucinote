"""``hallucinote-mcp install-remote-script`` — atomic Remote Script vendor.

The install skill calls this instead of hand-authoring ``rsync``/``robocopy``: the
copy, the excludes, and the atomic swap all live in tested Python (:mod:`install_ops`).
Emits a JSON result the skill inspects; never crosses into shell glob territory.
"""
from __future__ import annotations

import argparse
import json
import sys

from .. import install_ops as ops
from .. import install_paths as P


def run_install_remote_script(args: list[str]) -> int:
    """Vendor the Remote Script into ``<user-library>/Remote Scripts/Hallucinote``.

    Returns a process exit code (0 ok, 1 operation failed, 2 bad usage). The JSON
    result goes to stdout for the skill to parse; usage errors go to stderr.
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
    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 2)

    install_dir = P.remote_script_install_dir(ns.user_library)
    try:
        result = ops.vendor_remote_script(install_dir, force=ns.force)
    except ops.InstallError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1

    print(json.dumps({
        "ok": True,
        "install_dir": str(result.install_dir),
        "replaced_existing": result.replaced_existing,
        "verify": {
            "ok": result.verify.ok,
            "missing": list(result.verify.missing),
            "unexpected": list(result.verify.unexpected),
        },
    }, indent=2))
    return 0


__all__ = ["run_install_remote_script"]
