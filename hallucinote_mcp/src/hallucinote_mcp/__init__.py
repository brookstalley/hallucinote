"""hallucinote-mcp — unified Ableton Live MCP server.

Ten unified tools with action dispatch, designed for low-context-cost agent
interaction. See ``docs/mcp-tool-design.md`` in the parent repo for the full
architectural rationale.

``__version__`` is composed of a semver-style base (``BASE_VERSION``) plus
a short content-fingerprint of the source files that define the wire shape
(actions, handlers, dispatcher, schema, wire, remote_script). This makes
the version handshake detect SOURCE drift between the MCP server side and
the Remote Script side — the W2-5 root cause behind hours of debugging
when chunks A/B/C/D's source updates hadn't propagated into Live's User
Library. Any change to those files invalidates the fingerprint; the
handshake then surfaces a structured "Remote Script outdated, re-run
/ableton-install-mcp" error.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

BASE_VERSION = "0.1.0"

# Source files whose content defines the wire shape. Drift in any of
# these makes the two halves incompatible. Paths are relative to this
# package's root (``<pkg>/hallucinote_mcp/``). Direct-file entries and
# whole-directory entries are both supported — directories are walked
# recursively (sorted for determinism), skipping `.pyc` and `__pycache__`.
_FINGERPRINT_PATHS: tuple[str, ...] = (
    "wire.py",
    "schema.py",
    "dispatcher.py",
    "actions",
    "handlers",
    "remote_script",
)


def _compute_content_fingerprint() -> str:
    """Walk the source files that define the wire shape and return a
    short content fingerprint (12 hex chars of sha256).

    Returns ``"unknown"`` if the source tree can't be read — never
    raises, since import-time errors would break the entire package.
    A ``"unknown"`` fingerprint won't match any other side's fingerprint,
    which is the conservative behavior (the handshake will surface a
    teaching error instead of silently accepting drift).
    """
    pkg_root = Path(__file__).parent
    hasher = hashlib.sha256()
    try:
        for entry in _FINGERPRINT_PATHS:
            target = pkg_root / entry
            if target.is_file():
                _hash_file(hasher, target, entry)
            elif target.is_dir():
                for path in sorted(target.rglob("*")):
                    if not path.is_file():
                        continue
                    name = path.name
                    if name.endswith(".pyc"):
                        continue
                    if "__pycache__" in path.parts:
                        continue
                    rel = path.relative_to(pkg_root).as_posix()
                    _hash_file(hasher, path, rel)
            # If neither file nor dir: tolerate (e.g., partial install).
            # The fingerprint will still differ from the other side if
            # those files exist there.
    except OSError:
        return "unknown"
    return hasher.hexdigest()[:12]


def _hash_file(hasher: "hashlib._Hash", path: Path, rel: str) -> None:
    """Mix one file's path + content into the running hash."""
    hasher.update(rel.encode("utf-8"))
    hasher.update(b"\x00")
    try:
        hasher.update(path.read_bytes())
    except OSError:
        hasher.update(b"<unreadable>")
    hasher.update(b"\x00")


__version__ = f"{BASE_VERSION}+{_compute_content_fingerprint()}"


# Re-export the tool registry constants for convenience.
from . import schema as schema  # noqa: F401, E402  (import after __version__ to avoid cycle)


__all__ = ["__version__", "BASE_VERSION"]
