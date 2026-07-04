"""Device-chain pull: top-level chains, nested rack chains, and per-device
parameter values — planners + apply.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from hallucinote.analyzer_identity import is_analyzer_device
from hallucinote.capture import (
    RACK_CLASS_NAMES,
    chain_authored_props,
    normalize_param_value,
    param_needs_raw_channel,
)

from hallucinote.db import mutations as M, queries as Q

from ._core import (
    PullCall,
    PullPlan,
    ApplyResult,
    _normalized_values_match,
    _raw_values_match,
)


def _iter_linked_parents(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    plan: PullPlan,
    unlinked_warn,
):
    """Yield ``(parent_kind, parent_at, parent_row)`` for each linked track
    (``master`` skipped) then each linked return — the link-resolution pass
    shared by every ``plan_pull_*`` planner.

    ``parent_kind`` is ``"track"`` or ``"return"``; ``parent_at`` is the 1-based
    Ableton index from the session link; ``parent_row`` is the DB row. For a
    parent not linked in this session, ``unlinked_warn(parent_kind, parent_row)``
    is consulted: a returned string is appended via ``plan.warn`` and the parent
    skipped; ``None`` skips it silently. The warning text and the callers'
    ``any_emitted`` bookkeeping stay in the planners, where they legitimately
    differ (some warn on an unlinked parent, some don't).
    """
    for t in Q.get_tracks_for_song(conn, song_id):
        if t["kind"] == "master":
            continue
        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=t["id"],
        )
        if track_at is None:
            msg = unlinked_warn("track", t)
            if msg:
                plan.warn(msg)
            continue
        yield "track", track_at, t

    for r in Q.get_returns_for_song(conn, song_id):
        return_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="return", db_id=r["id"],
        )
        if return_at is None:
            msg = unlinked_warn("return", r)
            if msg:
                plan.warn(msg)
            continue
        yield "return", return_at, r


def _iter_linked_top_level_devices(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    plan: PullPlan,
    unlinked_warn,
):
    """Yield ``(parent_kind, parent_at, parent_row, device_row)`` for every
    device on the top-level chain (``position == 0``) of each linked parent.

    Layered on ``_iter_linked_parents`` (same link resolution, master-skip, and
    unlinked-warn policy), then descends one level — the top-level chain only.
    Used by the planners that legitimately stay shallow: ``plan_pull_nested_rack_chains``
    (whose ONE probe per top-level rack returns the full recursive tree) and
    ``plan_pull_device_sidechain``. The parameter pull goes depth-N via the
    sibling ``_iter_linked_device_params``. Yields in (tracks…, returns…) order,
    one tuple per device, so callers keep their per-device emission, rack
    filtering, and "nothing emitted" bookkeeping unchanged.
    """
    for parent_kind, parent_at, parent_row in _iter_linked_parents(
        conn, song_id=song_id, session_id=session_id,
        plan=plan, unlinked_warn=unlinked_warn,
    ):
        if parent_kind == "track":
            chains = Q.get_device_chains_for_track(conn, parent_row["id"])
        else:
            chains = Q.get_device_chains_for_return(conn, parent_row["id"])
        for chain in chains:
            if chain["position"] != 0:
                continue
            for d in Q.get_devices_for_chain(conn, chain["id"]):
                yield parent_kind, parent_at, parent_row, d


def _walk_nested_device_params(
    conn: sqlite3.Connection,
    *,
    parent_kind: str,
    parent_at: int,
    parent_row,
    rack_device,
    top_device_index: int,
    path: list[dict[str, int]],
):
    """Recurse a rack device's nested chains, yielding
    ``(parent_kind, parent_at, parent_row, device_row, node)`` for every nested
    device at any depth. ``node`` is the NodeAddr addressing it live — the LIVE
    parent index, the TOP-LEVEL ``device_index``, and the ``path`` of
    ``{chain_index, device_position}`` steps down to it (the address Chunk A
    froze; ``get_parameters`` resolves it server-side)."""
    for nchain in Q.get_device_chains_for_rack_device(conn, rack_device["id"]):
        for nd in Q.get_devices_for_chain(conn, nchain["id"]):
            step = {
                "chain_index": nchain["position"],
                "device_position": nd["position"],
            }
            node = {
                "parent": {"kind": parent_kind, "index": parent_at},
                "device_index": top_device_index,
                "path": path + [step],
            }
            yield parent_kind, parent_at, parent_row, nd, node
            if nd["kind"] in RACK_CLASS_NAMES:
                yield from _walk_nested_device_params(
                    conn, parent_kind=parent_kind, parent_at=parent_at,
                    parent_row=parent_row, rack_device=nd,
                    top_device_index=top_device_index, path=path + [step],
                )


def _iter_linked_device_params(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    plan: PullPlan,
    unlinked_warn,
):
    """Yield ``(parent_kind, parent_at, parent_row, device_row, node)`` for
    EVERY device on a linked parent — top-level chain AND nested rack chains, to
    any depth. The depth-N successor to `_iter_linked_top_level_devices` for the
    parameter pull: addressing is no longer the gap (Chunk A froze the NodeAddr
    `path`), so the param planner reaches nested devices too. For a top-level
    device the ``node`` is the flat ``{parent, device_index}`` shape (no path);
    nested devices carry the ``path``."""
    for parent_kind, parent_at, parent_row in _iter_linked_parents(
        conn, song_id=song_id, session_id=session_id,
        plan=plan, unlinked_warn=unlinked_warn,
    ):
        if parent_kind == "track":
            chains = Q.get_device_chains_for_track(conn, parent_row["id"])
        else:
            chains = Q.get_device_chains_for_return(conn, parent_row["id"])
        for chain in chains:
            if chain["position"] != 0:
                continue
            for d in Q.get_devices_for_chain(conn, chain["id"]):
                node = {
                    "parent": {"kind": parent_kind, "index": parent_at},
                    "device_index": d["position"],
                }
                yield parent_kind, parent_at, parent_row, d, node
                if d["kind"] in RACK_CLASS_NAMES:
                    yield from _walk_nested_device_params(
                        conn, parent_kind=parent_kind, parent_at=parent_at,
                        parent_row=parent_row, rack_device=d,
                        top_device_index=d["position"], path=[],
                    )


def plan_pull_devices(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan probes to pull the top-level device chain for each linked
    track and return (Wave M+1-2 / W3-3).

    Emits one ``ableton_device(action='list')`` per linked parent. The
    ``list`` probe returns positional device identity (``device_index``,
    ``class_name``, ``name``, ``is_active``) for the top-level chain only —
    this planner pulls the top-level chain shape; nested structure + params are
    separate planners (below).

    Out of scope of THIS planner (separate planners, no longer gap-gated —
    NODE-ADDR Chunk A froze the addressing, Chunk B reaches depth-N):
      - Nested rack chains → ``plan_pull_nested_rack_chains`` (depth-N apply)
      - Master-strip device chain (separate parent kind / planner)
      - Per-device parameter values → ``plan_pull_device_parameters`` (depth-N)
      - ``is_active`` flag (no DB column today; the field rides along in
        the probe but apply currently ignores it)

    Skips ``master`` track rows in the ``tracks`` iteration the same way
    ``plan_pull_mix`` does — master devices are reached via a future
    master-chain planner. Real returns live in the separate ``returns``
    table (the legacy ``tracks.kind='return'`` reservation was dropped
    V1 close-out 2026-05-17).
    """
    plan = PullPlan()
    any_emitted = False

    def _warn(parent_kind, row):
        if parent_kind == "track":
            return (
                f"track {row['name']!r} ({row['id']}) not linked in session — "
                "push it via the tracks phase (plan_push_song_tracks) first, "
                "then re-run pull"
            )
        return (
            f"return {row['name']!r} ({row['id']}) not linked in session — skipping"
        )

    for parent_kind, parent_at, row in _iter_linked_parents(
        conn, song_id=song_id, session_id=session_id, plan=plan, unlinked_warn=_warn,
    ):
        any_emitted = True
        index_kwarg = "track_index" if parent_kind == "track" else "return_index"
        plan.add(PullCall(
            tool="ableton_device",
            args={"action": "list", index_kwarg: parent_at},
            key=f"{parent_kind}_devices:{row['id']}",
            purpose=f"pull device chain for {parent_kind} {row['name']!r}",
        ))

    if not any_emitted:
        plan.warn(
            "no linked tracks or returns for this session — device-chain "
            "pull will be empty"
        )
    return plan


def plan_pull_nested_rack_chains(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan probes to pull one level of nested rack chains (W7-B).

    Iterates DB-side top-level device rows on linked tracks/returns and emits
    one ``ableton_device(action='get_device_chains', ...)`` per device whose
    `kind` is in `RACK_CLASS_NAMES`. The result is consumed by
    ``_apply_nested_rack_chains_for_device``, which diffs the response
    against `device_chains` + `devices` rows hung off the rack device.

    Assumes `plan_pull_devices` has already populated the top-level device
    rows for the session. If no top-level devices exist (no `plan_pull_devices`
    pull run yet), the planner emits nothing and warns.

    Depth: one probe per TOP-LEVEL rack is enough — ``get_device_chains``
    returns the FULL recursive tree (a nested device that is itself a rack
    carries its own `chains`), and the apply recurses it depth-N (NODE-ADDR
    Chunk B lifted the W7-B rack-in-rack scope cap). No separate probe per
    nested rack.

    `detail='summary'` is the default — identity-only nested device entries
    are sufficient for the diff (the recursive tree is present at summary
    detail; only per-nested mixer state needs `detail='full'`, and no schema
    column consumes it yet).
    """
    plan = PullPlan()
    any_emitted = False
    any_top_level_device = False

    for parent_kind, parent_at, row, d in _iter_linked_top_level_devices(
        conn, song_id=song_id, session_id=session_id, plan=plan,
        unlinked_warn=lambda _pk, _row: None,
    ):
        any_top_level_device = True
        if d["kind"] not in RACK_CLASS_NAMES:
            continue
        any_emitted = True
        index_kwarg = "track_index" if parent_kind == "track" else "return_index"
        plan.add(PullCall(
            tool="ableton_device",
            args={
                "action": "get_device_chains",
                index_kwarg: parent_at,
                "device_index": d["position"],
            },
            key=f"nested_rack_chains:{d['id']}",
            purpose=(
                f"pull nested chains for rack {d['kind']!r} "
                f"(pos {d['position']}) on {parent_kind} {row['name']!r}"
            ),
        ))

    if not any_top_level_device:
        plan.warn(
            "no top-level devices on linked tracks or returns — nested-rack "
            "pull will be empty (run plan_pull_devices first if you "
            "expected devices)"
        )
    elif not any_emitted:
        # Top-level devices exist but no racks among them — that's a valid
        # song shape, not a warning condition.
        pass
    return plan


def plan_pull_device_parameters(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan probes to pull per-device parameter values for every device
    already in the DB on a linked track or return (W5-D).

    The keystone for V1 round-trip parity: native Live instruments
    built by parameter-dialing (Operator, Wavetable, etc.) round-trip
    as default-state blanks today because the capture+pull side
    records the device class but not its parameter values.
    `plan_push_devices` already emits `set_parameter` per row in
    `device_parameters` (push.py:958-965); once pull populates the
    table, push closes the loop.

    Emits one ``ableton_device(action='get_parameters', detail='full')``
    per device. ``detail='full'`` is required for the ``min``/``max``/
    ``is_enum`` fields the apply path uses to compute
    ``value_normalized`` for the DB's [0, 1] storage form (enum and
    constant-range params get NULL).

    Iterates every device on each linked track/return — top-level chain AND
    nested rack chains, to any depth (NODE-ADDR Chunk B closes gap #17b: the
    nesting was gated on *addressing*, which Chunk A froze, so the planner now
    emits a `node` with the nested `path` for deep devices). `master` tracks are
    skipped. Operates on the device rows the previous `plan_pull_devices` +
    `plan_pull_nested_rack_chains` pulls wrote, so callers should run those
    first if the chain isn't already current.
    """
    plan = PullPlan()
    any_emitted = False

    for parent_kind, parent_at, row, d, node in _iter_linked_device_params(
        conn, song_id=song_id, session_id=session_id, plan=plan,
        unlinked_warn=lambda _pk, _row: (
            f"{_pk} {_row['name']!r} ({_row['id']}): not linked; skipping "
            "device parameters"
        ),
    ):
        any_emitted = True
        # NODE-ADDR: get_parameters takes a `node` device address. Top-level
        # devices get a flat `{parent, device_index}`; nested devices carry the
        # `path` of {chain_index, device_position} steps (built by the walk).
        depth = f", depth {len(node['path'])}" if node.get("path") else ""
        plan.add(PullCall(
            tool="ableton_device",
            args={
                "action": "get_parameters",
                "node": node,
                "detail": "full",
            },
            key=f"device_parameters:{d['id']}",
            purpose=(
                f"pull parameters for device {d['kind']!r} "
                f"(pos {d['position']}{depth}) on {parent_kind} {row['name']!r}"
            ),
        ))

    if not any_emitted:
        plan.warn(
            "no devices on linked tracks or returns — device-parameter "
            "pull will be empty (run plan_pull_devices first if you "
            "expected devices)"
        )
    return plan


def plan_pull_device_sidechain(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan probes to pull each linked device's sidechain SOURCE (SDC-7K3M).

    The PULL half of the device-sidechain round-trip whose author + push half
    already ships (``set_device_sidechain`` mutator + ``plan_push_device_sidechain``
    push phase). The ``S/C On`` / ``S/C Gain`` / ``S/C Mix`` params round-trip as
    ordinary ``device_parameters``; the one piece they can't carry is the SOURCE —
    the device's audio *input* routing, which on a sidechained compressor points
    at another track. Push restores it via ``set_input_routing``; this captures it
    via the symmetric ``get_input_routing``.

    Emits one ``ableton_device(action='get_input_routing')`` per device on a
    linked track or return via ``_iter_linked_top_level_devices`` — top-level
    chain only (``position==0``), ``master`` tracks skipped. (Sidechain pull is
    not yet extended depth-N — a nested sidechained compressor is uncommon; the
    addressing exists since NODE-ADDR if a witness appears.) The handler returns
    ``has_input_routing: False`` (no raise) for devices that lack the API,
    so probing every device is cheap and the apply layer no-ops the ones without
    a routing surface. Devices set in Ableton outside the DB are not
    auto-discovered (V1 — same boundary as the rest of pull).
    """
    plan = PullPlan()
    any_emitted = False

    for parent_kind, parent_at, row, d in _iter_linked_top_level_devices(
        conn, song_id=song_id, session_id=session_id, plan=plan,
        unlinked_warn=lambda _pk, _row: (
            f"{_pk} {_row['name']!r} ({_row['id']}): not linked; skipping "
            "device sidechain sources"
        ),
    ):
        any_emitted = True
        index_kwarg = "track_index" if parent_kind == "track" else "return_index"
        plan.add(PullCall(
            tool="ableton_device",
            args={
                "action": "get_input_routing",
                index_kwarg: parent_at,
                "device_index": d["position"],
            },
            key=f"device_sidechain_source:{d['id']}",
            purpose=(
                f"pull sidechain source for device {d['kind']!r} "
                f"(pos {d['position']}) on {parent_kind} {row['name']!r}"
            ),
        ))

    if not any_emitted:
        plan.warn(
            "no devices on linked tracks or returns — device-sidechain "
            "pull will be empty (run plan_pull_devices first if you "
            "expected devices)"
        )
    return plan


def _device_host_track_id(
    conn: sqlite3.Connection, device: sqlite3.Row,
) -> str | None:
    """The id of the track a device sits on, or ``None`` for a return- or
    rack-hosted device. Used to distinguish a real sidechain source from a
    device routed to its OWN track's signal (the default input)."""
    chain = Q.get_device_chain(conn, device["chain_id"])
    if chain is None:
        return None
    return chain["parent_track_id"]


def _apply_device_sidechain_source(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    song_id: str,
    device_id: str,
    result: dict[str, Any],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Ingest one device's sidechain SOURCE from a ``get_input_routing`` probe
    (shape: ``{has_input_routing, current_type, current_channel, available_*}``).

    The source is always a TRACK, so resolution is a track-name lookup (vs the
    routing-kind map track routing uses). Policy (V1, Ableton-authoritative in
    the SET direction; conservative on everything ambiguous):

      - device not linked → skip (defense in depth; the planner already gates).
      - ``has_input_routing`` False / ``current_type`` None → no-op.
      - ``current_type`` resolves to exactly ONE song track, distinct from the
        device's own host track → write it through ``set_device_sidechain``
        (idempotent).
      - resolves to the device's OWN host track → no-op (that's the default
        input, not a sidechain).
      - name collision (multiple tracks) → warning, skip.
      - no song-track match → no-op. The input is a non-track route (device
        default / external in / "No Input"). V1 does NOT auto-CLEAR an authored
        source here: how Live reports an un-sidechained device's default input is
        unverified without a session (operator-verification gates tightening this
        to a clear). A documented limitation, not a silent drop.
    """
    if Q.get_ableton_link(
        conn, session_id=session_id, db_kind="device", db_id=device_id,
    ) is None:
        out.skipped_unlinked += 1
        out.warnings.append(
            f"device_sidechain_source:{device_id} — device not linked in this "
            "session; the planner would not have emitted this. Skipping."
        )
        return
    dev = Q.get_device(conn, device_id)
    if dev is None:
        out.warnings.append(
            f"device_sidechain_source:{device_id} — DB row missing; skipping"
        )
        return

    if result.get("has_input_routing") is False:
        out.no_ops += 1
        return
    current_type = result.get("current_type")
    if current_type is None:
        out.no_ops += 1
        return

    matches = [
        t for t in Q.get_tracks_for_song(conn, song_id)
        if t["name"] == current_type
    ]
    if len(matches) > 1:
        out.warnings.append(
            f"device {dev['display_name']!r} sidechain source -> "
            f"{current_type!r}: matches multiple tracks by name; cannot form an "
            "unambiguous reference — skipping (rename one of the colliding tracks)"
        )
        return
    if not matches:
        # Non-track input (device default / external / "No Input"). V1 no-op —
        # see the policy note above; auto-clear is operator-verification-gated.
        out.no_ops += 1
        return

    source_track_id = matches[0]["id"]
    if source_track_id == _device_host_track_id(conn, dev):
        out.no_ops += 1  # routed to its own track's signal = default, not sidechain
        return

    live_channel = result.get("current_channel")
    if (dev["sidechain_source_track_id"], dev["sidechain_source_channel"]) == (
        source_track_id, live_channel,
    ):
        out.no_ops += 1
        return

    M.set_device_sidechain(
        conn, device_id=device_id, source_track_id=source_track_id,
        channel=live_channel, actor=actor, request_id=request_id, reason=reason,
    )
    out.mutations += 1
    out.details.append(
        f"device {dev['display_name']!r} sidechain source <- {current_type!r}"
        + (f" (channel {live_channel!r})" if live_channel else "")
    )


def _apply_devices_for_parent(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    parent_kind: str,
    parent_id: str,
    result: dict[str, Any],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Diff one top-level device chain against the probe payload (W3-3).

    Identity is *positional*: a (chain, position) slot holding a device
    with the same ``(class_name, name)`` is a no-op; any mismatch is a
    delete + create at that position (cleaner than a hypothetical
    ``update_device`` since per-device parameter rows cascade and a
    different kind at the same slot is structurally a different device).
    Live's API exposes no stable per-device identity across moves, so
    matching by position is the only stable shape.

    Empty-chain handling: if both sides are empty, no-op (don't create
    a stub chain row). If DB has a chain but Ableton is empty, all
    devices are deleted and the empty chain row is kept (cheap and
    avoids churn on the next push).

    ``is_active`` from the probe is ignored — no DB column today
    (tracked as a future schema extension). The mute/solo parity
    reference that used to live here was retired in M+1-4 when
    ``returns`` grew nullable ``mute``/``solo`` columns; the device
    chain's missing ``is_active`` column is now the sole remaining
    "schema doesn't model this yet" gap on the per-device-row level.
    """
    if Q.get_ableton_link(
        conn, session_id=session_id, db_kind=parent_kind, db_id=parent_id,
    ) is None:
        out.skipped_unlinked += 1
        out.warnings.append(
            f"{parent_kind}_devices for {parent_id!r}: not linked in session; "
            "skipping (the planner would not have emitted this)"
        )
        return

    devices_in = result.get("devices")
    if devices_in is None:
        out.warnings.append(
            f"{parent_kind}_devices for {parent_id!r}: result missing "
            "'devices' field"
        )
        return

    if parent_kind == "track":
        chains = Q.get_device_chains_for_track(conn, parent_id)
        parent_kwarg = {"parent_track_id": parent_id}
    elif parent_kind == "return":
        chains = Q.get_device_chains_for_return(conn, parent_id)
        parent_kwarg = {"parent_return_id": parent_id}
    else:
        raise ValueError(
            f"_apply_devices_for_parent: unsupported parent_kind {parent_kind!r}"
        )

    top_chain = next((c for c in chains if c["position"] == 0), None)
    if top_chain is None and not devices_in:
        out.no_ops += 1
        return
    if top_chain is None:
        chain_id = M.create_device_chain(
            conn, position=0,
            actor=actor, request_id=request_id, reason=reason,
            **parent_kwarg,
        )
    else:
        chain_id = top_chain["id"]

    _diff_chain_devices(
        conn,
        chain_id=chain_id,
        entries=devices_in,
        label=f"{parent_kind} device",
        context_label=f"{parent_kind}_devices for {parent_id!r}",
        out=out,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


def _exclude_analyzer_entries(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop HallucinoteAnalyzer probe entries and densely renumber the
    surviving authored devices' `device_index` (1-based rank among survivors).
    SNP-8R4K — Live→DB boundary exclusion (R3/R5).

    Position-independent: correct whether the analyzer is last or interleaved.
    An entry with a missing/invalid `device_index` is NOT renumbered — it
    passes through unchanged so `_diff_chain_devices`'s existing validation
    still warns on a malformed hand-crafted `results.json`.
    """
    survivors = [e for e in entries if not is_analyzer_device(e)]
    out: list[dict[str, Any]] = []
    rank = 0
    for e in survivors:
        idx = e.get("device_index")
        if isinstance(idx, int) and idx >= 1:
            rank += 1
            out.append({**e, "device_index": rank})
        else:
            out.append(e)
    return out


def _diff_chain_devices(
    conn: sqlite3.Connection,
    *,
    chain_id: str,
    entries: list[dict[str, Any]],
    label: str,
    context_label: str,
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Diff a Live device chain's contents against DB rows in `chain_id`.

    Positional identity: a (chain, position) slot whose ``(class_name, name)``
    matches is a no-op; any mismatch is delete + create at the same slot.
    Removals: any DB row at a position absent from `entries`.

    Shared by `_apply_devices_for_parent` (top-level chain, entries from
    `ableton_device(action='list')`) and
    `_apply_nested_rack_chains_for_device` (nested chain, entries from
    `ableton_device(action='get_device_chains')`). Both pre-normalize to
    use ``device_index`` for the slot — the wire-shape `position` field
    on nested entries is renamed at the caller.

    `label` is the per-row prefix in details lines (e.g. ``"track device"``,
    ``"rack chain 2 device"``). `context_label` is the prefix for warnings
    that name the surface being diffed.

    SNP-8R4K — analyzer exclusion: the HallucinoteAnalyzer is measurement
    infrastructure, not authored content. Probed entries that
    `is_analyzer_device` are dropped before the diff so a pull never writes an
    analyzer row, and the surviving authored devices are densely renumbered
    (rank among survivors) so an interleaved analyzer can't shift authored
    positions or leave a hole. Shared by both the top-level and nested-rack
    callers, so both inherit the exclusion.
    """
    entries = _exclude_analyzer_entries(entries)

    db_devices = list(Q.get_devices_for_chain(conn, chain_id))
    db_by_position = {d["position"]: d for d in db_devices}

    seen_positions: set[int] = set()
    for entry in entries:
        idx = entry.get("device_index")
        if not isinstance(idx, int) or idx < 1:
            out.warnings.append(
                f"{context_label}: entry missing or invalid "
                f"device_index: {entry!r}"
            )
            continue
        class_name_in = entry.get("class_name") or ""
        if not class_name_in:
            out.warnings.append(
                f"{context_label}: device at position {idx} missing "
                "class_name; skipping"
            )
            continue
        name_in = entry.get("name") or ""
        # Arc 4 / D4: prefer class_display_name as the loader-facing
        # `kind`. Fall back to `name` (display name on the instance) for
        # backwards compat with probe payloads emitted before D4 added
        # the field. Both are reliable for default-loaded devices; for
        # renamed/preset-loaded devices the loader uses preset_uri /
        # preset_query regardless, so a divergence here is harmless.
        kind_in = (
            entry.get("class_display_name")
            or name_in
            or class_name_in
        )
        seen_positions.add(idx)

        existing = db_by_position.get(idx)
        if existing is not None:
            existing_class_name = (
                existing["class_name"]
                if "class_name" in existing.keys() else None
            )
            if (
                existing["kind"] == kind_in
                and existing["display_name"] == name_in
                and existing_class_name == class_name_in
            ):
                out.no_ops += 1
                continue
            # Different device at the same slot — replace. Cascade clears
            # any device_parameters rows; correct for "this slot now holds
            # something else."
            M.delete_device(
                conn, device_id=existing["id"],
                actor=actor, request_id=request_id, reason=reason,
            )
        M.create_device(
            conn,
            chain_id=chain_id,
            position=idx,
            kind=kind_in,
            display_name=name_in,
            class_name=class_name_in,
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        if existing is not None:
            out.details.append(
                f"{label} pos {idx}: "
                f"{existing['kind']}/{existing['display_name']!r} -> "
                f"{kind_in}/{name_in!r}"
            )
        else:
            out.details.append(
                f"{label} pos {idx}: added {kind_in}/{name_in!r}"
            )

    # Removals: any DB row at a position Ableton didn't report. Iterating the
    # pre-mutation snapshot is safe — we never re-process a position we
    # already handled in the create/replace pass above.
    for d in db_devices:
        if d["position"] in seen_positions:
            continue
        M.delete_device(
            conn, device_id=d["id"],
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(
            f"{label} pos {d['position']}: "
            f"removed {d['kind']}/{d['display_name']!r}"
        )


def _apply_nested_rack_chains_for_device(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    rack_device_id: str,
    result: dict[str, Any],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Diff one rack device's nested chains against the probe payload (W7-B).

    Mirrors `_apply_devices_for_parent` but operates on chains hung off a
    rack device (`parent_rack_device_id`). Chain identity is positional —
    the `chain_index` field on each entry maps to `device_chains.position`.
    Nested device diff reuses `_diff_chain_devices` after normalizing the
    wire shape (`position` -> the same `device_index` field name).

    Missing rack device on the DB side -> warn + skip (the planner shouldn't
    have emitted, but defense-in-depth).
    """
    rack = Q.get_device(conn, rack_device_id)
    if rack is None:
        out.warnings.append(
            f"nested_rack_chains for {rack_device_id!r}: rack device row "
            "not found — DB drifted since planner ran; skipping"
        )
        return
    if rack["kind"] not in RACK_CLASS_NAMES:
        out.warnings.append(
            f"nested_rack_chains for rack {rack_device_id!r}: kind "
            f"{rack['kind']!r} is not a rack class "
            f"({sorted(RACK_CLASS_NAMES)}); skipping"
        )
        return

    # Defense-in-depth link check, parallel to `_apply_devices_for_parent`:
    # the planner won't emit for unlinked parents, but a hand-crafted
    # results.json could route around that guard.
    parent_chain = conn.execute(
        "SELECT parent_track_id, parent_return_id FROM device_chains WHERE id = ?",
        (rack["chain_id"],),
    ).fetchone()
    parent_kind, parent_id = (
        ("track", parent_chain["parent_track_id"]) if parent_chain["parent_track_id"]
        else ("return", parent_chain["parent_return_id"])
        if parent_chain["parent_return_id"]
        else (None, None)
    )
    if parent_kind is None:
        # Rack on a rack chain — outside W7-B scope (one level only). Defense:
        # the planner restricts emission to top-level rack rows, but if a
        # hand-rolled results.json bypassed that, surface it.
        out.warnings.append(
            f"nested_rack_chains for rack {rack_device_id!r}: rack lives on "
            "a nested chain — W7-B walks one level only; skipping"
        )
        return
    if Q.get_ableton_link(
        conn, session_id=session_id, db_kind=parent_kind, db_id=parent_id,  # type: ignore[arg-type]  # parent walked from a linked row
    ) is None:
        out.skipped_unlinked += 1
        out.warnings.append(
            f"nested_rack_chains for rack {rack_device_id!r}: parent "
            f"{parent_kind} {parent_id!r} not linked in session; skipping "
            "(the planner would not have emitted this)"
        )
        return

    chains_in = result.get("chains")
    if chains_in is None:
        out.warnings.append(
            f"nested_rack_chains for rack {rack_device_id!r}: result missing "
            "'chains' field"
        )
        return

    # `get_device_chains` returns the FULL recursive tree (each nested device
    # that is itself a rack carries its own `chains`), so the whole subtree is
    # diffed depth-N from this one probe — no rack-in-rack scope limit anymore
    # (NODE-ADDR Chunk B; the W7-B one-level cap is lifted).
    _diff_nested_chains(
        conn,
        rack_device_id=rack_device_id,
        rack_kind=rack["kind"],
        chains_in=chains_in,
        out=out,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


def _diff_nested_chains(
    conn: sqlite3.Connection,
    *,
    rack_device_id: str,
    rack_kind: str,
    chains_in: list[dict[str, Any]],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Diff one rack's nested chains against a `get_device_chains` subtree, then
    recurse into any nested device that is itself a rack — closing the W7-B
    one-level cap (NODE-ADDR Chunk B). The probe already carries the full tree,
    so recursion is pure DB-side bookkeeping (no extra probes)."""
    db_chains = Q.get_device_chains_for_rack_device(conn, rack_device_id)
    db_chain_by_position = {c["position"]: c for c in db_chains}

    seen_positions: set[int] = set()
    for chain_entry in chains_in:
        ci = chain_entry.get("chain_index")
        if not isinstance(ci, int) or ci < 1:
            out.warnings.append(
                f"nested_rack_chains for rack {rack_device_id!r}: chain "
                f"entry missing or invalid chain_index: {chain_entry!r}"
            )
            continue
        seen_positions.add(ci)

        existing_chain = db_chain_by_position.get(ci)
        if existing_chain is None:
            chain_id = M.create_device_chain(
                conn,
                parent_rack_device_id=rack_device_id,
                position=ci,
                actor=actor, request_id=request_id, reason=reason,
            )
            out.mutations += 1
            out.details.append(
                f"nested chain {ci} on rack {rack_kind}: added"
            )
        else:
            chain_id = existing_chain["id"]

        # NODE-ADDR Chunk C + F: diff the chain's authored properties (per-drum
        # choke_group/out_note + per-chain mixer mute/solo/volume/pan) against the
        # DB. chain_authored_props applies the non-default filter (None = Live
        # default), so a now-default value clears the DB's stale one — symmetric
        # with the set_track_routing / set_chain_properties clear-on-None
        # contract. set_chain_properties is idempotent (no event when nothing
        # changed), so a steady chain is a no-op even though we always pass every
        # field.
        props = chain_authored_props(chain_entry)
        result = M.set_chain_properties(
            conn,
            chain_id=chain_id,
            choke_group=props["choke_group"],
            out_note=props["out_note"],
            mute=props["mute"],
            solo=props["solo"],
            volume=props["volume"],
            pan=props["pan"],
            actor=actor, request_id=request_id, reason=reason,
        )
        if result.kind == "updated":
            out.mutations += 1
            out.details.append(
                f"nested chain {ci} on rack {rack_kind}: per-drum props "
                f"{props}"
            )

        # Normalize wire-shape `position` to `device_index` so `_diff_chain_devices`
        # can be shared with the top-level apply path. The MCP `get_device_chains`
        # handler uses `position` for the nested device's slot, while
        # `ableton_device(action='list')` uses `device_index` — same semantic,
        # different field name.
        nested_devices_raw = chain_entry.get("devices") or []
        normalized = [
            {**e, "device_index": e.get("position")}
            for e in nested_devices_raw
        ]
        _diff_chain_devices(
            conn,
            chain_id=chain_id,
            entries=normalized,
            label=f"nested chain {ci} on rack {rack_kind} device",
            context_label=f"nested_rack_chains for rack {rack_device_id!r}, "
                          f"chain {ci}",
            out=out,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )

        # DEPTH-N recursion: a nested device that is itself a rack carries its
        # own `chains` in the probe tree. After `_diff_chain_devices` has
        # created/matched the device row at that slot, descend into it. Nested
        # chains never hold the analyzer (it is injected only on top-level
        # track/return/master surfaces), so the probe `position` matches the DB
        # position 1:1 — no densify drift to reconcile here.
        db_devices_now = {
            d["position"]: d for d in Q.get_devices_for_chain(conn, chain_id)
        }
        for e in normalized:
            sub_chains = e.get("chains")
            if not sub_chains:
                continue
            sub_device = db_devices_now.get(e.get("device_index"))
            if sub_device is None or sub_device["kind"] not in RACK_CLASS_NAMES:
                continue
            _diff_nested_chains(
                conn,
                rack_device_id=sub_device["id"],
                rack_kind=sub_device["kind"],
                chains_in=sub_chains,
                out=out,
                actor=actor,
                request_id=request_id,
                reason=reason,
            )

    # Removals: chains in DB that Ableton didn't report. Cascade clears nested
    # devices + their parameters.
    for c in db_chains:
        if c["position"] in seen_positions:
            continue
        M.delete_device_chain(
            conn, chain_id=c["id"],
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(
            f"nested chain {c['position']} on rack {rack_kind}: removed"
        )


def _apply_device_parameters_for_device(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    result: dict[str, Any],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Diff one device's parameter set against the probe payload (W5-D).

    Identity is by parameter name (each device has unique parameter
    names per the schema's ``UNIQUE(device_id, name)``). Diff enumerates
    every state per the "detection enumerates every state" learning:

      - in DB + in Live + same value         -> no-op
      - in DB + in Live + value differs      -> upsert (mutator handles)
      - in Live only                         -> create (upsert)
      - in DB only                           -> remove

    ``value_normalized`` is computed from Live's raw ``value`` against
    the ``min``/``max`` returned by ``detail='full'``. Enum/quantized
    params and constant-range params store ``value_normalized=NULL``
    per the schema CHECK; ``value_display`` is always set.
    """
    device = Q.get_device(conn, device_id)
    if device is None:
        out.warnings.append(
            f"device_parameters for device {device_id!r}: device row not "
            "found; skipping (pull_devices may not have run)"
        )
        return

    params_in = result.get("parameters")
    if params_in is None:
        out.warnings.append(
            f"device_parameters for device {device_id!r} "
            f"({device['kind']!r}): result missing 'parameters' field"
        )
        return

    live_by_name: dict[str, dict[str, Any]] = {}
    for entry in params_in:
        if not isinstance(entry, dict):
            out.warnings.append(
                f"device_parameters for {device['kind']!r}: parameter "
                f"entry is not a dict: {entry!r}; skipping"
            )
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            out.warnings.append(
                f"device_parameters for {device['kind']!r}: parameter "
                "missing 'name'; skipping"
            )
            continue
        live_by_name[name] = entry

    db_rows = Q.get_device_parameters(conn, device_id)
    db_by_name = {r["name"]: r for r in db_rows}

    # Drift-detection scope (PULL-DRIFT-DETECT): diff only the params the DB
    # already tracks — the author's DIALED set. A Live param NOT in the DB is a
    # preset DEFAULT the DB deliberately doesn't store; capturing it would
    # pollute the dialed set with the device's full (thousands-strong) parameter
    # surface, and the pull can't tell a user-dial from a preset default without
    # the device's defaults (which it doesn't have). Capturing a brand-new
    # dialed param is the `/song-snapshot` full-recapture's job, not this
    # lightweight drift bake. So Live-only params are SKIPPED, never added.
    for name, existing in db_by_name.items():
        entry = live_by_name.get(name)
        if entry is None:
            continue  # absent from Live -> handled by the removal loop below
        raw_value = entry.get("value")
        if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
            out.warnings.append(
                f"device_parameters for {device['kind']!r}: parameter "
                f"{name!r} has non-numeric value {raw_value!r}; skipping"
            )
            continue
        value_display = entry.get("value_display")
        if not isinstance(value_display, str):
            value_display = ""
        min_val = float(entry.get("min", 0.0))
        max_val = float(entry.get("max", 1.0))
        is_enum = bool(entry.get("is_enum", False))
        # DEV-4P7R: a non-enum param whose raw range != [0,1] takes the raw
        # channel — normalize-as-raw mis-dials it at push (no value_normalized
        # handler kwarg) and a non-monotonic display is refused. value_raw is
        # Live's own param.value, pushed straight through. The two numeric
        # continuous channels are mutually exclusive (mutator-enforced).
        use_raw = param_needs_raw_channel(min_val, max_val, is_enum)
        if use_raw:
            value_raw: float | None = float(raw_value)
            value_normalized: float | None = None
        else:
            value_raw = None
            value_normalized = normalize_param_value(
                float(raw_value), min_val, max_val, is_enum,
            )
        # E1: capture value_items for enum params so the compose-time envelope
        # helper can resolve enum-name breakpoints without the build.py author
        # hand-listing the cardinality.
        value_items: list[str] | None = None
        if is_enum:
            raw_items = entry.get("value_items")
            if isinstance(raw_items, (list, tuple)):
                value_items = [str(item) for item in raw_items]
        new_items_json = json.dumps(value_items) if value_items else None
        items_same = existing["value_items_json"] == new_items_json

        # Round-trip-aware comparison (PULL-DRIFT-DETECT): compare by the param's
        # AUTHORITATIVE stored form, so an equal value never reads as a change.
        #   * continuous (DB value_normalized set) -> compare normalized within
        #     _FLOAT_EPS; the display string is a cosmetic render whose
        #     formatting Live may vary, so it is NOT part of the equality test.
        #   * display-only (DB value_normalized is NULL — no continuous form was
        #     stored) -> compare the display string (its only stored form). The
        #     old `display_same AND norm_same` forced a mismatch here because the
        #     pull always computes a non-NULL normalized from Live's raw value.
        #   * raw-channel (DEV-4P7R) -> compare value_raw within _FLOAT_EPS. A
        #     legacy row that stored this param as normalized has value_raw=NULL,
        #     so it reads as changed and the pull rewrites it to the raw form
        #     (migrating the broken legacy representation in place).
        if use_raw:
            value_same = _raw_values_match(value_raw, existing["value_raw"])
        elif existing["value_normalized"] is not None:
            value_same = _normalized_values_match(
                value_normalized, existing["value_normalized"],
            )
        else:
            value_same = existing["value_display"] == value_display
        if value_same and items_same:
            out.no_ops += 1
            continue
        M.set_device_parameter(
            conn,
            device_id=device_id,
            name=name,
            value_display=value_display,
            value_normalized=value_normalized,
            value_items=value_items,
            value_raw=value_raw,
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(
            f"device {device['kind']!r} param {name!r}: "
            f"updated -> {value_display!r}"
        )

    for db_row in db_rows:
        if db_row["name"] in live_by_name:
            continue
        M.remove_device_parameter(
            conn,
            device_id=device_id,
            name=db_row["name"],
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(
            f"device {device['kind']!r} param {db_row['name']!r}: removed"
        )


__all__ = [
    "plan_pull_devices",
    "plan_pull_nested_rack_chains",
    "plan_pull_device_parameters",
    "_apply_devices_for_parent",
    "_diff_chain_devices",
    "_apply_nested_rack_chains_for_device",
    "_apply_device_parameters_for_device",
]
