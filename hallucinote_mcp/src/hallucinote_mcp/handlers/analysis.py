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
    from hallucinote.audio import DeclaredReverbSend, analyze_mix
    from hallucinote.db import queries as Q
    from hallucinote.db.connection import init_db, resolve_db_path
    _HAS_HALLUCINOTE = True
except ImportError:  # pragma: no cover - exercised in Live's vendored env
    analyze_mix = None  # type: ignore[assignment]
    DeclaredReverbSend = None  # type: ignore[assignment]
    Q = None  # type: ignore[assignment]
    init_db = None  # type: ignore[assignment]
    resolve_db_path = None  # type: ignore[assignment]
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


def _verify_song_db_exists(song_slug: str) -> None:
    """Resolve the song DB to confirm the slug names a real song.

    Open + close — fail loud if the slug is a typo rather than silently
    writing a MixReport against random captures.
    """
    db_path = resolve_db_path(song_slug)
    if not db_path.exists():
        raise _AnalysisError(
            f"no song DB at {db_path} — slug {song_slug!r} doesn't name "
            f"a built song. `python3 songs/{song_slug}/build.py --reset` "
            f"creates it."
        )
    # Open + close to validate the DB is well-formed; init_db runs
    # the idempotent column-migration too.
    conn = init_db(db_path)
    conn.close()


def _collect_declared_sends(song_slug: str) -> list["DeclaredReverbSend"]:
    """Read DB-declared reverb-send intents and lift them into
    ``DeclaredReverbSend`` records for ``analyze_mix``.

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
    db_path = resolve_db_path(song_slug)
    conn = init_db(db_path)
    try:
        song = conn.execute(
            "SELECT id FROM songs WHERE name = ?", (song_slug,)
        ).fetchone()
        if song is None:
            return []
        rows = Q.get_reverb_send_intents_for_song(conn, song["id"])
    finally:
        conn.close()
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

    _verify_song_db_exists(song_slug)

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

    declared_sends = _collect_declared_sends(song_slug)
    report = analyze_mix(captures_path, declared_reverb_sends=declared_sends)

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
    _verify_song_db_exists(song_slug)
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
