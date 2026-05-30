"""Parity lock: theory.MODES must agree with Live's scale dictionary.

The theory layer OWNS its mode definitions (it carries modes Live may not
expose, and must not depend on the MCP package's resource path at import time).
But for every mode that appears in BOTH, the intervals must be identical — a
silent divergence would mean the lint lens validates against a different scale
than Live actually plays. This test is the teeth, in lieu of a cross-package
import (see learnings: "lock a duplicated contract with a parity test").
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hallucinote.theory.model import MODES

_SCALES_JSON = (
    Path(__file__).resolve().parents[3]
    / "hallucinote_mcp/src/hallucinote_mcp/resources/reference/scales.json"
)


def _live_scales() -> dict[str, tuple[int, ...]]:
    data = json.loads(_SCALES_JSON.read_text())
    return {s["name"]: tuple(s["intervals"]) for s in data["scales"]}


def test_scales_json_exists():
    assert _SCALES_JSON.is_file(), f"missing Live scale dictionary at {_SCALES_JSON}"


def test_shared_modes_have_identical_intervals():
    live = _live_scales()
    shared = set(live) & set(MODES)
    assert shared, "expected overlap between theory MODES and Live scales"
    mismatches = {
        name: (MODES[name].intervals, live[name])
        for name in shared
        if tuple(MODES[name].intervals) != live[name]
    }
    assert not mismatches, f"theory/Live scale interval drift: {mismatches}"


@pytest.mark.parametrize("name", ["Dorian", "Phrygian", "Major", "Minor", "Locrian"])
def test_key_modes_present_in_both(name):
    live = _live_scales()
    assert name in MODES and name in live
    assert tuple(MODES[name].intervals) == live[name]
