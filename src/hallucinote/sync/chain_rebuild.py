"""DEV-5R8Q — replace or reorder a device without destroying the mix work below it.

Live 12.4 exposes no device-reorder API and ``ableton_device(action='load')``
tail-appends, so "swap the instrument at position 1 and keep EQ Eight + Erosion
downstream" has no in-place form. The only sequence Live permits is
delete-descending then reload-in-order — and that sequence, run by hand, loses
every downstream effect's dialed state. On a heavily-tuned chain that is not a
missing convenience; it quietly destroys mix work and reports nothing.

This module is that sequence done safely, in five phases:

    capture   → probe the parent's live chain and read, per device, its full
                parameter set, its input routing (the sidechain SOURCE lives
                here) and, for a rack, its nested chain properties + drum pads.
    journal   → write ALL of it to disk, atomically, BEFORE the first delete.
    demolish  → mute the parent (the chain is briefly empty and the raw
                instrument would otherwise blast through the mix), then delete
                descending from the tail to ``from_position``.
    rebuild   → load in ascending DB ``position`` order, letting Live's
                tail-append produce the order the DB authors.
    restore   → re-apply parameters / routing / chain properties from the
                journal, RE-PROBE, and refuse to report success unless the
                class order and every restored value read back equal. Only then
                is the parent unmuted and the journal deleted.

The journal is the load-bearing part. A crash between demolish and rebuild is
the failure that destroys mix work, and only something on disk survives it — so
the journal is written before the first delete and removed only after the verify
pass passes. :func:`resume` replays a stranded one with nothing but the file.

Two callers share this one entry point (the owner's 2026-08-07 ruling that they
be designed together rather than grown in isolation): the interactive
``hallucinote chain-rebuild`` CLI, and ``push execute --reconcile-chains``.
The push caller is opt-in per push and never automatic — a destructive
operation that holds Live for real wall-clock time is not something a routine
push starts on its own.

**Non-goals.** No in-place reorder (the LOM has none). No rebuild of NESTED rack
content: a rack is restored by reloading its preset, so structure added inside
it in Live, and nested-device parameters dialed by ear that never reached the
DB, are both out of reach. What IS carried is the rack's own parameters and its
authored per-chain properties. :func:`plan_rebuild` refuses outright any device
in the span whose identity does not name something loadable, and the residual
loss is documented in ``docs/song-authoring-conventions.md``
("Reordering / inserting mid-chain" → "In-rack hand edits do not survive a
rebuild").
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from hallucinote.analyzer_identity import is_analyzer_device
from hallucinote.db import mutations as M, queries as Q
from hallucinote.paths import song_dir_for_conn
from hallucinote.sync.live_escalation import await_escalated, escalated_job_id

from .push._core import build_node_addr
from .push.devices import (
    OccupiedSlot,
    build_device_load_args,
    occupied_slots,
)


JOURNAL_VERSION = 1
# Deliberately NOT added to a song's .gitignore. A journal exists only between
# the first delete and a passing verify, so one still sitting here means a
# rebuild died holding a chain's captured state — exactly the thing an operator
# needs to notice. An ignored directory is one nothing shows you.
JOURNAL_DIRNAME = ".rebuild"

# Phase markers written into the journal as the rebuild advances. A resumed
# journal reads its marker only to REPORT where the run died; the replay itself
# re-derives Live's state by probing, because a crash can land between the write
# of a marker and the call it describes and only Live knows which.
PHASE_JOURNALED = "journaled"
PHASE_DEMOLISHED = "demolished"
PHASE_REBUILT = "rebuilt"
PHASE_RESTORED = "restored"
PHASE_VERIFIED = "verified"


class RebuildRefused(Exception):
    """The rebuild declined BEFORE touching anything.

    Every refusal reaches this exception with nothing deleted, nothing muted and
    no journal on disk. Deleting a device that cannot be put back is
    unrecoverable, so the checks that could refuse all run first.
    """


class RebuildVerifyFailed(Exception):
    """The post-rebuild read-back disagreed with what was asked for.

    Carries the journal path, which is deliberately still on disk: the chain is
    in an unknown state and the record of what it held is the only way back.
    """

    def __init__(self, message: str, *, journal_path: Path | None = None) -> None:
        super().__init__(message)
        self.journal_path = journal_path


@dataclass
class RebuildResult:
    """What one rebuild did, and everything it could not carry across.

    ``alerts`` is where a parameter that could not be restored is
    named here, never dropped. ``ok`` is False only on a path that also raised.
    """
    parent_kind: str
    parent_index: int
    parent_name: str = ""
    from_position: int = 0
    journal_path: Path | None = None
    deleted: list[str] = field(default_factory=list)
    loaded: list[str] = field(default_factory=list)
    restored_params: int = 0
    alerts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ok: bool = True

    def describe(self) -> str:
        where = (
            "master"
            if self.parent_kind == "master"
            else f"{self.parent_kind} {self.parent_name!r} (#{self.parent_index})"
        )
        return (
            f"{where}: rebuilt from position {self.from_position} — "
            f"deleted {self.deleted}, loaded {self.loaded}, "
            f"{self.restored_params} parameter(s) restored"
            + (f"; {len(self.alerts)} alert(s)" if self.alerts else "")
        )


# ---------------------------------------------------------------------------
# Wire helpers
# ---------------------------------------------------------------------------


def _parent_kv(parent_kind: str, parent_index: int) -> dict[str, Any]:
    if parent_kind == "master":
        return {"master": True}
    if parent_kind == "track":
        return {"track_index": parent_index}
    if parent_kind == "return":
        return {"return_index": parent_index}
    raise ValueError(
        f"parent_kind must be 'track', 'return' or 'master', got {parent_kind!r}"
    )


def _flat_parent_params(parent_kind: str, parent_index: int) -> dict[str, Any]:
    """The FLAT parent addressing (``track_index`` / ``return_index`` /
    ``master``) the pre-NODE-ADDR actions still take — ``delete``,
    ``get_input_routing``, ``set_input_routing``, ``get_device_chains``,
    ``pad_info``. The node-addressed actions (``load``, ``get_parameters``,
    ``set_parameter``, ``set_chain_property``) take :func:`_parent_kv` through
    ``build_node_addr`` instead."""
    return dict(_parent_kv(parent_kind, parent_index))


def _send(send_fn: Callable[[Any], Any], tool: str, action: str,
          params: dict[str, Any]) -> tuple[bool, Any, str]:
    """Dispatch one MCP call and normalize the answer to
    ``(ok, result, error)``.

    Constructing the ``Request`` here (rather than making callers do it) keeps
    the lazy ``hallucinote_mcp`` import in one place: this module must import
    without the MCP package present, exactly like ``push_cli``.

    **An escalation is resolved here, not returned as success.** A call that
    outran Live's main-thread ceiling comes back ``ok=True`` carrying a job
    handle, and the work is still running. Booking that as a completed call is
    unusually costly in THIS module: a device load recorded as landed while
    Live is still loading it makes the very next call hit the occupied bout and
    be refused — raising partway through the one sequence that must not fail
    partway through, with the chain already gutted. So the handle is polled to
    a terminal state and the real outcome is what every caller sees.
    """
    from hallucinote_mcp.wire import Request  # type: ignore[import-not-found]

    resp = send_fn(Request(tool=tool, action=action, params=params))
    job_id = escalated_job_id(resp)
    if job_id is not None:
        resp = await_escalated(
            job_id=job_id,
            label=f"{tool}({action!r})",
            send_fn=send_fn,
            request_cls=Request,
            progress_fn=_escalation_progress,
            warnings_sink=_escalation_progress,
        )
    ok = bool(getattr(resp, "ok", False))
    result = getattr(resp, "result", None)
    error = getattr(resp, "error", None) or ""
    return ok, result, error


def _escalation_progress(message: str) -> None:
    """Where an escalation's progress and completion notes go.

    stderr, not stdout: a rebuild's stdout is its report, and a caller
    redirecting it should not have a Live-slowness note land in the middle of
    one. The operator still sees it — waiting minutes on a wedged main thread
    with no output is the case this exists to avoid.
    """
    print(message, file=sys.stderr)


def _live_class(device: dict[str, Any]) -> str:
    return device.get("class_display_name") or device.get("class_name") or ""


# ---------------------------------------------------------------------------
# Journal I/O
# ---------------------------------------------------------------------------


def journal_dir_for(song_dir: Path) -> Path:
    return Path(song_dir) / JOURNAL_DIRNAME


def journal_path_for(song_dir: Path, parent_kind: str, parent_index: int) -> Path:
    """One journal per parent — a rebuild is scoped to a single chain, and two
    concurrent rebuilds of the same chain would be a bug, not a case to
    support."""
    return journal_dir_for(song_dir) / f"{parent_kind}-{parent_index}.json"


def write_journal(path: Path, payload: dict[str, Any]) -> None:
    """Atomic write (temp sibling + ``os.replace``).

    The same treatment ``push_execute`` gives ``.last-push-state.json``, and for
    a stronger reason: this file is read by a RECOVERY path, so a reader that
    catches it half-written would be handed a partial record of a chain that no
    longer exists.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
    os.replace(tmp, path)


def read_journal(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text())
    version = payload.get("version")
    if version != JOURNAL_VERSION:
        raise RebuildRefused(
            f"rebuild journal {path} has version {version!r}, this engine "
            f"writes and reads version {JOURNAL_VERSION}. Refusing to replay a "
            f"record whose shape it does not know — inspect the file by hand "
            f"and rebuild the chain from it."
        )
    return payload


def stranded_journals(song_dir: Path) -> list[Path]:
    """Every journal left on disk under ``song_dir``.

    A journal exists only between the first delete and a passing verify, so any
    file here names a chain that a rebuild started on and did not finish.
    """
    d = journal_dir_for(song_dir)
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.json") if not p.name.startswith("."))


# ---------------------------------------------------------------------------
# Phase 1 — capture
# ---------------------------------------------------------------------------


def capture_chain(
    send_fn: Callable[[Any], Any],
    *,
    parent_kind: str,
    parent_index: int,
    from_position: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read everything the demolish phase is about to destroy.

    Returns ``(captured, alerts)``. ``captured`` holds one entry per live device
    at ``device_index >= from_position``, in ascending index order, each with its
    class identity plus whatever of ``parameters`` / ``input_routing`` /
    ``chains`` / ``pads`` Live answered for. A read that FAILS is recorded as an
    alert and the key is omitted — never fabricated as "nothing there", which
    would restore a device to defaults and call it a success.

    The HallucinoteAnalyzer is excluded: it is measurement infrastructure the
    render appends and re-appends, never an authored slot (SNP-8R4K).
    """
    alerts: list[str] = []
    flat = _flat_parent_params(parent_kind, parent_index)
    ok, result, error = _send(send_fn, "ableton_device", "list", dict(flat))
    if not ok:
        raise RebuildRefused(
            f"chain-rebuild: could not read the device chain on {parent_kind} "
            f"#{parent_index} ({error or 'no reason given'}). Nothing was "
            f"touched. A rebuild demolishes a chain and puts it back from what "
            f"it read; a chain it cannot read is one it must not delete."
        )
    live_devices = list((result or {}).get("devices") or [])
    captured: list[dict[str, Any]] = []
    for dev in live_devices:
        if is_analyzer_device(dev):
            continue
        idx = dev.get("device_index")
        if not isinstance(idx, int) or idx < from_position:
            continue
        entry: dict[str, Any] = {
            "device_index": idx,
            "class": _live_class(dev),
            "class_name": dev.get("class_name"),
            "name": dev.get("name"),
        }
        node = build_node_addr(_parent_kv(parent_kind, parent_index),
                               device_index=idx)
        p_ok, p_res, p_err = _send(
            send_fn, "ableton_device", "get_parameters",
            {"node": node, "detail": "full"},
        )
        if p_ok:
            entry["parameters"] = list((p_res or {}).get("parameters") or [])
        else:
            alerts.append(
                f"chain-rebuild: could not read parameters of "
                f"{entry['class']!r} at position {idx} on {parent_kind} "
                f"#{parent_index} ({p_err or 'no reason given'}) — its dialed "
                f"state is NOT in the journal and will NOT be restored."
            )
        r_ok, r_res, _ = _send(
            send_fn, "ableton_device", "get_input_routing",
            {**flat, "device_index": idx},
        )
        if r_ok and (r_res or {}).get("has_input_routing") is not False:
            entry["input_routing"] = r_res
        c_ok, c_res, _ = _send(
            send_fn, "ableton_device", "get_device_chains",
            {**flat, "device_index": idx, "detail": "full"},
        )
        if c_ok:
            # A non-rack answers with a teaching error, which is not an alert:
            # "this device has no nested chains" is the normal answer for most
            # of a chain.
            entry["chains"] = list((c_res or {}).get("chains") or [])
        d_ok, d_res, _ = _send(
            send_fn, "ableton_device", "pad_info",
            {**flat, "device_index": idx},
        )
        if d_ok:
            entry["pads"] = list((d_res or {}).get("pads") or [])
        captured.append(entry)
    return captured, alerts


# ---------------------------------------------------------------------------
# Phase 0 — the refusal gate
# ---------------------------------------------------------------------------


@dataclass
class RebuildPlan:
    """The DB's answer for the affected span: what should be in the chain from
    ``from_position`` down, in order, and how to load each of it."""
    parent_kind: str
    parent_index: int
    parent_name: str
    from_position: int
    devices: list[dict[str, Any]] = field(default_factory=list)


def plan_rebuild(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    parent_kind: str,
    parent_index: int,
    from_position: int,
) -> RebuildPlan:
    """Resolve the DB span into loadable devices, or REFUSE.

    Every device the rebuild will have to put back is resolved here, before
    anything is deleted, because a device that cannot be reloaded is one whose
    deletion is unrecoverable. Two refusals:

    * a ``placeholder`` inside the span — the DB authors an intentionally EMPTY
      slot, and Live tail-appends, so there is no way to reproduce a gap in the
      middle of a chain;
    * a row with no loadable identity at all (no ``kind``, no preset selector) —
      nothing names what to load.

    Refusing NAMES the device. "Something in this chain can't be reloaded" sends
    the operator hunting; the whole point of refusing before the first delete is
    that they still have the chain to look at.
    """
    parent = _resolve_parent_row(
        conn, song_id=song_id, session_id=session_id,
        parent_kind=parent_kind, parent_index=parent_index,
    )
    get_devices_fn = (
        Q.get_devices_for_return if parent_kind == "return"
        else Q.get_devices_for_track
    )
    plan = RebuildPlan(
        parent_kind=parent_kind,
        parent_index=parent_index,
        parent_name=parent["name"],
        from_position=from_position,
    )
    parent_kv = _parent_kv(parent_kind, parent_index)
    unloadable: list[str] = []
    for db_dev in get_devices_fn(conn, parent["db_id"]):
        if db_dev["position"] < from_position:
            continue
        if is_analyzer_device(db_dev):
            # Never authored; the render puts it back itself.
            continue
        if db_dev["kind"] == "placeholder":
            unloadable.append(
                f"position {db_dev['position']} "
                f"({db_dev['display_name']!r}) is a PLACEHOLDER — an "
                f"intentionally empty slot. Live's load tail-appends, so a "
                f"rebuild cannot reproduce a gap mid-chain"
            )
            continue
        if not db_dev["kind"]:
            unloadable.append(
                f"position {db_dev['position']} "
                f"({db_dev['display_name']!r}) has no device kind, "
                f"preset_query, preset_uri or browser_path — nothing names "
                f"what to load"
            )
            continue
        load_args, notes = build_device_load_args(
            db_dev, parent_kv=parent_kv, parent_kind=parent_kind,
            parent_name=parent["name"],
        )
        plan.devices.append({
            "db_id": db_dev["id"],
            "position": db_dev["position"],
            "kind": db_dev["kind"],
            "display_name": db_dev["display_name"],
            "load_args": load_args,
            "notes": notes,
        })
    if unloadable:
        where = (
            "the master"
            if parent_kind == "master"
            else f"{parent_kind} {parent['name']!r} (#{parent_index})"
        )
        raise RebuildRefused(
            f"chain-rebuild: REFUSING to rebuild {where} from position "
            f"{from_position} — {len(unloadable)} device(s) in the affected "
            f"span cannot be reloaded: " + "; ".join(unloadable) + ". Nothing "
            "was deleted and no journal was written. Deleting a device that "
            "cannot be put back is unrecoverable, so this check runs before "
            "the chain is touched. Fix the DB rows (or narrow --from-position "
            "past them) and re-run."
        )
    if not plan.devices:
        raise RebuildRefused(
            f"chain-rebuild: the DB authors no devices at or after position "
            f"{from_position} on {parent_kind} #{parent_index}, so a rebuild "
            f"would delete the live chain's tail and load nothing back. If "
            f"that is what you want, delete those devices in Live directly."
        )
    return plan


def _resolve_parent_row(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    parent_kind: str,
    parent_index: int,
) -> dict[str, Any]:
    """The ``{db_id, ableton_index, name}`` entry for one addressed parent.

    Resolved through the SAME ``ableton_links`` walk the push devices phase uses
    (:func:`~hallucinote.sync.push.probe.linked_device_parents`), so a rebuild
    can only address a parent push can address. An unlinked parent refuses: its
    DB devices have no Live indices to rebuild against.
    """
    from .push.probe import linked_device_parents

    tracks, returns, master = linked_device_parents(
        conn, song_id=song_id, session_id=session_id,
    )
    pool = {"track": tracks, "return": returns, "master": master}.get(parent_kind)
    if pool is None:
        raise ValueError(
            f"parent_kind must be 'track', 'return' or 'master', got "
            f"{parent_kind!r}"
        )
    for parent in pool:
        if parent["ableton_index"] == parent_index:
            return parent
    known = sorted(p["ableton_index"] for p in pool)
    raise RebuildRefused(
        f"chain-rebuild: this session has no link binding a {parent_kind} to "
        f"Live index {parent_index} (linked {parent_kind} indices: "
        f"{known or 'none'}). Run `push_cli probe-and-link <session> --song "
        f"<slug> --probe` first — a rebuild addresses Live by the same links "
        f"push does, and rebuilding against an unbound index would demolish "
        f"whatever else is sitting there."
    )


# ---------------------------------------------------------------------------
# Phases 3-5 — demolish / rebuild / restore + verify
# ---------------------------------------------------------------------------


def _set_parent_mute(
    send_fn: Callable[[Any], Any], *, parent_kind: str, parent_index: int,
    muted: bool,
) -> tuple[bool, str]:
    """Returns ``(applied, note)``; the master has no mute, so it reports
    ``False`` with the reason rather than pretending."""
    if parent_kind == "master":
        return False, (
            "chain-rebuild: the master strip has no mute, so the "
            "transient-empty-chain window on it cannot be silenced — stop the "
            "transport before rebuilding the master chain."
        )
    tool = "ableton_track" if parent_kind == "track" else "ableton_return"
    key = "track_index" if parent_kind == "track" else "return_index"
    ok, _, error = _send(send_fn, tool, "set_property", {
        key: parent_index, "property": "mute", "value": 1.0 if muted else 0.0,
    })
    if ok:
        return True, ""
    return False, (
        f"chain-rebuild: could not {'mute' if muted else 'unmute'} "
        f"{parent_kind} #{parent_index} ({error or 'no reason given'})."
    )


def _read_parent_mute(
    send_fn: Callable[[Any], Any], *, parent_kind: str, parent_index: int,
) -> bool | None:
    """The parent's mute BEFORE the rebuild — journaled so the restore puts back
    what the operator had, not a hardcoded "unmuted"."""
    if parent_kind == "master":
        return None
    tool = "ableton_track" if parent_kind == "track" else "ableton_return"
    key = "track_index" if parent_kind == "track" else "return_index"
    ok, result, _ = _send(send_fn, tool, "info", {key: parent_index})
    if not ok:
        return None
    value = (result or {}).get("mute")
    return bool(value) if value is not None else None


def _demolish(
    send_fn: Callable[[Any], Any], *, parent_kind: str, parent_index: int,
    from_position: int, captured: list[dict[str, Any]],
) -> list[str]:
    """Delete descending from the tail to ``from_position``.

    Descending is not a preference: Live shifts every later index down after a
    delete, so ascending deletes would walk off the end of a shrinking chain
    (``ableton_device(action='delete')`` says so in its own tip).
    """
    deleted: list[str] = []
    flat = _flat_parent_params(parent_kind, parent_index)
    for entry in sorted(captured, key=lambda e: e["device_index"], reverse=True):
        idx = entry["device_index"]
        ok, _, error = _send(send_fn, "ableton_device", "delete", {
            **flat, "device_index": idx,
        })
        if not ok:
            raise RebuildVerifyFailed(
                f"chain-rebuild: deleting {entry['class']!r} at position {idx} "
                f"on {parent_kind} #{parent_index} FAILED "
                f"({error or 'no reason given'}). The chain is now part-way "
                f"demolished; the journal holds everything that was in it."
            )
        deleted.append(entry["class"])
    return list(reversed(deleted))


def _rebuild(
    send_fn: Callable[[Any], Any], *, plan_devices: list[dict[str, Any]],
    parent_kind: str, parent_index: int,
) -> list[str]:
    """Load in ascending ``position`` order and let Live's tail-append make the
    order true — the same mechanism the push planner already relies on."""
    loaded: list[str] = []
    for entry in sorted(plan_devices, key=lambda e: e["position"]):
        args = dict(entry["load_args"])
        action = args.pop("action", "load")
        ok, _, error = _send(send_fn, "ableton_device", action, args)
        if not ok:
            raise RebuildVerifyFailed(
                f"chain-rebuild: loading {entry['kind']!r} "
                f"('{entry['display_name']}') for position {entry['position']} "
                f"on {parent_kind} #{parent_index} FAILED "
                f"({error or 'no reason given'}). The chain is part-way "
                f"rebuilt; the journal holds what it used to be."
            )
        loaded.append(entry["kind"])
    return loaded


def _param_write_kwargs(param: dict[str, Any]) -> dict[str, Any] | None:
    """The ``set_parameter`` value kwargs that put ONE captured parameter back.

    Enum params ride their display string (``value_type='enum'``, which the
    handler resolves against ``value_items``); everything else rides the raw
    ``value`` that was read off Live — the round trip is exact because it is the
    same scale in both directions, which a display-string round trip is not.
    Returns ``None`` when the capture carries nothing writable.

    Both branches hand the wire a **string**: ``set_parameter`` declares
    ``ParamSpec(name="value", type="str")`` and validation rejects a float
    before it reaches Live. A continuous value therefore rides ``str`` of the
    float — shortest round-trip form, so the exactness above survives it — and
    the handler coerces it back. ``str`` and not ``repr`` because
    ``push.devices._param_value_kv`` produces the same wire field the same way;
    two producers of one field that choose differently is how they drift.
    """
    if param.get("is_enum") and param.get("value_items"):
        display = str(param.get("value_display") or "").strip()
        if not display:
            return None
        return {"value": display, "value_type": "enum"}
    value = param.get("value")
    if value is None:
        return None
    return {"value": str(float(value)), "value_type": "continuous"}


def _restorable(param: dict[str, Any]) -> bool:
    """Can this parameter be written at all?

    ``is_enabled=False`` means macro-mapped or otherwise locked: Live reads it
    fine and refuses every write with "Value cannot be set, the parameter is
    disabled". ``get_parameters(detail='full')`` reports it, which is what lets
    the alert say "this parameter is mapped" rather than "the write failed".

    A MISSING flag means "unknown", which must not become "skip" — that would
    silently drop real authored state — so unknown is treated as writable and a
    failed write becomes the alert instead. An older server that does not send
    the flag therefore degrades to the second-best answer rather than the wrong
    one.
    """
    return param.get("is_enabled", True) is not False


def _restore(
    send_fn: Callable[[Any], Any], *, journal: dict[str, Any],
    parent_kind: str, parent_index: int, live_after: list[dict[str, Any]],
) -> tuple[set[tuple[int, str]], list[str]]:
    """Re-apply parameters, input routing and chain properties from the journal.

    A journaled device is matched to a rebuilt one BY POSITION, and its state is
    applied only when the CLASS also agrees. That is the honest rule for a
    re-voice: position 1 changed from Analog to Operator, so Analog's dialed
    state has no meaning on Operator and carrying it across would be worse than
    dropping it — the change is reported, and the next push dials Operator from
    the DB. Positions whose class did NOT change are exactly the downstream
    effects this whole module exists to preserve.

    Returns ``(written, alerts)`` where ``written`` names every
    ``(device_index, parameter_name)`` the restore actually landed. The verify
    pass reads back exactly that set and no more — the verify gates "every RESTORED
    parameter", and a parameter whose write was REFUSED was not restored. It is
    an alert instead: one automated or locked parameter refusing a write
    should not gut an otherwise correct chain and strand its journal, but it
    must never pass unmentioned.
    """
    alerts: list[str] = []
    written: set[tuple[int, str]] = set()
    flat = _flat_parent_params(parent_kind, parent_index)
    by_index = {d.get("device_index"): d for d in live_after}
    for entry in journal.get("captured", []):
        idx = entry["device_index"]
        now = by_index.get(idx)
        if now is None:
            alerts.append(
                f"chain-rebuild: nothing sits at position {idx} on "
                f"{parent_kind} #{parent_index} after the rebuild, so the "
                f"captured state of {entry['class']!r} was NOT restored."
            )
            continue
        if _live_class(now) != entry["class"]:
            alerts.append(
                f"chain-rebuild: position {idx} on {parent_kind} "
                f"#{parent_index} changed class from {entry['class']!r} to "
                f"{_live_class(now)!r} — the captured parameters belong to the "
                f"OLD device and were not applied. Push the new device's "
                f"authored parameters with `push execute --only devices`."
            )
            continue
        node = build_node_addr(_parent_kv(parent_kind, parent_index),
                               device_index=idx)
        for param in entry.get("parameters", []):
            name = param.get("name")
            if not name:
                continue
            if not _restorable(param):
                alerts.append(
                    f"chain-rebuild: parameter {name!r} on {entry['class']!r} "
                    f"(position {idx}, {parent_kind} #{parent_index}) reads "
                    f"is_enabled=False — macro-mapped or locked, so Live "
                    f"refuses every write to it. Its captured value "
                    f"{param.get('value_display') or param.get('value')!r} was "
                    f"NOT restored; re-map or unlock it and re-apply by hand."
                )
                continue
            kwargs = _param_write_kwargs(param)
            if kwargs is None:
                alerts.append(
                    f"chain-rebuild: parameter {name!r} on {entry['class']!r} "
                    f"(position {idx}, {parent_kind} #{parent_index}) was "
                    f"captured with no writable value, so it was NOT restored."
                )
                continue
            ok, _, error = _send(send_fn, "ableton_device", "set_parameter", {
                "node": node, "parameter_name": name, **kwargs,
            })
            if ok:
                written.add((idx, name))
            else:
                alerts.append(
                    f"chain-rebuild: restoring {name!r} on {entry['class']!r} "
                    f"(position {idx}, {parent_kind} #{parent_index}) FAILED "
                    f"({error or 'no reason given'}) — the captured value is "
                    f"in the journal and was not applied."
                )
        routing = entry.get("input_routing")
        if routing:
            # `get_input_routing` answers with `current_type` / `current_channel`
            # (the read-side names, shared with the track handler);
            # `set_input_routing` takes `type_display_name` /
            # `channel_display_name`. The rename is the whole translation.
            type_display = routing.get("current_type")
            channel_display = routing.get("current_channel")
            params: dict[str, Any] = {**flat, "device_index": idx}
            if type_display:
                params["type_display_name"] = type_display
            if channel_display:
                params["channel_display_name"] = channel_display
            if len(params) > len(flat) + 1:
                ok, _, error = _send(
                    send_fn, "ableton_device", "set_input_routing", params,
                )
                if not ok:
                    alerts.append(
                        f"chain-rebuild: restoring the input routing of "
                        f"{entry['class']!r} (position {idx}, {parent_kind} "
                        f"#{parent_index}) FAILED "
                        f"({error or 'no reason given'}) — this is the "
                        f"SIDECHAIN SOURCE on a compressor or gate, so check it "
                        f"before trusting the mix."
                    )
        alerts.extend(_restore_chain_properties(
            send_fn, entry=entry, parent_kind=parent_kind,
            parent_index=parent_index, device_index=idx,
        ))
    return written, alerts


_CHAIN_PROPS: tuple[str, ...] = (
    "choke_group", "out_note", "mute", "solo", "volume", "pan",
)


def _restore_chain_properties(
    send_fn: Callable[[Any], Any], *, entry: dict[str, Any],
    parent_kind: str, parent_index: int, device_index: int,
) -> list[str]:
    """Re-apply a rack's per-chain authored properties (choke groups, chain
    mixer). The rack's own preset brings its chains back; these are the
    properties the operator set on top of it.

    Nested DEVICES inside a rack are NOT restored — they arrive with the preset,
    and a device hand-added inside a rack in Live is not in the preset and does
    not survive. That loss is real and documented rather than papered over.
    """
    alerts: list[str] = []
    for chain in entry.get("chains", []):
        chain_index = chain.get("chain_index")
        if chain_index is None:
            continue
        writes: dict[str, Any] = {}
        for prop in _CHAIN_PROPS:
            if prop not in chain:
                continue
            if chain.get(f"{prop}_is_enabled") is False:
                alerts.append(
                    f"chain-rebuild: chain property {prop!r} on chain "
                    f"{chain_index} of {entry['class']!r} (position "
                    f"{device_index}, {parent_kind} #{parent_index}) reads "
                    f"is_enabled=False — locked, so it was NOT restored."
                )
                continue
            writes[prop] = chain[prop]
        if not writes:
            continue
        node = build_node_addr(
            _parent_kv(parent_kind, parent_index),
            device_index=device_index, chain_index=chain_index,
            terminal="chain",
        )
        ok, _, error = _send(send_fn, "ableton_device", "set_chain_property", {
            "node": node, **writes,
        })
        if not ok:
            alerts.append(
                f"chain-rebuild: restoring chain {chain_index} properties "
                f"{sorted(writes)} on {entry['class']!r} (position "
                f"{device_index}, {parent_kind} #{parent_index}) FAILED "
                f"({error or 'no reason given'})."
            )
    return alerts


def _probe_chain(
    send_fn: Callable[[Any], Any], *, parent_kind: str, parent_index: int,
) -> list[dict[str, Any]]:
    ok, result, error = _send(
        send_fn, "ableton_device", "list",
        _flat_parent_params(parent_kind, parent_index),
    )
    if not ok:
        raise RebuildVerifyFailed(
            f"chain-rebuild: could not re-read the chain on {parent_kind} "
            f"#{parent_index} after rebuilding it "
            f"({error or 'no reason given'}). The rebuild is UNVERIFIED."
        )
    return [
        d for d in ((result or {}).get("devices") or [])
        if not is_analyzer_device(d)
    ]


def verify_rebuild(
    send_fn: Callable[[Any], Any], *, plan_devices: list[dict[str, Any]],
    journal: dict[str, Any], parent_kind: str, parent_index: int,
    from_position: int, written: set[tuple[int, str]],
) -> list[dict[str, Any]]:
    """The gate, not a log line.

    The regression this exists to catch is a chain rebuilt with DEFAULT
    parameters: an audibly wrong track that push reports as ``ok``. So success
    requires two things read back off Live, not inferred from the calls having
    returned ok — the class order from ``from_position`` down must equal the DB
    ``position`` order, and every parameter the restore claims to have written
    must read back equal.

    Raises :class:`RebuildVerifyFailed` on either mismatch, leaving the journal
    on disk. Returns the re-probed chain on the clean path.
    """
    live_after = _probe_chain(
        send_fn, parent_kind=parent_kind, parent_index=parent_index,
    )
    expected = [
        e["kind"] for e in sorted(plan_devices, key=lambda e: e["position"])
    ]
    actual = [
        _live_class(d) for d in live_after
        if isinstance(d.get("device_index"), int)
        and d["device_index"] >= from_position
    ]
    if expected != actual:
        raise RebuildVerifyFailed(
            f"chain-rebuild: VERIFY FAILED on {parent_kind} #{parent_index} — "
            f"the DB authors {expected} from position {from_position}, Live "
            f"now has {actual}. The chain is NOT what was asked for; the "
            f"journal is intact."
        )
    mismatches = _verify_parameters(
        send_fn, journal=journal, parent_kind=parent_kind,
        parent_index=parent_index, live_after=live_after, written=written,
    )
    if mismatches:
        raise RebuildVerifyFailed(
            f"chain-rebuild: VERIFY FAILED on {parent_kind} #{parent_index} — "
            f"{len(mismatches)} restored parameter(s) did not read back equal: "
            + "; ".join(mismatches[:10])
            + (f" (+{len(mismatches) - 10} more)" if len(mismatches) > 10 else "")
            + ". A chain rebuilt with default parameters is an audibly wrong "
              "track that would otherwise be reported ok. The journal is intact."
        )
    return live_after


# Live's parameter values are floats round-tripped through the wire; an exact
# equality test would fail on representation alone. This is tight enough that a
# parameter left at its DEFAULT — the regression the verify exists to catch — is always
# outside it, and loose enough that a faithful round trip is always inside.
_PARAM_EPSILON = 1e-6


def _verify_parameters(
    send_fn: Callable[[Any], Any], *, journal: dict[str, Any],
    parent_kind: str, parent_index: int, live_after: list[dict[str, Any]],
    written: set[tuple[int, str]],
) -> list[str]:
    """Read every device the restore wrote to and compare, value by value.

    Scoped to ``written`` — the parameters the restore actually landed. A
    parameter it declined or was refused on is already an alert; re-reporting it
    here as a verify failure would halt a chain that is as correct as Live let
    it be.
    """
    mismatches: list[str] = []
    by_index = {d.get("device_index"): d for d in live_after}
    for entry in journal.get("captured", []):
        idx = entry["device_index"]
        now = by_index.get(idx)
        if now is None or _live_class(now) != entry["class"]:
            # Not restored, and the restore already alerted about it.
            continue
        wanted = {
            p["name"]: p for p in entry.get("parameters", [])
            if (idx, p.get("name")) in written
        }
        if not wanted:
            continue
        node = build_node_addr(_parent_kv(parent_kind, parent_index),
                               device_index=idx)
        ok, result, error = _send(
            send_fn, "ableton_device", "get_parameters",
            {"node": node, "detail": "full"},
        )
        if not ok:
            mismatches.append(
                f"{entry['class']!r} at position {idx}: could not read its "
                f"parameters back ({error or 'no reason given'}), so the "
                f"restore is unproven"
            )
            continue
        now_by_name = {
            p.get("name"): p for p in ((result or {}).get("parameters") or [])
        }
        for name, param in wanted.items():
            read = now_by_name.get(name)
            if read is None:
                mismatches.append(
                    f"{entry['class']!r} at position {idx}: parameter {name!r} "
                    f"is gone after the rebuild"
                )
                continue
            before, after = param.get("value"), read.get("value")
            if before is None or after is None:
                continue
            if abs(float(before) - float(after)) > _PARAM_EPSILON:
                mismatches.append(
                    f"{entry['class']!r} at position {idx}: {name!r} was "
                    f"{before!r}, reads back {after!r}"
                )
    return mismatches


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------


def rebuild_chain(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    parent_kind: str,
    parent_index: int,
    from_position: int,
    send_fn: Callable[[Any], Any],
    song_dir: Path | None = None,
    actor: str = "sync",
    reason: str | None = None,
) -> RebuildResult:
    """Rebuild one parent's device chain from ``from_position`` to its tail so
    it matches the DB's ``position`` order, carrying every surviving device's
    dialed state across.

    The five phases in order, with the two properties that make it safe: nothing
    is deleted until every DB device in the span has been proved loadable and
    the full capture is on disk, and nothing is reported successful until Live
    has been re-read and agrees.

    Raises :class:`RebuildRefused` when it declines before touching anything, and
    :class:`RebuildVerifyFailed` when it started and could not finish — the
    latter leaves the journal for :func:`resume`.
    """
    if from_position < 1:
        raise ValueError(f"from_position {from_position} must be >= 1")
    if song_dir is None:
        song_dir = song_dir_for_conn(conn)
    if song_dir is None:
        raise RebuildRefused(
            "chain-rebuild: this connection has no song directory (an "
            "in-memory database), so the pre-delete journal has nowhere to "
            "live. Refusing — a rebuild without a durable journal is exactly "
            "the failure mode this command exists to remove. Pass an explicit "
            "song_dir, or run against the song's on-disk DB."
        )
    # The refusals all run before the chain is touched, so this is the
    # last of them and still ahead of the first read.
    plan = plan_rebuild(
        conn, song_id=song_id, session_id=session_id,
        parent_kind=parent_kind, parent_index=parent_index,
        from_position=from_position,
    )
    result = RebuildResult(
        parent_kind=parent_kind,
        parent_index=parent_index,
        parent_name=plan.parent_name,
        from_position=from_position,
    )
    for entry in plan.devices:
        result.notes.extend(entry.get("notes") or [])

    captured, capture_alerts = capture_chain(
        send_fn, parent_kind=parent_kind, parent_index=parent_index,
        from_position=from_position,
    )
    result.alerts.extend(capture_alerts)
    was_muted = _read_parent_mute(
        send_fn, parent_kind=parent_kind, parent_index=parent_index,
    )

    journal_path = journal_path_for(Path(song_dir), parent_kind, parent_index)
    # A journal already here is an INTERRUPTED rebuild's only record of what
    # that chain held. Overwriting it with a capture of the chain that run left
    # behind — half-demolished, or fully gutted — destroys exactly the thing
    # the journal exists to preserve, and does it silently on the operator's
    # most likely next action: running the command again. Refuse and name the
    # resume path.
    if journal_path.exists():
        raise RebuildRefused(
            f"chain-rebuild: a journal for {parent_kind} #{parent_index} is "
            f"already on disk at {journal_path}. That means an earlier rebuild "
            f"started on this chain and did not finish, and the file is the "
            f"only record of what the chain held before it did. Starting over "
            f"now would capture the chain THAT run left and overwrite it.\n"
            f"  Resume it:  hallucinote chain-rebuild --resume {journal_path}\n"
            f"If you are certain the chain is already correct, delete the "
            f"journal by hand — but read it first."
        )
    journal = {
        "version": JOURNAL_VERSION,
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "phase": PHASE_JOURNALED,
        "song_id": song_id,
        "session_id": session_id,
        "parent_kind": parent_kind,
        "parent_index": parent_index,
        "parent_name": plan.parent_name,
        "from_position": from_position,
        "parent_was_muted": was_muted,
        "captured": captured,
        "plan_devices": plan.devices,
    }
    # On disk BEFORE the first delete. Everything after this line can crash
    # without the operator losing the record of what the chain held.
    write_journal(journal_path, journal)
    result.journal_path = journal_path

    return _run_destructive_phases(
        conn, journal=journal, journal_path=journal_path,
        demolish_targets=captured, send_fn=send_fn, result=result,
        session_id=session_id, actor=actor, reason=reason,
    )


def _run_destructive_phases(
    conn: sqlite3.Connection | None,
    *,
    journal: dict[str, Any],
    journal_path: Path,
    demolish_targets: list[dict[str, Any]],
    send_fn: Callable[[Any], Any],
    result: RebuildResult,
    session_id: str | None,
    actor: str,
    reason: str | None,
) -> RebuildResult:
    """Demolish → rebuild → restore → verify → unmute → drop the journal.

    Shared by :func:`rebuild_chain` and :func:`resume` so a resumed run and a
    fresh one converge on the same chain, through the same gate.

    ``demolish_targets`` is separate from ``journal["captured"]`` on purpose. A
    fresh run deletes exactly what it captured, so they are the same list; a
    RESUME deletes what the interrupted run LEFT (re-probed, possibly a
    part-demolished chain) while restoring from what the original run captured.
    Collapsing the two would delete by indices that no longer exist.
    """
    parent_kind = journal["parent_kind"]
    parent_index = journal["parent_index"]

    muted, mute_note = _set_parent_mute(
        send_fn, parent_kind=parent_kind, parent_index=parent_index, muted=True,
    )
    if mute_note:
        result.alerts.append(mute_note)

    try:
        return _destructive_body(
            conn, journal=journal, journal_path=journal_path,
            demolish_targets=demolish_targets, send_fn=send_fn, result=result,
            session_id=session_id, actor=actor, reason=reason,
        )
    finally:
        # The mute we installed comes off on EVERY exit, not just the happy
        # one. A rebuild that raises used to leave the parent silenced with
        # nothing saying so, and an operator hunting a silent track is hunting
        # a problem the tool created. Restoring it costs one call and cannot
        # make a failure worse.
        if muted:
            _, unmute_note = _set_parent_mute(
                send_fn, parent_kind=parent_kind, parent_index=parent_index,
                muted=bool(journal.get("parent_was_muted")),
            )
            if unmute_note:
                result.alerts.append(unmute_note)


def _destructive_body(
    conn: sqlite3.Connection | None,
    *,
    journal: dict[str, Any],
    journal_path: Path,
    demolish_targets: list[dict[str, Any]],
    send_fn: Callable[[Any], Any],
    result: RebuildResult,
    session_id: str | None,
    actor: str,
    reason: str | None,
) -> RebuildResult:
    """The phases themselves. Split out so the caller's `finally` owns the mute.

    Every raise from here leaves the journal on disk deliberately — that is the
    recovery record — but must NOT leave the parent silenced.
    """
    parent_kind = journal["parent_kind"]
    parent_index = journal["parent_index"]
    from_position = journal["from_position"]

    result.deleted = _demolish(
        send_fn, parent_kind=parent_kind, parent_index=parent_index,
        from_position=from_position, captured=demolish_targets,
    )
    journal["phase"] = PHASE_DEMOLISHED
    write_journal(journal_path, journal)

    result.loaded = _rebuild(
        send_fn, plan_devices=journal["plan_devices"],
        parent_kind=parent_kind, parent_index=parent_index,
    )
    journal["phase"] = PHASE_REBUILT
    write_journal(journal_path, journal)

    live_after = _probe_chain(
        send_fn, parent_kind=parent_kind, parent_index=parent_index,
    )
    written, restore_alerts = _restore(
        send_fn, journal=journal, parent_kind=parent_kind,
        parent_index=parent_index, live_after=live_after,
    )
    result.restored_params = len(written)
    result.alerts.extend(restore_alerts)
    journal["phase"] = PHASE_RESTORED
    write_journal(journal_path, journal)

    # Raises with the journal intact if Live disagrees.
    verify_rebuild(
        send_fn, plan_devices=journal["plan_devices"], journal=journal,
        parent_kind=parent_kind, parent_index=parent_index,
        from_position=from_position, written=written,
    )
    journal["phase"] = PHASE_VERIFIED
    write_journal(journal_path, journal)

    if conn is not None and session_id is not None:
        result.notes.extend(_rebind_links(
            conn, journal=journal, session_id=session_id, actor=actor,
            reason=reason,
        ))
    else:
        result.alerts.append(
            "chain-rebuild: no database connection was available, so the DB's "
            "device links still point at the PRE-rebuild chain indices. Run "
            "`push_cli probe-and-link <session> --song <slug> --probe` before "
            "the next push, or it will plan against stale indices."
        )

    # The mute comes off in the caller's `finally` — every exit path, not just
    # this one. It reads the operator's own prior state from the journal rather
    # than forcing "unmuted", which would un-silence a track they had muted.

    # The journal is removed ONLY now, past the verify — the other half of
    # writing it before the first delete.
    journal_path.unlink(missing_ok=True)
    result.journal_path = None
    result.ok = True
    return result


def _rebind_links(
    conn: sqlite3.Connection,
    *,
    journal: dict[str, Any],
    session_id: str,
    actor: str,
    reason: str | None,
) -> list[str]:
    """Re-record ``ableton_links`` from the rebuilt chain's positions.

    Written through the standard mutators (``M.link_db_to_ableton``), so the
    event log stays complete and no schema changes. This is what makes a SECOND
    push after a reconcile emit no drift note for this parent (#323): the next
    probe finds each DB device already linked and class-matched at its position,
    so it neither re-emits the note nor re-plans a load.
    """
    notes: list[str] = []
    parent_kind = journal["parent_kind"]
    parent_index = journal["parent_index"]
    for entry in journal["plan_devices"]:
        M.link_db_to_ableton(
            conn,
            session_id=session_id,
            db_kind="device",
            db_id=entry["db_id"],
            ableton_index=entry["position"],
            actor=actor,
            reason=reason or (
                f"chain-rebuild: {parent_kind}#{parent_index} position "
                f"{entry['position']}"
            ),
        )
        notes.append(
            f"linked device {entry['display_name']!r} to "
            f"{parent_kind}#{parent_index} position {entry['position']}"
        )
    conn.commit()
    return notes


def resume(
    journal_path: Path,
    *,
    send_fn: Callable[[Any], Any],
    conn: sqlite3.Connection | None = None,
    session_id: str | None = None,
    actor: str = "sync",
    reason: str | None = None,
) -> RebuildResult:
    """Replay a stranded rebuild from its journal — and from nothing else.

    An interrupted rebuild leaves a chain in an unknown state and a journal that
    knows what it held. The replay re-probes Live, deletes whatever is sitting in
    the affected span NOW (what the interrupted run left, which is not what the
    journal captured), reloads the DB's order from the journal's plan and
    restores the journal's captured state onto it. It goes through the same
    verify gate: a resume that cannot prove the chain is right leaves the
    journal exactly where it found it.

    ``conn`` is optional on purpose. A journal must be replayable when the file
    is all the operator has — with no connection the chain is restored and the
    DB's links are left to ``probe-and-link``, said out loud as an alert rather
    than left to be discovered on the next push.
    """
    journal_path = Path(journal_path)
    journal = read_journal(journal_path)
    parent_kind = journal["parent_kind"]
    parent_index = journal["parent_index"]
    from_position = journal["from_position"]
    result = RebuildResult(
        parent_kind=parent_kind,
        parent_index=parent_index,
        parent_name=journal.get("parent_name", ""),
        from_position=from_position,
        journal_path=journal_path,
    )
    result.notes.append(
        f"resumed from {journal_path} — the interrupted run reached phase "
        f"{journal.get('phase')!r}"
    )
    live_now = _probe_chain(
        send_fn, parent_kind=parent_kind, parent_index=parent_index,
    )
    present = [
        {"device_index": d["device_index"], "class": _live_class(d)}
        for d in live_now
        if isinstance(d.get("device_index"), int)
        and d["device_index"] >= from_position
    ]
    return _run_destructive_phases(
        conn, journal=journal, journal_path=journal_path,
        demolish_targets=present, send_fn=send_fn, result=result,
        session_id=session_id, actor=actor, reason=reason,
    )


# ---------------------------------------------------------------------------
# Caller 2 — the push devices phase's opt-in reconcile
# ---------------------------------------------------------------------------


def reconcile_chains(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    live_devices_by_parent: dict[tuple[str, int], list[dict]],
    send_fn: Callable[[Any], Any],
    song_dir: Path | None = None,
    actor: str = "sync",
    reason: str | None = None,
) -> list[RebuildResult]:
    """The push-side caller: rebuild every chain the devices phase would refuse on.

    Fires on exactly the occupied-slot condition ``plan_push_devices`` refuses
    on (:func:`~hallucinote.sync.push.devices.occupied_slots` is that branch's
    rule, lifted out so the two readers can never disagree), and runs BEFORE the
    push, so the devices phase then sees a linked, in-order chain and emits no
    load at all.

    It is opt-in per push (``push execute --reconcile-chains``) and never
    automatic: a rebuild is destructive and holds Live for real wall-clock time,
    and a routine push must not start one the operator did not ask for.

    A refusal or a failed verify on ONE parent stops the whole reconcile —
    continuing would push into a set that is half-reconciled and half-not, which
    is harder to reason about than a stopped run with a named cause.
    """
    targets: list[OccupiedSlot] = occupied_slots(
        conn, song_id=song_id, session_id=session_id,
        live_devices_by_parent=live_devices_by_parent,
    )
    results: list[RebuildResult] = []
    for target in targets:
        results.append(rebuild_chain(
            conn,
            song_id=song_id,
            session_id=session_id,
            parent_kind=target.parent_kind,
            parent_index=target.parent_index,
            from_position=target.from_position,
            send_fn=send_fn,
            song_dir=song_dir,
            actor=actor,
            reason=reason or (
                f"push --reconcile-chains: {target.parent_kind}"
                f"#{target.parent_index} position {target.from_position} was "
                f"occupied by {target.occupant_class}"
            ),
        ))
    return results


# ---------------------------------------------------------------------------
# Caller 1 — the interactive re-voice CLI (`hallucinote chain-rebuild`)
# ---------------------------------------------------------------------------


def _cli_resolve_db(args: Any) -> Path:
    """``--song <slug>`` → the per-branch DB, ``--db PATH`` → PATH.

    Same resolution ``push_cli`` does (per-branch W12-A path, legacy
    ``<slug>.db`` fallback), duplicated rather than imported because
    ``push_cli`` imports THIS module for ``--reconcile-chains`` and a top-level
    import back would close the cycle.
    """
    from hallucinote.db import resolve_db_path

    if args.db:
        path = Path(args.db)
    else:
        path = resolve_db_path(args.song)
        if not path.exists():
            legacy = resolve_db_path(args.song, branch=None)
            if legacy.exists():
                path = legacy
    if not path.exists():
        raise SystemExit(
            f"chain-rebuild: DB not found at {path} — run "
            f"`python songs/{args.song}/build.py` first to populate it."
        )
    return path


def _cli_parent(args: Any) -> tuple[str, int]:
    if args.master:
        return "master", 0
    if args.track is not None:
        return "track", args.track
    if args.return_ is not None:
        return "return", args.return_
    raise SystemExit(
        "chain-rebuild: name the parent — --track <live index>, "
        "--return <live index> or --master."
    )


def _format_result(result: RebuildResult) -> str:
    lines = [result.describe()]
    for note in result.notes:
        lines.append(f"  note:  {note}")
    for alert in result.alerts:
        lines.append(f"  ALERT: {alert}")
    if not result.alerts:
        lines.append(
            "  Every captured parameter was restored and read back equal."
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """``hallucinote chain-rebuild`` — swap or reorder a device and keep the
    chain below it.

    Two modes. The default rebuilds one named parent's chain from
    ``--from-position`` down so it matches the DB's ``position`` order.
    ``--resume`` replays a journal a previous, interrupted run left behind —
    the recovery path for the crash that would otherwise leave a gutted chain.
    """
    import argparse
    import sys

    from hallucinote.db import init_db
    from hallucinote.sync.session_resolve import resolve_session_id

    p = argparse.ArgumentParser(
        prog="hallucinote chain-rebuild",
        description=(
            "Rebuild a track/return/master device chain into the DB's order, "
            "carrying every surviving device's dialed parameters across. Live "
            "has no reorder API, so this captures the chain, journals it to "
            "disk, deletes descending, reloads in order and restores — "
            "refusing to report success until Live reads back equal."
        ),
    )
    p.add_argument("session_id", nargs="?", default=None,
                   help="ableton session id (auto-resolved when omitted)")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--song", help="song slug (resolves the per-branch DB)")
    src.add_argument("--db", help="explicit path to the SQLite DB (escape hatch)")
    where = p.add_mutually_exclusive_group()
    where.add_argument("--track", type=int, default=None, metavar="INDEX",
                       help="the parent track's LIVE index (1-based)")
    where.add_argument("--return", dest="return_", type=int, default=None,
                       metavar="INDEX",
                       help="the parent return's LIVE index (1-based)")
    where.add_argument("--master", action="store_true",
                       help="rebuild the master strip's chain")
    p.add_argument("--from-position", type=int, default=1,
                   help=(
                       "the first DB position to rebuild (default 1 — the "
                       "instrument slot). Everything from here to the tail is "
                       "deleted and reloaded."
                   ))
    p.add_argument("--resume", default=None, metavar="JOURNAL",
                   help=(
                       "replay a stranded journal instead of starting a "
                       "rebuild. Pass the journal path, or `auto` to replay "
                       "the only one under the song's .rebuild/ directory."
                   ))
    p.add_argument("--reason", default=None,
                   help="reason recorded on the DB link mutations")
    args = p.parse_args(argv)

    if not args.song and not args.db:
        sys.stderr.write("chain-rebuild: need --song <slug> or --db <path>\n")
        return 2

    db_path = _cli_resolve_db(args)
    conn = init_db(db_path)
    try:
        session_id = resolve_session_id(
            conn, args.session_id, prog="chain-rebuild",
        )
        song_id = _cli_song_id(conn, session_id)
        song_dir = song_dir_for_conn(conn)

        if args.resume:
            journal_path = _cli_resume_target(args.resume, song_dir)
            if journal_path is None:
                return 2
            result = resume(
                journal_path, send_fn=_cli_send_fn(), conn=conn,
                session_id=session_id, actor="sync",
                reason=args.reason or "chain-rebuild --resume",
            )
        else:
            parent_kind, parent_index = _cli_parent(args)
            result = rebuild_chain(
                conn,
                song_id=song_id,
                session_id=session_id,
                parent_kind=parent_kind,
                parent_index=parent_index,
                from_position=args.from_position,
                send_fn=_cli_send_fn(),
                song_dir=song_dir,
                actor="sync",
                reason=args.reason or "chain-rebuild",
            )
    except RebuildRefused as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    except RebuildVerifyFailed as exc:
        sys.stderr.write(f"{exc}\n")
        sys.stderr.write(
            "The journal is still on disk. Re-run with "
            "`chain-rebuild --resume auto --song <slug>` once Live is "
            "answering again.\n"
        )
        return 1
    finally:
        conn.close()

    sys.stdout.write(_format_result(result))
    # An alert is operator-actionable but not a failure: the chain is verified
    # correct, and something in it could not be carried across. Exit 0 with the
    # alert printed, the same severity split the push report uses.
    return 0


def _cli_song_id(conn: sqlite3.Connection, session_id: str) -> str:
    session = Q.get_ableton_session(conn, session_id)
    if session is None:
        raise SystemExit(
            f"chain-rebuild: no ableton_sessions row with id {session_id!r}"
        )
    return session["song_id"]


def _cli_resume_target(spec: str, song_dir: Path | None) -> Path | None:
    """Resolve ``--resume`` to one journal file.

    ``auto`` is only unambiguous when exactly one journal is stranded; with
    several, the command names them and refuses rather than picking a chain to
    rebuild on the operator's behalf.
    """
    import sys

    if spec != "auto":
        path = Path(spec)
        if not path.exists():
            sys.stderr.write(f"chain-rebuild: no journal at {path}\n")
            return None
        return path
    if song_dir is None:
        sys.stderr.write(
            "chain-rebuild: --resume auto needs a song directory; pass the "
            "journal path instead.\n"
        )
        return None
    found = stranded_journals(Path(song_dir))
    if not found:
        sys.stderr.write(
            f"chain-rebuild: no stranded journal under "
            f"{journal_dir_for(Path(song_dir))} — nothing to resume.\n"
        )
        return None
    if len(found) > 1:
        sys.stderr.write(
            "chain-rebuild: several stranded journals; name the one to "
            "replay:\n" + "".join(f"  {p}\n" for p in found)
        )
        return None
    return found[0]


def _cli_send_fn() -> Callable[[Any], Any]:
    """Lazy resolver for ``hallucinote_mcp.client.send``.

    A module-level seam so tests can monkeypatch it — the same reason
    ``push_cli._resolve_send_fn`` exists, and for the same failure: patching
    the in-function import via ``sys.modules`` doesn't reach an already-bound
    ``client`` attribute.
    """
    from hallucinote_mcp import client as _client  # type: ignore[import-not-found]
    return _client.send
