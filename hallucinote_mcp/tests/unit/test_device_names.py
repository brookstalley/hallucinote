"""``device_names`` post-D4 — rack-root lookup only.

The previous translation-table tests (``class_name_to_display``,
``strip_device_suffix``) are gone — those functions were deleted in
Arc 4 / D4 when the loader switched to kind-as-given against Live's
``device.class_display_name`` attribute. What remains is the rack-
kind → canonical-root mapping that protects the device load against
cross-category preset shadowing (W7-0).
"""
from __future__ import annotations

import pytest

from hallucinote_mcp.device_names import browser_root_for_rack_kind


@pytest.mark.parametrize(
    "kind, expected_root",
    [
        ("Drum Rack", "drums"),
        ("Instrument Rack", "instruments"),
        ("Audio Effect Rack", "audio_effects"),
        ("MIDI Effect Rack", "midi_effects"),
    ],
)
def test_browser_root_for_rack_kind_maps_each_rack(kind, expected_root):
    assert browser_root_for_rack_kind(kind) == expected_root


@pytest.mark.parametrize(
    "kind",
    [
        "Compressor",          # not a rack
        "Operator",            # not a rack
        "DrumGroupDevice",     # class-name form, not display-name — under
                               # the post-D4 convention pull writes the
                               # display name into devices.kind, so the
                               # internal-class form should not match the
                               # rack-root lookup either
        "drum rack",           # case-sensitive
        "",                    # empty
    ],
)
def test_browser_root_for_rack_kind_returns_none_for_non_rack(kind):
    assert browser_root_for_rack_kind(kind) is None
