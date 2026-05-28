"""Tests for src/hallucinote/sync/compat.py — W13-B cross-machine portability.

Covers all five status branches of classify_device, the song-walk including
nested rack chains, REQUIREMENTS.md formatting, and the CLI exit-code
contract that the push-preflight gate keys off.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from hallucinote.db import init_db, mutations as M
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
    c = C.connect(db_path)
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
        "has_issues": True,
    }
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
        ("audio_effects", "Hall", ("Hybrid Reverb",)): 12,
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
    dry_runs = {("instruments", "Nonexistent Preset", ()): 0}
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
    dry_runs = {("instruments", "Bass-Pluck", ()): 1}
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
        ("instruments", "Bass-Pluck", ()): 1,
        ("audio_effects", "Hall", ("Hybrid Reverb",)): 3,
    })
    runs = C._probe_browser_dry_runs(conn, send_fn=send)
    assert runs == {
        ("instruments", "Bass-Pluck", ()): 1,
        ("audio_effects", "Hall", ("Hybrid Reverb",)): 3,
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
    base_send = _fake_send_factory({("instruments", "Pad", ()): 7})

    def _counting_send(req):
        nonlocal call_count
        call_count += 1
        return base_send(req)

    runs = C._probe_browser_dry_runs(conn, send_fn=_counting_send)
    assert call_count == 1
    assert runs == {("instruments", "Pad", ()): 7}


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
        ("instruments", "Bass", ()): 1,
    })
    runs = C._probe_browser_dry_runs(conn, send_fn=send)
    assert runs == {("instruments", "Bass", ()): 1}


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
        ("instruments", "Mystery", ()): {"ok": False, "error": "live not running"},
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
    send = _fake_send_factory({("audio_effects", "Hall", ()): 2})
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
    send = _fake_send_factory({("instruments", "Bass-Pluck", ()): 1})
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
    send = _fake_send_factory({("plugins", "Serum", ()): 1})
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
