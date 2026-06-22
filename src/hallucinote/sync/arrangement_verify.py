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
      * ``skipped_audio``   — audio placement (CLP-AUD2; no MIDI notes to check).
      * ``track_unlinked``  — the placement's track isn't linked in the session.
      * ``probe_failed``    — Live's note/clip probe errored for this placement.
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

    _CLEAN = ("faithful", "skipped_audio")
    # SILENT corruption — what the push-time assert HALTs on. track_unlinked /
    # probe_failed are operational (the planner already alerted on a skipped
    # track; a probe error is transient), NOT silent note corruption, so they
    # don't halt a push mid-flight — but the CLI audit still surfaces them.
    _CORRUPTION = ("diverged", "missing_clip")

    @property
    def faithful(self) -> bool:
        """Strict — every placement clean AND no orphan clips. The CLI's verdict."""
        return (
            all(r.status in self._CLEAN for r in self.results)
            and not self.extra_live_clips
        )

    def has_corruption(self) -> bool:
        """The push-time HALT criterion: a materialized clip's notes diverged, a
        placement dropped, or an orphan clip survived. Excludes the operational
        non-corruption statuses (track_unlinked / probe_failed)."""
        return (
            any(r.status in self._CORRUPTION for r in self.results)
            or bool(self.extra_live_clips)
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
    live_clips: list[dict[str, Any]], start_beats: float, eps: float,
) -> dict[str, Any] | None:
    """The Live arrangement clip whose start matches ``start_beats`` within eps."""
    best = None
    best_d = eps
    for c in live_clips:
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
            for r in rows:
                report.results.append(PlacementResult(
                    tname, r["clip_name"],
                    _position_bar_to_beats(r["start_bar"], ts),
                    status="probe_failed",
                    detail=f"ableton_clip(list) failed: {getattr(resp, 'error', '?')}",
                ))
            continue
        live_clips = list((resp.result or {}).get("clips") or [])
        matched_live_idx: set[int] = set()

        for r in rows:
            start_b = _position_bar_to_beats(r["start_bar"], ts)
            clip_row = Q.get_clip(conn, r["clip_id"])
            lc = _find_live_at(live_clips, start_b, eps_beats)
            if clip_row is not None and clip_row["kind"] == "audio":
                if lc is not None:
                    matched_live_idx.add(lc["arrangement_clip_index"])
                report.results.append(PlacementResult(
                    tname, r["clip_name"], start_b, status="skipped_audio",
                    detail="audio placement (CLP-AUD2) — no MIDI notes to verify",
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
    lines.append(
        f"  {len(divs)} placement divergence(s), "
        f"{len(report.extra_live_clips)} orphan clip(s)."
    )
    return "\n".join(lines)
