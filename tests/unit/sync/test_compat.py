"""Tests for src/hallucinote/sync/compat.py — cross-machine portability.

Covers all five status branches of classify_device, the song-walk including
nested rack chains, REQUIREMENTS.md formatting, and the CLI exit-code
contract that the push-preflight gate keys off — and the same three for the
second family, the samples an audio clip's ``audio_file`` names.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import get_args

import pytest

from hallucinote.db import connect, init_db, mutations as M
from hallucinote.sync import compat as C


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "song.db"
    conn = init_db(path)
    conn.close()
    return path


@pytest.fixture
def conn(db_path: Path) -> sqlite3.Connection:
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def song(conn) -> str:
    return M.create_song(conn, name="test-song", title="Test Song", key="C")


@pytest.fixture
def track(conn, song) -> str:
    return M.create_track(conn, song_id=song, track_index=1, name="Lead")


@pytest.fixture
def track_chain(conn, track) -> str:
    return M.create_device_chain(conn, parent_track_id=track)


# ---------------------------------------------------------------------------
# Plugin-class discriminator + classify_device
# ---------------------------------------------------------------------------


def test_plugin_classes_lock_matches_mcp_side():
    """The set of plugin-wrapper class names must agree with the MCP side.

    If MCP says a device is third-party (is_third_party_plugin) and compat
    doesn't, push silently misroutes. Lock-test pins the canonical set —
    if Live exposes a new wrapper class, update BOTH sides.
    """
    assert C._PLUGIN_CLASSES == frozenset({
        "PluginDevice", "AuPluginDevice", "Vst3PluginDevice",
    })


def test_is_plugin_class_exact_match():
    assert C._is_plugin_class("PluginDevice")
    assert C._is_plugin_class("AuPluginDevice")
    assert C._is_plugin_class("Vst3PluginDevice")


def test_is_plugin_class_substring_for_future_versions():
    """Future Live versions might add Vst4PluginDevice etc.; substring catches them."""
    assert C._is_plugin_class("Vst4PluginDevice")
    assert C._is_plugin_class("ImaginaryPluginDevice")


def test_classify_device_substring_branch_routes_to_third_party():
    """The substring branch ('Plugin' in class_name) must classify the
    same as the explicit-set branch — both feed third-party status.

    Pairs with test_plugin_classes_lock_matches_mcp_side to pin BOTH
    halves of the discriminator. Without this, a future Live release
    that introduces a new ``*PluginDevice`` class would silently route
    to ``native`` if the lock-test only pinned the explicit set.
    """
    status, lookup = C.classify_device(
        "Vst4PluginDevice", display_name="Hypothetical Plugin",
        installed_plugin_names=None,
    )
    assert status == "third_party_unverified"
    assert lookup == "Hypothetical Plugin"


def test_is_plugin_class_rejects_native():
    for native in ("Operator", "Eq8", "Drum Rack", "Compressor2",
                   "InstrumentMeld", "LoungeLizard", "Reverb"):
        assert not C._is_plugin_class(native), native


def test_classify_device_native():
    status, lookup = C.classify_device(
        "Operator", display_name="Operator", installed_plugin_names=None,
    )
    assert status == "native"
    assert lookup is None


def test_classify_device_placeholder():
    status, lookup = C.classify_device(
        "placeholder", display_name="future pad",
        installed_plugin_names=None,
    )
    assert status == "placeholder"
    assert lookup is None


def test_classify_device_third_party_unverified_when_no_list():
    """No installed-plugins list provided → cannot prove missing → flag unverified."""
    status, lookup = C.classify_device(
        "PluginDevice", display_name="Spitfire LABS Soft Piano",
        installed_plugin_names=None,
    )
    assert status == "third_party_unverified"
    assert lookup == "Spitfire LABS Soft Piano"


def test_classify_device_third_party_ok_exact_match():
    status, _ = C.classify_device(
        "PluginDevice", display_name="Serum",
        installed_plugin_names=frozenset({"Serum"}),
    )
    assert status == "third_party_ok"


def test_classify_device_third_party_ok_substring_either_direction():
    """Author's name shorter than installed name."""
    status, _ = C.classify_device(
        "PluginDevice", display_name="Spitfire LABS",
        installed_plugin_names=frozenset({"Spitfire LABS Soft Piano (VST3)"}),
    )
    assert status == "third_party_ok"


def test_classify_device_third_party_ok_substring_reversed():
    """Installed name shorter than author's name (preset name)."""
    status, _ = C.classify_device(
        "PluginDevice", display_name="My Custom Serum Patch v2",
        installed_plugin_names=frozenset({"Serum"}),
    )
    assert status == "third_party_ok"


def test_classify_device_third_party_ok_case_insensitive():
    status, _ = C.classify_device(
        "AuPluginDevice", display_name="DIVA",
        installed_plugin_names=frozenset({"u-he Diva"}),
    )
    assert status == "third_party_ok"


def test_classify_device_third_party_missing():
    status, lookup = C.classify_device(
        "PluginDevice", display_name="Massive X",
        installed_plugin_names=frozenset({"Serum", "Operator"}),
    )
    assert status == "third_party_missing"
    assert lookup == "Massive X"


def test_classify_device_empty_display_name_fails_closed():
    """Empty/whitespace display_name has no signal to match against.
    Without this guard, `'' in any_string` is True and the device
    would falsely match the first installed plugin as third_party_ok.
    """
    status, lookup = C.classify_device(
        "PluginDevice", display_name="",
        installed_plugin_names=frozenset({"Serum"}),
    )
    assert status == "third_party_missing"
    assert lookup == ""

    status_ws, _ = C.classify_device(
        "PluginDevice", display_name="   ",
        installed_plugin_names=frozenset({"Serum"}),
    )
    assert status_ws == "third_party_missing"


def test_classify_device_au_plugin_class():
    status, _ = C.classify_device(
        "AuPluginDevice", display_name="Omnisphere",
        installed_plugin_names=frozenset({"Omnisphere 2"}),
    )
    assert status == "third_party_ok"


# ---------------------------------------------------------------------------
# check_song — DB walk
# ---------------------------------------------------------------------------


def test_check_song_empty(conn, song, db_path):
    report = C.check_song(db_path)
    assert report.song_slug == "test-song"
    assert report.song_title == "Test Song"
    assert report.entries == []
    assert not report.has_issues
    assert not report.installed_provided


def test_check_song_all_native(conn, song, track_chain, db_path):
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="Operator", display_name="Operator")
    M.create_device(conn, chain_id=track_chain, position=2,
                    kind="EQ Eight", display_name="EQ Eight")
    conn.commit()
    report = C.check_song(db_path)
    assert len(report.entries) == 2
    assert {e.status for e in report.entries} == {"native"}
    assert not report.has_issues


def test_check_song_placeholder_does_not_create_issue(
    conn, song, track_chain, db_path,
):
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="placeholder",
                    display_name="future warm pad slot")
    conn.commit()
    report = C.check_song(db_path)
    assert len(report.placeholders) == 1
    assert report.placeholders[0].kind == "placeholder"
    assert not report.has_issues  # placeholders are intentional


def test_check_song_third_party_without_installed_list(
    conn, song, track_chain, db_path,
):
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="PluginDevice", display_name="Serum")
    conn.commit()
    report = C.check_song(db_path)
    assert len(report.unverified) == 1
    assert report.has_issues  # unverified → user must confirm


def test_check_song_third_party_with_installed_list_ok(
    conn, song, track_chain, db_path,
):
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="PluginDevice", display_name="Serum")
    conn.commit()
    report = C.check_song(
        db_path,
        installed_plugins=[{"name": "Serum", "uri": "query:plugins#1"}],
    )
    assert len(report.third_party_ok) == 1
    assert not report.has_issues
    assert report.installed_provided


def test_check_song_third_party_missing(conn, song, track_chain, db_path):
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="PluginDevice", display_name="Massive X")
    conn.commit()
    report = C.check_song(
        db_path,
        installed_plugins=[{"name": "Serum", "uri": "query:plugins#1"}],
    )
    assert len(report.missing) == 1
    assert report.missing[0].lookup_name == "Massive X"
    assert report.has_issues


def test_check_song_third_party_post_d4_shape_classifies_via_class_name(
    conn, song, track_chain, db_path,
):
    """Arc 4 / D4: under the post-D4 convention, third-party plugins
    have `kind` = plugin display name (e.g. ``'Serum'``) and
    `class_name` = wrapper class (e.g. ``'PluginDevice'``). Plugin
    discrimination must key off `class_name`, NOT `kind` — otherwise
    `_is_plugin_class('Serum')` returns False and the plugin would
    silently classify as a Live built-in.

    Pins the classifier's read of `class_name`. Without this, a
    refactor that accidentally restored kind-based discrimination
    would let plugins ship as native in the report — the documented
    snapshot-schema warning would then be the only safety net.
    """
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Serum", display_name="Serum",
        class_name="PluginDevice",
    )
    conn.commit()
    report = C.check_song(
        db_path,
        installed_plugins=[{"name": "Serum", "uri": "query:plugins#1"}],
    )
    assert len(report.third_party_ok) == 1
    assert report.third_party_ok[0].kind == "Serum"
    assert not report.native, (
        f"plugin classified as native: {report.native!r}"
    )


def test_check_song_skips_master_track(conn, song, db_path):
    """Master tracks don't carry devices via tracks.devices — skip cleanly."""
    M.create_track(conn, song_id=song, track_index=99, name="Master", kind="master")
    conn.commit()
    report = C.check_song(db_path)
    assert report.entries == []  # no devices anywhere; master row ignored


def test_check_song_walks_return_chains(conn, song, db_path):
    ret = M.create_return(conn, song_id=song, name="Reverb", position=1)
    chain = M.create_device_chain(conn, parent_return_id=ret)
    M.create_device(conn, chain_id=chain, position=1,
                    kind="Reverb", display_name="Reverb")
    M.create_device(conn, chain_id=chain, position=2,
                    kind="PluginDevice", display_name="Valhalla VintageVerb")
    conn.commit()
    report = C.check_song(db_path)
    assert len(report.entries) == 2
    assert report.entries[0].track_name == "Reverb"  # return name
    assert report.entries[1].status == "third_party_unverified"


def test_check_song_recurses_into_nested_rack_chains(
    conn, song, track_chain, db_path,
):
    """Plugin-inside-rack: an FX rack wrapping a third-party plugin must
    be detected, not hidden by the rack wrapper.
    """
    rack_id = M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Audio Effect Rack", display_name="My FX Rack",
    )
    inner_chain = M.create_device_chain(conn, parent_rack_device_id=rack_id)
    M.create_device(
        conn, chain_id=inner_chain, position=1,
        kind="PluginDevice", display_name="OTT",
    )
    conn.commit()
    report = C.check_song(db_path)
    statuses = [e.status for e in report.entries]
    kinds = [e.kind for e in report.entries]
    assert "Audio Effect Rack" in kinds
    assert "PluginDevice" in kinds
    assert "third_party_unverified" in statuses
    # The inner device's chain_path captures the rack so the user can
    # see where to install (matches REQUIREMENTS.md format).
    plugin_entry = next(e for e in report.entries if e.kind == "PluginDevice")
    assert "My FX Rack" in plugin_entry.chain_path


def test_check_song_rejects_multi_song_db(conn, song, db_path):
    """One-DB-per-song is a prescriptive invariant — reject multi-song DBs."""
    M.create_song(conn, name="other-song", key="D")
    conn.commit()
    with pytest.raises(ValueError, match="2 song rows"):
        C.check_song(db_path)


def test_check_song_accepts_bare_list_installed_plugins(
    conn, song, track_chain, db_path,
):
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="PluginDevice", display_name="Serum")
    conn.commit()
    # MCP wraps with {"plugins": [...], "count": N} but tests/hand-crafted
    # lists pass a bare list. check_song takes the unwrapped list — the
    # CLI helper does the unwrap.
    report = C.check_song(
        db_path,
        installed_plugins=[{"name": "Serum"}],
    )
    assert len(report.third_party_ok) == 1


# ---------------------------------------------------------------------------
# CompatReport JSON shape
# ---------------------------------------------------------------------------


def test_compat_report_to_json_shape(conn, song, track_chain, db_path):
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="Operator", display_name="Operator")
    M.create_device(conn, chain_id=track_chain, position=2,
                    kind="placeholder", display_name="future pad")
    M.create_device(conn, chain_id=track_chain, position=3,
                    kind="PluginDevice", display_name="Serum")
    conn.commit()
    report = C.check_song(db_path)
    data = report.to_json()
    assert data["song_slug"] == "test-song"
    assert data["installed_provided"] is False
    assert data["summary"] == {
        "total": 3, "native": 1, "placeholders": 1,
        "third_party_ok": 0, "missing": 0, "unverified": 1,
        "preset_query_invalid": 0, "kind_unresolvable": 0,
        "kind_ambiguous": 0, "preset_query_unverified": 0,
        "samples_total": 0, "samples_ok": 0, "samples_missing": 0,
        "samples_unreadable": 0, "samples_not_a_file": 0,
        "samples_unresolvable": 0,
        "has_issues": True,
    }
    # The device counts still count devices only — the sample family carries
    # its own numbers rather than widening one of these.
    assert data["samples"] == []
    assert len(data["entries"]) == 3
    # Entries are dicts after asdict()
    for e in data["entries"]:
        assert "status" in e and "kind" in e and "display_name" in e


# ---------------------------------------------------------------------------
# REQUIREMENTS.md formatter
# ---------------------------------------------------------------------------


def test_format_requirements_md_no_third_party(conn, song, track_chain, db_path):
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="Operator", display_name="Operator")
    conn.commit()
    report = C.check_song(db_path)
    md = C.format_requirements_md(report)
    assert "# Requirements — Test Song" in md
    assert "Required third-party plugins" in md
    assert "None." in md
    assert "Live built-in devices" in md
    assert "`Operator`" in md


def test_format_requirements_md_with_plugins(conn, song, track_chain, db_path):
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="PluginDevice", display_name="Serum")
    M.create_device(conn, chain_id=track_chain, position=2,
                    kind="AuPluginDevice", display_name="Omnisphere 2")
    conn.commit()
    report = C.check_song(db_path)
    md = C.format_requirements_md(report)
    assert "**Serum**" in md
    assert "**Omnisphere 2**" in md
    # Each lists its location for the consumer.
    assert "position 1" in md
    assert "position 2" in md


def test_format_requirements_md_groups_repeated_plugin_uses(
    conn, song, track_chain, db_path,
):
    """A plugin used on multiple tracks appears once in the required list
    with each use enumerated."""
    track2 = M.create_track(conn, song_id=song, track_index=2, name="Pad")
    chain2 = M.create_device_chain(conn, parent_track_id=track2)
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="PluginDevice", display_name="Serum")
    M.create_device(conn, chain_id=chain2, position=1,
                    kind="PluginDevice", display_name="Serum")
    conn.commit()
    report = C.check_song(db_path)
    md = C.format_requirements_md(report)
    # The plugin header appears once; both use sites listed beneath.
    assert md.count("**Serum**") == 1
    assert "Lead" in md
    assert "Pad" in md


def test_format_requirements_md_includes_placeholder_section(
    conn, song, track_chain, db_path,
):
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="placeholder",
                    display_name="warm pad slot")
    conn.commit()
    report = C.check_song(db_path)
    md = C.format_requirements_md(report)
    assert "Author-intentional placeholders" in md
    assert "warm pad slot" in md


def test_format_requirements_md_lists_preset_query_unverified(
    conn, song, track_chain, db_path,
):
    """A structurally-valid preset_query with no dry-run map lands in
    ``preset_query_unverified`` — and must still be NAMED in the file.

    Before the fix that bucket was rendered by no section, so the device
    appeared nowhere: REQUIREMENTS.md read "None. This song uses only
    Live's built-in devices" while ``has_issues`` refused the push on the
    very same report. ``regen_requirements`` never passes
    ``browser_dry_runs``, so on the sole write path EVERY structurally-valid
    preset_query device lands here.
    """
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Operator", display_name="Bass Pluck Slot",
        preset_query={"root": "instruments", "pattern": "Bass-Pluck"},
    )
    conn.commit()
    report = C.check_song(db_path)
    assert len(report.preset_query_unverified) == 1

    md = C.format_requirements_md(report)
    assert "preset_query authoring issues" in md
    assert "Bass Pluck Slot" in md
    assert "_preset_query_unverified_" in md
    # Framed as unresolved — NOT as a load-time refusal the report can't
    # stand behind (nothing was checked, so nothing is known to fail).
    assert "never resolved against a browser" in md
    assert "will refuse at load time" not in md


def test_format_requirements_md_separates_refusals_from_unverified(
    conn, song, track_chain, db_path,
):
    """Refusals and unverified rows share the heading, keep their framing.

    The refusal sentence is a claim about load-time behaviour; applying it
    to a selector nobody resolved would overstate what compat knows.
    """
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Operator", display_name="Broken Selector",
        preset_query={"root": "not-a-root", "pattern": "x"},
    )
    M.create_device(
        conn, chain_id=track_chain, position=2,
        kind="Operator", display_name="Unchecked Selector",
        preset_query={"root": "instruments", "pattern": "Bass-Pluck"},
    )
    conn.commit()
    report = C.check_song(db_path)
    assert len(report.preset_query_invalid) == 1
    assert len(report.preset_query_unverified) == 1

    md = C.format_requirements_md(report)
    assert md.count("## preset_query authoring issues") == 1
    assert "Broken Selector" in md
    assert "Unchecked Selector" in md
    assert "will refuse at load time" in md
    assert "never resolved against a browser" in md


def test_format_requirements_md_names_every_device_status(
    conn, song, track_chain, db_path,
):
    """The DeviceStatus caller contract: the REQUIREMENTS.md generator
    "MUST handle each value explicitly". No status may render to silence.

    Every status reachable from the sole write path is exercised here —
    ``regen_requirements`` calls ``check_song`` with neither
    ``installed_plugins`` nor ``browser_dry_runs``, which is exactly this
    call. The bucket count is pinned against the enum so a newly added
    status fails here until the generator is taught to render it.
    """
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="Operator", display_name="Warm Keys")
    M.create_device(conn, chain_id=track_chain, position=2,
                    kind="placeholder", display_name="warm pad slot")
    M.create_device(conn, chain_id=track_chain, position=3,
                    kind="PluginDevice", display_name="Serum")
    M.create_device(
        conn, chain_id=track_chain, position=4,
        kind="Operator", display_name="Bass Pluck Slot",
        preset_query={"root": "instruments", "pattern": "Bass-Pluck"},
    )
    conn.commit()
    report = C.check_song(db_path)

    buckets = {
        "native": report.native,
        "placeholder": report.placeholders,
        "third_party_ok": report.third_party_ok,
        "third_party_missing": report.missing,
        "third_party_unverified": report.unverified,
        "preset_query_invalid": report.preset_query_invalid,
        "kind_unresolvable": report.kind_unresolvable,
        "kind_ambiguous": report.kind_ambiguous,
        "preset_query_unverified": report.preset_query_unverified,
    }
    assert set(buckets) == set(get_args(C.DeviceStatus))

    md = C.format_requirements_md(report)
    # Natives are summarised by kind; the rest are named individually.
    assert "`Operator`" in md
    for name in ("warm pad slot", "Serum", "Bass Pluck Slot"):
        assert name in md, f"{name} is in the report but named nowhere in the file"


# ---------------------------------------------------------------------------
# CLI — exit codes + I/O contract
# ---------------------------------------------------------------------------


def test_cli_check_clean_song_exits_zero(
    monkeypatch, capsys, tmp_path, conn, song, track_chain,
):
    """compat check on a song with only native devices → exit 0."""
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="Operator", display_name="Operator")
    conn.commit()
    db_path = Path(conn.execute("PRAGMA database_list").fetchall()[0]["file"])
    monkeypatch.setattr(C, "resolve_db_path",
                        lambda slug, **kw: db_path)
    rc = C.main(["check", "test-song"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["summary"]["has_issues"] is False


def test_cli_check_exits_one_when_unverified(
    monkeypatch, capsys, conn, song, track_chain,
):
    """compat check on a song with un-cross-checked plugins → exit 1."""
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="PluginDevice", display_name="Serum")
    conn.commit()
    db_path = Path(conn.execute("PRAGMA database_list").fetchall()[0]["file"])
    monkeypatch.setattr(C, "resolve_db_path", lambda slug, **kw: db_path)
    rc = C.main(["check", "test-song"])
    assert rc == 1


def test_cli_check_with_installed_plugins_resolves(
    monkeypatch, capsys, conn, song, track_chain, tmp_path,
):
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="PluginDevice", display_name="Serum")
    conn.commit()
    db_path = Path(conn.execute("PRAGMA database_list").fetchall()[0]["file"])
    monkeypatch.setattr(C, "resolve_db_path", lambda slug, **kw: db_path)
    plugins_file = tmp_path / "plugins.json"
    plugins_file.write_text(json.dumps(
        {"plugins": [{"name": "Serum", "uri": "query:1"}], "count": 1}
    ))
    rc = C.main([
        "check", "test-song",
        "--installed-plugins", str(plugins_file),
    ])
    assert rc == 0  # Serum is installed
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["summary"]["third_party_ok"] == 1


def test_cli_write_requirements_creates_file(
    monkeypatch, tmp_path, conn, song, track_chain,
):
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="PluginDevice", display_name="Serum")
    conn.commit()
    db_path = Path(conn.execute("PRAGMA database_list").fetchall()[0]["file"])

    # Stage a temp songs/<slug>/ dir so the write target exists.
    songs_root = tmp_path / "songs"
    (songs_root / "test-song").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(C, "resolve_db_path", lambda slug, **kw: db_path)

    rc = C.main(["write-requirements", "test-song"])
    assert rc == 0
    out_file = songs_root / "test-song" / "REQUIREMENTS.md"
    assert out_file.exists()
    md = out_file.read_text()
    assert "**Serum**" in md
    assert "test-song" in md


def test_load_installed_plugins_accepts_wrapper_shape(tmp_path):
    path = tmp_path / "plugins.json"
    path.write_text(json.dumps(
        {"plugins": [{"name": "A"}, {"name": "B"}], "count": 2}
    ))
    result = C._load_installed_plugins(path)
    assert result == [{"name": "A"}, {"name": "B"}]


def test_load_installed_plugins_accepts_bare_list(tmp_path):
    path = tmp_path / "plugins.json"
    path.write_text(json.dumps([{"name": "A"}]))
    result = C._load_installed_plugins(path)
    assert result == [{"name": "A"}]


def test_load_installed_plugins_rejects_garbage(tmp_path):
    path = tmp_path / "plugins.json"
    path.write_text(json.dumps({"not": "a plugins list"}))
    with pytest.raises(SystemExit, match="must be a list"):
        C._load_installed_plugins(path)


# ---------------------------------------------------------------------------
# R-2.1: preset_query structural validation + dry-run resolution
# ---------------------------------------------------------------------------


def test_valid_browser_roots_lock_matches_mcp_side():
    """The set of valid browser roots in compat must agree with the MCP
    server's ``_ROOTS`` enum. Authors typo this surprisingly often (the
    resource URI uses 'effects', the loader uses 'audio_effects'), so a
    structural drift between the two sides would let typos slip through
    compat unnoticed.
    """
    from hallucinote_mcp.actions.browser import _ROOTS as MCP_ROOTS
    assert C._VALID_BROWSER_ROOTS == frozenset(MCP_ROOTS), (
        "compat._VALID_BROWSER_ROOTS drifted from "
        "hallucinote_mcp.actions.browser._ROOTS — update the compat side "
        "if the MCP side gained or dropped a root."
    )


def test_name_matches_matches_mcp_side():
    """The offline matcher (hallucinote.preset_query.name_matches) must agree
    with the MCP push-time matcher (hallucinote_mcp.handlers.browser.
    _name_matches) on every case. They are mirror implementations across the
    Remote-Script package boundary (the MCP side can't import the domain
    package, so they can't share one function); divergence would let an
    offline-authored preset_query resolve differently than push does.
    """
    from hallucinote_mcp.handlers.browser import _name_matches as mcp_match
    from hallucinote.preset_query import name_matches as domain_match

    cases = [
        ("Kit-Core 909", "909", "substring", False),
        ("Kit-Core 909", "CORE", "substring", False),
        ("Kit-Core 909", "core", "substring", True),
        ("Kit-Core 909", "808", "substring", False),
        ("Hot Rod Kit", "Hot*Kit", "glob", False),
        ("Hot Rod Kit", "hot*kit", "glob", True),
        ("Kit-Core 909", r"\d{3}", "regex", False),
        ("Kit-Core", r"\d{3}", "regex", False),
        ("EQ Eight", "eq", "substring", False),
        # exact: anchored whole-name equality (the substring-collision fix).
        ("Saturated Bass", "Saturated Bass", "exact", False),
        ("Basic Saturated Bass", "Saturated Bass", "exact", False),
        ("Saturated Bass", "saturated bass", "exact", False),
        ("Saturated Bass", "saturated bass", "exact", True),
    ]
    for name, pattern, mode, cs in cases:
        assert domain_match(name, pattern, mode, cs) == mcp_match(
            name, pattern, mode, cs
        ), f"matcher drift on {(name, pattern, mode, cs)!r}"


def test_resolve_query_matches_mcp_resolver_over_shared_fixture():
    """The offline resolver (preset_query.resolve_query, over flattened cache
    entries) must reach the SAME verdict as the push-time resolver
    (hallucinote_mcp.handlers.device._resolve_preset_query, over a live browser
    tree) for every query — single-match, 0-match, 2+-ambiguity, and
    path_prefix hit/miss. They are hand-maintained mirrors across the
    Remote-Script package boundary; this drives both over ONE shared fixture
    (a fake browser tree + its flattened-inventory equivalent) and asserts
    agreement, so drift in either resolver's ambiguity/prefix semantics fails
    here. Complements the name_matches + walk-depth locks above.
    """
    import types

    from hallucinote_mcp.handlers.device import _resolve_preset_query
    from hallucinote.preset_query import resolve_query

    def N(name, *, loadable=False, uri=None, children=()):
        return types.SimpleNamespace(
            name=name, uri=uri, is_loadable=loadable,
            is_folder=not loadable, children=list(children),
        )

    browser = types.SimpleNamespace(
        drums=N("Drums", children=[
            N("Kit-Core 909", loadable=True, uri="q909"),
            N("Kit-Core 808", loadable=True, uri="q808"),
            N("Acoustic", children=[N("Brush Kit", loadable=True, uri="qbrush")]),
            # Substring-collision pair: exact mode must disambiguate.
            N("Saturated Bass", loadable=True, uri="qsat"),
            N("Basic Saturated Bass", loadable=True, uri="qbasicsat"),
        ]),
        instruments=N("Instruments", children=[
            N("Operator", loadable=True, uri="qop", children=[
                N("Bass", children=[N("Sub", loadable=True, uri="qsub")]),
            ]),
            N("Wavetable", loadable=True, uri="qwt", children=[
                N("Bass", children=[N("Sub", loadable=True, uri="qwtsub")]),
            ]),
        ]),
    )

    # Flatten the SAME tree the way the inventory walk does: recurse past
    # loadables, full path rooted at the root KEY.
    entries: list[dict] = []

    def _flatten(node, path):
        if node.is_loadable:
            entries.append({
                "root": path[0], "path": list(path), "name": node.name,
                "uri": node.uri, "is_loadable": True,
            })
        for c in node.children:
            _flatten(c, path + [c.name])

    _flatten(browser.drums, ["drums"])
    _flatten(browser.instruments, ["instruments"])

    def _mcp(q):
        try:
            item, path = _resolve_preset_query(browser, q)
            return ("ok", str(item.name), tuple(path))
        except ValueError:
            return ("error",)

    def _offline(q):
        try:
            e = resolve_query(q, entries)
            return ("ok", e["name"], tuple(e["path"]))
        except ValueError:
            return ("error",)

    queries = [
        {"root": "drums", "pattern": "909"},                       # single
        {"root": "drums", "pattern": "Kit-Core"},                  # 2+ ambiguous
        {"root": "drums", "pattern": "nonexistent-xyz"},           # 0 match
        {"root": "drums", "pattern": "Brush"},                     # single, nested
        {"root": "instruments", "pattern": "Sub"},                 # 2+ (Operator+Wavetable)
        {"root": "instruments", "pattern": "Sub",
         "path_prefix": ["Operator", "Bass"]},                     # single via prefix
        {"root": "instruments", "pattern": "Sub",
         "path_prefix": ["Meld"]},                                 # prefix missing
        {"root": "drums", "pattern": "Saturated Bass"},            # substring → 2+ ambiguous
        {"root": "drums", "pattern": "Saturated Bass",
         "mode": "exact"},                                         # exact → single
        {"root": "drums", "pattern": "Basic Saturated Bass",
         "mode": "exact"},                                         # exact → the superstring one
    ]
    for q in queries:
        assert _mcp(q) == _offline(q), f"resolver disagreement on {q!r}"


def test_browser_walk_depth_matches_mcp_side():
    """An offline inventory cache MUST be walked at least as deep as the MCP
    push-time resolver walks the live browser, or offline resolution can miss
    a loadable that push would find. preset_query.MIN_WALK_DEPTH is the
    contract the cache writer honors; pin it >= the MCP depth.
    """
    from hallucinote_mcp.handlers.device import _BROWSER_WALK_DEPTH
    from hallucinote.preset_query import MIN_WALK_DEPTH
    assert MIN_WALK_DEPTH >= _BROWSER_WALK_DEPTH, (
        f"preset_query.MIN_WALK_DEPTH ({MIN_WALK_DEPTH}) is shallower than the "
        f"MCP resolver's _BROWSER_WALK_DEPTH ({_BROWSER_WALK_DEPTH}); an "
        "inventory cache walked to MIN_WALK_DEPTH would miss loadables push "
        "can still reach. Raise MIN_WALK_DEPTH to match."
    )


def test_classify_preset_query_accepts_valid_structure():
    """root in enum + pattern str + path_prefix list → return None (no
    structural error; caller proceeds to dry-run)."""
    out = C.classify_preset_query(json.dumps({
        "root": "audio_effects",
        "pattern": "Hall",
        "path_prefix": ["Hybrid Reverb"],
    }))
    assert out is None


def test_classify_preset_query_rejects_root_typo():
    """The sun-zone-done typo: ``root='effects'`` (singular, browser-resource
    form) instead of ``'audio_effects'`` (loader-accepted enum). 8 of the
    13 push failures in that session came from this single typo."""
    status, detail = C.classify_preset_query(json.dumps({
        "root": "effects", "pattern": "Reverb",
    }))
    assert status == "preset_query_invalid"
    assert "audio_effects" in detail and "effects" in detail


def test_classify_preset_query_rejects_string_path_prefix():
    """The sun-zone-done shape error: ``path_prefix='Tension'`` (string)
    instead of ``['Tension']`` (list). Loader raises
    ``preset_query.path_prefix must be a list``; compat must surface this
    BEFORE the push attempt."""
    status, detail = C.classify_preset_query(json.dumps({
        "root": "instruments", "pattern": "Boom in E",
        "path_prefix": "Tension",
    }))
    assert status == "preset_query_invalid"
    assert "path_prefix" in detail and "list" in detail


def test_classify_preset_query_rejects_an_unknown_mode():
    """SYN-6Q3D put `mode` on the wire, which makes it structural: an unknown
    mode reaches the browser, the enum is rejected, and
    `_probe_browser_dry_runs` raises SystemExit — killing the WHOLE --probe
    report over one bad device. Catching it here flags that device instead."""
    status, detail = C.classify_preset_query(json.dumps({
        "root": "instruments", "pattern": "Pad", "mode": "fuzzy",
    }))
    assert status == "preset_query_invalid"
    assert "mode" in detail and "fuzzy" in detail


def test_classify_preset_query_rejects_a_non_boolean_case_sensitive():
    """`case_sensitive` rides the wire too, and `name_matches` takes a bool.
    A string here is the same class of authoring error as a string
    path_prefix."""
    status, detail = C.classify_preset_query(json.dumps({
        "root": "instruments", "pattern": "Pad", "case_sensitive": "yes",
    }))
    assert status == "preset_query_invalid"
    assert "case_sensitive" in detail


def test_classify_preset_query_accepts_every_supported_mode():
    """The validator must not become a second, stricter matcher — it imports
    `preset_query.SEARCH_MODES` precisely so it cannot drift from the loader."""
    from hallucinote.preset_query import SEARCH_MODES

    for mode in SEARCH_MODES:
        assert C.classify_preset_query(json.dumps({
            "root": "instruments", "pattern": "Pad", "mode": mode,
        })) is None, f"{mode!r} is a supported mode and must pass structurally"


def test_a_bad_mode_device_does_not_kill_the_whole_probe_report(
    conn, song, track_chain, db_path,
):
    """The point of validating structurally: one malformed device must not take
    down the report for every OTHER device. Before this, the bad mode reached
    `ableton_browser(action='search')`, the enum was rejected, and
    `_probe_browser_dry_runs` raised SystemExit for the whole song."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Operator", display_name="Bad",
        preset_query={"root": "instruments", "pattern": "Pad", "mode": "fuzzy"},
    )
    M.create_device(
        conn, chain_id=track_chain, position=2,
        kind="Operator", display_name="Good",
        preset_query={"root": "instruments", "pattern": "Bass-Pluck"},
    )
    conn.commit()
    # The fake routes ONLY the good query — so if the bad one reached the wire
    # it would raise AssertionError rather than pass silently.
    send = _fake_send_factory({
        ("instruments", "Bass-Pluck", (), "substring", False): 1,
    })

    runs = C._probe_browser_dry_runs(conn, send_fn=send)
    assert runs == {("instruments", "Bass-Pluck", (), "substring", False): 1}

    report = C.check_song(db_path, browser_dry_runs=runs)
    assert [e.display_name for e in report.preset_query_invalid] == ["Bad"]
    assert report.has_issues is True


def test_classify_preset_query_rejects_garbage_json():
    """Malformed JSON in the preset_query column → still classified as
    invalid (don't let a corrupted snapshot pass through silently)."""
    status, detail = C.classify_preset_query("not json {")
    assert status == "preset_query_invalid"
    assert "JSON" in detail


def test_classify_preset_query_rejects_missing_root():
    status, detail = C.classify_preset_query(json.dumps({"pattern": "x"}))
    assert status == "preset_query_invalid"
    assert "root" in detail


def test_classify_preset_query_passes_when_no_preset_query():
    """No preset_query → ``None`` so the kind-only classify_device path
    takes over."""
    assert C.classify_preset_query(None) is None


def test_check_song_classifies_invalid_root_at_compose_time(conn, song, track_chain, db_path):
    """End-to-end: a device authored with the typo'd ``root='effects'``
    lands in ``preset_query_invalid``, the report's ``has_issues`` is
    True, and the entry carries the diagnostic detail."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Reverb", display_name="Reverb",
        preset_query={"root": "effects", "pattern": "Hall"},
    )
    conn.commit()
    report = C.check_song(db_path)
    assert len(report.preset_query_invalid) == 1
    e = report.preset_query_invalid[0]
    assert e.kind == "Reverb"
    assert "audio_effects" in (e.detail or "")
    assert report.has_issues is True


def test_check_song_classifies_kind_ambiguous_with_dry_runs(conn, song, track_chain, db_path):
    """When ``browser_dry_runs`` reports 2+ matches for a preset_query,
    the device is ``kind_ambiguous`` and the loader would refuse at
    push time. Compat catches this at compose time and the detail names
    the match count."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Reverb", display_name="Reverb",
        preset_query={"root": "audio_effects", "pattern": "Hall",
                       "path_prefix": ["Hybrid Reverb"]},
    )
    conn.commit()
    dry_runs = {
        ("audio_effects", "Hall", ("Hybrid Reverb",), "substring", False): 12,
    }
    report = C.check_song(db_path, browser_dry_runs=dry_runs)
    assert len(report.kind_ambiguous) == 1
    e = report.kind_ambiguous[0]
    assert "12 matches" in (e.detail or "")
    assert report.has_issues is True
    assert report.browser_dry_runs_provided is True


def test_check_song_classifies_kind_unresolvable_on_zero_matches(conn, song, track_chain, db_path):
    """Dry-run reports 0 matches → ``kind_unresolvable``. The author's
    pattern (or path_prefix) doesn't exist on the consumer's machine."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Operator", display_name="Operator",
        preset_query={"root": "instruments", "pattern": "Nonexistent Preset"},
    )
    conn.commit()
    dry_runs = {("instruments", "Nonexistent Preset", (), "substring", False): 0}
    report = C.check_song(db_path, browser_dry_runs=dry_runs)
    assert len(report.kind_unresolvable) == 1
    assert report.has_issues is True


def test_check_song_classifies_single_match_as_native(conn, song, track_chain, db_path):
    """Dry-run reports exactly 1 match → the preset_query is resolvable;
    device falls through to the regular plugin-classifier (native here
    since Operator isn't a plugin wrapper)."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Operator", display_name="Operator",
        preset_query={"root": "instruments", "pattern": "Bass-Pluck"},
    )
    conn.commit()
    dry_runs = {("instruments", "Bass-Pluck", (), "substring", False): 1}
    report = C.check_song(db_path, browser_dry_runs=dry_runs)
    assert len(report.native) == 1
    assert report.has_issues is False


def test_check_song_classifies_unverified_when_no_dry_runs(conn, song, track_chain, db_path):
    """Structurally-valid preset_query without a dry-runs map →
    ``preset_query_unverified`` (parallel to ``third_party_unverified``).
    The operator must explicitly verify; treating it as resolved would
    be false confidence."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Operator", display_name="Operator",
        preset_query={"root": "instruments", "pattern": "Bass-Pluck"},
    )
    conn.commit()
    report = C.check_song(db_path)
    assert len(report.preset_query_unverified) == 1
    assert report.has_issues is True
    assert report.browser_dry_runs_provided is False


def test_check_song_preset_query_invalid_skips_dry_run(conn, song, track_chain, db_path):
    """When ``root`` is invalid we don't bother consulting the dry-runs
    cache (the loader will refuse on root anyway). The device lands in
    ``preset_query_invalid``, not ``kind_unresolvable``."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Reverb", display_name="Reverb",
        preset_query={"root": "effects", "pattern": "Hall"},
    )
    conn.commit()
    report = C.check_song(db_path, browser_dry_runs={})
    assert len(report.preset_query_invalid) == 1
    assert len(report.kind_unresolvable) == 0


def test_check_song_preset_query_takes_precedence_over_plugin_class(
    conn, song, track_chain, db_path,
):
    """A third-party plugin device authored with a typo'd preset_query
    surfaces as ``preset_query_invalid`` (loader refuses outright)
    rather than ``third_party_missing`` (the consumer needs the plugin).
    The structural error must be fixed FIRST or the plugin install
    won't help."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="PluginDevice", display_name="Serum",
        preset_query={"root": "effects", "pattern": "Wobble"},
    )
    conn.commit()
    report = C.check_song(db_path)
    assert len(report.preset_query_invalid) == 1
    assert len(report.missing) == 0
    assert len(report.unverified) == 0


# ---------------------------------------------------------------------------
# C1: --probe path (in-process MCP browser-search → browser_dry_runs map)
# ---------------------------------------------------------------------------


def _fake_send_factory(routes):
    """Build a fake send_fn that maps (root, pattern, path_prefix tuple) →
    response payload.

    ``routes`` is a dict keyed exactly like ``_dry_run_key`` output, with
    values either an int (treated as the ``count`` field) or a dict
    (used verbatim as the response result). Any unrouted call raises
    AssertionError so tests fail loud on accidental misses.
    """
    from hallucinote_mcp.wire import Response

    def _send(req):
        assert req.tool == "ableton_browser", req.tool
        assert req.action == "search", req.action
        params = req.params or {}
        key = (
            str(params.get("root", "")),
            str(params.get("pattern", "")),
            tuple(params.get("path_prefix") or []),
            str(params.get("mode", "substring")),
            bool(params.get("case_sensitive", False)),
        )
        if key not in routes:
            raise AssertionError(
                f"_fake_send_factory: unrouted browser.search params {params!r}; "
                f"routes={list(routes)!r}"
            )
        v = routes[key]
        if isinstance(v, int):
            result = {"matches": [], "count": v}
        elif isinstance(v, dict) and "ok" in v and not v["ok"]:
            return Response(ok=False, error=v.get("error", "fake failure"))
        else:
            result = v
        return Response(ok=True, result=result)

    return _send


def test_probe_browser_dry_runs_builds_map_from_devices(
    conn, song, track_chain, db_path,
):
    """Two distinct preset_queries → two search calls → two entries in
    the resulting dry-runs map. Counts come straight from each
    ``search`` response."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Operator", display_name="Operator",
        preset_query={"root": "instruments", "pattern": "Bass-Pluck"},
    )
    M.create_device(
        conn, chain_id=track_chain, position=2,
        kind="Reverb", display_name="Reverb",
        preset_query={"root": "audio_effects", "pattern": "Hall",
                       "path_prefix": ["Hybrid Reverb"]},
    )
    conn.commit()
    send = _fake_send_factory({
        ("instruments", "Bass-Pluck", (), "substring", False): 1,
        ("audio_effects", "Hall", ("Hybrid Reverb",), "substring", False): 3,
    })
    runs = C._probe_browser_dry_runs(conn, send_fn=send)
    assert runs == {
        ("instruments", "Bass-Pluck", (), "substring", False): 1,
        ("audio_effects", "Hall", ("Hybrid Reverb",), "substring", False): 3,
    }


def test_probe_browser_dry_runs_deduplicates_identical_queries(
    conn, song, track_chain, db_path,
):
    """Two devices with the same preset_query → exactly one browser
    search call. Same pattern as caching one search per unique key."""
    pq = {"root": "instruments", "pattern": "Pad"}
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Operator", display_name="Operator",
        preset_query=pq,
    )
    M.create_device(
        conn, chain_id=track_chain, position=2,
        kind="Operator", display_name="Operator (copy)",
        preset_query=pq,
    )
    conn.commit()
    call_count = 0
    base_send = _fake_send_factory({("instruments", "Pad", (), "substring", False): 7})

    def _counting_send(req):
        nonlocal call_count
        call_count += 1
        return base_send(req)

    runs = C._probe_browser_dry_runs(conn, send_fn=_counting_send)
    assert call_count == 1
    assert runs == {("instruments", "Pad", (), "substring", False): 7}


def test_probe_browser_dry_runs_skips_structurally_invalid_queries(
    conn, song, track_chain, db_path,
):
    """Invalid root ('effects' isn't a browser root) is filtered at the
    structural step — the probe doesn't waste a call on a query the
    loader would refuse anyway. The invalid device still surfaces
    later via check_song's ``preset_query_invalid`` bucket."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Reverb", display_name="Reverb",
        preset_query={"root": "effects", "pattern": "Hall"},
    )
    M.create_device(
        conn, chain_id=track_chain, position=2,
        kind="Operator", display_name="Operator",
        preset_query={"root": "instruments", "pattern": "Bass"},
    )
    conn.commit()
    send = _fake_send_factory({
        ("instruments", "Bass", (), "substring", False): 1,
    })
    runs = C._probe_browser_dry_runs(conn, send_fn=send)
    assert runs == {("instruments", "Bass", (), "substring", False): 1}


def test_probe_browser_dry_runs_handles_no_preset_queries(
    conn, song, track_chain, db_path,
):
    """A song with only kind-resolvable devices (no preset_query) →
    empty map, no MCP calls. The probe should be a no-op rather than
    fail trying to construct a Request with no params."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Operator", display_name="Operator",
    )
    conn.commit()

    def _explode(req):  # pragma: no cover — must not be called
        raise AssertionError(f"unexpected MCP call: {req!r}")

    runs = C._probe_browser_dry_runs(conn, send_fn=_explode)
    assert runs == {}


def test_probe_browser_dry_runs_raises_on_search_failure(
    conn, song, track_chain, db_path,
):
    """Any ``ok=False`` response from the browser search fails the
    whole probe loud — a partial map would silently surface as a clean
    report (missing entries → no kind_unresolvable signal). Naming the
    failing preset_query in the error helps the operator diagnose."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Operator", display_name="Operator",
        preset_query={"root": "instruments", "pattern": "Mystery"},
    )
    conn.commit()
    send = _fake_send_factory({
        ("instruments", "Mystery", (), "substring", False): {"ok": False, "error": "live not running"},
    })
    with pytest.raises(SystemExit, match="ableton_browser.*live not running"):
        C._probe_browser_dry_runs(conn, send_fn=send)


def test_cli_check_with_probe_flags_ambiguous_preset_query(
    monkeypatch, capsys, conn, song, track_chain,
):
    """End-to-end: --probe populates browser_dry_runs and the report
    reflects the count. count=2 on a preset_query → kind_ambiguous,
    has_issues=True, exit 1."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Reverb", display_name="Reverb",
        preset_query={"root": "audio_effects", "pattern": "Hall"},
    )
    conn.commit()
    db_path = Path(conn.execute("PRAGMA database_list").fetchall()[0]["file"])
    monkeypatch.setattr(C, "resolve_db_path", lambda slug, **kw: db_path)
    send = _fake_send_factory({("audio_effects", "Hall", (), "substring", False): 2})
    monkeypatch.setattr(C, "_resolve_send_fn", lambda: send)

    rc = C.main(["check", "test-song", "--probe"])
    assert rc == 1
    data = json.loads(capsys.readouterr().out)
    assert data["browser_dry_runs_provided"] is True
    assert data["summary"]["kind_ambiguous"] == 1


def test_cli_check_with_probe_resolves_single_match(
    monkeypatch, capsys, conn, song, track_chain,
):
    """count=1 on a structurally-valid native preset_query → no issues,
    exit 0. Confirms --probe doesn't *introduce* false-positive issues
    when the song's queries all resolve cleanly."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Operator", display_name="Operator",
        preset_query={"root": "instruments", "pattern": "Bass-Pluck"},
    )
    conn.commit()
    db_path = Path(conn.execute("PRAGMA database_list").fetchall()[0]["file"])
    monkeypatch.setattr(C, "resolve_db_path", lambda slug, **kw: db_path)
    send = _fake_send_factory({("instruments", "Bass-Pluck", (), "substring", False): 1})
    monkeypatch.setattr(C, "_resolve_send_fn", lambda: send)

    rc = C.main(["check", "test-song", "--probe"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["browser_dry_runs_provided"] is True
    assert data["summary"]["native"] == 1
    assert data["summary"]["kind_unresolvable"] == 0
    assert data["summary"]["kind_ambiguous"] == 0


def test_cli_check_probe_combines_with_installed_plugins(
    monkeypatch, capsys, conn, song, track_chain, tmp_path,
):
    """--probe and --installed-plugins are orthogonal data sources;
    using both populates both branches of the classifier. A plugin
    device with a valid preset_query that resolves cleanly AND whose
    plugin is installed → third_party_ok, exit 0."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="PluginDevice", display_name="Serum",
        preset_query={"root": "plugins", "pattern": "Serum"},
    )
    conn.commit()
    db_path = Path(conn.execute("PRAGMA database_list").fetchall()[0]["file"])
    monkeypatch.setattr(C, "resolve_db_path", lambda slug, **kw: db_path)
    plugins_file = tmp_path / "plugins.json"
    plugins_file.write_text(json.dumps(
        {"plugins": [{"name": "Serum", "uri": "query:1"}], "count": 1}
    ))
    send = _fake_send_factory({("plugins", "Serum", (), "substring", False): 1})
    monkeypatch.setattr(C, "_resolve_send_fn", lambda: send)

    rc = C.main([
        "check", "test-song", "--probe",
        "--installed-plugins", str(plugins_file),
    ])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["installed_provided"] is True
    assert data["browser_dry_runs_provided"] is True
    assert data["summary"]["third_party_ok"] == 1


# ---------------------------------------------------------------------------
# SYN-6Q3D — the gate must probe with the matcher the LOADER will use
#
# `_dry_run_key` omitted `mode`/`case_sensitive` and `_probe_browser_dry_runs`
# never sent them, so an `exact` query was probed with the browser's DEFAULT
# substring matcher. `the-argument`'s Rock Drums declares
# {root: drums, pattern: 'Kit-BigPunchy.adg', mode: 'exact'} — exact returns 1,
# substring returns 2 ('Kit-BigPunchy.adg' and 'MPE Kit-BigPunchy.adg') — so the
# gate refused `kind_ambiguous` and exited 1 on a device that loads perfectly.
# A gate disagreeing with the thing it gates is the worst kind.
# ---------------------------------------------------------------------------


def test_probe_sends_the_declared_mode_so_exact_is_not_probed_as_substring(
    conn, song, track_chain, db_path,
):
    """An `exact` preset_query must reach the browser AS exact.

    The fake routes on the wire params, so it only answers if `mode='exact'`
    was actually sent; the substring key carries the 2-match count that
    produced the false `kind_ambiguous`, and routing to it would fail the
    count assertion rather than pass silently.
    """
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="DrumGroupDevice", display_name="Rock Drums",
        preset_query={"root": "drums", "pattern": "Kit-BigPunchy.adg",
                      "mode": "exact"},
    )
    conn.commit()
    send = _fake_send_factory({
        ("drums", "Kit-BigPunchy.adg", (), "exact", False): 1,
        ("drums", "Kit-BigPunchy.adg", (), "substring", False): 2,
    })
    runs = C._probe_browser_dry_runs(conn, send_fn=send)

    assert runs == {("drums", "Kit-BigPunchy.adg", (), "exact", False): 1}


def test_exact_query_that_is_ambiguous_only_by_substring_is_not_refused(
    conn, song, track_chain, db_path,
):
    """End-to-end: the device that produced the false refusal now passes.

    This is the item's headline signal — `kind_ambiguous: 0` on a song that
    pushes and loads fine.
    """
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="DrumGroupDevice", display_name="Rock Drums",
        preset_query={"root": "drums", "pattern": "Kit-BigPunchy.adg",
                      "mode": "exact"},
    )
    conn.commit()
    dry_runs = {("drums", "Kit-BigPunchy.adg", (), "exact", False): 1}
    report = C.check_song(db_path, browser_dry_runs=dry_runs)

    assert len(report.kind_ambiguous) == 0
    assert report.has_issues is False


def test_a_genuinely_ambiguous_substring_query_is_still_refused(
    conn, song, track_chain, db_path,
):
    """The fix must not become a rubber stamp: a query that really does
    resolve to 2+ matches under its OWN declared matcher still refuses."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="DrumGroupDevice", display_name="Rock Drums",
        preset_query={"root": "drums", "pattern": "Kit-BigPunchy"},
    )
    conn.commit()
    dry_runs = {("drums", "Kit-BigPunchy", (), "substring", False): 2}
    report = C.check_song(db_path, browser_dry_runs=dry_runs)

    assert len(report.kind_ambiguous) == 1
    assert report.has_issues is True


def test_two_queries_differing_only_in_mode_do_not_share_a_match_count(
    conn, song, track_chain, db_path,
):
    """The quieter half of the defect: with `mode` outside the key, two
    devices whose preset_query differs ONLY in `mode` deduped onto one cache
    entry and shared a single match count — so one of them was classified on
    the other's answer."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Operator", display_name="Exact",
        preset_query={"root": "instruments", "pattern": "Pad", "mode": "exact"},
    )
    M.create_device(
        conn, chain_id=track_chain, position=2,
        kind="Operator", display_name="Substring",
        preset_query={"root": "instruments", "pattern": "Pad",
                      "mode": "substring"},
    )
    conn.commit()
    send = _fake_send_factory({
        ("instruments", "Pad", (), "exact", False): 1,
        ("instruments", "Pad", (), "substring", False): 9,
    })
    runs = C._probe_browser_dry_runs(conn, send_fn=send)

    assert runs == {
        ("instruments", "Pad", (), "exact", False): 1,
        ("instruments", "Pad", (), "substring", False): 9,
    }, "two matchers, two probes, two counts — never one shared entry"


def test_case_sensitive_is_carried_onto_the_wire_too(
    conn, song, track_chain, db_path,
):
    """`name_matches` takes `case_sensitive`, so the probe must send it or the
    gate classifies on a case-insensitive count the loader won't reproduce."""
    M.create_device(
        conn, chain_id=track_chain, position=1,
        kind="Operator", display_name="Bass",
        preset_query={"root": "instruments", "pattern": "bass-pluck",
                      "case_sensitive": True},
    )
    conn.commit()
    send = _fake_send_factory({
        ("instruments", "bass-pluck", (), "substring", True): 1,
    })
    runs = C._probe_browser_dry_runs(conn, send_fn=send)

    assert runs == {("instruments", "bass-pluck", (), "substring", True): 1}


def test_classify_preset_query_rejects_an_explicit_null_mode():
    """`{"mode": null}` is not an absent key: absent means "use the default",
    but an explicit null reaches `name_matches` and raises "unknown search mode
    None". A truthiness check would let it through — gate and loader must agree.
    """
    status, detail = C.classify_preset_query(json.dumps({
        "root": "instruments", "pattern": "Pad", "mode": None,
    }))
    assert status == "preset_query_invalid"
    assert "mode" in detail


def test_classify_preset_query_accepts_an_absent_mode():
    """The overwhelmingly common shape — no `mode` key at all — still means
    substring and must stay structurally valid."""
    assert C.classify_preset_query(json.dumps({
        "root": "instruments", "pattern": "Pad",
    })) is None


def test_an_explicit_null_case_sensitive_is_accepted_not_refused():
    """The mirror of the `mode` rule does NOT apply here, and the asymmetry is
    the point: `mode: null` reaches `name_matches` and raises, so the gate must
    reject it; `case_sensitive: null` degrades to False in every consumer, so
    rejecting it would make the gate stricter than the loader — refusing a song
    that loads fine, the exact failure SYN-6Q3D removed."""
    assert C.classify_preset_query(json.dumps({
        "root": "instruments", "pattern": "Pad", "case_sensitive": None,
    })) is None


def test_classify_preset_query_still_rejects_a_non_null_non_bool_case_sensitive():
    status, detail = C.classify_preset_query(json.dumps({
        "root": "instruments", "pattern": "Pad", "case_sensitive": "yes",
    }))
    assert status == "preset_query_invalid"
    assert "case_sensitive" in detail


# ---------------------------------------------------------------------------
# Sample references — classify_sample
# ---------------------------------------------------------------------------
#
# A song whose audio clip points at a moved sample used to pass this check
# clean and fail at push, where the clips phase resolves the same reference
# through the same resolver. These pin the second family: its own statuses,
# its own rendering, and a device path that does not know it exists.


_ROOT_READS_EVERYTHING = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses file permissions, so an unreadable file reads fine",
)


def _audio_track(conn, song, *, name="Vox", index=2) -> str:
    return M.create_track(
        conn, song_id=song, track_index=index, name=name, kind="audio",
    )


def _audio_clip(conn, track_id, *, ref, slot=1, name=None) -> str:
    return M.create_audio_clip(
        conn, track_id=track_id, slot=slot, length_beats=4.0,
        audio_file=ref, name=name,
    )


def test_sample_status_vocabulary_is_disjoint_from_device_status():
    """The two families never share a status string.

    A sample is not a device, and a status that decorated both rows would
    mean different things depending on which one it landed on — the exact
    overload this second family exists to avoid.
    """
    assert not set(get_args(C.SampleStatus)) & set(get_args(C.DeviceStatus))


def test_classify_sample_ok_for_a_readable_file(tmp_path):
    (tmp_path / "assets").mkdir()
    wav = tmp_path / "assets" / "line.wav"
    wav.write_bytes(b"RIFF")
    status, resolved, detail = C.classify_sample(
        "assets/line.wav", song_dir=tmp_path,
    )
    assert status == "sample_ok"
    assert resolved == wav
    assert detail is None


def test_classify_sample_missing_names_both_the_ref_and_the_path(tmp_path):
    status, resolved, detail = C.classify_sample(
        "assets/gone.wav", song_dir=tmp_path,
    )
    assert status == "sample_missing"
    assert resolved == tmp_path / "assets" / "gone.wav"
    # Never a bare "None": the reference to re-point AND the path that was
    # looked for, because which of the two is wrong decides the fix.
    assert "assets/gone.wav" in detail
    assert str(tmp_path / "assets" / "gone.wav") in detail


@_ROOT_READS_EVERYTHING
def test_classify_sample_unreadable_is_not_collapsed_into_missing(tmp_path):
    """A sample that is exactly where the clip expects it but cannot be read
    is a permissions fix, not a relink — so it carries its own status."""
    wav = tmp_path / "locked.wav"
    wav.write_bytes(b"RIFF")
    wav.chmod(0o000)
    try:
        status, resolved, detail = C.classify_sample(
            "locked.wav", song_dir=tmp_path,
        )
    finally:
        wav.chmod(0o600)
    assert status == "sample_unreadable"
    assert resolved == wav
    assert str(wav) in detail


@_ROOT_READS_EVERYTHING
def test_classify_sample_unreadable_when_a_parent_dir_denies_access(tmp_path):
    """The file exists; a directory on the way to it does not let us look.

    Without this branch the failed ``stat`` would read as "nothing is there"
    and send the reader hunting for a file that never moved.
    """
    locked_dir = tmp_path / "vault"
    locked_dir.mkdir()
    (locked_dir / "line.wav").write_bytes(b"RIFF")
    locked_dir.chmod(0o000)
    try:
        status, resolved, detail = C.classify_sample(
            "vault/line.wav", song_dir=tmp_path,
        )
    finally:
        locked_dir.chmod(0o700)
    assert status == "sample_unreadable"
    assert str(resolved) in detail


def test_classify_sample_not_a_file_for_a_directory(tmp_path):
    (tmp_path / "assets").mkdir()
    status, resolved, detail = C.classify_sample("assets", song_dir=tmp_path)
    assert status == "sample_not_a_file"
    assert resolved == tmp_path / "assets"
    assert "directory" in detail


def test_classify_sample_unresolvable_when_a_relative_ref_has_no_anchor():
    """No song directory + a song-relative reference = existence unknown.

    Reported as its own status rather than guessed at: calling it missing
    would raise an alarm about a file that is very likely right where it
    belongs.
    """
    status, resolved, detail = C.classify_sample(
        "assets/line.wav", song_dir=None,
    )
    assert status == "sample_unresolvable"
    assert resolved is None
    assert "assets/line.wav" in detail


def test_classify_sample_absolute_ref_needs_no_anchor(tmp_path):
    wav = tmp_path / "outside.wav"
    wav.write_bytes(b"RIFF")
    status, resolved, _ = C.classify_sample(str(wav), song_dir=None)
    assert status == "sample_ok"
    assert resolved == wav


def test_classify_sample_absolute_ref_that_is_gone_is_missing(tmp_path):
    status, resolved, detail = C.classify_sample(
        str(tmp_path / "moved.wav"), song_dir=tmp_path,
    )
    assert status == "sample_missing"
    assert str(tmp_path / "moved.wav") in detail


# ---------------------------------------------------------------------------
# Sample references — the song walk
# ---------------------------------------------------------------------------


def test_check_song_flags_a_dangling_audio_file(conn, song, db_path, tmp_path):
    """The regression: a clip pointing at a sample that is not on disk used to
    report clean and fail in Live."""
    track_id = _audio_track(conn, song)
    _audio_clip(conn, track_id, ref="assets/gone.wav", name="verse take")
    conn.commit()

    report = C.check_song(db_path)

    assert report.has_issues is True
    [entry] = report.samples
    assert entry.status == "sample_missing"
    assert entry.audio_file == "assets/gone.wav"
    assert entry.resolved_path == str(tmp_path / "assets" / "gone.wav")
    assert entry.track_name == "Vox"
    assert entry.clip_name == "verse take"


def test_check_song_clean_when_the_sample_is_on_disk(conn, song, db_path, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "line.wav").write_bytes(b"RIFF")
    track_id = _audio_track(conn, song)
    _audio_clip(conn, track_id, ref="assets/line.wav")
    conn.commit()

    report = C.check_song(db_path)

    assert [e.status for e in report.samples] == ["sample_ok"]
    assert report.sample_issues == []
    assert report.has_issues is False


@_ROOT_READS_EVERYTHING
def test_check_song_reports_missing_and_unreadable_separately(
    conn, song, db_path, tmp_path,
):
    """Both are broken; they are not the same brokenness, and the report says
    which is which rather than collapsing them into one bucket."""
    (tmp_path / "assets").mkdir()
    locked = tmp_path / "assets" / "locked.wav"
    locked.write_bytes(b"RIFF")
    locked.chmod(0o000)
    track_id = _audio_track(conn, song)
    _audio_clip(conn, track_id, ref="assets/gone.wav", slot=1)
    _audio_clip(conn, track_id, ref="assets/locked.wav", slot=2)
    conn.commit()
    try:
        report = C.check_song(db_path)
    finally:
        locked.chmod(0o600)

    by_ref = {e.audio_file: e.status for e in report.samples}
    assert by_ref == {
        "assets/gone.wav": "sample_missing",
        "assets/locked.wav": "sample_unreadable",
    }
    assert len(report.samples_missing) == 1
    assert len(report.samples_unreadable) == 1


def test_check_song_does_not_synthesize_a_device_entry_for_a_sample(
    conn, song, track_chain, db_path,
):
    """The device path is unchanged: a sample never becomes a DeviceEntry, and
    a device's classification never consults a file on disk."""
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="Operator", display_name="Operator")
    track_id = _audio_track(conn, song)
    _audio_clip(conn, track_id, ref="assets/gone.wav")
    conn.commit()

    report = C.check_song(db_path)

    assert [type(e) for e in report.entries] == [C.DeviceEntry]
    assert [e.status for e in report.entries] == ["native"]
    assert [type(e) for e in report.samples] == [C.SampleEntry]


def test_check_song_reports_one_entry_per_clip_sharing_a_sample(
    conn, song, db_path,
):
    """Two clips on one missing sample are two clips to fix."""
    track_id = _audio_track(conn, song)
    _audio_clip(conn, track_id, ref="assets/gone.wav", slot=1)
    _audio_clip(conn, track_id, ref="assets/gone.wav", slot=2)
    conn.commit()

    report = C.check_song(db_path)

    assert [e.slot for e in report.samples] == [1, 2]
    assert {e.status for e in report.samples} == {"sample_missing"}


def test_check_song_ignores_midi_clips(conn, song, track, db_path):
    M.create_clip(conn, track_id=track, slot=1, length_beats=4.0)
    conn.commit()

    report = C.check_song(db_path)

    assert report.samples == []
    assert report.has_issues is False


def test_check_song_unnamed_clip_is_identified_by_its_slot(
    conn, song, db_path,
):
    """A clip with no name still has to be findable in the report."""
    track_id = _audio_track(conn, song)
    _audio_clip(conn, track_id, ref="assets/gone.wav", slot=7)
    conn.commit()

    [entry] = C.check_song(db_path).samples
    assert entry.clip_name == "slot 7"


def test_compat_report_to_json_carries_the_sample_family(
    conn, song, db_path, tmp_path,
):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "line.wav").write_bytes(b"RIFF")
    track_id = _audio_track(conn, song)
    _audio_clip(conn, track_id, ref="assets/line.wav", slot=1)
    _audio_clip(conn, track_id, ref="assets/gone.wav", slot=2)
    conn.commit()

    data = C.check_song(db_path).to_json()

    assert data["summary"]["samples_total"] == 2
    assert data["summary"]["samples_ok"] == 1
    assert data["summary"]["samples_missing"] == 1
    assert data["summary"]["has_issues"] is True
    assert data["summary"]["total"] == 0  # devices, and there are none
    statuses = {e["status"] for e in data["samples"]}
    assert statuses == {"sample_ok", "sample_missing"}
    for entry in data["samples"]:
        assert entry["audio_file"]
        assert entry["resolved_path"]


# ---------------------------------------------------------------------------
# Sample references — REQUIREMENTS.md
# ---------------------------------------------------------------------------


def test_format_requirements_md_lists_referenced_samples(
    conn, song, db_path, tmp_path,
):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "line.wav").write_bytes(b"RIFF")
    track_id = _audio_track(conn, song)
    _audio_clip(conn, track_id, ref="assets/line.wav", name="verse take")
    conn.commit()

    md = C.format_requirements_md(C.check_song(db_path))

    assert "## Referenced samples" in md
    assert "`assets/line.wav`" in md
    assert "Vox / verse take (slot 1)" in md
    assert "travels with the song" in md


def test_format_requirements_md_says_an_absolute_sample_does_not_travel(
    conn, song, db_path, tmp_path,
):
    outside = tmp_path / "library" / "kick.wav"
    outside.parent.mkdir()
    outside.write_bytes(b"RIFF")
    track_id = _audio_track(conn, song)
    _audio_clip(conn, track_id, ref=str(outside))
    conn.commit()

    md = C.format_requirements_md(C.check_song(db_path))

    assert "supply this file yourself" in md


def test_format_requirements_md_no_samples_says_so(
    conn, song, track_chain, db_path,
):
    M.create_device(conn, chain_id=track_chain, position=1,
                    kind="Operator", display_name="Operator")
    conn.commit()

    md = C.format_requirements_md(C.check_song(db_path))

    assert "## Referenced samples" in md
    assert "No clip in this song plays a file from disk." in md


def test_format_requirements_md_names_a_missing_sample_and_its_path(
    conn, song, db_path, tmp_path,
):
    track_id = _audio_track(conn, song)
    _audio_clip(conn, track_id, ref="assets/gone.wav")
    conn.commit()

    md = C.format_requirements_md(C.check_song(db_path))

    assert "sample_missing" in md
    assert str(tmp_path / "assets" / "gone.wav") in md


def test_format_requirements_md_names_every_sample_status():
    """The SampleStatus caller contract, the mirror of the device one: no
    status may render to silence.

    Built by hand rather than from a walk because one of the statuses
    (``sample_unresolvable``) cannot arise from a DB that lives on disk — the
    rendering contract holds for every value of the enum regardless.
    """
    report = C.CompatReport(song_slug="test-song", song_title="Test Song")
    for index, status in enumerate(get_args(C.SampleStatus), start=1):
        report.samples.append(C.SampleEntry(
            track_name="Vox",
            clip_name=f"take {index}",
            slot=index,
            audio_file=f"assets/{status}.wav",
            resolved_path=f"/songs/test-song/assets/{status}.wav",
            status=status,
            detail=None if status == "sample_ok" else f"why {status} happened",
        ))

    md = C.format_requirements_md(report)

    for status in get_args(C.SampleStatus):
        assert f"assets/{status}.wav" in md, f"{status} renders to silence"
        if status != "sample_ok":
            assert status in md, f"{status} is not named in the file"
            assert f"why {status} happened" in md


def test_format_requirements_md_redacts_the_home_directory(tmp_path):
    """REQUIREMENTS.md is checked in beside the song; the author's home
    directory has no business travelling with it."""
    ref = str(Path.home() / "Library" / "Samples" / "kick.wav")
    report = C.CompatReport(song_slug="test-song", song_title="Test Song")
    report.samples.append(C.SampleEntry(
        track_name="Drums", clip_name="hit", slot=1,
        audio_file=ref, resolved_path=ref, status="sample_missing",
        detail=f"audio_file={ref!r} resolves to {ref}, where nothing is",
    ))

    md = C.format_requirements_md(report)

    assert str(Path.home()) not in md
    assert "~/Library/Samples/kick.wav" in md


# ---------------------------------------------------------------------------
# Sample references — CLI gate
# ---------------------------------------------------------------------------


def test_cli_check_exits_one_on_a_dangling_sample(
    monkeypatch, capsys, conn, song, db_path,
):
    track_id = _audio_track(conn, song)
    _audio_clip(conn, track_id, ref="assets/gone.wav")
    conn.commit()
    monkeypatch.setattr(C, "resolve_db_path", lambda slug, **kw: db_path)

    rc = C.main(["check", "test-song"])

    assert rc == 1
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["samples_missing"] == 1
    assert data["samples"][0]["audio_file"] == "assets/gone.wav"
