"""The node-feature capability matrix — single source of truth for which
features Hallucinote can author on which node kinds (NODE-ADDR design §2).

Addressing is uniform (one ``NodeAddr`` reaches every node); **operations are
not**. Live's feature × node-kind matrix is sparse and ragged, so every feature
operation must capability-probe the resolved node and answer honestly. This
module is that matrix, expressed as a **typed data structure** (Critic note a)
so the three consumers below all derive from one place and cannot drift:

  1. the published resource ``ableton://reference/node-feature-matrix``
     (:func:`matrix_payload`) — read ahead, at no turn cost, so the agent never
     attempts an impossible op blind;
  2. the generic stub responder (:func:`cell_response`) — a deferred feature is
     *one table row*, not a handler; attempting one returns a typed response;
  3. teaching errors (:func:`teaching_error`) — every capability rejection names
     the node kind, the feature, and points back at the matrix.

A ``cross-consumer consistency test`` asserts all three resolve from the same
``Cell`` — "can't drift" is enforced by a test, not asserted in prose.

**Tri-state, because a binary "supported / not" is a lie** (§2b). Every
(feature × node-kind) cell is one of:

  - ``SUPPORTED`` — built; the real handler runs.
  - ``NOT_IMPLEMENTED`` — Live *can* do it here; Hallucinote hasn't built it. A
    roadmap gap a request can change → wait / file a request.
  - ``UNSUPPORTED_IN_LIVE`` — Live's LOM genuinely can't, on this node kind /
    version. A hard wall → route around it, permanently.

The distinction is *actionable*: it tells the agent whether to wait or to route
around. Every non-``SUPPORTED`` cell carries documented fields (reason,
``live_evidence``, workaround, request tag) so the classification is honest and
the response is self-explaining.

**Static vs probe-determined** (``determination``). Structural cells answer from
this table (``static`` — "master has no monitor", always true on the noted Live
version). Device-specific cells (``probe`` — "does *this* plugin expose S/C On?",
"is *this* chain a DrumChain?") record the table verdict but the runtime handler
re-probes the resolved node and never caches a stale "no" — so a Live update or a
different plugin isn't permanently blocked by a frozen verdict.

The matrix is **living**: the frozen/complete thing is the *address grammar*
(see ``handlers.device.validate_node_addr``); features layer on indefinitely, so
rows are added and cells flip ``NOT_IMPLEMENTED`` → ``SUPPORTED`` as chunks land.
Every cell here is LOM-confirmed (NODE-ADDR ``probe-findings.md``, 2026-06-15),
never guessed.

This module is pure data + small pure functions — stdlib only, no Live, no engine
imports — so it is safe to import at server startup and on the Remote-Script side.
It is deliberately **outside** ``_FINGERPRINT_PATHS`` (like ``resources`` and the
``reference/*.json`` files): the matrix is reference content, not wire shape, and
each feature chunk that flips a cell already touches ``handlers``/``actions`` and
re-vendors on its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


MATRIX_RESOURCE_URI = "ableton://reference/node-feature-matrix"

# The Live version the ``static`` verdicts were probed against. Device-specific
# (``probe``) cells re-probe at runtime and are not bound to this.
DEFAULT_LIVE_VERSION = "12.4"


class FeatureStatus(str, Enum):
    """Tri-state support for a (feature × node-kind) cell (design §2b)."""

    SUPPORTED = "SUPPORTED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    UNSUPPORTED_IN_LIVE = "UNSUPPORTED_IN_LIVE"


# The node kinds the matrix is indexed by. The first five are the frozen
# ``NodeAddr`` terminal kinds (``handlers.device._TERMINAL_KINDS``). ``send`` is
# a mix *property* pseudo-kind, not a resolvable terminal — it exists here only
# so the one send-mode feature (pre/post) has an honest home; the agent reads
# "send pre/post is a hard wall" rather than discovering it by trial.
NODE_KINDS: dict[str, str] = {
    "track": "A track strip (MIDI/audio/group) — NodeAddr terminal 'track'.",
    "return": "A return track — NodeAddr terminal 'return'.",
    "master": "The master strip (singleton) — NodeAddr terminal 'master'.",
    "device": "A device at any nesting depth — NodeAddr terminal 'device'.",
    "chain": "A rack chain / DrumChain — NodeAddr terminal 'chain'.",
    "send": "A track/return send (mix property; not an addressable terminal).",
}


@dataclass(frozen=True)
class Cell:
    """One (feature × node-kind) classification.

    ``reason`` / ``live_evidence`` are **required for every non-``SUPPORTED``
    cell** (enforced by test): the reason it is not built (vs. Live-impossible)
    and the LOM surface that proves Live can — or can't — so the tri-state
    classification is honest, not a bare flag. ``workaround`` / ``request_tag``
    are filled when one exists.
    """

    node_kind: str
    status: FeatureStatus
    reason: str = ""
    live_evidence: str = ""
    workaround: str = ""
    request_tag: str = ""
    determination: str = "static"  # "static" | "probe"
    live_version: str = DEFAULT_LIVE_VERSION


@dataclass(frozen=True)
class Feature:
    """A node feature + its per-node-kind cells. ``description`` lives once on the
    feature; each :class:`Cell` carries the node-kind-specific verdict."""

    key: str
    title: str
    description: str
    cells: tuple[Cell, ...]


# ---------------------------------------------------------------------------
# The matrix — every cell LOM-confirmed (NODE-ADDR probe-findings.md). The
# *address* is frozen; this feature list is living (rows added, cells flipped
# as chunks ship). Faithful to design §2 table + the §1.5/§2b probe amendments.
# ---------------------------------------------------------------------------

_SNAPSHOT_WORKAROUND = "Set it in Live's UI, then capture via /song-snapshot."

MATRIX: tuple[Feature, ...] = (
    Feature(
        key="device_parameters",
        title="Device parameters",
        description=(
            "Read / set any DeviceParameter (including device on/off) at any "
            "nesting depth, addressed by NodeAddr."
        ),
        cells=(Cell("device", FeatureStatus.SUPPORTED),),
    ),
    Feature(
        key="mixer_state",
        title="Mixer state (volume / pan / mute / solo / arm)",
        description="Strip-level mixer controls.",
        cells=(
            Cell("track", FeatureStatus.SUPPORTED),
            Cell("return", FeatureStatus.SUPPORTED),
            Cell("master", FeatureStatus.SUPPORTED),
            Cell(
                "chain",
                FeatureStatus.SUPPORTED,
                live_evidence=(
                    "Chain mute/solo are settable bools and the "
                    "ChainMixerDevice exposes volume/panning DeviceParameters "
                    "(probe 2026-06-15). NODE-ADDR Chunk F authors "
                    "volume/pan/mute/solo via the `chain` terminal; the handler "
                    "re-probes mixer_device. Chain SENDS are a separate cell "
                    "(`send_levels`/chain) — not part of mixer state."
                ),
                determination="probe",
            ),
        ),
    ),
    Feature(
        key="send_levels",
        title="Send levels (→ return)",
        description="Per-source send amounts into return tracks (a vector).",
        cells=(
            Cell("track", FeatureStatus.SUPPORTED),
            Cell("return", FeatureStatus.SUPPORTED),
            Cell(
                "chain",
                FeatureStatus.NOT_IMPLEMENTED,
                reason=(
                    "Per-chain sends (into a rack's own return chains) aren't "
                    "built — Chunk F authors chain volume/pan/mute/solo but not "
                    "sends."
                ),
                live_evidence=(
                    "ChainMixerDevice.sends is a DeviceParameter vector, empty "
                    "unless the rack has its own return chains — uncommon "
                    "(probe 2026-06-15)."
                ),
                workaround=_SNAPSHOT_WORKAROUND,
                request_tag="NODE-ADDR (chain sends, deferred)",
            ),
        ),
    ),
    Feature(
        key="output_routing",
        title="Output routing (+ channel)",
        description="Where a node's audio/MIDI output is sent.",
        cells=(
            Cell("track", FeatureStatus.SUPPORTED),
            Cell(
                "return",
                FeatureStatus.NOT_IMPLEMENTED,
                reason="Return/master output routing authoring isn't built.",
                live_evidence=(
                    "available_output_routing_types is populated on return and "
                    "master strips (probe 2026-06-15)."
                ),
                workaround=_SNAPSHOT_WORKAROUND,
                request_tag="NODE-ADDR (routing chunk)",
            ),
            Cell(
                "master",
                FeatureStatus.NOT_IMPLEMENTED,
                reason="Return/master output routing authoring isn't built.",
                live_evidence=(
                    "available_output_routing_types is populated on return and "
                    "master strips (probe 2026-06-15)."
                ),
                workaround=_SNAPSHOT_WORKAROUND,
                request_tag="NODE-ADDR (routing chunk)",
            ),
            Cell(
                "chain",
                FeatureStatus.UNSUPPORTED_IN_LIVE,
                reason="A rack/drum chain has no independent audio output route.",
                live_evidence=(
                    "DrumChain.available_output_routing_types raises "
                    "AttributeError (probe 2026-06-15)."
                ),
                determination="probe",
            ),
        ),
    ),
    Feature(
        key="input_routing",
        title="Input routing (+ channel)",
        description="Where a node's input is taken from.",
        cells=(
            Cell("track", FeatureStatus.SUPPORTED),
            Cell(
                "return",
                FeatureStatus.NOT_IMPLEMENTED,
                reason="Return/master input routing authoring isn't built.",
                live_evidence=(
                    "available_input_routing_types has 30 real entries on "
                    "return/master (probe 2026-06-15 — refutes the earlier "
                    "UNSUPPORTED_IN_LIVE guess for input)."
                ),
                workaround=_SNAPSHOT_WORKAROUND,
                request_tag="NODE-ADDR (routing chunk)",
            ),
            Cell(
                "master",
                FeatureStatus.NOT_IMPLEMENTED,
                reason="Return/master input routing authoring isn't built.",
                live_evidence=(
                    "available_input_routing_types has 30 real entries on "
                    "return/master (probe 2026-06-15 — refutes the earlier "
                    "UNSUPPORTED_IN_LIVE guess for input)."
                ),
                workaround=_SNAPSHOT_WORKAROUND,
                request_tag="NODE-ADDR (routing chunk)",
            ),
        ),
    ),
    Feature(
        key="monitor_state",
        title="Monitor state (In / Auto / Off)",
        description="The input-monitoring switch.",
        cells=(
            Cell("track", FeatureStatus.SUPPORTED),
            Cell(
                "return",
                FeatureStatus.UNSUPPORTED_IN_LIVE,
                reason="Return and master tracks have no monitoring state.",
                live_evidence=(
                    "No current_monitoring_state on return/master strips "
                    "(probe 2026-06-15)."
                ),
            ),
            Cell(
                "master",
                FeatureStatus.UNSUPPORTED_IN_LIVE,
                reason="Return and master tracks have no monitoring state.",
                live_evidence=(
                    "No current_monitoring_state on return/master strips "
                    "(probe 2026-06-15)."
                ),
            ),
        ),
    ),
    Feature(
        key="sidechain_source",
        title="Device sidechain source",
        description=(
            "Route a dynamics device's sidechain from another track. The value "
            "IS a NodeAddr (a track-terminal address)."
        ),
        cells=(
            Cell(
                "device",
                FeatureStatus.SUPPORTED,
                live_evidence=(
                    "Capability-probed per device: the canonical 'S/C On' "
                    "parameter (or naming variant)."
                ),
                determination="probe",
            ),
        ),
    ),
    Feature(
        key="name_color",
        title="Name + color metadata",
        description="The display name and RGB color of a node.",
        cells=(
            Cell("track", FeatureStatus.SUPPORTED),
            Cell("return", FeatureStatus.SUPPORTED),
            Cell("master", FeatureStatus.SUPPORTED),
            Cell("device", FeatureStatus.SUPPORTED),
            Cell("chain", FeatureStatus.SUPPORTED),
        ),
    ),
    Feature(
        key="macro_values",
        title="Macro values",
        description=(
            "The rack macro knob values — authored as ordinary device "
            "parameters (a macro IS a DeviceParameter)."
        ),
        cells=(
            Cell(
                "device",
                FeatureStatus.SUPPORTED,
                live_evidence=(
                    "A rack's macros are its first DeviceParameters "
                    "(parameters[1..8]); set + captured via the "
                    "`device_parameters` feature — no separate macro-value path "
                    "(NODE-ADDR Chunk D probe 2026-06-15). Capture keys params "
                    "by name, so a by-ear macro RENAME (itself unauthorable — "
                    "see `macro_names`) can decouple a stored value from its "
                    "knob on rebuild."
                ),
                determination="probe",
            ),
        ),
    ),
    Feature(
        key="macro_names",
        title="Macro custom names",
        description="A macro knob's custom (renamed) label.",
        cells=(
            Cell(
                "device",
                FeatureStatus.UNSUPPORTED_IN_LIVE,
                reason=(
                    "A macro's custom name cannot be authored — "
                    "DeviceParameter.name is read-only in Live's LOM."
                ),
                live_evidence=(
                    "Setting a macro DeviceParameter.name raises AttributeError "
                    "'property of DeviceParameter object has no setter' "
                    "(NODE-ADDR Chunk D probe 2026-06-15, Live 12.4). A custom "
                    "name rides the rack preset, not the API."
                ),
                workaround=(
                    "Rename the macro in the rack preset / Live's UI; the name "
                    "travels with the preset, not the DB."
                ),
            ),
        ),
    ),
    Feature(
        key="macro_mapping_target",
        title="Macro → parameter mapping",
        description="Which parameter(s) a macro controls.",
        cells=(
            Cell(
                "device",
                FeatureStatus.UNSUPPORTED_IN_LIVE,
                reason=(
                    "Live's LOM exposes no macro mapping TARGET — this is "
                    "DEV-3W9R's core ask and it cannot be built."
                ),
                live_evidence=(
                    "has_macro_mappings / macros_mapped are presence-only and "
                    "never name the destination parameter (probe 2026-06-15)."
                ),
                request_tag="DEV-3W9R (flagged unbuildable, not dropped)",
            ),
        ),
    ),
    Feature(
        key="macro_variations",
        title="Macro variations / snapshots (Live 12)",
        description="Store / recall rack macro-variation snapshots.",
        cells=(
            Cell(
                "device",
                FeatureStatus.NOT_IMPLEMENTED,
                reason=(
                    "Macro variation authoring is deferred (NODE-ADDR Chunk D): "
                    "a recalled variation's macro values are already durable as "
                    "device parameters, and a stored selected_variation_index + "
                    "recall on push would conflict with that captured-value "
                    "truth — so the API exists but isn't wired."
                ),
                live_evidence=(
                    "variation_count / store_variation / "
                    "recall_selected_variation are present, and "
                    "selected_variation_index is settable to 0..count-1 "
                    "(rejects -1) (probe 2026-06-15)."
                ),
                workaround="Store/recall variations in Live's UI.",
                request_tag="NODE-ADDR (macro variations, deferred)",
                determination="probe",
            ),
        ),
    ),
    Feature(
        key="zones",
        title="Key / velocity / chain-select zones",
        description="Per-chain key, velocity, and chain-select ranges.",
        cells=(
            Cell(
                "chain",
                FeatureStatus.UNSUPPORTED_IN_LIVE,
                reason=(
                    "Live's LOM exposes no per-chain key / velocity / "
                    "chain-select zone surface — the rack Zone editor is "
                    "UI-only, so zones can be neither read nor authored via "
                    "the API."
                ),
                live_evidence=(
                    "A Chain — including on a chain-select/selector rack — has "
                    "no key_range / velocity_range / chain_select_range "
                    "attribute; each raises AttributeError (NODE-ADDR Chunk E "
                    "probe 2026-06-15, Live 12.4)."
                ),
                workaround=(
                    "Bake zones into the rack preset / set them in Live's UI; "
                    "they persist in the .als but stay invisible to the API "
                    "(so /song-snapshot cannot capture them either)."
                ),
            ),
        ),
    ),
    Feature(
        key="choke_out_note",
        title="Choke group / out_note (drum chains)",
        description=(
            "Per-DrumChain choke group and MIDI out_note (transpose) remap, "
            "authored via the `chain` terminal. (Chain mute/solo WRITE is "
            "mixer-state — see the 'mixer_state' chain cell.)"
        ),
        cells=(
            Cell(
                "chain",
                FeatureStatus.SUPPORTED,
                live_evidence=(
                    "choke_group / out_note live on a DrumChain (probe "
                    "2026-06-15 — NOT on the DrumPad, NOT on a plain "
                    "instrument-rack Chain). NODE-ADDR Chunk C; the handler "
                    "re-probes, so a non-DrumChain gets a teaching error."
                ),
                determination="probe",
            ),
        ),
    ),
    Feature(
        key="crossfade_assign",
        title="Crossfade assign (A / B)",
        description="Assign a track to crossfader position A or B.",
        cells=(
            Cell(
                "track",
                FeatureStatus.NOT_IMPLEMENTED,
                reason="Crossfade-assign authoring isn't built (minor).",
                live_evidence="MixerDevice.crossfade_assign present (probe 2026-06-15).",
                workaround="Set the A/B assign in Live's UI.",
                request_tag="NODE-ADDR (minor)",
            ),
        ),
    ),
    Feature(
        key="send_pre_post",
        title="Send pre/post-fader mode",
        description="Whether a send taps the signal pre- or post-fader.",
        cells=(
            Cell(
                "send",
                FeatureStatus.UNSUPPORTED_IN_LIVE,
                reason="Live exposes no pre/post-fader mode for a send.",
                live_evidence=(
                    "No pre/post property on MixerDevice or the send "
                    "DeviceParameter (probe 2026-06-15)."
                ),
            ),
        ),
    ),
)


# ---------------------------------------------------------------------------
# Lookup + the three single-source consumers
# ---------------------------------------------------------------------------


_BY_KEY: dict[str, Feature] = {f.key: f for f in MATRIX}


def resolve_cell(feature: str, node_kind: str) -> tuple[Feature, Cell]:
    """Find the ``(Feature, Cell)`` for ``feature`` on ``node_kind`` — the one
    lookup all consumers go through. Teaching ``ValueError`` (listing valid
    options) for an unknown feature or a node kind the feature isn't classified
    on, so a caller fixes the request rather than getting a silent ``None``.
    """
    feat = _BY_KEY.get(feature)
    if feat is None:
        raise ValueError(
            f"unknown node feature {feature!r}; known features: "
            f"{sorted(_BY_KEY)}"
        )
    for cell in feat.cells:
        if cell.node_kind == node_kind:
            return feat, cell
    classified = [c.node_kind for c in feat.cells]
    raise ValueError(
        f"feature {feature!r} is not classified on node kind {node_kind!r}; "
        f"classified for: {classified}"
    )


def cell_response(feature: str, node_kind: str) -> dict[str, object]:
    """The typed response for a (feature × node-kind) cell — the **generic stub
    responder** (design §2b). A feature handler whose capability probe says the
    feature isn't ``SUPPORTED`` returns this instead of a bare error, so every
    deferred / impossible op is machine-visible and self-explaining. Carries the
    documented fields and a pointer to the matrix resource.
    """
    feat, cell = resolve_cell(feature, node_kind)
    return {
        "feature": feat.key,
        "title": feat.title,
        "node_kind": cell.node_kind,
        "status": cell.status.value,
        "description": feat.description,
        "reason": cell.reason,
        "live_evidence": cell.live_evidence,
        "workaround": cell.workaround,
        "request_tag": cell.request_tag,
        "determination": cell.determination,
        "live_version": cell.live_version,
        "matrix_resource": MATRIX_RESOURCE_URI,
    }


def teaching_error(feature: str, node_kind: str) -> str:
    """The teaching-error text for a non-``SUPPORTED`` cell — names the feature,
    the node kind, the actionable verdict (wait vs. route-around), and points
    back at the matrix (design §2a). Raises ``ValueError`` if called on a
    ``SUPPORTED`` cell (misuse — a supported op runs its real handler).
    """
    feat, cell = resolve_cell(feature, node_kind)
    if cell.status is FeatureStatus.SUPPORTED:
        raise ValueError(
            f"{feature!r} is SUPPORTED on a {node_kind!r} node — call its "
            "handler, not teaching_error()"
        )
    head = f"{feat.title} is "
    if cell.status is FeatureStatus.NOT_IMPLEMENTED:
        body = (
            f"not yet implemented on a {node_kind!r} node. {cell.reason} "
            f"Live supports it ({cell.live_evidence})"
        )
        if cell.request_tag:
            body += f"; request via {cell.request_tag}"
        body += "."
    else:  # UNSUPPORTED_IN_LIVE
        body = (
            f"not addressable on a {node_kind!r} node — Live's LOM has no "
            f"surface for it, so route around it ({cell.reason} "
            f"{cell.live_evidence})."
        )
    tail = ""
    if cell.workaround:
        tail += f" Workaround: {cell.workaround}"
    tail += f" See {MATRIX_RESOURCE_URI}."
    return head + body + tail


def matrix_payload() -> dict[str, object]:
    """The full matrix rendered for the published resource (design §2a). Every
    cell here is the same :func:`cell_response` the runtime stub returns, so the
    doc and the enforcement cannot disagree (cross-consumer consistency test)."""
    return {
        "schema_version": 1,
        "live_version": DEFAULT_LIVE_VERSION,
        "address_note": (
            "Addressing is uniform (one NodeAddr reaches every node); operations "
            "are NOT — this matrix is the sparse, ragged truth. Consult it before "
            "authoring. The address grammar is frozen; this feature list is living."
        ),
        "legend": {
            FeatureStatus.SUPPORTED.value: "Built — the real handler runs.",
            FeatureStatus.NOT_IMPLEMENTED.value: (
                "Live can do it here; Hallucinote hasn't built it. Wait / file a "
                "request (see request_tag)."
            ),
            FeatureStatus.UNSUPPORTED_IN_LIVE.value: (
                "Live's LOM genuinely can't, on this node kind/version. Route "
                "around it permanently."
            ),
        },
        "determination_note": (
            "'static' cells answer from this table for the noted live_version; "
            "'probe' cells are device/rack-specific — the runtime handler "
            "re-probes the resolved node and never caches a stale verdict."
        ),
        "node_kinds": [
            {"kind": kind, "description": desc} for kind, desc in NODE_KINDS.items()
        ],
        "features": [
            {
                "key": feat.key,
                "title": feat.title,
                "description": feat.description,
                "cells": [
                    cell_response(feat.key, cell.node_kind) for cell in feat.cells
                ],
            }
            for feat in MATRIX
        ],
    }


__all__ = [
    "FeatureStatus",
    "Cell",
    "Feature",
    "MATRIX",
    "MATRIX_RESOURCE_URI",
    "NODE_KINDS",
    "DEFAULT_LIVE_VERSION",
    "resolve_cell",
    "cell_response",
    "teaching_error",
    "matrix_payload",
]
