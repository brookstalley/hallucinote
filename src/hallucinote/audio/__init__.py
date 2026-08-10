"""Hallucinote audio analysis pipeline.

The pure-Python computation half of the audio-analysis MVP. Reads stems
+ master WAVs written by ``hallucinote_mcp.actions.ableton_render``
(see ``hallucinote_mcp/src/hallucinote_mcp/handlers/render.py``) and a
song's DB-recorded intent (track role, send targets, declared decay
times), produces a ``MixReport`` JSON keyed to that intent.

Module layout:

  ``report``       — ``MixReport`` schema + sub-dataclasses (wire format).
  ``io``           — ``load_capture`` reads manifest + WAVs from disk.
  ``loudness``     — BS.1770-4 LUFS-I / LUFS-S / LUFS-M + 4× true peak.
  ``attribution``  — master-bus overshoot detection + per-band per-stem
                     contribution attribution.
  ``reverb``       — per-return decay-tail RT60 (Schroeder on the return's
                     own captured ring-out) vs. declared intent.
  ``section``      — slice captured audio into named section windows so
                     loudness can be scoped to verse / chorus / bridge.
  ``masking``      — inter-stem spectral masking (which stems mask which,
                     per section) — neutral evidence for the interpreter.
  ``timing``       — per-part onset-vs-grid feel (push/drag/swing), the
                     read-side counterpart to the ``feel`` generator.

The MCP wrapper that exposes this as a tool lives in
``hallucinote_mcp/src/hallucinote_mcp/{actions,handlers}/analysis.py``;
this package never imports MCP. Per project preferences "Layer folders
inside ``src/hallucinote/``" — audio is a sibling of ``db``, ``sync``,
``generators``.
"""
from __future__ import annotations

from .analyze import DeclaredReverbSend, DeclaredWidthControl, analyze_mix
from .automation import DeclaredEnvelope
from .codeversion import disk_signature, is_stale, loaded_signature
from .energy import realize_energy
from .report import (
    BandContribution,
    EnergyInversion,
    EnergyRealization,
    EnvelopeVerification,
    Finding,
    LoudnessMetrics,
    MasterOvershoot,
    MixReport,
    ReverbVerification,
    SectionEnergy,
    SectionMetrics,
    StemMetrics,
    TimbreMetrics,
)
from .section import SectionWindow, TempoSegment

__all__ = [
    "BandContribution",
    "DeclaredEnvelope",
    "DeclaredReverbSend",
    "DeclaredWidthControl",
    "disk_signature",
    "EnergyInversion",
    "EnergyRealization",
    "EnvelopeVerification",
    "Finding",
    "is_stale",
    "loaded_signature",
    "LoudnessMetrics",
    "MasterOvershoot",
    "MixReport",
    "realize_energy",
    "ReverbVerification",
    "SectionEnergy",
    "SectionMetrics",
    "SectionWindow",
    "StemMetrics",
    "TempoSegment",
    "TimbreMetrics",
    "analyze_mix",
]
