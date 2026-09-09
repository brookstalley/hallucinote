"""Live-Ableton snapshot format and replay.

The snapshot is a JSON document describing the mix layout of an Ableton set —
tracks (with kind + mixer state), returns, sends, the master strip, and (post
chunk 4a) device chains with dialed parameters. It is the seed mechanism for
`build.py`: capture once (live Ableton -> snapshot.json), then replay into the
DB through mutators.

Scope (chunks 3 + 4a + W7-B + DEEP-RACK-ADDR): tracks + returns + sends + master
+ mixer state + device chains (top-level AND nested) + dialed device parameters.
Each rack-kind device (Arc 4 / D4 display names: ``Drum Rack``,
``Instrument Rack``, ``Audio Effect Rack``; pre-D4 these were the internal
class names ``DrumGroupDevice``/``InstrumentGroupDevice``/``AudioEffectGroupDevice``)
may optionally carry a ``chains: [{chain_index, name, devices: [...]}]``
array, and a nested device may itself be a rack — replay (`_replay_rack_chains`)
recurses to ARBITRARY depth (DEEP-RACK-ADDR; the DB's ``device_chains`` /
``device_parameters`` are depth-agnostic). NOTE: the snapshot-refresh PREVIEW
(`diff_snapshots` / `merge_snapshots`) itemizes only one level and summarizes
deeper subtrees opaquely — a preview simplification, NOT a data limit (replay
ingests the full snapshot regardless). Automation envelopes (chunk 4b) are
schema-modeled and push-plannable but the capture/replay path doesn't ingest
them yet — MCP exposes no read surface for the seven envelope target families
(see `ableton://guides/gaps`).

Snapshot shape (extends the existing `captured_session.json` prototype):

    {
      "song": {
        "name":      "..." (optional; defaults to caller-supplied),
        "key":       "..." (optional),
        "tempo":     132.0,         # informational; score-chunk tempo_map owns this
        "signature": "4/4",         # informational; score-chunk time_signature_map owns this
        "master":    {"volume": 0.85, "panning": 0.0,
                      "devices": [...]}  # optional master chain (SNP-4K7M)
      },
      "returns": [
        {"index": 1, "name": "A-Reverb", "volume": 0.85, "panning": 0.0, "color": null}
      ],
      "tracks": [
        {
          "index": 5, "name": "01 Drums", "type": "midi",
          "volume": 0.6249, "panning": 0.0,
          "mute": false, "solo": false, "arm": false,
          "color": null,
          "instrument_uri": "query:Drums#FileId_5418",   # optional
          "sends": {"A-Reverb": 0.0, "B-Delay": 0.0}
        }
      ]
    }

Replay creates: returns (1 row per `returns[]`), tracks (1 row per `tracks[]`,
plus a `kind='master'` row for `song.master`), sends (1 row per non-null entry
in each track's `sends` map, keyed by return name), top-level device chains
(1 per track/return/master that has a `devices: [...]` array — chunk 4a;
master added by SNP-4K7M), devices
(1 row per array entry), device parameters (1 row per entry in each device's
`params_dialed: {...}` map). A sampler device entry also carries
`audio_file: "assets/..."` — the sample it plays, in the same song-relative-or-
absolute form `clips.audio_file` uses; push hands it back via
`ableton_device(action='assign_sample')`. `clips: [...]` on tracks is still
ignored — populated by build.py hand-authored sections.

Live capture (Ableton -> snapshot.json) runs IN CODE over the bridge push/pull
already use: `assemble_snapshot_via_probes` walks the live set, issuing the v1
unified-action probes (`ableton_session(action='info')`,
`ableton_return(action='list'|'info')`, `ableton_track(action='info'|'get_sends')`,
`ableton_device(action='list'|'get_parameters'|'get_device_chains'|'pad_info')`)
and assembling the dict via `compile_snapshot` — reaching device parameters at
EVERY nesting depth via NodeAddr `path` (NODE-ADDR Chunk B). `tools/capture_cli.py`
exposes it as `capture execute`. `capture_plan` still lists the probe sequence
for hand/first captures, but the deterministic in-code path is the default.
(The earlier "Python can't call MCP tools" framing was wrong — the
`hallucinote_mcp.client.send` bridge has always been callable from Python.)
"""
from __future__ import annotations

import re
import sqlite3
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hallucinote.analyzer_identity import is_analyzer_device
from hallucinote.db import mutations as M, queries as Q
from hallucinote.paths import audio_file_ref
from hallucinote.return_naming import normalize_live_return_name

# SNP-8R4K chunk 2 — snapshot schema version stamped on every compiled snapshot
# (`compile_snapshot`) and asserted by the at-rest cleanup (`migrate_snapshot`).
# Bumped deliberately when the snapshot schema changes in a way the migrator
# must act on. v1 = "analyzer-free, dense authored device positions" (the
# SNP-8R4K release). An unstamped snapshot (missing key) or one stamped < this
# version is pre-SNP-8R4K and triggers the one-time cleanup
# (`snapshot_needs_migration`). This is an INTENTIONAL schema version — bumped
# by hand as part of a migration — not a freshness/staleness label, so the
# "derive from content, never hand-bump" learning does not apply.
SNAPSHOT_SCHEMA_VERSION = 1

# Track types accepted in snapshot["tracks"][n]["type"]; mapped 1:1 to
# `tracks.kind` in the DB. Unknown values raise; the snapshot is authoritative.
_VALID_TRACK_TYPES = frozenset({"midi", "audio", "group"})


# ---------------------------------------------------------------------------
# BAK-7D2V — pull-durability guard (replay side)
# ---------------------------------------------------------------------------
# A `/ableton-pull` apply writes live edits into the (regenerable, git-ignored)
# DB but never into `captured_session.json` — so the next build's
# `replay_capture` would re-assert the stale snapshot over them, silently.
# Both writers use actor='sync', so actor precedence can't see the conflict;
# the reliable discriminator is provenance: pull applies run under a
# `requests.kind='pull'` row and every event they emit carries that
# request_id + song_id + ts. `replay_capture` refuses (StaleSnapshotError)
# when such events are NEWER than the snapshot's `captured_at` stamp.
# Design + refuse/warn matrix: .prawduct/artifacts/plans/BAK-7D2V/archive/design.md.

# Event kinds for state replay_capture re-asserts from the snapshot. A pulled
# event OUTSIDE this set (clip-notes, envelopes, tempo/cue, routing, tuning,
# ...) is state replay cannot revert, so it never arms the guard — this is
# what keeps ordinary build.py-staging pulls from tripping it.
#
# Coverage contract (audited 2026-07-04; method + full table in
# .prawduct/artifacts/plans/BAK-7D2V/archive/design.md §"Kind-set audit"): for EVERY
# mutator any pull apply handler calls (grep `M\.` over sync/pull/), the event
# kind(s) it emits are either in this tuple (replay re-asserts that state) or
# provably outside replay's write surface. Cascade-deleting mutators matter
# most: delete_device_chain cascades its nested devices with NO per-device
# events, so `device_chain_deleted` is the ONLY signal for a pulled
# chain-removal that _replay_rack_chains would recreate. Re-run the audit when
# adding a pull apply handler or extending replay's write surface.
_REPLAY_ASSERTED_EVENT_KINDS: tuple[str, ...] = (
    "song_created", "song_updated",
    "track_created", "track_updated", "track_mixer_set",
    "return_created", "return_updated",
    "send_set", "send_removed",
    "device_chain_created", "device_chain_deleted", "device_chain_props_set",
    "device_created", "device_deleted",
    "device_parameter_set", "device_parameter_removed",
    "device_param_overrides_replaced", "device_sidechain_set",
    "drum_pad_mappings_replaced",
)

# `captured_at` must be EXACTLY the events.ts shape
# (strftime('%Y-%m-%dT%H:%M:%fZ'), i.e. YYYY-MM-DDTHH:MM:SS.mmmZ) for the
# lexicographic comparison against event rows to be chronological. Anything
# else — including an ISO stamp with a timezone OFFSET ("...T14:34:56+02:00",
# which can compare up to +14h ahead of the equivalent UTC instant and would
# silently defeat the guard) — takes the conservative legacy/warn path.
_CAPTURED_AT_SHAPE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")


def has_usable_captured_at(snapshot: dict[str, Any]) -> bool:
    """True when the snapshot's ``captured_at`` is present and parseable — i.e.
    the guard can order it against pulled events instead of falling back to the
    legacy warn-and-proceed branch.

    The one public read of :data:`_CAPTURED_AT_SHAPE`, so every caller that must
    distinguish a stamped snapshot from a legacy one shares a single definition
    of "usable" rather than re-deriving the shape.
    """
    captured_at = snapshot.get("captured_at")
    return bool(
        isinstance(captured_at, str) and _CAPTURED_AT_SHAPE.fullmatch(captured_at)
    )


class StaleSnapshotError(RuntimeError):
    """`replay_capture` refused to run: the DB holds pulled live edits newer
    than the snapshot's `captured_at`, which the replay would silently revert.

    Raised only when the snapshot carries a usable stamp to compare against —
    without one there is no ordering evidence, so the guard warns and proceeds
    rather than refusing (see :func:`_guard_stale_snapshot`'s matrix).

    The durable fix is a re-capture — `/song-snapshot` (diff + confirmed
    overwrite of the canonical file), or `capture_cli execute` + copying the
    `.refresh.json` it writes over `captured_session.json`. The
    conscious-revert override is `allow_stale_snapshot=True`
    (`--force-replay` in scaffolded build.py)."""


def utc_now_eventlike() -> str:
    """UTC now in the exact `events.ts` shape (`YYYY-MM-DDTHH:MM:SS.mmmZ`) so
    string comparison against event rows is chronological comparison."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _pulled_rows_newer_than(
    conn: sqlite3.Connection, *, song_id: str, cutoff_ts: str | None,
) -> list[sqlite3.Row]:
    """Events from `kind='pull'` requests on this song whose kind replay
    re-asserts, optionally restricted to those newer than ``cutoff_ts``.
    Dry-run pulls roll back their request + events, so they leave no rows."""
    placeholders = ", ".join("?" for _ in _REPLAY_ASSERTED_EVENT_KINDS)
    sql = (
        "SELECT e.seq, e.ts, e.kind FROM events e "
        "JOIN requests r ON r.id = e.request_id "
        "WHERE r.kind = 'pull' AND e.song_id = ? "
        f"AND e.kind IN ({placeholders})"
    )
    params: list[Any] = [song_id, *_REPLAY_ASSERTED_EVENT_KINDS]
    if cutoff_ts is not None:
        sql += " AND e.ts > ?"
        params.append(cutoff_ts)
    sql += " ORDER BY e.ts"
    return conn.execute(sql, params).fetchall()


def count_request_replay_asserted_events(
    conn: sqlite3.Connection, *, request_id: str,
) -> int:
    """How many events emitted under ``request_id`` are of a kind
    ``replay_capture`` re-asserts — i.e. mix-layer state a stale snapshot would
    later silently revert.

    ``pull_cli`` calls this right after a pull apply to fire its durability
    notice on exactly the event KINDS that arm the replay guard: same kind set
    (:data:`_REPLAY_ASSERTED_EVENT_KINDS`), same per-request provenance, no
    parallel domain whitelist to drift out of sync with the guard.

    Kind parity, not outcome parity — a non-zero count means the guard WILL be
    armed on the next build, but whether it then refuses or merely warns depends
    on the snapshot carrying a usable ``captured_at`` (see
    :func:`_guard_stale_snapshot`'s matrix). Scoping by ``request_id`` (not
    ``song_id``) restricts the count to the just-applied pull, so it reflects
    what THIS pull staged, not history."""
    placeholders = ", ".join("?" for _ in _REPLAY_ASSERTED_EVENT_KINDS)
    sql = (
        "SELECT COUNT(*) FROM events "
        f"WHERE request_id = ? AND kind IN ({placeholders})"
    )
    row = conn.execute(
        sql, [request_id, *_REPLAY_ASSERTED_EVENT_KINDS],
    ).fetchone()
    return int(row[0])


def _guard_stale_snapshot(
    conn: sqlite3.Connection,
    snapshot: dict[str, Any],
    *,
    song_id: str,
    song_name: str,
    allow_stale_snapshot: bool,
) -> None:
    """Refuse (or warn, per the BAK-7D2V matrix) before replay mutates anything.

    Matrix:
      * no pulled replay-asserted events        -> silent pass
      * stamped snapshot, newer pulled events   -> raise StaleSnapshotError
      * stamped + allow_stale_snapshot=True     -> UserWarning, proceed (revert)
      * legacy snapshot (no/unparseable stamp)
        with ANY pulled replay-asserted events  -> UserWarning, proceed
        (no ordering evidence; refusing would permanently false-alarm every
        previously-pulled song — the warning funnels to a stamping re-capture)
    """
    captured_at = (
        snapshot.get("captured_at") if has_usable_captured_at(snapshot) else None
    )
    rows = _pulled_rows_newer_than(conn, song_id=song_id, cutoff_ts=captured_at)
    if not rows:
        return

    newest = rows[-1]
    sample = ", ".join(f"{r['kind']} at {r['ts']} (seq {r['seq']})" for r in rows[-3:])
    if captured_at is None:
        warnings.warn(
            f"replay_capture: snapshot for song {song_name!r} has no "
            f"`captured_at` stamp, and the DB holds {len(rows)} pulled live "
            f"edit(s) from `/ableton-pull` (latest: {sample}). Whether this "
            "replay reverts them cannot be determined — if you pulled by-ear "
            "work after this snapshot was captured, it is being overwritten "
            "NOW. Re-capture to bake live edits durably and stamp the "
            "snapshot so this check becomes exact: run `/song-snapshot` "
            "(probe -> diff -> confirmed overwrite of captured_session.json), "
            'or `"<python>" -m hallucinote.cli capture execute --song '
            "<slug>` — note that writes captured_session.refresh.json, NOT "
            "the canonical file: review/diff it, then copy it over "
            "captured_session.json yourself. (A legacy file is never "
            "auto-stamped — that would silently defeat the check.)",
            UserWarning,
            stacklevel=3,
        )
        return
    if allow_stale_snapshot:
        warnings.warn(
            f"replay_capture: allow_stale_snapshot=True — REVERTING {len(rows)} "
            f"pulled live edit(s) on song {song_name!r} newer than the "
            f"snapshot ({captured_at}); latest: {sample}. This check fires "
            "again on every build until the snapshot is re-captured.",
            UserWarning,
            stacklevel=3,
        )
        return
    raise StaleSnapshotError(
        f"replay_capture: REFUSING to replay a stale snapshot onto song "
        f"{song_name!r}. The DB holds {len(rows)} live edit(s) pulled from "
        f"Ableton via `/ableton-pull` / pull_cli that are NEWER than the "
        f"snapshot's captured_at ({captured_at}) — newest: {sample} (event "
        f"seq {newest['seq']}). Replaying now would silently revert that "
        "by-ear work to the older snapshot values.\n"
        "The durable fix: re-capture the snapshot first, then rebuild — run "
        "`/song-snapshot` (probe -> diff -> confirmed overwrite of "
        "captured_session.json), or `python -m "
        "hallucinote.tools.capture_cli execute --song <slug>` and note that "
        "writes captured_session.refresh.json, NOT the canonical file: "
        "review/diff it (`capture_cli diff`), then copy it over "
        "captured_session.json yourself.\n"
        "To consciously revert the pulled edits instead, pass "
        "`allow_stale_snapshot=True` to replay_capture (scaffolded build.py "
        "exposes this as `--force-replay`). A forced replay does NOT clear "
        "this check — it fires on every build until the snapshot is "
        "re-captured."
    )


# Live device classes that own nested chains. Mirrors `_resolve_rack_chains`
# in hallucinote_mcp.handlers.device — kept here so the snapshot replay path
# can validate "this device carries `chains`, but its class isn't a rack"
# at the boundary. W6-I/J shipped the MCP-side walk; W7-B threads it through
# capture + pull.
# Arc 4 / D4: rack identity is checked against browser display names
# (the post-D4 ``devices.kind`` convention) — ``"Drum Rack"`` /
# ``"Instrument Rack"`` / ``"Audio Effect Rack"``. The pre-D4 set
# used internal Live class names (``DrumGroupDevice`` etc.) to match
# the old ``snapshot.class`` semantics; with the convention shift
# they're the same identity expressed in the loader-facing namespace.
RACK_CLASS_NAMES = frozenset({
    "Drum Rack",
    "Instrument Rack",
    "Audio Effect Rack",
})


def _norm_pan(value: Any) -> float | None:
    """Snapshot uses `panning`; DB column is `pan`. Pass-through with type check."""
    if value is None:
        return None
    f = float(value)
    if not -1.0 <= f <= 1.0:
        raise ValueError(f"pan {f} out of range [-1.0, 1.0]")
    return f


def _norm_vol(value: Any) -> float | None:
    if value is None:
        return None
    f = float(value)
    if not 0.0 <= f <= 1.0:
        raise ValueError(f"volume {f} out of range [0.0, 1.0]")
    return f


def _norm_bool(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def normalize_param_value(
    value: float, min_val: float, max_val: float, is_enum: bool,
) -> float | None:
    """Map Live's raw ``DeviceParameter.value`` into the DB's [0, 1] form.

    Returns ``None`` for enum/quantized params (schema CHECK allows NULL —
    there's no continuous form) and for constant-range params (``min == max``;
    the normalized form is undefined). Otherwise returns
    ``(value - min) / (max - min)`` clamped into [0, 1] — Live's reported value
    can be marginally outside the documented range due to float, but the schema
    CHECK is strict on [0, 1] so we clamp at the boundary.

    Single source for the raw→normalized conversion shared by the capture path
    (snapshot ``params_dialed`` normalized values) and the pull apply path (DB
    ``device_parameters.value_normalized``). Lives here — the lowest layer that
    both depend on (``sync.pull`` already imports ``capture``) — so there is one
    definition, not a per-consumer copy.
    """
    if is_enum:
        return None
    rng = max_val - min_val
    if abs(rng) < 1e-9:
        return None
    norm = (value - min_val) / rng
    return max(0.0, min(1.0, norm))


def param_needs_raw_channel(
    min_val: float, max_val: float, is_enum: bool,
) -> bool:
    """DEV-4P7R: True when a CONTINUOUS (non-enum) param must ride the raw
    ``value_raw`` channel — i.e. it is not an enum AND its raw range is not
    ``[0,1]``.

    Raw range != [0,1] is the principled discriminator, NOT ``is_quantized``
    (probed False on the witness ``Wavetable LFO S. Rate``: raw ``8.0`` ->
    "1/2", range ``[0,21]``, is_quantized False). For ANY non-[0,1] continuous
    param both other channels are unsafe: the normalized form is pushed AS raw
    (the handler has no value_normalized kwarg) so it mis-dials, and the display
    is non-monotonic for the step-list class ("8,6,4,...,1/64") so the live
    setter refuses to invert it. ``value_raw`` stores Live's own ``param.value``
    and pushes it straight through — always exact, so this rule can never
    mis-dial; it just routes the lossless channel for the affected class.

    Single source shared by the capture path (``_snapshot_param_entry``) and the
    pull apply path, mirroring ``normalize_param_value``."""
    if is_enum:
        return False
    if abs(max_val - min_val) < 1e-9:
        return False  # constant-range (min == max): nothing to dial, no channel
    return abs(min_val) > 1e-9 or abs(max_val - 1.0) > 1e-9


def _param_value_fields(
    p: Any, *, device_name: Any, param_name: Any,
) -> tuple[str, float | None, list[str] | None, float | None]:
    """Translate one snapshot param spec
    ``{value, normalized?, value_items?, value_raw?}`` into the
    ``(value_display, value_normalized, value_items, value_raw)`` the device
    mutators store. Emits the BUG4 bare-numeric-value warning. Shared by the
    top-level ``params_dialed`` replay and the nested ``param_overrides`` replay
    (SNP-2H9F) so both translate identically.

    ``value_raw`` (DEV-4P7R) is the UNCLAMPED raw channel for a quantized
    continuous param whose range != [0,1]. When present, ``value`` is optional
    (a readable display HINT only — push uses the raw); the mutator rejects
    pairing it with ``normalized`` / ``value_items``.
    """
    if not isinstance(p, dict) or ("value" not in p and "value_raw" not in p):
        raise ValueError(
            f"snapshot param {param_name!r} on device {device_name!r}: "
            f"expected dict with a 'value' or 'value_raw' key, got {p!r}"
        )
    normalized = p.get("normalized")
    value_raw = p.get("value_raw")
    raw_items = p.get("value_items")
    value_items = (
        [str(item) for item in raw_items]
        if isinstance(raw_items, (list, tuple))
        else None
    )
    # `value` is the display string (or a readable hint when value_raw drives).
    # Absent only in a raw-only entry, where it defaults to "" (push ignores it).
    value = p.get("value", "")
    # BUG4 (params_dialed authoring trap): a bare numeric `value` with no
    # `normalized` is stored as the DISPLAY string str(value) and pushed via
    # the display path (push devices.py branch 2 → the live setter's curve
    # inversion), which mis-dials a continuous param. The two correct author
    # forms are an explicit `normalized` (for a 0..1 value) or a display
    # STRING like "180 Hz" (the live setter inverts the log curve, DPP-7H2K).
    # value_raw is the third correct form, so a numeric `value` riding alongside
    # it is a readable hint, not the bare-numeric trap — don't warn there.
    if (
        value_raw is None
        and normalized is None
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        warnings.warn(
            f"snapshot param {param_name!r} on device {device_name!r}: a bare "
            f"numeric value {value!r} with no 'normalized' key is stored as "
            f"the display string {str(value)!r} and pushed as a display value "
            "(likely mis-dialing a continuous param). To author a NORMALIZED "
            f'0..1 value add "normalized": {value}; to author a display value '
            'use a string, e.g. "value": "180 Hz" (the push inverts it via the '
            "live setter); for a quantized non-[0,1] param use "
            f'"value_raw": {value}. See docs/snapshot-schema.md.',
            UserWarning,
            stacklevel=2,
        )
    return (
        str(value),
        float(normalized) if normalized is not None else None,
        value_items,
        float(value_raw) if value_raw is not None else None,
    )


def _override_entry_for_replay(
    o: Any, *, device_name: Any,
) -> dict[str, Any]:
    """Translate one snapshot ``param_overrides`` entry
    (``{path, name, value[, normalized][, value_items]}``) into the override dict
    ``replace_device_param_overrides`` stores (SNP-2H9F). The path is validated
    by the mutator; here we require the entry shape and reuse the shared value
    translation so an override dials identically to a top-level params_dialed."""
    if not isinstance(o, dict) or "name" not in o or "path" not in o:
        raise ValueError(
            f"snapshot param_override on device {device_name!r}: expected a dict "
            f"with 'path' and 'name', got {o!r}"
        )
    value_display, value_normalized, value_items, value_raw = _param_value_fields(
        o, device_name=device_name, param_name=o["name"],
    )
    return {
        "path": o["path"],
        "name": o["name"],
        "value_display": value_display,
        "value_normalized": value_normalized,
        "value_items": value_items,
        "value_raw": value_raw,
    }


def _replay_devices(
    conn: sqlite3.Connection,
    *,
    chain_id: str,
    devices_array: list[dict[str, Any]],
    actor: str,
    request_id: str | None,
    reason: str | None,
    sidechain_pending: list[tuple[str, str | None, str | None]],
) -> None:
    """Insert each entry of `devices_array` into the given chain, plus any
    dialed parameters and any nested rack chains — recursively, to arbitrary
    depth (DEEP-RACK-ADDR). A rack device inside a rack chain recurses through
    `_replay_rack_chains` the same way a top-level rack does; `device_chains`
    and `device_parameters` are depth-agnostic in the DB, so no per-depth
    special-casing is needed.

    BAK-3M9T — every device's sidechain source is appended to `sidechain_pending`
    as ``(device_id, sidechain_source_name | None, channel | None)``. Resolution
    is deferred to `replay_capture` (a source may name a track created later in
    the loop); the snapshot is authoritative, so an absent source clears any
    prior one (idempotent) — the same drop-clears-stale idiom as the per-chain
    properties in `_replay_rack_chains`.

    SNP-8R4K — defensive analyzer exclusion: capture filters the analyzer at
    `compile_snapshot`, but a legacy-polluted snapshot on disk may still carry
    an analyzer entry. We skip `is_analyzer_device` entries here so replay
    never writes an analyzer device row, and assign each survivor's `position`
    its 1-based rank among survivors (not the entry's raw `index`) so a dropped
    analyzer can't leave a hole or shift authored positions.
    """
    survivors = [d for d in devices_array if not is_analyzer_device(d)]
    for survivor_rank, d in enumerate(survivors, start=1):
        if "index" not in d or "class" not in d:
            raise ValueError(
                f"snapshot device missing required keys (index, class): {d!r}"
            )
        # Sweep B: snapshot device entries may carry preset_query as the
        # compose-time portable alternative to per-machine preset_uri.
        # The two are mutually exclusive — create_device refuses both at once.
        # Hand-authored snapshots use this to express "load a 909 kit"
        # without baking in this machine's FileId.
        preset_query = d.get("preset_query")
        preset_uri = d.get("guess_uri") if preset_query is None else None
        # Arc 7-tail / E3 (W13-A v1.0): snapshots may carry the browser
        # path the device was originally loaded from (captured by the
        # MCP load handler's `resolved_path` response field). The push
        # planner threads this through to the load handler as a
        # fallback identity when the per-machine preset_uri doesn't
        # resolve. Pre-E3 snapshots omit it — devices stay loadable
        # via preset_uri / kind-only, just without cross-machine
        # FileId fallback.
        browser_path_raw = d.get("browser_path")
        browser_path: list[str] | None
        if isinstance(browser_path_raw, list) and browser_path_raw:
            browser_path = [str(s) for s in browser_path_raw]
        else:
            browser_path = None
        # Arc 4 / D4: snapshots may carry `class_name` (Live's internal
        # class identifier) alongside `class` (the browser display name
        # the loader matches). Capture-from-Live populates both; hand-
        # authored snapshots may omit `class_name`. The mutator accepts
        # None for that field — informational column, drives plugin
        # classification when present.
        # SMP-7K2D: a sample-instrument device entry carries `audio_file`
        # (song-relative under assets/, or absolute) — the sampler's assigned
        # sample. Non-sampler devices omit it. Push resolves it via
        # paths.resolve_audio_path, the same resolver clips use.
        device_id = M.create_device(
            conn,
            chain_id=chain_id,
            position=survivor_rank,
            kind=d["class"],
            display_name=d.get("name", d["class"]),
            class_name=d.get("class_name"),
            preset_uri=preset_uri,
            preset_query=preset_query,
            browser_path=browser_path,
            audio_file=d.get("audio_file"),
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        # BAK-3M9T: defer sidechain-source resolution (the source may name a
        # track created later in the replay loop) to the post-pass.
        #
        # Snapshot SILENCE means "no opinion", not "clear". Only enqueue when the
        # snapshot ENTRY actually declares `sidechain_source` — a device the
        # snapshot says nothing about keeps whatever the DB already holds (e.g. a
        # source authored in build.py via M.set_device_sidechain). Capture only
        # writes the key when it FINDS a live source (~L1288 below), so an absent
        # key is genuinely "unspoken"; clobbering it to null re-cleared every
        # build.py-authored sidechain on every build, breaking converger
        # idempotency for any song with a mix-pass sidechain.
        # See backlog SYN-7N4K
        # An explicit null value (a future capture that records "no source here")
        # still clears on the post-pass — this is forward-compatible.
        if "sidechain_source" in d:
            sidechain_pending.append((
                device_id,
                d.get("sidechain_source"),
                d.get("sidechain_source_channel"),
            ))
        for name, p in (d.get("params_dialed") or {}).items():
            value_display, value_normalized, value_items, value_raw = \
                _param_value_fields(
                    p, device_name=d.get("name"), param_name=name,
                )
            M.set_device_parameter(
                conn,
                device_id=device_id,
                name=name,
                value_display=value_display,
                value_normalized=value_normalized,
                value_items=value_items,
                value_raw=value_raw,
                actor=actor,
                request_id=request_id,
                reason=reason,
            )
        # SYN-2D9K: prune device_parameters orphaned by a device-class change.
        # `params_dialed` is the authoritative full dialed set on capture, so a
        # DB param absent from it is a stale orphan — e.g. an Operator's params
        # lingering after the instrument was swapped to Analog. create_device
        # UPDATEs the existing row in place on a class change (reusing device_id),
        # so the old class's params are never CASCADE-deleted; the upsert above
        # never removes them; and the soft `--reset` deliberately preserves the
        # device tables. Mirror the pull path's drop-stale reconcile
        # (sync/pull/devices.py). Tri-state, exactly as for sidechain sources
        # above: snapshot SILENCE (no `params_dialed` key) is "no opinion, keep
        # whatever the DB holds"; a PRESENT mapping (even an explicit empty one)
        # is authoritative and clears any DB param not in it.
        if "params_dialed" in d:
            dialed = d["params_dialed"] or {}
            for row in Q.get_device_parameters(conn, device_id):
                if row["name"] not in dialed:
                    M.remove_device_parameter(
                        conn,
                        device_id=device_id,
                        name=row["name"],
                        actor=actor,
                        request_id=request_id,
                        reason=reason,
                    )
        # SNP-2H9F: nested-param overrides on a preset-seeded device. A flat list
        # of {path, name, value[, normalized][, value_items]} that keeps
        # preset_query intact — push re-asserts each at its NodeAddr path after the
        # preset loads (no chain creation, so the preset's waveform/samples
        # survive). Mutually exclusive with `chains`: `chains` authors/dumps the
        # nested tree, while `param_overrides` overrides params on the
        # preset-instantiated tree in place — carrying both is contradictory.
        overrides = d.get("param_overrides")
        nested = d.get("chains")
        if overrides and nested:
            raise ValueError(
                f"snapshot device {d.get('name')!r} carries both `chains` and "
                "`param_overrides` — they are contradictory representations "
                "(`param_overrides` overrides params on a preset-loaded nested "
                "tree in place; `chains` authors/dumps the tree). Author one."
            )
        if overrides:
            M.replace_device_param_overrides(
                conn,
                device_id=device_id,
                overrides=[
                    _override_entry_for_replay(o, device_name=d.get("name"))
                    for o in overrides
                ],
                actor=actor,
                request_id=request_id,
                reason=reason,
            )
        if nested:
            if d["class"] not in RACK_CLASS_NAMES:
                raise ValueError(
                    f"snapshot device {d.get('name')!r} carries `chains` but "
                    f"class {d['class']!r} is not a rack "
                    f"({sorted(RACK_CLASS_NAMES)})"
                )
            _replay_rack_chains(
                conn,
                rack_device_id=device_id,
                chains_array=nested,
                actor=actor,
                request_id=request_id,
                reason=reason,
                sidechain_pending=sidechain_pending,
            )
        # M1-C: Drum Rack pad mapping. Each Drum Rack may carry a
        # `drum_pads` array captured via `ableton_device(action='pad_info')`:
        # ``[{chain_name: str, midi_note: int}, ...]``. Replay persists into
        # `drum_pad_mappings` so the song's generators can resolve
        # ``load_kit(...).kick`` to the kit's actual MIDI note.
        # Arc 4 / D4: identity check uses the browser display name
        # ``"Drum Rack"`` (post-D4 ``snapshot.class`` semantics).
        pads = d.get("drum_pads")
        if pads:
            if d["class"] != "Drum Rack":
                raise ValueError(
                    f"snapshot device {d.get('name')!r} carries `drum_pads` "
                    f"but class {d['class']!r} is not 'Drum Rack' — "
                    "pad_info only applies to Drum Racks"
                )
            M.replace_drum_pad_mappings(
                conn,
                device_id=device_id,
                mappings=[
                    {
                        "chain_name": str(p.get("chain_name", p.get("name", ""))),
                        "midi_note": int(p["midi_note"] if "midi_note" in p else p["note"]),
                    }
                    for p in pads
                ],
                actor=actor,
                request_id=request_id,
                reason=reason,
            )


def _replay_rack_chains(
    conn: sqlite3.Connection,
    *,
    rack_device_id: str,
    chains_array: list[dict[str, Any]],
    actor: str,
    request_id: str | None,
    reason: str | None,
    sidechain_pending: list[tuple[str, str | None, str | None]],
) -> None:
    """Insert each nested chain under `rack_device_id` and recurse into the
    chain's devices — which may themselves be racks, recursing again to
    arbitrary depth (DEEP-RACK-ADDR). `sidechain_pending` threads through the
    recursion so a nested device's sidechain source is collected too (BAK-3M9T).

    Each entry: ``{chain_index: int>=1, name: str (optional), devices: [...]}``.
    The chain row's `position` matches W6-I/J's 1-based `chain_index` on the
    wire; top-level chains use `position=0` so the two address spaces don't
    collide.
    """
    for chain in chains_array:
        if "chain_index" not in chain:
            raise ValueError(
                f"snapshot nested chain missing 'chain_index': {chain!r}"
            )
        ci = int(chain["chain_index"])
        if ci < 1:
            raise ValueError(
                f"snapshot nested chain chain_index must be >= 1, got {ci}"
            )
        nested_chain_id = M.create_device_chain(
            conn,
            parent_rack_device_id=rack_device_id,
            position=ci,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        # NODE-ADDR Chunk C + F: apply the chain's authored properties (per-drum
        # choke/out_note + per-chain mixer mute/solo/volume/pan). Passed
        # explicitly (None when the snapshot omitted them) so a re-replay of a
        # snapshot that DROPPED a prop clears the stale DB value — replay is
        # idempotent and the snapshot is the source of truth.
        M.set_chain_properties(
            conn,
            chain_id=nested_chain_id,
            choke_group=chain.get("choke_group"),
            out_note=chain.get("out_note"),
            mute=chain.get("mute"),
            solo=chain.get("solo"),
            volume=chain.get("volume"),
            pan=chain.get("pan"),
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        _replay_devices(
            conn,
            chain_id=nested_chain_id,
            devices_array=chain.get("devices") or [],
            actor=actor,
            request_id=request_id,
            reason=reason,
            sidechain_pending=sidechain_pending,
        )


def _mixer_from_snapshot(t: dict[str, Any]) -> dict[str, Any]:
    """Pick the mixer fields out of a snapshot track dict, normalizing key names
    (`panning` -> `pan`) and skipping fields the snapshot didn't set."""
    out: dict[str, Any] = {}
    if "volume" in t:
        out["volume"] = _norm_vol(t["volume"])
    if "panning" in t:
        out["pan"] = _norm_pan(t["panning"])
    elif "pan" in t:
        out["pan"] = _norm_pan(t["pan"])
    if "mute" in t:
        out["mute"] = _norm_bool(t["mute"])
    if "solo" in t:
        out["solo"] = _norm_bool(t["solo"])
    if "arm" in t:
        out["arm"] = _norm_bool(t["arm"])
    if "color" in t and t["color"] is not None:
        out["color"] = int(t["color"])
    return out


def replay_capture(
    conn: sqlite3.Connection,
    snapshot: dict[str, Any],
    *,
    song_name: str,
    song_title: str | None = None,
    song_key: str | None = None,
    timing_mode: str = "native",
    actor: str = "sync",
    request_id: str | None = None,
    reason: str | None = None,
    allow_stale_snapshot: bool = False,
) -> str:
    """Replay a snapshot into a song in the DB. Returns the song_id.

    BAK-7D2V — pull-durability guard: if the DB already holds live edits
    pulled via `/ableton-pull` (events under a `requests.kind='pull'` request)
    that are NEWER than the snapshot's `captured_at`, this replay would
    silently revert them — so it raises :class:`StaleSnapshotError` before
    mutating anything. Pass ``allow_stale_snapshot=True`` (scaffolded build.py:
    ``--force-replay``) to consciously revert; re-capturing the snapshot is the
    durable fix. Snapshots without a `captured_at` stamp (pre-BAK-7D2V) warn
    instead of refusing — see `_guard_stale_snapshot` for the full matrix.

    W12-A: replay is idempotent — every underlying mutator (create_song,
    create_track, create_return, create_device_chain, create_device,
    set_device_parameter) is upsert-shaped. Re-replay onto an existing
    song updates rows whose state changed (snapshot edits) and is a no-op
    for unchanged rows. The prior "song already exists, raise" guard
    pre-dated mutator idempotency and is no longer needed; the actor='sync'
    threading still distinguishes pulled state from build-owned state for
    tombstone-time semantics.

    The mix layout IS replayed: tracks/returns/sends/mixer AND the full device
    tree — top-level devices, nested rack chains (`_replay_rack_chains`, depth-N),
    device parameters, and per-DrumChain props (choke_group/out_note). Notes/clips
    and the score-half (tempo/time-signature/sections/cue points) are NOT populated
    by replay — build.py authors those alongside the captured mix.

    SNP-8R4K chunk 2 — build-time migration trigger: if the snapshot predates
    the clean-at-rest contract (unstamped/old version, or still carrying
    analyzer device entries), emit a warning pointing at the migrate command.
    Replay/build is READ-ONLY on source files — chunk 1's `_replay_devices`
    already strips analyzer rows so the DB is correct either way; this is the
    one-line nudge to clean the committed FILE, not an auto-rewrite.
    """

    if snapshot_needs_migration(snapshot):
        analyzer_count = sum(
            _parent_analyzer_count(p)
            for p in (snapshot.get("tracks") or []) + (snapshot.get("returns") or [])
        )
        if analyzer_count:
            detail = f"{analyzer_count} analyzer device entr" + (
                "y" if analyzer_count == 1 else "ies"
            )
        else:
            detail = "unstamped/pre-SNP-8R4K"
        warnings.warn(
            f"replay_capture: snapshot predates SNP-8R4K ({detail}) — analyzer "
            "rows are ignored on build (the DB is clean either way), but the "
            "committed snapshot file is still dirty at rest. Run "
            '`"<python>" -m hallucinote.cli capture migrate '
            "<captured_session.json>` "
            "to clean + version-stamp the committed file.",
            UserWarning,
            stacklevel=2,
        )

    # BAK-7D2V: the guard must run BEFORE the first mutation (create_song is
    # itself an upsert that touches the song row). A song that doesn't exist
    # yet cannot have pulled state, so the guard only applies to re-replays.
    existing_song = Q.get_song_by_name(conn, song_name)
    if existing_song is not None:
        _guard_stale_snapshot(
            conn,
            snapshot,
            song_id=existing_song["id"],
            song_name=song_name,
            allow_stale_snapshot=allow_stale_snapshot,
        )

    song_id = M.create_song(
        conn,
        name=song_name,
        title=song_title,
        key=song_key,
        timing_mode=timing_mode,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )

    # BAK-3M9T: device sidechain sources, collected during _replay_devices and
    # applied after the full track loop (resolution needs the full track_ids_by_name).
    sidechain_pending: list[tuple[str, str | None, str | None]] = []

    song_block = snapshot.get("song") or {}
    master = song_block.get("master")
    if master:
        # Master is stored as a track row with the sentinel `track_index=0`.
        # Live's master strip has no real index, but the schema requires one.
        # Replay enforces `track_index >= 1` for non-master tracks below so the
        # 0 sentinel is unique within a song.
        master_id = M.create_track(
            conn,
            song_id=song_id,
            track_index=0,
            name="Master",
            instrument_uri=None,
            kind="master",
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        master_mixer = _mixer_from_snapshot(master)
        if master_mixer:
            M.set_track_mixer(
                conn,
                track_id=master_id,
                actor=actor,
                request_id=request_id,
                reason=reason,
                **master_mixer,
            )
        # SNP-4K7M — master device chain. The master is a track row, so its
        # device chain hangs off `parent_track_id` exactly like a regular
        # track's (the mutator is kind-agnostic). DEV-6M2K already pushes master
        # devices; this closes the authorship middle so a master Limiter / EQ
        # declared in build.py round-trips. Analyzer rows are filtered upstream
        # (compile_snapshot / migrate) so they never reach here.
        if master.get("devices"):
            master_chain_id = M.create_device_chain(
                conn,
                parent_track_id=master_id,
                actor=actor,
                request_id=request_id,
                reason=reason,
            )
            _replay_devices(
                conn,
                chain_id=master_chain_id,
                devices_array=master["devices"],
                actor=actor,
                request_id=request_id,
                reason=reason,
                sidechain_pending=sidechain_pending,
            )

    return_ids_by_name: dict[str, str] = {}
    stripped_pairs: list[tuple[str, str]] = []
    for r in snapshot.get("returns") or []:
        # W4-C: strip Live's `<letter>-` slot prefix on the way into the DB.
        # The snapshot's `t["sends"]` is keyed by the SAME prefixed names
        # Live reports, so we strip on the lookup side too (below).
        # SYN-RENDER-RELINK: also strip a render-appended ` | HallucinoteAnalyzer`
        # suffix so a snapshot taken post-render doesn't store the dirty name.
        stripped_name = normalize_live_return_name(r["name"])
        if stripped_name != r["name"]:
            stripped_pairs.append((r["name"], stripped_name))
        rid = M.create_return(
            conn,
            song_id=song_id,
            name=stripped_name,
            position=int(r["index"]),
            volume=_norm_vol(r.get("volume")),
            pan=_norm_pan(r.get("panning", r.get("pan"))),
            color=int(r["color"]) if r.get("color") is not None else None,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        return_ids_by_name[stripped_name] = rid
        if r.get("devices"):
            return_chain_id = M.create_device_chain(
                conn,
                parent_return_id=rid,
                actor=actor,
                request_id=request_id,
                reason=reason,
            )
            _replay_devices(
                conn,
                chain_id=return_chain_id,
                devices_array=r["devices"],
                actor=actor,
                request_id=request_id,
                reason=reason,
                sidechain_pending=sidechain_pending,
            )

    if stripped_pairs:
        pretty = ", ".join(f"{orig!r} -> {stripped!r}" for orig, stripped in stripped_pairs)
        warnings.warn(
            "replay_capture: stripped Live's <letter>- slot prefix from "
            f"{len(stripped_pairs)} return name(s): {pretty}. The DB stores "
            "SUFFIX-only return names (W4-C convention) — hand-authored "
            "snapshots should use the stripped form, and build.py lookups "
            "(Q.get_return_by_name) should pass the stripped form too. See "
            "docs/snapshot-schema.md ('Return names: stored stripped').",
            UserWarning,
            stacklevel=2,
        )

    track_ids_by_name: dict[str, str] = {}
    for t in snapshot.get("tracks") or []:
        track_type = t.get("type", "midi")
        if track_type not in _VALID_TRACK_TYPES:
            raise ValueError(
                f"track {t.get('name')!r}: type {track_type!r} not in "
                f"{sorted(_VALID_TRACK_TYPES)}"
            )
        idx = int(t["index"])
        if idx < 1:
            # 0 is reserved for the master sentinel; Live's tracks are 1-based.
            raise ValueError(
                f"track {t.get('name')!r}: index {idx} must be >= 1 "
                "(0 is reserved for the master sentinel)"
            )
        tid = M.create_track(
            conn,
            song_id=song_id,
            track_index=idx,
            name=t["name"],
            instrument_uri=t.get("instrument_uri"),
            kind=track_type,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        track_ids_by_name[t["name"]] = tid
        mixer = _mixer_from_snapshot(t)
        if mixer:
            M.set_track_mixer(
                conn,
                track_id=tid,
                actor=actor,
                request_id=request_id,
                reason=reason,
                **mixer,
            )
        for return_name, level in (t.get("sends") or {}).items():
            if level is None:
                continue
            # W4-C: the snapshot's send map is keyed by Live's prefixed names;
            # the return_ids_by_name dict is keyed by stripped names, so we
            # strip here too for consistent lookup. SYN-RENDER-RELINK: normalize
            # the analyzer suffix too so a post-render snapshot's sends still bind.
            target = return_ids_by_name.get(normalize_live_return_name(return_name))
            if target is None:
                raise ValueError(
                    f"track {t['name']!r} sends to return {return_name!r} "
                    "which is not defined in snapshot['returns']"
                )
            M.set_send_level(
                conn,
                from_track_id=tid,
                to_return_id=target,
                level=float(level),
                actor=actor,
                request_id=request_id,
                reason=reason,
            )
        if t.get("devices"):
            track_chain_id = M.create_device_chain(
                conn,
                parent_track_id=tid,
                actor=actor,
                request_id=request_id,
                reason=reason,
            )
            _replay_devices(
                conn,
                chain_id=track_chain_id,
                devices_array=t["devices"],
                actor=actor,
                request_id=request_id,
                reason=reason,
                sidechain_pending=sidechain_pending,
            )

    # BAK-3M9T: apply each device's sidechain source now that every track exists.
    # The source is stored by surface name (never a per-build UUID), resolved here
    # against this song's tracks (the source is always a track — see
    # set_device_sidechain / plan_pull_device_sidechain). Only devices whose
    # snapshot entry DECLARED `sidechain_source` reach this list (snapshot silence
    # is "no opinion", not "clear" — see _replay_devices above); an explicit null
    # source value DOES clear, idempotently. The snapshot is authoritative for what
    # it declares, never for what it omits.
    for device_id, source_name, channel in sidechain_pending:
        if source_name is None:
            M.set_device_sidechain(
                conn, device_id=device_id, source_track_id=None, channel=None,
                actor=actor, request_id=request_id, reason=reason,
            )
            continue
        source_track_id = track_ids_by_name.get(source_name)
        if source_track_id is None:
            raise ValueError(
                f"device sidechain source {source_name!r} is not a track defined "
                "in snapshot['tracks'] — cannot resolve the reference (capture "
                "filters unresolvable sources; check a hand-authored source name)"
            )
        M.set_device_sidechain(
            conn, device_id=device_id, source_track_id=source_track_id,
            channel=channel, actor=actor, request_id=request_id, reason=reason,
        )

    return song_id


# ---------------------------------------------------------------------------
# Capture-plan (Ableton -> snapshot dict)
# ---------------------------------------------------------------------------
# `assemble_snapshot_via_probes` (above) is the deterministic in-code capture;
# `capture_plan` documents the same probe sequence for a hand-driven / first
# capture. `compile_snapshot` assembles the JSON dict from already-gathered MCP
# probe results (used by both the in-code walker and any manual assembly).


def capture_plan() -> list[dict[str, str]]:
    """List the MCP probe calls the agent should run to populate a snapshot.

    Returns a sequence of `{tool, purpose}` records. The agent executes each,
    accumulates the results, and hands them to `compile_snapshot`.

    Chunk 3 baseline: tempo/master/returns/tracks/sends. Chunk 4a adds top-
    level device chain + per-device dialed parameter probes. W7-B adds the
    nested-rack chain walk: for every rack device returned in a track's or
    return's top-level chain, probe `get_device_chains` to capture one level
    of nested chains and their devices.
    """
    return [
        {"tool": "ableton_session(action='info')",
         "purpose": "global state: tempo, signature, master volume/pan, track counts"},
        {"tool": "ableton_device(action='list', target='master')",
         "purpose": "SNP-4K7M: the master's top-level device chain (kind + "
                    "display_name + position), attached as `song.master.devices` "
                    "— mirrors a track's device chain so a master Limiter/EQ "
                    "round-trips. Probe get_parameters per master device as for "
                    "tracks; the HallucinoteAnalyzer is dropped at compile time."},
        {"tool": "ableton_return(action='list')",
         "purpose": "return tracks: name + volume + pan per return; "
                    "chunk 4a: include each return's top-level device chain"},
        {"tool": "ableton_track(action='info')",
         "purpose": "per-track: name, type, volume, pan, mute/solo/arm, "
                    "top-level device chain (kind + display_name + position) "
                    "— loop over tracks"},
        {"tool": "ableton_track(action='get_sends')",
         "purpose": "per-track: sends map keyed by return name (loop over tracks)"},
        {"tool": "ableton_device(action='get_parameters')",
         "purpose": "per-device: dialed parameter map "
                    "(name -> {value, normalized}) — loop over each device"},
        {"tool": "ableton_device(action='get_device_chains')",
         "purpose": "per-rack-device: the FULL nested chain tree + their "
                    "devices. Emit for every device whose probed "
                    f"`class_display_name` is in {sorted(RACK_CLASS_NAMES)} "
                    "(Arc 4 / D4 — was `class_name` in {DrumGroupDevice, "
                    "InstrumentGroupDevice, AudioEffectGroupDevice} pre-D4; "
                    "now keyed off Live's class_display_name to match the "
                    "post-D4 snapshot.class convention). The agent attaches "
                    "the result as the device's `chains` field on the "
                    "snapshot. DO NOT emit a `_note` placeholder ('Rack — "
                    "internal chain instruments not captured', etc.) on "
                    "rack devices any more — `get_device_chains` returns the "
                    "whole nested tree in ONE call (depth-N) and replay "
                    "RECURSES into rack-in-rack (NODE-ADDR Chunk B lifted the "
                    "former W7-B one-level cap; replay no longer raises). For "
                    "nested racks prefer the deterministic `capture execute`, "
                    "which walks the tree in code."},
        {"tool": "ableton_device(action='pad_info')",
         "purpose": "per-Drum-Rack: pad layout (midi_note + chain_name per "
                    "non-empty pad). M1-C. Emit ONLY for devices whose "
                    "probed `class_display_name` is 'Drum Rack' (Arc 4 / "
                    "D4 — was class_name 'DrumGroupDevice' pre-D4). The "
                    "agent attaches the result as the device's `drum_pads` "
                    "field on the snapshot: ``[{midi_note: int, chain_name: "
                    "str}, ...]``. Replay persists into `drum_pad_mappings` "
                    "so songs can "
                    "use `hallucinote.kits.load_kit(conn, device_id)` to author kit-"
                    "portable drum patterns instead of GM-assumed MIDI notes."},
    ]


def compile_snapshot(
    *,
    session_info: dict[str, Any],
    returns: list[dict[str, Any]],
    tracks: list[dict[str, Any]],
    browser_paths: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble a snapshot dict from raw MCP probe outputs.

    Inputs are already-shaped dicts:
      session_info = {tempo, signature, master: {volume, panning}, ...}
      returns      = [{index, name, volume, panning, ...}, ...]
      tracks       = [{index, name, type, volume, panning, mute, solo, arm,
                        sends: {return_name: level, ...}, ...}, ...]

    Output is normalized to the snapshot schema documented in this module.
    Devices/clips on inputs are preserved verbatim; replay ignores them.

    `browser_paths` (Arc 7-tail / E3, snapshot-write side of W13-A v1.0):
    optional list of load records the caller accumulated by reading each
    `ableton_device(action='load')` response's `resolved_path`. Each record
    is `{track_index|return_index: int, device_index: int, browser_path:
    [str, ...]}`. When supplied, the function injects `browser_path` into
    the matching top-level device entry on the assembled snapshot so the
    cross-machine fallback identity round-trips through capture.

    SNP-8R4K — analyzer exclusion (THE off-by-one fix): the
    HallucinoteAnalyzer is measurement infrastructure, not authored content.
    Every parent's `devices` array is filtered to drop `is_analyzer_device`
    entries before assembly, and each survivor's `index` is re-assigned its
    1-based rank among survivors — NEVER the raw Live chain index. So an
    interleaved analyzer can never shift an authored device's position, and
    the analyzer (and its M4L params) never enters the snapshot. Browser-path
    injection runs AFTER the densify so its `device_index` records address the
    renumbered positions.
    """
    returns = [_exclude_analyzer_from_parent(r) for r in returns]
    tracks = [_exclude_analyzer_from_parent(t) for t in tracks]
    # SNP-4K7M — the master carries an optional `devices` array now (probed from
    # the master chain), so it gets the same analyzer strip + densify as tracks
    # and returns. None / device-less masters pass through unchanged.
    master_block = session_info.get("master")
    if master_block:
        master_block = _exclude_analyzer_from_parent(master_block)
    snapshot = {
        # SNP-8R4K chunk 2 — every compiled snapshot carries the schema version
        # so a consumer (and the at-rest cleanup) can tell a fresh capture from
        # a pre-SNP-8R4K one without inspecting device arrays.
        "snapshot_version": SNAPSHOT_SCHEMA_VERSION,
        # BAK-7D2V — capture-time stamp in the events.ts shape; the replay-side
        # pull-durability guard compares pulled events against it, and a fresh
        # capture updating it is exactly what disarms the guard. Deliberately
        # NOT back-stamped by migrate_snapshot (that would defeat the guard).
        "captured_at": utc_now_eventlike(),
        "song": {
            "tempo": session_info.get("tempo"),
            "signature": session_info.get("signature"),
            "master": master_block,
        },
        "returns": returns,
        "tracks": tracks,
    }
    if browser_paths:
        inject_browser_paths(snapshot, browser_paths)
    return snapshot


def _exclude_analyzer_from_parent(parent: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a snapshot parent (track / return) whose top-level
    `devices` array has the HallucinoteAnalyzer dropped and surviving devices
    densely renumbered (`index` = 1-based rank among survivors). SNP-8R4K R3/R5.

    Position-independent by construction: correct whether the analyzer is last
    or interleaved. Parents without a `devices` array pass through unchanged.
    Each surviving device entry is shallow-copied before its `index` is
    rewritten so the caller's input dicts aren't mutated.
    """
    devices = parent.get("devices")
    if not devices:
        return parent
    survivors = [d for d in devices if not is_analyzer_device(d)]
    renumbered = [
        {**d, "index": rank}
        for rank, d in enumerate(survivors, start=1)
    ]
    return {**parent, "devices": renumbered}


# ---------------------------------------------------------------------------
# Deterministic capture (Live -> snapshot dict, in code) — NODE-ADDR Chunk B
# ---------------------------------------------------------------------------
# `assemble_snapshot_via_probes` walks the live set IN CODE over the bridge that
# push/pull already use, replacing the agent-orchestrated `capture_plan` recipe
# (the agent ran the probes by hand and assembled the dict). It is the read-side
# acquisition the params-durability gap was missing: top-level AND nested device
# parameters are probed at every depth via NodeAddr `path` (Chunk A froze the
# address; this consumes it), so a depth-2 dialed param survives `/song-snapshot`
# without saving the .als. The transport is injected as a high-level `probe`
# callable so this engine module stays free of any `hallucinote_mcp` import
# (dependency direction is MCP→engine; see analyzer_identity) and so tests drive
# it with a fake — `tools/capture_cli.py` builds the real `probe` from
# `client.send`.

# OQ5 default-filter tolerance: a param within this of its intrinsic
# `default_value` is treated as "at default" and dropped from `params_dialed`
# (it is not dialed). Mirrors the pull diff's _FLOAT_EPS (~0.1% of full scale).
_CAPTURE_DEFAULT_EPS = 1e-3


def _format_signature(sig: Any) -> str | None:
    """Render the probe's ``{numerator, denominator}`` signature as the
    snapshot's ``"n/d"`` string (informational field; the score chunk's
    time_signature_map owns the authoritative meter). Returns None when the
    probe didn't carry a usable signature."""
    if isinstance(sig, str):
        return sig
    if isinstance(sig, dict):
        num = sig.get("numerator")
        den = sig.get("denominator")
        if num is not None and den is not None:
            return f"{int(num)}/{int(den)}"
    return None


def _snapshot_param_entry(p: dict[str, Any]) -> dict[str, Any] | None:
    """Translate one ``get_parameters`` probe entry into a ``params_dialed``
    entry, applying the OQ5 default-value filter. Returns ``None`` for a param
    sitting at its intrinsic default (it is not *dialed* — don't store it).

    The default filter is what lets capture record the live set wholesale yet
    persist only the authored deltas:
      * ``value`` within ``_CAPTURE_DEFAULT_EPS`` of ``default_value`` -> drop.
      * ``default_value`` ABSENT (Live raises on some quantized params — the
        handler omits it, design §1b fallback) -> ALWAYS capture (can't prove
        it's at default, so keep it; the always-capture minority).

    Shape matches what `_replay_devices` consumes: ``value`` is the DISPLAY
    string (replay stores ``value_display = str(value)``) and ``normalized`` is
    the [0, 1] form (omitted for enum/constant-range params, where there is no
    continuous form — replay then stores ``value_normalized = NULL``). Computed
    via the single-source `normalize_param_value`, so a captured-then-replayed
    param lands the same DB row a pull would write.

    DEV-4P7R: a non-enum param whose raw range != [0,1] instead gets
    ``value_raw`` (Live's own ``param.value``) — the only channel that round-trips
    for it (normalized is pushed AS raw so it mis-dials, and a step-list display
    like LFO S. Rate's "8..1/64" is non-monotonic so push refuses it). ``value``
    keeps the display string as a readable HINT; push prefers the raw.
    """
    raw = p.get("value")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return None  # non-numeric / missing value — nothing dialable to store
    default = p.get("default_value")
    if isinstance(default, (int, float)) and not isinstance(default, bool):
        if abs(float(raw) - float(default)) <= _CAPTURE_DEFAULT_EPS:
            return None  # at intrinsic default — not dialed
    is_enum = bool(p.get("is_enum", False))
    min_val = float(p.get("min", 0.0))
    max_val = float(p.get("max", 1.0))
    value_display = p.get("value_display")
    if not isinstance(value_display, str):
        # Probe omitted a display string (rare — a param with no str_for_value).
        # Store EMPTY, never str(raw): a bare number pushed as a *display* value
        # mis-dials a continuous param (its curve is inverted by the live
        # setter). Empty display makes push fall through to the normalized value
        # instead — exactly what the pull apply path does, so capture and pull
        # land the same DB row.
        value_display = ""
    entry: dict[str, Any] = {"value": value_display}
    if param_needs_raw_channel(min_val, max_val, is_enum):
        # The display string stays as a readable hint; value_raw is authoritative.
        entry["value_raw"] = float(raw)
        return entry
    normalized = normalize_param_value(float(raw), min_val, max_val, is_enum)
    if normalized is not None:
        entry["normalized"] = normalized
    if is_enum:
        items = p.get("value_items")
        if isinstance(items, (list, tuple)):
            entry["value_items"] = [str(i) for i in items]
    return entry


def _params_dialed_via_probe(
    probe, *, node: dict[str, Any],
) -> dict[str, Any]:
    """Probe one device's parameters (``detail='full'`` — the filter + the
    normalized math need min/max/is_enum) and assemble the filtered
    ``params_dialed`` map keyed by parameter name."""
    result = probe("ableton_device", "get_parameters", node=node, detail="full")
    out: dict[str, Any] = {}
    for p in result.get("parameters") or []:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        if not isinstance(name, str) or not name:
            continue
        entry = _snapshot_param_entry(p)
        if entry is not None:
            out[name] = entry
    return out


def _parent_node(parent_kind: str, parent_index: int | None) -> dict[str, Any]:
    """The NodeAddr ``parent`` block for a capture target (master is a
    singleton — no index)."""
    parent: dict[str, Any] = {"kind": parent_kind}
    if parent_kind != "master":
        parent["index"] = int(parent_index)
    return parent


def _parent_flat_args(parent_kind: str, parent_index: int | None) -> dict[str, Any]:
    """Flat addressing args for the not-yet-node-migrated probes
    (``ableton_device(action='list'|'get_device_chains'|'pad_info')``)."""
    if parent_kind == "track":
        return {"track_index": int(parent_index)}
    if parent_kind == "return":
        return {"return_index": int(parent_index)}
    return {"master": True}


def _chain_mixer_nondefault(
    chain_entry: dict[str, Any], key: str,
) -> float | None:
    """Non-default filter for a chain mixer float (volume / pan) — NODE-ADDR
    Chunk F. Returns the value only when it differs from the chain's intrinsic
    ``<key>_default`` (within ``_CAPTURE_DEFAULT_EPS``, the same tolerance the
    Chunk B param filter uses), else ``None``. With no default available (the
    rare param that raises on ``default_value``) it returns ``None`` — mixer
    state must not over-capture (a stored unity-volume on every chain is bloat),
    so "can't prove non-default" errs toward NOT capturing here, the opposite of
    the always-capture param fallback."""
    val = chain_entry.get(key)
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        return None
    # Never record state we cannot replay. A macro-mapped / locked chain mixer
    # reads back a perfectly good value and then refuses every write with
    # "Value cannot be set, the parameter is disabled" — so capturing it writes
    # a snapshot whose next push HALTS on a value-level no-op. (Witnessed on
    # Live's own 606 Core Kit: the closed/open hi-hat pads.) An absent flag means
    # "unknown", not "disabled" — older Live and odd params don't report it, and
    # treating unknown as disabled would silently drop real authored mix state.
    if chain_entry.get(f"{key}_is_enabled") is False:
        return None
    default = chain_entry.get(f"{key}_default")
    if not isinstance(default, (int, float)) or isinstance(default, bool):
        return None
    if abs(float(val) - float(default)) <= _CAPTURE_DEFAULT_EPS:
        return None
    return float(val)


def chain_authored_props(
    chain_entry: dict[str, Any],
) -> dict[str, int | float | None]:
    """Normalize a ``get_device_chains`` chain entry's authored properties to
    their AUTHORED form (NODE-ADDR Chunk C + F) — the single non-default filter
    shared by the snapshot-assemble (capture) and pull-diff paths.

    Chunk C — ``choke_group`` / ``out_note`` exist on a ``DrumChain`` only; a
    plain instrument-rack ``Chain`` has neither (both come back ``None``).
    Defaults filtered to ``None``: ``choke_group`` 0 ("no choke group") and an
    ``out_note`` equal to ``in_note`` (no transpose).

    Chunk F — per-chain mixer state on EVERY chain: ``mute`` / ``solo`` (stored
    1 only when set; unmuted/unsoloed is the default → ``None``) and ``volume`` /
    ``pan`` (stored only when off the chain's intrinsic param default, via
    :func:`_chain_mixer_nondefault`).

    Returns all six keys always present so a pull diff can clear any one back to
    its default. Mirrors the Chunk B param default-filter throughout.
    """
    choke = chain_entry.get("choke_group")
    out_note = chain_entry.get("out_note")
    in_note = chain_entry.get("in_note")
    choke_val = (
        int(choke)
        if isinstance(choke, int) and not isinstance(choke, bool) and choke != 0
        else None
    )
    out_val = (
        int(out_note)
        if isinstance(out_note, int) and not isinstance(out_note, bool)
        and out_note != in_note
        else None
    )
    return {
        "choke_group": choke_val,
        "out_note": out_val,
        "mute": 1 if chain_entry.get("is_muted") else None,
        "solo": 1 if chain_entry.get("is_soloed") else None,
        "volume": _chain_mixer_nondefault(chain_entry, "volume"),
        "pan": _chain_mixer_nondefault(chain_entry, "pan"),
    }


def _capture_nested_chains(
    probe, *, parent_kind: str, parent_index: int | None,
    top_device_index: int, chains_tree: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Walk a `get_device_chains` recursive tree (identity-only) and assemble
    the snapshot's ``chains`` array, probing ``get_parameters`` for every nested
    device at its NodeAddr ``path`` (the tree's ``device_path``, relative to the
    top-level rack). A nested device that is itself a rack carries its own
    ``chains`` in the tree — recurse, attaching its params too.
    """
    out: list[dict[str, Any]] = []
    for chain in chains_tree or []:
        ci = chain.get("chain_index")
        if not isinstance(ci, int) or ci < 1:
            continue
        devices_out: list[dict[str, Any]] = []
        for nd in chain.get("devices") or []:
            if is_analyzer_device(nd):
                continue
            entry = {
                "index": nd.get("position"),
                "class": nd.get("class_display_name") or nd.get("class_name"),
                "class_name": nd.get("class_name"),
                "name": nd.get("name", ""),
            }
            node = {
                "parent": _parent_node(parent_kind, parent_index),
                "terminal": "device",
                "device_index": top_device_index,
                "path": nd.get("device_path") or [],
            }
            params = _params_dialed_via_probe(probe, node=node)
            if params:
                entry["params_dialed"] = params
            if nd.get("is_rack") and nd.get("chains"):
                entry["chains"] = _capture_nested_chains(
                    probe, parent_kind=parent_kind, parent_index=parent_index,
                    top_device_index=top_device_index, chains_tree=nd["chains"],
                )
            devices_out.append(entry)
        chain_out: dict[str, Any] = {
            "chain_index": ci,
            "name": chain.get("name", ""),
            "devices": devices_out,
        }
        # NODE-ADDR Chunk C: a DrumChain's authored per-drum properties, stored
        # non-default-filtered (absent on plain chains and at the Live default).
        for prop, val in chain_authored_props(chain).items():
            if val is not None:
                chain_out[prop] = val
        out.append(chain_out)
    return out


def _device_sample_ref(
    listed: dict[str, Any], song_dir: Path | None,
) -> str | None:
    """The snapshot's ``audio_file`` reference for one listed device, or None.

    ``sample_file_path`` rides the chain listing for any device with a sample
    slot; its value is None for a slot nothing is loaded into, which is not a
    reference to record — an empty Simpler round-trips as a Simpler with no
    sample, exactly as it stands in Live.

    Rendered through :func:`hallucinote.paths.audio_file_ref` so a sample under
    the song directory is stored song-relative and a sample from the user's own
    library keeps its absolute path — the same two forms ``clips.audio_file``
    carries, read back by the same resolver at push time.
    """
    file_path = listed.get("sample_file_path")
    if not file_path:
        return None
    return audio_file_ref(song_dir, str(file_path))


def _capture_devices_for_parent(
    probe, *, parent_kind: str, parent_index: int | None = None,
    song_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Capture the full device chain (top-level + nested, to any depth) for one
    parent (track / return / master), in the snapshot ``devices`` shape.

    The analyzer is skipped here so it is never probed; `compile_snapshot`
    strips it again defensively (R3) and densifies positions.

    ``song_dir`` anchors a sampler's ``audio_file`` reference; without it every
    captured sample path is stored absolute, which still replays on this
    machine but does not travel.
    """
    listing = probe("ableton_device", "list", **_parent_flat_args(parent_kind, parent_index))
    out: list[dict[str, Any]] = []
    for d in listing.get("devices") or []:
        if is_analyzer_device(d):
            continue
        di = d.get("device_index")
        cls_display = d.get("class_display_name") or d.get("class_name")
        entry: dict[str, Any] = {
            "index": di,
            "class": cls_display,
            "class_name": d.get("class_name"),
            "name": d.get("name", ""),
        }
        sample_ref = _device_sample_ref(d, song_dir)
        if sample_ref is not None:
            entry["audio_file"] = sample_ref
        node = {
            "parent": _parent_node(parent_kind, parent_index),
            "terminal": "device",
            "device_index": di,
        }
        params = _params_dialed_via_probe(probe, node=node)
        if params:
            entry["params_dialed"] = params
        # BAK-3M9T: a top-level device's sidechain SOURCE — the one piece the
        # S/C On/Gain/Mix params can't carry (see set_device_sidechain). Probe the
        # input-routing surface (cheap: has_input_routing=False on non-capable
        # devices); `current_type` is the source track's display name. Stored raw
        # by surface name (+ channel) here; `_resolve_captured_sidechain_sources`
        # drops the own-track default and unrepresentable sources once every track
        # name is known. Top-level only, matching plan_pull_device_sidechain.
        routing = probe(
            "ableton_device", "get_input_routing",
            device_index=di, **_parent_flat_args(parent_kind, parent_index),
        )
        if routing.get("has_input_routing") and routing.get("current_type"):
            entry["sidechain_source"] = routing["current_type"]
            channel = routing.get("current_channel")
            if channel:
                entry["sidechain_source_channel"] = channel
        if cls_display in RACK_CLASS_NAMES:
            chains_resp = probe(
                "ableton_device", "get_device_chains",
                detail="full", device_index=di,
                **_parent_flat_args(parent_kind, parent_index),
            )
            entry["chains"] = _capture_nested_chains(
                probe, parent_kind=parent_kind, parent_index=parent_index,
                top_device_index=di, chains_tree=chains_resp.get("chains") or [],
            )
        if cls_display == "Drum Rack":
            pads_resp = probe(
                "ableton_device", "pad_info",
                device_index=di, **_parent_flat_args(parent_kind, parent_index),
            )
            pads = [
                {"chain_name": str(p.get("chain_name") or p.get("name") or ""),
                 "midi_note": int(p["note"] if "note" in p else p["midi_note"])}
                for p in (pads_resp.get("pads") or [])
                if (p.get("note") is not None or p.get("midi_note") is not None)
            ]
            if pads:
                entry["drum_pads"] = pads
        out.append(entry)
    return out


def _resolve_captured_sidechain_sources(snapshot: dict[str, Any]) -> None:
    """Filter the raw per-device ``sidechain_source`` references captured by
    `_capture_devices_for_parent`, in place, now that every track name is known.

    Three cases:
      * source == the device's OWN host track — Live's default input, not a
        sidechain. Dropped QUIETLY (there is nothing to re-apply).
      * source resolves to a real OTHER track in the snapshot — KEPT.
      * a genuine sidechain whose source is NOT a track in the snapshot (a return /
        master / external input, or a track absent from the capture) — cannot be
        represented as a surface-stable reference. Rather than drop it silently
        (the umbrella's anti-pattern, BAK-3M9T), it is dropped WITH a UserWarning
        that lists each dropped source so the operator can re-apply it in Live.

    Top-level devices only, matching what `_capture_devices_for_parent` emits.
    Scope (deliberate): this is the *sidechain* re-apply guarantee — a general
    "diff everything probed vs everything the schema represents" sweep is out of
    scope (open-ended; rule-of-three not met).
    """
    track_names = {t.get("name") for t in (snapshot.get("tracks") or [])}
    unrepresentable: list[str] = []

    def _filter(
        parent: dict[str, Any], *, own_track_name: str | None, parent_label: str,
    ) -> None:
        for d in parent.get("devices") or []:
            src = d.get("sidechain_source")
            if src is None:
                continue
            if src == own_track_name:
                d.pop("sidechain_source", None)  # own-track default, not a sidechain
                d.pop("sidechain_source_channel", None)
            elif src not in track_names:
                name = d.get("name") or d.get("class") or "device"
                unrepresentable.append(f"{name!r} on {parent_label} → {src!r}")
                d.pop("sidechain_source", None)
                d.pop("sidechain_source_channel", None)
            # else: a real cross-track sidechain — keep it.

    for t in snapshot.get("tracks") or []:
        _filter(t, own_track_name=t.get("name"),
                parent_label=f"track {t.get('name')!r}")
    for r in snapshot.get("returns") or []:
        _filter(r, own_track_name=None, parent_label=f"return {r.get('name')!r}")
    master = (snapshot.get("song") or {}).get("master")
    if master:
        _filter(master, own_track_name=None, parent_label="master")

    if unrepresentable:
        pretty = "; ".join(unrepresentable)
        warnings.warn(
            "capture: dropped sidechain source(s) that don't resolve to a track in "
            f"the snapshot — RE-APPLY MANUALLY in Live: {pretty}. Only a track can "
            "be a snapshot-stable sidechain source (the DB models the source as a "
            "track FK); a return / master / external source isn't carried. See "
            "docs/snapshot-schema.md ('sidechain_source').",
            UserWarning,
            stacklevel=2,
        )


def _capture_sends(probe, *, track_index: int) -> dict[str, Any]:
    """Probe a track's sends and reshape the probe's ``[{return_name, value}]``
    list into the snapshot's ``{return_name: level}`` map (replay strips the
    ``<letter>-`` slot prefix on lookup, so we store the name as Live reports it).
    Sends whose return name doesn't resolve are skipped (can't be keyed)."""
    resp = probe("ableton_track", "get_sends", track_index=track_index)
    sends: dict[str, Any] = {}
    for s in resp.get("sends") or []:
        name = s.get("return_name")
        if not isinstance(name, str) or not name:
            continue
        sends[name] = s.get("value")
    return sends


def assemble_snapshot_via_probes(
    probe, *, old_snapshot: dict[str, Any] | None = None,
    song_dir: Path | None = None,
) -> dict[str, Any]:
    """Deterministically build a full ``captured_session.json`` snapshot by
    walking the live set in code — the in-code successor to the
    agent-orchestrated `capture_plan` recipe (NODE-ADDR Chunk B).

    ``probe(tool, action, **params) -> result_dict`` is the injected transport:
    it issues one MCP call and returns the handler's result dict, raising on a
    tool-side failure (a partial snapshot would silently drop authored state, so
    capture aborts loudly rather than compiling half a set). `tools/capture_cli`
    builds the real `probe` over `hallucinote_mcp.client.send`; tests pass a fake.

    Captures the same surface `capture_plan` documented — session globals, the
    master chain, returns (+ mixer + devices), tracks (+ mixer + sends +
    devices) — but reaches device parameters at EVERY depth via NodeAddr `path`,
    closing the read-side acquisition gap. `old_snapshot`, when given, carries
    `browser_path` forward for devices whose identity still matches (capture
    probes don't surface it), exactly as `/song-snapshot` did by hand — and
    (SNP-2H9F) for a device the prior snapshot loaded via `preset_query`, carries
    that portable seed forward and rewrites the fresh `chains` dump into a flat
    `param_overrides` list, so a by-ear nested tweak survives a rebuild without
    dropping the preset's timbre or bloating the snapshot.

    ``song_dir`` is the directory the snapshot will be written beside. It
    anchors a sampler's captured sample to a song-relative ``audio_file``
    reference; omitted, such a path is stored absolute and stops travelling
    between machines.
    """
    info = probe("ableton_session", "info")
    master_mixer = info.get("master")
    master_block: dict[str, Any] | None = None
    if master_mixer:
        master_block = {
            "volume": master_mixer.get("volume"),
            "panning": master_mixer.get("panning"),
        }
        master_devices = _capture_devices_for_parent(
            probe, parent_kind="master", song_dir=song_dir,
        )
        if master_devices:
            master_block["devices"] = master_devices

    session_info = {
        "tempo": info.get("tempo"),
        "signature": _format_signature(info.get("signature")),
        "master": master_block,
    }

    returns_out: list[dict[str, Any]] = []
    listing = probe("ableton_return", "list")
    for r in listing.get("returns") or []:
        ri = r.get("return_index")
        rinfo = probe("ableton_return", "info", return_index=ri)
        entry: dict[str, Any] = {
            "index": ri,
            "name": rinfo.get("name", r.get("name")),
            "volume": rinfo.get("volume"),
            "panning": rinfo.get("panning"),
            "color": rinfo.get("color", r.get("color")),
        }
        devices = _capture_devices_for_parent(
            probe, parent_kind="return", parent_index=ri, song_dir=song_dir,
        )
        if devices:
            entry["devices"] = devices
        returns_out.append(entry)

    tracks_out: list[dict[str, Any]] = []
    track_count = int(info.get("track_count") or 0)
    for ti in range(1, track_count + 1):
        tinfo = probe("ableton_track", "info", track_index=ti)
        entry = {
            "index": ti,
            "name": tinfo.get("name"),
            "type": tinfo.get("kind", "midi"),
            "volume": tinfo.get("volume"),
            "panning": tinfo.get("panning"),
        }
        for flag in ("mute", "solo", "arm"):
            if flag in tinfo:
                entry[flag] = tinfo[flag]
        if tinfo.get("color") is not None:
            entry["color"] = tinfo["color"]
        sends = _capture_sends(probe, track_index=ti)
        if sends:
            entry["sends"] = sends
        devices = _capture_devices_for_parent(
            probe, parent_kind="track", parent_index=ti, song_dir=song_dir,
        )
        if devices:
            entry["devices"] = devices
        tracks_out.append(entry)

    snapshot = compile_snapshot(
        session_info=session_info, returns=returns_out, tracks=tracks_out,
    )
    _resolve_captured_sidechain_sources(snapshot)
    if old_snapshot is not None:
        preserve_browser_paths(old_snapshot, snapshot)
        # SNP-2H9F: a device the prior snapshot loaded via preset_query keeps its
        # portable seed + by-ear nested deltas (param_overrides) instead of the
        # fresh full chains dump (which drops the seed + the preset's timbre).
        preserve_preset_overrides(old_snapshot, snapshot)
    return snapshot


# ---------------------------------------------------------------------------
# At-rest snapshot migration (SNP-8R4K chunk 2 — State-1 clean-at-rest)
# ---------------------------------------------------------------------------
# Chunk 1 already makes a polluted snapshot *functionally* clean on the next
# build (`compile_snapshot` + `_replay_devices` both strip the analyzer and
# densify). This chunk cleans the committed `captured_session.json` FILE so the
# artifact itself stops carrying analyzer rows — strip + densify + stamp a
# version so the rewrite runs exactly once, and announce per parent what was
# stripped (never a silent rewrite). The migrate command (capture_cli) is the
# action; `replay_capture` emits the warning that points users at it.


def _parent_analyzer_count(parent: dict[str, Any]) -> int:
    """Number of `is_analyzer_device` entries in a parent's top-level `devices`
    array (0 if it has none / no array)."""
    return sum(1 for d in (parent.get("devices") or []) if is_analyzer_device(d))


def snapshot_needs_migration(snapshot: dict[str, Any]) -> bool:
    """True if `snapshot` predates SNP-8R4K's clean-at-rest contract and the
    one-time cleanup should run.

    Two independent triggers (either fires):
      * version: `snapshot_version` is missing or < SNAPSHOT_SCHEMA_VERSION
        (an unstamped or older snapshot).
      * pollution: any track or return `devices` array still carries an
        `is_analyzer_device` entry (a polluted snapshot — even one that has
        somehow been version-stamped — must still be cleaned).
    """
    version = snapshot.get("snapshot_version")
    if version is None or version < SNAPSHOT_SCHEMA_VERSION:
        return True
    parents = (snapshot.get("tracks") or []) + (snapshot.get("returns") or [])
    master = (snapshot.get("song") or {}).get("master")
    if master:
        parents = parents + [master]
    return any(_parent_analyzer_count(p) > 0 for p in parents)


def migrate_snapshot(snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Clean a committed snapshot at rest: drop `is_analyzer_device` entries +
    densely renumber survivors on every track and return, and stamp the schema
    version. Pure function — the input dict is never mutated.

    BAK-7D2V: this deliberately does NOT stamp `captured_at` on a legacy file.
    The content was captured at an unknown earlier time; stamping "now" would
    assert it is newer than pulled live edits it doesn't contain, silently
    defeating the replay-side pull-durability guard. Only a real capture
    (`compile_snapshot`) stamps.

    Returns ``(cleaned_snapshot, report)``. The report announces what was
    stripped so the rewrite is never silent::

        {
          "stripped": [{"parent": <name>, "kind": "track"|"return"|"master",
                        "removed": <count>}, ...],   # only parents with removals
          "total_removed": <int>,
          "version_before": <old version int or None>,
          "version_after": SNAPSHOT_SCHEMA_VERSION,
        }

    Reuses `_exclude_analyzer_from_parent` (the chunk-1 strip+densify helper) so
    the cleanup is identical to capture/replay — single source of truth, no
    reimplementation. SNP-4K7M: the master joins the strip too (it can now carry
    a device chain), so a master Limiter authored after a render is cleaned here
    exactly like a track/return chain.
    """
    stripped: list[dict[str, Any]] = []

    def _clean(parents: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        for parent in parents:
            removed = _parent_analyzer_count(parent)
            if removed:
                stripped.append({
                    "parent": parent.get("name"),
                    "kind": kind,
                    "removed": removed,
                })
            cleaned.append(_exclude_analyzer_from_parent(parent))
        return cleaned

    cleaned_tracks = _clean(snapshot.get("tracks") or [], "track")
    cleaned_returns = _clean(snapshot.get("returns") or [], "return")

    # SNP-4K7M — the master can carry a device chain too, so it joins the strip
    # (was intentionally skipped while the master had no device array).
    song = snapshot.get("song") or {}
    master = song.get("master")
    cleaned_master = master
    if master:
        removed = _parent_analyzer_count(master)
        if removed:
            stripped.append({
                "parent": master.get("name") or "Master",
                "kind": "master",
                "removed": removed,
            })
        cleaned_master = _exclude_analyzer_from_parent(master)

    # Shallow-copy the top level; `_exclude_analyzer_from_parent` already returns
    # fresh parent/device dicts for every array we rewrite (tracks/returns/master),
    # so the input dict and its sub-trees are never mutated.
    cleaned = dict(snapshot)
    cleaned["tracks"] = cleaned_tracks
    cleaned["returns"] = cleaned_returns
    if master is not None:
        cleaned_song = dict(song)
        cleaned_song["master"] = cleaned_master
        cleaned["song"] = cleaned_song
    version_before = snapshot.get("snapshot_version")
    cleaned["snapshot_version"] = SNAPSHOT_SCHEMA_VERSION

    report = {
        "stripped": stripped,
        "total_removed": sum(s["removed"] for s in stripped),
        "version_before": version_before,
        "version_after": SNAPSHOT_SCHEMA_VERSION,
    }
    return cleaned, report


# ---------------------------------------------------------------------------
# Browser-path injection / preservation (Arc 7-tail / E3, snapshot-write side)
# ---------------------------------------------------------------------------
# E3 (Arc 7-tail, 2026-05-22) shipped the READ side of W13-A v1.0:
# `ableton_device(action='load')` returns `resolved_path`, replay_capture
# consumes snapshot `browser_path` into `devices.browser_path_json`, push
# threads it back to the load handler as a fallback identity. The producer
# side — where the agent captures `resolved_path` from a fresh load and
# attaches it to the snapshot's device entry — lives here.
#
# Two surfaces:
#
# - `inject_browser_paths(snapshot, loads)` — used by `/song-pick-instruments`
#   (and any other load-driven flow) after `ableton_device(action='load')`.
#   The agent records each load's `resolved_path` into a list of records;
#   this helper writes them into the right device entries on the assembled
#   snapshot. Top-level devices only (track + return chains); nested rack
#   chain devices are out of scope for browser-path injection since no
#   current skill drives that path (and nested devices arrive with the rack
#   preset, so they need no per-device browser identity).
#
# - `preserve_browser_paths(old, new)` — used by `/song-snapshot` (the
#   refresh flow). Capture probes don't expose `browser_path` (Live doesn't
#   track each loaded device's browser origin), so without preservation
#   every refresh would silently drop the fallback identity for every
#   device. The helper copies `browser_path` from `old` to `new` for
#   devices whose identity matches (same parent index + position + class).
#   `browser_path` already present in `new` (e.g. just-loaded via
#   `inject_browser_paths`) wins over the old value.


def _attach_browser_path_to_device(
    parent: dict[str, Any],
    *,
    device_index: int,
    browser_path: list[str],
    parent_kind: str,
    parent_index: int,
) -> None:
    """Write `browser_path` onto the device at position `device_index` (1-based)
    in `parent["devices"]`. Raises if no such device exists — the caller
    passed a stale record."""
    devices = parent.get("devices") or []
    for d in devices:
        if int(d.get("index", -1)) == device_index:
            d["browser_path"] = list(browser_path)
            return
    raise ValueError(
        f"inject_browser_paths: no device at index={device_index} on "
        f"{parent_kind} {parent_index} (parent has "
        f"{len(devices)} device(s))"
    )


def inject_browser_paths(
    snapshot: dict[str, Any],
    loads: list[dict[str, Any]],
) -> None:
    """Attach `browser_path` to snapshot device entries the agent just loaded.

    Each load record (one per `ableton_device(action='load')` call the
    agent ran while assembling the snapshot):

      {"track_index":  int (>=1), "device_index": int (>=1),
       "browser_path": [str, ...]}
      OR
      {"return_index": int (>=1), "device_index": int (>=1),
       "browser_path": [str, ...]}

    `browser_path` is the value the MCP load handler returned as
    `resolved_path` — segments from the browser root key to the loaded
    item's leaf name. The push planner threads this onto subsequent loads
    as a fallback identity when the per-machine preset_uri stops resolving
    (different Live install, plugin moved between catalog versions).

    Mutates `snapshot` in place. Raises on malformed records or on records
    that don't match any device in the snapshot.
    """
    for record in loads:
        bp = record.get("browser_path")
        if not isinstance(bp, list) or not bp or not all(
            isinstance(s, str) and s for s in bp
        ):
            raise ValueError(
                "inject_browser_paths: each record must carry a non-empty "
                "browser_path list of non-empty strings; got "
                f"{bp!r} on record {record!r}"
            )
        if "device_index" not in record:
            raise ValueError(
                f"inject_browser_paths: record missing device_index: {record!r}"
            )
        device_index = int(record["device_index"])
        if device_index < 1:
            raise ValueError(
                f"inject_browser_paths: device_index must be >= 1, got "
                f"{device_index} on record {record!r}"
            )
        has_track = "track_index" in record
        has_return = "return_index" in record
        if has_track == has_return:
            raise ValueError(
                "inject_browser_paths: each record must carry exactly one of "
                f"track_index or return_index; got {record!r}"
            )
        if has_track:
            ti = int(record["track_index"])
            for t in snapshot.get("tracks") or []:
                if int(t.get("index", -1)) == ti:
                    _attach_browser_path_to_device(
                        t,
                        device_index=device_index,
                        browser_path=bp,
                        parent_kind="track",
                        parent_index=ti,
                    )
                    break
            else:
                raise ValueError(
                    f"inject_browser_paths: no track with index={ti} in "
                    "snapshot"
                )
        else:
            ri = int(record["return_index"])
            for r in snapshot.get("returns") or []:
                if int(r.get("index", -1)) == ri:
                    _attach_browser_path_to_device(
                        r,
                        device_index=device_index,
                        browser_path=bp,
                        parent_kind="return",
                        parent_index=ri,
                    )
                    break
            else:
                raise ValueError(
                    f"inject_browser_paths: no return with index={ri} in "
                    "snapshot"
                )


def _collect_browser_paths(
    snapshot: dict[str, Any],
) -> dict[tuple[str, int, int, Any], list[str]]:
    """Build an identity-keyed lookup of every top-level device that carries
    a `browser_path`. Key: (parent_kind, parent_index, device_index, class).
    The class is included so re-using an index slot with a different device
    (e.g. swap Operator for Wavetable at position 1) doesn't carry forward
    a stale path that no longer matches identity."""
    out: dict[tuple[str, int, int, Any], list[str]] = {}
    for t in snapshot.get("tracks") or []:
        if "index" not in t:
            continue
        ti = int(t["index"])
        for d in t.get("devices") or []:
            bp = d.get("browser_path")
            if not bp or "index" not in d:
                continue
            out[("track", ti, int(d["index"]), d.get("class"))] = list(bp)
    for r in snapshot.get("returns") or []:
        if "index" not in r:
            continue
        ri = int(r["index"])
        for d in r.get("devices") or []:
            bp = d.get("browser_path")
            if not bp or "index" not in d:
                continue
            out[("return", ri, int(d["index"]), d.get("class"))] = list(bp)
    return out


def preserve_browser_paths(
    old: dict[str, Any],
    new: dict[str, Any],
) -> None:
    """Copy `browser_path` from `old` snapshot to `new` for devices whose
    identity matches (same parent index + position + class).

    Used by `/song-snapshot` during refresh: capture probes don't expose
    `browser_path` (Live doesn't track each loaded device's browser
    origin), so without this preservation every refresh would silently
    drop the cross-machine fallback identity for every device.

    A `browser_path` already present on a `new` device wins (e.g. the
    flow just loaded a fresh device and `inject_browser_paths` attached
    its `resolved_path`). Position-or-class identity mismatch drops the
    old path silently — the device at that slot is a different one now.

    Mutates `new` in place.
    """
    old_paths = _collect_browser_paths(old)
    if not old_paths:
        return
    for t in new.get("tracks") or []:
        if "index" not in t:
            continue
        ti = int(t["index"])
        for d in t.get("devices") or []:
            if d.get("browser_path") or "index" not in d:
                continue
            key = ("track", ti, int(d["index"]), d.get("class"))
            if key in old_paths:
                d["browser_path"] = list(old_paths[key])
    for r in new.get("returns") or []:
        if "index" not in r:
            continue
        ri = int(r["index"])
        for d in r.get("devices") or []:
            if d.get("browser_path") or "index" not in d:
                continue
            key = ("return", ri, int(d["index"]), d.get("class"))
            if key in old_paths:
                d["browser_path"] = list(old_paths[key])


# ---------------------------------------------------------------------------
# SNP-2H9F: capture a preset device's nested deltas as param_overrides
# ---------------------------------------------------------------------------
# `assemble_snapshot_via_probes` dumps a full `chains` tree for EVERY rack and
# never carries `preset_query` forward (live probes don't surface a device's
# preset origin). For a device the prior snapshot loaded via `preset_query`, that
# dump drops the portable seed AND the preset's un-parameterizable timbre (a
# Wavetable waveform is not a DeviceParameter) and bloats. This post-compile
# transform — the read-side sibling of the replay/push paths — restores
# `preset_query` from the old snapshot and rewrites the fresh `chains` dump into a
# flat `param_overrides` list (the by-ear nested deltas), so the snapshot stays
# portable + small while the deep tweak survives a from-scratch rebuild.

# Authored per-chain props (NODE-ADDR Chunk C/F: choke/out_note/mixer state) live
# IN the chains structure and can't ride param_overrides (device params only). A
# preset device whose dump carries any keeps its full `chains` dump rather than
# lose them (a drum-rack-via-preset edge; the instrument-rack param case is the
# SNP-2H9F target).
_CHAIN_PROP_KEYS = ("choke_group", "out_note", "mute", "solo", "volume", "pan")


def _collect_preset_queries(
    snapshot: dict[str, Any],
) -> dict[tuple[str, int, int, Any], Any]:
    """Identity-keyed lookup of every top-level device carrying `preset_query`.
    Key shape matches `_collect_browser_paths` — (parent_kind, parent_index,
    device_index, class) — so a re-used slot with a different device doesn't
    carry forward a stale seed."""
    out: dict[tuple[str, int, int, Any], Any] = {}
    for parent_kind, parents in (("track", snapshot.get("tracks")),
                                 ("return", snapshot.get("returns"))):
        for p in parents or []:
            if "index" not in p:
                continue
            pidx = int(p["index"])
            for d in p.get("devices") or []:
                pq = d.get("preset_query")
                if pq is None or "index" not in d:
                    continue
                out[(parent_kind, pidx, int(d["index"]), d.get("class"))] = pq
    return out


def _chains_carry_props(chains: list[dict[str, Any]] | None) -> bool:
    """True if any chain (at any depth) in a captured dump carries an authored
    Chunk C/F per-chain prop — those can't be expressed as param_overrides."""
    for chain in chains or []:
        if any(k in chain for k in _CHAIN_PROP_KEYS):
            return True
        for dev in chain.get("devices") or []:
            if dev.get("chains") and _chains_carry_props(dev["chains"]):
                return True
    return False


def _flatten_chains_to_overrides(
    chains: list[dict[str, Any]] | None,
    prefix_path: list[dict[str, int]],
) -> list[dict[str, Any]]:
    """Flatten a captured `chains` tree into a `param_overrides` list — one entry
    per nested device's dialed param, carrying the NodeAddr descent `path` to that
    device (chain_index from the chain, device_position from the device's 1-based
    `index`). The params are already non-default-filtered by capture, so this is
    the by-ear delta set (SNP-2H9F; design §8 — over-captures the preset's own
    non-defaults until the bounded preset-cache lands)."""
    out: list[dict[str, Any]] = []
    for chain in chains or []:
        ci = chain.get("chain_index")
        if not isinstance(ci, int):
            continue
        for dev in chain.get("devices") or []:
            dp = dev.get("index")
            if not isinstance(dp, int):
                continue
            path = prefix_path + [{"chain_index": ci, "device_position": dp}]
            for name, p in (dev.get("params_dialed") or {}).items():
                entry: dict[str, Any] = {"path": path, "name": name,
                                         "value": p["value"]}
                if "normalized" in p:
                    entry["normalized"] = p["normalized"]
                if "value_items" in p:
                    entry["value_items"] = p["value_items"]
                # DEV-4P7R: carry the raw channel — a preset device's nested
                # quantized non-[0,1] param (the witness LFO S. Rate) is exactly
                # what param_overrides exists for; dropping it here would silently
                # revert the fix on the next /song-snapshot refresh.
                if "value_raw" in p:
                    entry["value_raw"] = p["value_raw"]
                out.append(entry)
            if dev.get("chains"):
                out.extend(_flatten_chains_to_overrides(dev["chains"], path))
    return out


def preserve_preset_overrides(
    old: dict[str, Any],
    new: dict[str, Any],
) -> None:
    """For each NEW top-level device whose matching OLD device was preset-seeded
    (carried `preset_query`), carry that seed forward and convert the fresh
    `chains` dump into a flat `param_overrides` list — dropping `chains` so the
    snapshot keeps the portable preset + the by-ear nested deltas without the
    preset's structure/timbre or the dump bloat (SNP-2H9F). Mutates `new`.

    Skips conversion (keeps the full `chains` dump, preset_query NOT carried) when
    the dump carries authored per-chain props, which can't ride param_overrides —
    a drum-rack-via-preset edge, flagged via a warning, not silently dropped."""
    old_presets = _collect_preset_queries(old)
    if not old_presets:
        return
    for parent_kind, parents in (("track", new.get("tracks")),
                                 ("return", new.get("returns"))):
        for parent in parents or []:
            if "index" not in parent:
                continue
            pidx = int(parent["index"])
            for d in parent.get("devices") or []:
                if "index" not in d:
                    continue
                key = (parent_kind, pidx, int(d["index"]), d.get("class"))
                preset = old_presets.get(key)
                if preset is None:
                    continue
                chains = d.get("chains")
                if chains and _chains_carry_props(chains):
                    warnings.warn(
                        f"capture: preset device {d.get('name')!r} on "
                        f"{parent_kind} {pidx} carries authored per-chain props "
                        "(choke/out_note/mixer) that param_overrides can't "
                        "express — keeping the full chains dump (its preset_query "
                        "is not carried forward; SNP-2H9F covers preset device "
                        "PARAMS, not preset drum-chain props).",
                        UserWarning,
                        stacklevel=2,
                    )
                    continue
                # Carry the portable seed forward (lost by the live walk).
                if "preset_query" not in d:
                    d["preset_query"] = preset
                if chains:
                    overrides = _flatten_chains_to_overrides(chains, [])
                    del d["chains"]
                    if overrides:
                        d["param_overrides"] = overrides


# ---------------------------------------------------------------------------
# Snapshot diff (W12-B)
# ---------------------------------------------------------------------------
# W12-B's `/song-snapshot` skill drives a fresh capture, then diffs the result
# against the on-disk `captured_session.json` so the user can see what changed
# before overwriting. The diff lives here (not in the skill body) so the
# matching logic is testable and the LLM doesn't have to re-derive it from a
# 50KB JSON every refresh.
#
# Identity rules:
#   - Returns matched by `index` (Live's 1-based return slot)
#   - Tracks matched by `index` (Live's 1-based track slot)
#   - Devices inside a chain matched by `index` within that chain
# Name drift is reported as a field_change, not as add/remove. Reordering
# Live's tracks moves the indices; we report that as removed-from-old-index
# + added-at-new-index rather than trying to track-by-name (Live allows
# duplicate track names, so name is not a reliable identity).
#
# Per-device dialed-param drift is diffed in full; nested rack chains are
# walked one level by this PREVIEW diff, reporting anything deeper as a single
# "nested_chains_subtree_changed" flag. That is a preview simplification only —
# replay (`_replay_rack_chains`) and push handle nested params at ARBITRARY
# depth (DEEP-RACK-ADDR), so a deep change is never lost, just not itemized in
# the operator-facing diff.


_MIXER_FIELDS = ("volume", "panning", "mute", "solo", "arm", "color")
_RETURN_FIELDS = ("name", "volume", "panning", "color")
_TRACK_IDENTITY_FIELDS = ("name", "type")
_DEVICE_IDENTITY_FIELDS = ("name", "class", "kind", "guess_uri")


def _field_diff(old: dict[str, Any], new: dict[str, Any], fields: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """Compare each named field in two dicts; return {field: {old, new}} entries
    where the value differs. Fields absent from one side are reported only when
    the other side has a non-None value (avoids spurious None-vs-missing churn)."""
    out: dict[str, dict[str, Any]] = {}
    for f in fields:
        o = old.get(f)
        n = new.get(f)
        if o == n:
            continue
        if o is None and n is None:
            continue
        out[f] = {"old": o, "new": n}
    return out


def _sends_diff(
    old_sends: dict[str, Any] | None,
    new_sends: dict[str, Any] | None,
) -> dict[str, Any]:
    """Diff two sends maps (return_name -> level). Returns
    {added: {name: level}, removed: {name: level}, changed: {name: {old, new}}}.
    Empty fields are omitted from the result."""
    old = old_sends or {}
    new = new_sends or {}
    added = {k: new[k] for k in new.keys() - old.keys()}
    removed = {k: old[k] for k in old.keys() - new.keys()}
    changed: dict[str, dict[str, Any]] = {}
    for k in old.keys() & new.keys():
        if old[k] != new[k]:
            changed[k] = {"old": old[k], "new": new[k]}
    out: dict[str, Any] = {}
    if added:
        out["added"] = added
    if removed:
        out["removed"] = removed
    if changed:
        out["changed"] = changed
    return out


def _params_diff(
    old_params: dict[str, Any] | None,
    new_params: dict[str, Any] | None,
) -> dict[str, Any]:
    """Diff two `params_dialed` maps. Each entry is `{value, normalized}`; an
    entry differs if either subfield differs."""
    old = old_params or {}
    new = new_params or {}
    added = {k: new[k] for k in new.keys() - old.keys()}
    removed = {k: old[k] for k in old.keys() - new.keys()}
    changed: dict[str, dict[str, Any]] = {}
    for k in old.keys() & new.keys():
        if old[k] != new[k]:
            changed[k] = {"old": old[k], "new": new[k]}
    out: dict[str, Any] = {}
    if added:
        out["added"] = added
    if removed:
        out["removed"] = removed
    if changed:
        out["changed"] = changed
    return out


def _devices_diff(
    old_devices: list[dict[str, Any]] | None,
    new_devices: list[dict[str, Any]] | None,
    _depth: int = 0,
) -> dict[str, Any]:
    """Diff two device arrays (top-level or nested-chain). Matches by `index`."""
    old = old_devices or []
    new = new_devices or []
    old_by_idx = {int(d["index"]): d for d in old if "index" in d}
    new_by_idx = {int(d["index"]): d for d in new if "index" in d}
    added = [new_by_idx[i] for i in sorted(new_by_idx.keys() - old_by_idx.keys())]
    removed = [old_by_idx[i] for i in sorted(old_by_idx.keys() - new_by_idx.keys())]
    changed: list[dict[str, Any]] = []
    for i in sorted(old_by_idx.keys() & new_by_idx.keys()):
        od = old_by_idx[i]
        nd = new_by_idx[i]
        entry: dict[str, Any] = {"index": i}
        fc = _field_diff(od, nd, _DEVICE_IDENTITY_FIELDS)
        if fc:
            entry["field_changes"] = fc
        pd = _params_diff(od.get("params_dialed"), nd.get("params_dialed"))
        if pd:
            entry["params"] = pd
        # Nested rack chains: the snapshot-refresh PREVIEW itemizes one level
        # and summarizes anything deeper as an opaque subtree change. This is a
        # preview simplification only — replay/push (DEEP-RACK-ADDR) materialize
        # nested params at any depth, so a deep change is never LOST, just not
        # spelled out field-by-field in the diff the operator sees.
        old_chains = od.get("chains")
        new_chains = nd.get("chains")
        if old_chains or new_chains:
            if _depth > 0:
                # Deeper-than-one-level nested chains: flag as opaque change.
                if old_chains != new_chains:
                    entry["nested_chains_subtree_changed"] = True
            else:
                cd = _chains_diff(old_chains, new_chains)
                if cd:
                    entry["chains"] = cd
        if len(entry) > 1:
            entry["name"] = nd.get("name", od.get("name"))
            changed.append(entry)
    out: dict[str, Any] = {}
    if added:
        out["added"] = added
    if removed:
        out["removed"] = removed
    if changed:
        out["changed"] = changed
    return out


def _chains_diff(
    old_chains: list[dict[str, Any]] | None,
    new_chains: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Diff two `chains` arrays (rack-device nested chains). Matches by
    `chain_index`. Each chain's devices are diffed at `_depth=1` — the
    snapshot-refresh preview itemizes one level and summarizes deeper subtrees
    opaquely (replay/push handle any depth; this is a preview simplification,
    not a data limit)."""
    old = old_chains or []
    new = new_chains or []
    old_by_idx = {int(c["chain_index"]): c for c in old if "chain_index" in c}
    new_by_idx = {int(c["chain_index"]): c for c in new if "chain_index" in c}
    added = [new_by_idx[i] for i in sorted(new_by_idx.keys() - old_by_idx.keys())]
    removed = [old_by_idx[i] for i in sorted(old_by_idx.keys() - new_by_idx.keys())]
    changed: list[dict[str, Any]] = []
    for i in sorted(old_by_idx.keys() & new_by_idx.keys()):
        oc = old_by_idx[i]
        nc = new_by_idx[i]
        entry: dict[str, Any] = {"chain_index": i}
        if oc.get("name") != nc.get("name"):
            entry["name_change"] = {"old": oc.get("name"), "new": nc.get("name")}
        dd = _devices_diff(oc.get("devices"), nc.get("devices"), _depth=1)
        if dd:
            entry["devices"] = dd
        if len(entry) > 1:
            changed.append(entry)
    out: dict[str, Any] = {}
    if added:
        out["added"] = added
    if removed:
        out["removed"] = removed
    if changed:
        out["changed"] = changed
    return out


def _entity_diff(old: dict[str, Any], new: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Diff a track or return: mixer/identity fields + sends + devices.
    `fields` selects the named-field set (different for track vs return)."""
    entry: dict[str, Any] = {"index": int(new.get("index", old.get("index")))}
    fc = _field_diff(old, new, fields)
    if fc:
        entry["field_changes"] = fc
    sd = _sends_diff(old.get("sends"), new.get("sends"))
    if sd:
        entry["sends"] = sd
    dd = _devices_diff(old.get("devices"), new.get("devices"))
    if dd:
        entry["devices"] = dd
    return entry


def diff_snapshots(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Compute a structured diff between two captured-session snapshots.

    Identity: tracks/returns matched by `index`; devices within a chain matched
    by `index` within that chain. Name drift is a field-change, not an
    add/remove (Live track names aren't unique enough to use as identity).

    Returns a dict with keys (only those with non-empty content):

      ``song``    : ``{field: {old, new}}`` for tempo / signature changes
      ``master``  : ``{field: {old, new}}`` for master volume/pan changes
      ``returns`` : ``{added: [...], removed: [...], changed: [entity_diff]}``
      ``tracks``  : same shape as ``returns``

    An ``entity_diff`` is:

      ``{index, field_changes, sends, devices}`` — any field is omitted if the
      sub-diff is empty.

    The whole result is empty (`{}`) when snapshots are identical at this
    schema's resolution. Caller checks ``not result`` to know "no changes."
    """
    out: dict[str, Any] = {}

    old_song = old.get("song") or {}
    new_song = new.get("song") or {}
    song_fc = _field_diff(old_song, new_song, ("tempo", "signature"))
    if song_fc:
        out["song"] = song_fc
    master_fc = _field_diff(
        old_song.get("master") or {},
        new_song.get("master") or {},
        ("volume", "panning"),
    )
    if master_fc:
        out["master"] = master_fc

    for kind, fields in (("returns", _RETURN_FIELDS), ("tracks", _MIXER_FIELDS + _TRACK_IDENTITY_FIELDS)):
        old_items = old.get(kind) or []
        new_items = new.get(kind) or []
        old_by_idx = {int(it["index"]): it for it in old_items if "index" in it}
        new_by_idx = {int(it["index"]): it for it in new_items if "index" in it}
        added = [new_by_idx[i] for i in sorted(new_by_idx.keys() - old_by_idx.keys())]
        removed = [old_by_idx[i] for i in sorted(old_by_idx.keys() - new_by_idx.keys())]
        changed: list[dict[str, Any]] = []
        for i in sorted(old_by_idx.keys() & new_by_idx.keys()):
            entry = _entity_diff(old_by_idx[i], new_by_idx[i], fields)
            if len(entry) > 1:
                changed.append(entry)
        sub: dict[str, Any] = {}
        if added:
            sub["added"] = added
        if removed:
            sub["removed"] = removed
        if changed:
            sub["changed"] = changed
        if sub:
            out[kind] = sub

    return out


# ---------------------------------------------------------------------------
# Snapshot merge (Group 1 / G1-C — browser_path stickiness floor)
# ---------------------------------------------------------------------------
# `browser_path` (Arc 7-tail / E3, W13-A v1.0) is captured at LOAD time by
# the MCP load handler's `resolved_path` response field. The list-time
# probes that drive `/song-snapshot` (`ableton_track(action='info')`,
# `ableton_device(action='get_parameters')`) don't surface it — Live's API
# exposes the path only via the browser walk performed at load.
#
# Without stickiness, refreshing a snapshot would wipe every device's
# `browser_path`, breaking the W13-A v1.0 cross-machine fallback identity
# whenever someone re-snapshots a song. Autonomous re-capture (load-time
# snapshot write) is the longer-term fix and is tracked separately; this
# merge helper is the floor that keeps existing values from getting lost.
#
# Sticky fields (preserved when `new` omits them):
#   - device-level `browser_path`
# Other fields use `new`'s value verbatim (intentional drift: a knob move
# captured in the fresh probe must overwrite the on-disk value).

_DEVICE_STICKY_FIELDS: tuple[str, ...] = ("browser_path",)


def _merge_devices(
    old_devices: list[dict[str, Any]] | None,
    new_devices: list[dict[str, Any]] | None,
    _depth: int = 0,
) -> list[dict[str, Any]]:
    """Walk two device arrays (matched by `index`), returning `new` with
    sticky fields copied from the matching `old` entry when `new` doesn't
    carry them. Recurses one level into nested rack `chains` — the only sticky
    field is `browser_path`, which nested devices don't carry (capture injects
    it for top-level devices only), so one level covers every device that
    actually has a sticky field. (Replay/push handle nested params at any depth;
    this merge is a snapshot-refresh preview helper, not the durability path.)
    """
    new = new_devices or []
    old_by_idx = {
        int(d["index"]): d for d in (old_devices or []) if "index" in d
    }
    merged: list[dict[str, Any]] = []
    for nd in new:
        if "index" not in nd:
            merged.append(nd)
            continue
        od = old_by_idx.get(int(nd["index"]))
        if od is None:
            merged.append(nd)
            continue
        entry = dict(nd)
        for field in _DEVICE_STICKY_FIELDS:
            if entry.get(field) in (None, [], {}) and od.get(field) not in (
                None, [], {},
            ):
                entry[field] = od[field]
        if _depth == 0 and (entry.get("chains") or od.get("chains")):
            entry["chains"] = _merge_chains(
                od.get("chains"), entry.get("chains"),
            )
        merged.append(entry)
    return merged


def _merge_chains(
    old_chains: list[dict[str, Any]] | None,
    new_chains: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Walk two nested-chain arrays (matched by `chain_index`), merging
    each chain's devices at `_depth=1`. Returns the new chains with
    stickiness applied; an old-only chain isn't preserved (chain
    structure tracks Live, not the snapshot's history)."""
    new = new_chains or []
    old_by_idx = {
        int(c["chain_index"]): c for c in (old_chains or [])
        if "chain_index" in c
    }
    merged: list[dict[str, Any]] = []
    for nc in new:
        if "chain_index" not in nc:
            merged.append(nc)
            continue
        oc = old_by_idx.get(int(nc["chain_index"]))
        if oc is None:
            merged.append(nc)
            continue
        entry = dict(nc)
        entry["devices"] = _merge_devices(
            oc.get("devices"), nc.get("devices"), _depth=1,
        )
        merged.append(entry)
    return merged


def merge_snapshots(
    old: dict[str, Any], new: dict[str, Any],
) -> dict[str, Any]:
    """Return a snapshot dict that takes `new` as base but preserves
    sticky device fields (`browser_path`) from `old` where `new` omits
    them. Other fields use `new`'s value verbatim — a snapshot refresh
    must reflect the user's actual changes (knob moves, send tweaks,
    track renames) without false drift.

    The merge is structural — track / return / device identity is
    `index`; nested-rack chains match by `chain_index`. Recurses one
    level into rack chains to match capture/replay/diff depth.
    """
    out = dict(new)
    old_tracks = old.get("tracks") or []
    new_tracks = new.get("tracks") or []
    old_tracks_by_idx = {
        int(t["index"]): t for t in old_tracks if "index" in t
    }
    merged_tracks: list[dict[str, Any]] = []
    for nt in new_tracks:
        if "index" not in nt:
            merged_tracks.append(nt)
            continue
        ot = old_tracks_by_idx.get(int(nt["index"]))
        if ot is None:
            merged_tracks.append(nt)
            continue
        entry = dict(nt)
        if ot.get("devices") or nt.get("devices"):
            entry["devices"] = _merge_devices(
                ot.get("devices"), nt.get("devices"),
            )
        merged_tracks.append(entry)
    out["tracks"] = merged_tracks

    old_returns = old.get("returns") or []
    new_returns = new.get("returns") or []
    old_returns_by_idx = {
        int(r["index"]): r for r in old_returns if "index" in r
    }
    merged_returns: list[dict[str, Any]] = []
    for nr in new_returns:
        if "index" not in nr:
            merged_returns.append(nr)
            continue
        or_ = old_returns_by_idx.get(int(nr["index"]))
        if or_ is None:
            merged_returns.append(nr)
            continue
        entry = dict(nr)
        if or_.get("devices") or nr.get("devices"):
            entry["devices"] = _merge_devices(
                or_.get("devices"), nr.get("devices"),
            )
        merged_returns.append(entry)
    out["returns"] = merged_returns
    return out


def format_diff_summary(diff: dict[str, Any]) -> str:
    """One-screen human-readable summary of a diff dict. The skill prints this
    for the user, then asks to confirm overwrite. Detailed per-param drift is
    summarized as counts; users who want the full per-field detail read the
    JSON itself."""
    if not diff:
        return "No changes — snapshot is up to date."
    lines: list[str] = []
    if "song" in diff:
        for f, ch in diff["song"].items():
            lines.append(f"  song.{f}: {ch['old']!r} -> {ch['new']!r}")
    if "master" in diff:
        for f, ch in diff["master"].items():
            lines.append(f"  master.{f}: {ch['old']!r} -> {ch['new']!r}")
    for kind in ("returns", "tracks"):
        sub = diff.get(kind)
        if not sub:
            continue
        for item in sub.get("added") or []:
            lines.append(f"  +{kind[:-1]} {item.get('index')} {item.get('name')!r}")
        for item in sub.get("removed") or []:
            lines.append(f"  -{kind[:-1]} {item.get('index')} {item.get('name')!r}")
        for item in sub.get("changed") or []:
            idx = item["index"]
            bits: list[str] = []
            if "field_changes" in item:
                bits.append(f"{len(item['field_changes'])} field(s)")
            if "sends" in item:
                s = item["sends"]
                send_bits = []
                if s.get("added"):
                    send_bits.append(f"+{len(s['added'])}")
                if s.get("removed"):
                    send_bits.append(f"-{len(s['removed'])}")
                if s.get("changed"):
                    send_bits.append(f"~{len(s['changed'])}")
                bits.append(f"sends {' '.join(send_bits)}")
            if "devices" in item:
                d = item["devices"]
                dev_bits = []
                if d.get("added"):
                    dev_bits.append(f"+{len(d['added'])}")
                if d.get("removed"):
                    dev_bits.append(f"-{len(d['removed'])}")
                if d.get("changed"):
                    dev_bits.append(f"~{len(d['changed'])}")
                bits.append(f"devices {' '.join(dev_bits)}")
            lines.append(f"  ~{kind[:-1]} {idx}: {', '.join(bits)}")
    return "\n".join(lines) if lines else "No changes — snapshot is up to date."
