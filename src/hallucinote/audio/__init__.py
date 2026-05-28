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
  ``reverb``       — Wiener-deconvolved IR + RT60 measurement vs. declared
                     intent.
  ``section``      — slice captured audio into named section windows so
                     loudness can be scoped to verse / chorus / bridge.

The MCP wrapper that exposes this as a tool lives in
``hallucinote_mcp/src/hallucinote_mcp/{actions,handlers}/analysis.py``;
this package never imports MCP. Per project preferences "Layer folders
inside ``src/hallucinote/``" — audio is a sibling of ``db``, ``sync``,
``generators``.
"""
from __future__ import annotations

from .analyze import DeclaredReverbSend, analyze_mix
from .report import (
    BandContribution,
    Finding,
    LoudnessMetrics,
    MasterOvershoot,
    MixReport,
    ReverbVerification,
    SectionMetrics,
    StemMetrics,
)
from .section import SectionWindow

__all__ = [
    "BandContribution",
    "DeclaredReverbSend",
    "Finding",
    "LoudnessMetrics",
    "MasterOvershoot",
    "MixReport",
    "ReverbVerification",
    "SectionMetrics",
    "SectionWindow",
    "StemMetrics",
    "analyze_mix",
]
