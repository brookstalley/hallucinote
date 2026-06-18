"""Server-side-only MCP surface — code that runs in the MCP server process,
never inside Live.

Actions registered from this package are declared ``runs_server_side=True``
(``schema.Action``): the dispatcher executes them in the MCP server with
``context=None`` and never sends them over TCP to the Live Remote Script
(``dispatcher.py``). They touch disk + the song DB only — e.g. ``ableton_analysis``
reads a captures dir and writes a ``MixReport``.

**Why this package exists (MCP-7F2K).** The server↔Remote-Script version
handshake fingerprints the files that are *vendored into Live AND executed in
Live* (``_FINGERPRINT_PATHS`` in ``hallucinote_mcp/__init__.py``). Server-side
code fails the second half — it is never executed in Live — so a change to it
must NOT flip the fingerprint and nag the user to re-vendor. This package is
deliberately **kept out of ``_FINGERPRINT_PATHS``** (it is not under
``handlers/`` or ``actions/``, the two directories the fingerprint walks), so
its high-churn handler bodies and its action param schemas no longer force a
re-vendor. The exclusion is path-based and import-free, like the ``node_features``
and ``resources`` exclusions.

**Isolation invariant** (enforced by ``tests/unit/test_server_side_isolation.py``):
no Live-side handler (anything under ``handlers/``) may import from here, so a
server-side change provably cannot alter Live-side behavior. Shared utilities both
sides use belong in the fingerprinted set, not here.

Importing this package registers its actions as a side effect (mirrors the
``actions`` package). ``actions/__init__.py`` imports it at boot so the one
"import the actions, get every action" invariant still holds for ``create_server``
and the ``isolated_actions`` test helper.
"""
from __future__ import annotations

# Side-effect import: triggers the ``schema.register(...)`` calls for the
# server-side actions. Order-independent (actions depend only on schema types).
from . import analysis_actions as analysis_actions  # noqa: F401


__all__ = ["analysis_actions"]
