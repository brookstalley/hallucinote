"""Handlers for ``ableton_analysis``.

The analysis surface is the read-side counterpart to ``ableton_render``:
``render`` produces a captures dir on disk; ``analyze`` consumes it +
the song's DB-recorded intent and writes a ``MixReport`` JSON at
``songs/<slug>/analysis/<ts>.json``.

Both actions are server-side — analysis touches disk + the song DB
only, never Live. The handler shape mirrors
``handlers/ableton_annotation.py`` (DB resolution via
``hallucinote.db.connection.resolve_db_path``; teaching error when the
song dir or DB row is missing).

Why not declare ``db_writes=True``? The MVP doesn't emit events — the
MixReport is a pure read-side artifact. When ``AUDIO_ANALYZED`` becomes
an event kind (P3 backlog), this handler flips on ``db_writes`` and
threads ``_request_id`` into the event.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from ..dispatcher import LiveContext  # noqa: F401  (used in type hints)

# Guarded import: the `hallucinote` package is NOT vendored into Live's
# User Library, so a module-level import would crash the Remote Script
# load. Same pattern as `handlers/ableton_annotation.py:62-73` — the
# import is only exercised on the MCP server side (where this handler
# actually runs, gated by runs_server_side=True).
try:
    from hallucinote.audio import (
        DeclaredReverbSend,
        SectionWindow,
        TempoSegment,
        analyze_mix,
    )
    from hallucinote.audio.levels import live_fader_gain
    from hallucinote.db import queries as Q
    from hallucinote.db.connection import init_db, resolve_db_path
    # Reuse the canonical bar→beat converter the push planner uses — it walks
    # the song's time_signature_map so meter changes accumulate exactly. Both
    # section windows and tempo-map segments are positioned through it.
    from hallucinote.sync.push import _position_bar_to_beats
    _HAS_HALLUCINOTE = True
except ImportError:  # pragma: no cover - exercised in Live's vendored env
    analyze_mix = None  # type: ignore[assignment]
    DeclaredReverbSend = None  # type: ignore[assignment]
    SectionWindow = None  # type: ignore[assignment]
    TempoSegment = None  # type: ignore[assignment]
    Q = None  # type: ignore[assignment]
    init_db = None  # type: ignore[assignment]
    resolve_db_path = None  # type: ignore[assignment]
    _position_bar_to_beats = None  # type: ignore[assignment]
    _HAS_HALLUCINOTE = False

# `track_id_for_surface` is the canonical DB-UUID → capture-surface-ID
# translator. Importing it (vs hand-rolling the `f"track:{n}"` shape)
# keeps the convention sweep-safe — if the surface-ID format ever
# changes, the analyzer module is the single point of update.
from ..analyzer.setup import track_id_for_surface  # noqa: E402


class _AnalysisError(ValueError):
    """Teaching error for analysis-handler failures.

    Inherits from ValueError so the dispatcher's broad-except translates
    it to a structured ``ok=False`` response — same shape as the
    annotation handler's failure path.
    """


def _resolve_song_dir(song_slug: str) -> Path:
    """The song's working directory (`songs/<slug>/`).

    Reaches it the same way the annotation handler does — by going up
    from the DB path resolver. Keeps the DB-discovery logic in one
    place (``hallucinote.db.connection.resolve_db_path``).
    """
    db_path = resolve_db_path(song_slug)
    return db_path.parent


def _latest_captures_dir(song_slug: str) -> Path:
    """Pick the most recent captures dir under ``songs/<slug>/captures/``.

    Names are ISO-8601 (UTC, like ``20260527T200614Z``) so lex order
    == chronological order. Raises a teaching ``_AnalysisError`` if the
    captures dir is empty or absent.
    """
    captures_root = _resolve_song_dir(song_slug) / "captures"
    if not captures_root.exists():
        raise _AnalysisError(
            f"no captures directory at {captures_root} — has "
            f"ableton_render(action='render', song_slug={song_slug!r}) "
            f"been called yet? Captures are written to "
            f"songs/{song_slug}/captures/<iso-ts>/."
        )
    candidates = sorted(
        p for p in captures_root.iterdir()
        if p.is_dir() and (p / "manifest.json").exists()
    )
    if not candidates:
        raise _AnalysisError(
            f"{captures_root} has no captures dirs with a manifest.json — "
            f"each ableton_render(render) call writes one; if you see "
            f"WAVs but no manifest the render didn't complete cleanly."
        )
    return candidates[-1]


def _latest_report_path(song_slug: str) -> Path | None:
    """Most recent MixReport JSON in ``songs/<slug>/analysis/``, or None."""
    analysis_root = _resolve_song_dir(song_slug) / "analysis"
    if not analysis_root.exists():
        return None
    candidates = sorted(p for p in analysis_root.glob("*.json"))
    return candidates[-1] if candidates else None


def _utc_timestamp() -> str:
    """ISO-8601 UTC with second precision, no separators — matches the
    capture-dir naming convention so MixReport files sort alongside
    their source captures."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _existing_db_path(song_slug: str) -> Path:
    """Resolve the song DB path, failing loud if the slug isn't a built song.

    Existence check only (no open) — the handler opens the DB exactly once for
    well-formedness validation + both collectors. Catches a typo'd slug before
    a MixReport gets written against random captures.
    """
    db_path = resolve_db_path(song_slug)
    if not db_path.exists():
        raise _AnalysisError(
            f"no song DB at {db_path} — slug {song_slug!r} doesn't name "
            f"a built song. `python3 songs/{song_slug}/build.py --reset` "
            f"creates it."
        )
    return db_path


def _collect_declared_sends(
    conn: "sqlite3.Connection", song_id: str,
) -> list["DeclaredReverbSend"]:
    """Lift DB-declared reverb-send intents into ``DeclaredReverbSend`` records
    for ``analyze_mix``, using an already-open connection.

    Translates DB UUIDs (``sends.from_track_id`` / ``sends.to_return_id``)
    into the capture manifest's ``track:N`` / ``return:N`` surface IDs
    (see ``analyzer.setup.track_id_for_surface``). This is the boundary:
    the DB is keyed by UUID, captures are keyed by structurally-stable
    surface index — ``analyze_mix`` looks up dry/wet by capture-side ID,
    so the lift has to happen here before the call.

    Empty list when the song has no intents declared yet — ``analyze_mix``
    emits its own ``skipped_analyses`` entry teaching the caller to declare
    them via ``set_send_intended_rt60``.
    """
    rows = Q.get_reverb_send_intents_for_song(conn, song_id)
    return [
        DeclaredReverbSend(
            dry_track_id=track_id_for_surface("track", int(row["from_track_index"])),
            wet_return_track_id=track_id_for_surface(
                "return", int(row["return_position"])
            ),
            declared_rt60_s=float(row["intended_rt60_s"]),
        )
        for row in rows
    ]


def _collect_stem_gains(
    conn: "sqlite3.Connection", song_id: str,
) -> dict[str, float]:
    """Per-track linear fader gain ({tracks.id: gain}) for mix-level masking.

    Captured stems are pre-fader (F1); masking needs mix-level. Convert each
    track's normalized ``volume`` to a linear gain via ``live_fader_gain`` so
    ``analyze_mix`` can scale the masking input. A NULL volume (uncaptured)
    defaults to unity (1.0) — no correction rather than a guess. Static gain
    only; volume automation is a deferred refinement (see audio/levels.py).
    """
    gains: dict[str, float] = {}
    for row in Q.get_tracks_for_song(conn, song_id):
        vol = row["volume"]
        if vol is not None:
            gains[row["id"]] = live_fader_gain(float(vol))
    return gains


def _collect_sections(
    conn: "sqlite3.Connection", song_id: str,
) -> list["SectionWindow"]:
    """Lift the song's ``sections`` table into beat-domain ``SectionWindow``
    records for ``analyze_mix``, using an already-open connection.

    Sections are stored as named half-open ``[start_bar, end_bar)`` spans
    (``sections`` table); the capture's transport window and the analysis
    pipeline work in song-absolute beats. This is the boundary: convert
    each bar bound to beats via ``_position_bar_to_beats`` (which walks the
    song's ``time_signature_map`` so meter changes accumulate exactly),
    then hand beat windows to ``analyze_mix`` — which slices audio by beat
    and stays DB-agnostic.

    ``cue_points`` are deliberately NOT used: they're point markers with no
    spans, so they can't scope a loudness window. Named sectional structure
    lives in ``sections``.

    Empty list when the song declares no sections — ``analyze_mix`` emits
    its own ``skipped_analyses`` entry teaching the caller to declare them
    via ``create_section``.
    """
    section_rows = Q.get_sections_for_song(conn, song_id)
    ts_points = Q.get_time_signature_map(conn, song_id)
    return [
        SectionWindow(
            name=row["name"],
            start_beat=_position_bar_to_beats(row["start_bar"], ts_points),
            end_beat=_position_bar_to_beats(row["end_bar"], ts_points),
        )
        for row in section_rows
    ]


def _collect_tempo_map(
    conn: "sqlite3.Connection", song_id: str,
) -> list["TempoSegment"]:
    """Read the song's ``tempo_map`` and lift it into beat-domain
    ``TempoSegment`` records for ``analyze_mix``, using an already-open
    connection.

    Tempo rows are keyed by ``start_bar``; each bar bound is converted to a
    song-absolute beat via ``_position_bar_to_beats`` (the same exact meter
    walk ``_collect_sections`` uses), giving ``analyze_mix`` the variable-tempo
    map it needs for accurate beat→sample windowing. Empty list when the song
    has no tempo_map rows — ``analyze_mix`` then falls back to the constant-
    tempo linear map (calibrated to the audio duration), so this is a safe
    no-op, not a silent drop of required data.

    Caveat: this feeds the analyzer the *declared* tempo_map. It assumes the
    render honored it. Today the push layer materializes only the bar-1 tempo
    (the non-bar-1-tempo gap in ``.prawduct/backlog.md``), so a song that
    declares variable tempo currently renders at one tempo — for that song the
    declared changes aren't in the audio and ``BeatSampleMap`` documents how
    that can be less accurate than the linear fallback. Harmless for the
    constant-tempo songs that are all push can render today (byte-identical),
    and correct once variable-tempo rendering lands.
    """
    tempo_rows = Q.get_tempo_map(conn, song_id)
    ts_points = Q.get_time_signature_map(conn, song_id)
    return [
        TempoSegment(
            start_beat=_position_bar_to_beats(row["start_bar"], ts_points),
            bpm=float(row["tempo_bpm"]),
        )
        for row in tempo_rows
    ]


def analyze_handler(
    _context: LiveContext,
    *,
    song_slug: str,
    captures_dir: str | None = None,
) -> dict[str, Any]:
    """Run analyze_mix against a captures dir; write the report; return path.

    Returns: ``{report_path, schema_version, finding_count, summary}``
    where summary names the master peak, overshoot count, and any
    out-of-tolerance reverb sends.
    """
    if not _HAS_HALLUCINOTE:  # pragma: no cover - exercised in Live's vendored env
        raise _AnalysisError(
            "ableton_analysis requires the hallucinote package — this "
            "handler must run server-side, not from Live's Remote Script "
            "vendored env (which doesn't ship hallucinote). Check the "
            "action's runs_server_side flag."
        )

    db_path = _existing_db_path(song_slug)

    captures_path = (
        Path(captures_dir).resolve()
        if captures_dir is not None
        else _latest_captures_dir(song_slug)
    )
    manifest = captures_path / "manifest.json"
    if not manifest.exists():
        raise _AnalysisError(
            f"no manifest.json at {captures_path} — captures dirs are "
            f"produced by ableton_render(render) and always include "
            f"manifest.json next to the WAVs."
        )

    # Single open: validates the DB is well-formed (init_db runs the
    # idempotent migration) AND serves all three collectors. Previously each
    # collector — and the existence verifier — opened its own connection
    # (a quadruple-open per handler call once the tempo_map collector landed).
    conn = init_db(db_path)
    try:
        song = conn.execute(
            "SELECT id FROM songs WHERE name = ?", (song_slug,)
        ).fetchone()
        song_id = song["id"] if song is not None else None
        declared_sends = _collect_declared_sends(conn, song_id) if song_id else []
        sections = _collect_sections(conn, song_id) if song_id else []
        tempo_map = _collect_tempo_map(conn, song_id) if song_id else []
        stem_gains = _collect_stem_gains(conn, song_id) if song_id else {}
    finally:
        conn.close()
    report = analyze_mix(
        captures_path,
        declared_reverb_sends=declared_sends,
        sections=sections,
        tempo_map=tempo_map,
        # Masking is per-section evidence; enable it whenever the song declares
        # sections (the handler already gated section work on that). It is
        # neutral measurement — the holistic interpreter grades it vs intent.
        # NOTE (F1): captured stems are pre-fader, so real-song masking is
        # provisional until level reconstruction (build-plan C3) lands.
        analyze_masking=bool(sections),
        # Mix-level reconstruction (F1): scale each pre-fader stem by its
        # static fader gain so masking sees mix balance, not source level.
        # The fader curve is an unverified approximation (see audio/levels.py).
        stem_gains=stem_gains,
    )

    analysis_dir = _resolve_song_dir(song_slug) / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    report_path = analysis_dir / f"{_utc_timestamp()}.json"
    report_dict = report.to_json_dict()
    report_path.write_text(
        json.dumps(report_dict, indent=2),
        encoding="utf-8",
    )

    out_of_tolerance = [
        r for r in report_dict["reverb_verifications"]
        if not r["within_tolerance"]
    ]
    summary = {
        "master_true_peak_dbtp": report_dict["master"]["loudness"]["true_peak_dbtp"],
        "overshoot_count": len(report_dict["overshoots"]),
        "reverb_out_of_tolerance_count": len(out_of_tolerance),
        "section_count": len(report_dict["per_section"]),
        "skipped_analyses_count": len(report_dict["skipped_analyses"]),
    }
    return {
        "report_path": str(report_path),
        "schema_version": report_dict["schema_version"],
        "finding_count": len(report_dict["findings"]),
        "summary": summary,
    }


def get_latest_report_handler(
    _context: LiveContext,
    *,
    song_slug: str,
) -> dict[str, Any]:
    """Return the most recent MixReport JSON for ``song_slug``.

    Returns: ``{report_path, report}`` where ``report`` is the parsed
    JSON dict. Raises ``_AnalysisError`` if the song has no analyses on
    disk yet.
    """
    if not _HAS_HALLUCINOTE:  # pragma: no cover - exercised in Live's vendored env
        raise _AnalysisError(
            "ableton_analysis requires the hallucinote package — "
            "see analyze_handler for the same diagnosis."
        )
    _existing_db_path(song_slug)  # fail loud on a typo'd slug
    report_path = _latest_report_path(song_slug)
    if report_path is None:
        raise _AnalysisError(
            f"no MixReport JSON found under "
            f"songs/{song_slug}/analysis/ — has "
            f"ableton_analysis(action='analyze') been called yet for "
            f"this song?"
        )
    return {
        "report_path": str(report_path),
        "report": json.loads(report_path.read_text(encoding="utf-8")),
    }


__all__ = [
    "analyze_handler",
    "get_latest_report_handler",
]
