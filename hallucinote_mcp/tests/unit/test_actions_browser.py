"""ableton_browser schema + handler behavior."""
from __future__ import annotations

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------- Fakes ----------


class FakeBrowserItem:
    def __init__(
        self,
        name: str,
        *,
        uri: str | None = None,
        is_loadable: bool = False,
        is_folder: bool = True,
        children: list | None = None,
    ):
        self.name = name
        self.uri = uri
        self.is_loadable = is_loadable
        self.is_folder = is_folder
        self.children = children or []


class FakeBrowser:
    def __init__(self):
        self.instruments = FakeBrowserItem(
            "Instruments", children=[
                FakeBrowserItem("Operator", children=[
                    FakeBrowserItem(
                        "Bass", uri="query:Operator/Bass", is_loadable=True,
                        is_folder=False,
                    ),
                    FakeBrowserItem(
                        "Lead", uri="query:Operator/Lead", is_loadable=True,
                        is_folder=False,
                    ),
                ]),
                FakeBrowserItem("Wavetable", children=[
                    FakeBrowserItem(
                        "Pad", uri="query:Wavetable/Pad", is_loadable=True,
                        is_folder=False,
                    ),
                ]),
            ],
        )
        self.audio_effects = FakeBrowserItem("Audio Effects", children=[])
        self.midi_effects = FakeBrowserItem("MIDI Effects", children=[])
        self.drums = FakeBrowserItem("Drums", children=[])
        self.plugins = FakeBrowserItem("Plug-ins", children=[
            FakeBrowserItem("Native", children=[
                FakeBrowserItem(
                    "Serum", uri="plugin:Native/Serum",
                    is_loadable=True, is_folder=False,
                ),
                FakeBrowserItem(
                    "Massive", uri="plugin:Native/Massive",
                    is_loadable=True, is_folder=False,
                ),
            ]),
            FakeBrowserItem("Audio Damage", children=[
                FakeBrowserItem(
                    "Rough Rider", uri="plugin:AD/RoughRider",
                    is_loadable=True, is_folder=False,
                ),
            ]),
        ])
        self.samples = FakeBrowserItem("Samples", children=[])
        self.user_library = FakeBrowserItem("User", children=[])
        self.packs = FakeBrowserItem("Packs", children=[])


class FakeApp:
    def __init__(self, version="12.1.5", variant="Suite"):
        self.browser = FakeBrowser()
        self._version = version
        self._variant = variant

    def get_version_string(self):
        return self._version

    def get_variant(self):
        return self._variant


class FakeSong:
    """Real Live ``Song`` does NOT expose ``get_application`` — the
    Application is reached via ``Live.Application.get_application()`` and
    flows to handlers through ``LiveContext.application``. The fake
    mirrors that surface (no get_application)."""


class FakeCtx:
    """LiveContext stub. Owns the FakeApp directly (symmetric to the real
    Protocol where ``application`` is a peer of ``song``)."""

    def __init__(self, application: FakeApp | None = None):
        self._song = FakeSong()
        self._application = application or FakeApp()
        self.run_on_main_calls = 0

    @property
    def song(self):
        return self._song

    @property
    def application(self):
        return self._application

    def run_on_main(self, fn, **_kwargs):
        self.run_on_main_calls += 1
        return fn()


@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


# ---------- Schema sanity ----------


_EXPECTED_BROWSER_ACTIONS = {
    "help", "tree", "at_path", "search", "plugins_list", "inventory",
}


def test_browser_registers_six_actions(loaded_actions):
    names = {a.name for a in schema.actions_for("ableton_browser")}
    assert names == _EXPECTED_BROWSER_ACTIONS


def test_browser_help_lists_all_actions(loaded_actions):
    resp = dispatch(Request(tool="ableton_browser", action="help"))
    assert resp.ok is True
    names = {a["name"] for a in resp.result["actions"]}
    assert names == _EXPECTED_BROWSER_ACTIONS - {"help"}


# ---------- tree ----------


def test_tree_default_root_and_depth(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(tool="ableton_browser", action="tree", params={}),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["root"] == "instruments"
    tree = resp.result["tree"]
    assert tree["name"] == "Instruments"
    # depth=2 → root + immediate children + grandchildren
    operator = next(c for c in tree["children"] if c["name"] == "Operator")
    assert {c["name"] for c in operator["children"]} == {"Bass", "Lead"}


def test_tree_depth_zero_returns_root_only(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_browser", action="tree",
            params={"root": "instruments", "depth": 0},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert "children" not in resp.result["tree"]


def test_tree_depth_clamped_to_six(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_browser", action="tree",
            params={"depth": 10},
        ),
        context=ctx,
    )
    # Either via the schema enum bound or the handler check
    assert resp.ok is False


def test_tree_rejects_unknown_root(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_browser", action="tree",
            params={"root": "wrong"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "not in enum" in (resp.error or "")


# ---------- at_path ----------


def test_at_path_walks_to_node(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_browser", action="at_path",
            params={"path": ["instruments", "Operator", "Bass"]},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["node"]["name"] == "Bass"
    assert resp.result["node"]["uri"] == "query:Operator/Bass"
    assert resp.result["node"]["is_loadable"] is True


def test_at_path_unknown_segment_lists_available(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_browser", action="at_path",
            params={"path": ["instruments", "Bogus"]},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "Bogus" in err
    # Lists what IS available at that level
    assert "Operator" in err and "Wavetable" in err


def test_at_path_empty_rejected(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_browser", action="at_path",
            params={"path": []},
        ),
        context=ctx,
    )
    assert resp.ok is False


def test_at_path_bad_root_rejected(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_browser", action="at_path",
            params={"path": ["wrong"]},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "wrong" in (resp.error or "")


# ---------- plugins_list ----------


def test_plugins_list_returns_flat_loadables(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(tool="ableton_browser", action="plugins_list"),
        context=ctx,
    )
    assert resp.ok is True
    plugins = resp.result["plugins"]
    names = sorted(p["name"] for p in plugins)
    assert names == ["Massive", "Rough Rider", "Serum"]
    assert resp.result["count"] == 3


# ---------- run_on_main ----------


def test_browser_execution_marshals_to_main_thread(loaded_actions):
    ctx = FakeCtx()
    dispatch(
        Request(tool="ableton_browser", action="plugins_list"),
        context=ctx,
    )
    assert ctx.run_on_main_calls == 1


# ---------- search ----------


def _drum_browser() -> FakeBrowser:
    """Browser fake with a realistic drums-root shape: engine folders + presets.

    Mirrors what the real Live browser exposes — engine nodes (Impulse,
    Drum Rack) are loadable folders with preset children that are
    loadable leaves. Categories like 'Bass'/'Pad' under instruments
    engines are non-loadable category folders. Confirmed against real
    Live introspection 2026-05-20.
    """
    b = FakeBrowser()
    # Replace the empty drums tree with one that has presets.
    b.drums = FakeBrowserItem(
        "Drums", children=[
            FakeBrowserItem(
                "Drum Hits", children=[
                    FakeBrowserItem(
                        "Kit-Core 909", uri="query:Drums#FileId_5418",
                        is_loadable=True, is_folder=False,
                    ),
                    FakeBrowserItem(
                        "Kit-Vintage 909", uri="query:Drums#FileId_5419",
                        is_loadable=True, is_folder=False,
                    ),
                    FakeBrowserItem(
                        "Kit-Acoustic", uri="query:Drums#FileId_5420",
                        is_loadable=True, is_folder=False,
                    ),
                ],
            ),
            FakeBrowserItem(
                "Late Night", uri="query:Drums#FileId_5500",
                is_loadable=True, is_folder=False,
            ),
        ],
    )
    return b


def _ctx_with_drums() -> FakeCtx:
    app = FakeApp()
    app.browser = _drum_browser()
    return FakeCtx(application=app)


def test_search_substring_default_mode(loaded_actions):
    resp = dispatch(
        Request(
            tool="ableton_browser", action="search",
            params={"pattern": "909", "root": "drums"},
        ),
        context=_ctx_with_drums(),
    )
    assert resp.ok is True
    names = sorted(m["name"] for m in resp.result["matches"])
    assert names == ["Kit-Core 909", "Kit-Vintage 909"]
    assert resp.result["count"] == 2
    assert resp.result["truncated"] is False
    assert resp.result["depth_exhausted"] is False


def test_search_returns_full_path_for_disambiguation(loaded_actions):
    resp = dispatch(
        Request(
            tool="ableton_browser", action="search",
            params={"pattern": "Kit-Core", "root": "drums"},
        ),
        context=_ctx_with_drums(),
    )
    assert resp.ok is True
    m = resp.result["matches"][0]
    # path starts with the root key (lowercase agent-facing form),
    # not the browser node's display name.
    assert m["path"] == ["drums", "Drum Hits", "Kit-Core 909"]
    assert m["uri"] == "query:Drums#FileId_5418"
    assert m["is_loadable"] is True


def test_search_glob_mode(loaded_actions):
    # 'Kit-*909' = 'Kit-' + any chars + '909'. Matches "Kit-Core 909"
    # and "Kit-Vintage 909" but NOT "Kit-Acoustic" (no trailing 909).
    resp = dispatch(
        Request(
            tool="ableton_browser", action="search",
            params={
                "pattern": "Kit-*909", "root": "drums", "mode": "glob",
            },
        ),
        context=_ctx_with_drums(),
    )
    assert resp.ok is True
    names = sorted(m["name"] for m in resp.result["matches"])
    assert names == ["Kit-Core 909", "Kit-Vintage 909"]


def test_search_regex_mode(loaded_actions):
    resp = dispatch(
        Request(
            tool="ableton_browser", action="search",
            params={
                "pattern": r"^Kit-(Core|Acoustic)",
                "root": "drums", "mode": "regex",
            },
        ),
        context=_ctx_with_drums(),
    )
    assert resp.ok is True
    names = sorted(m["name"] for m in resp.result["matches"])
    assert names == ["Kit-Acoustic", "Kit-Core 909"]


def test_search_regex_invalid_pattern_rejected(loaded_actions):
    resp = dispatch(
        Request(
            tool="ableton_browser", action="search",
            params={
                "pattern": "[unbalanced",
                "mode": "regex",
            },
        ),
        context=_ctx_with_drums(),
    )
    assert resp.ok is False
    assert "invalid regex" in (resp.error or "")


def test_search_case_insensitive_default(loaded_actions):
    # Operator in the basic fake is a folder (loadable_only filters it),
    # so the pattern hits its loadable children instead. Searching for the
    # uppercase 'BASS' must match the Operator/Bass leaf in case-insensitive
    # mode (the default).
    resp = dispatch(
        Request(
            tool="ableton_browser", action="search",
            params={"pattern": "BASS", "root": "instruments"},
        ),
        context=FakeCtx(),
    )
    assert resp.ok is True
    names = [m["name"] for m in resp.result["matches"]]
    assert "Bass" in names


def test_search_case_sensitive_opt_in(loaded_actions):
    resp = dispatch(
        Request(
            tool="ableton_browser", action="search",
            params={
                "pattern": "BASS", "root": "instruments",
                "case_sensitive": True,
            },
        ),
        context=FakeCtx(),
    )
    assert resp.ok is True
    names = [m["name"] for m in resp.result["matches"]]
    assert "Bass" not in names
    assert resp.result["count"] == 0


def test_search_path_prefix_scopes_the_walk(loaded_actions):
    # Pattern 'Bass' would match the Operator/Bass node as well as Wavetable;
    # path_prefix narrows to only the Operator subtree.
    resp = dispatch(
        Request(
            tool="ableton_browser", action="search",
            params={
                "pattern": "Bass", "root": "instruments",
                "path_prefix": ["Operator"],
            },
        ),
        context=FakeCtx(),
    )
    assert resp.ok is True
    matches = resp.result["matches"]
    assert all(m["path"][:2] == ["instruments", "Operator"] for m in matches)
    assert any(m["name"] == "Bass" for m in matches)


def test_search_path_prefix_unknown_segment_lists_available(loaded_actions):
    resp = dispatch(
        Request(
            tool="ableton_browser", action="search",
            params={
                "pattern": "anything", "root": "instruments",
                "path_prefix": ["Bogus"],
            },
        ),
        context=FakeCtx(),
    )
    assert resp.ok is False
    assert "Bogus" in (resp.error or "")
    # Helpful error: names what IS at that level
    assert "available" in (resp.error or "")


def test_search_loadable_only_filters_category_folders(loaded_actions):
    # In the fake instruments tree, "Operator" is a folder (is_folder=True
    # in the default fake, is_loadable=False). With loadable_only=True
    # (default), the Operator folder itself is filtered out — only the
    # loadable Bass/Lead children make it through.
    resp = dispatch(
        Request(
            tool="ableton_browser", action="search",
            params={"pattern": "Operator", "root": "instruments"},
        ),
        context=FakeCtx(),
    )
    assert resp.ok is True
    # Operator is a folder in the basic fake → filtered out by default.
    assert resp.result["count"] == 0

    # With loadable_only=False, the folder is returned too.
    resp = dispatch(
        Request(
            tool="ableton_browser", action="search",
            params={
                "pattern": "Operator", "root": "instruments",
                "loadable_only": False,
            },
        ),
        context=FakeCtx(),
    )
    assert resp.ok is True
    names = [m["name"] for m in resp.result["matches"]]
    assert "Operator" in names


def test_search_truncated_at_limit(loaded_actions):
    resp = dispatch(
        Request(
            tool="ableton_browser", action="search",
            params={
                "pattern": "Kit", "root": "drums", "limit": 2,
            },
        ),
        context=_ctx_with_drums(),
    )
    assert resp.ok is True
    assert resp.result["count"] == 2
    assert resp.result["truncated"] is True


def test_search_depth_exhausted_flag(loaded_actions):
    # depth=1 from the drums root reaches "Drum Hits" + "Late Night" but
    # NOT inside Drum Hits' children. The Kit presets are at depth 2, so
    # they're missed — depth_exhausted should fire.
    resp = dispatch(
        Request(
            tool="ableton_browser", action="search",
            params={
                "pattern": "Kit", "root": "drums", "depth": 1,
            },
        ),
        context=_ctx_with_drums(),
    )
    assert resp.ok is True
    assert resp.result["count"] == 0
    assert resp.result["depth_exhausted"] is True


def test_search_empty_pattern_rejected(loaded_actions):
    resp = dispatch(
        Request(
            tool="ableton_browser", action="search",
            params={"pattern": "", "root": "drums"},
        ),
        context=_ctx_with_drums(),
    )
    assert resp.ok is False
    assert "non-empty" in (resp.error or "")


def test_search_unknown_mode_rejected(loaded_actions):
    resp = dispatch(
        Request(
            tool="ableton_browser", action="search",
            params={"pattern": "x", "mode": "fuzzy"},
        ),
        context=_ctx_with_drums(),
    )
    assert resp.ok is False
    # Caught by ParamSpec enum validation, not the handler.
    assert "fuzzy" in (resp.error or "") or "enum" in (resp.error or "")


def test_search_runs_on_main_thread(loaded_actions):
    ctx = _ctx_with_drums()
    dispatch(
        Request(
            tool="ableton_browser", action="search",
            params={"pattern": "Kit", "root": "drums"},
        ),
        context=ctx,
    )
    assert ctx.run_on_main_calls == 1


# ---------- inventory ----------


def _inv(ctx, **params):
    return dispatch(
        Request(tool="ableton_browser", action="inventory", params=params),
        context=ctx,
    )


def test_inventory_flattens_loadables_with_full_paths(loaded_actions):
    ctx = FakeCtx()
    resp = _inv(ctx, root="instruments")
    assert resp.ok is True
    by_name = {e["name"]: e for e in resp.result["entries"]}
    # Only loadables — folders (Operator, Wavetable) are excluded.
    assert set(by_name) == {"Bass", "Lead", "Pad"}
    assert by_name["Bass"]["path"] == ["instruments", "Operator", "Bass"]
    assert by_name["Bass"]["root"] == "instruments"
    assert by_name["Bass"]["uri"] == "query:Operator/Bass"
    assert resp.result["truncated"] is False
    assert resp.result["scope"] == ["instruments"]


def test_inventory_walk_depth_is_push_resolver_depth(loaded_actions):
    from hallucinote_mcp.handlers.device import _BROWSER_WALK_DEPTH
    ctx = FakeCtx()
    resp = _inv(ctx, root="instruments")
    assert resp.result["walk_depth"] == _BROWSER_WALK_DEPTH


def test_inventory_stamps_live_version(loaded_actions):
    ctx = FakeCtx()
    resp = _inv(ctx, root="instruments")
    assert resp.result["live_version"] == "12.1.5"
    assert resp.result["live_variant"] == "Suite"


def test_inventory_recurses_past_loadables(loaded_actions):
    """A loadable rack can contain further loadable presets; the push-time
    resolver walks past loadables, so inventory must too — else a nested
    preset push can reach would be missing from the cache."""
    rack = FakeBrowserItem(
        "Kit Rack", uri="query:rack", is_loadable=True, is_folder=False,
        children=[
            FakeBrowserItem(
                "Inner Snare", uri="query:rack/snare",
                is_loadable=True, is_folder=False,
            ),
        ],
    )
    app = FakeApp()
    app.browser.drums = FakeBrowserItem("Drums", children=[rack])
    ctx = FakeCtx(application=app)
    resp = _inv(ctx, root="drums")
    names = {e["name"] for e in resp.result["entries"]}
    assert names == {"Kit Rack", "Inner Snare"}
    inner = next(e for e in resp.result["entries"] if e["name"] == "Inner Snare")
    assert inner["path"] == ["drums", "Kit Rack", "Inner Snare"]


def test_inventory_truncates_at_max_entries(loaded_actions):
    ctx = FakeCtx()
    # instruments has 3 loadables; cap at 2 → truncated.
    resp = _inv(ctx, root="instruments", max_entries=2)
    assert resp.ok is True
    assert resp.result["truncated"] is True
    assert resp.result["count"] == 2


def test_inventory_path_prefix_narrows_scope(loaded_actions):
    ctx = FakeCtx()
    resp = _inv(ctx, root="instruments", path_prefix=["Operator"])
    assert resp.ok is True
    names = {e["name"] for e in resp.result["entries"]}
    assert names == {"Bass", "Lead"}  # Wavetable/Pad excluded
    assert resp.result["scope"] == ["instruments", "Operator"]


def test_inventory_unknown_root_errors(loaded_actions):
    ctx = FakeCtx()
    resp = _inv(ctx, root="bogus")
    assert resp.ok is False


def test_inventory_requires_root(loaded_actions):
    ctx = FakeCtx()
    resp = _inv(ctx)
    assert resp.ok is False
