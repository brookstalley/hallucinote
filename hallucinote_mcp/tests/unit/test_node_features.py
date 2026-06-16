"""NODE-ADDR — the node-feature capability matrix (design §2 / §2b).

The matrix is a single typed source (``hallucinote_mcp.node_features``) that three
consumers derive from: the published resource, the generic stub responder, and
teaching errors. These tests enforce the invariants that keep the tri-state
honest and the **cross-consumer consistency** that makes "can't drift" a tested
fact, not a prose claim (Critic note a).
"""
from __future__ import annotations

import json

import pytest

from hallucinote_mcp.node_features import (
    DEFAULT_LIVE_VERSION,
    MATRIX,
    MATRIX_RESOURCE_URI,
    NODE_KINDS,
    Cell,
    FeatureStatus,
    cell_response,
    matrix_payload,
    resolve_cell,
    teaching_error,
)


def _all_cells() -> list[tuple[str, Cell]]:
    return [(feat.key, cell) for feat in MATRIX for cell in feat.cells]


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------


def test_feature_keys_unique():
    keys = [f.key for f in MATRIX]
    assert len(keys) == len(set(keys)), f"duplicate feature keys: {keys}"


def test_no_duplicate_cells():
    seen: set[tuple[str, str]] = set()
    for key, cell in _all_cells():
        pair = (key, cell.node_kind)
        assert pair not in seen, f"duplicate cell {pair}"
        seen.add(pair)


def test_every_cell_node_kind_is_known():
    for key, cell in _all_cells():
        assert cell.node_kind in NODE_KINDS, (
            f"{key}/{cell.node_kind!r} is not a known node kind {sorted(NODE_KINDS)}"
        )


def test_every_cell_determination_is_valid():
    for key, cell in _all_cells():
        assert cell.determination in ("static", "probe"), (
            f"{key}/{cell.node_kind}: bad determination {cell.determination!r}"
        )


def test_non_supported_cells_carry_documented_fields():
    """The whole point of the tri-state is honesty: every NOT_IMPLEMENTED /
    UNSUPPORTED_IN_LIVE cell must say WHY (reason) and prove the Live verdict
    (live_evidence). A bare flag is exactly what §2b forbids."""
    for key, cell in _all_cells():
        if cell.status is FeatureStatus.SUPPORTED:
            continue
        assert cell.reason.strip(), f"{key}/{cell.node_kind}: missing reason"
        assert cell.live_evidence.strip(), (
            f"{key}/{cell.node_kind}: missing live_evidence"
        )


def test_not_implemented_cells_point_somewhere_actionable():
    """NOT_IMPLEMENTED means 'a request can change this' — so it must carry a
    request tag (where to ask) so the agent can route the ask, per §2b."""
    for key, cell in _all_cells():
        if cell.status is FeatureStatus.NOT_IMPLEMENTED:
            assert cell.request_tag.strip(), (
                f"{key}/{cell.node_kind}: NOT_IMPLEMENTED needs a request_tag"
            )


# ---------------------------------------------------------------------------
# Probe-confirmed verdicts are present (probe-findings.md, 2026-06-15) — guards
# against a future edit silently softening a wall or hardening a buildable.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "feature,node_kind",
    [
        ("send_pre_post", "send"),
        ("macro_mapping_target", "device"),
        ("output_routing", "chain"),
        ("monitor_state", "return"),
        ("monitor_state", "master"),
        # NODE-ADDR Chunk E: the zone probe (2026-06-15) found NO key/velocity/
        # chain-select surface on a Chain — not even on a selector rack — so
        # zones are a hard LOM wall, re-scoped from NOT_IMPLEMENTED.
        ("zones", "chain"),
        # NODE-ADDR Chunk D: a macro DeviceParameter.name has no setter — custom
        # names are a LOM wall (the value rides device_parameters; the NAME does
        # not).
        ("macro_names", "device"),
    ],
)
def test_probed_walls_are_unsupported_in_live(feature, node_kind):
    _, cell = resolve_cell(feature, node_kind)
    assert cell.status is FeatureStatus.UNSUPPORTED_IN_LIVE


@pytest.mark.parametrize(
    "feature,node_kind",
    [
        # macro_values/device flipped SUPPORTED in NODE-ADDR Chunk D (macros are
        # device parameters); macro_names/device became a wall — see the other
        # two guards.
        ("macro_variations", "device"),
        ("crossfade_assign", "track"),
        ("input_routing", "return"),
        ("input_routing", "master"),
        ("output_routing", "return"),
        ("output_routing", "master"),
        # choke_out_note/chain flipped SUPPORTED in NODE-ADDR Chunk C, and
        # mixer_state/chain in Chunk F — see test_shipped_features_are_supported.
        # zones/chain re-scoped to UNSUPPORTED_IN_LIVE in Chunk E (see
        # test_probed_walls_are_unsupported_in_live).
        # NODE-ADDR Chunk F: chain SENDS deferred (mixer_state covers vol/pan/
        # mute/solo; sends into a rack's own return chains are rarely populated).
        ("send_levels", "chain"),
    ],
)
def test_probed_buildables_are_not_implemented(feature, node_kind):
    _, cell = resolve_cell(feature, node_kind)
    assert cell.status is FeatureStatus.NOT_IMPLEMENTED


@pytest.mark.parametrize(
    "feature,node_kind",
    [
        ("device_parameters", "device"),
        ("sidechain_source", "device"),
        ("mixer_state", "track"),
        ("send_levels", "return"),
        ("output_routing", "track"),
        ("monitor_state", "track"),
        # NODE-ADDR Chunk C: per-DrumChain choke_group / out_note authoring.
        ("choke_out_note", "chain"),
        # NODE-ADDR Chunk F: per-chain mixer state (mute/solo/volume/pan).
        ("mixer_state", "chain"),
        # NODE-ADDR Chunk D: macro values ARE device parameters (authored via
        # the device_parameters path) — supported; only the NAME is a wall.
        ("macro_values", "device"),
    ],
)
def test_shipped_features_are_supported(feature, node_kind):
    _, cell = resolve_cell(feature, node_kind)
    assert cell.status is FeatureStatus.SUPPORTED


# ---------------------------------------------------------------------------
# resolve_cell / cell_response / teaching_error
# ---------------------------------------------------------------------------


def test_resolve_cell_unknown_feature_teaches():
    with pytest.raises(ValueError, match="unknown node feature"):
        resolve_cell("teleport", "device")


def test_resolve_cell_unclassified_node_kind_teaches():
    with pytest.raises(ValueError, match="not classified on node kind"):
        # device_parameters is classified for 'device' only.
        resolve_cell("device_parameters", "master")


def test_cell_response_carries_status_fields_and_matrix_pointer():
    resp = cell_response("macro_variations", "device")
    assert resp["feature"] == "macro_variations"
    assert resp["node_kind"] == "device"
    assert resp["status"] == "NOT_IMPLEMENTED"
    assert resp["reason"]
    assert resp["live_evidence"]
    assert resp["request_tag"]
    assert resp["matrix_resource"] == MATRIX_RESOURCE_URI
    assert resp["live_version"] == DEFAULT_LIVE_VERSION


def test_teaching_error_not_implemented_is_actionable():
    msg = teaching_error("macro_variations", "device")
    assert "Macro variations" in msg
    assert "device" in msg
    assert "not yet implemented" in msg
    assert "deferred" in msg  # the request tag fragment
    assert MATRIX_RESOURCE_URI in msg


def test_teaching_error_unsupported_says_route_around():
    msg = teaching_error("send_pre_post", "send")
    assert "route around" in msg
    assert MATRIX_RESOURCE_URI in msg
    assert "not addressable" in msg


def test_teaching_error_on_supported_is_misuse():
    with pytest.raises(ValueError, match="SUPPORTED"):
        teaching_error("device_parameters", "device")


# ---------------------------------------------------------------------------
# matrix_payload + cross-consumer consistency (Critic note a)
# ---------------------------------------------------------------------------


def test_matrix_payload_is_json_serializable_with_expected_shape():
    payload = matrix_payload()
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped["schema_version"] == 1
    assert set(round_tripped["legend"]) == {s.value for s in FeatureStatus}
    assert round_tripped["live_version"] == DEFAULT_LIVE_VERSION
    kinds = {k["kind"] for k in round_tripped["node_kinds"]}
    assert kinds == set(NODE_KINDS)
    feature_keys = {f["key"] for f in round_tripped["features"]}
    assert feature_keys == {f.key for f in MATRIX}


def test_resource_payload_equals_stub_responses_cell_for_cell():
    """THE consistency test: every cell the published resource renders is byte-for-
    byte the same dict the runtime stub responder returns. Doc and enforcement are
    one source — they cannot disagree (§2a/§2b, Critic note a)."""
    payload = matrix_payload()
    rendered = {
        (feat["key"], cell["node_kind"]): cell
        for feat in payload["features"]
        for cell in feat["cells"]
    }
    expected = {
        (key, cell.node_kind): cell_response(key, cell.node_kind)
        for key, cell in _all_cells()
    }
    assert rendered == expected


def test_teaching_errors_derive_from_the_same_cell():
    """The third consumer: every non-SUPPORTED teaching error carries the same
    title + evidence the resource/stub do — so all three readers resolve from the
    one Cell, never a hand-written duplicate."""
    for feat in MATRIX:
        for cell in feat.cells:
            if cell.status is FeatureStatus.SUPPORTED:
                continue
            msg = teaching_error(feat.key, cell.node_kind)
            assert feat.title in msg
            # a distinctive fragment of the cell's evidence rides the error
            assert cell.live_evidence.split("(")[0].strip()[:20] in msg


def test_resource_loader_serializes_the_table():
    """The registered resource loader returns exactly the table payload — the
    resource is not a separate hand-maintained copy."""
    from hallucinote_mcp.resources import _node_feature_matrix

    assert json.loads(_node_feature_matrix()) == json.loads(json.dumps(matrix_payload()))
