"""Mix-half planner: device chains (instruments + effects + parameters)."""
from __future__ import annotations

import json
import sqlite3

from hallucinote.analyzer_identity import is_analyzer_device
from hallucinote.db import queries as Q

from ._core import PushPlan, ToolCall, build_node_addr


def plan_push_devices(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the push of device chains — instruments + effects on tracks/returns
    plus their dialed parameters.

    Strategy (Wave M-4: unified ableton_device tool):
      1. For each linked track / return, walk its top-level device chain in
         position order.
      2. For each device, check the `ableton_links` projection for a 'device'
         binding. If missing, emit `ableton_device(action='load', ...)` with
         the parent-addressing (`track_index` OR `return_index`) and record a
         diagnostic note — parameter writes for that device wait for the
         executor's same-pass convergence re-plan (SYN-9F2L), which re-runs
         this planner once the link has landed.
      3. For each linked device, emit
         `ableton_device(action='set_parameter', ...)` per dialed param,
         choosing the wire form by what the DB stored (SYN-9F2L):
           * captured enum items → `value_type='enum'` with the display string
             (the handler validates membership);
           * a display string → `value_display` (`value_type='continuous'`; the
             handler inverts the param's own display curve — exact, and
             center-zero-safe where a naive normalized fraction dials the wrong
             direction);
           * normalized only → the raw `value` (stringified, `'continuous'`);
           * none of those → an operator ALERT (`plan.alert`, drained into the
             push report's warnings) — the dialed intent was authored but can't
             be pushed; never a silent drop.
         A refused display write is retried once by the executor (as enum, or
         with the DB's normalized value) — see push_execute's set_parameter
         fallback.
      4. DEEP-RACK-ADDR: for each linked top-level RACK device, recurse its
         nested chains and emit `set_parameter` with the canonical `device_path`
         for every nested device's dialed params (to arbitrary depth). Nested
         devices are NOT loaded — they arrive with the rack preset — so push
         only sets their params. This is what makes a deep by-ear fix survive a
         `build.py` rebuild.
    """
    plan = PushPlan()
    tracks = Q.get_tracks_for_song(conn, song_id)
    returns = Q.get_returns_for_song(conn, song_id)

    if not tracks and not returns:
        plan.warn("no devices to push for this song")
        return plan

    for t in tracks:
        if t["kind"] == "master":
            # Master strip is a song-level singleton — no ableton_link row
            # (no track_index addressing) and no name disambiguation. Devices
            # on the master are addressed via `master=True` at load time.
            for chain in Q.get_device_chains_for_track(conn, t["id"]):
                for device in Q.get_devices_for_chain(conn, chain["id"]):
                    _emit_device_calls(
                        plan, conn,
                        session_id=session_id,
                        parent_kind="master",
                        parent_at=None,
                        parent_name=t["name"],
                        device=device,
                    )
            continue
        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=t["id"]
        )
        if track_at is None:
            chains = Q.get_device_chains_for_track(conn, t["id"])
            if chains:
                plan.warn(
                    f"track {t['name']!r} not linked in session — "
                    f"{len(chains)} chain(s) skipped; create the track first"
                )
            continue
        for chain in Q.get_device_chains_for_track(conn, t["id"]):
            for device in Q.get_devices_for_chain(conn, chain["id"]):
                _emit_device_calls(
                    plan, conn,
                    session_id=session_id,
                    parent_kind="track",
                    parent_at=track_at,
                    parent_name=t["name"],
                    device=device,
                )

    for r in returns:
        return_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="return", db_id=r["id"]
        )
        if return_at is None:
            chains = Q.get_device_chains_for_return(conn, r["id"])
            if chains:
                plan.warn(
                    f"return {r['name']!r} not linked in session — "
                    f"{len(chains)} chain(s) skipped; create the return first"
                )
            continue
        for chain in Q.get_device_chains_for_return(conn, r["id"]):
            for device in Q.get_devices_for_chain(conn, chain["id"]):
                _emit_device_calls(
                    plan, conn,
                    session_id=session_id,
                    parent_kind="return",
                    parent_at=return_at,
                    parent_name=r["name"],
                    device=device,
                )

    return plan


def _emit_device_calls(
    plan: PushPlan,
    conn: sqlite3.Connection,
    *,
    session_id: str,
    parent_kind: str,         # 'track' | 'return' | 'master'
    parent_at: int | None,
    parent_name: str,
    device: sqlite3.Row,
) -> None:
    """Emit load + parameter calls for a single device. If the device isn't
    yet linked in this session, emit the load and skip parameter writes —
    the agent must call apply_push_results to record the new device_index
    before parameters can be addressed.

    ``parent_kind='master'`` is the master-strip path: ``parent_at`` is
    ``None`` (master is a singleton, no index addressing), and the emitted
    ToolCall uses ``master=True`` instead of ``track_index`` / ``return_index``.
    """
    # W13-B (v0.9.0): placeholder devices represent an author-intentional
    # empty slot. Push leaves the chain position empty; the consumer
    # picks an instrument/effect to fill it. Skip cleanly with a warn so
    # the agent UI surfaces the gap.
    if device["kind"] == "placeholder":
        plan.warn(
            f"placeholder device {device['display_name']!r} at position "
            f"{device['position']} on {parent_kind} {parent_name!r} — "
            "skipping load (author left this slot intentionally empty; "
            "load any instrument/effect there in Live before producing)"
        )
        return
    # SNP-8R4K: the HallucinoteAnalyzer is measurement infrastructure owned
    # solely by the render subsystem — never a loadable, authored device.
    # Capture/pull exclude it at the boundary, so a clean DB never holds one;
    # this defensive skip protects a legacy-polluted DB from breaking a
    # rebuild (it's not a loadable browser node — emitting a load would
    # fail/halt the push). Never emit a load for it.
    if is_analyzer_device(device):
        plan.warn(
            f"HallucinoteAnalyzer row {device['display_name']!r} at position "
            f"{device['position']} on {parent_kind} {parent_name!r} — "
            "skipping (measurement infrastructure, not an authored device; "
            "the render injects it at capture time). A clean DB shouldn't "
            "carry this row — run the SNP-8R4K legacy cleanup to strip it."
        )
        return
    device_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="device", db_id=device["id"]
    )
    # Master strip addressing diverges from track/return: a boolean flag
    # instead of an index. Captured up front so both load + set_parameter
    # branches share one shape.
    if parent_kind == "master":
        parent_kv: dict[str, object] = {"master": True}
    elif parent_kind == "track":
        parent_kv = {"track_index": parent_at}
    else:
        parent_kv = {"return_index": parent_at}
    # DEV-6M2K: master device chains push like track/return chains. The earlier
    # SYN-2M9P skip here (emit no master load, surface a place-by-hand note)
    # mirrored DEV-2M9K's refusal — both rested on a premise refuted on Live
    # 12.4.2 (master device load works). An unlinked master device now falls
    # through to the generic load emission below: `parent_kv = {"master": True}`
    # is already set up, and `load_handler` no longer refuses master, so the
    # load executes and the device links via the same `device:<id>` key path —
    # no PARTIAL-by-master halt, no hand-placement step.
    if device_at is None:
        # Wave M-4: unified ableton_device(action='load') replaces the
        # legacy fork's load_device / load_device_on_return narrow tools.
        # The handler accepts a Live device class name as `kind` and an
        # optional Live browser URI as `preset_uri`. Live 12.4 has no
        # public reorder API — devices always land at the END of the
        # destination chain, so the planner does not emit `position`.
        # If the DB chain order needs to be enforced, push devices in the
        # order they appear in the chain (position-asc) and Live's
        # tail-append will match.
        # Top-level load: the destination is the parent's main device chain, a
        # node-itself address (terminal == parent_kind). Push never loads NESTED
        # devices — they arrive with the rack preset (DEEP-RACK-ADDR §3c).
        load_args = {
            "action": "load",
            "node": build_node_addr(parent_kv, terminal=parent_kind),
            "kind": device["kind"],
        }
        # Arc 7-tail / E3 (W13-A v1.0): the captured browser path is a
        # fallback identity for the cross-machine "same plugin, different
        # catalog id" case. Threaded alongside whichever of preset_query
        # / preset_uri the planner emits — the load handler uses it when
        # the per-machine FileId in preset_uri doesn't resolve. Extracted
        # once at the top so every branch below can attach it.
        browser_path_raw = (
            device["browser_path_json"]
            if "browser_path_json" in device.keys() else None
        )
        browser_path_value: list[str] | None = None
        if browser_path_raw is not None:
            try:
                browser_path_value = json.loads(browser_path_raw)
            except (json.JSONDecodeError, TypeError) as exc:
                plan.warn(
                    f"device {device['display_name']!r} on {parent_kind} "
                    f"{parent_name!r}: stored browser_path is not valid "
                    f"JSON ({exc}); loading without the fallback identity "
                    "path — cross-machine FileId mismatch will fail"
                )
        # Sweep B: preset_query (portable) takes precedence over preset_uri
        # (per-machine). The MCP load handler refuses if both are set, so
        # the planner must pick one. Composer's expressed preference wins.
        preset_query_raw = (
            device["preset_query"] if "preset_query" in device.keys() else None
        )
        if preset_query_raw is not None:
            try:
                load_args["preset_query"] = json.loads(preset_query_raw)
            except (json.JSONDecodeError, TypeError) as exc:
                plan.warn(
                    f"device {device['display_name']!r} on {parent_kind} "
                    f"{parent_name!r}: stored preset_query is not valid JSON "
                    f"({exc}); falling back to preset_uri / kind-only load"
                )
                if device["preset_uri"] is not None:
                    load_args["preset_uri"] = device["preset_uri"]
                    if browser_path_value is not None:
                        load_args["browser_path"] = browser_path_value
        elif device["preset_uri"] is not None:
            load_args["preset_uri"] = device["preset_uri"]
            if browser_path_value is not None:
                load_args["browser_path"] = browser_path_value
        plan.add(ToolCall(
            tool="ableton_device",
            args=load_args,
            key=f"device:{device['id']}",
            purpose=(
                f"load {device['kind']} '{device['display_name']}' "
                f"at position {device['position']} on {parent_kind} {parent_name!r}"
            ),
        ))
        plan.warn(
            f"device {device['display_name']!r} on {parent_kind} {parent_name!r} "
            "not linked yet; rerun plan_push_devices after apply_push_results "
            "records the device_index"
        )
        return

    _emit_param_writes(
        plan, conn,
        device=device,
        parent_kv=parent_kv,
        device_index=device_at,
        device_path=None,
        parent_kind=parent_kind,
        parent_name=parent_name,
    )
    # DEEP-RACK-ADDR: a rack device's nested-chain devices are NOT separately
    # linked or loaded (they arrive with the rack preset, the unit of load) —
    # but their dialed params must still be pushed, or a deep fix reverts on the
    # next rebuild. Recurse the nested tree to arbitrary depth, addressing each
    # nested device by its canonical device_path relative to THIS top-level
    # device's Live index (device_at). Uses set_parameter + device_path, never
    # the retired in_rack triple (design §8: that would silently re-cap at 2).
    _emit_nested_param_writes(
        plan, conn,
        rack_device_id=device["id"],
        parent_kv=parent_kv,
        top_device_index=device_at,
        parent_kind=parent_kind,
        parent_name=parent_name,
    )


def _emit_param_writes(
    plan: PushPlan,
    conn: sqlite3.Connection,
    *,
    device: sqlite3.Row,
    parent_kv: dict[str, object],
    device_index: int,
    device_path: list[dict[str, int]] | None,
    parent_kind: str,
    parent_name: str,
) -> None:
    """Emit `set_parameter` calls for one device's dialed params.

    ``device_index`` is the TOP-LEVEL device's Live index; ``device_path`` (a
    list of ``{chain_index, device_position}`` steps, or None) addresses a
    device nested inside it (DEEP-RACK-ADDR). For a top-level device pass
    ``device_path=None`` — the wire shape is then identical to the pre-nesting
    behavior.

    SYN-9F2L wire-form selection per param:
      * captured value_items → a known enum: value_type='enum' with the display
        string (the handler validates membership);
      * display string present → value_display (the handler inverts the param's
        own display curve — exact, and safe for center-zero params where a naive
        normalized fraction dials the wrong direction);
      * normalized only → the raw `value` (stringified on the wire);
      * neither → an operator ALERT, never a silent drop.
    The executor retries a refused display write once (as enum, or with the DB's
    normalized value) — see push_execute's set_parameter fallback.
    """
    params = Q.get_device_parameters(conn, device["id"])
    unwritable: list[str] = []
    nested_note = f" (nested depth {len(device_path)})" if device_path else ""
    for p in params:
        display = (p["value_display"] or "").strip()
        if p["value_items_json"] is not None:
            if not display:
                unwritable.append(p["name"])
                continue
            value_kv: dict[str, object] = {
                "value": display, "value_type": "enum",
            }
            chosen = f"enum {display!r}"
        elif display:
            value_kv = {"value_display": display, "value_type": "continuous"}
            chosen = f"display {display!r}"
        elif p["value_normalized"] is not None:
            value_kv = {
                "value": str(p["value_normalized"]),
                "value_type": "continuous",
            }
            chosen = f"normalized {p['value_normalized']:g}"
        else:
            unwritable.append(p["name"])
            continue
        args: dict[str, object] = {
            "action": "set_parameter",
            "node": build_node_addr(
                parent_kv, device_index=device_index, device_path=device_path,
            ),
            "parameter_name": p["name"],
            **value_kv,
        }
        plan.add(ToolCall(
            tool="ableton_device",
            args=args,
            key=f"device_parameter:{device['id']}:{p['name']}",
            purpose=(
                f"{parent_name} / {device['display_name']}{nested_note} / "
                f"{p['name']} = {chosen}"
            ),
        ))
    if unwritable:
        # Operator-actionable (SYN-9F2L): the dialed intent was authored but
        # can't be pushed — surface it in the push report, not the diagnostic
        # notes channel where it gets discarded.
        plan.alert(
            f"device {device['display_name']!r}{nested_note} on {parent_kind} "
            f"{parent_name!r}: "
            f"{len(unwritable)} param(s) have no writable form "
            f"({', '.join(unwritable[:3])}{'...' if len(unwritable) > 3 else ''}) "
            "— no display value and no normalized value stored; the dialed "
            "intent was NOT pushed"
        )


def _emit_nested_param_writes(
    plan: PushPlan,
    conn: sqlite3.Connection,
    *,
    rack_device_id: str,
    parent_kv: dict[str, object],
    top_device_index: int,
    parent_kind: str,
    parent_name: str,
) -> None:
    """Recurse a rack device's nested chains, emitting `set_parameter` (with
    `device_path`) for each nested device's dialed params — to arbitrary depth.

    Nested devices are NOT loaded (they arrive with the rack preset); push only
    sets their dialed params. Each device's `device_path` is computed from the
    DB hierarchy (`get_device_nesting_path`), so it matches the reloaded
    preset's structure. ``top_device_index`` is the Live index of the top-level
    rack — every nested device addresses from there.
    """
    for chain in Q.get_device_chains_for_rack_device(conn, rack_device_id):
        for nested in Q.get_devices_for_chain(conn, chain["id"]):
            # Defensive: a clean DB never nests a placeholder or the analyzer,
            # but a legacy-polluted one might — skip both (mirrors the
            # top-level guards) rather than emit an unaddressable write.
            if nested["kind"] == "placeholder" or is_analyzer_device(nested):
                continue
            device_path = Q.get_device_nesting_path(conn, nested["id"])
            _emit_param_writes(
                plan, conn,
                device=nested,
                parent_kv=parent_kv,
                device_index=top_device_index,
                device_path=device_path,
                parent_kind=parent_kind,
                parent_name=parent_name,
            )
            # Recurse deeper — this nested device may itself be a rack.
            _emit_nested_param_writes(
                plan, conn,
                rack_device_id=nested["id"],
                parent_kv=parent_kv,
                top_device_index=top_device_index,
                parent_kind=parent_kind,
                parent_name=parent_name,
            )


def plan_push_device_sidechain(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Materialize device sidechain SOURCE routing (SDC-7K3M).

    Runs AFTER the ``devices`` phase: a device must exist + be linked before its
    sidechain input routing can be set. Mirrors ``plan_push_routing``'s track-FK
    resolution — the DB stores the source as a ``tracks`` FK, we resolve it to
    the source track's Live display_name (``name``) and emit
    ``ableton_device(action='set_input_routing')``. The ``S/C On`` / ``S/C Gain``
    params are pushed by the ``devices`` phase as ordinary parameters; this phase
    restores the one piece they can't carry — the SOURCE.

    Ack-only (like routing): the state originates from the DB, no Live-side index
    to record back. A device whose source FK doesn't resolve to a song track is
    ALERTed (operator-actionable); an unlinked device is deferred to the
    devices-convergence re-plan.
    """
    plan = PushPlan()
    by_id = {t["id"]: t for t in Q.get_tracks_for_song(conn, song_id)}
    returns = Q.get_returns_for_song(conn, song_id)

    def _emit_for_device(device, parent_kv, parent_kind, parent_name):
        keys = device.keys()
        src_id = (
            device["sidechain_source_track_id"]
            if "sidechain_source_track_id" in keys else None
        )
        if src_id is None:
            return  # no sidechain source authored on this device
        src = by_id.get(src_id)
        if src is None:
            plan.alert(
                f"device {device['display_name']!r} on {parent_kind} "
                f"{parent_name!r}: sidechain source track {src_id!r} is not in "
                "this song — cannot resolve a Live source; skipped"
            )
            return
        device_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="device", db_id=device["id"]
        )
        if device_at is None:
            plan.warn(
                f"device {device['display_name']!r} on {parent_kind} "
                f"{parent_name!r} not linked yet; sidechain source deferred to "
                "the devices-convergence re-plan"
            )
            return
        args = {
            **parent_kv,
            "action": "set_input_routing",
            "device_index": device_at,
            "type_display_name": src["name"],
        }
        channel = (
            device["sidechain_source_channel"]
            if "sidechain_source_channel" in keys else None
        )
        if channel is not None:
            args["channel_display_name"] = channel
        plan.add(ToolCall(
            tool="ableton_device",
            args=args,
            key=f"device_sidechain:{device['id']}",
            purpose=(
                f"sidechain {device['display_name']!r} on {parent_kind} "
                f"{parent_name!r} ← source {src['name']!r}"
            ),
        ))

    for t in by_id.values():
        if t["kind"] == "master":
            parent_kv: dict[str, object] = {"master": True}
            parent_kind = "master"
        else:
            track_at = Q.get_ableton_link(
                conn, session_id=session_id, db_kind="track", db_id=t["id"]
            )
            if track_at is None:
                continue
            parent_kv = {"track_index": track_at}
            parent_kind = "track"
        for chain in Q.get_device_chains_for_track(conn, t["id"]):
            for device in Q.get_devices_for_chain(conn, chain["id"]):
                _emit_for_device(device, parent_kv, parent_kind, t["name"])

    for r in returns:
        return_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="return", db_id=r["id"]
        )
        if return_at is None:
            continue
        for chain in Q.get_device_chains_for_return(conn, r["id"]):
            for device in Q.get_devices_for_chain(conn, chain["id"]):
                _emit_for_device(
                    device, {"return_index": return_at}, "return", r["name"]
                )

    return plan
