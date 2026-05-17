"""Action registration.

Importing this package as a side effect registers all actions on every
unified tool. The server's ``create_server`` does this exactly once at boot;
tests use the ``isolated_registry`` fixture to avoid cross-contamination.

The split into one module per tool keeps each domain navigable and lets a
chunk land its actions without touching the others.
"""
from __future__ import annotations

# Each import below triggers the module's ``schema.register(...)`` calls as a
# side effect. Order doesn't matter — actions only depend on the schema types,
# not on each other.
from . import session as session  # noqa: F401
from . import track as track  # noqa: F401
from . import return_ as return_  # noqa: F401
from . import clip as clip  # noqa: F401
from . import note as note  # noqa: F401
from . import device as device  # noqa: F401
from . import automation as automation  # noqa: F401
from . import arrangement as arrangement  # noqa: F401
from . import scene as scene  # noqa: F401
from . import browser as browser  # noqa: F401


__all__ = [
    "session", "track", "return_", "clip", "note",
    "device", "automation", "arrangement", "scene", "browser",
]
