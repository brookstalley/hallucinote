"""Translation table for Live device class_name ↔ browser display name."""
from __future__ import annotations

import pytest

from hallucinote_mcp.device_names import class_name_to_display


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
