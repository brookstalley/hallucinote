"""M-6 resource registration + per-URI content tests."""
from __future__ import annotations

import json

import pytest

from hallucinote_mcp.resources import (
    RESOURCE_TEMPLATE_URIS,
    RESOURCE_URIS,
    _read_guide,
    _read_reference_json,
)
from hallucinote_mcp.server import (
    create_server,
    registered_resource_template_uris,
    registered_resource_uris,
)


# ---------- Surface lock ----------


_EXPECTED_URIS = {
    "ableton://session/snapshot",
    "ableton://browser/instruments",
    "ableton://browser/effects",
    "ableton://browser/drums",
    "ableton://plugins/installed",
    "ableton://reference/scales",
    "ableton://reference/device-params",
    "ableton://guides/getting-started",
    "ableton://guides/conventions",
    "ableton://guides/error-recovery",
    "ableton://guides/gaps",
}


def test_resource_uri_list_matches_design():
    """Lock the M-6 surface: exactly these 11 URIs, no more, no less.

    Carry-forward principle #3 (lock-the-surface negative test for
    deliberate omissions). A future PR that adds an unlisted resource
    or drops one from the list gets caught here with an actionable
    diff.
    """
    assert set(RESOURCE_URIS) == _EXPECTED_URIS, (
        "RESOURCE_URIS drifted from the M-6 design. Either update the "
        "build plan and this test, OR revert the drift."
    )


def test_create_server_registers_all_eleven_resources():
    """End-to-end: create_server wires every URI into FastMCP."""
    mcp = create_server()
    actual = set(registered_resource_uris(mcp))
    # FastMCP normalizes some URIs; assert by comparison without trailing slashes etc.
    normalized_actual = {u.rstrip("/") for u in actual}
    normalized_expected = {u.rstrip("/") for u in _EXPECTED_URIS}
    assert normalized_actual == normalized_expected, (
        f"FastMCP registry differs from RESOURCE_URIS.\n"
        f"  missing: {normalized_expected - normalized_actual}\n"
        f"  extra:   {normalized_actual - normalized_expected}"
    )


# ---------- Static resources content ----------


@pytest.mark.parametrize("guide_name", [
    "getting-started", "conventions", "error-recovery", "gaps",
])
def test_guide_loads_and_contains_expected_anchors(guide_name):
    """Guides are markdown shipped in the package data dir. Each must
    load + carry a few sanity anchors (the title heading + at least one
    bullet/section).
    """
    content = _read_guide(guide_name)
    assert len(content) > 200, (
        f"guide {guide_name!r} too short — likely truncated or empty"
    )
    # Title line starts with "# " — markdown convention.
    assert content.lstrip().startswith("# "), (
        f"guide {guide_name!r} missing top-level # heading"
    )


def test_scales_json_loads_with_expected_shape():
    raw = _read_reference_json("scales")
    data = json.loads(raw)
    assert "scales" in data
    assert len(data["scales"]) >= 10
    # Every scale entry has name + intervals
    for scale in data["scales"]:
        assert "name" in scale
        assert "intervals" in scale
        assert isinstance(scale["intervals"], list)
        assert all(0 <= i <= 11 for i in scale["intervals"])


def test_device_params_json_loads_with_expected_shape():
    raw = _read_reference_json("device-params")
    data = json.loads(raw)
    assert "devices" in data
    assert len(data["devices"]) >= 3
    # Each device has class_name + display + (common_params OR enum_params OR _note)
    for device in data["devices"]:
        assert "class_name" in device
        assert "display" in device


def test_reference_json_validates_at_read_time():
    """Sanity: the JSON files are valid JSON. The loader validates and
    re-raises; if a stray edit broke parseability the test fails before
    a runtime read returns garbage to the agent.
    """
    # Both reference files should parse without raising.
    json.loads(_read_reference_json("scales"))
    json.loads(_read_reference_json("device-params"))


# ---------- Live-backed resource shapes (with stubs) ----------


def test_live_backed_session_snapshot_composition(monkeypatch):
    """session_snapshot composes 3 underlying tool calls. Verify the
    composition by stubbing handle_tool_call.
    """
    from hallucinote_mcp import resources as res_mod

    calls: list[tuple[str, str]] = []

    def fake(tool, action, params=None):
        calls.append((tool, action))
        return {"ok": True, "result": {"stub": f"{tool}.{action}"}}

    # The resource loader imports handle_tool_call lazily inside the function,
    # so monkeypatch the server module attribute.
    from hallucinote_mcp import server as server_mod
    monkeypatch.setattr(server_mod, "handle_tool_call", fake)

    out = res_mod._session_snapshot()
    data = json.loads(out)
    assert set(data.keys()) == {"session", "tracks", "returns"}
    assert calls == [
        ("ableton_session", "info"),
        ("ableton_track", "list"),
        ("ableton_return", "list"),
    ]


def test_live_backed_browser_tree_delegates_with_root(monkeypatch):
    from hallucinote_mcp import resources as res_mod
    from hallucinote_mcp import server as server_mod

    captured: list[tuple[str, str, dict]] = []

    def fake(tool, action, params=None):
        captured.append((tool, action, dict(params or {})))
        return {"ok": True, "result": {"root": params["root"], "tree": {}}}

    monkeypatch.setattr(server_mod, "handle_tool_call", fake)

    res_mod._browser_tree("instruments")
    assert captured[-1] == (
        "ableton_browser", "tree", {"root": "instruments", "depth": 3},
    )
    res_mod._browser_tree("drums")
    assert captured[-1] == (
        "ableton_browser", "tree", {"root": "drums", "depth": 3},
    )


def test_live_backed_plugins_delegates(monkeypatch):
    from hallucinote_mcp import resources as res_mod
    from hallucinote_mcp import server as server_mod

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        server_mod, "handle_tool_call",
        lambda t, a, p=None: (calls.append((t, a)) or {"ok": True, "result": []}),
    )

    res_mod._plugins_installed()
    assert calls == [("ableton_browser", "plugins_list")]


# ---------- PRIMER includes resources ----------


def test_primer_advertises_resources():
    """The server PRIMER (sent on initialize) must mention resources so
    clients see them at connect time.
    """
    from hallucinote_mcp.server import PRIMER
    assert "Resources" in PRIMER or "resources" in PRIMER.lower()
    assert "ableton://" in PRIMER  # at least one URI shown


# ---------- Templated resources (W11-A: hallucinote:// + slug-in-URI) ----------


_EXPECTED_TEMPLATE_URIS = {
    "hallucinote://song/{slug}/annotations",
}


def test_resource_template_uri_list_matches_design():
    """Arc 5 / P3 lock: the templated URI tuple stays in sync with the
    register_resources(mcp) wiring. New per-song hallucinote:// resources
    add a row here AND a parallel registration."""
    assert set(RESOURCE_TEMPLATE_URIS) == _EXPECTED_TEMPLATE_URIS, (
        "RESOURCE_TEMPLATE_URIS drifted from the W11-A / Arc 5 design. "
        "Either update the build plan and this test, OR revert the drift."
    )


def test_create_server_registers_song_annotations_template():
    """End-to-end: create_server wires the hallucinote://song/{slug}/annotations
    template into FastMCP's resource-template registry."""
    mcp = create_server()
    actual = set(registered_resource_template_uris(mcp))
    assert actual == _EXPECTED_TEMPLATE_URIS, (
        f"FastMCP template registry differs from RESOURCE_TEMPLATE_URIS.\n"
        f"  missing: {_EXPECTED_TEMPLATE_URIS - actual}\n"
        f"  extra:   {actual - _EXPECTED_TEMPLATE_URIS}"
    )


def test_song_annotations_resource_returns_annotations_for_slug(tmp_path, monkeypatch):
    """End-to-end: resolve a slug, read annotations from the song's DB,
    return them as JSON. Mirrors the ableton_annotation(action='list',
    song_slug=<slug>) shape so an LLM agent gets the same data from a
    zero-turn-cost resource fetch."""
    # Set up a real per-song DB the handler can resolve to.
    from hallucinote.db import mutations as M
    from hallucinote.db.connection import init_db
    from hallucinote_mcp.handlers import ableton_annotation as ah
    from hallucinote_mcp.resources import _song_annotations

    db_path = tmp_path / "fw.db"
    conn = init_db(db_path)
    song_id = M.create_song(conn, name="fw", title="FW", key="Dm")
    M.add_annotation(
        conn, song_id=song_id, kind="intent",
        body="verse feels like weight getting worse",
    )
    M.add_annotation(
        conn, song_id=song_id, kind="stylistic",
        body="don't sidechain the bass on the bridge — let it bloom",
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(ah, "_resolve_song_db", lambda slug: db_path)

    out = json.loads(_song_annotations("fw"))
    assert "annotations" in out
    bodies = {a["body"] for a in out["annotations"]}
    assert "verse feels like weight getting worse" in bodies
    assert (
        "don't sidechain the bass on the bridge — let it bloom" in bodies
    )


def test_song_annotations_resource_unknown_slug_raises_teaching_error(
    tmp_path, monkeypatch
):
    """Unknown slug must surface the same teaching error the
    ableton_annotation(action='list') tool path raises — failure modes
    are consistent across tool + resource surfaces."""
    from hallucinote_mcp.handlers import ableton_annotation as ah
    from hallucinote_mcp.resources import _song_annotations

    monkeypatch.setattr(
        ah, "_resolve_song_db", lambda slug: tmp_path / f"{slug}.db",
    )
    with pytest.raises(Exception, match=r"(?i)song.*not.*found|no song"):
        _song_annotations("does-not-exist")
