"""PSH-DEVDUP — post-phase device-chain integrity verification.

The sibling of :mod:`arrangement_verify` for the ``devices`` phase, and it
exists for the same reason: a materialize step that can corrupt state silently
must PROVE it didn't, not assume it. The arrangement phase learned this when a
clear+rebuild dropped/stacked clips and still reported OK; the devices phase
learned it on 2026-08-08, when a push onto a set that already carried every
track's FX chain appended a second copy of all eighteen effects across nine
tracks and printed ``devices 23/23 ok``. A guitar through two
Overdrive→Amp→Cabinet→Saturator chains is a different instrument, and the
render, the mix and the analysis all ran on it before anyone noticed.

The comparison is deliberately class-shaped, not count-shaped. Live sets
legitimately carry devices the DB never authored (a factory device on a stock
return, something the composer dropped in by hand), and halting on those would
break working flows for no safety gain. What is NEVER legitimate is Live
carrying a device whose CLASS the DB already authors on that same parent, beyond
the count the DB authors — that is the duplication signature, and it is what
halts.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from hallucinote.analyzer_identity import is_analyzer_device
from hallucinote.db import queries as Q

from .push.probe import linked_device_parents


# Per-parent verdicts.
CHAIN_FAITHFUL = "faithful"
"""Live's authored chain is exactly the DB's authored chain."""
CHAIN_DUPLICATED = "duplicated"
"""Live carries MORE devices of a class the DB authors here than the DB
authors. The corruption signature — this is what halts the push."""
CHAIN_EXTRA = "extra"
"""Live carries devices beyond the DB's chain, but of classes the DB does not
author on this parent (a factory/hand-placed device). Benign; reported."""
CHAIN_SHORT = "short"
"""Live's authored chain is missing devices the DB authors. Not corruption (the
push under-delivered rather than over-delivered) but never silent."""
CHAIN_DRIFT = "drift"
"""Same device count, different classes — the set is not the song. Reported."""
CHAIN_PROBE_FAILED = "probe_failed"
"""Live's chain could not be read for this parent. Nothing is claimed."""


@dataclass
class ChainResult:
    """One parent's device-chain verification outcome."""
    parent_kind: str          # 'track' | 'return' | 'master'
    parent_index: int
    parent_name: str
    expected: list[str] = field(default_factory=list)   # DB device classes, position order
    actual: list[str] = field(default_factory=list)     # Live authored classes, index order
    status: str = CHAIN_FAITHFUL
    duplicated: list[str] = field(default_factory=list)  # classes over-represented in Live

    def describe(self) -> str:
        where = (
            "master"
            if self.parent_kind == "master"
            else f"{self.parent_kind} {self.parent_name!r} (#{self.parent_index})"
        )
        return (
            f"{where}: DB authors {self.expected}, Live has {self.actual}"
            + (f"; DUPLICATED {self.duplicated}" if self.duplicated else "")
        )


@dataclass
class DeviceChainReport:
    results: list[ChainResult] = field(default_factory=list)

    def duplicated(self) -> list[ChainResult]:
        return [r for r in self.results if r.status == CHAIN_DUPLICATED]

    def has_corruption(self) -> bool:
        """The push-time HALT criterion: at least one parent's Live chain
        carries a duplicate of a class the DB authors there."""
        return bool(self.duplicated())

    def anomalies(self) -> list[ChainResult]:
        """Non-fatal disagreements worth surfacing as warnings."""
        return [
            r for r in self.results
            if r.status in (CHAIN_EXTRA, CHAIN_SHORT, CHAIN_DRIFT)
        ]


class DeviceChainIntegrityError(Exception):
    """Raised by :func:`assert_device_chains_materialized` when Live carries a
    duplicated device chain. Carries the report for the caller's error record."""

    def __init__(self, report: DeviceChainReport) -> None:
        self.report = report
        dupes = report.duplicated()
        detail = "; ".join(r.describe() for r in dupes)
        super().__init__(
            f"devices integrity: {len(dupes)} device chain(s) in Live carry a "
            f"DUPLICATE of a device the DB already authors there — the push "
            f"doubled a signal path. {detail}. Live has no reorder API, so this "
            f"cannot be repaired by re-pushing: delete the duplicate devices in "
            f"Live (or push into a fresh set), then re-run "
            f"`push_cli probe-and-link <session> --song <slug> --probe` so the "
            f"DB binds the chain that survives."
        )


def compare_chain(expected: list[str], actual: list[str]) -> tuple[str, list[str]]:
    """Pure comparator: DB-authored device classes vs Live's authored classes.

    Returns ``(status, duplicated_classes)``.

    The rule, in order:

    * identical lists → ``faithful``.
    * Live has MORE of some class than the DB authors on this parent →
      ``duplicated``, naming those classes. This is the only corruption verdict,
      and it is class-multiset-based rather than length-based on purpose: a
      Live chain may legitimately hold devices the DB doesn't know about (a
      factory device on a stock return, a hand-dropped utility), and a
      length-only check would halt on those for no safety gain.
    * Live has devices the DB doesn't author, none of them over-represented →
      ``extra``.
    * Live is missing something the DB authors → ``short``.
    * same multiset, different order, or equal-length disagreement → ``drift``.
    """
    if expected == actual:
        return CHAIN_FAITHFUL, []
    want = Counter(expected)
    have = Counter(actual)
    duplicated = sorted(
        cls for cls, n in have.items() if cls in want and n > want[cls]
    )
    if duplicated:
        return CHAIN_DUPLICATED, duplicated
    if have - want:
        return CHAIN_EXTRA, []
    if want - have:
        return CHAIN_SHORT, []
    return CHAIN_DRIFT, []


def _live_class(device: dict[str, Any]) -> str:
    return device.get("class_display_name") or device.get("class_name") or ""


def verify_device_chains(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    probe_fn: Callable[[str, int], list[dict[str, Any]] | None],
) -> DeviceChainReport:
    """Compare every addressable parent's DB device chain against Live's.

    ``probe_fn(parent_kind, parent_index)`` returns the parent's live device
    list (``ableton_device(action='list')`` shape) or ``None`` when the read
    failed — a failure is recorded as ``probe_failed`` and claims nothing, never
    fabricating either a clean bill or a corruption halt.

    The HallucinoteAnalyzer is excluded from Live's side (measurement
    infrastructure, SNP-8R4K); DB-side placeholders and any legacy analyzer row
    are excluded to match what the planner would actually push.
    """
    report = DeviceChainReport()
    tracks, returns, master = linked_device_parents(
        conn, song_id=song_id, session_id=session_id,
    )
    for parents, parent_kind, get_devices_fn in (
        (tracks, "track", Q.get_devices_for_track),
        (returns, "return", Q.get_devices_for_return),
        (master, "master", Q.get_devices_for_track),
    ):
        for parent in parents:
            expected = [
                d["kind"] for d in get_devices_fn(conn, parent["db_id"])
                if d["kind"] != "placeholder" and not is_analyzer_device(d)
            ]
            if not expected:
                # The DB authors nothing here — there is no expectation to
                # violate, and whatever Live carries is the composer's.
                continue
            live = probe_fn(parent_kind, parent["ableton_index"])
            if live is None:
                report.results.append(ChainResult(
                    parent_kind=parent_kind,
                    parent_index=parent["ableton_index"],
                    parent_name=parent["name"],
                    expected=expected,
                    status=CHAIN_PROBE_FAILED,
                ))
                continue
            actual = [
                _live_class(d) for d in live if not is_analyzer_device(d)
            ]
            status, duplicated = compare_chain(expected, actual)
            report.results.append(ChainResult(
                parent_kind=parent_kind,
                parent_index=parent["ableton_index"],
                parent_name=parent["name"],
                expected=expected,
                actual=actual,
                status=status,
                duplicated=duplicated,
            ))
    return report


def assert_device_chains_materialized(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    probe_fn: Callable[[str, int], list[dict[str, Any]] | None],
) -> DeviceChainReport:
    """Run :func:`verify_device_chains` and RAISE on duplication.

    The executor calls this after the devices phase. Returns the report on the
    clean path so the caller can surface ``anomalies()`` / ``probe_failed`` as
    warnings — "couldn't verify" must read differently from "verified clean".
    """
    report = verify_device_chains(
        conn, song_id=song_id, session_id=session_id, probe_fn=probe_fn,
    )
    if report.has_corruption():
        raise DeviceChainIntegrityError(report)
    return report
