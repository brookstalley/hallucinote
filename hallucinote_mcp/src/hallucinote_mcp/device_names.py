"""Rack-kind → canonical browser-root lookup.

Arc 4 / D4 trimmed this module to one concern. The previous role —
translating Live's internal ``device.class_name`` to the browser
display name (``Compressor2 → Compressor``,
``DrumGroupDevice → Drum Rack``, etc.) — is now obsolete: Live
exposes the right value natively via ``device.class_display_name``,
which the MCP capture probes read and pull writes into
``devices.kind``. The loader then matches on ``kind`` directly.

What remains: a small mapping for the four RACK display names. Racks
are the only device kinds where a name match in the wrong browser
root would silently pick the wrong device — a user-saved Instrument
Rack preset named "Drum Rack" in the instruments root would
otherwise shadow the canonical empty Drum Rack node in the drums
root (W7-0 finding). Restricting rack walks to the canonical root
prevents this.

If Live adds new rack kinds in future versions, extend
``_RACK_KIND_TO_BROWSER_ROOT``. The set is bounded by Live's rack
device family, not by every device class — much smaller maintenance
footprint than the deleted ``_CLASS_TO_DISPLAY`` table.
"""
from __future__ import annotations


# Live's rack display names → canonical browser root. Each rack lives in
# exactly one category; restricting the load-by-name walk to that root
# prevents cross-category collisions (W7-0).
_RACK_KIND_TO_BROWSER_ROOT: dict[str, str] = {
    "Drum Rack": "drums",
    "Instrument Rack": "instruments",
    "Audio Effect Rack": "audio_effects",
    "MIDI Effect Rack": "midi_effects",
}


def browser_root_for_rack_kind(kind: str) -> str | None:
    """Return the canonical browser-root attribute for a rack display name.

    Returns one of ``"drums"`` / ``"instruments"`` / ``"audio_effects"`` /
    ``"midi_effects"`` for the four rack display names; ``None`` for
    everything else. Callers loading a rack ``kind`` should restrict
    their browser walk to this root.
    """
    return _RACK_KIND_TO_BROWSER_ROOT.get(kind)


__all__ = [
    "browser_root_for_rack_kind",
]
