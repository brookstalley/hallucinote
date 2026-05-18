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
    def __init__(self):
        self.browser = FakeBrowser()


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

    def run_on_main(self, fn):
        self.run_on_main_calls += 1
        return fn()


@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


# ---------- Schema sanity ----------


_EXPECTED_BROWSER_ACTIONS = {"help", "tree", "at_path", "plugins_list"}


def test_browser_registers_four_actions(loaded_actions):
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
