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
    for native in ("Operator", "Eq8", "DrumGroupDevice", "Compressor2",
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
                    kind="Eq8", display_name="EQ Eight")
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
        kind="AudioEffectGroupDevice", display_name="My FX Rack",
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
    assert "AudioEffectGroupDevice" in kinds
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
