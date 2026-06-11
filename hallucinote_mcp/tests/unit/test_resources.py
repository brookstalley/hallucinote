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


def test_error_recovery_guide_documents_render_capture_preconditions():
    """The render 0-frame fix must be discoverable in the guide, not only via
    the fail-fast teaching error. Locks the recorder-arming preconditions +
    the /mcp-respawn recovery (backlog: render-skill preconditions doc).
    """
    content = _read_guide("error-recovery").lower()
    assert "0 frames" in content or "0-frame" in content, (
        "error-recovery guide should name the 0-frame capture failure"
    )
    assert "udpreceive" in content, (
        "guide should name udpreceive contention as the root cause"
    )
    assert "/mcp" in content, "guide should name the /mcp respawn fix"
    assert "editor" in content, (
        "guide should name the open analyzer editor window as a cause"
    )


def test_error_recovery_guide_documents_version_pin_recovery():
    """SYN-5C3J: the parallel-engine-dev pin recovery must be discoverable in
    the guide (the friction was reaching for it from scratch). Locks the
    worktree + PYTHONPATH + preflight recipe and the no-`--pin`-flag rationale.
    The subsection name is also cross-referenced by push_cli's recovery footer,
    so this pins that link target too.
    """
    content = _read_guide("error-recovery").lower()
    assert "engine version drift during a live compose session" in content, (
        "guide should carry the subsection push_cli's recovery footer links to"
    )
    assert "git worktree add" in content
    assert "pythonpath" in content
    assert "preflight" in content


def test_conventions_guide_documents_chain_rebuild_pattern():
    """DEV-5R8Q: the delete-descending / reload-in-order recipe for reordering
    a materialized device chain (no Live reorder API) must be discoverable in
    the conventions guide. Locks the descending-delete ordering rule and the
    transient-empty-chain caveat."""
    content = _read_guide("conventions").lower()
    assert "descending" in content, (
        "guide should name descending delete order (so indices stay stable)"
    )
    assert "reload" in content
    assert "empty" in content, (
        "guide should warn about the transient empty-chain window"
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


def test_primer_resource_count_matches_actual_registry():
    """Pattern-sweep guard (post-Arc-6 Critic): the PRIMER's resource count
    headline drifted from 11 to 12 when Arc 5 / P3 added the first
    templated resource (`hallucinote://song/{slug}/annotations`). A
    future resource addition without a parallel PRIMER edit gets
    caught here — the test asserts the quoted total matches
    `len(RESOURCE_URIS) + len(RESOURCE_TEMPLATE_URIS)`."""
    import re
    from hallucinote_mcp.server import PRIMER

    total = len(RESOURCE_URIS) + len(RESOURCE_TEMPLATE_URIS)
    # PRIMER says "N resources" — sniff the headline number.
    match = re.search(r"(\d+) resources", PRIMER)
    assert match is not None, (
        "PRIMER must advertise the total resource count (substring "
        "'N resources') so clients see the surface size on initialize"
    )
    assert int(match.group(1)) == total, (
        f"PRIMER claims {match.group(1)} resources but the registry has "
        f"{total} (={len(RESOURCE_URIS)} static + "
        f"{len(RESOURCE_TEMPLATE_URIS)} templated). "
        "Update PRIMER in hallucinote_mcp/src/hallucinote_mcp/server.py."
    )


def test_readme_resource_count_matches_actual_registry():
    """Pattern-sweep guard #2 (Arc 7 cumulative Critic): the README's
    headline resource count drifted to 11 when the templated resource
    landed — exactly the failure mode the "tree-wide pattern sweeps"
    learning warned about. Pin the README the same way PRIMER is pinned.

    Tolerates either '12 resources' OR '12 resources (11 static + 1
    templated)' — the count itself is what's load-bearing."""
    import re
    from pathlib import Path

    total = len(RESOURCE_URIS) + len(RESOURCE_TEMPLATE_URIS)
    readme_path = Path(__file__).resolve().parents[2] / "README.md"
    text = readme_path.read_text()
    match = re.search(r"(\d+) resources", text)
    assert match is not None, (
        "README must advertise the total resource count (substring "
        "'N resources') so readers see the surface size up front"
    )
    assert int(match.group(1)) == total, (
        f"README claims {match.group(1)} resources but the registry "
        f"has {total} (={len(RESOURCE_URIS)} static + "
        f"{len(RESOURCE_TEMPLATE_URIS)} templated). "
        "Update hallucinote_mcp/README.md."
    )


# ---------- Templated resources (W11-A: hallucinote:// + slug-in-URI) ----------


# Currently empty — the first templated surface (`.../annotations`) was retired
# with the DB annotations table. The plumbing stays for the next per-song
# DB-backed resource; this set locks the surface at "none today".
_EXPECTED_TEMPLATE_URIS: set[str] = set()


def test_resource_template_uri_list_matches_design():
    """W11-A lock: the templated URI tuple stays in sync with the
    register_resources(mcp) wiring. New per-song hallucinote:// resources
    add a row here AND a parallel registration."""
    assert set(RESOURCE_TEMPLATE_URIS) == _EXPECTED_TEMPLATE_URIS, (
        "RESOURCE_TEMPLATE_URIS drifted from the W11-A design. "
        "Either update the build plan and this test, OR revert the drift."
    )


def test_create_server_registers_templated_resources():
    """End-to-end: the FastMCP resource-template registry matches
    RESOURCE_TEMPLATE_URIS exactly. Empty today (no templated resources);
    catches drift in either direction when a per-song resource lands."""
    mcp = create_server()
    actual = set(registered_resource_template_uris(mcp))
    assert actual == _EXPECTED_TEMPLATE_URIS, (
        f"FastMCP template registry differs from RESOURCE_TEMPLATE_URIS.\n"
        f"  missing: {_EXPECTED_TEMPLATE_URIS - actual}\n"
        f"  extra:   {actual - _EXPECTED_TEMPLATE_URIS}"
    )
