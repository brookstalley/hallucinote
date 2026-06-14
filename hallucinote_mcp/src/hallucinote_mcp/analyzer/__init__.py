"""HallucinoteAnalyzer orchestration.

The analyzer is the M4L device that ships in `hallucinote_mcp/m4l/`. This
package is the Python-side orchestrator that:

- silently auto-loads the analyzer on every track + return + master
  (`setup.ensure_analyzers_loaded`);
- composes the per-instance OSC channel used to deliver the WAV path,
  track identity, and transport-position windows (`osc.AnalyzerOSC`);
- runs the UDP receive sidecar that the analyzer's feature emitter
  streams to during a render (`sidecar.OSCSidecar`).

`handlers/render.py` wires these together into the `ableton_render`
action. Skills (`/song-new`, `/track-new-with-instrument`, `/return-new`)
invoke `ableton_render(action='ensure_loaded')` to keep the analyzer
present without forcing the user to think about it.
"""
from __future__ import annotations

from .setup import (
    ANALYZER_DEVICE_NAME,
    ANALYZER_SIGNATURE,
    AnalyzerInstance,
    AnalyzerLayout,
    StripResult,
    StrippedAnalyzer,
    ensure_analyzers_loaded,
    strip_analyzers,
)

__all__ = [
    "ANALYZER_DEVICE_NAME",
    "ANALYZER_SIGNATURE",
    "AnalyzerInstance",
    "AnalyzerLayout",
    "StripResult",
    "StrippedAnalyzer",
    "ensure_analyzers_loaded",
    "strip_analyzers",
]
