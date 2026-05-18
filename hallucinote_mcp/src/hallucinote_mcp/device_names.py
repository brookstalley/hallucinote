"""Live device class_name ↔ browser display name translation.

Live exposes built-in devices via TWO name spaces:

- **Internal class name** — ``device.class_name`` (returned by ``device.list``
  and captured into the DB). Examples: ``Compressor2``, ``Eq8``,
  ``StereoGain``, ``DrumGroupDevice``, ``InstrumentMeld``.
- **Browser display name** — what shows up in Live's browser and what
  ``browser.load_item`` looks up by name. Examples: ``Compressor``, ``EQ
  Eight``, ``Utility``, ``Drum Rack``, ``Meld``.

A round-trip (capture → push → load) breaks for every built-in whose
class name differs from its display name: the planner emits
``device.load(kind='Compressor2')`` and the handler's browser walk finds
no node named ``Compressor2``. This table bridges the gap.

**Maintenance**: this list covers built-in Live devices observed in
real songs. Third-party plugins use their plugin name as both class and
display (no translation needed). When Live adds new built-ins with
renamed display names, add them here. Empirical source: read each
device's ``class_name`` after loading via the browser and compare to
the browser node's ``name``.

For unmapped names (third-party plugins, future built-ins), callers
should fall through to the direct display-name match — that's still the
primary lookup path. This table is the fallback when class_name doesn't
match a browser node directly.
"""
from __future__ import annotations


# Class name → Browser display name. Verified against Ableton Live 12.4
# browser dumps. Entries where class_name == display_name are omitted
# (the direct lookup already works for those).
_CLASS_TO_DISPLAY: dict[str, str] = {
    # Audio effects
    "Compressor2": "Compressor",
    "Chorus2": "Chorus-Ensemble",
    "Eq8": "EQ Eight",
    "Eq3": "EQ Three",
    "FilterEQ3": "EQ Three",
    "MultibandDynamics": "Multiband Dynamics",
    "StereoGain": "Utility",
    "GlueCompressor": "Glue Compressor",
    "GrainDelay": "Grain Delay",
    "FilterDelay": "Filter Delay",
    "HybridReverb": "Hybrid Reverb",
    "DrumBuss": "Drum Buss",
    "BeatRepeat": "Beat Repeat",
    "AutoFilter": "Auto Filter",
    "AutoPan": "Auto Pan-Tremolo",
    "Phaser": "Phaser-Flanger",
    "Flanger": "Phaser-Flanger",
    "DynamicTube": "Dynamic Tube",
    "VinylDistortion": "Vinyl Distortion",
    "SpectralResonator": "Spectral Resonator",
    "SpectralTime": "Spectral Time",
    "EnvelopeFollower": "Envelope Follower",
    "AlignDelay": "Align Delay",
    "AutoShift": "Auto Shift",
    "ChannelEQ": "Channel EQ",
    # Instruments
    "InstrumentMeld": "Meld",
    "InstrumentVector": "Wavetable",
    "LoungeLizard": "Electric",
    "AnalogSimplerDevice": "Simpler",
    "ExternalInstrument": "External Instrument",
    # Racks (group devices)
    "DrumGroupDevice": "Drum Rack",
    "InstrumentGroupDevice": "Instrument Rack",
    "AudioEffectGroupDevice": "Audio Effect Rack",
    "MidiEffectGroupDevice": "MIDI Effect Rack",
    # Note: the following classes are the same in both namespaces and
    # don't need entries (kept here as a checked-against list for the
    # maintainer to confirm new Live versions haven't renamed them):
    #
    #   Operator, Saturator, Reverb, Delay, Echo, Limiter, Gate,
    #   Overdrive, Pedal, Cabinet, Looper, Roar, Tuner, Spectrum,
    #   Shaper, Shifter, Vocoder, Erosion, Resonators, Redux, Amp,
    #   Corpus, LFO, Shaper.
}


def class_name_to_display(class_name: str) -> str | None:
    """Return the browser display name for a Live device class name.

    Returns ``None`` if the class name has no known translation. Callers
    should fall back to the direct display-name lookup with the original
    string in that case — third-party plugins typically use the same
    name in both spaces.
    """
    return _CLASS_TO_DISPLAY.get(class_name)


__all__ = ["class_name_to_display"]
