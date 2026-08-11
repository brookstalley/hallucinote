"""Handlers for ``ableton_analysis``.

The analysis surface is the read-side counterpart to ``ableton_render``:
``render`` produces a captures dir on disk; ``analyze`` consumes it +
the song's DB-recorded intent and writes a ``MixReport`` JSON at
``songs/<slug>/analysis/<ts>.json``.

Both actions are server-side — analysis touches disk + the song DB
only, never Live. The handler follows the standard server-side DB
shape: DB resolution via ``hallucinote.db.connection.resolve_db_path``
and a teaching error when the song dir or DB row is missing.

This module lives in ``hallucinote_mcp.server_side`` (not ``handlers/``)
so its changes stay out of the version fingerprint — see that package's
docstring and ``hallucinote_mcp/__init__.py`` ``_FINGERPRINT_PATHS`` (MCP-7F2K).

Why not declare ``db_writes=True``? The MVP doesn't emit events — the
MixReport is a pure read-side artifact. When ``AUDIO_ANALYZED`` becomes
an event kind (P3 backlog), this handler flips on ``db_writes`` and
threads ``_request_id`` into the event.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    # Type-only: sqlite3 is FORBIDDEN as a top-level runtime import here —
    # this module is scanned by test_remote_script_import_safety (Live's
    # embedded Python doesn't ship it). The "sqlite3.Connection" annotations
    # below are lazy strings; checkers just need the name.
    import sqlite3

from ..dispatcher import LiveContext  # noqa: F401  (used in type hints)
# jobs.py lives in the FINGERPRINTED handlers/ set (it runs in BOTH processes —
# render's worker uses it Live-side, analyze's uses it here server-side), so the
# server-side analyze handlers reach UP into it. This is server_side → handlers,
# the allowed direction; the isolation invariant only forbids handlers/ →
# server_side/ (a Live-side change must never hinge on server-side code). See
# the package docstring + test_server_side_isolation.py.
from ..handlers.jobs import (
    DEFAULT_STATUS_LONG_POLL_S,
    JobRegistry,
    default_registry,
    spawn_daemon,
)

logger = logging.getLogger("hallucinote_mcp.analysis")

# Guarded import: the `hallucinote` package is NOT vendored into Live's
# User Library, so a module-level import would crash the Remote Script
# load. The standard server-side-handler pattern — the import is only
# exercised on the MCP server side (where this handler actually runs,
# gated by runs_server_side=True).
try:
    from hallucinote.audio import (
        DeclaredEnvelope,
        DeclaredReverbSend,
        DeclaredWidthControl,
        SectionEnergy,
        SectionWindow,
        TempoSegment,
        analyze_mix,
        is_stale,
        loaded_signature,
    )
    from hallucinote.audio.levels import live_fader_gain
    from hallucinote.db import queries as Q
    from hallucinote.db.connection import init_db, resolve_db_path
    # The write half of the persisted-path contract — status.json is written
    # into the git-tracked analysis/ dir alongside the reports, so the path it
    # carries is anchored to the song dir, not to this machine.
    from hallucinote.paths import (
        portable_path,
        portable_text,
        resolve_portable_path,
        self_ignore_dir,
    )
    from hallucinote.workspace import explain_unresolved_song
    # Reuse the canonical bar→beat converter the push planner uses — it walks
    # the song's time_signature_map so meter changes accumulate exactly. Both
    # section windows and tempo-map segments are positioned through it.
    from hallucinote.sync.push import _position_bar_to_beats
    # The canonical "newest take" ordering, shared with the retention sweep
    # (`hallucinote.takes`). The two MUST agree: a sweep that ordered takes
    # differently from this selector could delete the very take the next
    # analysis would have chosen.
    from hallucinote.takes import recency_key
    _HAS_HALLUCINOTE = True
except ImportError:  # pragma: no cover - exercised in Live's vendored env
    analyze_mix = None  # type: ignore[assignment]
    is_stale = None  # type: ignore[assignment]
    loaded_signature = None  # type: ignore[assignment]
    # The class names double as types, so mypy needs [misc] ("cannot assign
    # to a type") on top of [assignment] for the None fallbacks.
    DeclaredEnvelope = None  # type: ignore[assignment, misc]
    DeclaredReverbSend = None  # type: ignore[assignment, misc]
    DeclaredWidthControl = None  # type: ignore[assignment, misc]
    SectionEnergy = None  # type: ignore[assignment, misc]
    SectionWindow = None  # type: ignore[assignment, misc]
    TempoSegment = None  # type: ignore[assignment, misc]
    Q = None  # type: ignore[assignment]
    init_db = None  # type: ignore[assignment]
    resolve_db_path = None  # type: ignore[assignment]
    explain_unresolved_song = None  # type: ignore[assignment]
    portable_path = None  # type: ignore[assignment]
    portable_text = None  # type: ignore[assignment]
    resolve_portable_path = None  # type: ignore[assignment]
    self_ignore_dir = None  # type: ignore[assignment]
    _position_bar_to_beats = None  # type: ignore[assignment]
    recency_key = None  # type: ignore[assignment]
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


def _capture_recency_key(captures_dir: Path) -> tuple[str, float, str]:
    """Recency sort key for a captures dir, robust to NON-ISO dir names.

    Delegates to ``hallucinote.takes.recency_key``, which owns the definition so
    the retention sweep and this selector can never disagree about which take is
    newest. Kept as a named local so the reason this ordering exists stays
    readable here: renders name their dirs ISO-8601 (``20260527T200614Z``), but a
    dir may also be hand-named for a focused capture (e.g.
    ``v4-seam-verse2-chorus2``), and keying on the dir NAME let such a dir
    silently shadow the newest render — ``'v'`` (0x76) sorts ABOVE every
    ``2026…`` timestamp (0x32), so ``max(by name)`` picked the stale ``v4-…``
    dir and the analysis read the wrong (often tiny, single-section) audio.

    Only ever called after the ``_HAS_HALLUCINOTE`` gate (via
    :func:`_latest_captures_dir` from ``analyze_handler``), so the guarded
    import is always resolved by the time this runs."""
    return recency_key(captures_dir)


def _latest_captures_dir(song_slug: str) -> Path:
    """Pick the most recent captures dir under ``songs/<slug>/captures/``.

    "Most recent" is the manifest's recorded ``captured_at`` (see
    :func:`_capture_recency_key`) — NOT the dir name, so a hand-named focused
    capture can't shadow the newest render. Raises a teaching ``_AnalysisError``
    if the captures dir is empty or absent.
    """
    captures_root = _resolve_song_dir(song_slug) / "captures"
    if not captures_root.exists():
        raise _AnalysisError(
            f"no captures directory at {captures_root} — has "
            f"ableton_render(action='start', song_slug={song_slug!r}) "
            f"been called yet? (Then poll action='status' to completion.) "
            f"Captures are written to {captures_root}/<iso-ts>/."
        )
    candidates = [
        p for p in captures_root.iterdir()
        if p.is_dir() and (p / "manifest.json").exists()
    ]
    if not candidates:
        raise _AnalysisError(
            f"{captures_root} has no captures dirs with a manifest.json — "
            f"each ableton_render(action='start') render writes one; if you see "
            f"WAVs but no manifest the render didn't complete cleanly."
        )
    return max(candidates, key=_capture_recency_key)


def _latest_report_path(song_slug: str) -> Path | None:
    """Most recent MixReport JSON in ``songs/<slug>/analysis/``, or None.

    Excludes ``status.json`` — that's the BUG3 completion heartbeat the
    analyze handler writes into the same dir, not a report. Report files are
    named ``<utc-ts>.json``; the heartbeat is the lone fixed-name ``.json``,
    so a name match is the precise exclusion (a glob like ``*Z.json`` would be
    brittle to a future report-naming change)."""
    analysis_root = _resolve_song_dir(song_slug) / "analysis"
    if not analysis_root.exists():
        return None
    candidates = sorted(
        p for p in analysis_root.glob("*.json")
        if p.name != ANALYSIS_STATUS_FILENAME
    )
    return candidates[-1] if candidates else None


def _utc_timestamp() -> str:
    """ISO-8601 UTC with second precision, no separators — matches the
    capture-dir naming convention so MixReport files sort alongside
    their source captures."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# The completion-heartbeat filename, written into <analysis_dir> around the
# analyze_mix call (BUG3). analyze_mix runs server-side and can take long
# enough that the MCP wrapper red-times-out at 60s before the report JSON
# (the only completion signal today) appears, forcing fragile dir-watching.
# status.json is the robust signal: running before analyze, then a terminal
# done (with the report path) / error.
ANALYSIS_STATUS_FILENAME = "status.json"


def _write_analysis_status(analysis_dir: Path, status: dict[str, Any]) -> None:
    """Best-effort heartbeat write into <analysis_dir>/status.json.

    Observability only, never analysis-affecting: a write failure must not break
    an analysis whose report is otherwise fine, so the rare filesystem error is
    swallowed (no logic depends on it — the real result is the report JSON; a
    missed heartbeat only costs a poller one more poll). Not an error-hiding
    catch: nothing downstream reads the write's success.
    """
    try:
        (analysis_dir / ANALYSIS_STATUS_FILENAME).write_text(
            json.dumps(status, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _analysis_code_status() -> dict[str, Any]:
    """Loaded-vs-disk version of the analysis pipeline, for the tool response.

    The MCP server caches imported analysis modules, so an edit to
    ``hallucinote.audio`` isn't picked up until ``/mcp`` respawns the
    subprocess. ``signature`` is the content hash of the code that produced
    this response; ``stale`` is True when that loaded code no longer matches
    what's on disk — the cue to respawn. See ``hallucinote.audio.codeversion``.
    """
    return {"signature": loaded_signature(), "stale": is_stale()}


def _existing_db_path(song_slug: str) -> Path:
    """Resolve the song DB path, failing loud if the slug isn't a built song.

    Existence check only (no open) — the handler opens the DB exactly once for
    well-formedness validation + both collectors. Catches a typo'd slug before
    a MixReport gets written against random captures.

    The failure message defers to ``workspace.explain_unresolved_song``, which
    distinguishes the three things a missing DB can mean — the workspace this
    process resolved doesn't hold the song / no marker was found at all so the
    legacy path was used / the song genuinely doesn't exist. The flat "doesn't
    name a built song. run build.py --reset" this replaced ran all three
    together, and told an operator to scaffold a duplicate over a song that was
    built and findable a directory away.
    """
    db_path = resolve_db_path(song_slug)
    if not db_path.exists():
        raise _AnalysisError(
            f"no song DB at {db_path} — {explain_unresolved_song(song_slug)}"
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


# Device parameters that are stereo-WIDTH controls. Deliberately a small closed
# set of exact names rather than a substring match: "Spread" on a Phaser-Flanger
# spreads notch frequencies WITHIN a channel and is not a width control at all —
# mistaking it for one is the exact confusion that made a wet flanger read as
# stereo when the stem was bit-exact mono (STR-4C8N). Add names here only after
# confirming the parameter moves the L/R image.
_WIDTH_PARAMETER_NAMES = frozenset({"Stereo Width"})

# Unity width — Live's Utility default. A pull writes a row for EVERY parameter
# Live reports on a device, not only the ones an author touched, so presence in
# the DB is not evidence of intent: without this filter every untouched Utility
# in the song contributes a "declared 100 %" row, and a naturally wide stem
# carrying one presents to /mix-review as `declared 100 % / measured -3 dB` — a
# contradiction with an intent nobody expressed. The cost is the reverse case: a
# width DELIBERATELY held at unity is indistinguishable from an untouched one and
# is not listed. That asymmetry is the right way round — the lens exists to
# surface contradictions with real intent, and a fabricated declaration
# manufactures them.
_UNITY_WIDTH_DISPLAYS = frozenset({"100 %", "100%", "100.0 %", "100.0%", "100"})


def _collect_declared_width_controls(
    conn: "sqlite3.Connection", song_id: str,
) -> list["DeclaredWidthControl"]:
    """Lift dialled stereo-width device params into ``DeclaredWidthControl``.

    Mirrors ``_collect_declared_sends``: the DB is keyed by UUID, captures by
    surface index, so the translation happens HERE and ``analyze_mix`` stays
    DB-agnostic and joins on ``surface_id`` alone.

    **Three known blind spots, disclosed rather than silent** — ``analyze.py``
    attaches the recognition-scope note to EVERY report, not just the zero case,
    so a partial list never reads as a complete one:

    * Only names in :data:`_WIDTH_PARAMETER_NAMES` are recognised.
    * Only TOP-LEVEL devices on tracks and returns are walked —
      ``get_devices_for_track`` / ``get_devices_for_return`` do not recurse into a
      rack's nested chains, so a Utility inside an Instrument or Audio Effect Rack
      is invisible here. Widening this means a nested-chain walk; until then the
      honest claim is the narrow one.
    * A control at unity (:data:`_UNITY_WIDTH_DISPLAYS`) is not a declaration —
      see that constant for why presence in the DB is not evidence of intent.
    """
    controls: list[DeclaredWidthControl] = []

    def _collect(surface: "str | None", devices) -> None:
        if surface is None:
            return
        for device in devices:
            for param in Q.get_device_parameters(conn, device["id"]):
                if param["name"] not in _WIDTH_PARAMETER_NAMES:
                    continue
                display = param["value_display"]
                if display is None:
                    continue
                if str(display).strip() in _UNITY_WIDTH_DISPLAYS:
                    continue
                controls.append(DeclaredWidthControl(
                    surface_id=surface,
                    device_name=str(device["display_name"]),
                    parameter_name=str(param["name"]),
                    declared_display=str(display),
                ))

    for track in Q.get_tracks_for_song(conn, song_id):
        _collect(
            _track_surface(conn, track["id"]),
            Q.get_devices_for_track(conn, track["id"]),
        )
    # Returns too: a width control on a reverb/delay bus is an ordinary move, and
    # collecting only tracks would make it INVISIBLE rather than skipped — a
    # silent drop, which reads to the caller as "nothing declared".
    for ret in Q.get_returns_for_song(conn, song_id):
        _collect(
            _return_surface(conn, ret["id"]),
            Q.get_devices_for_return(conn, ret["id"]),
        )
    return controls


def _collect_declared_envelopes(
    conn: "sqlite3.Connection", song_id: str,
) -> list["DeclaredEnvelope"]:
    """Lift DB automation envelopes into ``DeclaredEnvelope`` records for
    ``analyze_mix``, resolving each to the capture surface it's measured on.

    Surface resolution (the DB-UUID → ``track:N`` / ``return:N`` boundary):
      - ``device_parameter`` → the track (or return) HOSTING the device
        (device → chain → parent track/return → surface index). The pre-fader
        stem captures the device's timbre change (e.g. the Amp Type flip).
      - ``send_level`` → the RETURN the send feeds (more send → louder return).
      - ``mixer_volume`` / ``mixer_pan`` → the track surface; the audio
        module verifies them on the MASTER (post-fader sum, AUD-3F8M) using
        the declared fader values / pan positions to predict the expected
        master effect, with honest unmeasurable verdicts when the stem is
        too diluted for the master to speak.

    Clip-/note-scoped MIDI automation (clip_cc, clip_pitch_bend,
    note_expression) is not mix-audio automation — dropped here. Breakpoint
    ``time_beats`` is already arrangement-local (song-absolute) beats for
    mixer/send/device envelopes (schema), so no bar→beat conversion is needed.
    Envelopes with fewer than two breakpoints carry no change to verify.
    """
    out: list["DeclaredEnvelope"] = []
    for env in Q.get_envelopes_for_song(conn, song_id):
        surface_id = _envelope_surface_id(conn, env)
        if surface_id is None:
            continue  # unresolvable, or a kind not verifiable from audio
        bps = Q.get_breakpoints(conn, env["id"])
        if len(bps) < 2:
            continue
        out.append(DeclaredEnvelope(
            target_surface_id=surface_id,
            target_kind=env["target_kind"],
            parameter_path=env["parameter_path"],
            breakpoints=tuple(
                (float(b["time_beats"]), float(b["value"])) for b in bps
            ),
        ))
    return out


def _envelope_surface_id(
    conn: "sqlite3.Connection", env: "sqlite3.Row",
) -> "str | None":
    """Capture surface (``track:N`` / ``return:N``) an envelope is measured on,
    or None for kinds not verifiable from a captured surface."""
    kind = env["target_kind"]
    if kind in ("mixer_volume", "mixer_pan"):
        return _track_surface(conn, env["target_track_id"])
    if kind == "send_level":
        return _return_surface(conn, env["target_send_return_id"])
    if kind == "device_parameter":
        device = Q.get_device(conn, env["target_device_id"])
        if device is None:
            return None
        chain = Q.get_device_chain(conn, device["chain_id"])
        if chain is None:
            return None
        if chain["parent_track_id"]:
            return _track_surface(conn, chain["parent_track_id"])
        if chain["parent_return_id"]:
            return _return_surface(conn, chain["parent_return_id"])
        return None  # device in a nested rack chain — not surface-resolvable yet
    return None  # clip_cc / clip_pitch_bend / note_expression — not mix audio


def _track_surface(conn: "sqlite3.Connection", track_id) -> "str | None":
    if not track_id:
        return None
    track = Q.get_track(conn, track_id)
    if track is None:
        return None
    return track_id_for_surface("track", int(track["track_index"]))


def _return_surface(conn: "sqlite3.Connection", return_id) -> "str | None":
    if not return_id:
        return None
    ret = Q.get_return(conn, return_id)
    if ret is None:
        return None
    return track_id_for_surface("return", int(ret["position"]))


def _collect_stem_gains(
    conn: "sqlite3.Connection", song_id: str,
) -> dict[str, float]:
    """Per-track linear fader gain ({tracks.id: gain}) for mix-level masking.

    Captured stems are pre-fader (F1); masking needs mix-level. Convert each
    track's normalized ``volume`` to a linear gain via ``live_fader_gain`` so
    ``analyze_mix`` can scale the masking input. A NULL volume (uncaptured)
    defaults to unity (1.0) — no correction rather than a guess. Static gain
    only; volume automation is a deferred refinement (see audio/levels.py).

    Keyed by the **capture surface ID** (``track:N``), NOT the DB UUID — the
    stems handed to ``apply_stem_gains`` come from the capture manifest and are
    keyed by surface index. Same DB-UUID → surface-ID lift as
    ``_collect_declared_sends`` (via ``track_id_for_surface``); keying by
    ``row['id']`` would silently never match and make the correction a no-op.
    """
    gains: dict[str, float] = {}
    for row in Q.get_tracks_for_song(conn, song_id):
        vol = row["volume"]
        if vol is not None:
            surface_id = track_id_for_surface("track", int(row["track_index"]))
            gains[surface_id] = live_fader_gain(float(vol))
    return gains


def _collect_master_fader_volume(
    conn: "sqlite3.Connection", song_id: str,
) -> float | None:
    """The master track's normalized fader volume (0..1), for the report's
    DELIVERED (post-fader) true-peak.

    The master loudness/true-peak is captured PRE-fader (the HallucinoteAnalyzer
    taps the master DEVICE CHAIN, before the master mixer volume), so `analyze_mix`
    needs the fader to emit `delivered_true_peak_dbtp` (it converts via
    `live_fader_db`). Returns None when there's no master row or a NULL volume —
    then the report's master block stays pre-fader bus only (no false delivered #).
    """
    for row in Q.get_tracks_for_song(conn, song_id):
        if row["kind"] == "master":
            vol = row["volume"]
            return float(vol) if vol is not None else None
    return None


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
            section_id=row["id"],
        )
        for row in section_rows
    ]


def _collect_declared_energy(
    conn: "sqlite3.Connection", song_id: str,
) -> list["SectionEnergy"]:
    """Lift the song's declared per-section ``energy`` (ARR-7M3D) into a list of
    ``SectionEnergy`` the energy-realization lens consumes, using an
    already-open connection.

    Carries each section's ``start_beat`` — derived from ``start_bar`` via the
    same ``_position_bar_to_beats`` meter walk ``_collect_sections`` uses — so it
    shares the lens's join key (``start_beat``, NOT name: ``vary()`` /
    recapitulation repeats section names, so name mis-pairs two distinct
    sections; see the join-key note in ``report.EnergyRealization``). Two
    same-named sections at different ``start_bar`` therefore lift to two
    distinct ``SectionEnergy`` rows.

    NULL-energy sections are EXCLUDED from the lift (not coerced to a fabricated
    value) — the lens never sees a NULL-energy declared section, and a song that
    declared no energy at all lifts to an empty list (``analyze_mix`` then
    records an ``energy_realization`` skip rather than a fabricated ρ).
    """
    section_rows = Q.get_sections_for_song(conn, song_id)
    ts_points = Q.get_time_signature_map(conn, song_id)
    return [
        SectionEnergy(
            start_beat=_position_bar_to_beats(row["start_bar"], ts_points),
            name=row["name"],
            energy=float(row["energy"]),
        )
        for row in section_rows
        if row["energy"] is not None
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
    (the non-bar-1-tempo gap — tracker ids ``TMP-7B3X`` / ``TMP-4J6Q`` /
    ``TMP-5K1R``), so a song that
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
            ramp=row["ramp"],
        )
        for row in tempo_rows
    ]


def analyze_handler(
    _context: LiveContext,
    *,
    song_slug: str,
    captures_dir: str | None = None,
    compare_to: int | None = None,
) -> dict[str, Any]:
    """Run analyze_mix against a captures dir; write the report; return path.

    ``compare_to`` is a song audit-log seq: the report is diffed against
    the previous analysis JSON whose ``db_seq`` matches (per-surface
    loudness deltas + significance flags in ``report.compare_to`` —
    neutral evidence, no findings derived). Captures record their seq in
    ``manifest.db_seq`` at render time.

    Returns: ``{report_path, schema_version, finding_count, summary}``
    where summary names the master peak, overshoot count, any
    out-of-tolerance reverb sends, and (when ``compare_to`` was given)
    the significant-delta count vs the baseline.
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
            f"produced by ableton_render(action='start') and always include "
            f"manifest.json next to the WAVs."
        )

    # Single open: validates the DB is well-formed (init_db runs the
    # idempotent migration) AND serves all three collectors. Previously each
    # collector — and the existence verifier — opened its own connection
    # (a quadruple-open per handler call once the tempo_map collector landed).
    conn = init_db(db_path)
    try:
        song = Q.get_song_by_name(conn, song_slug)
        song_id = song["id"] if song is not None else None
        declared_sends = _collect_declared_sends(conn, song_id) if song_id else []
        declared_envelopes = _collect_declared_envelopes(conn, song_id) if song_id else []
        declared_widths = _collect_declared_width_controls(conn, song_id) if song_id else []
        sections = _collect_sections(conn, song_id) if song_id else []
        declared_energy = _collect_declared_energy(conn, song_id) if song_id else []
        tempo_map = _collect_tempo_map(conn, song_id) if song_id else []
        stem_gains = _collect_stem_gains(conn, song_id) if song_id else {}
        master_fader_volume = (
            _collect_master_fader_volume(conn, song_id) if song_id else None
        )
    finally:
        conn.close()

    # The analysis dir doubles as the baseline pool compare_to resolves
    # against — computed before analyze_mix so the seq lookup can fail fast.
    analysis_dir = _resolve_song_dir(song_slug) / "analysis"
    # Create the dir up front so the running heartbeat can land before the
    # (potentially long) analyze_mix call (BUG3). The report write below
    # reuses it.
    analysis_dir.mkdir(parents=True, exist_ok=True)
    # WSP-3R7K: ignore this dir's contents where they are WRITTEN, so a
    # workspace created before `init-workspace` shipped its managed root block
    # (or by a bare `git init`) stops surfacing MixReports as committable.
    # Guarded like every other engine symbol here — in Live's vendored env
    # there is no hallucinote to import, and no git working copy to tidy.
    if self_ignore_dir is not None:
        self_ignore_dir(analysis_dir)

    # Heartbeat=running before analyze_mix — analyze_mix has no progress
    # callback (and the spec is not to plumb one in), so the pre/post writes
    # are the completion signal. Wrapped so a failure inside analyze_mix or the
    # report write lands a terminal status.json=error for a poller.
    _write_analysis_status(analysis_dir, {"state": "running"})
    try:
        report = analyze_mix(
            captures_path,
            declared_reverb_sends=declared_sends,
            declared_envelopes=declared_envelopes,
            declared_width_controls=declared_widths,
            sections=sections,
            declared_energy=declared_energy,
            tempo_map=tempo_map,
            # Masking is per-section evidence; enable it whenever the song declares
            # sections (the handler already gated section work on that). It is
            # neutral measurement — the holistic interpreter grades it vs intent.
            # F1 (pre-fader capture) is handled: stem_gains below reconstructs
            # mix-level before the masking pass.
            analyze_masking=bool(sections),
            # Per-part onset-vs-grid feel (push/drag/swing) — the read-side
            # counterpart to the `feel` generator. Per-section like masking; gated
            # on declared sections. Level-blind (gain doesn't move onsets), so it
            # needs no stem_gains. Neutral measurement — the interpreter grades it.
            analyze_timing=bool(sections),
            # Per-part cross-rhythm / subdivision naming (3:2, quintuplets, ...) —
            # names what grid a part is on when it fights the straight grid timing
            # measures against (the question C7 leaves open). Per-section, gated on
            # declared sections; level-blind. Composes with timing: the timing
            # pass's swing read feeds cross-rhythm's swing-deference internally.
            analyze_cross_rhythm=bool(sections),
            # Mix-level reconstruction (F1): scale each pre-fader stem by its
            # static fader gain so masking sees mix balance, not source level.
            # Fader curve is Live-12-calibrated (see audio/levels.py).
            stem_gains=stem_gains,
            # The master metrics are captured PRE master-fader (the analyzer taps
            # the master DEVICE CHAIN). Thread the master fader volume so the
            # report can surface the post-fader DELIVERED true-peak — the number
            # that answers "is the delivered output clipping?" (None → the master
            # block stays pre-fader bus only).
            master_fader_volume=master_fader_volume,
            compare_to=compare_to,
            analysis_dir=analysis_dir,
        )

        report_path = analysis_dir / f"{_utc_timestamp()}.json"
        report_dict = report.to_json_dict()
        report_path.write_text(
            # allow_nan=False is a structural backstop (ARR-7M3D B1): the report's
            # value objects guarantee None-or-finite by construction (the energy lens
            # records None for an undefined Spearman ρ, never nan), so any stray nan
            # from a future regression fails loud here instead of writing invalid
            # JSON that strict consumers (JSON.parse, the eval judge) would reject.
            json.dumps(report_dict, indent=2, allow_nan=False),
            encoding="utf-8",
        )
    except Exception as e:  # prawduct:allow prawduct/broad-except -- top-level analyze supervisor: write status.json=error then re-raise so a poller sees a terminal state for an analysis that raised (BUG3); the exception is NOT swallowed (re-raised, so the dispatcher still surfaces it)
        # Every catch logs context (project norm) before the terminal heartbeat —
        # the dispatcher surfaces the re-raised exception to the caller, but the
        # server log is where a stuck-analyze postmortem reads what actually blew up.
        logger.exception(
            "analyze: failed for song_slug=%s (analysis_dir=%s) — wrote "
            "status.json=error and re-raising", song_slug, analysis_dir,
        )
        # The message is quoted verbatim into the git-tracked analysis/ dir, and
        # the teaching errors here name the paths they're teaching about ("no
        # manifest.json at <captures_path>"). Collapse this machine's home so a
        # failed run doesn't commit it; the message otherwise stays intact —
        # the diagnosis is the point. The exception re-raised below is the
        # UNCOLLAPSED one, so the caller still gets the full path on the wire.
        _write_analysis_status(
            analysis_dir, {"state": "error", "error": portable_text(str(e))},
        )
        raise

    # Heartbeat=done — the report JSON is on disk. The robust completion signal
    # an agent polls for; carries the report path so the poller can read it
    # directly without re-globbing the analysis dir.
    #
    # status.json lives in the git-tracked analysis/ dir (only captures/ is
    # ignored), so the path it records is written the same portable way the
    # MixReport's own paths are: relative to the SONG dir (analysis_dir.parent),
    # i.e. `analysis/<ts>.json`. A poller reading status.json already knows the
    # analysis dir it read it from, so it joins from there — while an absolute
    # path would commit this machine's home directory on every analysis run.
    # The tool RETURN value below stays absolute on purpose: it is an in-flight
    # API response the agent uses to open the file, never persisted.
    _write_analysis_status(analysis_dir, {
        "state": "done",
        "report_path": portable_path(report_path, base=analysis_dir.parent),
    })

    out_of_tolerance = [
        r for r in report_dict["reverb_verifications"]
        if not r["within_tolerance"]
    ]
    summary = {
        # `master_true_peak_dbtp` is the PRE-fader mix bus (the analyzer taps the
        # master device chain). `delivered_true_peak_dbtp` is the post-fader number
        # a clipping check actually needs; both None-when-unknown values come from
        # the already-sanitized report_dict (muted master → null, not -inf).
        "master_true_peak_dbtp": report_dict["master"]["loudness"]["true_peak_dbtp"],
        "delivered_true_peak_dbtp": report_dict["delivered_true_peak_dbtp"],
        "master_fader_db": report_dict["master_fader_db"],
        "overshoot_count": len(report_dict["overshoots"]),
        "reverb_out_of_tolerance_count": len(out_of_tolerance),
        "section_count": len(report_dict["per_section"]),
        "skipped_analyses_count": len(report_dict["skipped_analyses"]),
    }
    if report_dict["compare_to"] is not None:
        diff = report_dict["compare_to"]
        summary["compare_to"] = {
            # The REPORT records this song-relative (it's a checked-in file);
            # the response re-absolutizes it, because a caller reads a returned
            # path to open the file and has no reason to know the anchor.
            # Same split as `report_path` below: portable on disk, resolved on
            # the wire.
            "baseline_ref": str(
                resolve_portable_path(analysis_dir.parent, diff["baseline"]["ref"])
            ),
            # Loudness rows + the overshoot-count change (always significant
            # when nonzero — an overshoot appearing/disappearing is the
            # headline a summary reader must not miss).
            "significant_delta_count": (
                sum(1 for d in diff["deltas"] if d["significant"])
                + (1 if diff["overshoot_count"]["significant"] else 0)
            ),
            "overshoot_delta": diff["overshoot_count"]["delta"],
            "added_surfaces": diff["added_surfaces"],
            "missing_surfaces": diff["missing_surfaces"],
        }
    return {
        "report_path": str(report_path),
        "schema_version": report_dict["schema_version"],
        "finding_count": len(report_dict["findings"]),
        "summary": summary,
        "analysis_code": _analysis_code_status(),
    }


# --- async start / status (MCP-5N8K) ---------------------------------

# A many-surface / many-section analysis runs the full DSP pipeline (per-stem
# loudness, masking, timing, cross-rhythm, reverb verification) and can exceed
# the 60s per-tool-call timeout, false-failing the synchronous `analyze` long
# after the report is actually written. `start` backgrounds the DSP on a
# detached SERVER-PROCESS thread (analyze is pure DSP — no Live, so unlike
# render's worker it needs no main-thread marshaling) and returns a job handle
# immediately; `status` long-polls the registry. The synchronous `analyze`
# stays as the one-call fast path for a quick few-surface capture — the action
# help documents when to use which. See
# .prawduct/artifacts/plans/MCP-ASYNC-RENDER-ANALYZE/api-notes.md.

ANALYZE_POLL_INSTRUCTION = (
    "Analysis running in the background. Poll ableton_analysis(action='status', "
    "job_id='{job_id}'); each status call long-polls ~45s and returns "
    "{{state}} — repeat until state is 'done' or 'failed'. One analysis at a "
    "time: don't call start again while this is running."
)


def analyze_start_handler(
    _context: LiveContext,
    *,
    song_slug: str,
    captures_dir: str | None = None,
    compare_to: int | None = None,
    _registry: JobRegistry | None = None,
    _analyze_fn: Callable[..., dict[str, Any]] | None = None,
    _spawn: Callable[[Callable[[], None]], None] | None = None,
    _resolve_report_dir: Callable[[str], Path] | None = None,
) -> dict[str, Any]:
    """Background an analysis and return its job handle immediately.

    The handle (``job_id`` + ``report_dir`` + a poll instruction) lets the agent
    poll ``status`` without holding the tool-call socket for the DSP's duration —
    a many-surface / many-section report can exceed the 60s tool-call timeout the
    synchronous ``analyze`` false-fails on. One analysis at a time: a ``start``
    while another is running returns ``{busy: True, job_id}`` rather than
    launching a second DSP pass (the pipeline is CPU-heavy; concurrent passes
    would only contend).

    ``eta_seconds`` is deliberately omitted (None): analyze runtime depends on
    surface count × audio length × which per-section passes the song's declared
    sections enable, with no realtime anchor like render's beats/tempo — any
    single number would be a guess, so we report none rather than a misleading
    one. Input errors (typo'd slug, no captures dir) surface via ``status`` as
    ``state='failed'`` with the teaching error, the same path as a DSP failure —
    ``start`` validates only what it needs to mint the handle (mirrors
    render_start, whose render-time failures also surface through ``status``).
    """
    if not _HAS_HALLUCINOTE:  # pragma: no cover - exercised in Live's vendored env
        raise _AnalysisError(
            "ableton_analysis requires the hallucinote package — this handler "
            "must run server-side, not from Live's Remote Script vendored env "
            "(which doesn't ship hallucinote). Check the action's "
            "runs_server_side flag."
        )
    registry = _registry if _registry is not None else default_registry()
    analyze_fn = _analyze_fn if _analyze_fn is not None else analyze_handler
    spawn = _spawn if _spawn is not None else (
        lambda worker: spawn_daemon(worker, name="hallucinote-analyze-worker")
    )
    resolve_report_dir = (
        _resolve_report_dir
        if _resolve_report_dir is not None
        else (lambda slug: _resolve_song_dir(slug) / "analysis")
    )

    # One analysis at a time — atomically claim the slot. The async dispatch
    # wrapper (server.py) lets two starts run on different threads, so the claim
    # must be atomic; create_if_idle closes the check-then-create TOCTOU. A
    # start while one runs returns a busy handle pointing at the live job.
    report_dir = resolve_report_dir(song_slug)
    job, created = registry.create_if_idle(kind="analyze", dir=str(report_dir))
    if not created:
        return {
            "busy": True,
            "job_id": job.job_id,
            "state": job.state,
            "report_dir": job.dir,
            "message": (
                "An analysis is already running (one at a time). Poll it with "
                f"ableton_analysis(action='status', job_id='{job.job_id}'), "
                "or wait for it to finish before starting another."
            ),
        }
    # Analyze has no fine-grained progress — analyze_mix is one blocking call
    # with no progress callback (the spec is not to plumb one in) — so progress
    # stays a coarse stage marker, the shape the api-notes job record reserves
    # for analyze (``progress: {stage, ...} (coarse)``).
    registry.update_progress(job.job_id, {"stage": "analyzing"})

    def _worker() -> None:
        try:
            result = analyze_fn(
                None,  # type: ignore[arg-type]  # no LiveContext server-side by design
                song_slug=song_slug,
                captures_dir=captures_dir,
                compare_to=compare_to,
            )
            # Map analyze_handler's return into the locked-in {report,
            # report_path} status shape (api-notes): ``report`` is the same
            # lightweight bundle the synchronous ``analyze`` returns (summary +
            # finding_count + schema_version + analysis_code); the full per-stem
            # MixReport JSON stays on disk at ``report_path`` (the convenient
            # accessor, symmetric with render's manifest_path).
            registry.mark_done(job.job_id, {
                "report": result,
                "report_path": result.get("report_path"),
            })
        except Exception as e:  # prawduct:allow prawduct/broad-except -- detached analyze worker: any failure must land as job state=failed (else status long-polls forever); analyze_handler already logged + wrote status.json=error before re-raising — the worker's job is only to record the terminal state
            logger.exception(
                "analyze worker failed for job %s (song_slug=%s)",
                job.job_id, song_slug,
            )
            registry.mark_failed(job.job_id, str(e))

    spawn(_worker)
    return job.start_result(ANALYZE_POLL_INSTRUCTION.format(job_id=job.job_id))


def analyze_status_handler(
    _context: LiveContext,
    *,
    job_id: str,
    _registry: JobRegistry | None = None,
    _long_poll_s: float = DEFAULT_STATUS_LONG_POLL_S,
) -> dict[str, Any]:
    """Long-poll an analyze job: wait up to ``_long_poll_s`` for it to finish,
    then return its current state + progress (and report/error if terminal).

    Returns ``state='running'`` if still in flight after the wait — the agent
    simply calls again. Reads in-process job state only (no Live, no disk
    re-glob), so ``_context`` is unused but kept for the uniform handler
    signature. An unknown ``job_id`` raises a teaching ``_AnalysisError`` naming
    recent analyze jobs (job state lives in the server process — it resets when
    the MCP server restarts)."""
    registry = _registry if _registry is not None else default_registry()
    job = registry.get(job_id)
    if job is None:
        recent = registry.recent_ids(kind="analyze")
        hint = (
            f"recent analyze jobs: {', '.join(recent)}"
            if recent
            else "no analyze jobs have been started in this server process"
        )
        raise _AnalysisError(
            f"analyze status: unknown job_id {job_id!r} ({hint})"
        )
    job.wait_terminal(_long_poll_s)
    return job.status_result()


def get_latest_report_handler(
    _context: LiveContext,
    *,
    song_slug: str,
) -> dict[str, Any]:
    """Return the most recent MixReport JSON for ``song_slug``.

    Returns: ``{report_path, report, analysis_code}`` where ``report`` is
    the parsed JSON dict and ``analysis_code`` is the loaded-vs-disk version
    probe (see ``_analysis_code_status``). Raises ``_AnalysisError`` if the
    song has no analyses on disk yet.
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
            f"{_resolve_song_dir(song_slug) / 'analysis'} — has "
            f"ableton_analysis(action='analyze') been called yet for "
            f"this song?"
        )
    return {
        "report_path": str(report_path),
        "report": json.loads(report_path.read_text(encoding="utf-8")),
        "analysis_code": _analysis_code_status(),
    }


def _extract_song_structure(conn: "sqlite3.Connection", song_id: str) -> dict[str, Any]:
    """Assemble a raw structural dump of a song from the DB.

    This is the score-as-data tier the audio/compose analyzers can't see:
    exact note timings, section boundaries, device chains + parameters,
    arrangement placements, sends, returns, cues, tempo/meter maps. The
    musical-work eval judge reads phase relationships and structural facts
    straight from this dump (its ``--db-extract`` input) rather than
    hand-querying the sqlite DB.

    Uses the read-side ``queries`` helpers exclusively — no raw SQL — so
    the dump tracks the canonical projections (note tags deserialized,
    sends joined to return identity, devices joined to chain position).
    Every ``sqlite3.Row`` is materialized to a plain dict so the result is
    JSON-serializable; ``get_notes_for_clip`` already returns dicts.

    Device caveat: ``get_devices_for_track`` / ``get_devices_for_return``
    walk only the top-level chain — nested rack chains (one level deep via
    ``get_device_chains_for_rack_device``, recursive racks not modeled at
    all) are not flattened in. A song using Instrument/Audio-Effect Racks
    therefore reports its rack containers but not the devices inside them.
    Acceptable for the eval-judge tier (which reasons about structure /
    phase, not exhaustive device trees) until nested-rack pull lands.
    """
    song_row = Q.get_song(conn, song_id)
    song = dict(song_row) if song_row is not None else {"id": song_id}

    tracks: list[dict[str, Any]] = []
    for track in Q.get_tracks_for_song(conn, song_id):
        track_id = track["id"]
        clips: list[dict[str, Any]] = []
        for clip in Q.get_clips_for_track(conn, track_id):
            clip_d = dict(clip)
            # get_notes_for_clip already returns dicts (tags deserialized).
            clip_d["notes"] = Q.get_notes_for_clip(conn, clip["id"])
            clips.append(clip_d)
        devices: list[dict[str, Any]] = []
        for device in Q.get_devices_for_track(conn, track_id):
            device_d = dict(device)
            device_d["parameters"] = [
                dict(p) for p in Q.get_device_parameters(conn, device["id"])
            ]
            devices.append(device_d)
        track_d = dict(track)
        track_d["clips"] = clips
        track_d["arrangement_clips"] = [
            dict(a) for a in Q.get_arrangement_for_track(conn, track_id)
        ]
        track_d["devices"] = devices
        track_d["sends"] = [dict(s) for s in Q.get_sends_for_track(conn, track_id)]
        tracks.append(track_d)

    returns: list[dict[str, Any]] = []
    for ret in Q.get_returns_for_song(conn, song_id):
        ret_d = dict(ret)
        ret_devices: list[dict[str, Any]] = []
        for device in Q.get_devices_for_return(conn, ret["id"]):
            device_d = dict(device)
            device_d["parameters"] = [
                dict(p) for p in Q.get_device_parameters(conn, device["id"])
            ]
            ret_devices.append(device_d)
        ret_d["devices"] = ret_devices
        returns.append(ret_d)

    return {
        "song": song,
        "tempo_map": [dict(r) for r in Q.get_tempo_map(conn, song_id)],
        "time_signature_map": [
            dict(r) for r in Q.get_time_signature_map(conn, song_id)
        ],
        "sections": [dict(r) for r in Q.get_sections_for_song(conn, song_id)],
        "cue_points": [dict(r) for r in Q.get_cue_points(conn, song_id)],
        "tracks": tracks,
        "returns": returns,
    }


def extract_structure_handler(
    _context: LiveContext,
    *,
    song_slug: str,
) -> dict[str, Any]:
    """Return a raw structural dump of a song's DB.

    The score-as-data tier the analyzers can't reach: tracks, clips, notes
    (exact timings), sections, device chains + parameters, arrangement
    placements, sends, returns, cues, tempo/meter maps — keyed under one
    tool call so the musical-work eval judge consumes it via ``--db-extract``
    instead of a bespoke sqlite query.

    Returns: ``{song_slug, extract}`` where ``extract`` is the nested dump.
    Raises ``_AnalysisError`` on a typo'd / unbuilt slug (same teaching
    error shape as ``analyze``).
    """
    if not _HAS_HALLUCINOTE:  # pragma: no cover - exercised in Live's vendored env
        raise _AnalysisError(
            "ableton_analysis requires the hallucinote package — "
            "see analyze_handler for the same diagnosis."
        )
    db_path = _existing_db_path(song_slug)  # fail loud on a typo'd slug
    conn = init_db(db_path)
    try:
        song = Q.get_song_by_name(conn, song_slug)
        if song is None:
            raise _AnalysisError(
                f"no song row named {song_slug!r} in {db_path} — the DB "
                f"exists but has no matching song. `python3 "
                f"{db_path.parent / 'build.py'} --reset` populates it."
            )
        extract = _extract_song_structure(conn, song["id"])
    finally:
        conn.close()
    return {"song_slug": song_slug, "extract": extract}


__all__ = [
    "analyze_handler",
    "analyze_start_handler",
    "analyze_status_handler",
    "get_latest_report_handler",
    "extract_structure_handler",
]
