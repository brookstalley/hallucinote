"""Scoped note push — materialize only targeted / content-changed clips to Live.

Single-model bulk authoring (build-plan B1). Notes are authored as code in a
song's ``build.py``, materialized to the DB through mutators, and pushed to Live
by this module **without the notes ever entering the agent's context** — the
agent runs one command; the bytes flow DB → TCP → Live (the "code execution with
MCP" pattern). This is the incremental compose loop's materialize step: push one
clip (or only the clips whose note content changed) instead of the gated
thirteen-phase :func:`push_execute.execute_push`.

Why a separate path, not a flag on ``execute``: ``execute`` runs all thirteen phases
behind a coherence gate and writes ``.last-push-state.json``. The compose loop
wants a cheap, repeatable "re-materialize these clips" step with its own
content-change tracking — conflating the two schemas/contracts would muddy both.

**Change detection is content-based, not event-watermark based.** A whole-DB
rebuild re-emits ``CLIP_NOTES_REPLACED`` for every clip even when content is
identical, so an event watermark would over-push. Instead each clip carries a
fingerprint — a hash of the **MCP wire shape** (exactly what gets sent to Live).
Move, delete, and total-replace all change the fingerprint; a rebuilt-identical
clip (or a DB change that doesn't alter the wire shape, e.g. tags-only) is
skipped. Fingerprints are recorded in ``.last-notes-push.json`` and compared on
the next ``changed_only`` run.

The summary returned to the caller carries **note counts, never note arrays**
(reference-style result, per MCP large-payload guidance).
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..db import queries as Q
from . import push

logger = logging.getLogger(__name__)

# Lives next to the DB (or an explicit --state-dir), beside .last-push-state.json
# but with a distinct name so the full-push and notes-push schemas never collide.
NOTES_PUSH_STATE = ".last-notes-push.json"


def clip_fingerprint(notes: list[dict[str, Any]]) -> str:
    """Content hash of what this clip would materialize to Live.

    Fingerprints the **MCP wire shape** (:func:`push._notes_for_mcp`), so the
    fingerprint answers exactly "does Live need updating?": a DB change that
    doesn't alter the wire shape (tags-only) won't force a push, and a move /
    delete / total-replace will. Sorted on the full note tuple so a
    reordered-but-identical set hashes the same.
    """
    wire = push._notes_for_mcp(notes)
    tuples = sorted(
        (n["pitch"], n["start_time"], n["duration"], n["velocity"], n["mute"])
        for n in wire
    )
    blob = json.dumps(tuples, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class ScopedPushResult:
    """Outcome of a scoped note push. Counts only — never note arrays."""

    pushed: list[dict[str, Any]] = field(default_factory=list)   # {clip_id, name, note_count}
    skipped: list[dict[str, Any]] = field(default_factory=list)  # {clip_id, name, reason}
    errors: list[dict[str, Any]] = field(default_factory=list)   # {clip_id, name, error}
    connection_lost: bool = False

    def to_summary(self) -> dict[str, Any]:
        return {
            "pushed": self.pushed,
            "skipped": self.skipped,
            "errors": self.errors,
            "connection_lost": self.connection_lost,
            "counts": {
                "pushed": len(self.pushed),
                "skipped": len(self.skipped),
                "errors": len(self.errors),
            },
        }


def format_summary(result: "ScopedPushResult") -> str:
    """One-page stdout summary for the CLI — counts + a JSON block, never notes."""
    c = result.to_summary()["counts"]
    head = (
        f"scoped notes push: {c['pushed']} pushed, {c['skipped']} skipped, "
        f"{c['errors']} error(s)"
        + (" — CONNECTION LOST" if result.connection_lost else "")
        + "\n"
    )
    return head + json.dumps(result.to_summary(), indent=2) + "\n"


def _load_fingerprints(state_path: Path) -> dict[str, str]:
    """Last-pushed fingerprints, or {} if absent/unreadable.

    A missing or corrupt state file is treated as "nothing pushed yet" — the
    safe direction (``changed_only`` then pushes everything; ``set_notes`` is
    idempotent). Corruption is logged, not swallowed.
    """
    if not state_path.exists():
        return {}
    try:
        data = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "notes-push state %s unreadable (%s); treating as empty",
            state_path, exc,
        )
        return {}
    fps = data.get("fingerprints")
    return fps if isinstance(fps, dict) else {}


def _resolve_candidates(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    clip_ids: list[str] | None,
    result: ScopedPushResult,
) -> list[sqlite3.Row]:
    """Explicit clip_ids (in order), else every clip on the song.

    An explicit clip_id that doesn't exist is surfaced as an error rather than
    silently dropped — the caller named it on purpose.
    """
    if clip_ids:
        rows: list[sqlite3.Row] = []
        for cid in clip_ids:
            row = Q.get_clip(conn, cid)
            if row is None:
                result.errors.append(
                    {"clip_id": cid, "name": None, "error": f"clip {cid} not found"}
                )
            else:
                rows.append(row)
        return rows
    return list(Q.get_clips_for_song(conn, song_id))


def push_notes(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    state_dir: Path,
    clip_ids: list[str] | None = None,
    changed_only: bool = False,
    send_fn: Callable[..., Any] | None = None,
    actor: str = "sync",
    reason: str | None = None,
) -> ScopedPushResult:
    """Materialize the targeted clips' notes to Live; record fingerprints.

    Scope: ``clip_ids`` (explicit) else the whole song. With ``changed_only``,
    a clip whose fingerprint matches the last push is skipped. Each in-scope
    clip is planned via :func:`push.plan_push_clip` (which chooses create vs
    replace_notes) and dispatched via ``send_fn`` (defaults to the MCP TCP
    client). Successful pushes update ``.last-notes-push.json``.

    Aborts on a connection-class failure (Live unreachable) — there's no point
    continuing — and records every successfully-pushed clip's fingerprint up to
    that point so a re-run skips them.
    """
    if send_fn is None:
        from hallucinote_mcp import client as _client  # type: ignore[import-not-found]
        send_fn = _client.send
    from hallucinote_mcp.wire import Request  # type: ignore[import-not-found]
    try:
        from hallucinote_mcp.client import (  # type: ignore[import-not-found]
            LiveConnectionError as _LiveConnectionError,
        )
        _CONNECTION_EXCS: tuple[type[BaseException], ...] = (_LiveConnectionError, OSError)
    except ImportError:
        _CONNECTION_EXCS = (OSError,)

    state_path = state_dir / NOTES_PUSH_STATE
    prior_fps = _load_fingerprints(state_path)
    new_fps = dict(prior_fps)

    result = ScopedPushResult()
    candidates = _resolve_candidates(
        conn, song_id=song_id, clip_ids=clip_ids, result=result,
    )

    for row in candidates:
        cid = row["id"]
        name = row["name"]
        if row["kind"] == "audio":
            # CLP-AUD1: audio clips host no notes and have no push path
            # until CLP-AUD2. Without this skip, plan_push_clip's
            # refuse-loudly path (a warn, zero calls) would fall through
            # the empty-calls loop and misreport the clip as pushed.
            result.skipped.append({
                "clip_id": cid, "name": name,
                "reason": "kind='audio': audio-clip push is CLP-AUD2 "
                          "scope — the row is authored but not synced",
            })
            continue
        notes = Q.get_notes_for_clip(conn, cid)
        fp = clip_fingerprint(notes)

        if changed_only and prior_fps.get(cid) == fp:
            result.skipped.append({"clip_id": cid, "name": name, "reason": "unchanged"})
            continue

        try:
            plan = push.plan_push_clip(conn, clip_id=cid, session_id=session_id)
        except ValueError as exc:
            # e.g. the clip's track isn't linked yet — run a full push first.
            result.errors.append({"clip_id": cid, "name": name, "error": str(exc)})
            continue

        results_payload: list[dict[str, Any]] = []
        clip_ok = True
        for call in plan.calls:
            action = call.args.get("action")
            params = {k: v for k, v in call.args.items() if k != "action"}
            req = Request(tool=call.tool, action=action or "", params=params)
            try:
                resp = send_fn(req)
            except _CONNECTION_EXCS as exc:
                result.errors.append(
                    {"clip_id": cid, "name": name,
                     "error": f"{type(exc).__name__}: {exc}"}
                )
                result.connection_lost = True
                clip_ok = False
                break

            ok = bool(getattr(resp, "ok", False))
            results_payload.append({
                "key": call.key,
                "tool": call.tool,
                "ok": ok,
                "result": getattr(resp, "result", None) if ok else None,
                "error": getattr(resp, "error", None) if not ok else None,
            })
            if not ok:
                clip_ok = False
                result.errors.append(
                    {"clip_id": cid, "name": name,
                     "error": getattr(resp, "error", None)}
                )

        # Record any successful create-links (replace_notes records nothing).
        if results_payload:
            apply_warnings = push.apply_push_results(
                conn, results_payload, session_id=session_id,
                actor=actor, reason=reason or f"scoped notes push clip={cid}",
            )
            # Notes pushes emit no perform_batch: keys, so this is empty today
            # — surfaced anyway so a future key kind can't be silently eaten.
            for w in apply_warnings:
                result.errors.append({"clip_id": cid, "name": name, "error": w})

        if clip_ok:
            new_fps[cid] = fp
            result.pushed.append({"clip_id": cid, "name": name, "note_count": len(notes)})

        if result.connection_lost:
            break

    # Persist fingerprints (best-effort, even after a connection abort, so a
    # re-run skips the clips that did land).
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {"song_id": song_id, "session_id": session_id, "fingerprints": new_fps},
            indent=2,
        )
        + "\n"
    )
    return result
