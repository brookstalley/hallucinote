"""ARR-PROJ Chunk 3 — the canonical arrangement integrity comparator.

ONE comparator, two consumers (design §6b-B):
  (a) the push-time assertion folded into the arrangement phase (PREVENTION) —
      `assert_arrangement_materialized`;
  (b) the ``hallucinote verify-arrangement`` audit CLI (DETECTION).

It compares a clip's DB notes against Live's actual arrangement-clip notes,
encoding the three normalizations the 2026-06-21 bulk-drop / 2026-06-22 orphan
bugs proved necessary — a raw note_count compare cries wolf:

  1. **Live collapses same-(pitch, start).** Compare the distinct-(pitch, start)
     collapsed set, not raw counts. build.py legitimately stacks notes sharing
     pitch+start with different duration/velocity (e.g. ``add_wildness``); Live
     holds one per (pitch, start). Confirmed live on alien (Human Riff chorus3:
     332 raw DB → 305 Live, *faithful*).
  2. **Float tolerance.** start/duration within ``eps_beats``, pitch exact,
     velocity within ``vel_tol`` (capture/probe introduces ~1e-7 noise; the MCP
     note API already ints velocity, so the tolerance is a safety margin).
  3. **Read via the note API.** This module is PURE — the caller supplies the
     already-probed Live notes (from ``ableton_note(list, location=
     'arrangement')`` / ``get_notes_extended``, NOT ``ableton_clip list``
     note_count), read in a FRESH callback (never inline after the write).

This module does no I/O and never touches Live — it is unit-testable in full.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

DEFAULT_EPS_BEATS = 1e-3
DEFAULT_VEL_TOL = 1  # MIDI velocity units (0-127)


@dataclass(frozen=True)
class NoteLite:
    """The audible quartet, normalized for comparison. ``mute`` is excluded —
    a muted note is still a placed note for integrity purposes."""
    pitch: int
    start: float
    dur: float
    vel: int


def _to_lite(n: Any) -> NoteLite:
    """Accept either a DB note dict (``start_beats``/``duration_beats``) or an
    MCP note dict (``start_time``/``duration``) or a NoteLite — one comparator,
    both note shapes."""
    if isinstance(n, NoteLite):
        return n
    pitch = int(n["pitch"])
    if "start_beats" in n:  # DB note shape
        return NoteLite(pitch, float(n["start_beats"]),
                        float(n["duration_beats"]), int(n["velocity"]))
    # MCP / note-API shape
    return NoteLite(pitch, float(n["start_time"]),
                    float(n["duration"]), int(n["velocity"]))


@dataclass
class ClipDiff:
    """Per-clip divergence. ``faithful`` when all three lists are empty.

    * ``extra``   — audible keys in LIVE but not the DB (orphans / stacks — the
      2026-06-22 ``replace_notes`` orphan bug, or a B-24 stack).
    * ``missing`` — audible keys in the DB but not LIVE (drops — the 2026-06-21
      bulk-drop bug). One representative per collapsed key.
    * ``mismatch``— a key present in both whose Live note matches NO DB stack
      member within tolerance (velocity/duration drift). ``(db_repr, live)``.
    """
    extra: list[NoteLite] = field(default_factory=list)
    missing: list[NoteLite] = field(default_factory=list)
    mismatch: list[tuple[NoteLite, NoteLite]] = field(default_factory=list)

    @property
    def faithful(self) -> bool:
        return not (self.extra or self.missing or self.mismatch)

    def summary(self) -> str:
        if self.faithful:
            return "faithful"
        return (
            f"{len(self.missing)} missing, {len(self.extra)} extra, "
            f"{len(self.mismatch)} mismatch"
        )


def _bucket(start: float, eps: float) -> int:
    """Quantize a start time to an integer eps-bucket. Absorbs the set_notes
    round-trip + capture noise; real note starts sit on musical grids far wider
    than ``eps``, so this never splits a genuine correspondence."""
    return round(float(start) / eps)


def _dur_vel_match(a: NoteLite, b: NoteLite, eps: float, vel_tol: int) -> bool:
    return abs(a.dur - b.dur) <= eps and abs(a.vel - b.vel) <= vel_tol


def compare_clip_notes(
    db_notes: Iterable[Any],
    live_notes: Iterable[Any],
    *,
    eps_beats: float = DEFAULT_EPS_BEATS,
    vel_tol: int = DEFAULT_VEL_TOL,
) -> ClipDiff:
    """Compare one clip's DB notes against Live's actual notes.

    Both are collapsed to the distinct-(pitch, eps-bucketed start) audible set
    (normalization #1). A DB key may carry a *stack* of (dur, vel) variants
    (wildness); Live holds one note per key, faithful if it matches ANY member
    of the DB stack within tolerance (#2). Returns a :class:`ClipDiff`.
    """
    eps = eps_beats
    db_groups: dict[tuple[int, int], list[NoteLite]] = {}
    for n in db_notes:
        nl = _to_lite(n)
        db_groups.setdefault((nl.pitch, _bucket(nl.start, eps)), []).append(nl)
    live_groups: dict[tuple[int, int], list[NoteLite]] = {}
    for n in live_notes:
        nl = _to_lite(n)
        live_groups.setdefault((nl.pitch, _bucket(nl.start, eps)), []).append(nl)

    diff = ClipDiff()
    db_keys = set(db_groups)
    live_keys = set(live_groups)

    for k in db_keys - live_keys:
        # One representative per missing collapsed key (the audible note dropped).
        diff.missing.append(db_groups[k][0])
    for k in live_keys - db_keys:
        # Every Live note at an un-authored key is extra (orphan / stack member).
        diff.extra.extend(live_groups[k])
    for k in db_keys & live_keys:
        members = db_groups[k]
        for lv in live_groups[k]:
            if not any(_dur_vel_match(dbn, lv, eps, vel_tol) for dbn in members):
                diff.mismatch.append((members[0], lv))

    return diff
