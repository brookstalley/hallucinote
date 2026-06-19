"""Push-time tuning notices for alt-tuned songs (MICROTUNE Chunk 3, gated).

Two operator-facing notices, emitted by ``push_execute.execute_push`` *before the
phase loop* and **only** when the song carries an alternate tuning
(``songs.tuning_ref`` set — NULL for the 99.99%, who pay nothing here):

1. **Re-load instruction** (:func:`reload_instruction`) — the cached ``.ascl`` is
   the human re-load file; the push cannot load it (the LOM tuning surface is
   read-only), so it *instructs* the operator to drag it into Live's Tuning
   section before playback. This mirrors the existing manual-guidance pattern.

2. **Drift warning** (:func:`drift_warning`) — the push re-reads
   ``song.tuning_system`` and warns (NON-blocking) when what's loaded in Live
   doesn't match what the song stored: nothing loaded at all (playback would be a
   wrong 12-TET), or a *different* tuning loaded (name/period mismatch). Silent
   when they match.

**Isolation (FR-6).** This module is on the core side (``sync/`` is scanned by the
isolation test), so it must **not** import ``hallucinote.tuning``. It reads the
persisted tuning state through the *tuning-agnostic* core query
:func:`hallucinote.db.queries.get_song_tuning` and parses only the two
locked-format keys it needs from the blob (``name`` + ``period_cents`` — the
format is locked in ``hallucinote.tuning.model.TuningData`` /
``alternate-tunings.md`` §6). That tiny restatement is the deliberate cost of the
core never importing the bolt-on.

**Confidence — the loaded-tuning read (verify-api closed 2026-06-19).** Both the
"nothing loaded" shape (``song.tuning_system → {"type":"NoneType",...}``) and the
loaded-tuning **scalar** reads — ``name`` (str) + ``pseudo_octave_in_cents``
(float) — are now **live-confirmed** off a real loaded tuning (Wendy Carlos
gamma; ``api-notes-tuning.md``). The remaining limit is a deliberate *scope*
choice, not an unverified one: the compare is name+period only — a coarse but
real drift signal — NOT the full cents array (full-cents drift is out of v1
scope). When the scalars can't be read, the notice still says so rather than
faking a verdict.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

from hallucinote.db import queries as Q
from hallucinote.tuning_probe import is_no_tuning_loaded

logger = logging.getLogger("hallucinote.sync.push.tuning_notice")

# Cents tolerance for the loaded-vs-stored period match. Deliberately LOOSER than
# TuningData's own ``_PERIOD_TOLERANCE_CENTS`` (1e-3, which guards an internal
# round-trip invariant): this compares a *live LOM read* against a stored value,
# so it must absorb Live's float reporting noise too — while staying tight enough
# that a genuinely different period (e.g. an octave vs a non-octave tuning) reads
# as drift.
_PERIOD_TOLERANCE_CENTS = 1e-2

_TUNING_SYSTEM_PATH = "song.tuning_system"


@dataclass(frozen=True)
class LoadedTuning:
    """The scalar fields of the tuning currently loaded in Live, as re-read.

    ``name`` / ``period_cents`` are ``None`` when a tuning *is* loaded but its
    scalars could not be read (a sub-read of ``name`` / ``pseudo_octave_in_cents``
    returned nothing) — distinct from ``loaded=None`` at the call site, which means
    *nothing* is loaded.
    """

    name: str | None
    period_cents: float | None


def reload_instruction(slug: str, tuning_ref: str) -> str:
    """The operator instruction to load the song's cached ``.ascl`` (Part 2).

    ``tuning_ref`` is the song-relative POSIX path (e.g. ``tunings/19-edo.ascl``).
    We name it relative to the song dir + the slug rather than a hardcoded
    ``songs/<slug>/`` filesystem prefix: songs may live in their own repo now (the
    framework⇄songs split), so an absolute ``songs/`` prefix would mislead. This
    matches the lens caveat, which shows the same song-relative ref.
    """
    return (
        f"tuning: song {slug!r} is in a non-12 tuning — load its {tuning_ref} "
        "(under the song directory) into Live's Tuning section before playback "
        "(push can't load it; the LOM tuning surface is read-only)."
    )


def _stored_name_and_period(stored_blob: str) -> tuple[str, float]:
    """Pull ``(name, period_cents)`` out of the persisted ``tuning_data`` blob.

    The blob is the locked TuningData JSON; only these two keys are read here.
    Raises ``ValueError`` on a malformed blob so the caller degrades to a soft
    "couldn't verify" notice rather than a wrong drift verdict.
    """
    try:
        raw = json.loads(stored_blob)
        return str(raw["name"]), float(raw["period_cents"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"unreadable tuning_data blob: {exc}") from exc


def drift_warning(stored_blob: str, loaded: LoadedTuning | None) -> str | None:
    """Compare the song's stored tuning against what's loaded in Live (Part 3).

    Pure (no I/O) so the warn/silent decision is fully unit-testable without
    Live. ``loaded is None`` means nothing is loaded; a :class:`LoadedTuning`
    with ``None`` fields means a tuning is loaded but its scalars couldn't be
    read. Returns the warning line, or ``None`` when the loaded tuning matches
    the stored one (silent on match).
    """
    try:
        stored_name, stored_period = _stored_name_and_period(stored_blob)
    except ValueError as exc:
        return (
            f"tuning: could not verify the loaded tuning against the song — "
            f"{exc}. Confirm the right .ascl is loaded in Live."
        )

    if loaded is None:
        return (
            f"tuning DRIFT: this song expects the non-12 tuning {stored_name!r} "
            "but Live has NO tuning loaded — playback would be a wrong 12-TET. "
            "Load the song's .ascl into Live's Tuning section (see the load "
            "instruction above)."
        )

    if loaded.name is None or loaded.period_cents is None:
        return (
            f"tuning: a tuning is loaded in Live, but Hallucinote could not read "
            f"its name/period to confirm it matches {stored_name!r} "
            "(the scalar read returned nothing) — confirm by ear."
        )

    name_matches = loaded.name == stored_name
    period_matches = abs(loaded.period_cents - stored_period) <= _PERIOD_TOLERANCE_CENTS
    if name_matches and period_matches:
        return None
    return (
        f"tuning DRIFT: Live has {loaded.name!r} (period "
        f"{loaded.period_cents:.2f}¢) loaded, but this song was authored against "
        f"{stored_name!r} (period {stored_period:.2f}¢) — they differ. Confirm "
        "the right .ascl is loaded before playback."
    )


def _probe_get(send_fn: Callable[..., Any], request_cls: Any, path: str) -> Any:
    """Read a LOM path via ``ableton_probe`` get; return its ``value``.

    Raises on a non-ok response or a send failure so the caller's guarded
    best-effort wrapper can degrade to a soft notice. ``allow_version_mismatch``
    is set because the read is non-mutating and therefore safe under the drift
    the server/Remote-Script may carry (api-notes-tuning.md).
    """
    resp = send_fn(request_cls(
        tool="ableton_probe", action="get",
        params={"path": path}, allow_version_mismatch=True,
    ))
    if not getattr(resp, "ok", False):
        raise RuntimeError(
            f"ableton_probe get {path} failed: {getattr(resp, 'error', '?')}"
        )
    result = getattr(resp, "result", None) or {}
    return result


def _read_loaded_tuning(send_fn: Callable[..., Any], request_cls: Any) -> LoadedTuning | None:
    """Re-read Live's currently-loaded tuning. ``None`` ⇒ nothing loaded.

    The ``{"type": "NoneType", ...}`` shape (12-TET / no tuning) is the
    live-confirmed signal for "nothing loaded". When a tuning IS loaded, read its
    scalar ``name`` + ``pseudo_octave_in_cents`` sub-paths (both live-confirmed by
    verify-api); a sub-read miss yields ``LoadedTuning(None, None)`` so the caller
    reports "couldn't verify" instead of a false match.
    """
    top = _probe_get(send_fn, request_cls, _TUNING_SYSTEM_PATH)
    if is_no_tuning_loaded(top):
        # Same narrow classifier read.py uses — a {type:"TuningSystem",value:None}
        # is NOT "nothing loaded" (the unconfirmed-shape lesson); it falls through
        # to the scalar reads, which degrade to a "couldn't verify" note if they
        # miss, rather than silently claiming 12-TET.
        return None
    # A tuning is loaded — try the scalar fields. Either miss → can't-verify.
    try:
        name = _probe_get(send_fn, request_cls, f"{_TUNING_SYSTEM_PATH}.name").get("value")
        period = _probe_get(
            send_fn, request_cls, f"{_TUNING_SYSTEM_PATH}.pseudo_octave_in_cents",
        ).get("value")
    except (RuntimeError, OSError):
        return LoadedTuning(None, None)
    name = str(name) if name is not None else None
    period = float(period) if isinstance(period, (int, float)) else None
    return LoadedTuning(name, period)


def collect_tuning_notices(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    send_fn: Callable[..., Any],
    request_cls: Any,
) -> list[str]:
    """The push-time notice list for a song: empty for 12-TET, else instruction
    (+ drift warning) (MICROTUNE Chunk 3).

    Reads ``tuning_ref`` / ``tuning_data`` through the tuning-agnostic core
    query, so the 12-TET path costs one SELECT and **no** Live round-trip (the
    re-read fires only when a tuning is set). The live re-read is best-effort:
    any failure degrades to a soft notice — a drift check must never break or
    mask the push itself.
    """
    row = Q.get_song_tuning(conn, song_id)
    if row is None or row["tuning_ref"] is None:
        return []  # 12-TET — inert, no Live read.

    tuning_ref = row["tuning_ref"]
    stored_blob = row["tuning_data"]
    notices = [reload_instruction(_song_slug(conn, song_id), tuning_ref)]

    try:
        loaded = _read_loaded_tuning(send_fn, request_cls)
    except Exception as exc:  # prawduct:allow prawduct/broad-except -- best-effort drift re-read: any failure (connection, wire, handler) must degrade to a soft notice, never break/mask the push
        logger.info("tuning drift re-read skipped: %s", exc)
        notices.append(
            "tuning: could not re-read Live's tuning to verify it matches the "
            f"song ({exc}) — confirm the .ascl is loaded before playback."
        )
        return notices

    if stored_blob is None:
        # tuning_ref set without a blob shouldn't happen (set_song_tuning writes
        # both), but never crash the push over it — name-less drift note.
        if loaded is None:
            notices.append(
                "tuning DRIFT: this song expects a non-12 tuning but Live has "
                "none loaded — playback would be a wrong 12-TET."
            )
        return notices

    warn = drift_warning(stored_blob, loaded)
    if warn is not None:
        notices.append(warn)
    return notices


def _song_slug(conn: sqlite3.Connection, song_id: str) -> str:
    """The song's slug (== its ``name``) for the load-instruction path."""
    song = Q.get_song(conn, song_id)
    return song["name"] if song is not None else song_id


__all__ = [
    "LoadedTuning",
    "reload_instruction",
    "drift_warning",
    "collect_tuning_notices",
]
