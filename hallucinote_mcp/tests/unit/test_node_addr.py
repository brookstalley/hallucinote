"""NODE-ADDR spine: the one resolver (`_resolve_node`), the one validator
(`validate_node_addr`), and the handler facade (`resolve_node_addr`).

These freeze the address grammar (design §1c): terminals
track/return/master/device/chain, a structured `node` object on the wire, and
a track/return/master terminal that is also the as-value shape. The resolver is
positional and feature-agnostic — what features each terminal *supports* is the
capability table's job, not the resolver's.
"""
from __future__ import annotations

import pytest

from hallucinote_mcp.handlers.device import (
    _resolve_node,
    get_parameters_handler,
    resolve_node_addr,
    validate_node_addr,
)

_MISSING = object()


# --- minimal fakes (resolver touches only .devices / .chains / index ranges) ---

class _Dev:
    def __init__(self, name: str, class_name: str = "Operator"):
        self.name = name
        self.class_name = class_name


class _Chain:
    def __init__(self, name: str, devices: list | None = None):
        self.name = name
        self.devices = list(devices or [])


class _Rack(_Dev):
    def __init__(self, name: str = "Rack", chains: list | None = None):
        super().__init__(name, class_name="InstrumentGroupDevice")
        self.chains = list(chains or [])


class _Track:
    def __init__(self, name: str = "T", devices: list | None = None):
        self.name = name
        self.devices = list(devices or [])


class _Return(_Track):
    pass


class _Song:
    def __init__(self, tracks=None, returns=None, master=None):
        self.tracks = tracks if tracks is not None else [_Track("T1")]
        self.return_tracks = returns if returns is not None else [_Return("A")]
        self.master_track = master if master is not None else _Track("Master")


class _Ctx:
    def __init__(self, song: _Song):
        self._song = song

    @property
    def song(self) -> _Song:
        return self._song


def _deep_track() -> _Track:
    """track ▸ rack[1] ▸ chain[1] ▸ rack[1] ▸ chain[1] ▸ leaf — a depth-2 tree."""
    leaf = _Dev("Leaf", class_name="Compressor2")
    inner_rack = _Rack("Inner", chains=[_Chain("InnerChain", devices=[leaf])])
    top_rack = _Rack("Top", chains=[_Chain("TopChain", devices=[_Dev("Sub"), inner_rack])])
    return _Track("Gtr", devices=[top_rack])


# --------------------------------------------------------------------------
# validate_node_addr — normalization + teaching errors (the single grammar)
# --------------------------------------------------------------------------

def test_validate_device_terminal_defaults():
    out = validate_node_addr({"parent": {"kind": "track", "index": 3}, "device_index": 1})
    assert out == {
        "parent": {"kind": "track", "index": 3},
        "terminal": "device",
        "device_index": 1,
    }


def test_validate_master_takes_no_index():
    out = validate_node_addr({"parent": {"kind": "master"}, "device_index": 2})
    assert out["parent"] == {"kind": "master"}
    assert out["device_index"] == 2


def test_validate_master_with_index_rejected():
    with pytest.raises(ValueError, match="singleton"):
        validate_node_addr({"parent": {"kind": "master", "index": 1}, "device_index": 1})


def test_validate_path_preserved_and_normalized():
    out = validate_node_addr({
        "parent": {"kind": "return", "index": 2},
        "device_index": 1,
        "path": [{"chain_index": 1, "device_position": 2}],
    })
    assert out["path"] == [{"chain_index": 1, "device_position": 2}]
    assert out["parent"] == {"kind": "return", "index": 2}


def test_validate_chain_terminal_ok():
    out = validate_node_addr({
        "parent": {"kind": "track", "index": 1},
        "device_index": 1,
        "terminal": "chain",
        "chain_index": 2,
    })
    assert out["terminal"] == "chain"
    assert out["chain_index"] == 2


def test_validate_node_terminal_is_as_value_shape():
    out = validate_node_addr({"parent": {"kind": "track", "index": 2}, "terminal": "track"})
    assert out == {"parent": {"kind": "track", "index": 2}, "terminal": "track"}


@pytest.mark.parametrize("node, match", [
    ("nope", "must be an object"),
    ({"parent": {"kind": "bogus"}}, "parent.kind"),
    ({"parent": {"kind": "track"}, "device_index": 1}, "1-based"),  # missing index
    ({"parent": {"kind": "track", "index": 1}}, "device_index"),  # device default, no di
    ({"parent": {"kind": "track", "index": 1}, "device_index": 1, "terminal": "chain"},
     "chain_index"),  # chain w/o chain_index
    ({"parent": {"kind": "track", "index": 1}, "device_index": 1, "chain_index": 2},
     "only valid for terminal 'chain'"),  # chain_index on device
    ({"parent": {"kind": "track", "index": 1}, "terminal": "return"},
     "must match node.parent.kind"),  # terminal/kind mismatch
    ({"parent": {"kind": "track", "index": 1}, "terminal": "track", "device_index": 1},
     "must be absent"),  # node terminal carries device_index
    ({"parent": {"kind": "track", "index": 1}, "device_index": True},
     "1-based"),  # bool is not a position
])
def test_validate_teaching_errors(node, match):
    with pytest.raises(ValueError, match=match):
        validate_node_addr(node)


# --------------------------------------------------------------------------
# _resolve_node — every terminal × depth, positional descent
# --------------------------------------------------------------------------

def test_resolve_device_depth0():
    dev = _Dev("Top")
    parent = _Track(devices=[dev])
    assert _resolve_node(parent, device_index=1, terminal="device") is dev


def test_resolve_device_depth2_nested():
    track = _deep_track()
    leaf = _resolve_node(
        track,
        device_index=1,
        path=[{"chain_index": 1, "device_position": 2},
              {"chain_index": 1, "device_position": 1}],
        terminal="device",
    )
    assert leaf.name == "Leaf"


def test_resolve_chain_terminal():
    chain = _Chain("Lead", devices=[_Dev("x")])
    rack = _Rack("R", chains=[_Chain("other"), chain])
    parent = _Track(devices=[rack])
    assert _resolve_node(parent, device_index=1, terminal="chain", chain_index=2) is chain


def test_resolve_chain_terminal_nested_rack():
    track = _deep_track()
    # descend to the inner rack (chain1/device2 of the top rack) then its chain 1
    inner_chain = _resolve_node(
        track, device_index=1,
        path=[{"chain_index": 1, "device_position": 2}],
        terminal="chain", chain_index=1,
    )
    assert inner_chain.name == "InnerChain"


def test_resolve_parent_terminal_returns_parent():
    parent = _Track("Gtr", devices=[_Dev("x")])
    assert _resolve_node(parent, parent_kind="track", terminal="track") is parent


def test_resolve_chain_on_non_rack_teaches():
    parent = _Track(devices=[_Dev("plain", class_name="Operator")])
    with pytest.raises(ValueError, match="is not a rack"):
        _resolve_node(parent, device_index=1, terminal="chain", chain_index=1)


def test_resolve_terminal_kind_mismatch():
    parent = _Track()
    with pytest.raises(ValueError, match="must equal the parent kind"):
        _resolve_node(parent, parent_kind="track", terminal="return")


def test_resolve_device_out_of_range():
    parent = _Track(devices=[_Dev("only")])
    with pytest.raises(IndexError):
        _resolve_node(parent, device_index=2, terminal="device")


def test_resolve_chain_index_out_of_range():
    rack = _Rack("R", chains=[_Chain("only")])
    parent = _Track(devices=[rack])
    with pytest.raises(IndexError):
        _resolve_node(parent, device_index=1, terminal="chain", chain_index=2)


def test_resolve_unknown_terminal():
    with pytest.raises(ValueError, match="unknown terminal"):
        _resolve_node(_Track(), terminal="banana")


# --------------------------------------------------------------------------
# resolve_node_addr — the handler facade (parse object → resolve parent → descend)
# --------------------------------------------------------------------------

def test_facade_device_end_to_end():
    dev = _Dev("Synth")
    ctx = _Ctx(_Song(tracks=[_Track("T1"), _Track("T2", devices=[dev])]))
    node, kind, idx, spec = resolve_node_addr(
        ctx, {"parent": {"kind": "track", "index": 2}, "device_index": 1})
    assert node is dev and kind == "track" and idx == 2
    assert spec["terminal"] == "device" and spec["device_index"] == 1


def test_facade_track_as_value():
    src = _Track("Kit")
    ctx = _Ctx(_Song(tracks=[src, _Track("Bass")]))
    node, kind, idx, spec = resolve_node_addr(
        ctx, {"parent": {"kind": "track", "index": 1}, "terminal": "track"})
    assert node is src and kind == "track" and idx == 1
    assert spec["terminal"] == "track"


def test_facade_return_and_master_terminals():
    ret = _Return("A-Hall")
    master = _Track("Master")
    ctx = _Ctx(_Song(returns=[ret], master=master))
    rnode, rkind, ridx, _ = resolve_node_addr(
        ctx, {"parent": {"kind": "return", "index": 1}, "terminal": "return"})
    mnode, mkind, _, _ = resolve_node_addr(
        ctx, {"parent": {"kind": "master"}, "terminal": "master"})
    assert rnode is ret and rkind == "return" and ridx == 1
    assert mnode is master and mkind == "master"


def test_facade_chain_end_to_end():
    chain = _Chain("Lead", devices=[_Dev("x")])
    rack = _Rack("R", chains=[chain])
    ctx = _Ctx(_Song(tracks=[_Track("T1", devices=[rack])]))
    node, kind, idx, spec = resolve_node_addr(
        ctx, {"parent": {"kind": "track", "index": 1}, "device_index": 1,
              "terminal": "chain", "chain_index": 1})
    assert node is chain and spec["terminal"] == "chain"


def test_facade_parent_index_out_of_range():
    ctx = _Ctx(_Song(tracks=[_Track("only")]))
    with pytest.raises(IndexError):
        resolve_node_addr(ctx, {"parent": {"kind": "track", "index": 5}, "device_index": 1})


# --------------------------------------------------------------------------
# get_parameters default_value filter (NODE-ADDR / OQ5) — feeds Chunk-B capture
# --------------------------------------------------------------------------

class _P:
    """A fake DeviceParameter whose default_value can be a real float, absent
    (AttributeError — like FakeParam), or raising (RuntimeError — mirrors Live's
    "no default value available" on some quantized params, e.g. Simpler Snap)."""

    def __init__(self, name, value=0.3, *, default=_MISSING, raises=False):
        self.name = name
        self.value = value
        self._default = default
        self._raises = raises

    def str_for_value(self, v):
        return f"{v:.2f}"

    @property
    def default_value(self):
        if self._raises:
            raise RuntimeError("no default value available for this type of parameter")
        if self._default is _MISSING:
            raise AttributeError("default_value")
        return self._default


class _DevP:
    def __init__(self, params):
        self.name = "D"
        self.class_name = "Operator"
        self.parameters = tuple(params)


def test_get_parameters_default_value_present_omitted_and_raises():
    cont = _P("Cutoff", value=0.3, default=0.5)
    quant = _P("Snap", value=1.0, raises=True)   # Live raises on default_value
    absent = _P("Mystery", value=0.0)            # no default_value attribute
    ctx = _Ctx(_Song(tracks=[_Track("T1", devices=[_DevP([cont, quant, absent])])]))
    out = get_parameters_handler(
        ctx, node={"parent": {"kind": "track", "index": 1}, "device_index": 1})
    by_name = {p["name"]: p for p in out["parameters"]}
    assert by_name["Cutoff"]["default_value"] == 0.5
    # raised / absent → OMITTED (the signal for capture to always-capture these)
    assert "default_value" not in by_name["Snap"]
    assert "default_value" not in by_name["Mystery"]
