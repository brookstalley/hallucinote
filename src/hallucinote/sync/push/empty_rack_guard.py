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

This module makes the devices phase fail loud instead: before dispatching a batch
of device-phase calls, the executor lets this guard probe each rack ADDRESSED by a
pending nested write — its RUNTIME chain count, via the existing
``ableton_device(action='get_device_chains')`` handler (engine-only, no MCP wire
change) — and drop the doomed nested writes for any rack that came up empty,
emitting ONE "preset content did not load" failure. The phase then halts on that
single clear error rather than the cascade.

The candidate racks are derived from the CALLS themselves: every call that
descends into a chain (a nested-device ``path`` or a ``chain`` terminal) names a
top-level rack by its ``(parent, device_index)`` live address. Grouping by that
pair means the guard works on ANY device-phase batch — the fresh-load convergence
re-plan (where the writes first appear) AND the main dispatch of a later push
(where a still-empty but already-linked rack re-emits them). Both must be guarded:
the load link commits even on a halted push, so without the main-dispatch pass the
cascade would return on every push after the first.

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
sender) and the optional ``name_fn`` (a best-effort display-name lookup), so it
unit-tests with a fake probe + plain call objects.
"""
from __future__ import annotations

from typing import Any, Callable


def _dependent_address(node: Any) -> tuple[Any, int] | None:
    """If ``node`` addresses a chain / nested device INSIDE a rack — a write that
    NEEDS the rack's chains to exist, so it is doomed when the rack loaded empty —
    return the rack's ``(parent, device_index)`` live address; else ``None``.

    A write to the rack's OWN params (device terminal, no ``path``) addresses the
    rack device itself, which exists even on an empty load, so it is NOT a
    dependent write and yields ``None`` (left alone). ``parent`` is part of the
    address because two racks can sit at the same ``device_index`` under different
    parents.
    """
    if not isinstance(node, dict):
        return None
    device_index = node.get("device_index")
    if device_index is None:
        return None
    # Dependent iff it descends into a chain: a nested-device ``path`` OR a
    # chain-terminal address (``set_chain_property``).
    if not (node.get("path") or node.get("terminal") == "chain"):
        return None
    return node.get("parent"), device_index


def _parent_key(parent: Any) -> tuple[Any, Any]:
    """A hashable grouping key for a NodeAddr parent dict (``kind`` + ``index``;
    ``index`` is absent → ``None`` for the master parent)."""
    if not isinstance(parent, dict):
        return ("?", parent)
    return (parent.get("kind"), parent.get("index"))


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
    probe_fn: Callable[[dict[str, Any]], int | None],
    name_fn: Callable[[Any, int], str | None] | None = None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Split ``calls`` into ``(survivors, empty_rack_failures)``.

    Candidate racks are derived from ``calls``: every call whose NodeAddr descends
    into a chain (:func:`_dependent_address`) is grouped by its ``(parent,
    device_index)`` — that pair is a top-level rack's live address. For each group:

      * probe the rack's live chain count via ``probe_fn({"parent", "live_index"})``;
      * if it is confidently ``0`` the writes are doomed — drop them and record one
        failure;
      * any other result (``None`` = read failed, or ``> 0`` = populated) keeps the
        group (keep-on-doubt).

    ``name_fn(parent, device_index) -> str | None`` is an optional best-effort
    lookup of the rack's display name for the message (falls back to the address).

    Each ``empty_rack_failures`` entry is ``{"parent", "device_index",
    "display_name", "suppressed_count", "message", "hint"}`` — the executor turns
    it into one ``results`` + ``error_records`` pair so the phase halts on a single
    clear error instead of the cascade. Original call order is preserved in
    ``survivors``; ``probe_fn`` is called at most once per distinct rack.
    """
    # (parent_key) -> {"parent", "device_index", "calls"}. dict preserves first-
    # seen order so failures report in call order.
    groups: dict[tuple[Any, Any], dict[str, Any]] = {}
    for call in calls:
        addr = _dependent_address(getattr(call, "args", {}).get("node"))
        if addr is None:
            continue
        parent, device_index = addr
        gkey = _parent_key(parent)
        group = groups.get(gkey)
        if group is None:
            group = groups[gkey] = {
                "parent": parent, "device_index": device_index, "calls": [],
            }
        group["calls"].append(call)

    suppressed: set[int] = set()  # id() of dropped call objects (all live in `calls`)
    failures: list[dict[str, Any]] = []
    for group in groups.values():
        parent = group["parent"]
        device_index = group["device_index"]
        if probe_fn({"parent": parent, "live_index": device_index}) != 0:
            continue  # None (read failed) or > 0 (populated) -> keep-on-doubt
        doomed = group["calls"]
        for call in doomed:
            suppressed.add(id(call))
        name = name_fn(parent, device_index) if name_fn else None
        label = (
            f"rack {name!r} on {_describe_parent(parent)}" if name
            else f"the rack on {_describe_parent(parent)} at device index {device_index}"
        )
        failures.append({
            "parent": parent,
            "device_index": device_index,
            "display_name": name,
            "suppressed_count": len(doomed),
            "message": (
                f"preset content did not load: {label} came up with 0 chains, but "
                f"the song authored nested content for it — suppressed "
                f"{len(doomed)} dependent nested write(s) that would each fail "
                "chain-index-out-of-range. The rack preset's identity did not "
                "resolve on this machine."
            ),
            "hint": (
                "the rack preset's identity must be repaired before this song can "
                "push: re-load the preset in Live (browse to the .adg/.adv and "
                "load it onto the device), or repair the snapshot's preset "
                "identity (preset_query / preset_uri), THEN re-run execute. "
                "Re-running without fixing the preset reproduces this next push."
            ),
        })

    survivors = [c for c in calls if id(c) not in suppressed]
    return survivors, failures
