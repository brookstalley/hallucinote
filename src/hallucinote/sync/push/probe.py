"""Probe-and-link + default-scaffold cleanup + clip prune + coherence check.

These planners operate against a freshly-probed Live snapshot rather than
emitting forward MCP calls: they bind existing Live tracks/returns/devices
to DB rows (``probe_and_link``), identify Live-side defaults safe to delete
(``plan_cleanup_default_scaffold``), find orphan Live clips
(``plan_clip_prune``), and validate session/link consistency before execute
(``check_coherence``).
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field, asdict
from typing import Any

from hallucinote.return_naming import normalize_live_return_name
from hallucinote.analyzer_identity import is_analyzer_device
from hallucinote.analyzer_staleness import detect_stale_analyzer_surfaces
from hallucinote.db import mutations as M, queries as Q

from ._core import _position_bar_to_beats


# ---------------------------------------------------------------------------
# Probe-and-link: bind existing Live tracks/returns to DB rows by name
# ---------------------------------------------------------------------------


# W18-D: Live 12.x's brand-new-set scaffold ships these track names. Detection
# of the "first push onto a fresh default set" case keys off this exact set —
# any drift (rename, locale change, user customization) means the tracks are
# no longer recognisable defaults and we fall back to the standard "continue
# alongside?" confirmation.
CANONICAL_DEFAULT_SCAFFOLD_TRACK_NAMES: frozenset[str] = frozenset({
    "1-MIDI", "2-MIDI", "3-Audio", "4-Audio",
})

# Returns in Live's brand-new-set ship under these prefixed names. The
# probe-and-link returns matcher strips the ``[A-Z]-`` slot prefix and
# matches against the DB's stripped form (W4-C); cleanup keys off the
# raw Live names because cleanup is about deleting Live-side defaults
# the song hasn't claimed, not matching by stripped name.
CANONICAL_DEFAULT_SCAFFOLD_RETURN_NAMES: frozenset[str] = frozenset({
    "A-Reverb", "B-Delay",
})


# ---------------------------------------------------------------------------
# Default-scaffold cleanup (R-1.2)
# ---------------------------------------------------------------------------


@dataclass
class CleanupScaffoldPlan:
    """Outcome of :func:`plan_cleanup_default_scaffold`.

    ``deletable_tracks`` / ``deletable_returns`` are sorted in DESCENDING
    index order so a caller iterating the lists and dispatching deletes
    naturally shifts later indices last (Live's track/return list is
    1-based and shifts down on each delete). ``refusals`` is a list of
    ``{"kind": "non_canonical"|"would_empty"|..., "detail": str}``
    entries — a non-empty list means the cleanup MUST NOT proceed.
    """

    deletable_tracks: list[dict[str, Any]] = field(default_factory=list)
    deletable_returns: list[dict[str, Any]] = field(default_factory=list)
    refusals: list[dict[str, str]] = field(default_factory=list)

    @property
    def can_proceed(self) -> bool:
        return not self.refusals

    def to_dict(self) -> dict[str, Any]:
        return {
            "deletable_tracks": self.deletable_tracks,
            "deletable_returns": self.deletable_returns,
            "refusals": self.refusals,
            "can_proceed": self.can_proceed,
        }


def plan_cleanup_default_scaffold(
    *,
    unmatched_live_tracks: list[dict[str, Any]],
    unmatched_live_returns: list[dict[str, Any]],
    total_live_track_count: int,
    matched_track_count: int,
) -> CleanupScaffoldPlan:
    """Identify canonical-default tracks/returns safe to delete.

    Refuse-and-teach when:

    * Any unmatched-Live track is NOT a canonical default. The user
      must hand-resolve "another song's tracks" before cleanup runs.
    * Deleting every deletable track would leave Live with zero tracks
      (Live rejects deletion of the last surviving track). Push the
      song's tracks first, then cleanup, OR keep one default for the
      song's eventual content to replace.

    Symmetric logic for returns. Returns can drop to zero (Live permits
    zero returns).

    Outputs deletable lists in DESCENDING index order so the caller's
    naive forward iteration produces safe descending deletes.

    Pure: no MCP calls, no DB writes. The CLI orchestrates the side
    effects.
    """
    plan = CleanupScaffoldPlan()

    # Track classification.
    non_canonical_tracks = [
        t for t in unmatched_live_tracks
        if t["name"] not in CANONICAL_DEFAULT_SCAFFOLD_TRACK_NAMES
    ]
    if non_canonical_tracks:
        names = sorted({t["name"] for t in non_canonical_tracks})
        plan.refusals.append({
            "kind": "non_canonical_tracks",
            "detail": (
                f"{len(non_canonical_tracks)} unmatched Live track(s) are not "
                f"canonical defaults: {names}. Cleanup only deletes Live's "
                f"brand-new-set scaffold ({sorted(CANONICAL_DEFAULT_SCAFFOLD_TRACK_NAMES)}). "
                "Rename or hand-delete the non-canonical tracks first."
            ),
        })

    canonical_track_candidates = [
        t for t in unmatched_live_tracks
        if t["name"] in CANONICAL_DEFAULT_SCAFFOLD_TRACK_NAMES
    ]
    # "Would empty Live" guard: if we'd delete every track in Live (no
    # song tracks linked yet either), Live refuses the last delete.
    # Total tracks after cleanup = total_live - len(canonical_track_candidates)
    # — and if that's 0, refuse.
    if (
        canonical_track_candidates
        and total_live_track_count - len(canonical_track_candidates) <= 0
    ):
        plan.refusals.append({
            "kind": "would_empty_live_tracks",
            "detail": (
                f"Cleanup would delete all {len(canonical_track_candidates)} "
                f"Live track(s), but Live requires at least one. Push the "
                f"song's tracks first (so they're alongside the defaults), "
                f"then re-run cleanup; OR keep one default and let push "
                f"absorb it as a song track."
            ),
        })

    # Return classification — no minimum-count constraint (returns can
    # drop to zero in Live), so the refusal here is only non_canonical.
    non_canonical_returns = [
        r for r in unmatched_live_returns
        if r["name"] not in CANONICAL_DEFAULT_SCAFFOLD_RETURN_NAMES
    ]
    if non_canonical_returns:
        names = sorted({r["name"] for r in non_canonical_returns})
        plan.refusals.append({
            "kind": "non_canonical_returns",
            "detail": (
                f"{len(non_canonical_returns)} unmatched Live return(s) are "
                f"not canonical defaults: {names}. Cleanup only deletes "
                f"{sorted(CANONICAL_DEFAULT_SCAFFOLD_RETURN_NAMES)}. Rename or "
                "hand-delete the non-canonical returns first."
            ),
        })

    canonical_return_candidates = [
        r for r in unmatched_live_returns
        if r["name"] in CANONICAL_DEFAULT_SCAFFOLD_RETURN_NAMES
    ]

    # Build the deletable lists in descending index order so naive
    # forward iteration over them produces the right delete sequence.
    plan.deletable_tracks = sorted(
        canonical_track_candidates,
        key=lambda t: -int(t["track_index"]),
    )
    plan.deletable_returns = sorted(
        canonical_return_candidates,
        key=lambda r: -int(r["return_index"]),
    )

    # If there's nothing to do AND no refusals, surface that as a refusal
    # so the CLI doesn't silently "succeed" against a non-default Live set.
    if not plan.deletable_tracks and not plan.deletable_returns and not plan.refusals:
        plan.refusals.append({
            "kind": "nothing_to_do",
            "detail": (
                "No canonical-default tracks or returns to clean up. Live "
                "either has no unmatched defaults, or this isn't a "
                "brand-new-set scaffold scenario. (matched_track_count="
                f"{matched_track_count})"
            ),
        })

    return plan


@dataclass
class ClipPruneTarget:
    """One Live session clip slated for deletion (orphan: in Live, not in DB)."""

    track_index: int
    track_name: str
    clip_index: int  # Live session slot (1-based)
    name: str        # Live clip's display name


@dataclass
class ClipPrunePlan:
    """Outcome of :func:`plan_clip_prune` — opt-in structural deletion (B1b).

    ``prunable`` lists Live session clips whose slot has no matching DB clip on
    the linked track (the author removed/relocated the part; the Live clip
    lingers). ``refusals`` lists tracks deliberately NOT clip-pruned, with a
    teaching reason — currently the "whole-track orphan" case (a Live track with
    populated clips that no DB track is linked to), which is a track-level
    concern handled by ``cleanup-default-scaffold`` or explicit removal, never
    by clip-prune silently gutting a track the DB doesn't manage.
    """

    prunable: list[ClipPruneTarget] = field(default_factory=list)
    refusals: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prunable": [asdict(t) for t in self.prunable],
            "refusals": self.refusals,
        }


def plan_clip_prune(tracks: list[dict[str, Any]]) -> ClipPrunePlan:
    """Identify Live session clips to prune — orphans relative to the DB.

    Each ``tracks`` entry: ``{track_index, track_name, db_slots, live_clips}``
    where ``db_slots`` is the set of DB clip ``slot`` values for the DB track
    linked to this Live track (or ``None`` if no DB track is linked), and
    ``live_clips`` is the list of POPULATED Live session clips
    (``{clip_index, name}``) — the caller drops empty slots before calling.

    A populated Live slot whose ``clip_index`` is not in ``db_slots`` is an
    orphan: prunable. A DB-backed slot is NEVER pruned (the core safety
    property — clip-prune can't delete something the DB still wants). A Live
    track with no linked DB track is refused (track-level concern).

    Pure: no MCP calls, no DB writes. The CLI orchestrates probe + dispatch and
    defaults to dry-run.
    """
    plan = ClipPrunePlan()
    for t in tracks:
        live_clips = t["live_clips"]
        db_slots = t["db_slots"]
        if db_slots is None:
            if live_clips:
                plan.refusals.append({
                    "kind": "no_db_track_linked",
                    "track_index": t["track_index"],
                    "track_name": t["track_name"],
                    "detail": (
                        f"Live track {t['track_index']} ({t['track_name']!r}) has "
                        f"{len(live_clips)} clip(s) but no DB track is linked to it — "
                        "every clip would be an orphan. This is a track-level prune; "
                        "remove the track explicitly or via cleanup-default-scaffold, "
                        "not clip-prune."
                    ),
                })
            continue
        for c in live_clips:
            if c["clip_index"] not in db_slots:
                plan.prunable.append(ClipPruneTarget(
                    track_index=t["track_index"],
                    track_name=t["track_name"],
                    clip_index=c["clip_index"],
                    name=c.get("name", ""),
                ))
    return plan


@dataclass
class ProbeAndLinkResult:
    """Outcome of :func:`probe_and_link`. The skill displays the
    matched / unmatched lists so the user can spot rename drift
    (e.g. DB has 'Drums', Live has 'Drum Kit').

    W18-B added ``unlinked_stale_tracks`` / ``unlinked_stale_returns``: links
    whose ``ableton_index`` no longer matches a Live entity in the fresh
    probe and were deleted by strict reconciliation. The skill surfaces the
    counts so the user sees that probe-and-link recovered from a deleted-
    Live-track drift instead of silently leaving stale rows.

    SYN-3C8K added ``unlinked_stale_clips``: ``clip`` links whose parent
    track is no longer linked in this session (its track link was dropped as
    stale, or never existed) and were cascade-deleted by reconciliation. The
    W18-B sweep originally skipped nested kinds on the assumption they
    cascade-invalidate from parent-track *deletion* — but a Live-set swap that
    reuses the session drops the parent *track link* without deleting the clip
    link, leaving it dangling. A dangling clip link makes the clips planner
    downgrade ``create`` to ``replace_notes`` against an empty slot, halting
    the clips phase. Cascading the clip-link drop restores the
    "links describe Live truth" invariant the clips planner relies on.

    W18-D added ``default_scaffold_unmatched_tracks``: present (non-empty)
    when every entry in ``unmatched_live_tracks`` matches a canonical Live
    default name. The skill keys its "delete defaults after push?" prompt off
    this field, not off ``unmatched_live_tracks`` directly — that way an
    unrelated set with the same names doesn't trigger destructive cleanup.
    (SYN-3C8K dropped the original ``auto_session_created=True`` gate: a
    *reused* session pushed onto a fresh default set has the same canonical
    scaffold to clean up, and the canonical-name signature is the real
    discriminator, not whether the session was freshly minted.)

    W20-A added ``matched_devices``: per-device bindings created when
    ``live_devices_by_parent`` is supplied. Matching by ``(parent track or
    return, position, class_name)`` closes the punk-fate re-push drift
    where Live's default ``A-Reverb``'s built-in Reverb matched a DB
    device but wasn't yet linked, causing ``_emit_device_calls`` to load
    a duplicate Reverb on each subsequent push.

    SYN-4R7P added ``unlinked_stale_arrangement_clips`` / ``rebound_arrangement_clips``:
    ``arrangement_clip`` links reconciled against Live truth when
    ``live_arrangement_clips_by_track`` is supplied (the ``--probe`` path).
    A Live arrangement clip has no stable id and Live re-numbers
    ``arrangement_clip_index`` on any delete, so position is its identity
    key. A link whose live placement is gone is dropped (so the next push
    re-duplicates it instead of crashing on a ``replace_notes`` REFRESH at a
    dead index); a link whose live placement merely renumbered is re-bound to
    the current index. This is the arrangement-side sibling of the SYN-3C8K
    clip cascade — without it ``--only arrangement --probe`` raised
    ``IndexError: clip_index out of range`` after the user deleted arrangement
    clips in Live.
    """
    matched_tracks: list[dict[str, Any]] = field(default_factory=list)
    matched_returns: list[dict[str, Any]] = field(default_factory=list)
    matched_devices: list[dict[str, Any]] = field(default_factory=list)
    unmatched_db_tracks: list[dict[str, Any]] = field(default_factory=list)
    unmatched_db_returns: list[dict[str, Any]] = field(default_factory=list)
    unmatched_live_tracks: list[dict[str, Any]] = field(default_factory=list)
    unmatched_live_returns: list[dict[str, Any]] = field(default_factory=list)
    unlinked_stale_tracks: list[dict[str, Any]] = field(default_factory=list)
    unlinked_stale_returns: list[dict[str, Any]] = field(default_factory=list)
    unlinked_stale_clips: list[dict[str, Any]] = field(default_factory=list)
    unlinked_stale_arrangement_clips: list[dict[str, Any]] = field(default_factory=list)
    rebound_arrangement_clips: list[dict[str, Any]] = field(default_factory=list)
    default_scaffold_unmatched_tracks: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def probe_and_link(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    live_tracks: list[dict[str, Any]],
    live_returns: list[dict[str, Any]],
    live_devices_by_parent: dict[tuple[str, int], list[dict[str, Any]]] | None = None,
    live_arrangement_clips_by_track: dict[int, list[dict[str, Any]]] | None = None,
    actor: str = "sync",
    reason: str | None = None,
) -> ProbeAndLinkResult:
    """Match Live tracks/returns by name against DB rows; write the
    matches as ``ableton_links`` so subsequent phases skip the
    create call.

    This is the W3-G work that was deferred from Wave 3 — running it
    before the master orchestrator lets the agent push against a
    Live set that already contains some of the song's tracks/returns
    (typical when the user opened a half-built set or is iterating
    against a saved template). Unmatched DB entities still get
    created in phases 3 / 4; unmatched Live entities are NOT
    deleted — push is additive, not destructive.

    Track matching: case-sensitive name equality. Master tracks (DB
    ``kind='master'``) are skipped — Live's track list never
    contains master, and master mixer state is reached via
    ``ableton_session`` rather than a track index.

    Return matching: the live-side name is stripped of Live's
    automatic slot-letter prefix (W4-C) before comparison. So DB
    'Reverb' matches Live 'A-Reverb' (and is linked to return_index
    1, the index Live exposes for slot A).

    Duplicate names on either side warn loudly and link the FIRST
    match; the agent should rename to disambiguate. Returns kind
    drift between DB and Live as a note (informational — kind isn't
    enforced at link time).

    Re-runnable: calling ``probe_and_link`` a second time on the same
    inputs is a no-op for the link upserts (link_db_to_ableton is
    upsert-by-(session, db_kind, db_id)) and a no-op for the strict
    reconciliation (no stale links to delete the second time).

    **W18-B: strict link reconciliation.** After the name-matching pass,
    any ``ableton_links`` row whose ``ableton_index`` no longer appears in
    the fresh probe is deleted (track + return kinds). ``clip`` links cascade
    off their parent track (SYN-3C8K): a clip link whose parent track is no
    longer linked is dropped, because a Live-set swap that reuses the session
    drops the parent track link without deleting the clip link, and a dangling
    clip link makes the clips planner emit ``replace_notes`` against an empty
    slot. This closes the punk-fate drift bug (deleted Live track → stale link →
    clip creates against the wrong track) and the swell set-swap halt (dangling
    clip links → clips phase IndexError).

    **SYN-4R7P: arrangement-clip reconciliation.** When
    ``live_arrangement_clips_by_track`` is supplied (the ``--probe`` path),
    ``arrangement_clip`` links are reconciled against Live truth by POSITION
    (Live re-numbers ``arrangement_clip_index`` on any delete, so the index is
    not a stable handle — same identity rule as the pull-side diff). A link
    whose live placement is gone is dropped so the next push re-duplicates it;
    a renumbered placement is re-bound to its new index. Without this,
    ``--only arrangement --probe`` raised ``IndexError`` after the user deleted
    arrangement clips in Live (the link survived, so the planner took the
    ``replace_notes`` REFRESH branch at a dead index). The remaining nested
    kinds (device / envelope / note) are still re-established by the next push's
    create-call path.

    **W18-D: default-scaffold detection.** When every entry in
    ``unmatched_live_tracks`` matches a canonical Live-default name
    (``1-MIDI`` / ``2-MIDI`` / ``3-Audio`` / ``4-Audio``), the unmatched
    list is also surfaced as ``default_scaffold_unmatched_tracks`` so the
    skill can offer "delete defaults after push?" as the prompt default
    instead of the generic "continue alongside?" gate. (SYN-3C8K removed the
    earlier ``auto_session_created=True`` precondition — a reused session
    pushed onto a fresh default set has the same scaffold to clean up.)
    """
    result = ProbeAndLinkResult()

    db_tracks = [t for t in Q.get_tracks_for_song(conn, song_id) if t["kind"] != "master"]
    db_returns = list(Q.get_returns_for_song(conn, song_id))

    # ---- Tracks: name-equality match.
    live_track_by_name: dict[str, list[dict[str, Any]]] = {}
    for lt in live_tracks:
        live_track_by_name.setdefault(lt["name"], []).append(lt)
    consumed_live_track_indexes: set[int] = set()
    for dt in db_tracks:
        candidates = live_track_by_name.get(dt["name"], [])
        if not candidates:
            result.unmatched_db_tracks.append({"db_id": dt["id"], "name": dt["name"]})
            continue
        if len(candidates) > 1:
            result.notes.append(
                f"track name {dt['name']!r}: {len(candidates)} Live tracks "
                "match; linking to the first (track_index="
                f"{candidates[0]['track_index']}). Rename in Live to disambiguate."
            )
        chosen = candidates[0]
        if dt["kind"] != chosen.get("kind"):
            result.notes.append(
                f"track {dt['name']!r}: DB kind={dt['kind']!r} but "
                f"Live kind={chosen.get('kind')!r} (informational; link written anyway)"
            )
        M.link_db_to_ableton(
            conn, session_id=session_id, db_kind="track", db_id=dt["id"],
            ableton_index=chosen["track_index"], actor=actor, reason=reason,
        )
        consumed_live_track_indexes.add(chosen["track_index"])
        result.matched_tracks.append({
            "db_id": dt["id"],
            "name": dt["name"],
            "ableton_index": chosen["track_index"],
        })
    for lt in live_tracks:
        if lt["track_index"] not in consumed_live_track_indexes:
            result.unmatched_live_tracks.append({
                "track_index": lt["track_index"],
                "name": lt["name"],
            })

    _flag_case_near_matches(
        result.unmatched_db_tracks,
        result.unmatched_live_tracks,
        kind="track",
        notes=result.notes,
    )

    # ---- Returns: strip Live's slot-letter prefix, then match by name.
    live_return_by_name: dict[str, list[dict[str, Any]]] = {}
    for lr in live_returns:
        stripped = normalize_live_return_name(lr["name"])
        live_return_by_name.setdefault(stripped, []).append(lr)
    consumed_live_return_indexes: set[int] = set()
    for dr in db_returns:
        candidates = live_return_by_name.get(dr["name"], [])
        if not candidates:
            result.unmatched_db_returns.append({"db_id": dr["id"], "name": dr["name"]})
            continue
        if len(candidates) > 1:
            result.notes.append(
                f"return name {dr['name']!r} (suffix): {len(candidates)} Live "
                "returns match; linking to the first (return_index="
                f"{candidates[0]['return_index']})."
            )
        chosen = candidates[0]
        M.link_db_to_ableton(
            conn, session_id=session_id, db_kind="return", db_id=dr["id"],
            ableton_index=chosen["return_index"], actor=actor, reason=reason,
        )
        consumed_live_return_indexes.add(chosen["return_index"])
        result.matched_returns.append({
            "db_id": dr["id"],
            "name": dr["name"],
            "ableton_index": chosen["return_index"],
        })
    for lr in live_returns:
        if lr["return_index"] not in consumed_live_return_indexes:
            result.unmatched_live_returns.append({
                "return_index": lr["return_index"],
                "name": lr["name"],
            })

    # Returns match by stripped-name; compare against stripped form
    # so DB 'Reverb' vs Live 'A-reverb' surfaces as near-match.
    _flag_case_near_matches(
        result.unmatched_db_returns,
        result.unmatched_live_returns,
        kind="return",
        notes=result.notes,
        live_normalize=normalize_live_return_name,
    )

    # W18-B: strict reconciliation — sweep ableton_links for rows whose
    # ableton_index no longer appears in the fresh probe. Track + return kinds
    # drop here directly; the clip kind cascades off its parent track below
    # (SYN-3C8K), and arrangement_clip links reconcile by position when probed
    # (SYN-4R7P, further below). The remaining nested kinds (device/envelope/
    # note) are re-established by the next push's create-call path. Iterate over a
    # snapshot of the rows because the unlink mutator deletes from the same
    # table.
    live_track_indexes = {lt["track_index"] for lt in live_tracks}
    live_return_indexes = {lr["return_index"] for lr in live_returns}
    for link in list(Q.get_ableton_links_for_session(conn, session_id)):
        db_kind = link["db_kind"]
        ableton_index = link["ableton_index"]
        if db_kind == "track" and ableton_index not in live_track_indexes:
            M.unlink_db_from_ableton(
                conn,
                session_id=session_id,
                db_kind=db_kind,
                db_id=link["db_id"],
                actor=actor,
                reason=reason or "probe-and-link: stale track link",
            )
            result.unlinked_stale_tracks.append({
                "db_id": link["db_id"],
                "ableton_index": ableton_index,
            })
        elif db_kind == "return" and ableton_index not in live_return_indexes:
            M.unlink_db_from_ableton(
                conn,
                session_id=session_id,
                db_kind=db_kind,
                db_id=link["db_id"],
                actor=actor,
                reason=reason or "probe-and-link: stale return link",
            )
            result.unlinked_stale_returns.append({
                "db_id": link["db_id"],
                "ableton_index": ableton_index,
            })

    # SYN-3C8K: cascade stale clip-link drops. A `clip` link is valid only
    # while its parent track is linked in this session; a Live-set swap that
    # reuses the session drops the parent track link (above) but leaves the
    # clip link, so the clips planner downgrades `create` to `replace_notes`
    # against an empty slot and halts the clips phase. Drop a clip link whose
    # parent track has no surviving link (just-dropped or never linked), or
    # whose clip row is gone from the DB. Runs AFTER the track sweep so the
    # parent-link lookup reflects the drops; fresh snapshot because the track
    # sweep already consumed one and the unlink mutator mutates the same table.
    for link in [
        ln for ln in Q.get_ableton_links_for_session(conn, session_id)
        if ln["db_kind"] == "clip"
    ]:
        clip_row = Q.get_clip(conn, link["db_id"])
        parent_linked = clip_row is not None and Q.get_ableton_link(
            conn,
            session_id=session_id,
            db_kind="track",
            db_id=clip_row["track_id"],
        ) is not None
        if parent_linked:
            continue
        M.unlink_db_from_ableton(
            conn,
            session_id=session_id,
            db_kind="clip",
            db_id=link["db_id"],
            actor=actor,
            reason=reason or "probe-and-link: stale clip link (parent track unlinked)",
        )
        result.unlinked_stale_clips.append({
            "db_id": link["db_id"],
            "ableton_index": link["ableton_index"],
        })

    # SYN-4R7P: reconcile stale arrangement_clip links against Live truth. An
    # arrangement clip is a distinct Live copy whose index Live RE-NUMBERS on any
    # delete (no stable id, no name column — position is the identity key,
    # mirroring the pull-side diff in sync/pull/clips.py). When the user
    # deletes/edits arrangement clips in Live, the recorded arrangement_clip link
    # goes stale: plan_push_arrangement sees the link present, takes the
    # replace_notes(location='arrangement', clip_index=stale) REFRESH branch, and
    # crashes with IndexError on a clip that no longer exists. The original W18-B
    # sweep skipped this kind on the (false) claim it "re-establishes via the next
    # push's create-call path" — but that path only fires when the link is ABSENT,
    # so a stale-but-present link never recovers. Reconcile here, after the track
    # sweep + clip cascade so parent-track links are settled:
    #   * DB row gone, or parent track link gone     -> drop (cascade)
    #   * no live placement at the row's authored pos -> drop (create re-dupes)
    #   * live placement at a RENUMBERED index        -> re-bind the link index
    #   * live placement at the recorded index        -> keep (refresh works)
    # Only runs with a fresh per-track arrangement probe (None on --snapshot, like
    # devices). A track ABSENT from the probe map is a transient per-track probe
    # failure -> skip (never drop a live binding on missing info); an EMPTY list
    # is genuinely "no live clips on that track" -> drop.
    if live_arrangement_clips_by_track is not None:
        ts_points = Q.get_time_signature_map(conn, song_id)
        arr_rows_by_id = {
            r["id"]: r for r in Q.get_arrangement_for_song(conn, song_id)
        }
        # Identity is the placement's START position only (not start+end): the
        # reconcile asks "does a live clip still exist for this DB placement?",
        # so a user resize/trim in Live keeps the binding (the pull-side diff in
        # sync/pull/clips.py keys on (start,end) because it diffs CONTENT — a
        # different question). Two DB placements may legitimately share a start
        # on one track ("rare but valid" per get_arrangement_for_song); to keep
        # coincident placements from both binding to the SAME live clip, track
        # the live indices already consumed per track and prefer each link's
        # RECORDED index when it still sits at the position (no churn, no swap).
        consumed_by_track: dict[int, set[int]] = {}
        for link in [
            ln for ln in Q.get_ableton_links_for_session(conn, session_id)
            if ln["db_kind"] == "arrangement_clip"
        ]:
            arr_row = arr_rows_by_id.get(link["db_id"])
            parent_track_at = (
                Q.get_ableton_link(
                    conn, session_id=session_id, db_kind="track",
                    db_id=arr_row["track_id"],
                )
                if arr_row is not None else None
            )
            if arr_row is None or parent_track_at is None:
                M.unlink_db_from_ableton(
                    conn,
                    session_id=session_id,
                    db_kind="arrangement_clip",
                    db_id=link["db_id"],
                    actor=actor,
                    reason=reason or "probe-and-link: stale arrangement_clip "
                    "link (DB row or parent track gone)",
                )
                result.unlinked_stale_arrangement_clips.append({
                    "db_id": link["db_id"],
                    "ableton_index": link["ableton_index"],
                })
                continue
            # Track absent from the probe map = transient probe failure; keep the
            # link rather than risk dropping a live binding on missing info.
            if parent_track_at not in live_arrangement_clips_by_track:
                continue
            placements = live_arrangement_clips_by_track[parent_track_at]
            want_beats = _position_bar_to_beats(arr_row["start_bar"], ts_points)
            consumed = consumed_by_track.setdefault(parent_track_at, set())
            recorded = link["ableton_index"]
            at_position = [
                p for p in placements
                if p.get("start_beats") is not None
                and abs(float(p["start_beats"]) - want_beats) <= 1e-3
            ]
            # Prefer the recorded index if a live clip still sits at this
            # position there — keeps the binding stable and stops two coincident
            # placements from swapping indices. Otherwise take the first live
            # clip at the position not already claimed by another placement.
            match = next(
                (
                    p for p in at_position
                    if p.get("arrangement_clip_index") == recorded
                    and recorded not in consumed
                ),
                None,
            ) or next(
                (
                    p for p in at_position
                    if p.get("arrangement_clip_index") not in consumed
                ),
                None,
            )
            if match is None:
                M.unlink_db_from_ableton(
                    conn,
                    session_id=session_id,
                    db_kind="arrangement_clip",
                    db_id=link["db_id"],
                    actor=actor,
                    reason=reason or "probe-and-link: stale arrangement_clip "
                    "link (no live clip at authored position)",
                )
                result.unlinked_stale_arrangement_clips.append({
                    "db_id": link["db_id"],
                    "ableton_index": link["ableton_index"],
                })
                continue
            live_idx = match.get("arrangement_clip_index")
            if live_idx is not None:
                consumed.add(int(live_idx))
            if live_idx is not None and int(live_idx) != link["ableton_index"]:
                M.link_db_to_ableton(
                    conn,
                    session_id=session_id,
                    db_kind="arrangement_clip",
                    db_id=link["db_id"],
                    ableton_index=int(live_idx),
                    actor=actor,
                    reason=reason or "probe-and-link: re-bind arrangement_clip "
                    "link after Live re-numbered the placement",
                )
                result.rebound_arrangement_clips.append({
                    "db_id": link["db_id"],
                    "from_index": link["ableton_index"],
                    "to_index": int(live_idx),
                })

    # W20-A: bind devices by (parent, position, class_name). Run after track
    # + return matching so we know each parent's ableton_index. Closes the
    # re-push device duplication path where pre-existing Live devices that
    # match DB devices in shape were not yet in ableton_links, so
    # `_emit_device_calls` would dispatch a (duplicate) load on the next push.
    if live_devices_by_parent:
        _match_devices_for_linked_parents(
            conn,
            song_id=song_id,
            session_id=session_id,
            result=result,
            live_devices_by_parent=live_devices_by_parent,
            actor=actor,
            reason=reason,
        )
        # SNP-8R4K chunk 4: State-2 migration trigger. The probed device chains
        # are in chain order; if any surface has authored devices AFTER the
        # HallucinoteAnalyzer, the analyzer isn't the terminal measurement tap
        # and per-stem captures under-measured those trailing devices. This is
        # the pre-SNP-8R4K signature of a stale saved set. Emit operator
        # GUIDANCE (a note, not a hard halt — push is still safe; the SET's
        # captures are the only thing affected, and the fix is the operator's
        # to make). A clean/rebuilt set has no authored-after-analyzer
        # condition, so this is silent.
        _flag_stale_analyzer_set(result, live_devices_by_parent)

    # W18-D: detect "push onto Live's brand-new-set default scaffold."
    # Fires whenever every unmatched Live track is a canonical default — that
    # name set is the unambiguous signature, the real discriminator. When ANY
    # unmatched-Live track has a non-canonical name, this is "some other song's
    # tracks" territory and we deliberately don't suggest cleanup; the standard
    # "continue alongside?" gate handles that case.
    # SYN-3C8K: this used to also require ``auto_session_created`` — but a
    # *reused* session pushed onto a fresh default set (the set-swap case) has
    # the identical canonical scaffold to clean up, and degrading to the
    # generic unmatched-Live confirm there was a friction the dogfood hit. The
    # canonical-name signature already excludes unrelated sets, so the
    # fresh-vs-reused distinction added nothing but the missed-cleanup gap.
    if (
        result.unmatched_live_tracks
        and all(
            t["name"] in CANONICAL_DEFAULT_SCAFFOLD_TRACK_NAMES
            for t in result.unmatched_live_tracks
        )
    ):
        result.default_scaffold_unmatched_tracks = list(result.unmatched_live_tracks)

    return result


def _match_devices_for_linked_parents(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    result: ProbeAndLinkResult,
    live_devices_by_parent: dict[tuple[str, int], list[dict[str, Any]]],
    actor: str,
    reason: str | None,
) -> None:
    """W20-A: bind DB devices to Live device-chain slots by
    (parent, chain position, class_name).

    For each linked track/return (and the master), walk the parent's top-level
    device chain
    in parallel: at position P we have a DB device (with ``kind`` and
    ``display_name``) and, if Live's chain runs that deep, a Live device
    (with ``class_name`` and ``name``). When the class names agree, write
    an ``ableton_links`` row binding the DB device's id to Live's
    ``device_index`` so the next push's ``_emit_device_calls`` skips this
    slot instead of dispatching a duplicate ``load``.

    Match rule: position equality (DB ``devices.position`` = Live
    ``device_index``) AND class equality (DB ``devices.kind`` =
    Live ``class_name``). Mismatched class at the same position is a
    drift note — push will still load over the wrong device, but the
    note surfaces the situation so the user can rename or rebuild.

    Nested rack-chain devices are not LINKED here — only top-level devices
    carry an ableton_link binding. (DEEP-RACK-ADDR: their dialed params ARE
    pushed, addressed by the top-level device's index + the canonical
    device_path — see `push/devices.py _emit_nested_param_writes`; they arrive
    with the rack preset, so they need no separate load/link.) This probe-match
    walks the top-level chains, the high-frequency case that resolves the
    punk-fate bug.
    """
    # ANALYZER-INDEX: the master device chain reconciles like track/return
    # chains. The master is a DB-singleton track (kind='master') with no
    # name-match and no track_index, so synthesize its matched-parent entry
    # directly — db_id = the song's master track, ableton_index = 0 (the device
    # matcher's master key, matching `_probe_live_devices_via_mcp`'s
    # ("master", 0)). Before this, the master was excluded from device
    # reconciliation entirely (the track/return loop never covered it), so a
    # master device link was frozen at first-load and never re-bound; once a
    # render's analyzer load/reposition shifted the chain, a param re-push
    # targeted the stale index — the master Limiter's Ceiling hit the analyzer
    # and hard-halted the devices phase. Only attempt it when the master chain
    # was actually probed into the map.
    master_matched: list[dict[str, Any]] = []
    if ("master", 0) in live_devices_by_parent:
        master_track = next(
            (t for t in Q.get_tracks_for_song(conn, song_id)
             if t["kind"] == "master"),
            None,
        )
        if master_track is not None:
            master_matched = [{"db_id": master_track["id"], "ableton_index": 0}]

    for matched, parent_kind, get_devices_fn in (
        (result.matched_tracks, "track", Q.get_devices_for_track),
        (result.matched_returns, "return", Q.get_devices_for_return),
        (master_matched, "master", Q.get_devices_for_track),
    ):
        for parent in matched:
            ableton_index = parent["ableton_index"]
            live_devices = live_devices_by_parent.get((parent_kind, ableton_index))
            if not live_devices:
                continue
            db_devices = list(get_devices_fn(conn, parent["db_id"]))
            # Devices are 1-based by position in both spaces.
            # BUG1A: the HallucinoteAnalyzer is measurement infrastructure (a
            # render leaves it trailing the chain), not authored content — exclude
            # it before position-matching. Otherwise an authored DB device whose
            # position lands on the analyzer's slot compared against it, produced a
            # false "device drift" note, and skipped its link (so a param re-push
            # over an analyzer-laden set forced manual analyzer-deletion first). The
            # render keeps the analyzer terminal, so dropping it preserves the
            # authored devices' real `device_index` for the link.
            authored_live = [d for d in live_devices if not is_analyzer_device(d)]
            live_by_pos = {
                d["device_index"]: d for d in authored_live
            }
            for db_dev in db_devices:
                pos = db_dev["position"]
                live_dev = live_by_pos.get(pos)
                if live_dev is None:
                    # Live's chain is shorter — push will create the
                    # missing devices via _emit_device_calls. No link
                    # to write yet.
                    continue
                db_class = db_dev["kind"]
                # Arc 4 / D4: DB stores `kind` as the post-rename display
                # name (`class_display_name`). The MCP probe surfaces both
                # `class_display_name` (display) and `class_name` (internal,
                # e.g. `Eq8`, `Compressor2`, `InstrumentVector`). Compare
                # against the display value to match the DB's storage
                # convention; fall back to `class_name` so older probe
                # responses (pre-`class_display_name`) still resolve.
                live_class = (
                    live_dev.get("class_display_name")
                    or live_dev.get("class_name", "")
                )
                if db_class != live_class:
                    result.notes.append(
                        f"device drift at {parent_kind}#{ableton_index} "
                        f"position {pos}: DB has {db_class!r}, Live has "
                        f"{live_class!r}; not linking (push will load "
                        f"the DB device over Live's at this slot)"
                    )
                    continue
                M.link_db_to_ableton(
                    conn,
                    session_id=session_id,
                    db_kind="device",
                    db_id=db_dev["id"],
                    ableton_index=pos,
                    actor=actor,
                    reason=reason or f"probe-and-link: device match at {parent_kind}#{ableton_index} pos {pos}",
                )
                result.matched_devices.append({
                    "db_id": db_dev["id"],
                    "parent_kind": parent_kind,
                    "parent_index": ableton_index,
                    "position": pos,
                    "class_name": db_class,
                })


def _flag_stale_analyzer_set(
    result: ProbeAndLinkResult,
    live_devices_by_parent: dict[tuple[str, int], list[dict[str, Any]]],
) -> None:
    """SNP-8R4K chunk 4: detect a pre-SNP-8R4K stale Live set + emit guidance.

    A set is stale when any probed chain has an authored (non-analyzer) device
    AFTER the HallucinoteAnalyzer — the analyzer is no longer terminal, so the
    render's per-stem capture under-measured those trailing devices. Rolls the
    pure :func:`hallucinote.analyzer_staleness.detect_stale_analyzer_surfaces`
    detector over the same per-chain ORDERED probe map ``probe_and_link``
    already binds devices from, then appends operator guidance to
    ``result.notes`` (the non-fatal channel — same place device-drift surfaces;
    NOT a hard halt). Naming the stale surfaces + their trailing devices makes
    the "rebuild from source" guidance actionable.

    Silent on a clean/rebuilt set: with the analyzer terminal (or absent) on
    every surface, the detector returns ``[]`` and no note is added.
    """
    stale_surfaces = detect_stale_analyzer_surfaces(live_devices_by_parent)
    if not stale_surfaces:
        return
    surface_lines = "; ".join(stale_surfaces)
    result.notes.append(
        "STALE SET (SNP-8R4K): the HallucinoteAnalyzer is not the terminal "
        "device on " + str(len(stale_surfaces)) + " surface(s) — authored "
        "devices sit after the measurement tap, so per-stem captures "
        "under-measured them: " + surface_lines + ". This set predates the "
        "analyzer-infrastructure fix (SNP-8R4K). Live has no reorder API, so "
        "the fix is to REBUILD THE SET FROM SOURCE: push into a fresh set (the "
        "model is already analyzer-free, and the render adds the analyzer last "
        "on capture). The push itself is unaffected — only this set's captured "
        "measurements were wrong."
    )


def _flag_case_near_matches(
    unmatched_db: list[dict[str, Any]],
    unmatched_live: list[dict[str, Any]],
    *,
    kind: str,
    notes: list[str],
    live_normalize: Callable[[str | None], str | None] | None = None,
) -> None:
    """Surface DB×Live pairs that match case-insensitively but not
    case-sensitively. Catches the silent foot-gun where a user renames
    Live's 'Drums' → 'drums' and the probe creates a duplicate 'Drums'
    track right next to it (W4-E real-Live finding, 2026-05-18).

    Returns through ``notes`` rather than the unmatched lists — both
    sides stay genuinely unmatched (the probe doesn't auto-link
    case-variant pairs; the user decides). ``live_normalize`` is
    applied to the Live-side name before comparison (e.g. strip
    Live's return slot-letter prefix so DB 'Reverb' near-matches
    Live 'A-reverb' / 'a-Reverb').
    """
    norm = live_normalize or (lambda s: s)
    for db in unmatched_db:
        db_name = db["name"]
        for live in unmatched_live:
            live_name = norm(live["name"])
            if (
                db_name != live_name
                and db_name.casefold() == live_name.casefold()
            ):
                notes.append(
                    f"DB {kind} {db_name!r} has near-match Live "
                    f"{live['name']!r} (case differs); intentional? "
                    "Rename one to match if not."
                )


# ---------------------------------------------------------------------------
# Coherence check (W18-A)
# ---------------------------------------------------------------------------


@dataclass
class CoherenceResult:
    """Outcome of :func:`check_coherence`. Tri-state: ``ok=True`` with no
    errors means execute is safe; ``ok=False`` with errors means refuse and
    surface recovery hints. ``notes`` carries informational findings (e.g.
    "session has no links yet, push will create from scratch") that don't
    block execute.
    """
    ok: bool = True
    errors: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def add_error(self, *, kind: str, detail: str, recovery: str) -> None:
        self.errors.append({"kind": kind, "detail": detail, "recovery": recovery})
        self.ok = False


def check_coherence(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    live_tracks: list[dict[str, Any]],
    live_returns: list[dict[str, Any]],
) -> CoherenceResult:
    """Validate that ``ableton_sessions`` + ``ableton_links`` rows are
    consistent with a freshly-probed Live snapshot, before ``execute``
    starts mutating Live.

    Closes the punk-fate 2026-05-20 state-drift class: three pieces of
    per-machine state (snapshot file, ``ableton_sessions``, ``ableton_links``)
    with independent invalidation rules and no consistency check. This
    function refuses execute on any of:

    1. **Session row missing.** ``session_id`` doesn't resolve in
       ``ableton_sessions`` (e.g. ``build.py --reset`` wiped it).
    2. **Stale track link.** An ``ableton_links`` row points at a
       ``track_index`` no longer in the live probe (e.g. the user deleted
       the linked Live track).
    3. **Stale return link.** Same shape for ``return_index``.

    Callers pass a FRESH probe (re-run ``ableton_track(action='list')`` +
    ``ableton_return(action='list')`` against Live just before this check).
    The function reads links from the DB and validates against that probe.

    Nested links (clip / device / device_chain) aren't validated directly
    here — a stale parent track link cascade-invalidates them, and the
    parent check is sufficient to refuse the push. Probing every nested
    binding would require deep MCP traffic; the parent-level check buys
    the same safety at a tenth the cost.

    Returns a :class:`CoherenceResult`. Callers should refuse to execute
    when ``ok`` is False and surface the per-error ``recovery`` hints.
    """
    result = CoherenceResult()

    if Q.get_ableton_session(conn, session_id) is None:
        result.add_error(
            kind="session_missing",
            detail=f"no ableton_sessions row with id {session_id!r}",
            recovery=(
                "Mint a fresh session: run "
                "`push_cli probe-and-link --auto-session --song <slug> "
                "--snapshot <path>`. This is the usual repro after "
                "`build.py --reset` wipes the sessions table."
            ),
        )
        # No session → no point checking links; they're orphaned anyway.
        return result

    live_track_indexes = {lt["track_index"] for lt in live_tracks}
    live_return_indexes = {lr["return_index"] for lr in live_returns}

    links = Q.get_ableton_links_for_session(conn, session_id)
    if not links:
        result.notes.append(
            "session has no ableton_links rows — push will create tracks/returns "
            "from scratch (this is fine for a first push, but probe-and-link "
            "should have run if Live already contained any of the song's tracks)"
        )
        return result

    stale_track_links: list[dict[str, Any]] = []
    stale_return_links: list[dict[str, Any]] = []
    for link in links:
        db_kind = link["db_kind"]
        ableton_index = link["ableton_index"]
        if db_kind == "track":
            if ableton_index not in live_track_indexes:
                stale_track_links.append({
                    "db_id": link["db_id"],
                    "ableton_index": ableton_index,
                })
        elif db_kind == "return":
            if ableton_index not in live_return_indexes:
                stale_return_links.append({
                    "db_id": link["db_id"],
                    "ableton_index": ableton_index,
                })
        # Other kinds (clip / device / device_chain) are nested under a
        # track or return; a stale parent link cascade-invalidates them
        # and the parent-level error is sufficient.

    if stale_track_links:
        indexes = sorted({l["ableton_index"] for l in stale_track_links})
        result.add_error(
            kind="stale_track_links",
            detail=(
                f"{len(stale_track_links)} ableton_links row(s) point at "
                f"track_index(es) {indexes} that no longer exist in Live "
                f"(live tracks: {sorted(live_track_indexes)}). "
                "Common cause: user deleted the linked Live track after "
                "probe-and-link wrote the link row."
            ),
            recovery=(
                "Re-run `push_cli probe-and-link --probe` (or supply a fresh "
                "--snapshot). W18-B's strict reconciliation will delete the "
                "stale link rows and re-match anything still present."
            ),
        )

    if stale_return_links:
        indexes = sorted({l["ableton_index"] for l in stale_return_links})
        result.add_error(
            kind="stale_return_links",
            detail=(
                f"{len(stale_return_links)} ableton_links row(s) point at "
                f"return_index(es) {indexes} that no longer exist in Live "
                f"(live returns: {sorted(live_return_indexes)}). "
                "Common cause: user deleted the linked Live return after "
                "probe-and-link wrote the link row."
            ),
            recovery=(
                "Re-run `push_cli probe-and-link --probe` (or supply a fresh "
                "--snapshot) to drop the stale link rows."
            ),
        )

    return result
