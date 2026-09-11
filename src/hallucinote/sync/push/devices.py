"""Mix-half planner: device chains (instruments + effects + parameters)."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from hallucinote.analyzer_identity import is_analyzer_device
from hallucinote.capture import is_sidechain_enable_param
from hallucinote.db import queries as Q
from hallucinote.paths import resolve_audio_path, same_file_path, song_dir_for_conn

from ._core import PushPlan, ToolCall, build_node_addr
from .probe import linked_device_parents

# SYN-RACK-PRESET-RELINK: a browser_path whose leaf is a preset FILE (.adg rack
# preset / .adv device preset) names loadable preset CONTENT, so the load handler
# honors it as a STANDALONE selector. A built-in-device browser_path (leaf = a
# class node, no extension) does not, and the handler refuses it standalone — so
# the planner must only emit a no-uri/no-query browser_path for a preset file.
# Mirrors hallucinote_mcp.handlers.device._browser_path_is_preset_file (separate
# packages, so the tiny check is duplicated rather than shared).
_PRESET_FILE_SUFFIXES: tuple[str, ...] = (".adg", ".adv")


def _browser_path_names_preset_file(browser_path: list[str]) -> bool:
    return bool(browser_path) and browser_path[-1].lower().endswith(
        _PRESET_FILE_SUFFIXES
    )


# PSH-DEVDUP: the three verdicts of "is this DB device's slot already occupied
# in Live?", answered from a freshly-probed device-chain map.
#
#   "absent"  — Live's authored chain does not run as deep as this device's
#               position, so a `load` (which Live tail-appends) lands it at the
#               right place. The ONLY verdict that may emit a load.
#   "present" — a device already sits at that position. Reconciliation should
#               have bound it; reaching the load branch anyway means the bind
#               was refused (class drift), so loading would DOUBLE the chain.
#   "unknown" — no probe data for this parent. "Can't determine" is not
#               "absent"; guessing here is exactly what doubled every FX chain
#               on `the-argument` (2026-08-08).
_LOAD_TARGET_ABSENT = "absent"
_LOAD_TARGET_PRESENT = "present"
_LOAD_TARGET_UNKNOWN = "unknown"


def classify_load_target(
    live_devices_by_parent: dict[tuple[str, int], list[dict]] | None,
    *,
    parent_kind: str,
    parent_index: int | None,
    position: int,
) -> tuple[str, dict | None]:
    """Decide whether a `load` at ``position`` on this parent is safe.

    Returns ``(verdict, occupant)`` where ``occupant`` is the probed Live device
    already sitting at ``position`` (only for ``"present"``).

    ``parent_index=None`` (a track/return with no resolved Live index) is
    ``"unknown"`` for the same reason an unprobed parent is: there is nothing to
    look the chain up by, so presence cannot be established.

    ``live_devices_by_parent=None`` means the caller supplied no probe at all
    (the pure-planner contract used by ``push_cli plan`` and the unit suite);
    the verdict is ``"absent"`` so the legacy behavior is preserved for callers
    that never had Live truth to begin with. The EXECUTE path always supplies a
    map, so the guard is live exactly where the corruption happened.

    The HallucinoteAnalyzer is excluded before positional comparison — it is
    measurement infrastructure the render appends, never an authored slot
    (SNP-8R4K).
    """
    if live_devices_by_parent is None:
        return _LOAD_TARGET_ABSENT, None
    if parent_index is None:
        return _LOAD_TARGET_UNKNOWN, None
    live_devices = live_devices_by_parent.get((parent_kind, parent_index))
    if live_devices is None:
        return _LOAD_TARGET_UNKNOWN, None
    for d in live_devices:
        if is_analyzer_device(d):
            continue
        if d.get("device_index") == position:
            return _LOAD_TARGET_PRESENT, d
    return _LOAD_TARGET_ABSENT, None


def live_device_at(
    live_devices_by_parent: dict[tuple[str, int], list[dict]] | None,
    *,
    parent_kind: str,
    parent_index: int | None,
    position: int,
) -> dict | None:
    """The probed Live device sitting at ``position``, or ``None`` for "no
    probe data about it".

    ``None`` is deliberately the answer to every uncertainty — no probe was
    supplied, the parent was not in it, the chain does not run that deep. The
    sample diff reads it as "cannot compare", which emits the assignment; the
    alternative (treating absence as "no sample there") would silently skip a
    device whose chain simply was not readable.

    Separate from :func:`classify_load_target`, which walks the same list to
    answer a different question and must keep its three verdicts apart: there,
    "cannot determine" REFUSES, because a load that guesses wrong doubles the
    signal chain. Here a re-assignment is harmless, so uncertainty collapses to
    one answer.
    """
    if live_devices_by_parent is None or parent_index is None:
        return None
    live_devices = live_devices_by_parent.get((parent_kind, parent_index))
    if live_devices is None:
        return None
    for d in live_devices:
        if is_analyzer_device(d):
            continue
        if d.get("device_index") == position:
            return d
    return None


def _resolve_device_sample(
    conn: sqlite3.Connection, ref: str, *, where: str,
) -> tuple[Path | None, str | None]:
    """Resolve a ``devices.audio_file`` reference to the absolute path the wire
    takes, or say why it cannot be — ``(path, None)`` or ``(None, reason)``.

    The sampler sibling of the clips phase's audio resolution, and refusing on
    the same two grounds: a connection with no database file on disk (so a
    song-relative reference has no anchor), and a file that is not there. A
    sampler pushed with nothing to play is a phase reporting OK on a track that
    will be silent, which is what the sync boundary contract exists to prevent.
    """
    song_dir = song_dir_for_conn(conn)
    if song_dir is None:
        return None, (
            f"{where}: audio_file={ref!r} names a sample, but this connection "
            "has no database file on disk, so there is no song directory to "
            "resolve a song-relative reference against. Open the song's DB "
            "through init_db(<song dir>/<slug>.db) and re-plan."
        )
    resolved = resolve_audio_path(song_dir, ref)
    if not resolved.is_file():
        return None, (
            f"{where}: its sample is not on disk — audio_file={ref!r} resolves "
            f"to {resolved} against song directory {song_dir}. The device was "
            "NOT pushed (a sampler with nothing loaded plays silence)."
        )
    return resolved, None


def _emit_sample_assignment(
    plan: PushPlan,
    conn: sqlite3.Connection,
    *,
    device: sqlite3.Row,
    parent_kv: dict[str, object],
    device_index: int,
    device_path: list[dict[str, int]] | None,
    parent_kind: str,
    parent_name: str,
    live_device: dict | None,
) -> bool:
    """Emit `assign_sample` for a device whose row names one, diffing against
    what Live already plays. Returns False when the device is BLOCKED and the
    caller should emit nothing further for it.

    Ordered BEFORE the parameter writes: probe row 18 recorded that
    ``replace_sample`` assigns the file, not whether it resets the device's
    parameters, so the assignment goes first — which is correct either way,
    where the reverse would silently undo a dialed `S Start` if it does.

    Two refusals, both of them the DB describing something Live cannot
    materialize, and both :meth:`PushPlan.blocked` so the push report says the
    song did not get what it asked for:

    * the probe says this device has no sample slot (no ``sample_file_path``
      key at all — see the MCP handler's ``_sample_surface``). Capability comes
      from the probe rather than a list of sampler class names, so a sampler
      nobody enumerated still works;
    * the file is not resolvable or not on disk.

    Without probe data the assignment is emitted unconditionally: it is
    re-callable, so re-assigning a sample Live already carries costs a call and
    changes nothing, while skipping one it does not carry leaves the track
    silent.
    """
    keys = device.keys()
    ref = device["audio_file"] if "audio_file" in keys else None
    if not ref:
        return True
    nested_note = f" (nested depth {len(device_path)})" if device_path else ""
    where = (
        f"devices: {device['display_name']!r}{nested_note} on {parent_kind} "
        f"{parent_name!r}"
    )
    if live_device is not None and "sample_file_path" not in live_device:
        live_class = (
            live_device.get("class_display_name")
            or live_device.get("class_name")
            or "?"
        )
        plan.blocked(
            f"{where}: the DB assigns the sample {ref!r}, but the device at "
            f"that position in Live is {live_class!r}, which has no sample "
            "slot. Only a sampler instrument takes one (Simpler, and Live's "
            "Sampler). Nothing was pushed for this device. Fix: author a "
            "Simpler at this position, or drop audio_file from the device row."
        )
        return False
    resolved, reason = _resolve_device_sample(conn, str(ref), where=where)
    if resolved is None:
        plan.blocked(reason or f"{where}: sample could not be resolved")
        return False
    live_path = (live_device or {}).get("sample_file_path")
    if live_path and same_file_path(resolved, Path(str(live_path))):
        return True
    args: dict[str, object] = {
        "action": "assign_sample",
        **parent_kv,
        "device_index": device_index,
        # ABSOLUTE by contract — the wire refuses a relative path, and Live
        # resolves nothing against a working directory.
        "sample_path": str(resolved),
    }
    if device_path:
        args["device_path"] = device_path
    plan.add(ToolCall(
        tool="ableton_device",
        args=args,
        key=f"device_sample:{device['id']}",
        purpose=(
            f"{parent_name} / {device['display_name']}{nested_note} "
            f"plays {ref}"
        ),
    ))
    return True


def build_device_load_args(
    device: sqlite3.Row,
    *,
    parent_kv: dict[str, object],
    parent_kind: str,
    parent_name: str,
) -> tuple[dict[str, object], list[str]]:
    """Build the ``ableton_device(action='load')`` kwargs for ONE DB device row,
    plus any diagnostic notes the identity resolution produced.

    The single place the DB's three load selectors — ``preset_query`` (portable),
    ``preset_uri`` (per-machine), ``browser_path`` (fallback identity, and a
    STANDALONE selector when its leaf is a ``.adg``/``.adv`` preset file) — are
    turned into wire args. Two callers need the identical answer and must never
    drift apart: the push planner's load emission, and
    :mod:`hallucinote.sync.chain_rebuild`, which reloads the same device after
    demolishing the chain around it. A rebuild that resolved a device's identity
    differently from push would reload a DIFFERENT device than the one it
    deleted, which is the one failure the rebuild exists to prevent.

    Live 12.4 has no public reorder API — a load always lands at the END of the
    destination chain, so no ``position`` is emitted. Order comes from loading in
    ascending DB ``position``. The destination is the parent's MAIN chain, a
    node-itself address (``terminal == parent_kind``); nested devices are never
    loaded, they arrive with the rack preset (DEEP-RACK-ADDR §3c).
    """
    notes: list[str] = []
    load_args: dict[str, object] = {
        "action": "load",
        "node": build_node_addr(parent_kv, terminal=parent_kind),
        "kind": device["kind"],
    }
    # Arc 7-tail / E3 (W13-A v1.0): the captured browser path is a fallback
    # identity for the cross-machine "same plugin, different catalog id" case.
    # Threaded alongside whichever of preset_query / preset_uri is emitted — the
    # load handler uses it when the per-machine FileId in preset_uri doesn't
    # resolve. Extracted once up front so every branch below can attach it.
    browser_path_raw = (
        device["browser_path_json"]
        if "browser_path_json" in device.keys() else None
    )
    browser_path_value: list[str] | None = None
    if browser_path_raw is not None:
        try:
            browser_path_value = json.loads(browser_path_raw)
        except (json.JSONDecodeError, TypeError) as exc:
            notes.append(
                f"device {device['display_name']!r} on {parent_kind} "
                f"{parent_name!r}: stored browser_path is not valid "
                f"JSON ({exc}); loading without the fallback identity "
                "path — cross-machine FileId mismatch will fail"
            )
    # Sweep B: preset_query (portable) takes precedence over preset_uri
    # (per-machine). The MCP load handler refuses if both are set, so
    # exactly one is chosen here. Composer's expressed preference wins.
    preset_query_raw = (
        device["preset_query"] if "preset_query" in device.keys() else None
    )
    if preset_query_raw is not None:
        try:
            load_args["preset_query"] = json.loads(preset_query_raw)
        except (json.JSONDecodeError, TypeError) as exc:
            notes.append(
                f"device {device['display_name']!r} on {parent_kind} "
                f"{parent_name!r}: stored preset_query is not valid JSON "
                f"({exc}); falling back to preset_uri / kind-only load"
            )
            if device["preset_uri"] is not None:
                load_args["preset_uri"] = device["preset_uri"]
                if browser_path_value is not None:
                    load_args["browser_path"] = browser_path_value
            elif browser_path_value is not None and (
                _browser_path_names_preset_file(browser_path_value)
            ):
                # Corrupt preset_query + no preset_uri: still honor a
                # standalone preset-file browser_path, or the rack loads
                # EMPTY — the same SYN-RACK-PRESET-RELINK gap the main elif
                # below closes for the (common) no-preset_query case.
                load_args["browser_path"] = browser_path_value
    elif device["preset_uri"] is not None:
        load_args["preset_uri"] = device["preset_uri"]
        if browser_path_value is not None:
            load_args["browser_path"] = browser_path_value
    elif browser_path_value is not None and _browser_path_names_preset_file(
        browser_path_value
    ):
        # SYN-RACK-PRESET-RELINK: no preset_query / preset_uri, but a captured
        # browser_path whose leaf is a preset FILE (.adg/.adv). The load handler
        # honors that as a STANDALONE selector (loads the preset content, not a
        # bare class). This is the common /song-snapshot case: capture can't
        # probe preset_uri, so a rack preset's only identity is its
        # browser_path — without emitting it the device loaded as an empty rack
        # (0 chains) and every nested param write failed. Only emit it
        # standalone for a preset FILE; a built-in-device browser_path (no
        # extension) stays kind-only (the handler refuses a standalone
        # non-preset-file browser_path).
        load_args["browser_path"] = browser_path_value
    return load_args, notes


# DEV-5R8Q: the occupied-slot refusal's remedy sentence, shared by the two
# refusal messages and by `skills/ableton-push/SKILL.md`'s halt entry. Before
# `chain-rebuild` existed the refusal could only tell the operator to accept
# Live's order (re-snapshot) or fix it by hand; the rebuild is the third answer
# and the only one that makes the DB's order true without losing the downstream
# devices' dialed state.
def _rebuild_remedy(parent_kind: str, parent_name: str, position: int) -> str:
    """The occupied-slot refusal's third remedy, addressed at ONE parent.

    Rendered rather than stored as a constant because the command's parent
    argument differs per parent kind (the master is a singleton flag, a
    track/return is named), and a refusal that names a command the operator
    cannot paste is not a remedy.
    """
    where = (
        "--master" if parent_kind == "master"
        else f"--{parent_kind} {parent_name!r}"
    )
    return (
        f"run `hallucinote chain-rebuild --song <slug> {where} "
        f"--from-position {position}` — it captures the chain, rebuilds it in "
        f"the DB's order and restores every downstream device's parameters "
        f"(the same orchestration `push execute --reconcile-chains` runs for "
        f"you)"
    )


@dataclass(frozen=True)
class OccupiedSlot:
    """One parent whose DB-authored chain collides with Live's at a position.

    ``from_position`` is the SHALLOWEST colliding position on that parent — the
    point a chain rebuild has to start from, because everything at or below it
    must come out before the DB's order can be re-established.
    """
    parent_kind: str          # 'track' | 'return' | 'master'
    parent_index: int         # Live index; 0 for the master singleton
    parent_name: str
    from_position: int
    occupant_class: str


def occupied_slots(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    live_devices_by_parent: dict[tuple[str, int], list[dict]],
) -> list[OccupiedSlot]:
    """Every parent where :func:`plan_push_devices` would hit the
    ``_LOAD_TARGET_PRESENT`` refusal, with the position the rebuild must start at.

    This is the occupied-slot branch's condition, lifted out so the reconcile
    caller (``push execute --reconcile-chains``) fires on EXACTLY what the
    planner refuses on — one rule, two readers. Answering it here rather than
    inside the planner is forced by the plan/dispatch split: a rebuild is a
    read-then-write sequence (probe params, journal, delete, load, restore) and
    a ``PushPlan`` is a flat call list built before anything is dispatched, so
    the rebuild has to run BEFORE the devices phase plans, not inside it. Once
    it has, the planner sees a linked, in-order chain and emits no load at all.

    ``_LOAD_TARGET_UNKNOWN`` is deliberately NOT included: a chain that could
    not be read is one a rebuild must not touch, since the capture it would
    journal is the same read that just failed.
    """
    targets: dict[tuple[str, int], OccupiedSlot] = {}
    tracks, returns, master = linked_device_parents(
        conn, song_id=song_id, session_id=session_id,
    )
    for parents, parent_kind, get_devices_fn in (
        (tracks, "track", Q.get_devices_for_track),
        (returns, "return", Q.get_devices_for_return),
        (master, "master", Q.get_devices_for_track),
    ):
        for parent in parents:
            ableton_index = parent["ableton_index"]
            for db_dev in get_devices_fn(conn, parent["db_id"]):
                if db_dev["kind"] == "placeholder" or is_analyzer_device(db_dev):
                    continue
                if Q.get_ableton_link(
                    conn, session_id=session_id,
                    db_kind="device", db_id=db_dev["id"],
                ) is not None:
                    continue
                verdict, occupant = classify_load_target(
                    live_devices_by_parent,
                    parent_kind=parent_kind,
                    parent_index=ableton_index,
                    position=db_dev["position"],
                )
                if verdict != _LOAD_TARGET_PRESENT:
                    continue
                key = (parent_kind, ableton_index)
                found = OccupiedSlot(
                    parent_kind=parent_kind,
                    parent_index=ableton_index,
                    parent_name=parent["name"],
                    from_position=db_dev["position"],
                    occupant_class=(
                        (occupant or {}).get("class_display_name")
                        or (occupant or {}).get("class_name")
                        or "?"
                    ),
                )
                prior = targets.get(key)
                if prior is None or found.from_position < prior.from_position:
                    targets[key] = found
    return sorted(
        targets.values(), key=lambda t: (t.parent_kind, t.parent_index),
    )


def plan_push_devices(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    live_devices_by_parent: dict[tuple[str, int], list[dict]] | None = None,
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
      3. For each linked device whose row carries `audio_file`, emit
         `ableton_device(action='assign_sample', ...)` BEFORE that device's
         parameter writes — a sampler is handed its file first, then dialed.
         See `_emit_sample_assignment` for the diff and the two refusals.
      4. For each linked device, emit
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
      5. DEEP-RACK-ADDR: for each linked top-level RACK device, recurse its
         nested chains and emit `set_parameter` with the canonical `device_path`
         for every nested device's dialed params (to arbitrary depth). Nested
         devices are NOT loaded — they arrive with the rack preset — so push
         only sets their params. This is what makes a deep by-ear fix survive a
         `build.py` rebuild.

    ``live_devices_by_parent`` (PSH-DEVDUP) is a freshly-probed
    ``{(parent_kind, parent_index): [live device dict, ...]}`` map — Live's
    CURRENT device chains, the same shape ``probe_and_link`` consumes. Supplying
    it makes step 2 a real diff: a load is emitted only for a position Live's
    authored chain does not already reach. Without it the planner had no way to
    tell "this device is missing" from "this device is present but unlinked",
    and answered `load` to both — which appends a SECOND copy of the whole
    post-instrument FX chain onto a set that already carries it, silently, while
    reporting every call ok (observed on `the-argument`, 2026-08-08: nine tracks,
    every effect doubled). When the map is supplied but says the slot is
    occupied — or says nothing at all about that parent — the planner raises a
    hard :meth:`PushPlan.error`, halting the phase BEFORE dispatch. Refusing to
    guess is the contract: a doubled signal chain is silent, audible, and
    compounds on every push, so "load nothing and say why" strictly beats it.

    ``None`` (the default) preserves the pre-PSH-DEVDUP behavior for callers
    that have no Live truth to offer (``push_cli plan``, unit tests).
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
                        live_devices_by_parent=live_devices_by_parent,
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
                    live_devices_by_parent=live_devices_by_parent,
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
                    live_devices_by_parent=live_devices_by_parent,
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
    live_devices_by_parent: dict[tuple[str, int], list[dict]] | None = None,
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
        # PSH-DEVDUP: before emitting a load, establish that Live's chain does
        # NOT already carry this device. Live 12.4 has no reorder API, so a load
        # tail-APPENDS — which means "load onto a chain that already has it"
        # doesn't repair anything, it doubles the signal path (and the doubling
        # compounds on every subsequent push). Unlinked no longer implies
        # absent: a chain loaded into Live by hand or by /song-pick-instruments
        # enters the DB later, via the capture snapshot, and never had a link.
        verdict, occupant = classify_load_target(
            live_devices_by_parent,
            parent_kind=parent_kind,
            parent_index=0 if parent_kind == "master" else parent_at,
            position=device["position"],
        )
        if verdict == _LOAD_TARGET_PRESENT:
            occupant_class = (
                (occupant or {}).get("class_display_name")
                or (occupant or {}).get("class_name")
                or "?"
            )
            occupant_name = (occupant or {}).get("name") or occupant_class
            plan.error(
                f"devices: REFUSING to load {device['kind']!r} "
                f"('{device['display_name']}') at position {device['position']} "
                f"on {parent_kind} {parent_name!r} — that slot is ALREADY "
                f"occupied in Live by {occupant_name!r} ({occupant_class}), and "
                f"the DB has no link to it, so this device could not be matched "
                f"to what is there. Live has no reorder API: a load would "
                f"APPEND a second copy and silently double the chain. Nothing "
                f"was pushed for this track. Three fixes, in the order to try "
                f"them: run `push_cli probe-and-link <session> --song <slug> "
                f"--probe` to bind the chain that is already there; or "
                f"re-snapshot the set (/song-snapshot) so the DB describes what "
                f"Live has; or, when the DB's ORDER is the one you want and "
                f"Live's is wrong, "
                + _rebuild_remedy(parent_kind, parent_name, device["position"])
                + ". Then re-run execute."
            )
            return
        if verdict == _LOAD_TARGET_UNKNOWN:
            plan.error(
                f"devices: REFUSING to load {device['kind']!r} "
                f"('{device['display_name']}') at position {device['position']} "
                f"on {parent_kind} {parent_name!r} — Live's device chain for "
                f"that {parent_kind} could not be read, so whether the chain is "
                f"already there is UNKNOWN. Appending on a guess would double "
                f"the signal path if it is. Nothing was pushed for this track. "
                f"Fix: re-run `execute --probe` once Live answers (idempotent)."
            )
            return
        load_args, load_notes = build_device_load_args(
            device, parent_kv=parent_kv, parent_kind=parent_kind,
            parent_name=parent_name,
        )
        for note in load_notes:
            plan.warn(note)
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

    # SMP-6V2K: the sample comes before the params — see `_emit_sample_assignment`
    # for why the order is load-bearing. A blocked assignment stops this device
    # entirely: dialing `S Start` on a sampler holding nothing is dialing air.
    if not _emit_sample_assignment(
        plan, conn,
        device=device,
        parent_kv=parent_kv,
        device_index=device_at,
        device_path=None,
        parent_kind=parent_kind,
        parent_name=parent_name,
        live_device=live_device_at(
            live_devices_by_parent,
            parent_kind=parent_kind,
            parent_index=0 if parent_kind == "master" else parent_at,
            position=device["position"],
        ),
    ):
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
    # SNP-2H9F: re-assert nested-param overrides on a preset-seeded device. The
    # override's path addresses a DESCENDANT instantiated by the preset load, so
    # push sets it via set_parameter (never create_device_chain — the preset's
    # waveform/samples and structure survive, nothing duplicates). The override
    # table is empty for the common (non-preset) device, so this is a no-op there.
    _emit_param_override_writes(
        plan, conn,
        device=device,
        parent_kv=parent_kv,
        device_index=device_at,
        parent_kind=parent_kind,
        parent_name=parent_name,
    )


def _param_value_kv(p: sqlite3.Row) -> tuple[dict[str, object], str] | None:
    """SYN-9F2L wire-form selection for ONE stored param/override row -> the
    `set_parameter` value kwargs + a human description, or None when the row has
    no writable form (no display value and no normalized value). Shared by
    `_emit_param_writes` (device_parameters) and `_emit_param_override_writes`
    (device_param_overrides) — both column shapes carry value_display /
    value_items_json / value_normalized / value_raw, so they dial identically:
      * captured value_items -> a known enum: value_type='enum' with the display
        string (the handler validates membership);
      * value_raw present -> the UNCLAMPED raw value on the wire (DEV-4P7R) — the
        only form for a quantized continuous param whose raw range != [0,1] and
        whose display is non-monotonic; checked BEFORE display so an explicit raw
        wins even when a readable display hint is also stored on the row;
      * display string present -> value_display (the handler inverts the param's
        own display curve — exact, and safe for center-zero params);
      * normalized only -> the raw value (stringified on the wire). The handler
        has no value_normalized kwarg, so this rides `value` as raw and only
        round-trips when the param's raw range IS [0,1] — else use value_raw;
      * neither -> None (the caller surfaces an operator ALERT, never a silent drop).
    """
    display = (p["value_display"] or "").strip()
    if p["value_items_json"] is not None:
        if not display:
            return None
        return ({"value": display, "value_type": "enum"}, f"enum {display!r}")
    if p["value_raw"] is not None:
        return ({"value": str(p["value_raw"]), "value_type": "continuous"},
                f"raw {p['value_raw']:g}")
    if display:
        return ({"value_display": display, "value_type": "continuous"},
                f"display {display!r}")
    if p["value_normalized"] is not None:
        return ({"value": str(p["value_normalized"]), "value_type": "continuous"},
                f"normalized {p['value_normalized']:g}")
    return None


def _emit_param_override_writes(
    plan: PushPlan,
    conn: sqlite3.Connection,
    *,
    device: sqlite3.Row,
    parent_kv: dict[str, object],
    device_index: int,
    parent_kind: str,
    parent_name: str,
) -> None:
    """Emit a node-addressed `set_parameter` for each stored nested-param override
    on a preset-seeded device (SNP-2H9F). Each override's ``path_json`` is the
    NodeAddr descent to a device nested inside the preset; push addresses it from
    the top-level preset's Live index (``device_index``) + that path, exactly like
    a nested ``device_parameters`` write — but the override exists WITHOUT a nested
    DB device row (the preset, not the DB, owns the tree). No load, no chain
    creation: just the param set after the preset instantiates the descendant."""
    unwritable: list[str] = []
    for o in Q.get_device_param_overrides(conn, device["id"]):
        try:
            path = json.loads(o["path_json"])
        except (json.JSONDecodeError, TypeError) as exc:
            plan.alert(
                f"device {device['display_name']!r} on {parent_kind} "
                f"{parent_name!r}: param override {o['name']!r} has a malformed "
                f"path ({exc}); the override was NOT pushed"
            )
            continue
        kv = _param_value_kv(o)
        if kv is None:
            unwritable.append(o["name"])
            continue
        value_kv, chosen = kv
        args: dict[str, object] = {
            "action": "set_parameter",
            "node": build_node_addr(
                parent_kv, device_index=device_index, device_path=path,
            ),
            "parameter_name": o["name"],
            **value_kv,
        }
        plan.add(ToolCall(
            tool="ableton_device",
            args=args,
            key=f"device_param_override:{device['id']}:{o['path_json']}:{o['name']}",
            purpose=(
                f"{parent_name} / {device['display_name']} "
                f"(preset override depth {len(path)}) / {o['name']} = {chosen}"
            ),
        ))
    if unwritable:
        plan.alert(
            f"device {device['display_name']!r} on {parent_kind} {parent_name!r}: "
            f"{len(unwritable)} param override(s) have no writable form "
            f"({', '.join(unwritable[:3])}{'...' if len(unwritable) > 3 else ''}) "
            "— no display value and no normalized value stored; the override was "
            "NOT pushed"
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
        kv = _param_value_kv(p)
        if kv is None:
            unwritable.append(p["name"])
            continue
        value_kv, chosen = kv
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

    NODE-ADDR Chunk C: each chain may also carry authored per-drum properties
    (choke_group / out_note). Those are re-asserted on the DrumChain via the
    `chain` terminal after the rack loads — like nested params, they survive a
    rebuild only if pushed. ``rack_path`` is this rack's own device_path from the
    top-level rack ([] when ``rack_device_id`` IS the top-level rack).
    """
    rack_path = Q.get_device_nesting_path(conn, rack_device_id)
    for chain in Q.get_device_chains_for_rack_device(conn, rack_device_id):
        _emit_chain_property_calls(
            plan,
            chain=chain,
            parent_kv=parent_kv,
            top_device_index=top_device_index,
            rack_path=rack_path,
            parent_kind=parent_kind,
            parent_name=parent_name,
        )
        for nested in Q.get_devices_for_chain(conn, chain["id"]):
            # Defensive: a clean DB never nests a placeholder or the analyzer,
            # but a legacy-polluted one might — skip both (mirrors the
            # top-level guards) rather than emit an unaddressable write.
            if nested["kind"] == "placeholder" or is_analyzer_device(nested):
                continue
            device_path = Q.get_device_nesting_path(conn, nested["id"])
            # A sampler inside a rack gets its file the same way a top-level one
            # does, addressed by its device_path. `live_device=None` because the
            # chain probe reads only top-level devices: nothing about a nested
            # device is known, so the assignment is emitted rather than diffed.
            if not _emit_sample_assignment(
                plan, conn,
                device=nested,
                parent_kv=parent_kv,
                device_index=top_device_index,
                device_path=device_path,
                parent_kind=parent_kind,
                parent_name=parent_name,
                live_device=None,
            ):
                continue
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


def _emit_chain_property_calls(
    plan: PushPlan,
    *,
    chain: sqlite3.Row,
    parent_kv: dict[str, object],
    top_device_index: int,
    rack_path: list[dict[str, int]],
    parent_kind: str,
    parent_name: str,
) -> None:
    """Emit a `set_chain_property` call for a chain's stored authored properties
    (NODE-ADDR Chunk C per-drum choke/out_note + Chunk F mixer mute/solo/volume/
    pan). The DB stores only non-defaults (choke != 0, out_note != in_note,
    mute/solo only when set, volume/pan only off the preset default), so a
    default-only chain emits nothing. Addressed by the `chain` terminal:
    device_index = the top-level rack, path = this rack's own path (empty for the
    top-level rack), chain_index = the chain's DB position. mute/solo are stored
    0/1 and re-emitted as bools (the handler's wire type)."""
    keys = chain.keys()
    choke = chain["choke_group"] if "choke_group" in keys else None
    out_note = chain["out_note"] if "out_note" in keys else None
    mute = chain["mute"] if "mute" in keys else None
    solo = chain["solo"] if "solo" in keys else None
    volume = chain["volume"] if "volume" in keys else None
    pan = chain["pan"] if "pan" in keys else None
    if all(v is None for v in (choke, out_note, mute, solo, volume, pan)):
        return
    node = build_node_addr(
        parent_kv,
        device_index=top_device_index,
        device_path=rack_path or None,
        terminal="chain",
        chain_index=int(chain["position"]),
    )
    args: dict[str, object] = {"action": "set_chain_property", "node": node}
    set_desc: list[str] = []
    if choke is not None:
        args["choke_group"] = int(choke)
        set_desc.append(f"choke_group={int(choke)}")
    if out_note is not None:
        args["out_note"] = int(out_note)
        set_desc.append(f"out_note={int(out_note)}")
    if mute is not None:
        args["mute"] = bool(mute)
        set_desc.append(f"mute={bool(mute)}")
    if solo is not None:
        args["solo"] = bool(solo)
        set_desc.append(f"solo={bool(solo)}")
    if volume is not None:
        args["volume"] = float(volume)
        set_desc.append(f"volume={float(volume):.3f}")
    if pan is not None:
        args["pan"] = float(pan)
        set_desc.append(f"pan={float(pan):.3f}")
    plan.add(ToolCall(
        tool="ableton_device",
        args=args,
        key=f"device_chain_props:{chain['id']}",
        purpose=(
            f"{parent_name} / chain {chain['position']}: "
            f"{', '.join(set_desc)}"
        ),
    ))


def sidechain_armed_in_db(
    conn: sqlite3.Connection, device_id: str,
) -> bool:
    """True when the DB's stored parameters show this device's sidechain ENABLED.

    Only DIALED parameters are stored (defaults are implied by absence), so an
    absent enable param means off. A stored one is read off whichever numeric
    channel carries it — ``value_normalized`` / ``value_raw`` — falling back to
    the display string for an enum-shaped row with no numeric form.
    """
    for row in Q.get_device_parameters(conn, device_id):
        if not is_sidechain_enable_param(row["name"]):
            continue
        keys = row.keys()
        for field in ("value_normalized", "value_raw"):
            if field in keys and row[field] is not None:
                return float(row[field]) > 0.5
        display = str(row["value_display"] or "").strip().lower()
        return display in {"on", "1", "true", "enabled", "yes"}
    return False


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

    #536: the phase also emits a READ — ``get_input_routing``, keyed
    ``device_sidechain_probe:<device id>`` — for each device whose sidechain is
    ARMED but carries no source. ``has_input_routing`` is a Live fact the DB
    cannot hold, and it is the only thing that separates "the source is simply
    unset" from "the source can never be captured, so this push just erased it";
    ``apply_push_results`` turns a ``False`` into the operator warning.
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
            # No source authored. Usually nothing to do — but #536: a device
            # whose sidechain is ARMED and which exposes no input-routing
            # surface can never HAVE a captured source, so this rebuild
            # materializes it armed and pointed at nothing, silently undoing
            # whatever the operator set by hand in Live. Whether the surface
            # exists is a LIVE fact (`has_input_routing`), not a DB one, so ask
            # Live for it and let the apply step say so. Asking only for armed
            # devices is what keeps the Compressor path (#374, the common case)
            # silent: a warning that fired there would train the operator to
            # ignore all of them.
            if not sidechain_armed_in_db(conn, device["id"]):
                return
            device_at = Q.get_ableton_link(
                conn, session_id=session_id, db_kind="device", db_id=device["id"]
            )
            if device_at is None:
                plan.warn(
                    f"device {device['display_name']!r} on {parent_kind} "
                    f"{parent_name!r} not linked yet; sidechain-surface check "
                    "deferred to the devices-convergence re-plan"
                )
                return
            plan.add(ToolCall(
                tool="ableton_device",
                args={
                    **parent_kv,
                    "action": "get_input_routing",
                    "device_index": device_at,
                },
                key=f"device_sidechain_probe:{device['id']}",
                purpose=(
                    f"check whether {device['display_name']!r} on {parent_kind} "
                    f"{parent_name!r} exposes a sidechain SOURCE surface — its "
                    "sidechain is armed but the DB carries no source"
                ),
            ))
            return
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
