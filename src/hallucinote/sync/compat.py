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
- ``compat check <slug> [--installed-plugins FILE]`` — print JSON report
  + exit 1 if items need user attention (missing or unverified third-party).
  Called by the ``/ableton-push`` skill as a preflight gate.
- ``compat write-requirements <slug>`` — (re)generate
  ``songs/<slug>/REQUIREMENTS.md`` so the file travels with the song. The
  *author* runs this when their device list materially changes; the
  *consumer* reads it before installing missing plugins. Independent of
  any installed-plugins list (REQUIREMENTS.md is what the song NEEDS, not
  what THIS MACHINE has).

Pure-Python module — no MCP calls. The push skill orchestrates the MCP
probe (``ableton_browser(action='plugins_list')``) and hands the result
to this module via ``--installed-plugins``, matching the rest of
``sync/`` discipline (plans, not side effects).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from hallucinote.db import queries as Q, resolve_db_path
from hallucinote.db.connection import connect


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
    "native",                  # Live built-in — no install needed.
    "placeholder",             # Author intentionally left this slot empty.
    "third_party_ok",          # Plugin needed AND found in the installed list.
    "third_party_missing",     # Plugin needed AND not found in the installed list.
    "third_party_unverified",  # Plugin needed AND no installed list was provided.
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


@dataclass
class CompatReport:
    """Structured result of one ``check_song`` run.

    The five status buckets cover every device in the song's DB. The
    ``has_issues`` flag is what the push-preflight gate keys off: True
    means "stop and ask the user before pushing."
    """
    song_slug: str
    song_title: str | None
    entries: list[DeviceEntry] = field(default_factory=list)
    installed_provided: bool = False  # Was --installed-plugins given?

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
    def has_issues(self) -> bool:
        """True iff the push-preflight gate should refuse-and-confirm.

        Missing plugins ARE issues. Unverified plugins ARE issues too
        (the operator should explicitly confirm rather than discover at
        load time). Placeholders are NOT issues — they're intentional.
        """
        return bool(self.missing or self.unverified)

    def to_json(self) -> dict:
        return {
            "song_slug": self.song_slug,
            "song_title": self.song_title,
            "installed_provided": self.installed_provided,
            "entries": [asdict(e) for e in self.entries],
            "summary": {
                "total": len(self.entries),
                "native": len(self.native),
                "placeholders": len(self.placeholders),
                "third_party_ok": len(self.third_party_ok),
                "missing": len(self.missing),
                "unverified": len(self.unverified),
                "has_issues": self.has_issues,
            },
        }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


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
    """
    conn = connect(db_path)
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
) -> None:
    """Recursively walk a device chain, classifying each device.

    Nested racks (DrumGroupDevice / InstrumentGroupDevice /
    AudioEffectGroupDevice) carry their own inner chains via
    ``device_chains.parent_rack_device_id``. Recurse so plugin-inside-
    rack is detected.
    """
    devices = Q.get_devices_for_chain(conn, chain["id"])
    for d in devices:
        status, lookup = classify_device(
            d["kind"],
            display_name=d["display_name"],
            installed_plugin_names=installed_names,
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
        ))
        for inner in Q.get_device_chains_for_rack_device(conn, d["id"]):
            _walk_chain(
                conn, inner,
                parent_label=f"{parent_label} / {d['display_name']}",
                track_name=track_name,
                report=report, installed_names=installed_names,
            )


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
        legacy = Path("songs") / slug / f"{slug}.db"
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


def _cmd_check(args: argparse.Namespace) -> int:
    db_path = _resolve_db(args.song)
    installed: list[dict] | None = None
    if args.installed_plugins:
        installed = _load_installed_plugins(Path(args.installed_plugins))
    report = check_song(db_path, installed_plugins=installed)
    json.dump(report.to_json(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 1 if report.has_issues else 0


def _cmd_write_requirements(args: argparse.Namespace) -> int:
    db_path = _resolve_db(args.song)
    # write_requirements is author-side: ignore installed_plugins
    # (REQUIREMENTS.md is consumer-side-agnostic). All third-party
    # plugins surface as 'third_party_unverified' which the formatter
    # treats identically to missing/ok in the required-plugins section.
    report = check_song(db_path, installed_plugins=None)
    out_path = Path("songs") / args.song / "REQUIREMENTS.md"
    if not out_path.parent.exists():
        raise SystemExit(
            f"compat: songs/{args.song}/ does not exist — wrong slug?"
        )
    content = format_requirements_md(report)
    out_path.write_text(content)
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
