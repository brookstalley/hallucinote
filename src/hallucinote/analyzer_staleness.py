"""Detect a pre-SNP-8R4K stale Live set from its probed device chains.

The ``HallucinoteAnalyzer`` is a Max-for-Live audio tap that must be the
chain's **terminal** device to measure a surface's full output (SNP-8R4K).
A saved Live set is *stale* when authored devices were loaded **after** the
analyzer: the analyzer is no longer terminal, so per-stem captures
under-measure every device past the tap, emitting silently-wrong numbers.

This is the State-2 migration condition (design §Migration). Live has no
reorder API and the user blessed "rebuild the entire set is OK" — so we do
NOT surgically reorder or auto-rebuild; we DETECT the stale condition from
the push/compat preflight's probe data and emit operator GUIDANCE: the set
predates the analyzer-infrastructure fix; rebuild from source (push into a
fresh set).

Detection is **pure** and **position-based on the PROBE's chain order**, not
the DB — the DB is already analyzer-free (chunk 1), so only the materialized
Live set can carry a mis-ordered analyzer. It consumes the single shared
identity predicate :func:`hallucinote.analyzer_identity.is_analyzer_device`
(R1) so "what is the analyzer" is defined in exactly one place.

The "version/condition key" that keeps a clean set silent is the condition
itself: a clean or rebuilt set has no authored device after the analyzer, so
:func:`find_authored_after_analyzer` returns ``[]`` and no surface is flagged.
A set with the analyzer present-but-not-terminal is the unambiguous
pre-SNP-8R4K signature.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hallucinote.analyzer_identity import is_analyzer_device


def find_authored_after_analyzer(
    chain_devices: list[Mapping[str, Any]],
) -> list[str]:
    """Return the names of authored devices that sit AFTER the first analyzer.

    ``chain_devices`` is ONE chain's device entries in **chain order** — the
    probe shape from ``ableton_device(action='list')``
    (``{"device_index", "name", "class_name", ...}``); the list is assumed to
    be ordered as Live exposes the chain (``device_index`` ascending, which
    :func:`hallucinote.sync.push.probe._probe_live_devices_via_mcp` preserves).

    A surface is *stale* when the analyzer is present but **not terminal** —
    i.e. at least one NON-analyzer device appears at a position after the
    FIRST analyzer entry. Those trailing authored devices are exactly the ones
    a per-stem capture under-measured, so naming them is the actionable
    signal.

    Returns the offending authored device names (in chain order). An empty
    list means the surface is NOT stale, which covers every clean case:

      * analyzer present and last (terminal) — nothing after it;
      * analyzer absent entirely — nothing to be non-terminal relative to
        (the render will load it terminal at the next capture, chunk 3);
      * analyzer-only chain — no authored device to under-measure.

    Position-based, not index-arithmetic-based: we scan for the first
    analyzer, then collect non-analyzer survivors after it. Multiple analyzers
    (a legacy accumulation artifact — design cascade step 6) collapse to "the
    first one" as the measurement boundary; any authored device after that
    first tap is under-measured regardless of how many taps follow.
    """
    first_analyzer_pos: int | None = None
    for pos, device in enumerate(chain_devices):
        if is_analyzer_device(device):
            first_analyzer_pos = pos
            break
    if first_analyzer_pos is None:
        return []  # No analyzer in the chain → nothing can be non-terminal.

    offending: list[str] = []
    for device in chain_devices[first_analyzer_pos + 1:]:
        if is_analyzer_device(device):
            continue  # A trailing duplicate tap is not authored content.
        name = _device_label(device)
        offending.append(name)
    return offending


def detect_stale_analyzer_surfaces(
    probed_surfaces: dict[tuple[str, Any], list[Mapping[str, Any]]],
) -> list[str]:
    """Roll :func:`find_authored_after_analyzer` up over every probed surface.

    ``probed_surfaces`` is the per-chain ORDERED probe map the push preflight
    already assembles — keyed by ``(surface_kind, surface_id)`` (e.g.
    ``("track", 4)``, ``("return", 1)``, ``("master", None)``) with each value
    a chain's ordered device entries. This is the same shape
    ``probe_and_link`` receives as ``live_devices_by_parent`` (tracks +
    returns today). SNP-4K7M shipped the *snapshot* master device path
    (capture/replay/migrate); extending THIS push-preflight stale-set detector
    to the master needs ``probe_and_link`` to also probe the master chain into
    ``live_devices_by_parent`` — a separate, still-open piece.

    Returns a sorted list of human-readable surface labels that are stale,
    each naming the offending trailing devices, e.g.::

        "track #4 (Drums): Saturator, Limiter after the analyzer"

    An empty list means no surface is stale — a clean or rebuilt set, which
    the caller surfaces as silence. Labels are deterministic (sorted by
    surface kind then id) so the guidance message and its tests are stable.
    """
    stale: list[tuple[tuple[str, Any], list[str]]] = []
    for surface_key, chain_devices in probed_surfaces.items():
        offending = find_authored_after_analyzer(chain_devices)
        if offending:
            stale.append((surface_key, offending))

    # Sort by (kind, id-as-string) so the order is deterministic across dict
    # iteration orders — the guidance message lists surfaces stably.
    stale.sort(key=lambda item: (str(item[0][0]), str(item[0][1])))

    labels: list[str] = []
    for surface_key, offending in stale:
        kind, surface_id = surface_key
        names = ", ".join(offending)
        if surface_id is None:
            location = str(kind)
        else:
            location = f"{kind} #{surface_id}"
        labels.append(f"{location}: {names} after the analyzer")
    return labels


def _device_label(device: Mapping[str, Any] | Any) -> str:
    """Best human-readable name for a probed device entry.

    Prefer ``name`` (the probe's display field), fall back to
    ``class_display_name`` / ``class_name`` so an unnamed device still
    surfaces something actionable rather than an empty string.
    """
    for key in ("name", "class_display_name", "class_name"):
        value = device.get(key) if isinstance(device, Mapping) else None
        if value:
            return str(value)
    return "(unnamed device)"
