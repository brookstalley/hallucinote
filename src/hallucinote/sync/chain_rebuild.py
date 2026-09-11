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
                journal onto the POST-rebuild chain, RE-PROBE, and refuse to
                report success unless the class order and every restored value
                read back equal AND every writable parameter that was captured
                actually landed. Only then is the parent unmuted and the journal
                deleted.

**Two numberings, never conflated.** The DB authors a ``position``; Live answers
to a ``device_index``; and the HallucinoteAnalyzer occupies a device_index while
holding no position — it is measurement infrastructure the render appends, and
the authoring model behaves as if it is not there (SNP-8R4K). The delete removes
only authored devices, so the analyzer SURVIVES a rebuild and the reloads
tail-append behind it: a tap that sat at the tail before sits at the head after,
and every physical index past it moves by one. So the capture selects its span
by position, the restore addresses devices by the index read back from the
POST-rebuild chain, and :func:`_logical_chain` is the one place the two
numberings meet. Trusting the pre-delete index is how a restore writes real
values onto the slot next door.

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
from hallucinote.capture import (
    sidechain_armed_in_probe,
    unreadable_sidechain_source_warning,
)
from hallucinote.db import mutations as M, queries as Q
from hallucinote.paths import song_dir_for_conn
from hallucinote.sync.live_escalation import await_escalated, escalated_job_id

from .push._core import build_node_addr
from .push.devices import (
    OccupiedSlot,
    build_device_load_args,
    occupied_slots,
)


JOURNAL_VERSION = 2
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
_ROUTING_SLOT = "\u2039input routing\u203a"
"""Accounting key for a device's input routing — the sidechain source — inside
the restore's ``expected`` / ``written`` sets. Bracketed so it can never collide
with a real Live parameter name, since those sets are keyed by
``(position, parameter_name)`` and a device is free to own a parameter called
anything at all."""

PHASE_SHORTFALL = "shortfall"
"""The rebuild finished and rebound its links, and some captured parameters
never landed. Distinct from the phases above because it describes a chain that
is CORRECT and linked, with values missing — not one a rebuild abandoned
mid-flight. `push execute` refuses the latter and only warns about this."""


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
    named here, never dropped.

    ``restored_params`` (M) against ``expected_params`` (N) is the run's own
    honesty check: N counts every writable parameter the capture carried onto a
    device the rebuild matched, M counts the ones that landed. ``ok`` is False
    when they differ — a SHORTFALL — as well as on a path that raised, and a
    shortfall keeps ``journal_path`` pointing at the retained journal: it holds
    the values that did not land and is the only record of them.
    """
    parent_kind: str
    parent_index: int
    parent_name: str = ""
    from_position: int = 0
    journal_path: Path | None = None
    deleted: list[str] = field(default_factory=list)
    loaded: list[str] = field(default_factory=list)
    restored_params: int = 0
    expected_params: int = 0
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
            + (
                f" of {self.expected_params} captured — SHORTFALL"
                if not self.ok else ""
            )
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
            progress_fn=_operator_note,
            warnings_sink=_operator_note,
        )
    ok = bool(getattr(resp, "ok", False))
    result = getattr(resp, "result", None)
    error = getattr(resp, "error", None) or ""
    return ok, result, error


def _operator_note(message: str) -> None:
    """Where anything the operator needs WHILE the rebuild runs goes.

    stderr, not stdout: a rebuild's stdout is its report, and a caller
    redirecting it should not have a live note land in the middle of one. The
    operator still sees it — waiting minutes on a wedged main thread with no
    output is one case this exists to avoid, and a warning that only reaches
    the final report is another: this command is non-interactive, so the only
    abort it offers is the operator's own, and that needs the message on screen
    while the chain is still intact.
    """
    print(message, file=sys.stderr)


def _live_class(device: dict[str, Any]) -> str:
    return device.get("class_display_name") or device.get("class_name") or ""


# ---------------------------------------------------------------------------
# The two numberings
# ---------------------------------------------------------------------------


def _logical_chain(live_devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Live's chain as the AUTHORING model sees it, with both numbers kept.

    One entry per authored device — ``{"position", "device_index", "device"}`` —
    where ``position`` is the 1-based slot the DB authors and ``device_index`` is
    the physical index Live answers to. The HallucinoteAnalyzer holds a
    device_index and no position, so from the first rendered surface onward the
    two numbers differ, and after a rebuild they differ the other way round (the
    tap moves from the tail to the head). Deriving them together here is what
    keeps a restore addressing the device it measured.
    """
    logical: list[dict[str, Any]] = []
    for dev in live_devices:
        idx = dev.get("device_index")
        if not isinstance(idx, int) or is_analyzer_device(dev):
            continue
        logical.append({
            "position": len(logical) + 1,
            "device_index": idx,
            "device": dev,
        })
    return logical


def _logical_span(
    live_devices: list[dict[str, Any]], *, from_position: int,
) -> list[dict[str, Any]]:
    """:func:`_logical_chain` narrowed to the rebuilt span — positions at or
    after ``from_position``, which is a DB position and never a Live index."""
    return [
        e for e in _logical_chain(live_devices) if e["position"] >= from_position
    ]


def _unaddressable(live_devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Devices Live reports that this rebuild can neither address nor delete.

    A device the demolish skips survives it and shifts every later physical
    index, which is the whole of #532. Exactly one device earns that tolerance:
    the HallucinoteAnalyzer, because the render places it, re-places it, and the
    authoring model is defined to behave as if it is not there. Anything else
    Live lists without a usable ``device_index`` is refused BY NAME before the
    first delete — the same bright line as a device that cannot be reloaded,
    and for the same two reasons: deleting it would be unrecoverable and letting
    it survive would silently misdirect every restored value.
    """
    return [
        d for d in live_devices
        if not isinstance(d.get("device_index"), int)
        and not is_analyzer_device(d)
    ]


def _describe_device(device: dict[str, Any]) -> str:
    return (
        f"{_live_class(device) or '<no class>'!r} (name "
        f"{device.get('name')!r}, device_index "
        f"{device.get('device_index')!r})"
    )


def _entry_position(entry: dict[str, Any]) -> int:
    """The journal entry's DB position — never the physical index it also holds.

    Required, not inferred — which is why this reads the entry and nothing else.
    An earlier version took the span's start and the entry's ordinal too, to
    re-derive a missing ``position`` from the entry's ORDER, on the reasoning
    that ``captured`` is ascending and starts at the same number. That holds only
    when the captured span held nothing but authored devices — and a journal
    written before ``position`` existed is exactly a journal written by the code
    that could not see a surviving analyzer, so replaying one onto a chain whose
    tap now sits at the head reproduces the off-by-one this module was changed to
    end. ``JOURNAL_VERSION`` carries the requirement: a journal without
    ``position`` is version 1, and :func:`read_journal` refuses it with a
    teaching error rather than guessing.
    """
    position = entry.get("position")
    if isinstance(position, int):
        return position
    raise RebuildRefused(
        f"rebuild journal entry for {entry.get('class', '<unknown>')!r} carries "
        f"no DB position, so which device it describes cannot be established "
        f"without assuming the chain held no unauthored device — the assumption "
        f"that put every restored value one slot off. Rebuild the chain from the "
        f"DB instead of replaying this journal, and read the file first: it "
        f"still holds the captured values."
    )


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


def journal_phase(path: Path) -> str:
    """The phase recorded in one journal, or ``""`` when it cannot be read.

    Unreadable counts as unknown, never as finished: a journal whose phase this
    cannot determine is treated by every caller as the dangerous kind.
    """
    try:
        payload = json.loads(Path(path).read_text())
    except Exception:  # prawduct:allow prawduct/broad-except -- an unreadable journal must degrade to "unknown phase", which every caller treats as mid-flight; re-raising here would turn a recovery hint into a crash.
        return ""
    phase = payload.get("phase")
    return phase if isinstance(phase, str) else ""


def partition_journals(song_dir: Path) -> tuple[list[Path], list[Path]]:
    """Split the journals on disk into ``(mid_flight, shortfall)``.

    A shortfall journal describes a chain that is rebuilt, rebound and verified
    for everything that landed — values are missing from it, the chain is not.
    Everything else is treated as mid-flight — a rebuild that stopped somewhere
    it must not be pushed over. That includes ``verified``, which is **reachable
    and deliberately grouped there**: the verify is stamped before the final
    chain read and the link rebind, so a disconnect in that window leaves a chain
    that is correct while the DB's links still address the PRE-rebuild one. The
    chain being right is exactly what makes that dangerous — a push would plan
    against stale indices and report ok — so `verified` refuses like an
    unfinished rebuild rather than passing like a shortfall. ``--resume`` is the
    right remedy there, which is the other reason it belongs in this half.

    So: four reachable phases, two answers, and the grouping is a judgement
    rather than a fallthrough. An unreadable phase lands here too, because
    unknown has to degrade to dangerous.
    """
    mid_flight: list[Path] = []
    shortfall: list[Path] = []
    for journal in stranded_journals(song_dir):
        (shortfall if journal_phase(journal) == PHASE_SHORTFALL
         else mid_flight).append(journal)
    return mid_flight, shortfall


def stranded_journals(song_dir: Path) -> list[Path]:
    """Every journal left on disk under ``song_dir``, of either kind.

    Two states leave a journal behind, and this does not distinguish them — use
    :func:`partition_journals` where the difference matters:

    * a rebuild stopped between its first delete and its link rebind, so either
      the chain or the links it is addressed by are in an unknown state (phases
      ``journaled`` … ``restored``, and ``verified`` — the verify is stamped
      before the rebind, so that one means a correct chain with stale links);
    * a rebuild FINISHED and came up short — the chain is rebuilt, its links are
      rebound and the verify passed for everything that landed, and the journal
      is kept because it is the only record of the values that did not
      (``shortfall``).

    So "a file here" no longer means "a chain nobody finished". Callers that
    treat it that way are reading one of the two cases wrong.
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

    Returns ``(captured, alerts)``. ``captured`` holds one entry per authored
    live device at DB ``position >= from_position``, in ascending order, each
    carrying BOTH numberings (``position`` and the physical ``device_index`` the
    demolish deletes by) plus its class identity and whatever of ``parameters`` /
    ``input_routing`` / ``chains`` / ``pads`` Live answered for. A read that FAILS
    is recorded as an alert and the key is omitted — never fabricated as "nothing
    there", which would restore a device to defaults and call it a success.

    The span is selected by POSITION, not by physical index. The
    HallucinoteAnalyzer is excluded from the authoring model — it is measurement
    infrastructure the render appends and re-appends, never an authored slot
    (SNP-8R4K) — so a tap sitting ahead of ``from_position`` would otherwise
    shift the span by one and take the device below it out with the rest.
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
    unaddressable = _unaddressable(live_devices)
    if unaddressable:
        raise RebuildRefused(
            f"chain-rebuild: REFUSING to rebuild {parent_kind} #{parent_index} "
            f"from position {from_position} — Live reports "
            f"{len(unaddressable)} device(s) in this chain that the rebuild can "
            f"neither address nor delete: "
            + "; ".join(_describe_device(d) for d in unaddressable)
            + ". Nothing was deleted and no journal was written. A device the "
            "rebuild cannot delete survives the demolish, so the chain it "
            "rebuilds can never match the DB's order — and a device it cannot "
            "address is one it cannot capture, restore or verify, so it cannot "
            "say what was lost either. The HallucinoteAnalyzer is the one device "
            "allowed to survive (the render places it, the authoring model "
            "ignores it by identity, and the restore maps around it by "
            "position); anything else has to leave the chain, or be named in the "
            "DB, before a rebuild can be trusted."
        )
    captured: list[dict[str, Any]] = []
    unreadable_sidechain: list[str] = []
    for logical in _logical_span(live_devices, from_position=from_position):
        dev = logical["device"]
        idx = logical["device_index"]
        entry: dict[str, Any] = {
            "device_index": idx,
            "position": logical["position"],
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
                f"{entry['class']!r} at position {entry['position']} on "
                f"{parent_kind} #{parent_index} "
                f"({p_err or 'no reason given'}) — its dialed "
                f"state is NOT in the journal and will NOT be restored."
            )
        r_ok, r_res, _ = _send(
            send_fn, "ableton_device", "get_input_routing",
            {**flat, "device_index": idx},
        )
        if r_ok and (r_res or {}).get("has_input_routing") is not False:
            entry["input_routing"] = r_res
        elif sidechain_armed_in_probe(entry.get("parameters") or []):
            # The sidechain is ARMED and Live exposes no routing surface, so
            # there is nothing for the journal to hold and nothing for the
            # restore to put back. Every OTHER way this module can lose a
            # source is already an alert raised by the write that failed; this
            # one never reaches a write, so without this it is the single
            # value a rebuild can destroy while exiting 0. Raised HERE, in the
            # pre-delete read, because that is the last moment aborting still
            # saves it — the demolish is what does the destroying.
            unreadable_sidechain.append(
                f"{(entry['name'] or entry['class'] or 'device')!r} on "
                f"{parent_kind} {parent_index}"
            )
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
    if unreadable_sidechain:
        warning = "chain-rebuild: " + unreadable_sidechain_source_warning(
            unreadable_sidechain)
        # Both channels, and they are not redundant. The alert puts it in the
        # report, which is the durable record; the note puts it on screen NOW,
        # which is the only thing that can still save the source — every later
        # phase deletes the device it is describing.
        _operator_note(warning)
        alerts.append(warning)
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
                f"chain-rebuild: deleting {entry['class']!r} at device_index "
                f"{idx} "
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
) -> tuple[set[tuple[int, str]], set[tuple[int, str]], list[str]]:
    """Re-apply parameters, input routing and chain properties from the journal.

    A journaled device is matched to a rebuilt one BY POSITION — the DB position
    both sides agree on — and **addressed by the physical index read back off the
    POST-rebuild chain**. Those are different numbers whenever an unauthored
    device survived the delete: the analyzer that sat at the tail sits at the
    head afterwards, so every authored device moved down one slot and the
    pre-delete index in the journal now names its neighbour (#532). State is
    applied only when the CLASS also agrees at the pairing. That is the honest
    rule for a re-voice: position 1 changed from Analog to Operator, so Analog's
    dialed state has no meaning on Operator and carrying it across would be worse
    than dropping it — the change is reported, and the next push dials Operator
    from the DB. Positions whose class did NOT change are exactly the downstream
    effects this whole module exists to preserve.

    Returns ``(written, expected, alerts)``, both sets keyed by ``(position,
    parameter_name)``:

    * ``written`` is every parameter the restore actually landed. The verify pass
      reads back exactly that set and no more — it gates "every RESTORED
      parameter", and a parameter whose write was REFUSED was not restored.
    * ``expected`` is every writable parameter the restore ATTEMPTED: the
      captured set, minus what Live cannot accept (``is_enabled=False``, nothing
      writable captured) and minus a position whose class changed, where dropping
      the state is the designed answer rather than a loss. The two sets differing
      is a SHORTFALL, and a shortfall is not success (#538) — it keeps the
      journal and exits non-zero, because the journal is the only record of the
      values that did not land.
    """
    alerts: list[str] = []
    written: set[tuple[int, str]] = set()
    expected: set[tuple[int, str]] = set()
    flat = _flat_parent_params(parent_kind, parent_index)
    from_position = journal["from_position"]
    by_position = {
        e["position"]: e
        for e in _logical_span(live_after, from_position=from_position)
    }
    for entry in journal.get("captured", []):
        position = _entry_position(entry)
        rebuilt = by_position.get(position)
        if rebuilt is None:
            expected |= {
                (position, name) for name in _writable_names(entry)
            }
            alerts.append(
                f"chain-rebuild: nothing sits at position {position} on "
                f"{parent_kind} #{parent_index} after the rebuild, so the "
                f"captured state of {entry['class']!r} was NOT restored."
            )
            continue
        now = rebuilt["device"]
        idx = rebuilt["device_index"]
        if _live_class(now) != entry["class"]:
            alerts.append(
                f"chain-rebuild: position {position} on {parent_kind} "
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
                    f"(position {position}, {parent_kind} #{parent_index}) reads "
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
                    f"(position {position}, {parent_kind} #{parent_index}) was "
                    f"captured with no writable value, so it was NOT restored."
                )
                continue
            expected.add((position, name))
            ok, _, error = _send(send_fn, "ableton_device", "set_parameter", {
                "node": node, "parameter_name": name, **kwargs,
            })
            if ok:
                written.add((position, name))
            else:
                alerts.append(
                    f"chain-rebuild: restoring {name!r} on {entry['class']!r} "
                    f"(position {position}, {parent_kind} #{parent_index}) "
                    f"FAILED ({error or 'no reason given'}) — the captured "
                    f"value is in the journal and was not applied."
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
                # The sidechain SOURCE is captured mix work like any parameter,
                # so it is accounted like one: a refusal here has to reach the
                # shortfall (and keep the journal), or the one value #536 and
                # #291's sidechain box both care about is the single thing this
                # module can still lose while exiting 0.
                expected.add((position, _ROUTING_SLOT))
                ok, _, error = _send(
                    send_fn, "ableton_device", "set_input_routing", params,
                )
                if ok:
                    written.add((position, _ROUTING_SLOT))
                if not ok:
                    alerts.append(
                        f"chain-rebuild: restoring the input routing of "
                        f"{entry['class']!r} (position {position}, "
                        f"{parent_kind} #{parent_index}) FAILED "
                        f"({error or 'no reason given'}) — this is the "
                        f"SIDECHAIN SOURCE on a compressor or gate, so check it "
                        f"before trusting the mix."
                    )
        alerts.extend(_restore_chain_properties(
            send_fn, entry=entry, parent_kind=parent_kind,
            parent_index=parent_index, device_index=idx, position=position,
        ))
    return written, expected, alerts


def _writable_names(entry: dict[str, Any]) -> list[str]:
    """The captured parameters of one device that Live would accept a write for.

    The same two exclusions the restore applies — a locked/macro-mapped
    parameter and one captured with nothing writable — so a device the restore
    never reached is counted by what it COULD have carried rather than by its
    whole parameter list. Without that, a 41-parameter EQ Eight with one locked
    band would look like a shortfall it is not.
    """
    names: list[str] = []
    for param in entry.get("parameters", []):
        name = param.get("name")
        if not name or not _restorable(param):
            continue
        if _param_write_kwargs(param) is None:
            continue
        names.append(name)
    return names


_CHAIN_PROPS: tuple[str, ...] = (
    "choke_group", "out_note", "mute", "solo", "volume", "pan",
)


def _restore_chain_properties(
    send_fn: Callable[[Any], Any], *, entry: dict[str, Any],
    parent_kind: str, parent_index: int, device_index: int, position: int,
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
                    f"{position}, {parent_kind} #{parent_index}) reads "
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
                f"{position}, {parent_kind} #{parent_index}) FAILED "
                f"({error or 'no reason given'})."
            )
    return alerts


def _probe_chain(
    send_fn: Callable[[Any], Any], *, parent_kind: str, parent_index: int,
) -> list[dict[str, Any]]:
    """Live's chain exactly as Live reports it — analyzer included.

    The unauthored devices are NOT filtered here, because the physical indices
    are what the restore has to address by and dropping a device from the list
    does not drop it from the chain. Callers derive the authoring model with
    :func:`_logical_chain` / :func:`_logical_span`, which keep both numberings
    together (#532: filtering here and addressing by the filtered order is how
    every restored value landed one slot off).
    """
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
    return list((result or {}).get("devices") or [])


def verify_rebuild(
    send_fn: Callable[[Any], Any], *, plan_devices: list[dict[str, Any]],
    journal: dict[str, Any], parent_kind: str, parent_index: int,
    from_position: int, written: set[tuple[int, str]],
    expected_params: set[tuple[int, str]],
) -> list[dict[str, Any]]:
    """The gate, not a log line.

    The regression this exists to catch is a chain rebuilt with DEFAULT
    parameters: an audibly wrong track that push reports as ``ok``. So success
    requires three things read back off Live, not inferred from the calls having
    returned ok — the class order from ``from_position`` down must equal the DB
    ``position`` order, the restore must have landed SOMETHING of what it
    attempted, and every parameter it claims to have written must read back
    equal.

    That middle check is #538: the value comparison is scoped to ``written``, so
    a restore that landed nothing compares nothing and passes on an empty set.
    A chain at its class defaults is exactly what that looks like from here, so
    "wrote none of them" is a verify FAILURE and not a quiet pass.

    Raises :class:`RebuildVerifyFailed` on any of the three, leaving the journal
    on disk. Returns the re-probed chain on the clean path.
    """
    live_after = _probe_chain(
        send_fn, parent_kind=parent_kind, parent_index=parent_index,
    )
    expected = [
        e["kind"] for e in sorted(plan_devices, key=lambda e: e["position"])
    ]
    actual = [
        _live_class(e["device"])
        for e in _logical_span(live_after, from_position=from_position)
    ]
    if expected != actual:
        raise RebuildVerifyFailed(
            f"chain-rebuild: VERIFY FAILED on {parent_kind} #{parent_index} — "
            f"the DB authors {expected} from position {from_position}, Live "
            f"now has {actual}. The chain is NOT what was asked for; the "
            f"journal is intact."
        )
    if expected_params and not written:
        raise RebuildVerifyFailed(
            f"chain-rebuild: VERIFY FAILED on {parent_kind} #{parent_index} — "
            f"the restore landed NONE of the {len(expected_params)} writable "
            f"parameter(s) it captured, so there is nothing for the read-back "
            f"to compare and a chain sitting at its class DEFAULTS would pass "
            f"here unnoticed. Every failure is named in the alerts above. The "
            f"journal is intact and holds every captured value."
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

    Scoped to ``written`` — the parameters the restore actually landed, keyed by
    the DB position both it and this pass agree on, and read back through the
    POST-rebuild physical index (the same mapping the restore wrote through; a
    read-back aimed at the pre-delete index would compare the neighbouring
    device's values). A parameter the restore declined or was refused on is
    already an alert, and #538's "landed nothing at all" case is caught by
    :func:`verify_rebuild` before this runs.
    """
    mismatches: list[str] = []
    from_position = journal["from_position"]
    by_position = {
        e["position"]: e
        for e in _logical_span(live_after, from_position=from_position)
    }
    for entry in journal.get("captured", []):
        position = _entry_position(entry)
        rebuilt = by_position.get(position)
        if rebuilt is None or _live_class(rebuilt["device"]) != entry["class"]:
            # Not restored, and the restore already alerted about it.
            continue
        idx = rebuilt["device_index"]
        wanted = {
            p["name"]: p for p in entry.get("parameters", [])
            if (position, p.get("name")) in written
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
                f"{entry['class']!r} at position {position}: its parameters "
                f"could not be read back ({error or 'no reason given'}), so "
                f"the restore is unproven"
            )
            continue
        now_by_name = {
            p.get("name"): p for p in ((result or {}).get("parameters") or [])
        }
        for name, param in wanted.items():
            read = now_by_name.get(name)
            if read is None:
                mismatches.append(
                    f"{entry['class']!r} at position {position}: parameter "
                    f"{name!r} is gone after the rebuild"
                )
                continue
            before, after = param.get("value"), read.get("value")
            if before is None or after is None:
                continue
            if abs(float(before) - float(after)) > _PARAM_EPSILON:
                mismatches.append(
                    f"{entry['class']!r} at position {position}: {name!r} was "
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
        # Two states leave a journal, and telling the operator the wrong one
        # sends them at the wrong remedy: `--resume` demolishes the chain, which
        # is recovery for a gutted one and destruction for a correct one.
        if journal_phase(journal_path) == PHASE_SHORTFALL:
            raise RebuildRefused(
                f"chain-rebuild: a SHORTFALL journal for {parent_kind} "
                f"#{parent_index} is already on disk at {journal_path}. That "
                f"chain was rebuilt and its links were rebound — it is correct "
                f"— but some captured values never landed, and this file is the "
                f"only record of them. Starting over now would capture the "
                f"chain as it stands and overwrite those values for good.\n"
                f"  Re-apply what the DB authors:  push execute --only devices\n"
                f"  Or retry the refused writes:   hallucinote chain-rebuild "
                f"--resume {journal_path}\n"
                f"    (that demolishes and rebuilds a chain that is already "
                f"correct, to re-attempt what Live refused)\n"
                f"Then delete the journal. Read it first if you want to know "
                f"which values are at stake."
            )
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
    written, expected_params, restore_alerts = _restore(
        send_fn, journal=journal, parent_kind=parent_kind,
        parent_index=parent_index, live_after=live_after,
    )
    result.restored_params = len(written)
    result.expected_params = len(expected_params)
    result.alerts.extend(restore_alerts)
    journal["phase"] = PHASE_RESTORED
    write_journal(journal_path, journal)

    # Raises with the journal intact if Live disagrees.
    verify_rebuild(
        send_fn, plan_devices=journal["plan_devices"], journal=journal,
        parent_kind=parent_kind, parent_index=parent_index,
        from_position=from_position, written=written,
        expected_params=expected_params,
    )
    journal["phase"] = PHASE_VERIFIED
    write_journal(journal_path, journal)

    if conn is not None and session_id is not None:
        # Read the chain ONE more time rather than trusting the pre-delete
        # indices: the links are addresses the next push writes through, and
        # the whole of #532 is that a surviving device makes the captured index
        # and the real one disagree.
        index_by_position = {
            e["position"]: e["device_index"]
            for e in _logical_chain(_probe_chain(
                send_fn, parent_kind=parent_kind, parent_index=parent_index,
            ))
        }
        result.notes.extend(_rebind_links(
            conn, journal=journal, index_by_position=index_by_position,
            session_id=session_id, actor=actor, reason=reason,
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

    missing = expected_params - written
    if missing:
        # A SHORTFALL (#538): the chain is in the DB's order and everything that
        # landed reads back equal, and some of the captured mix work is still
        # only in the journal. That is not success, so the journal stays — it is
        # the only record of the values that did not land, and the run it
        # describes is the one an operator has to finish by hand.
        result.ok = False
        result.journal_path = journal_path
        # Stamp the journal so a later reader can tell this chain apart from one
        # a rebuild abandoned: the links are rebound and the chain is in the
        # DB's order here, so `push execute` warns about it rather than
        # refusing (which would block the very recovery the alert recommends).
        journal["phase"] = PHASE_SHORTFALL
        write_journal(journal_path, journal)
        result.alerts.append(
            f"chain-rebuild: SHORTFALL on {parent_kind} #{parent_index} — "
            f"{len(written)} of {len(expected_params)} writable parameter(s) "
            f"captured were restored; {len(missing)} were not (each named "
            f"above). The journal is KEPT at {journal_path}: it holds every "
            f"captured value, including the ones that did not land. Re-apply "
            f"them — `push execute --only devices` for anything the DB already "
            f"authors — then delete the journal, which is what tells the next "
            f"rebuild this chain is no longer mid-flight."
        )
        return result

    # The journal is removed ONLY now, past the verify and with nothing left
    # unrestored — the other half of writing it before the first delete.
    journal_path.unlink(missing_ok=True)
    result.journal_path = None
    result.ok = True
    return result


def _rebind_links(
    conn: sqlite3.Connection,
    *,
    journal: dict[str, Any],
    index_by_position: dict[int, int],
    session_id: str,
    actor: str,
    reason: str | None,
) -> list[str]:
    """Re-record ``ableton_links`` against the rebuilt chain's PHYSICAL indices.

    Written through the standard mutators (``M.link_db_to_ableton``), so the
    event log stays complete and no schema changes. This is what makes a SECOND
    push after a reconcile emit no drift note for this parent (#323): the next
    probe finds each DB device already linked and class-matched at its position,
    so it neither re-emits the note nor re-plans a load.

    ``ableton_index`` is consumed as a **physical** device index — it is what
    ``plan_push_devices`` hands ``set_parameter`` as ``device_index`` — so this
    writes the index the device actually answers to, taken from a post-rebuild
    chain read, NOT its DB ``position``. The two agree only while the analyzer
    is terminal, which is exactly what a rebuild has temporarily undone: with
    the tap surviving at the head, position *q* answers to index *q+1*, and
    writing the position here pointed every link one device short. That is #532
    again, one layer out — the restore addressed the right device and the links
    sent the next push to the wrong one, including the
    ``push execute --only devices`` that the shortfall alert recommends.

    A position with no entry in ``index_by_position`` is not linked and says so:
    a link is an address, and an address nobody verified is the thing this whole
    module exists to stop writing.
    """
    notes: list[str] = []
    parent_kind = journal["parent_kind"]
    parent_index = journal["parent_index"]
    for entry in journal["plan_devices"]:
        physical = index_by_position.get(entry["position"])
        if physical is None:
            notes.append(
                f"chain-rebuild: position {entry['position']} on {parent_kind} "
                f"#{parent_index} is not in the post-rebuild chain, so its DB "
                f"device link was NOT rebound — the next push will re-probe and "
                f"bind it, or refuse."
            )
            continue
        M.link_db_to_ableton(
            conn,
            session_id=session_id,
            db_kind="device",
            db_id=entry["db_id"],
            ableton_index=physical,
            actor=actor,
            reason=reason or (
                f"chain-rebuild: {parent_kind}#{parent_index} position "
                f"{entry['position']} at device_index {physical}"
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

    Replaying a ``shortfall`` journal is a legitimate RETRY rather than a
    recovery: that chain is already correct, so this demolishes and rebuilds it
    to re-attempt the writes Live refused (a parameter that was automated when
    the first run reached it may not be now). It costs a full rebuild of a
    working chain, which is worth knowing before reaching for ``--resume auto``
    when a shortfall journal is the one lying around.

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
        {
            "device_index": e["device_index"],
            "position": e["position"],
            "class": _live_class(e["device"]),
        }
        for e in _logical_span(live_now, from_position=from_position)
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
    if result.ok and not result.alerts:
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
    # An alert over a COMPLETE restore is operator-actionable but not a failure:
    # the chain is verified correct and Live refused nothing the capture could
    # carry (a macro-mapped parameter was never writable to begin with). Exit 0
    # with the alert printed, the same severity split the push report uses.
    #
    # A SHORTFALL is a failure (#538). Captured mix work did not make it back
    # onto the chain, and the run that says so cannot also say 0 — an operator
    # re-running #291's witness box reads the exit code before the report, and a
    # 0 there is what let this path run green for the module's whole life.
    if not result.ok:
        shortfall = result.expected_params - result.restored_params
        sys.stderr.write(
            f"chain-rebuild: restored {result.restored_params} of "
            f"{result.expected_params} writable parameter(s) captured on "
            f"{result.parent_kind} #{result.parent_index} — {shortfall} could "
            f"not be written (named in the ALERT lines above). The journal is "
            f"still on disk at {result.journal_path}, holding every captured "
            f"value including those. Exiting 1: a chain missing restored state "
            f"is not a chain that was rebuilt.\n"
        )
        return 1
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
    mid_flight, shortfall = partition_journals(Path(song_dir))
    if not mid_flight and not shortfall:
        sys.stderr.write(
            f"chain-rebuild: no stranded journal under "
            f"{journal_dir_for(Path(song_dir))} — nothing to resume.\n"
        )
        return None
    if not mid_flight:
        # `auto` means "finish the rebuild that stopped". A shortfall journal is
        # not that: its chain is rebuilt, linked and verified for everything that
        # landed, so replaying it would demolish a correct chain to retry a
        # refused write. That can be what the operator wants, but never by
        # inference — make them name the file.
        sys.stderr.write(
            "chain-rebuild: no unfinished rebuild to resume. What is on disk is "
            "a SHORTFALL journal, whose chain is already rebuilt and linked:\n"
            + "".join(f"  {p}\n" for p in shortfall)
            + "  Re-apply what the DB authors:  push execute --only devices\n"
            "  To retry the refused writes instead, name the journal: "
            "--resume <path> (that demolishes and rebuilds a correct chain).\n"
        )
        return None
    if len(mid_flight) > 1:
        sys.stderr.write(
            "chain-rebuild: several stranded journals; name the one to "
            "replay:\n" + "".join(f"  {p}\n" for p in mid_flight)
        )
        return None
    return mid_flight[0]


def _cli_send_fn() -> Callable[[Any], Any]:
    """Lazy resolver for ``hallucinote_mcp.client.send``.

    A module-level seam so tests can monkeypatch it — the same reason
    ``push_cli._resolve_send_fn`` exists, and for the same failure: patching
    the in-function import via ``sys.modules`` doesn't reach an already-bound
    ``client`` attribute.
    """
    from hallucinote_mcp import client as _client  # type: ignore[import-not-found]
    return _client.send
