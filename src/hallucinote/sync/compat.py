"""Cross-machine portability: detect third-party plugins a song requires.

W13-B (v0.9.0). The DB-as-source-of-truth model means a song travels as a
DB + a captured snapshot — but Live devices reference plugins (VST/AU) that
the consumer's machine may not have installed. This module walks a song's
device tree and classifies every device into one of five states so the
push skill can refuse-and-confirm before silently failing at load time.

Express non-goals (build-plan W13-B):
- **Never substitute.** A missing Spitfire LABS isn't replaced by Operator.
- **Never bundle.** Hallucinote does not ship instrument or sample data.

If a plugin is missing, the consumer installs it. REQUIREMENTS.md (written
by ``write_requirements``) is the shopping list the song's author leaves
for collaborators.

Two CLI subcommands:
- ``compat check <slug> [--installed-plugins FILE] [--probe]`` — print JSON
  report + exit 1 if items need user attention (missing or unverified
  third-party, structurally invalid preset_query, or — with ``--probe`` —
  preset_query that resolves to 0 or 2+ matches in Live's browser).
  Called by the ``/ableton-push`` skill as a preflight gate.
- ``compat write-requirements <slug>`` — (re)generate
  ``songs/<slug>/REQUIREMENTS.md`` so the file travels with the song. The
  *author* runs this when their device list materially changes; the
  *consumer* reads it before installing missing plugins. Independent of
  any installed-plugins list (REQUIREMENTS.md is what the song NEEDS, not
  what THIS MACHINE has).

Core functions (``classify_device``, ``classify_preset_query``,
``check_song``) remain pure — no MCP imports — so they're usable from
tests and other in-process callers without a running Live. The CLI
``--probe`` flag is the one orchestration seam where MCP enters: it
issues ``ableton_browser(action='search')`` for every structurally-valid
preset_query in the song and feeds the resulting count map to
``check_song`` as ``browser_dry_runs=``. Same lazy-import seam as
``push_cli._resolve_send_fn`` so this module imports cleanly without
``hallucinote_mcp`` installed.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from hallucinote.db import init_db, queries as Q, resolve_db_path
from hallucinote.preset_query import BROWSER_ROOTS as _VALID_BROWSER_ROOTS
from hallucinote.preset_query import SEARCH_MODES as _VALID_MATCH_MODES
from hallucinote.workspace import resolve_song_dir


# The matcher's own defaults, named once. Importing the ENUM but restating
# the DEFAULTS would leave the gate half-anchored to the loader — the same
# split that let SYN-6Q3D happen.
_MATCH_MODE_DEFAULT = "substring"
_CASE_SENSITIVE_DEFAULT = False


# ---------------------------------------------------------------------------
# Plugin-class discriminator
# ---------------------------------------------------------------------------
#
# Live wraps third-party plugins under stable class names. Mirror of the
# ``is_third_party_plugin`` logic in
# ``hallucinote_mcp/.../handlers/device.py`` (search the string). The two
# sides MUST agree — if MCP says a device is third-party and compat-check
# doesn't classify it as such (or vice versa), push will silently misroute.
# A lock-test in ``tests/unit/sync/test_compat.py`` pins the set.

_PLUGIN_CLASSES: frozenset[str] = frozenset({
    "PluginDevice",       # Live's generic VST/VST3 wrapper (Windows + cross-platform)
    "AuPluginDevice",     # macOS AudioUnit
    "Vst3PluginDevice",   # Some Live builds report VST3 separately
})

# Sentinel kind for "author intentionally left this slot empty for the
# consumer to fill." Push planner skips placeholder devices cleanly.
_PLACEHOLDER_KIND = "placeholder"


# Browser roots accepted by `ableton_device(action='load', preset_query=...)`
# imported as the canonical name `_VALID_BROWSER_ROOTS` from
# ``hallucinote.preset_query`` so this module and the path-shape parser
# stay in lock-step. The MCP-side lock-test still pins both against
# ``hallucinote_mcp.actions.browser._ROOTS``.


def _is_plugin_class(class_name: str) -> bool:
    """True iff ``class_name`` indicates a third-party plugin wrapper.

    Conservative: the explicit set is the canonical list; the substring
    check catches future Live versions that introduce e.g.
    ``Vst4PluginDevice``. Test fakes that fail this discriminator
    contract are likely a Live-API change worth investigating.
    """
    return class_name in _PLUGIN_CLASSES or "Plugin" in class_name


# ---------------------------------------------------------------------------
# Report types
# ---------------------------------------------------------------------------
#
# Status enumerates every state the report differentiates. Per the
# "Detection that replaces a user question must enumerate every state"
# learning, callers (push-preflight gate, REQUIREMENTS.md generator,
# the agent UI) MUST handle each value explicitly — they can't fall
# back to a "found"/"not found" binary.

DeviceStatus = Literal[
    "native",                   # Live built-in — no install needed.
    "placeholder",              # Author intentionally left this slot empty.
    "third_party_ok",           # Plugin needed AND found in the installed list.
    "third_party_missing",      # Plugin needed AND not found in the installed list.
    "third_party_unverified",   # Plugin needed AND no installed list was provided.
    # R-2.1: preset_query / load-shape validation. Catches authoring errors
    # that compat used to let pass through to push time.
    "preset_query_invalid",     # preset_query has a structural error (bad root, non-list path_prefix).
    "kind_unresolvable",        # Dry-run reported 0 matches for kind/preset_query — load will fail.
    "kind_ambiguous",           # Dry-run reported 2+ matches — strict loader will refuse.
    "preset_query_unverified",  # preset_query needed AND no dry-runs map was provided.
]


@dataclass
class DeviceEntry:
    """One row in the report — per device in the song's DB.

    ``chain_path`` describes the device's location for nested racks
    (``"Drums / Late Nite Kit"`` for a device inside the Late Nite Kit
    drum rack on the Drums track). For top-level devices it's just the
    track or return name.
    """
    track_name: str
    chain_path: str
    position: int
    display_name: str
    kind: str
    preset_uri: str | None
    status: DeviceStatus
    # For third-party plugins, the name the consumer should look for in
    # their plugin scanner. Until W13-A's snapshot-format expansion lands
    # a dedicated ``plugin_name`` column, we use ``display_name`` as the
    # best signal we have — the author typically names the device after
    # the plugin (or after a preset they bought from that vendor).
    lookup_name: str | None = None
    # R-2.1: for preset_query_* statuses, a human-readable hint naming
    # the specific defect (e.g. "root='effects' not in valid roots",
    # "0 matches for pattern='Hall' under audio_effects/Hybrid Reverb"
    # — the agent can use this to suggest a concrete fix without
    # re-running the dry-run).
    detail: str | None = None


@dataclass
class CompatReport:
    """Structured result of one ``check_song`` run.

    The status buckets cover every device in the song's DB. The
    ``has_issues`` flag is what the push-preflight gate keys off: True
    means "stop and ask the user before pushing."
    """
    song_slug: str
    song_title: str | None
    entries: list[DeviceEntry] = field(default_factory=list)
    installed_provided: bool = False  # Was --installed-plugins given?
    # R-2.1: was --browser-dry-runs (or the in-process equivalent) given?
    # Mirrors ``installed_provided``: when False, preset_query devices
    # land in ``preset_query_unverified`` instead of resolved/refused.
    browser_dry_runs_provided: bool = False

    @property
    def native(self) -> list[DeviceEntry]:
        return [e for e in self.entries if e.status == "native"]

    @property
    def placeholders(self) -> list[DeviceEntry]:
        return [e for e in self.entries if e.status == "placeholder"]

    @property
    def third_party_ok(self) -> list[DeviceEntry]:
        return [e for e in self.entries if e.status == "third_party_ok"]

    @property
    def missing(self) -> list[DeviceEntry]:
        return [e for e in self.entries if e.status == "third_party_missing"]

    @property
    def unverified(self) -> list[DeviceEntry]:
        return [e for e in self.entries if e.status == "third_party_unverified"]

    @property
    def preset_query_invalid(self) -> list[DeviceEntry]:
        return [e for e in self.entries if e.status == "preset_query_invalid"]

    @property
    def kind_unresolvable(self) -> list[DeviceEntry]:
        return [e for e in self.entries if e.status == "kind_unresolvable"]

    @property
    def kind_ambiguous(self) -> list[DeviceEntry]:
        return [e for e in self.entries if e.status == "kind_ambiguous"]

    @property
    def preset_query_unverified(self) -> list[DeviceEntry]:
        return [e for e in self.entries if e.status == "preset_query_unverified"]

    @property
    def has_issues(self) -> bool:
        """True iff the push-preflight gate should refuse-and-confirm.

        Missing plugins ARE issues. Unverified plugins ARE issues too
        (the operator should explicitly confirm rather than discover at
        load time). Placeholders are NOT issues — they're intentional.

        R-2.1: the three new preset_query failure modes
        (``preset_query_invalid``, ``kind_unresolvable``,
        ``kind_ambiguous``) are ALL issues — every one of them is a
        push-time refusal the loader will raise. ``preset_query_unverified``
        is an issue for the same reason ``third_party_unverified`` is:
        the operator should explicitly confirm rather than discover at
        load time.
        """
        return bool(
            self.missing or self.unverified
            or self.preset_query_invalid
            or self.kind_unresolvable
            or self.kind_ambiguous
            or self.preset_query_unverified
        )

    def to_json(self) -> dict:
        return {
            "song_slug": self.song_slug,
            "song_title": self.song_title,
            "installed_provided": self.installed_provided,
            "browser_dry_runs_provided": self.browser_dry_runs_provided,
            "entries": [asdict(e) for e in self.entries],
            "summary": {
                "total": len(self.entries),
                "native": len(self.native),
                "placeholders": len(self.placeholders),
                "third_party_ok": len(self.third_party_ok),
                "missing": len(self.missing),
                "unverified": len(self.unverified),
                "preset_query_invalid": len(self.preset_query_invalid),
                "kind_unresolvable": len(self.kind_unresolvable),
                "kind_ambiguous": len(self.kind_ambiguous),
                "preset_query_unverified": len(self.preset_query_unverified),
                "has_issues": self.has_issues,
            },
        }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_preset_query(
    preset_query_raw: str | None,
) -> tuple[DeviceStatus, str | None] | None:
    """Validate the STRUCTURE of a stored preset_query (root + path_prefix
    shape). Returns ``None`` when the device has no preset_query (the
    classify-by-kind path takes over) or when the structure is fine and
    a dry-run is the next step.

    R-2.1 catches the two structural traps from sun-zone-done that never
    reach a dry-run:

    * ``root`` not in the loader's accepted enum (typo: ``"effects"`` vs
      ``"audio_effects"`` — 8 push failures in one run).
    * ``path_prefix`` is a JSON string instead of a list — the loader's
      ``preset_query.path_prefix must be a list`` error gets surfaced at
      compose time instead of push time.

    Garbage JSON (un-parseable) also lands here as ``preset_query_invalid``
    so a malformed snapshot can't slip through to push.
    """
    if preset_query_raw is None:
        return None
    try:
        pq = json.loads(preset_query_raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return "preset_query_invalid", f"preset_query is not valid JSON: {exc}"
    if not isinstance(pq, dict):
        return (
            "preset_query_invalid",
            f"preset_query must be a JSON object, got {type(pq).__name__}",
        )
    root = pq.get("root")
    if root is None:
        return (
            "preset_query_invalid",
            "preset_query.root is required (see snapshot-schema.md for the "
            "valid root enum)",
        )
    if root not in _VALID_BROWSER_ROOTS:
        return (
            "preset_query_invalid",
            f"preset_query.root={root!r} not in valid roots "
            f"{sorted(_VALID_BROWSER_ROOTS)} (note: the resource URI uses "
            "'effects', but the loader uses 'audio_effects')",
        )
    path_prefix = pq.get("path_prefix")
    if path_prefix is not None and not isinstance(path_prefix, list):
        return (
            "preset_query_invalid",
            f"preset_query.path_prefix must be a list of name segments, got "
            f"{type(path_prefix).__name__} ({path_prefix!r}). Wrap a single "
            "segment in a list: ['Operator']",
        )
    pattern = pq.get("pattern")
    if pattern is not None and not isinstance(pattern, str):
        return (
            "preset_query_invalid",
            f"preset_query.pattern must be a string, got {type(pattern).__name__}",
        )
    # SYN-6Q3D: `mode` and `case_sensitive` now ride the wire into
    # `ableton_browser(action='search')`, so they are structural too. Without
    # this check an unknown mode reaches the probe, the browser rejects the
    # enum, and `_probe_browser_dry_runs` raises SystemExit — killing the WHOLE
    # `--probe` report over one bad device instead of flagging that device. The
    # enum is IMPORTED from `preset_query` (the lock-tested mirror of the
    # MCP resolver) rather than restated, so the gate cannot drift from the
    # matcher — the exact class of disagreement this item existed to fix.
    # `"mode": null` is NOT the same as an absent key: absent means "use the
    # default", while an explicit null reaches `name_matches` and raises
    # "unknown search mode None". Keying on presence rather than truthiness
    # keeps the gate and the loader agreeing — the exact disagreement SYN-6Q3D
    # existed to fix, which a `pq.get("mode")` check would have reopened.
    mode = pq["mode"] if "mode" in pq else _MATCH_MODE_DEFAULT
    if mode not in _VALID_MATCH_MODES:
        return (
            "preset_query_invalid",
            f"preset_query.mode={mode!r} not in {sorted(_VALID_MATCH_MODES)}",
        )
    # NOT the presence rule `mode` uses, deliberately — the justification does
    # not transfer. An explicit `mode: null` REACHES `name_matches` and raises,
    # so the gate must reject it to stay in step with the loader. An explicit
    # `case_sensitive: null` degrades to False in every consumer (`name_matches`
    # tests `if not case_sensitive`, `_dry_run_key` coerces via `bool(...)`, the
    # MCP resolver does the same), so rejecting it would make this gate STRICTER
    # than the loader — refusing a song that loads fine, which is the exact
    # failure shape SYN-6Q3D existed to remove. Only a non-null non-bool is an
    # authoring error worth reporting.
    case_sensitive = pq.get("case_sensitive")
    if case_sensitive is not None and not isinstance(case_sensitive, bool):
        return (
            "preset_query_invalid",
            "preset_query.case_sensitive must be a boolean, got "
            f"{type(case_sensitive).__name__}",
        )
    # Structure is fine — caller will dispatch the dry-run.
    return None


# The browser dry-run cache key: every field `preset_query.name_matches` reads.
# Named rather than spelled out at each use so widening it (as SYN-6Q3D did,
# adding mode + case_sensitive) is a one-line change, not an eight-site sweep.
_DryRunKey = tuple[str, str, tuple[str, ...], str, bool]

def _dry_run_key(preset_query: dict) -> _DryRunKey:
    """Canonical key for a precomputed browser-search dry-run cache.

    Carries every field ``preset_query.name_matches`` reads — ``root``,
    ``pattern``, tuple-encoded ``path_prefix``, ``mode`` and
    ``case_sensitive`` — so the cache hash is stable across re-runs AND two
    queries that differ only in how they match cannot collide on one entry.

    ``mode``/``case_sensitive`` were originally absent, which caused both
    halves of SYN-6Q3D: the probe searched with the browser's default
    substring matcher regardless of what the query declared, and two devices
    differing only in ``mode`` shared a single match count. The defaults here
    mirror :func:`hallucinote.preset_query.name_matches`.
    """
    return (
        str(preset_query.get("root", "")),
        str(preset_query.get("pattern", "")),
        tuple(preset_query.get("path_prefix") or []),
        str(preset_query.get("mode", _MATCH_MODE_DEFAULT)),
        bool(preset_query.get("case_sensitive", _CASE_SENSITIVE_DEFAULT)),
    )


def classify_device(
    device_kind: str,
    *,
    display_name: str,
    installed_plugin_names: frozenset[str] | None,
) -> tuple[DeviceStatus, str | None]:
    """Classify a single device into one of five statuses.

    ``installed_plugin_names`` is None when no list was provided (offline
    use, or running compat check without an MCP probe). In that case,
    third-party plugins land in ``third_party_unverified`` rather than
    being incorrectly flagged ``third_party_missing``.

    The plugin-name match is a case-insensitive substring check in both
    directions. The author's display_name is often a preset name ("Late
    Nite Kit", "Spitfire LABS Soft Piano") while Live's plugins_list
    output uses the plugin's marketed name ("Spitfire LABS"); requiring
    exact equality would false-positive too aggressively, and a stricter
    match is W13-A's job once dedicated plugin metadata lands.
    """
    if device_kind == _PLACEHOLDER_KIND:
        return "placeholder", None
    if not _is_plugin_class(device_kind):
        return "native", None
    lookup_name = display_name
    if installed_plugin_names is None:
        return "third_party_unverified", lookup_name
    # Empty display_name → no signal to match against. Schema allows
    # empty strings (NOT NULL but no length check), so this can arise
    # from incomplete authoring or a future probe path that doesn't
    # populate the name. `'' in any_string` is always True, which would
    # spuriously match the first installed plugin — fail closed instead.
    if not lookup_name.strip():
        return "third_party_missing", lookup_name
    needle = lookup_name.lower()
    for installed in installed_plugin_names:
        hay = installed.lower()
        if needle in hay or hay in needle:
            return "third_party_ok", lookup_name
    return "third_party_missing", lookup_name


# ---------------------------------------------------------------------------
# Song walk
# ---------------------------------------------------------------------------


def check_song(
    db_path: Path | str,
    *,
    installed_plugins: list[dict] | None = None,
    browser_dry_runs: dict[_DryRunKey, int] | None = None,
) -> CompatReport:
    """Walk the song's DB and classify every device.

    Recurses into nested rack chains so plugin-inside-rack ("an FX rack
    wrapping a Spitfire VST") is detected — top-level-only would miss
    this case and produce false-clean reports.

    ``installed_plugins`` matches the shape of
    ``ableton_browser(action='plugins_list')``: a list of
    ``{"name": str, "uri": str}`` dicts. Pass None to skip the
    cross-check entirely (every third-party plugin becomes
    ``third_party_unverified``).

    R-2.1 ``browser_dry_runs`` (optional): precomputed map from
    ``(root, pattern, path_prefix_tuple)`` → integer match count. Filled
    in by the caller (CLI / skill) by running ``ableton_browser(action=
    'search')`` for every device's ``preset_query``. When None,
    structurally-valid preset_queries land in ``preset_query_unverified``
    (mirrors the ``third_party_unverified`` design). When provided, the
    match count drives ``kind_unresolvable`` (0) /
    ``kind_ambiguous`` (2+) / native (1).
    """
    # Open via init_db (not bare connect) so a song DB built by an earlier
    # release is migrated to the current schema first — check_song reads
    # post-0.9.0 device columns (class_name / preset_query / browser_path_json),
    # which a legacy DB lacks. Same rationale as push_cli/_open_db.
    conn = init_db(db_path)
    try:
        songs = conn.execute("SELECT id, name, title FROM songs").fetchall()
        if len(songs) != 1:
            raise ValueError(
                f"compat check: DB at {db_path} has {len(songs)} song rows; "
                "expected exactly 1 (one DB per song convention — see "
                "project-preferences.md)."
            )
        song_row = songs[0]
        song_id = song_row["id"]

        installed_names: frozenset[str] | None = None
        if installed_plugins is not None:
            installed_names = frozenset(
                str(p.get("name", "")).strip()
                for p in installed_plugins
                if p.get("name")
            )

        report = CompatReport(
            song_slug=song_row["name"],
            song_title=song_row["title"],
            installed_provided=installed_plugins is not None,
            browser_dry_runs_provided=browser_dry_runs is not None,
        )

        tracks = conn.execute(
            "SELECT id, name FROM tracks WHERE song_id = ? AND kind != 'master' "
            "ORDER BY track_index",
            (song_id,),
        ).fetchall()
        for t in tracks:
            for chain in Q.get_device_chains_for_track(conn, t["id"]):
                _walk_chain(
                    conn, chain, parent_label=t["name"], track_name=t["name"],
                    report=report, installed_names=installed_names,
                    browser_dry_runs=browser_dry_runs,
                )

        returns = conn.execute(
            "SELECT id, name FROM returns WHERE song_id = ? ORDER BY position",
            (song_id,),
        ).fetchall()
        for r in returns:
            for chain in Q.get_device_chains_for_return(conn, r["id"]):
                _walk_chain(
                    conn, chain, parent_label=r["name"], track_name=r["name"],
                    report=report, installed_names=installed_names,
                    browser_dry_runs=browser_dry_runs,
                )

        return report
    finally:
        conn.close()


def _walk_chain(
    conn: sqlite3.Connection,
    chain: sqlite3.Row,
    *,
    parent_label: str,
    track_name: str,
    report: CompatReport,
    installed_names: frozenset[str] | None,
    browser_dry_runs: dict[_DryRunKey, int] | None,
) -> None:
    """Recursively walk a device chain, classifying each device.

    Nested racks (DrumGroupDevice / InstrumentGroupDevice /
    AudioEffectGroupDevice) carry their own inner chains via
    ``device_chains.parent_rack_device_id``. Recurse so plugin-inside-
    rack is detected.
    """
    devices = Q.get_devices_for_chain(conn, chain["id"])
    for d in devices:
        status, lookup, detail = _classify_device_full(
            d, installed_names=installed_names, browser_dry_runs=browser_dry_runs,
        )
        report.entries.append(DeviceEntry(
            track_name=track_name,
            chain_path=parent_label,
            position=d["position"],
            display_name=d["display_name"],
            kind=d["kind"],
            preset_uri=d["preset_uri"],
            status=status,
            lookup_name=lookup,
            detail=detail,
        ))
        for inner in Q.get_device_chains_for_rack_device(conn, d["id"]):
            _walk_chain(
                conn, inner,
                parent_label=f"{parent_label} / {d['display_name']}",
                track_name=track_name,
                report=report, installed_names=installed_names,
                browser_dry_runs=browser_dry_runs,
            )


def _classify_device_full(
    device_row: sqlite3.Row,
    *,
    installed_names: frozenset[str] | None,
    browser_dry_runs: dict[_DryRunKey, int] | None,
) -> tuple[DeviceStatus, str | None, str | None]:
    """Combined classifier — preset_query validation takes precedence
    over plugin-check, because a structurally-broken preset_query will
    refuse at load time regardless of whether the underlying class is
    native or third-party.

    Returns ``(status, lookup_name, detail)``. ``detail`` is non-None
    for the new preset_query failure modes; the legacy plugin path
    leaves it None to keep its output stable.
    """
    # preset_query branch — structural check first, dry-run after.
    preset_query_raw = device_row["preset_query"] if "preset_query" in device_row.keys() else None
    if preset_query_raw is not None:
        structural = classify_preset_query(preset_query_raw)
        if structural is not None:
            status, detail = structural
            return status, device_row["display_name"], detail
        # Structurally valid → consult the dry-run cache (if available).
        pq = json.loads(preset_query_raw)
        if browser_dry_runs is None:
            return (
                "preset_query_unverified",
                device_row["display_name"],
                "no browser dry-runs provided (run `compat check <slug> --probe` "
                "with Live + the MCP bridge available)",
            )
        key = _dry_run_key(pq)
        match_count = browser_dry_runs.get(key)
        pattern = pq.get("pattern", "")
        root = pq.get("root", "")
        path = pq.get("path_prefix") or []
        path_str = "/".join(str(p) for p in path) if path else "(no path_prefix)"
        if match_count is None or match_count == 0:
            return (
                "kind_unresolvable",
                device_row["display_name"],
                f"0 matches for pattern={pattern!r} under root={root!r} "
                f"path_prefix={path_str} — Live's browser has nothing at "
                "that location. Tighten path_prefix or fix the pattern.",
            )
        if match_count >= 2:
            return (
                "kind_ambiguous",
                device_row["display_name"],
                f"{match_count} matches for pattern={pattern!r} under "
                f"root={root!r} path_prefix={path_str} — the strict loader "
                "refuses on multi-match. Use a more specific pattern, an "
                "explicit '.adv' suffix, or a tighter path_prefix.",
            )
        # match_count == 1 → resolves cleanly; fall through to plugin check
        # since the SAME device could still be a third-party plugin needing
        # the installed-plugin classifier.

    # Arc 4 / D4: plugin classification keys off Live's INTERNAL class
    # name (PluginDevice / AuPluginDevice / Vst3PluginDevice — these are
    # Live's wrapper classes, not browser display names). Under the
    # post-D4 convention `kind` is the browser display name (e.g.
    # "Serum" for a Serum patch); the internal class lives in
    # `class_name`. When the DB row was written pre-D4 or via a
    # hand-authored snapshot without `class_name`, fall back to `kind`
    # so existing tests + legacy data continue to discriminate plugins
    # the same way.
    discriminator_class = (
        device_row["class_name"]
        if "class_name" in device_row.keys() and device_row["class_name"]
        else device_row["kind"]
    )
    status, lookup = classify_device(
        discriminator_class,
        display_name=device_row["display_name"],
        installed_plugin_names=installed_names,
    )
    return status, lookup, None


# ---------------------------------------------------------------------------
# REQUIREMENTS.md generation
# ---------------------------------------------------------------------------


def format_requirements_md(report: CompatReport) -> str:
    """Format REQUIREMENTS.md content for a song.

    Authored from the song's perspective ("what this song needs"), NOT the
    consumer's machine — the same REQUIREMENTS.md ships to every
    collaborator regardless of what they have installed. Per the
    "link, don't summarize" learning, the file points the consumer at
    the song's DB for authoritative device counts/positions rather than
    restating them here.
    """
    title = report.song_title or report.song_slug
    lines: list[str] = [
        f"# Requirements — {title}",
        "",
        f"Song slug: `{report.song_slug}`",
        "",
        "This file lists the third-party plugins this song uses. Install them "
        "in Ableton Live before pushing the song. Generated by "
        "`python -m hallucinote.sync.compat write-requirements <slug>` — re-run "
        "after material changes to the song's device list.",
        "",
    ]

    # Group third-party entries by unique display_name so a plugin used on
    # multiple tracks appears once. Walk the full third-party set (ok +
    # missing + unverified) — REQUIREMENTS.md is consumer-side-agnostic.
    third_party = (
        report.third_party_ok + report.missing + report.unverified
    )
    if third_party:
        lines.append("## Required third-party plugins")
        lines.append("")
        by_name: dict[str, list[DeviceEntry]] = {}
        for e in third_party:
            name = e.lookup_name or e.display_name
            by_name.setdefault(name, []).append(e)
        for name in sorted(by_name):
            uses = by_name[name]
            lines.append(f"- **{name}**")
            for e in uses:
                lines.append(
                    f"  - {e.chain_path} (position {e.position}, "
                    f"class `{e.kind}`)"
                )
        lines.append("")
        lines.append(
            "If you've installed something but the push preflight still "
            "flags it as missing, check that Live has scanned the plugin "
            "(Preferences → Plug-Ins → Rescan). Plugin names below are "
            "the author's display names — the actual plugin may carry a "
            "different name in Live's plugin list; a case-insensitive "
            "substring match in either direction counts as a hit."
        )
        lines.append("")
    else:
        lines.append("## Required third-party plugins")
        lines.append("")
        lines.append(
            "None. This song uses only Live's built-in devices — no "
            "additional installs needed."
        )
        lines.append("")

    if report.placeholders:
        lines.append("## Author-intentional placeholders")
        lines.append("")
        lines.append(
            "These device slots are placeholders the author left empty for "
            "you to fill in. Push will leave them as empty Live chains; "
            "load any instrument or effect you want there before producing."
        )
        lines.append("")
        for e in report.placeholders:
            label = e.display_name or "(unnamed placeholder)"
            lines.append(
                f"- {e.chain_path} (position {e.position}) — {label}"
            )
        lines.append("")

    # R-2.1: preset_query failure modes belong in REQUIREMENTS.md because
    # the consumer can't fix a structurally-broken snapshot by installing
    # plugins — the AUTHOR needs to repair the snapshot. Surfacing here
    # makes the fix list visible at the same time as the install list.
    preset_query_issues = (
        report.preset_query_invalid
        + report.kind_unresolvable
        + report.kind_ambiguous
    )
    if preset_query_issues:
        lines.append("## preset_query authoring issues")
        lines.append("")
        lines.append(
            "These devices have ``preset_query`` selectors the push planner "
            "will refuse at load time. Fix in the snapshot (or the "
            "build.py that authored them) before re-pushing:"
        )
        lines.append("")
        for e in preset_query_issues:
            lines.append(
                f"- **{e.display_name}** at {e.chain_path} position "
                f"{e.position} — _{e.status}_"
            )
            if e.detail:
                lines.append(f"  - {e.detail}")
        lines.append("")

    if report.native:
        unique_kinds = sorted({e.kind for e in report.native})
        lines.append("## Live built-in devices (no install needed)")
        lines.append("")
        lines.append(
            "Listed here for completeness — these ship with Live and "
            "don't need separate installation:"
        )
        lines.append("")
        lines.append(", ".join(f"`{k}`" for k in unique_kinds) + ".")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "_The song's DB is the source of truth for device counts and "
        "positions; this file is a human-readable summary._"
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _resolve_db(slug: str) -> Path:
    """Mirror push_cli's DB resolution: per-branch first, legacy fallback."""
    path = resolve_db_path(slug)
    if not path.exists():
        legacy = resolve_db_path(slug, branch=None)  # no-branch fallback, same song dir
        if legacy.exists():
            return legacy
        raise SystemExit(
            f"compat: DB not found at {path} — run "
            f"`python songs/{slug}/build.py` first to populate it."
        )
    return path


def _load_installed_plugins(path: Path) -> list[dict]:
    """Parse the JSON dumped by ``ableton_browser(action='plugins_list')``.

    Accepts the wrapper shape ``{"plugins": [...], "count": N}`` or a bare
    list. Both shapes appear in the wild — the wrapper from the MCP tool
    response, the bare list from hand-crafted test fixtures.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"compat: --installed-plugins {path} could not be read: {exc}"
        ) from exc
    if isinstance(data, dict) and "plugins" in data:
        return list(data["plugins"])
    if isinstance(data, list):
        return data
    raise SystemExit(
        f"compat: --installed-plugins {path} must be a list or "
        '{"plugins": [...]} — got '
        f"{type(data).__name__}."
    )


def _resolve_send_fn():
    """Lazy resolver for ``hallucinote_mcp.client.send``.

    Mirrors :func:`hallucinote.sync.push_cli._resolve_send_fn` — the seam
    exists so tests can inject a fake send_fn without monkeypatching
    ``sys.modules``. Keeps compat importable when ``hallucinote_mcp``
    isn't installed (the core ``check_song`` walk doesn't need it; only
    ``--probe`` does).
    """
    from hallucinote_mcp import client as _client  # type: ignore[import-not-found]
    return _client.send


def _collect_preset_query_specs(
    conn: sqlite3.Connection,
) -> list[tuple[_DryRunKey, dict]]:
    """Walk every device in the (single-song) DB and return unique
    structurally-valid preset_queries as ``(dry_run_key, query_dict)``
    pairs.

    Deduplicates by ``_dry_run_key`` so two devices sharing the same
    ``preset_query`` only get probed once. Structurally invalid queries
    (per :func:`classify_preset_query`) are skipped — they'll surface as
    ``preset_query_invalid`` in the report whether the probe ran or not.
    The flat ``SELECT`` is safe because compat operates per-song DBs
    (``check_song`` enforces a single-song invariant on the surrounding
    walk).
    """
    rows = conn.execute(
        "SELECT preset_query FROM devices WHERE preset_query IS NOT NULL"
    ).fetchall()
    seen: dict[_DryRunKey, dict] = {}
    for row in rows:
        raw = row["preset_query"]
        if classify_preset_query(raw) is not None:
            continue
        try:
            pq = json.loads(raw)
        except json.JSONDecodeError:
            # classify_preset_query already filtered un-parseable JSON;
            # belt-and-suspenders so a future schema drift can't slip
            # garbage past the structural check into the probe call.
            continue
        key = _dry_run_key(pq)
        if key not in seen:
            seen[key] = pq
    return list(seen.items())


def _probe_browser_dry_runs(
    conn: sqlite3.Connection,
    *,
    send_fn=None,
) -> dict[_DryRunKey, int]:
    """Issue ``ableton_browser(action='search')`` for every unique
    structurally-valid preset_query in the song's DB and return a map
    suitable for :func:`check_song`'s ``browser_dry_runs=`` parameter.

    ``limit=2`` because the report only distinguishes 0 / 1 / 2+ matches;
    walking further is wasted work. Empty DB → empty map (no probe
    calls).

    Any non-``ok`` response raises ``SystemExit`` with the upstream
    error. A partial map would silently produce false-clean reports
    (a device with no entry in the map looks unverified instead of
    surfacing the probe failure) — fail loud instead.
    """
    specs = _collect_preset_query_specs(conn)
    if not specs:
        return {}
    if send_fn is None:
        send_fn = _resolve_send_fn()
    from hallucinote_mcp.wire import Request  # type: ignore[import-not-found]

    out: dict[_DryRunKey, int] = {}
    for key, pq in specs:
        params: dict = {
            "pattern": pq.get("pattern", ""),
            "root": pq.get("root", "instruments"),
            "limit": 2,
        }
        path_prefix = pq.get("path_prefix") or []
        if path_prefix:
            params["path_prefix"] = list(path_prefix)
        # Probe with the matcher the LOADER will use. Omitting these made the
        # gate disagree with the thing it gates: an `exact` query was probed
        # with the browser's default substring matcher, so a pattern matching
        # one preset exactly but two by substring was refused as
        # `kind_ambiguous` on a device that loads perfectly. Sent only when
        # non-default so the wire stays byte-identical for ordinary queries.
        mode = pq.get("mode")
        if mode:
            params["mode"] = str(mode)
        if pq.get("case_sensitive"):
            params["case_sensitive"] = True
        resp = send_fn(Request(
            tool="ableton_browser", action="search", params=params,
        ))
        if not getattr(resp, "ok", False):
            raise SystemExit(
                "compat check --probe: ableton_browser(action='search') failed "
                f"for preset_query={pq!r} — "
                f"{getattr(resp, 'error', 'unknown error')}"
            )
        payload = getattr(resp, "result", None) or {}
        out[key] = int(payload.get("count", len(payload.get("matches") or [])))
    return out


def _cmd_check(args: argparse.Namespace) -> int:
    db_path = _resolve_db(args.song)
    installed: list[dict] | None = None
    if args.installed_plugins:
        installed = _load_installed_plugins(Path(args.installed_plugins))
    browser_dry_runs = None
    if args.probe:
        conn = init_db(db_path)  # migrate-on-open; see check_song
        try:
            browser_dry_runs = _probe_browser_dry_runs(conn)
        finally:
            conn.close()
    report = check_song(
        db_path,
        installed_plugins=installed,
        browser_dry_runs=browser_dry_runs,
    )
    json.dump(report.to_json(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 1 if report.has_issues else 0


def regen_requirements(song_slug: str) -> Path:
    """Regenerate ``songs/<slug>/REQUIREMENTS.md`` from the song's DB.

    Author-side: ``installed_plugins`` is ignored (REQUIREMENTS.md is
    consumer-side-agnostic). All third-party plugins surface as
    'third_party_unverified' which the formatter treats identically to
    missing/ok in the required-plugins section.

    Callable seam for DOC-5W8B (auto-regen after a device-changing push)
    and the ``write-requirements`` CLI command. Returns the written path;
    raises ``SystemExit`` when the song dir doesn't resolve.
    """
    db_path = _resolve_db(song_slug)
    report = check_song(db_path, installed_plugins=None)
    out_path = resolve_song_dir(song_slug) / "REQUIREMENTS.md"
    if not out_path.parent.exists():
        raise SystemExit(
            f"compat: {out_path.parent}/ does not exist — wrong slug?"
        )
    content = format_requirements_md(report)
    out_path.write_text(content)
    return out_path


def _cmd_write_requirements(args: argparse.Namespace) -> int:
    out_path = regen_requirements(args.song)
    sys.stdout.write(f"wrote {out_path}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hallucinote.sync.compat",
        description=(
            "Detect third-party plugins a song needs and generate "
            "REQUIREMENTS.md (W13-B). Both subcommands resolve the song's "
            "DB and write REQUIREMENTS.md relative to the current working "
            "directory — run from the repo root."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser(
        "check",
        help=(
            "Classify every device in the song; exit 1 if items need "
            "user attention (missing/unverified third-party)."
        ),
    )
    p_check.add_argument("song", help="song slug")
    p_check.add_argument(
        "--installed-plugins",
        help=(
            "Path to JSON from ableton_browser(action='plugins_list'). "
            "Omit to run without cross-checking; every third-party "
            "plugin then surfaces as 'third_party_unverified'."
        ),
    )
    p_check.add_argument(
        "--probe", action="store_true",
        help=(
            "Resolve every preset_query against Live's browser via the MCP "
            "bridge — issues ableton_browser(action='search') per unique "
            "(root, pattern, path_prefix). Without this flag, structurally "
            "valid preset_queries surface as 'preset_query_unverified'. "
            "Requires hallucinote_mcp installed and a running Live with the "
            "Hallucinote Remote Script enabled."
        ),
    )
    p_check.set_defaults(func=_cmd_check)

    p_req = sub.add_parser(
        "write-requirements",
        help=(
            "(Re)generate songs/<slug>/REQUIREMENTS.md from the song's "
            "DB. Author-side tool — run after material device changes."
        ),
    )
    p_req.add_argument("song", help="song slug")
    p_req.set_defaults(func=_cmd_write_requirements)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
