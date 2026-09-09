"""ARR-PROJ Chunk 3 — arrangement integrity verification orchestration.

Pairs each DB arrangement placement with its Live arrangement clip (by track +
start position), probes Live's actual notes via the NOTE API (a FRESH callback,
never ``ableton_clip list`` note_count — §6a / §6b-B), and compares with the
canonical comparator (:func:`arrangement_compare.compare_clip_notes`). Two
consumers share this one orchestration:

  (a) :func:`assert_arrangement_materialized` — the push-time PREVENTION assert,
      folded into the executor after the arrangement phase: HALT on divergence
      instead of reporting OK (the backstop for both 2026-06-21/-22 bugs).
  (b) :func:`verify_song_arrangement` + :func:`format_report` — the DETECTION
      layer behind ``hallucinote verify-arrangement``.

The note probes go through ``send_fn`` (the MCP TCP client; tests inject a fake),
matching the dispatch path of the rest of the sync layer.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable

from hallucinote.db import queries as Q

from .arrangement_compare import ClipDiff, DEFAULT_EPS_BEATS, compare_clip_notes
from .geometry import _position_bar_to_beats


@dataclass
class PlacementResult:
    """One DB arrangement placement's verification outcome.

    ``status`` is one of:
      * ``faithful``        — Live's notes match the DB collapsed set.
      * ``diverged``        — present but the notes differ (``diff`` carries the
        extra/missing/mismatch).
      * ``missing_clip``    — no Live arrangement clip at this position (the
        whole placement was dropped).
      * ``skipped_audio``   — audio placement that IS present; only the note
        comparison is skipped, because an audio clip has none. Absence is
        ``missing_clip``, exactly as for MIDI.
      * ``track_unlinked``  — the placement's track isn't linked in the session.
      * ``probe_failed``    — Live's per-clip NOTE probe errored: the clip IS
        there at the right position, only its contents could not be read. A
        transient, per-clip read failure — not evidence of corruption.
      * ``lane_probe_failed`` — Live's per-track ``ableton_clip(list,
        location='arrangement')`` errored, so the whole LANE is unreadable.
        Categorically stronger than ``probe_failed`` (ARR-ORPHAN2): the pusher
        uses that same probe to plan the CLEAR, so an unreadable lane was
        neither cleared nor rebuilt, and orphan detection never ran on it. A
        placement in this state is silent data loss, not a transient read
        hiccup — see :attr:`ArrangementReport._CORRUPTION`.
    """
    track_name: str
    section: str
    start_beats: float
    status: str
    diff: ClipDiff | None = None
    detail: str = ""


@dataclass
class ArrangementReport:
    results: list[PlacementResult] = field(default_factory=list)
    # Whole arrangement clips present in Live with NO DB placement at their
    # position (a stale/orphan clip the projection would otherwise clear).
    extra_live_clips: list[dict[str, Any]] = field(default_factory=list)
    # ARR-ORPHAN2: tracks whose arrangement LANE could not be listed at all
    # (``{track, track_index, error}``). Recorded separately from the per-
    # placement results because it carries a second fact no placement row can:
    # orphan detection did NOT run for this lane, so ``extra_live_clips`` is
    # known-incomplete. format_report says so rather than implying "no orphans".
    lane_probe_failures: list[dict[str, Any]] = field(default_factory=list)

    _CLEAN = ("faithful", "skipped_audio")
    # SILENT corruption — what the push-time assert HALTs on.
    #
    # track_unlinked / probe_failed stay OUT: the planner already alerted on a
    # deliberately-skipped track, and a per-clip note-read error is transient
    # (the clip is demonstrably at the right position). Neither is note
    # corruption, so neither halts a push mid-flight — the CLI audit still
    # surfaces them.
    #
    # lane_probe_failed IS in (ARR-ORPHAN2). The pusher plans its per-lane CLEAR
    # from the SAME ``ableton_clip(list, location='arrangement')`` probe: when
    # that probe fails, ``plan_push_arrangement`` skips the whole track — no
    # clear, no rebuild — and any orphan already sitting in that lane survives.
    # Tolerating it here is what let a track lose every placement while the
    # phase reported "97/97 ok": the placements came back unverifiable, the
    # orphan was invisible (the lane could not be listed), and nothing halted.
    # An unreadable lane immediately after a materialize is a DROPPED lane until
    # proven otherwise.
    _CORRUPTION = ("diverged", "missing_clip", "lane_probe_failed")

    @property
    def faithful(self) -> bool:
        """Strict — every placement clean AND no orphan clips. The CLI's verdict."""
        return (
            all(r.status in self._CLEAN for r in self.results)
            and not self.extra_live_clips
            and not self.lane_probe_failures
        )

    def has_corruption(self) -> bool:
        """The push-time HALT criterion: a materialized clip's notes diverged, a
        placement dropped, an orphan clip survived, or a whole lane could not be
        read (so it was never cleared and its orphans are invisible). Excludes
        the operational non-corruption statuses (track_unlinked / probe_failed)."""
        return (
            any(r.status in self._CORRUPTION for r in self.results)
            or bool(self.extra_live_clips)
            or bool(self.lane_probe_failures)
        )

    def divergences(self) -> list[PlacementResult]:
        return [r for r in self.results if r.status not in self._CLEAN]


class ArrangementIntegrityError(Exception):
    """Raised by :func:`assert_arrangement_materialized` on divergence — the
    push-time HALT. Carries the report for an actionable message."""

    def __init__(self, report: ArrangementReport) -> None:
        self.report = report
        super().__init__(format_report(report, header="arrangement integrity FAILED"))


def _send(send_fn: Callable[..., Any], tool: str, action: str, **params: Any) -> Any:
    from hallucinote_mcp.wire import Request  # lazy: import-light at module load
    return send_fn(Request(tool=tool, action=action, params=params))


def _find_live_at(
    live_clips: list[dict[str, Any]],
    start_beats: float,
    eps: float,
    consumed: set[int],
) -> dict[str, Any] | None:
    """The closest unconsumed Live arrangement clip whose start matches
    ``start_beats`` within eps.

    ``consumed`` holds the ``arrangement_clip_index`` values already paired to an
    earlier DB placement. Excluding them lets two placements sharing a start on one
    track ("rare but valid" per :func:`Q.get_arrangement_for_song`) each pair to
    their OWN Live clip instead of both matching the single closest one — the
    second's twin would otherwise fall into ``extra_live_clips`` and FALSE-halt a
    faithful build. This mirrors the per-track consumed-index discipline the
    removed SYN-4R7P reconcile used for the same coincident-placement case."""
    best = None
    best_d = eps
    for c in live_clips:
        if c.get("arrangement_clip_index") in consumed:
            continue
        d = abs(float(c["start_beats"]) - start_beats)
        if d <= best_d:
            best, best_d = c, d
    return best


def verify_song_arrangement(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    send_fn: Callable[..., Any] | None = None,
    eps_beats: float = DEFAULT_EPS_BEATS,
) -> ArrangementReport:
    """Compare ``conn``'s DB arrangement against Live's actual arrangement.

    For each DB placement: resolve its track link, probe the track's Live
    arrangement clips, match by start position, probe the matched clip's notes
    (note API, fresh call), and compare to the DB clip's notes. Also surfaces
    whole Live clips with no DB placement (``extra_live_clips``). Returns an
    :class:`ArrangementReport`; never raises on divergence (the caller decides).
    """
    if send_fn is None:
        from hallucinote_mcp import client as _client  # type: ignore[import-not-found]
        send_fn = _client.send

    report = ArrangementReport()
    ts = Q.get_time_signature_map(conn, song_id)
    arr_rows = Q.get_arrangement_for_song(conn, song_id)

    rows_by_track: dict[str, list[sqlite3.Row]] = {}
    for r in arr_rows:
        rows_by_track.setdefault(r["track_id"], []).append(r)

    for track_id, rows in rows_by_track.items():
        tname = rows[0]["track_name"]
        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=track_id,
        )
        if track_at is None:
            for r in rows:
                report.results.append(PlacementResult(
                    tname, r["clip_name"],
                    _position_bar_to_beats(r["start_bar"], ts),
                    status="track_unlinked",
                    detail="track not linked in this session",
                ))
            continue

        resp = _send(send_fn, "ableton_clip", "list",
                     track_index=track_at, location="arrangement")
        if not getattr(resp, "ok", False):
            # ARR-ORPHAN2: the LANE is unreadable — categorically worse than a
            # per-clip note-read failure. The pusher plans its clear from this
            # same probe, so a lane it cannot list is a lane it did not clear
            # and did not rebuild; whatever was there (including an orphan) is
            # still there. Record it as its own halting status AND as a lane
            # failure, so the report can state that orphan detection is
            # known-incomplete for this track rather than implying "no orphans".
            err = getattr(resp, "error", "?")
            report.lane_probe_failures.append(
                {"track": tname, "track_index": track_at, "error": err}
            )
            for r in rows:
                report.results.append(PlacementResult(
                    tname, r["clip_name"],
                    _position_bar_to_beats(r["start_bar"], ts),
                    status="lane_probe_failed",
                    detail=(
                        f"ableton_clip(list, location='arrangement') failed for "
                        f"track {track_at}: {err}. The lane could not be read, so "
                        "push could not clear or rebuild it and this placement is "
                        "UNPROVEN — treat as dropped until a successful re-probe "
                        "says otherwise."
                    ),
                ))
            continue
        live_clips = list((resp.result or {}).get("clips") or [])
        matched_live_idx: set[int] = set()

        for r in rows:
            start_b = _position_bar_to_beats(r["start_bar"], ts)
            clip_row = Q.get_clip(conn, r["clip_id"])
            lc = _find_live_at(live_clips, start_b, eps_beats, matched_live_idx)
            if clip_row is not None and clip_row["kind"] == "audio":
                # PRESENCE is checked for audio exactly as for MIDI; only the
                # NOTE comparison is skipped, because an audio clip has none.
                # The two must stay separate branches: audio placements
                # materialize through the same clear-then-rebuild projection,
                # so a placement the clear removed and the rebuild failed to
                # restore has to read `missing_clip` (halting), never the
                # _CLEAN `skipped_audio`, or the push-time assert is blind to
                # exactly the drop the destructive phase can cause.
                if lc is None:
                    report.results.append(PlacementResult(
                        tname, r["clip_name"], start_b, status="missing_clip",
                        detail="no Live arrangement clip at this position (dropped)",
                    ))
                    continue
                matched_live_idx.add(lc["arrangement_clip_index"])
                report.results.append(PlacementResult(
                    tname, r["clip_name"], start_b, status="skipped_audio",
                    detail="audio placement present — no MIDI notes to verify",
                ))
                continue
            if lc is None:
                report.results.append(PlacementResult(
                    tname, r["clip_name"], start_b, status="missing_clip",
                    detail="no Live arrangement clip at this position (dropped)",
                ))
                continue
            matched_live_idx.add(lc["arrangement_clip_index"])
            nresp = _send(send_fn, "ableton_note", "list", track_index=track_at,
                          location="arrangement", clip_index=lc["arrangement_clip_index"])
            if not getattr(nresp, "ok", False):
                report.results.append(PlacementResult(
                    tname, r["clip_name"], start_b, status="probe_failed",
                    detail=f"ableton_note(list) failed: {getattr(nresp, 'error', '?')}",
                ))
                continue
            live_notes = list((nresp.result or {}).get("notes") or [])
            db_notes = Q.get_notes_for_clip(conn, r["clip_id"])
            diff = compare_clip_notes(db_notes, live_notes, eps_beats=eps_beats)
            report.results.append(PlacementResult(
                tname, r["clip_name"], start_b,
                status="faithful" if diff.faithful else "diverged",
                diff=diff,
            ))

        for c in live_clips:
            if c.get("arrangement_clip_index") not in matched_live_idx:
                report.extra_live_clips.append({"track": tname, **c})

    return report


def assert_arrangement_materialized(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    send_fn: Callable[..., Any] | None = None,
    eps_beats: float = DEFAULT_EPS_BEATS,
) -> ArrangementReport:
    """Push-time PREVENTION assert: verify the freshly-materialized arrangement,
    raise :class:`ArrangementIntegrityError` (HALT) on silent corruption
    (:meth:`ArrangementReport.has_corruption`). Returns the report otherwise.
    Reads in a fresh probe — never inline after the write (§6a).

    ARR-ORPHAN2: "corruption" includes a lane whose ``ableton_clip(list)`` probe
    FAILED. The push planner reads the lane inventory from that same probe, so a
    failure there means the lane was never cleared and never rebuilt — the exact
    state in which a track lost every placement while the phase printed
    "97/97 ok". The only statuses the assert still tolerates are the two the
    planner has ALREADY reported on its own channel: ``track_unlinked`` (planner
    alert / blocked reason) and ``probe_failed`` (a per-clip note read on a clip
    that is demonstrably at the right position).

    SCOPE (design §9 residual risk): this assert is NOTE-only — it does not read
    back clip envelopes, so it cannot catch an envelope-bearing placement that was
    mis-routed to create+fill and silently dropped its clip envelope. That branch's
    correctness rests on :func:`push.envelope_hosting_clip_ids` reusing the
    authoritative ``classify_envelope_route`` (a pure-DB query, unit-tested), NOT
    on this assert. Extending the assert to verify clip envelopes is future work."""
    report = verify_song_arrangement(
        conn, song_id=song_id, session_id=session_id,
        send_fn=send_fn, eps_beats=eps_beats,
    )
    if report.has_corruption():
        raise ArrangementIntegrityError(report)
    return report


def format_report(report: ArrangementReport, *, header: str = "verify-arrangement") -> str:
    """Human-readable, per-(track, section) report — used by the CLI and the
    HALT message. Lists every divergence with extra/missing/mismatch counts."""
    lines = [header]
    divs = report.divergences()
    if report.faithful:
        lines.append(
            f"  OK — {len(report.results)} placement(s) faithful "
            f"(or audio-skipped); no orphan clips."
        )
        return "\n".join(lines)
    for r in divs:
        if r.status == "diverged" and r.diff is not None:
            lines.append(
                f"  [{r.status}] {r.track_name} / {r.section} @ beat {r.start_beats:g}: "
                f"{r.diff.summary()}"
            )
        else:
            lines.append(
                f"  [{r.status}] {r.track_name} / {r.section} @ beat "
                f"{r.start_beats:g}: {r.detail}"
            )
    for c in report.extra_live_clips:
        lines.append(
            f"  [extra_clip] {c.get('track')} / {c.get('name')} @ beat "
            f"{c.get('start_beats')}: a Live arrangement clip with no DB placement"
        )
    for lane in report.lane_probe_failures:
        lines.append(
            f"  [lane_unreadable] {lane.get('track')} (Live track "
            f"{lane.get('track_index')}): {lane.get('error')} — push could not "
            "clear or rebuild this lane, and ORPHAN DETECTION DID NOT RUN on it, "
            "so the orphan count below excludes it."
        )
    lines.append(
        f"  {len(divs)} placement divergence(s), "
        f"{len(report.extra_live_clips)} orphan clip(s), "
        f"{len(report.lane_probe_failures)} unreadable lane(s)."
    )
    return "\n".join(lines)
