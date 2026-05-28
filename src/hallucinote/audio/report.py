"""MixReport — the audio analysis pipeline's wire format.

Produced by ``analyze_mix(captures_dir, song_db_conn)`` and serialized to
``songs/<slug>/analysis/<iso-ts>.json``. The MCP handler
(``ableton_analysis(action='analyze')``) is a thin wrapper that calls
``analyze_mix`` and writes this report.

Schema version is pinned in the report itself; downstream consumers
(future ``compare_to`` differs, dashboards) discriminate by
``schema_version`` rather than file path or git tag.

The MVP carries skeleton fields that aren't yet populated:

  ``compare_to``         — baseline-diff field. Reserved per spike §9
                            (P2 backlog). Always ``None`` in MVP output.
  ``skipped_analyses``   — explicit record when a declared analysis
                            couldn't run (e.g. no declared decay times
                            in the song DB for the reverb check). Keeps
                            us honest per CLAUDE.md "Never silently drop
                            a requirement."

Per project preferences: ``@dataclass`` for in-process value objects;
serialization is one explicit ``to_json_dict()`` boundary (not
``dataclasses.asdict()`` — we want to control field ordering and reject
non-JSON-safe nesting at the seam).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = "1"

SurfaceKind = Literal["track", "return", "master"]
Severity = Literal["info", "warning", "blocking"]

_VALID_SURFACE_KINDS = ("track", "return", "master")
_VALID_SEVERITIES = ("info", "warning", "blocking")


@dataclass(frozen=True)
class LoudnessMetrics:
    """Per-surface loudness measurements.

    All values in dB. LUFS-I follows BS.1770-4 gating; LUFS-S median is the
    50th percentile of 3-second short-term blocks; LUFS-M peak is the max
    400 ms momentary block. True peak is 4×-oversampled sample-peak in dBTP.
    """
    lufs_i: float
    lufs_s_median: float
    lufs_m_peak: float
    true_peak_dbtp: float


@dataclass(frozen=True)
class StemMetrics:
    """One row per captured surface (audio track / return / master)."""
    track_id: str
    surface_kind: SurfaceKind
    surface_name: str
    loudness: LoudnessMetrics

    def __post_init__(self) -> None:
        if self.surface_kind not in _VALID_SURFACE_KINDS:
            raise ValueError(
                f"surface_kind={self.surface_kind!r} must be one of "
                f"{_VALID_SURFACE_KINDS}"
            )


@dataclass(frozen=True)
class MasterOvershoot:
    """A master-bus true-peak overshoot window with per-stem attribution.

    ``attribution`` is ranked top-to-bottom; each entry is
    ``(track_id, fraction)`` where ``fraction`` is the stem's share of RMS
    energy in ``dominant_band`` during the overshoot window. Sums may not
    reach 1.0 — only top contributors are surfaced; long-tail stems are
    aggregated into the residual.
    """
    start_beat: float
    end_beat: float
    peak_dbtp: float
    dominant_band: str
    attribution: list[tuple[str, float]]


@dataclass(frozen=True)
class ReverbVerification:
    """One declared dry-stem → wet-return-send verification result.

    ``measured_rt60_s`` is the RT60 measured from the Wiener-deconvolved
    IR via Schroeder backward energy integration
    (``pyroomacoustics.experimental.rt60.measure_rt60``).
    ``within_tolerance`` is ``abs(measured - declared) <= tolerance_s``.
    """
    dry_track_id: str
    wet_return_track_id: str
    declared_rt60_s: float
    measured_rt60_s: float
    within_tolerance: bool
    tolerance_s: float


@dataclass(frozen=True)
class Finding:
    """Structured intent-keyed observation from the analysis pass.

    The MVP populates findings keyed to DB-declared intent (track role,
    send target, declared decay). The LLM ranks/filters by ``kind`` +
    ``severity`` without parsing prose — per spike §6.

    ``db_reference`` is a free-form pointer back into the song DB
    (cue point, send id, track role) — purely for the LLM to cite when
    explaining the finding.
    """
    kind: str
    severity: Severity
    subject: str
    metric: str
    observed: float
    expected: float
    db_reference: str | None = None

    def __post_init__(self) -> None:
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"severity={self.severity!r} must be one of "
                f"{_VALID_SEVERITIES}"
            )


@dataclass
class MixReport:
    """Top-level wire format. Mutable so ``analyze_mix`` can populate
    progressively without re-allocating; the ``to_json_dict()`` boundary
    is where it becomes pure data."""

    song_slug: str
    captures_dir: str
    captured_at: str
    analyzer_signature: str
    stems: list[StemMetrics]
    master: StemMetrics
    returns: list[StemMetrics] = field(default_factory=list)
    overshoots: list[MasterOvershoot] = field(default_factory=list)
    reverb_verifications: list[ReverbVerification] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    skipped_analyses: list[dict[str, Any]] = field(default_factory=list)
    compare_to: dict[str, Any] | None = None
    schema_version: str = SCHEMA_VERSION

    def to_json_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict.

        Explicit rather than ``dataclasses.asdict`` because (a) we want a
        stable field ORDER in the file (schema_version first, payload
        next, optional/empty fields last), and (b) tuples serialize as
        lists in JSON anyway — we make that explicit at the boundary so
        round-trip equality of typed objects works.
        """
        return {
            "schema_version": self.schema_version,
            "song_slug": self.song_slug,
            "captures_dir": self.captures_dir,
            "captured_at": self.captured_at,
            "analyzer_signature": self.analyzer_signature,
            "master": _stem_to_dict(self.master),
            "stems": [_stem_to_dict(s) for s in self.stems],
            "returns": [_stem_to_dict(r) for r in self.returns],
            "overshoots": [_overshoot_to_dict(o) for o in self.overshoots],
            "reverb_verifications": [
                _reverb_to_dict(r) for r in self.reverb_verifications
            ],
            "findings": [_finding_to_dict(f) for f in self.findings],
            "skipped_analyses": list(self.skipped_analyses),
            "compare_to": self.compare_to,
        }


def _stem_to_dict(s: StemMetrics) -> dict[str, Any]:
    return {
        "track_id": s.track_id,
        "surface_kind": s.surface_kind,
        "surface_name": s.surface_name,
        "loudness": {
            "lufs_i": s.loudness.lufs_i,
            "lufs_s_median": s.loudness.lufs_s_median,
            "lufs_m_peak": s.loudness.lufs_m_peak,
            "true_peak_dbtp": s.loudness.true_peak_dbtp,
        },
    }


def _overshoot_to_dict(o: MasterOvershoot) -> dict[str, Any]:
    return {
        "start_beat": o.start_beat,
        "end_beat": o.end_beat,
        "peak_dbtp": o.peak_dbtp,
        "dominant_band": o.dominant_band,
        "attribution": [list(pair) for pair in o.attribution],
    }


def _reverb_to_dict(r: ReverbVerification) -> dict[str, Any]:
    return {
        "dry_track_id": r.dry_track_id,
        "wet_return_track_id": r.wet_return_track_id,
        "declared_rt60_s": r.declared_rt60_s,
        "measured_rt60_s": r.measured_rt60_s,
        "within_tolerance": r.within_tolerance,
        "tolerance_s": r.tolerance_s,
    }


def _finding_to_dict(f: Finding) -> dict[str, Any]:
    return {
        "kind": f.kind,
        "severity": f.severity,
        "subject": f.subject,
        "metric": f.metric,
        "observed": f.observed,
        "expected": f.expected,
        "db_reference": f.db_reference,
    }
