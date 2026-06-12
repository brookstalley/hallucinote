"""Canonical DB-routing-kind ↔ Live display_name correspondence (RTE-1K9T).

Single source of truth shared by BOTH directions of the sync layer:

  * the push planner (``push/routing.py``) maps a DB ``*_routing_kind`` → the
    Live ``display_name`` the MCP routing actions expect;
  * the pull apply layer (``pull/mix.py``) maps a Live ``display_name`` back to
    a DB kind.

Deriving both directions from ONE mapping is the whole point of this module: a
display_name fixed in one place and not the other would make push and pull
silently disagree about what (say) ``ext_out`` means. The ``track`` kind is NOT
in these maps — it resolves to a specific target track's own name (push: the
target's ``name``; pull: a name→id lookup), so it is handled at each call site.

These keys mirror the closed mutator vocabularies in
``db/mutations/tracks.py`` (``OUTPUT_ROUTING_KINDS`` / ``INPUT_ROUTING_KINDS``)
minus ``'track'``.
"""
from __future__ import annotations

# DB kind → Live display_name (the non-track kinds). Live-probed (Live 12.4.2).
OUTPUT_KIND_DISPLAY_NAME: dict[str, str] = {
    "master": "Main",
    "sends_only": "Sends Only",
    "ext_out": "Ext. Out",
}
INPUT_KIND_DISPLAY_NAME: dict[str, str] = {
    "ext_in": "Ext. In",
    "no_input": "No Input",
    "resampling": "Resampling",
}

# Inverse (Live display_name → DB kind) — the pull direction.
OUTPUT_DISPLAY_NAME_KIND: dict[str, str] = {
    v: k for k, v in OUTPUT_KIND_DISPLAY_NAME.items()
}
INPUT_DISPLAY_NAME_KIND: dict[str, str] = {
    v: k for k, v in INPUT_KIND_DISPLAY_NAME.items()
}

# Live's DEFAULT route — the routing a track has with no explicit authoring.
# Pull treats a DB NULL routing column as EQUIVALENT to the default so a first
# pull of an unrouted track doesn't churn every NULL into an explicit default
# (D8). Only OUTPUT and MONITOR have a default constant here: both are closed,
# live-probed-certain domains ("Main" / "Auto"). INPUT deliberately has NO
# default constant — Live's non-track input default is open + hardware-bound
# (a MIDI track defaults to "All Ins", an interface-bound audio track to a
# channel name) and is NOT live-probed, so a NULL≡default rule on input would
# rest on an unverified premise. V1 pull therefore persists ONLY a track→track
# input (which is never a default and needs no default constant); fixed input
# kinds + arbitrary hardware inputs are deferred until a live-probe pins Live's
# input defaults (D6/D8; enqueued in operator-verification.md).
OUTPUT_DEFAULT_KIND = "master"
MONITOR_DEFAULT = "Auto"


__all__ = [
    "OUTPUT_KIND_DISPLAY_NAME",
    "INPUT_KIND_DISPLAY_NAME",
    "OUTPUT_DISPLAY_NAME_KIND",
    "INPUT_DISPLAY_NAME_KIND",
    "OUTPUT_DEFAULT_KIND",
    "MONITOR_DEFAULT",
]
