"""Tests for src/hallucinote/analyzer_staleness.py — SNP-8R4K chunk 4.

The pure detection logic for the State-2 migration trigger: a saved Live set
where authored devices landed AFTER the HallucinoteAnalyzer (so the analyzer
is no longer the terminal measurement tap and per-stem captures
under-measured those devices). Position-based on the PROBE's chain order;
reuses `is_analyzer_device` as the single identity source.
"""
from __future__ import annotations

from hallucinote.analyzer_identity import ANALYZER_DEVICE_NAME
from hallucinote.analyzer_staleness import (
    detect_stale_analyzer_surfaces,
    find_authored_after_analyzer,
)


def _analyzer(device_index: int) -> dict:
    """A probed analyzer entry (the render-stamped name + the generic M4L class)."""
    return {
        "device_index": device_index,
        "name": ANALYZER_DEVICE_NAME,
        "class_name": "MxDeviceAudioEffect",
        "class_display_name": "Max Audio Effect",
    }


def _device(device_index: int, name: str, class_name: str | None = None) -> dict:
    return {
        "device_index": device_index,
        "name": name,
        "class_name": class_name or name,
    }


# ---------------------------------------------------------------------------
# find_authored_after_analyzer — single chain
# ---------------------------------------------------------------------------


def test_analyzer_last_is_not_stale():
    """Analyzer terminal (last device) → nothing after it → not stale."""
    chain = [
        _device(1, "Operator"),
        _device(2, "Reverb"),
        _analyzer(3),
    ]
    assert find_authored_after_analyzer(chain) == []


def test_authored_device_after_analyzer_is_stale():
    """An authored device interleaved after the analyzer → stale, names it."""
    chain = [
        _device(1, "Operator"),
        _analyzer(2),
        _device(3, "Saturator"),
    ]
    assert find_authored_after_analyzer(chain) == ["Saturator"]


def test_no_analyzer_is_not_stale():
    """No analyzer in the chain → nothing can be non-terminal → not stale.

    (The render loads it terminal at the next capture — chunk 3.)
    """
    chain = [
        _device(1, "Operator"),
        _device(2, "Reverb"),
    ]
    assert find_authored_after_analyzer(chain) == []


def test_analyzer_only_is_not_stale():
    """Analyzer-only chain → no authored device to under-measure → not stale."""
    assert find_authored_after_analyzer([_analyzer(1)]) == []


def test_empty_chain_is_not_stale():
    assert find_authored_after_analyzer([]) == []


def test_multiple_authored_after_analyzer_collects_all_names():
    """Two authored devices after the analyzer → both named, in chain order."""
    chain = [
        _device(1, "Operator"),
        _analyzer(2),
        _device(3, "Saturator"),
        _device(4, "Limiter"),
    ]
    assert find_authored_after_analyzer(chain) == ["Saturator", "Limiter"]


def test_analyzer_first_with_everything_after_is_stale():
    """Analyzer at the head → every following authored device is under-measured."""
    chain = [
        _analyzer(1),
        _device(2, "Operator"),
        _device(3, "Reverb"),
    ]
    assert find_authored_after_analyzer(chain) == ["Operator", "Reverb"]


def test_duplicate_trailing_analyzer_is_not_authored():
    """A second analyzer after the first (legacy accumulation) is NOT authored
    content — only genuine authored devices after the first tap count."""
    chain = [
        _device(1, "Operator"),
        _analyzer(2),
        _analyzer(3),
    ]
    assert find_authored_after_analyzer(chain) == []


def test_duplicate_analyzers_with_authored_between_is_stale():
    """First analyzer is the measurement boundary; an authored device after it
    is stale even if another analyzer follows."""
    chain = [
        _analyzer(1),
        _device(2, "Saturator"),
        _analyzer(3),
    ]
    assert find_authored_after_analyzer(chain) == ["Saturator"]


def test_device_after_analyzer_uses_display_name_fallback_when_unnamed():
    """An entry with no `name` falls back to class_display_name / class_name so
    the operator still gets an actionable label, not an empty string."""
    chain = [
        _analyzer(1),
        {"device_index": 2, "class_name": "Eq8", "class_display_name": "EQ Eight"},
    ]
    assert find_authored_after_analyzer(chain) == ["EQ Eight"]


# ---------------------------------------------------------------------------
# detect_stale_analyzer_surfaces — roll-up over track / return / master
# ---------------------------------------------------------------------------


def test_rollup_empty_when_all_surfaces_clean():
    """A clean/rebuilt set (analyzer terminal everywhere) → no stale surfaces."""
    probed = {
        ("track", 1): [_device(1, "Operator"), _analyzer(2)],
        ("return", 1): [_device(1, "Reverb"), _analyzer(2)],
        ("master", 0): [_device(1, "Limiter"), _analyzer(2)],
    }
    assert detect_stale_analyzer_surfaces(probed) == []


def test_rollup_flags_stale_track_surface():
    probed = {
        ("track", 4): [_device(1, "Operator"), _analyzer(2), _device(3, "Saturator")],
    }
    assert detect_stale_analyzer_surfaces(probed) == [
        "track #4: Saturator after the analyzer",
    ]


def test_rollup_flags_stale_return_surface():
    probed = {
        ("return", 1): [_analyzer(1), _device(2, "Delay")],
    }
    assert detect_stale_analyzer_surfaces(probed) == [
        "return #1: Delay after the analyzer",
    ]


def test_rollup_flags_stale_master_surface_labels_without_suffix():
    """The master is a singleton, so it labels as "master" (never "master #0")
    regardless of which id sentinel the caller used — the push-preflight probe
    map keys it ("master", 0); an older/None sentinel labels the same way."""
    for sentinel in (0, None):
        probed = {
            ("master", sentinel): [_analyzer(1), _device(2, "Ceiling")],
        }
        assert detect_stale_analyzer_surfaces(probed) == [
            "master: Ceiling after the analyzer",
        ], sentinel


def test_rollup_across_track_return_and_master():
    """Stale surfaces of every kind are collected; clean ones are silent;
    output is deterministically sorted (kind, then id)."""
    probed = {
        ("track", 4): [_device(1, "Operator"), _analyzer(2), _device(3, "Saturator")],
        ("track", 1): [_device(1, "Bass"), _analyzer(2)],  # clean
        ("return", 1): [_analyzer(1), _device(2, "Delay")],
        ("master", 0): [_analyzer(1), _device(2, "Limiter"), _device(3, "Ceiling")],
    }
    assert detect_stale_analyzer_surfaces(probed) == [
        "master: Limiter, Ceiling after the analyzer",
        "return #1: Delay after the analyzer",
        "track #4: Saturator after the analyzer",
    ]


def test_rollup_empty_map_is_silent():
    assert detect_stale_analyzer_surfaces({}) == []
