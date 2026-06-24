"""Unit tests for Live return-track name normalization."""
from __future__ import annotations

from hallucinote.return_naming import (
    normalize_live_return_name,
    strip_analyzer_suffix,
    strip_return_slot_prefix,
)


def test_strip_analyzer_suffix_removes_render_appended_name():
    """SYN-RENDER-RELINK: the render appends ` | HallucinoteAnalyzer` to a return."""
    assert strip_analyzer_suffix("Reverb | HallucinoteAnalyzer") == "Reverb"


def test_strip_analyzer_suffix_is_idempotent_and_none_safe():
    assert strip_analyzer_suffix("Reverb") == "Reverb"
    assert strip_analyzer_suffix(None) is None


def test_strip_analyzer_suffix_tolerates_spacing_variants():
    assert strip_analyzer_suffix("Delay|HallucinoteAnalyzer") == "Delay"
    assert strip_analyzer_suffix("Delay  |  HallucinoteAnalyzer") == "Delay"


def test_strip_analyzer_suffix_is_anchored_not_substring():
    """Only a TRAILING analyzer suffix is stripped — a legitimately authored
    ` | ` mid-name (or the device name elsewhere) survives."""
    assert strip_analyzer_suffix("Verb | Room") == "Verb | Room"
    assert (
        strip_analyzer_suffix("HallucinoteAnalyzer | Reverb")
        == "HallucinoteAnalyzer | Reverb"
    )


def test_normalize_live_return_name_strips_both_prefix_and_suffix():
    """The render-renamed, slot-prefixed live form collapses to the DB name."""
    assert (
        normalize_live_return_name("A-Reverb | HallucinoteAnalyzer") == "Reverb"
    )
    # each strip still works alone
    assert normalize_live_return_name("B-Delay") == "Delay"
    assert normalize_live_return_name("Chorus | HallucinoteAnalyzer") == "Chorus"


def test_normalize_live_return_name_none_safe():
    assert normalize_live_return_name(None) is None


def test_strip_return_slot_prefix_unaffected_by_new_helpers():
    """Regression guard: the existing prefix strip behaves as before."""
    assert strip_return_slot_prefix("A-Reverb") == "Reverb"
    assert strip_return_slot_prefix("Reverb") == "Reverb"
