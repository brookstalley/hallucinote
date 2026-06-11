"""Mix-half planner: device chains (instruments + effects + parameters)."""
from __future__ import annotations

import json
import sqlite3

from hallucinote.db import queries as Q

from ._core import PushPlan, ToolCall


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
         fallback. Nested rack chains aren't pushed here (snapshot doesn't
         capture them).
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
    # SYN-2M9P: master devices are CONFIGURE-ONLY across the whole stack.
    # Ableton Live 12.4 has no LOM path to load a device onto the master
    # strip, so DEV-2M9K made the load_handler + render setup refuse master
    # loads ("place by hand once" contract). The planner must mirror that:
    # emitting `device.load(master=True)` for an unlinked master device is an
    # impossible call that FAILS at execute time and HALTS the devices phase
    # (outcome='partial'), leaving every downstream phase PENDING. Skip the
    # load with a place-by-hand note; set_parameter writes (below) still fire
    # once the hand-placed device is linked.
    if parent_kind == "master" and device_at is None:
        plan.warn(
            f"master device {device['display_name']!r} (kind {device['kind']!r}) "
            "not loadable via LOM — Live 12.4 has no master-strip load path; "
            "place it on the master by hand once, then re-run push to record "
            "its index and write parameters"
        )
        return
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
        load_args = {
            **parent_kv,
            "action": "load",
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

    params = Q.get_device_parameters(conn, device["id"])
    unwritable: list[str] = []
    for p in params:
        # SYN-9F2L: pick the wire form per param.
        #   * captured value_items → a known enum: value_type='enum' with the
        #     display string (the handler validates membership);
        #   * display string present → value_display (the handler inverts the
        #     param's own display curve — exact, and safe for center-zero
        #     params where a naive normalized fraction dials the wrong
        #     direction);
        #   * normalized only → the raw `value` (stringified on the wire);
        #   * neither → warn, never drop silently.
        # The executor retries a refused display write once (as enum, or with
        # the DB's normalized value) — see push_execute's set_parameter
        # fallback.
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
        plan.add(ToolCall(
            tool="ableton_device",
            args={
                "action": "set_parameter",
                **parent_kv,
                "device_index": device_at,
                "parameter_name": p["name"],
                **value_kv,
            },
            key=f"device_parameter:{device['id']}:{p['name']}",
            purpose=(
                f"{parent_name} / {device['display_name']} / "
                f"{p['name']} = {chosen}"
            ),
        ))
    if unwritable:
        # Operator-actionable (SYN-9F2L): the dialed intent was authored but
        # can't be pushed — surface it in the push report, not the diagnostic
        # notes channel where it gets discarded.
        plan.alert(
            f"device {device['display_name']!r} on {parent_kind} {parent_name!r}: "
            f"{len(unwritable)} param(s) have no writable form "
            f"({', '.join(unwritable[:3])}{'...' if len(unwritable) > 3 else ''}) "
            "— no display value and no normalized value stored; the dialed "
            "intent was NOT pushed"
        )
