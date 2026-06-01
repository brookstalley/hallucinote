"""Loaded-vs-disk version probe for the analysis pipeline.

The MCP ``ableton_analysis`` handler runs inside a long-lived server
subprocess that caches the imported ``hallucinote.audio`` modules. After
the analysis source is edited on disk, that subprocess keeps serving the
*old* code until ``/mcp`` respawns it — and the response gives no signal
that the loaded code is stale. The capture-side ``analyzer_signature``
(``hallucinote-analyzer-v1``, baked into the render manifest) describes the
M4L capture device, not this pipeline, so it never moves when analysis code
changes and can't surface the staleness.

This module closes that gap with a *content-derived* signature rather than a
hand-bumped version string. A version string fails at exactly the failure
mode we care about — forgetting to bump it is indistinguishable from
forgetting to ``/mcp`` — so we hash the package source instead:

  - ``_LOADED_SIGNATURE`` is computed once, at import. Because Python compiles
    the package from these files moments before this module body runs, the
    import-time hash captures the code the subprocess is actually *running*.
    It is then frozen for the life of the process.
  - ``disk_signature()`` re-hashes the same files on each call, reflecting
    what is on disk *now*.
  - ``is_stale()`` compares the two: when they differ, the loaded code no
    longer matches disk — the report was produced by code that has since been
    edited, and the server should be respawned (``/mcp``).

Hashing is scoped to the ``hallucinote/audio/`` package directory (the
analysis pipeline). The package is flat, so a non-recursive ``*.py`` glob
covers every module; ``__pycache__`` is excluded by the glob.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

# Marker hashed in place of a file's bytes when it can't be read (e.g. a file
# vanished mid-walk). Folding the failure into the digest deterministically
# keeps this probe from ever raising into the analysis path, while still
# changing the signature — a disappeared module *is* a code change.
_UNREADABLE = b"<unreadable>"


def _package_dir() -> Path:
    """The ``hallucinote/audio/`` directory — the analysis pipeline source."""
    return Path(__file__).resolve().parent


def _read_py(path: Path) -> bytes:
    """File bytes, or ``_UNREADABLE`` if the read fails."""
    try:
        return path.read_bytes()
    except OSError:
        return _UNREADABLE


def _hash_dir(directory: Path) -> str:
    """Short content hash over the ``.py`` files directly in ``directory``.

    Order-stable (files sorted by name) and includes each file's name in the
    digest so a rename changes the result. Returns the first 12 hex chars of
    the SHA-256 — enough to make collisions implausible while staying glanceable
    in a tool response.
    """
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.py"), key=lambda p: p.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_read_py(path))
        digest.update(b"\0")
    return digest.hexdigest()[:12]


# Frozen at import — see module docstring. This is the signature of the code
# the running process actually loaded.
_LOADED_SIGNATURE = _hash_dir(_package_dir())


def loaded_signature() -> str:
    """Signature of the analysis code loaded into this process (frozen at import)."""
    return _LOADED_SIGNATURE


def disk_signature() -> str:
    """Signature of the analysis source currently on disk (recomputed per call)."""
    return _hash_dir(_package_dir())


def is_stale() -> bool:
    """True when the loaded analysis code differs from what is on disk.

    A True result means a saved/served report was produced by code that has
    since been edited; respawn the MCP server (``/mcp``) to pick up the change.
    """
    return loaded_signature() != disk_signature()


__all__ = ["loaded_signature", "disk_signature", "is_stale"]
