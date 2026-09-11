"""Load a :class:`~hallucinote.generators.kit.Kit` from the database.

This module exists to keep ``generators/`` pure. The purity norm
(`project-preferences.md`, "Generators stay pure") earns its keep by making
musical primitives constructible and testable with no DB and no Live — and a
DB import under ``generators/`` is exactly what takes that away. ``Kit`` itself
is a frozen value object with no persistence knowledge; the query that fills it
lives here, one layer out, where reaching for ``db`` is unremarkable.

The split was made 2026-09-08 (JANITOR-2026-09 R2) after the first Norm Health
sweep measured the purity norm at one violation site: ``kit.py`` imported
``hallucinote.db.queries`` for a single call. Note the shape of the fix — the
dependency was **inverted**, not deferred. ``Kit.from_rows`` takes rows, so the
DB is the caller's problem rather than a lazily-imported secret.

``load_kit`` IS the documented authoring entry point. ``Kit.from_device``
survives as a one-major-version alias for it and is slated for removal in
2.0; nothing new should teach it.
"""
from __future__ import annotations

import sqlite3

from hallucinote.db import queries as Q
from hallucinote.generators.kit import Kit


def load_kit(
    conn: sqlite3.Connection,
    device_id: str,
    *,
    name: str | None = None,
) -> Kit:
    """Build a :class:`Kit` from the DB's ``drum_pad_mappings`` for ``device_id``.

    ``name`` defaults to a stub derived from the device_id — pass the device's
    display_name explicitly when you want warning text to be informative.
    """
    return Kit.from_rows(
        Q.get_drum_pad_mappings(conn, device_id),
        name=name,
        device_id=device_id,
    )
