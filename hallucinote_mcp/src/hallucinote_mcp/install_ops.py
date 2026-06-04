"""Filesystem *mutations* for the install / uninstall skills.

``install_paths.py`` is the read-only counterpart — detection and path math, no
filesystem mutation. This module *changes the disk*: it vendors the Remote Script
package into Live's User Library and writes the Control Surface entry stub
(Chunk 1), installs the analyzer device, and removes them again (Chunk 2).

The load-bearing property is **atomicity**. The Remote Script is built into a
sibling staging directory, *verified*, and only then swapped into place with
rollback — so a failure or interruption never leaves a half-installed Control
Surface that Live would try (and fail) to load. This replaces the previous
hand-authored ``rsync``/``robocopy`` shell in the install skill, which crossed
the shell boundary (a zsh glob abort once left exactly such a half-install).

Stdlib-only, like the rest of ``hallucinote_mcp``.
"""
from __future__ import annotations

import dataclasses
import fnmatch
import os
import pathlib
import shutil

from .install_paths import (
    REMOTE_SCRIPT_EXCLUDE_DIRS_ANY,
    REMOTE_SCRIPT_EXCLUDE_FILE_GLOBS_ANY,
    REMOTE_SCRIPT_EXCLUDE_TOP_LEVEL_FILES,
    package_root,
    remote_script_install_dir,
    remote_script_stub_text,
)


class InstallError(RuntimeError):
    """A filesystem install/uninstall operation could not complete safely.

    Raised instead of leaving the disk in a partial state — the live install is
    always either the complete prior version or the complete new one.
    """


@dataclasses.dataclass(frozen=True)
class VerifyResult:
    """Outcome of :func:`verify_remote_script`.

    ``missing`` lists expected files (derived from the source tree minus the
    excludes) that aren't present in the install. ``unexpected`` lists excluded
    entries that leaked into the install — the load-bearing failure that breaks
    Live's Control Surface load (e.g. the FastMCP-dependent package-root
    ``server.py``).
    """

    ok: bool
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class VendorResult:
    """Outcome of :func:`vendor_remote_script`."""

    install_dir: pathlib.Path
    replaced_existing: bool
    verify: VerifyResult


# --- internal helpers ------------------------------------------------------

def _make_ignore(source_root: pathlib.Path):
    """Build a ``shutil.copytree``-compatible ``ignore(dir, names)`` predicate.

    Reproduces rsync's anchoring in pure Python: the package-root ``server.py``
    (FastMCP-dependent — Live's embedded Python can't import it) is excluded
    **only at the source root**, so ``remote_script/server.py`` (the Control
    Surface entry point Live loads) survives. Directory names and ``*.pyc``
    globs are excluded anywhere.
    """
    root_resolved = pathlib.Path(source_root).resolve()

    def _ignore(dirpath, names):
        out: set[str] = set()
        try:
            at_root = pathlib.Path(dirpath).resolve() == root_resolved
        except OSError:
            at_root = False
        for name in names:
            if at_root and name in REMOTE_SCRIPT_EXCLUDE_TOP_LEVEL_FILES:
                out.add(name)
            elif name in REMOTE_SCRIPT_EXCLUDE_DIRS_ANY:
                out.add(name)
            elif any(fnmatch.fnmatch(name, pat) for pat in REMOTE_SCRIPT_EXCLUDE_FILE_GLOBS_ANY):
                out.add(name)
        return out

    return _ignore


def _rmtree_quiet(path: pathlib.Path) -> None:
    """Best-effort removal of a temp staging/backup path.

    ``OSError`` here means a leftover temp dir couldn't be cleaned — non-fatal
    and deliberately never allowed to mask the result of the actual operation
    (the live install is already correct by the time cleanup runs). Narrow
    exception, not a broad swallow.
    """
    try:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    except OSError:
        pass


# --- Remote Script vendoring ----------------------------------------------

def write_remote_script_stub(install_dir: pathlib.Path | str) -> pathlib.Path:
    """Write the Control Surface entry-point ``__init__.py`` into ``install_dir``.

    The stub re-exports ``create_instance`` from the vendored package next to it
    (see :func:`install_paths.remote_script_stub_text`). Returns the path written.
    """
    install_dir = pathlib.Path(install_dir)
    install_dir.mkdir(parents=True, exist_ok=True)
    stub = install_dir / "__init__.py"
    stub.write_text(remote_script_stub_text(), encoding="utf-8")
    return stub


def verify_remote_script(
    install_dir: pathlib.Path | str,
    *,
    source_root: pathlib.Path | None = None,
) -> VerifyResult:
    """Check a vendored Remote Script tree for completeness and held excludes.

    Completeness is derived from the *source* tree (``source_root``, defaulting
    to the running package) minus the excludes — so this never drifts against a
    hardcoded file list as the package evolves. Excludes-held scans the install
    for any entry that must not be present (the anchored package-root
    ``server.py``, the ``cli``/``tests``/``m4l``/``__pycache__`` dirs, ``*.pyc``).
    """
    install_dir = pathlib.Path(install_dir)
    source_root = pathlib.Path(source_root) if source_root is not None else package_root()
    pkg = install_dir / "hallucinote_mcp"
    missing: list[str] = []
    unexpected: list[str] = []

    if not (install_dir / "__init__.py").is_file():
        missing.append("__init__.py")

    if not pkg.is_dir():
        missing.append("hallucinote_mcp/")
        return VerifyResult(ok=False, missing=tuple(missing), unexpected=())

    # Completeness — every non-excluded source file must be present in the copy.
    ignore = _make_ignore(source_root)
    for src_dir, dirnames, filenames in os.walk(source_root):
        ignored = ignore(src_dir, list(dirnames) + list(filenames))
        dirnames[:] = [d for d in dirnames if d not in ignored]
        rel_dir = os.path.relpath(src_dir, source_root)
        for fn in filenames:
            if fn in ignored:
                continue
            rel = os.path.normpath(os.path.join(rel_dir, fn))
            if not (pkg / rel).is_file():
                missing.append(f"hallucinote_mcp/{rel}")

    # Excludes held — the anchored package-root server.py and any-position dirs/globs.
    if (pkg / "server.py").exists():
        unexpected.append("hallucinote_mcp/server.py")
    for dest_dir, dirnames, filenames in os.walk(pkg):
        for name in dirnames:
            if name in REMOTE_SCRIPT_EXCLUDE_DIRS_ANY:
                unexpected.append(os.path.relpath(os.path.join(dest_dir, name), install_dir))
        for fn in filenames:
            if any(fnmatch.fnmatch(fn, pat) for pat in REMOTE_SCRIPT_EXCLUDE_FILE_GLOBS_ANY):
                unexpected.append(os.path.relpath(os.path.join(dest_dir, fn), install_dir))

    missing_t = tuple(sorted(set(missing)))
    unexpected_t = tuple(sorted(set(unexpected)))
    return VerifyResult(ok=not missing_t and not unexpected_t, missing=missing_t, unexpected=unexpected_t)


def vendor_remote_script(
    install_dir: pathlib.Path | str,
    *,
    source_root: pathlib.Path | None = None,
    force: bool = False,
) -> VendorResult:
    """Atomically vendor the Remote Script into ``install_dir``.

    Stages the full tree (stub + vendored package, excludes applied in Python),
    verifies it, then swaps it into place with rollback. The live install is
    never touched until a complete, verified tree exists; a crash leaves only
    collectable ``.staging``/``.backup`` dross.

    ``force`` is required to replace an existing install — the caller (the skill)
    confirms the overwrite with the user first. Raises :class:`InstallError`
    (without mutating the live install) on an unforced overwrite or a failed
    staged verification.
    """
    install_dir = pathlib.Path(install_dir)
    source_root = pathlib.Path(source_root) if source_root is not None else package_root()

    if install_dir.exists() and not force:
        raise InstallError(
            f"{install_dir} already exists; pass force=True to replace it "
            f"(the install skill confirms the overwrite first)."
        )

    parent = install_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    staging = parent / f".{install_dir.name}.staging-{pid}"
    backup = parent / f".{install_dir.name}.backup-{pid}"
    _rmtree_quiet(staging)
    _rmtree_quiet(backup)

    # Build + verify the staged tree. A failure here cleans up the staging dir
    # and never touches the live install (nothing has moved yet).
    try:
        staging.mkdir(parents=True)
        write_remote_script_stub(staging)
        shutil.copytree(source_root, staging / "hallucinote_mcp", ignore=_make_ignore(source_root))
        result = verify_remote_script(staging, source_root=source_root)
        if not result.ok:
            raise InstallError(
                "staged Remote Script failed verification (not installed): "
                f"missing={list(result.missing)} unexpected={list(result.unexpected)}"
            )
    except BaseException:
        _rmtree_quiet(staging)
        raise

    # Atomic swap: move any existing install aside, move the staged tree in, and
    # roll back if that move fails. One code path on every platform — Windows
    # can't os.replace onto a non-empty directory, so we never try to.
    replaced = install_dir.exists()
    if replaced:
        os.replace(install_dir, backup)
    try:
        os.replace(staging, install_dir)
    except OSError:
        _rmtree_quiet(staging)
        if replaced:
            try:
                os.replace(backup, install_dir)  # rollback to the prior install
            except OSError as rollback_exc:
                raise InstallError(
                    f"Remote Script swap failed and rollback failed. Your previous "
                    f"install is preserved at {backup} — move it back to {install_dir} "
                    f"manually."
                ) from rollback_exc
        raise

    if replaced:
        _rmtree_quiet(backup)  # the old install is no longer needed
    return VendorResult(install_dir=install_dir, replaced_existing=replaced, verify=result)


__all__ = [
    "InstallError",
    "VendorResult",
    "VerifyResult",
    "vendor_remote_script",
    "verify_remote_script",
    "write_remote_script_stub",
]
