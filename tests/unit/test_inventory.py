"""Tests for src/hallucinote/inventory.py — the machine-local browser
inventory cache (offline preset_query authoring).

The write side (refresh) talks to the MCP client via an injected ``send_fn``;
these tests drive a fake that mimics ``ableton_browser`` inventory / tree /
at_path responses. The read side (read_cache / find / cache_age_days) is pure
file + dict logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from hallucinote import inventory as INV


# --- fakes ------------------------------------------------------------------


@dataclass
class FakeResp:
    ok: bool = True
    result: dict = field(default_factory=dict)
    error: str | None = None


def _entry(root, *segments, uri="query:x"):
    return {
        "root": root,
        "path": [root, *segments],
        "name": segments[-1],
        "uri": uri,
        "is_loadable": True,
    }


class FakeSend:
    """Maps (tool, action, root, path_prefix) → canned responses.

    ``inventory_results`` keyed by (root, tuple(path_prefix)) → dict result.
    ``tree_children`` keyed by (root, tuple(path_prefix)) → list of child names.
    """

    def __init__(self, inventory_results: dict, tree_children: dict | None = None):
        self.inventory_results = inventory_results
        self.tree_children = tree_children or {}
        self.calls: list[tuple] = []
        self.timeouts: list[float | None] = []

    def __call__(self, request, read_timeout=None):  # mimic client.send
        self.timeouts.append(read_timeout)
        action = request.action
        params = request.params
        if action == "inventory":
            key = (params["root"], tuple(params.get("path_prefix", []) or []))
            self.calls.append(("inventory", *key))
            res = self.inventory_results.get(key)
            if res is None:
                return FakeResp(ok=False, error=f"no canned inventory for {key}")
            return FakeResp(ok=True, result=res)
        if action == "tree":
            key = (params["root"], ())
            self.calls.append(("tree", *key))
            names = self.tree_children.get(key, [])
            return FakeResp(ok=True, result={
                "root": params["root"],
                "tree": {"name": params["root"],
                         "children": [{"name": n} for n in names]},
            })
        if action == "at_path":
            path = params["path"]
            key = (path[0], tuple(path[1:]))
            self.calls.append(("at_path", *key))
            names = self.tree_children.get(key, [])
            return FakeResp(ok=True, result={
                "node": {"children": [{"name": n} for n in names]},
            })
        return FakeResp(ok=False, error=f"unexpected action {action}")


def _inv_result(*entries, truncated=False, scope=None, version="12.1.5", variant="Suite"):
    return {
        "scope": scope or ["?"],
        "walk_depth": INV.MIN_WALK_DEPTH,
        "entries": list(entries),
        "count": len(entries),
        "truncated": truncated,
        "live_version": version,
        "live_variant": variant,
    }


# --- read side --------------------------------------------------------------


def test_read_cache_missing_returns_none(tmp_path):
    assert INV.read_cache(tmp_path / "nope.json") is None


def test_read_cache_corrupt_raises(tmp_path):
    p = tmp_path / "cache.json"
    p.write_text("{not json")
    with pytest.raises(ValueError, match="unreadable"):
        INV.read_cache(p)


def test_read_cache_wrong_schema_raises(tmp_path):
    p = tmp_path / "cache.json"
    p.write_text('{"schema_version": 999, "entries": []}')
    with pytest.raises(ValueError, match="schema_version"):
        INV.read_cache(p)


def test_refresh_then_read_round_trips(tmp_path):
    send = FakeSend({
        ("drums", ()): _inv_result(_entry("drums", "Kit-Core 909"), scope=["drums"]),
    })
    p = tmp_path / "cache.json"
    written = INV.refresh(roots=("drums",), send_fn=send, path=p)
    loaded = INV.read_cache(p)
    assert loaded == written
    assert loaded["count"] == 1
    assert loaded["roots_covered"] == ["drums"]
    assert loaded["live_version"] == "12.1.5"
    assert loaded["live_variant"] == "Suite"
    assert loaded["walk_depth"] == INV.MIN_WALK_DEPTH


def test_cache_age_days():
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    cache = {"captured_at": old}
    age = INV.cache_age_days(cache)
    assert age is not None and 9.9 < age < 10.1


def test_cache_age_days_unparseable_returns_none():
    assert INV.cache_age_days({"captured_at": "not-a-date"}) is None
    assert INV.cache_age_days({}) is None


# --- find -------------------------------------------------------------------


def test_find_resolves_single_match():
    cache = {
        "roots_excluded": [], "roots_partial": [],
        "entries": [_entry("drums", "Kit-Core 909"), _entry("drums", "Kit-Core 808")],
    }
    out = INV.find(cache, {"root": "drums", "pattern": "909"})
    assert out["name"] == "Kit-Core 909"


def test_find_accepts_path_shape_string():
    cache = {
        "roots_excluded": [], "roots_partial": [],
        "entries": [_entry("drums", "Kit-Core 909")],
    }
    out = INV.find(cache, "Drums/Kit-Core 909")
    assert out["name"] == "Kit-Core 909"


def test_find_excluded_root_raises_clearly():
    cache = {"roots_excluded": ["samples"], "roots_partial": [], "entries": []}
    with pytest.raises(ValueError, match="not cached"):
        INV.find(cache, {"root": "samples", "pattern": "x"})


def test_find_partial_root_miss_surfaces_coverage_gap():
    # A miss in a partially-cached root is distinguished from "not installed".
    cache = {
        "roots_excluded": [], "roots_partial": ["packs"],
        "entries": [_entry("packs", "Some Pack", "Kit A")],
    }
    with pytest.raises(ValueError, match="PARTIALLY cached"):
        INV.find(cache, {"root": "packs", "pattern": "Nonexistent"})


def test_find_partial_root_hit_resolves_normally():
    # When the pick IS in the cached portion, no partial warning is raised.
    cache = {
        "roots_excluded": [], "roots_partial": ["packs"],
        "entries": [_entry("packs", "Some Pack", "Kit A")],
    }
    out = INV.find(cache, {"root": "packs", "pattern": "Kit A"})
    assert out["name"] == "Kit A"


# --- refresh ----------------------------------------------------------------


def test_refresh_excludes_samples_by_default(tmp_path):
    # Provide canned results for all default roots.
    results = {(r, ()): _inv_result(scope=[r]) for r in INV.DEFAULT_CACHED_ROOTS}
    send = FakeSend(results)
    cache = INV.refresh(send_fn=send, path=tmp_path / "c.json")
    assert "samples" in cache["roots_excluded"]
    assert "samples" not in cache["roots_covered"]
    # samples was never queried
    assert all(c[1] != "samples" for c in send.calls if c[0] == "inventory")


def test_refresh_passes_generous_read_timeout(tmp_path):
    send = FakeSend({("drums", ()): _inv_result(scope=["drums"])})
    INV.refresh(roots=("drums",), send_fn=send, path=tmp_path / "c.json")
    assert all(t == INV._INVENTORY_READ_TIMEOUT for t in send.timeouts)


def test_refresh_subdivides_on_truncation(tmp_path):
    # drums root truncates; subdivide into two child folders, each fits.
    results = {
        ("drums", ()): _inv_result(
            _entry("drums", "Direct Kit"), truncated=True, scope=["drums"]),
        ("drums", ("808s",)): _inv_result(
            _entry("drums", "808s", "Kit A"), scope=["drums", "808s"]),
        ("drums", ("909s",)): _inv_result(
            _entry("drums", "909s", "Kit B"), scope=["drums", "909s"]),
    }
    send = FakeSend(results, tree_children={("drums", ()): ["808s", "909s"]})
    cache = INV.refresh(roots=("drums",), send_fn=send, path=tmp_path / "c.json")
    names = {e["name"] for e in cache["entries"]}
    # The capped parent's partial entry + both subdivided branches, de-duped.
    assert names == {"Direct Kit", "Kit A", "Kit B"}
    assert cache["roots_covered"] == ["drums"]
    assert cache["roots_partial"] == []


def test_refresh_records_partial_when_subdivision_exhausted(tmp_path):
    # Root truncates AND a child still truncates after the subdivision budget.
    results = {
        ("drums", ()): _inv_result(
            _entry("drums", "X"), truncated=True, scope=["drums"]),
        ("drums", ("Big",)): _inv_result(
            _entry("drums", "Big", "Y"), truncated=True, scope=["drums", "Big"]),
    }
    send = FakeSend(results, tree_children={("drums", ()): ["Big"]})
    cache = INV.refresh(roots=("drums",), send_fn=send, path=tmp_path / "c.json")
    assert cache["roots_partial"] == ["drums"]
    assert cache["roots_covered"] == []
    # Still keeps what it could collect — never a silent total drop.
    assert {e["name"] for e in cache["entries"]} == {"X", "Y"}


def test_refresh_dedupes_entries_by_path(tmp_path):
    # Parent partial and child both report the same leaf — counted once.
    dup = _entry("drums", "Shared", "Kit")
    results = {
        ("drums", ()): _inv_result(dup, truncated=True, scope=["drums"]),
        ("drums", ("Shared",)): _inv_result(dup, scope=["drums", "Shared"]),
    }
    send = FakeSend(results, tree_children={("drums", ()): ["Shared"]})
    cache = INV.refresh(roots=("drums",), send_fn=send, path=tmp_path / "c.json")
    assert cache["count"] == 1


def test_refresh_rejects_unknown_root(tmp_path):
    with pytest.raises(ValueError, match="valid roots"):
        INV.refresh(roots=("bogus",), send_fn=FakeSend({}), path=tmp_path / "c.json")
