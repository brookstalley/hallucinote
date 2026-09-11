"""Engine-side identity for the HallucinoteAnalyzer measurement device.

The ``HallucinoteAnalyzer`` is a Max-for-Live audio tap the render subsystem
injects on every measured surface — it is **measurement infrastructure, not
authored content** (SNP-8R4K). The authoring model (snapshot + DB) must behave
exactly as if it does not exist: it can never enter a snapshot, accumulate
across pull/push cycles, or shift authored device positions. This module is the
one place the engine recognizes the analyzer, consumed at every Live↔model
boundary (capture, pull, push) to exclude it by *identity* (R1).

Why a separate engine-side constant (not an import of the MCP package):

  * The reliable marker is the device's NAME == ``"HallucinoteAnalyzer"`` — the
    render stamps this on load (it is the .amxd filename surfaced as
    ``device.name``). The generic M4L class display name ``"Max Audio Effect"``
    (DB ``class_name`` / snapshot ``class_name``) is shared by ALL M4L
    audio-effect devices, so it is NOT a sufficient discriminator on its own.
  * The MCP side already defines the same constant at
    ``hallucinote_mcp.analyzer.setup.ANALYZER_DEVICE_NAME``. The dependency
    direction is MCP→engine, never the reverse — the engine (``src/hallucinote``)
    must NOT import the ``hallucinote_mcp`` package. So the engine mirrors the
    constant here. A drift-guard test
    (``tests/unit/test_analyzer_identity.py``) asserts the two are equal so they
    can never silently diverge.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ANALYZER_DEVICE_NAME = "HallucinoteAnalyzer"
"""The HallucinoteAnalyzer .amxd filename (without extension), which Live
surfaces as ``device.name`` for the loaded device. This is the engine-side
mirror of ``hallucinote_mcp.analyzer.setup.ANALYZER_DEVICE_NAME`` — the render
stamps the name on load, and the engine recognizes the analyzer by it at every
Live↔model boundary. Kept in lock-step with the MCP constant by a drift-guard
test (the engine must not import the MCP package — dependency direction is
MCP→engine)."""


def is_analyzer_device(device: Mapping[str, Any] | Any) -> bool:
    """Return True if ``device`` is the HallucinoteAnalyzer measurement tap.

    Works across the three device representations the engine sees, all of which
    carry the analyzer's distinguishing name under ``name`` or ``display_name``:

      * snapshot device dict — ``{"class": <kind>, "name": <display_name>,
        "class_name": ...}`` (``name`` is the display name)
      * DB device row (``sqlite3.Row`` or dict) — columns ``kind``,
        ``display_name``, ``class_name`` (``display_name`` is the name)
      * probed-Live device dict from pull
        (``ableton_device(action='list')``) — ``{"device_index", "name",
        "class_name", "class_display_name", ...}`` (``name`` is the display name)

    Identity is the NAME alone (``ANALYZER_DEVICE_NAME``): the render stamps it,
    and the M4L class display name (``"Max Audio Effect"``) is generic to every
    M4L audio-effect device so it cannot discriminate. We read whichever of
    ``name`` / ``display_name`` is present (preferring ``name``, the snapshot /
    probe field) and compare.

    Discriminator asymmetry (intentional): the MCP-side ``find_analyzer_index``
    additionally requires ``class_display_name == "Max Audio Effect"`` to guard
    against a live-browser preset name-collision when *loading*. At the model
    boundary the render-stamped name alone is reliable + sufficient (the class
    field isn't always captured into snapshot / DB rows), so the engine keys on
    name-only. The drift-guard test pins the shared NAME constant, NOT this
    context-specific discriminator logic — the two stay deliberately asymmetric.

    Accepts any Mapping or ``sqlite3.Row``-like object (anything indexable with
    a ``.keys()`` or supporting ``in`` / ``[]``). Returns False for anything
    that doesn't expose a name field.
    """
    name = _read_field(device, "name")
    if name is None:
        name = _read_field(device, "display_name")
    return name == ANALYZER_DEVICE_NAME


def _read_field(device: Mapping[str, Any] | Any, key: str) -> Any | None:
    """Read ``key`` from a Mapping or ``sqlite3.Row``-like device, returning
    None if absent. ``sqlite3.Row`` supports ``in`` and ``[]`` but not
    ``.get()``; plain dicts support all three. This covers both without
    swallowing unrelated errors.
    """
    if isinstance(device, Mapping):
        return device.get(key)
    # sqlite3.Row and similar: membership-test then index.
    try:
        keys = device.keys()
    except AttributeError:
        return None
    if key in keys:
        return device[key]
    return None
