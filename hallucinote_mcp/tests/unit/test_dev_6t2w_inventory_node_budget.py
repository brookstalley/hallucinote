"""DEV-6T2W: inventory walk must bound MAIN-THREAD wall-clock by node count.

The whole inventory walk runs inside ONE ``run_on_main`` bout (the inventory
action has no ``runs_on_worker`` opt-out), so it is subject to the dispatcher's
15s ``_main_thread_timeout``. The pre-existing breadth cap (``max_entries``)
only counts *loadable leaves*, so a root whose tree is mostly non-loadable
folder containers can recurse past the breadth cap without ever tripping it —
visiting an unbounded number of nodes (each a Live-API ``.children`` read) and
risking a spurious TimeoutError that keeps freezing Live.

These tests pin the node-visit budget (``max_nodes``) that bounds the walk's
total work regardless of how many non-loadable folders the tree contains.
"""
from __future__ import annotations

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.handlers import browser as B
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request

import pytest


# ---------- minimal fakes (self-contained; do not edit the shared file) ----------


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
    """Only the roots the tests touch; the rest are empty folders."""

    def __init__(self, drums_children: list):
        self.instruments = FakeBrowserItem("Instruments", children=[])
        self.audio_effects = FakeBrowserItem("Audio Effects", children=[])
        self.midi_effects = FakeBrowserItem("MIDI Effects", children=[])
        self.drums = FakeBrowserItem("Drums", children=drums_children)
        self.plugins = FakeBrowserItem("Plug-ins", children=[])
        self.samples = FakeBrowserItem("Samples", children=[])
        self.user_library = FakeBrowserItem("User", children=[])
        self.packs = FakeBrowserItem("Packs", children=[])


class FakeApp:
    def __init__(self, drums_children: list):
        self.browser = FakeBrowser(drums_children)

    def get_version_string(self):
        return "12.1.5"

    def get_variant(self):
        return "Suite"


class FakeSong:
    pass


class FakeCtx:
    def __init__(self, drums_children: list):
        self._song = FakeSong()
        self._application = FakeApp(drums_children)

    @property
    def song(self):
        return self._song

    @property
    def application(self):
        return self._application

    def run_on_main(self, fn, **_kwargs):
        return fn()


@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


def _folder_heavy_drums(n_folders: int) -> list:
    """A drums root that is mostly NON-loadable folders — exactly the shape the
    loadable-only breadth cap fails to bound. Exactly one loadable leaf at the
    end, so ``max_entries`` is never the thing that stops the walk."""
    folders = [
        FakeBrowserItem(f"Empty Folder {i}", is_loadable=False, is_folder=True)
        for i in range(n_folders)
    ]
    folders.append(
        FakeBrowserItem(
            "The One Kit", uri="query:drums/one", is_loadable=True,
            is_folder=False,
        )
    )
    return folders


def _inv(ctx, **params):
    return dispatch(
        Request(tool="ableton_browser", action="inventory", params=params),
        context=ctx,
    )


# ---------- _flatten_loadables: the node-visit budget itself ----------


def test_node_budget_truncates_folder_heavy_tree():
    """A tree of mostly non-loadable folders trips the node budget even though
    only ONE loadable exists (the breadth cap would never fire)."""
    root = FakeBrowserItem(
        "Drums", children=_folder_heavy_drums(50)
    )
    out: list = []
    # budget small enough to be exhausted by the folder nodes.
    truncated = B._flatten_loadables(
        root, ["drums"], 8, out, max_entries=20000, budget=[10],
    )
    assert truncated is True
    # The walk stopped early — it did NOT collect the single loadable that sits
    # AFTER the 50 folder nodes, proving the budget bounded the visit count.
    assert len(out) == 0


def test_node_budget_counts_every_node_not_just_loadables():
    """The budget decrements per node ENTERED, so visiting N nodes with a
    budget of N-1 truncates regardless of how few are loadable."""
    # 4 nodes total: root + 3 empty folders, zero loadables.
    root = FakeBrowserItem(
        "Drums",
        children=[
            FakeBrowserItem("f1"),
            FakeBrowserItem("f2"),
            FakeBrowserItem("f3"),
        ],
    )
    out: list = []
    # budget 3 < 4 nodes → must truncate even with NO loadables to cap.
    truncated = B._flatten_loadables(
        root, ["drums"], 8, out, max_entries=20000, budget=[3],
    )
    assert truncated is True
    assert out == []


def test_generous_budget_does_not_truncate_normal_tree():
    """A budget well above the node count leaves behavior unchanged: all
    loadables collected, not truncated."""
    root = FakeBrowserItem(
        "Drums", children=_folder_heavy_drums(50)
    )
    out: list = []
    truncated = B._flatten_loadables(
        root, ["drums"], 8, out, max_entries=20000, budget=[10000],
    )
    assert truncated is False
    assert {e["name"] for e in out} == {"The One Kit"}


# ---------- dispatch-level: the action exposes + enforces max_nodes ----------


def test_inventory_max_nodes_param_truncates_through_dispatch(loaded_actions):
    """The bug class end-to-end: a folder-heavy root with a single loadable
    returns truncated=True when max_nodes is hit, even though max_entries
    (20000) is nowhere near being reached."""
    ctx = FakeCtx(_folder_heavy_drums(50))
    resp = _inv(ctx, root="drums", max_nodes=10)
    assert resp.ok is True
    assert resp.result["truncated"] is True


def test_inventory_max_entries_alone_does_not_bound_folder_heavy_root(loaded_actions):
    """Regression witness: with the DEFAULT generous max_entries and a SMALL
    folder-heavy tree, the loadable-only cap never fires — only the node
    budget can bound such a walk. Here the tree is tiny so a generous node
    budget completes cleanly and returns the lone loadable."""
    ctx = FakeCtx(_folder_heavy_drums(50))
    resp = _inv(ctx, root="drums")  # defaults: max_entries=20000, max_nodes=200000
    assert resp.ok is True
    assert resp.result["truncated"] is False
    names = {e["name"] for e in resp.result["entries"]}
    assert names == {"The One Kit"}


def test_inventory_rejects_nonpositive_max_nodes(loaded_actions):
    ctx = FakeCtx(_folder_heavy_drums(1))
    resp = _inv(ctx, root="drums", max_nodes=0)
    assert resp.ok is False


def test_inventory_default_max_nodes_is_generous_constant(loaded_actions):
    """The default budget is far above any real install (author's Suite:
    13884 loadables) so it never bites a healthy walk."""
    assert B._INVENTORY_MAX_NODES >= 100000
