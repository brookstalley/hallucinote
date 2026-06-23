"""ARR-PROJ Chunk 3 — the canonical arrangement integrity comparator.

ONE comparator, two consumers (design §6b-B):
  (a) the push-time assertion folded into the arrangement phase (PREVENTION) —
      `assert_arrangement_materialized`;
  (b) the ``hallucinote verify-arrangement`` audit CLI (DETECTION).

It compares a clip's DB notes against Live's actual arrangement-clip notes,
encoding the normalizations the 2026-06-21 bulk-drop / 2026-06-22 orphan bugs
(and the ARR-CMPHALT false-halts) proved necessary — a raw note_count compare
cries wolf:

  1. **Live collapses same-(pitch, start) and truncates a same-pitch overlap.**
     Two faces of one Live constraint — same-pitch notes may not overlap. (a)
     Same (pitch, start): compare the distinct-(pitch, start) collapsed set, not
     raw counts. build.py legitimately stacks notes sharing pitch+start with
     different duration/velocity (e.g. ``add_wildness``); Live holds one per
     (pitch, start). Confirmed live on alien (Human Riff chorus3: 332 raw DB →
     305 Live, *faithful*). (b) Different starts, overlapping: when build.py
     authors a same-pitch note whose duration runs past the next same-pitch
     onset (wildness sustains, legato, doublings), Live ``set_notes`` truncates
     the earlier note to end exactly at that onset — faithful (every onset
     survives, only ``dur`` clamps). Normalize the SAME clamp into both note sets
     before comparing (``_clamp_same_pitch_overlaps``) so a faithful trim is not
     read as a duration mismatch (ARR-CMPHALT Finding 1).
  2. **Float tolerance.** start/duration within ``eps_beats``, pitch exact,
     velocity within ``vel_tol`` (capture/probe introduces ~1e-7 noise; the MCP
     note API already ints velocity, so the tolerance is a safety margin). A
     start on a half-eps bucket boundary can bucket to adjacent integers on the
     two sides; a boundary-split reconcile repairs it so one onset is never
     split into a false missing+extra (ARR-CMPHALT Finding 2).
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
    """Quantize a start time to an integer eps-bucket for grouping. A start on a
    half-eps boundary can land in adjacent buckets on the DB vs Live side
    (``round`` is half-to-even and the round-tripped values differ sub-ULP); the
    boundary-split reconcile in :func:`compare_clip_notes` repairs that, so a
    genuine correspondence is never left split as missing+extra (ARR-CMPHALT
    Finding 2)."""
    return round(float(start) / eps)


def _dur_vel_match(a: NoteLite, b: NoteLite, eps: float, vel_tol: int) -> bool:
    return abs(a.dur - b.dur) <= eps and abs(a.vel - b.vel) <= vel_tol


def _clamp_same_pitch_overlaps(notes: list[NoteLite], eps: float) -> list[NoteLite]:
    """Mirror Live's same-pitch overlap truncation (ARR-CMPHALT Finding 1).

    Live's clip model forbids two same-pitch notes from overlapping, so
    ``set_notes`` trims each note's duration to end no later than the next
    same-pitch *onset*. Apply the identical clamp to a note set so a faithfully
    materialized overlap compares equal instead of reading as a duration
    mismatch. Pure and idempotent — re-clamping an already-trimmed set (Live's
    side) is a no-op. Only ever *shortens* a duration; never adds, drops, or
    moves a note, so a genuine missing/extra onset is unaffected."""
    by_pitch: dict[int, list[NoteLite]] = {}
    for nl in notes:
        by_pitch.setdefault(nl.pitch, []).append(nl)
    out: list[NoteLite] = []
    for group in by_pitch.values():
        starts = sorted(nl.start for nl in group)
        for nl in group:
            # The next same-pitch onset is the smallest start more than eps
            # beyond this note's (notes within eps share an onset — a stack —
            # and do not truncate each other).
            next_onset = next((s for s in starts if s > nl.start + eps), None)
            if next_onset is not None:
                gap = next_onset - nl.start
                if nl.dur > gap + eps:  # genuine overlap → clamp to the onset
                    nl = NoteLite(nl.pitch, nl.start, gap, nl.vel)
            out.append(nl)
    return out


def compare_clip_notes(
    db_notes: Iterable[Any],
    live_notes: Iterable[Any],
    *,
    eps_beats: float = DEFAULT_EPS_BEATS,
    vel_tol: int = DEFAULT_VEL_TOL,
) -> ClipDiff:
    """Compare one clip's DB notes against Live's actual notes.

    Both are collapsed to the distinct-(pitch, eps-bucketed start) audible set
    (normalization #1a), after clamping same-pitch overlaps to mirror Live's
    truncation (#1b, ``_clamp_same_pitch_overlaps``). A DB key may carry a
    *stack* of (dur, vel) variants (wildness); Live holds one note per key,
    faithful if it matches ANY member of the DB stack within tolerance (#2).
    Returns a :class:`ClipDiff`.
    """
    eps = eps_beats
    db_lites = _clamp_same_pitch_overlaps([_to_lite(n) for n in db_notes], eps)
    live_lites = _clamp_same_pitch_overlaps([_to_lite(n) for n in live_notes], eps)
    db_groups: dict[tuple[int, int], list[NoteLite]] = {}
    for nl in db_lites:
        db_groups.setdefault((nl.pitch, _bucket(nl.start, eps)), []).append(nl)
    live_groups: dict[tuple[int, int], list[NoteLite]] = {}
    for nl in live_lites:
        live_groups.setdefault((nl.pitch, _bucket(nl.start, eps)), []).append(nl)

    diff = ClipDiff()
    db_keys = set(db_groups)
    live_keys = set(live_groups)

    # Pair DB keys to Live keys: exact (pitch, eps-bucket) matches first, then
    # reconcile Finding-2 boundary splits among the leftovers. A note whose start
    # lands on a half-eps bucket boundary buckets to ADJACENT integers on the DB
    # vs Live side, so the SAME onset would otherwise surface as both a `missing`
    # (DB bucket) and an `extra` (Live bucket) — a note must never appear in both.
    pairs: list[tuple[tuple[int, int], tuple[int, int]]] = [
        (k, k) for k in db_keys & live_keys
    ]
    unmatched_db = sorted(db_keys - live_keys)
    unmatched_live = sorted(live_keys - db_keys)
    for dk in unmatched_db[:]:
        pitch, bucket = dk
        for lk in unmatched_live:
            # Same pitch, adjacent bucket, representative starts within eps = one
            # onset split by the round() boundary, not a genuine drop+orphan pair.
            if (lk[0] == pitch and abs(lk[1] - bucket) <= 1
                    and abs(db_groups[dk][0].start - live_groups[lk][0].start) <= eps):
                pairs.append((dk, lk))
                unmatched_db.remove(dk)
                unmatched_live.remove(lk)
                break

    for dk in unmatched_db:
        # One representative per missing collapsed key (the audible note dropped).
        diff.missing.append(db_groups[dk][0])
    for lk in unmatched_live:
        # Every Live note at an un-authored key is extra (orphan / stack member).
        diff.extra.extend(live_groups[lk])
    for dk, lk in pairs:
        members = db_groups[dk]
        for lv in live_groups[lk]:
            if not any(_dur_vel_match(dbn, lv, eps, vel_tol) for dbn in members):
                diff.mismatch.append((members[0], lv))

    return diff
