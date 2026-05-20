"""Translation table for Live device class_name ↔ browser display name."""
from __future__ import annotations

import pytest

from hallucinote_mcp.device_names import (
    browser_root_for_rack_kind,
    class_name_to_display,
    strip_device_suffix,
)


@pytest.mark.parametrize(
    "class_name, display_name",
    [
        # The 14 device classes observed in falling-walking's DB.
        ("Compressor2", "Compressor"),
        ("Chorus2", "Chorus-Ensemble"),
        ("Eq8", "EQ Eight"),
        ("DrumBuss", "Drum Buss"),
        ("DrumGroupDevice", "Drum Rack"),
        ("InstrumentGroupDevice", "Instrument Rack"),
        ("InstrumentMeld", "Meld"),
        ("InstrumentVector", "Wavetable"),
        ("LoungeLizard", "Electric"),
        ("StereoGain", "Utility"),
        # Additional renames worth pinning.
        ("AudioEffectGroupDevice", "Audio Effect Rack"),
        ("MidiEffectGroupDevice", "MIDI Effect Rack"),
        ("GlueCompressor", "Glue Compressor"),
        ("GrainDelay", "Grain Delay"),
        ("HybridReverb", "Hybrid Reverb"),
        ("MultibandDynamics", "Multiband Dynamics"),
    ],
)
def test_known_renames(class_name, display_name):
    assert class_name_to_display(class_name) == display_name


@pytest.mark.parametrize(
    "class_name",
    [
        # These exist in falling-walking but match in both name spaces;
        # the table deliberately omits them so the direct lookup is
        # primary. Confirm the table returns None (= "no translation").
        "Operator", "Reverb", "Delay", "Saturator",
        # Third-party plugin (hypothetical) — also no translation.
        "Serum", "Massive X",
        # Unknown class name — empty string, etc.
        "", "NoSuchDevice",
    ],
)
def test_no_translation_returns_none(class_name):
    assert class_name_to_display(class_name) is None


# ---------- strip_device_suffix (M1-A: AnalogDevice → Analog) ----------


@pytest.mark.parametrize(
    "class_name, expected",
    [
        ("AnalogDevice", "Analog"),
        ("OperatorDevice", "Operator"),
        ("CompressorDevice", "Compressor"),
        ("ReverbDevice", "Reverb"),
    ],
)
def test_strip_device_suffix_strips_trailing_device(class_name, expected):
    assert strip_device_suffix(class_name) == expected


@pytest.mark.parametrize(
    "class_name",
    [
        "Compressor2",        # no Device suffix
        "Operator",           # canonical name
        "Eq8",                # rename, not Device-suffixed
        "",                   # empty
        "Device",             # bare suffix — stripping would yield empty
        "InstrumentMeld",     # InstrumentXxx is its own naming pattern
    ],
)
def test_strip_device_suffix_returns_none_for_no_suffix_or_empty(class_name):
    assert strip_device_suffix(class_name) is None


# ---------- browser_root_for_rack_kind (M1-A: cross-category disambiguation) ----------


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
        "DrumGroupDevice",     # class-name form, not display-name — caller
                               # must translate via class_name_to_display
                               # first; the rack-root lookup is keyed on
                               # the browser display name
        "drum rack",           # case-sensitive
        "",                    # empty
    ],
)
def test_browser_root_for_rack_kind_returns_none_for_non_rack(kind):
    assert browser_root_for_rack_kind(kind) is None
