"""SYN-9F4K: fail loud when a rack preset loads empty in the push devices phase.

When a top-level rack device loads with 0 chains — the preset content failed to
populate (e.g. a snapshot whose only identity is a `browser_path` that doesn't
resolve on this machine) — but the song authored nested content for it, the
planner still emits nested-chain parameter / chain-property writes addressed INTO
chains that don't exist. Each one fails ``IndexError: chain_index N out of range
[1, 0]`` — hundreds of cascade errors that bury the real cause (the empty load)
under symptom noise (the 2026-06-20 ``fresh-push-loads-rack-presets-as-empty-
shells`` report, fix #3; the primary empty-rack cause was already fixed by
SYN-RACK-PRESET-RELINK — this is the diagnostics half).

This module makes the devices phase fail loud instead: after the loads land, the
executor probes each freshly-loaded rack's RUNTIME chain count (the existing
``ableton_device(action='get_device_chains')`` handler — engine-only, no MCP wire
change) and this module drops the doomed nested writes for any rack that came up
empty, emitting ONE "preset content did not load" failure. The phase then halts
on that single clear error rather than the cascade.

SAFETY LAW — **suppress-on-confident-empty, keep-on-any-doubt.** A false
suppression+halt would block a push that would otherwise apply (re-runnable, but
still a false stop); a false keep merely degrades to today's cascade (no worse
than the status quo this improves). So a rack's writes are dropped ONLY when its
chain count is positively read as 0; a probe that fails (returns ``None``) or
reports > 0 keeps every write for that rack. The guard can only ever escalate a
genuine empty load into a clear halt, never invent one.

Why a RUNTIME chain count, not a static DB property: a re-push onto a Live set
that ALREADY holds a populated rack has chains even with no DB preset selector
(the 8 no-selector ``test_push_devices.py`` cases encode that such racks DO emit
nested writes). Whether a loaded rack is empty is a fact only the live device can
answer — so the check lives here in the executor, never in the planner (which
stays unchanged, leaving those cases untouched by construction).

Pure apart from the injected ``probe_fn`` (the executor's get_device_chains
sender), so it unit-tests with a fake probe + plain call objects.
"""
from __future__ import annotations

from typing import Any, Callable


def _addresses_into_rack(node: Any, *, parent: Any, device_index: int) -> bool:
    """True when a call's NodeAddr targets a chain / nested device INSIDE the
    rack at ``(parent, device_index)`` — a write that NEEDS the rack's chains to
    exist, so it is doomed when the rack loaded empty.

    A write to the rack's OWN params (device terminal, no ``path``) addresses the
    rack device itself, which exists even on an empty load, so it is NOT a
    dependent write and is left alone. Both ``parent`` AND ``device_index`` must
    match: two racks can sit at the same ``device_index`` under different parents.
    """
    if not isinstance(node, dict):
        return False
    if node.get("parent") != parent:
        return False
    if node.get("device_index") != device_index:
        return False
    # Dependent iff it descends into a chain: a nested-device ``path``, OR a
    # chain-terminal address (``set_chain_property``).
    return bool(node.get("path")) or node.get("terminal") == "chain"


def _describe_parent(parent: Any) -> str:
    """A short human label for a NodeAddr parent dict, for the failure message."""
    if not isinstance(parent, dict):
        return "an unknown parent"
    kind = parent.get("kind")
    if kind == "master":
        return "the master track"
    return f"{kind} index {parent.get('index')}"


def partition_doomed_nested_writes(
    calls: list[Any],
    *,
    loaded_racks: list[dict[str, Any]],
    probe_fn: Callable[[dict[str, Any]], int | None],
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Split ``calls`` into ``(survivors, empty_rack_failures)``.

    ``loaded_racks`` is one entry per top-level rack device loaded THIS pass:
    ``{"device_id", "live_index", "parent", "display_name"}`` (``parent`` is the
    NodeAddr parent dict; ``live_index`` the rack's Live ``device_index``). For
    each rack:

      * gather the calls in ``calls`` that address INTO it
        (:func:`_addresses_into_rack`);
      * if there are none, the rack has no pending nested writes — skip it (so a
        legitimately-empty preset with no authored content is never probed and
        never false-flagged);
      * otherwise probe its live chain count. If it is confidently ``0``, those
        writes are doomed — drop them and record one failure. Any other result
        (``None`` = read failed, or ``> 0`` = populated) keeps the rack's writes
        (keep-on-doubt).

    Each ``empty_rack_failures`` entry is ``{"device_id", "display_name",
    "parent", "suppressed_count", "message", "hint"}`` — the executor turns it
    into one ``results`` + ``error_records`` pair so the phase halts on a single
    clear error instead of the cascade.

    Original call order is preserved in ``survivors``.
    """
    suppressed: set[int] = set()  # id() of dropped call objects (all live in `calls`)
    failures: list[dict[str, Any]] = []

    for rack in loaded_racks:
        parent = rack["parent"]
        live_index = rack["live_index"]
        dependent = [
            c for c in calls
            if _addresses_into_rack(
                getattr(c, "args", {}).get("node"),
                parent=parent, device_index=live_index,
            )
        ]
        if not dependent:
            continue  # no authored nested content pending -> nothing to protect
        if probe_fn(rack) != 0:
            continue  # None (read failed) or > 0 (populated) -> keep-on-doubt
        for c in dependent:
            suppressed.add(id(c))
        name = rack.get("display_name") or rack["device_id"]
        failures.append({
            "device_id": rack["device_id"],
            "display_name": name,
            "parent": parent,
            "suppressed_count": len(dependent),
            "message": (
                f"preset content did not load: rack {name!r} on "
                f"{_describe_parent(parent)} came up with 0 chains, but the song "
                f"authored nested content for it — suppressed {len(dependent)} "
                "dependent nested write(s) that would each fail "
                "chain-index-out-of-range. The rack preset's identity did not "
                "resolve on this machine."
            ),
            "hint": (
                "re-load the preset in Live (browse to the .adg/.adv and load it "
                "onto the device), or repair the snapshot's preset identity "
                "(preset_query / preset_uri), then re-run execute (idempotent — "
                "applied rows skip)."
            ),
        })

    survivors = [c for c in calls if id(c) not in suppressed]
    return survivors, failures
