"""PSH-3K9D: skip-unchanged diff for the push ``devices`` phase.

The devices phase plans one ``set_parameter`` per stored param row,
unconditionally (``push/devices.py`` ``_emit_param_writes``). On the canonical
``/song-pick-instruments`` -> capture -> push flow every param already equals
Live, so the reconcile is ~1200 redundant TCP round-trips that stall for minutes
and read as a hang. Reported as: ``push execute`` stalls for minutes at the
``devices`` phase, re-applying ALL device params (1243 calls) on a set whose
params were just captured.

This module makes the devices phase a true diff-reconcile: the executor reads
each device's CURRENT Live parameter values once (batched
``ableton_device(action='get_parameters', detail='full')``) and this module
drops the ``set_parameter`` calls whose target already matches Live.

SAFETY LAW — **skip-on-confident-equal, keep-on-any-doubt.** A false KEEP is a
harmless redundant write (today's behavior). A false SKIP silently fails to
apply dialed intent (a wrong mix). So a call is dropped ONLY when equality is
positively proven; on ANY uncertainty — the param is absent from the read,
``min``/``max`` missing for a normalized compare, the key is unparseable, a
comparison raises — the call is KEPT. The optimization can only ever degrade to
re-writing everything, never to a wrong result.

Pure apart from the injected ``read_fn`` (the executor's ``get_parameters``
sender) and DB reads, so it unit-tests with a fake ``read_fn`` + in-memory DB.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Callable

from hallucinote.db import queries as Q

# Only ``device_parameter:`` calls are eligible to skip — the 1227-bulk. The
# planner also emits ``device_param_override:`` and ``device_chain_props:``
# (small count, trickier addressing) and ``device:`` loads; those pass straight
# through, unaffected.
#
# NOTE: this prefix is deliberately DISTINCT from ``device_param_override:`` —
# the two diverge at char 13 (``device_paramet`` vs ``device_param_o``), so a
# ``startswith`` test correctly excludes overrides. Keep them prefix-distinct.
_DEVICE_PARAM_KEY_PREFIX = "device_parameter:"


def _floats_equal(a: float, b: float, *, rel: float = 1e-6, abs_: float = 1e-6) -> bool:
    """Live parameters are 32-bit floats; compare with a small absolute +
    relative tolerance so capture/round-trip representation noise doesn't read
    as a change.

    SYN-8Q3F: deliberately TIGHTER than the pull diff engine's 1e-3
    (``pull/_core._FLOAT_EPS``) — a false EQUAL here silently skips a dialed
    write (a wrong mix); pull's loose tolerance only avoids DB churn. The
    directed invariant push-equal ⟹ pull-no-drift (per channel) is pinned by
    ``tests/unit/sync/test_diff_float_semantics.py``; change either tolerance
    only through that test. Rationale: sync-boundary-contract.md §Diff engines."""
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def param_matches_live(db_row: Any, live: dict[str, Any] | None) -> bool:
    """True only when the DB param's stored value provably equals the current
    Live value. Mirrors ``push/devices.py`` ``_param_value_kv`` priority, but
    compares values rather than choosing a wire form. Any uncertainty -> False.

    ``live`` is one entry from ``get_parameters(detail='full')``: ``name``,
    ``value`` (raw float — for enum, the index), ``value_display`` (the device's
    own ``str_for_value`` rendering at the current value), ``is_enum``,
    ``value_items``, ``min``, ``max``.
    """
    if live is None:
        return False

    db_display = (db_row["value_display"] or "").strip()

    # Enum (value_items captured) -> compare display strings. Both the
    # DB-captured and the live value_display come from the SAME str_for_value
    # curve, so an identical value yields an identical string. String equality
    # sidesteps the display-rounding / enum-index-vs-name traps with no float math.
    if db_row["value_items_json"] is not None:
        if not db_display:
            return False
        live_display = str(live.get("value_display", "")).strip()
        return bool(live_display) and db_display == live_display

    # value_raw present (the unclamped raw for a quantized continuous param) ->
    # compare against Live's raw ``value`` with tolerance.
    if db_row["value_raw"] is not None:
        live_value = live.get("value")
        if live_value is None:
            return False
        try:
            return _floats_equal(float(db_row["value_raw"]), float(live_value))
        except (TypeError, ValueError):
            return False

    # Display string present -> compare display strings (same str_for_value).
    if db_display:
        live_display = str(live.get("value_display", "")).strip()
        return bool(live_display) and db_display == live_display

    # Normalized only -> convert to a raw target via Live's min/max and compare
    # with tolerance. (The planner sends normalized as the raw ``value``, which
    # only round-trips when the param's raw range IS [0,1]; there min=0,max=1 so
    # this collapses to the same number — consistent.)
    if db_row["value_normalized"] is not None:
        lo, hi, live_value = live.get("min"), live.get("max"), live.get("value")
        if lo is None or hi is None or live_value is None:
            return False
        try:
            target_raw = float(lo) + float(db_row["value_normalized"]) * (float(hi) - float(lo))
            return _floats_equal(target_raw, float(live_value))
        except (TypeError, ValueError):
            return False

    # No stored writable form — the planner wouldn't have emitted this; nothing
    # to compare, so keep.
    return False


def _live_params_by_name(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]] | None:
    """Index a ``get_parameters`` result payload by param name, or None when the
    read failed / returned nothing (caller then keeps that device's calls)."""
    if not payload:
        return None
    params = payload.get("parameters")
    if not params:
        return None
    return {p["name"]: p for p in params if p.get("name")}


def partition_unchanged_device_params(
    calls: list[Any],
    *,
    conn: sqlite3.Connection,
    read_fn: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Split ``calls`` into ``(to_send, skipped)``.

    Only ``device_parameter:`` calls are eligible to skip; every other call
    passes straight into ``to_send``. For each eligible call, the device's
    current Live params are read once (``read_fn(node)``, cached per device id)
    and the call is dropped iff :func:`param_matches_live` proves equality.

    ``read_fn(node)`` must return the ``get_parameters`` result payload
    (``{"parameters": [...]}``) or ``None`` on any failure (it must not raise) —
    a ``None`` keeps every call for that device (skip-on-confident-equal).

    ``skipped`` entries are ``{"key", "parameter_name", "device_id"}`` for the
    summary/log. Original call order is preserved in ``to_send``.
    """
    to_send: list[Any] = []
    skipped: list[dict[str, Any]] = []
    # device_id -> {param_name: live_entry} or None (read failed); cached so a
    # device's params are read once even though its calls arrive interleaved.
    live_cache: dict[str, dict[str, dict[str, Any]] | None] = {}
    db_cache: dict[str, dict[str, Any]] = {}

    for call in calls:
        key = getattr(call, "key", "") or ""
        if not key.startswith(_DEVICE_PARAM_KEY_PREFIX):
            to_send.append(call)
            continue
        # key == "device_parameter:<device_id>:<param_name>". The device id is a
        # colon-free TEXT id; the param name (the remainder) may contain colons,
        # so split into exactly 3 and take the param name from the args anyway.
        parts = key.split(":", 2)
        param_name = call.args.get("parameter_name")
        node = call.args.get("node")
        if len(parts) < 3 or not param_name or node is None:
            to_send.append(call)  # malformed / unaddressable -> keep (safety)
            continue
        device_id = parts[1]

        if device_id not in live_cache:
            live_cache[device_id] = _live_params_by_name(read_fn(node))
            db_cache[device_id] = {
                r["name"]: r for r in Q.get_device_parameters(conn, device_id)
            }
        live_by_name = live_cache[device_id]
        if live_by_name is None:
            to_send.append(call)  # read failed -> keep all for this device
            continue

        db_row = db_cache[device_id].get(param_name)
        live_entry = live_by_name.get(param_name)
        if db_row is None or live_entry is None:
            to_send.append(call)  # can't compare -> keep
            continue

        if param_matches_live(db_row, live_entry):
            skipped.append(
                {"key": key, "parameter_name": param_name, "device_id": device_id}
            )
        else:
            to_send.append(call)

    return to_send, skipped
