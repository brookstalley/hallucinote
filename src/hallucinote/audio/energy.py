"""The energy-realization lens (ARR-7M3D) — the RULER.

Joins the declared per-section energy curve (``[SectionEnergy]``, keyed by
``start_beat``) to a render's measured per-section intensity correlates
(LUFS-S median loudness + onset density) and reports, per correlate:

  * a **Spearman ρ** of (declared energy rank, measured intensity rank) over the
    energy-declared sections — the "did intensity track intent overall?" scalar,
    or ``None`` when ρ is undefined (a constant/tied measured correlate makes
    scipy return ``nan``; we record ``None``, never ``nan``); and
  * a list of **inversions** — ordered section pairs where the
    higher-declared-energy section renders LOWER intensity (the "where it didn't"
    locals), well-defined per-pair even when the aggregate ρ is ``None``.

RULER, NOT STAMP: this module reports ρ + inversions + the ranked declared curve
as FACTS. It NEVER re-authors the energy curve, NEVER sets a target loudness, and
NEVER grades pass/fail. A negative ρ is "the arc inverted vs intent" — evidence
``/mix-review`` grades against recalled intent, not a defect.

Join key is ``start_beat``, NEVER name: ``vary()``/recapitulation repeats section
names (two "Chorus" rows), and an ordered-index join also breaks because
out-of-capture sections are skipped (``per_section`` is not positionally aligned).
``start_beat`` is song-unique and robust to both.

Pure, DB-agnostic, no MCP coupling — the handler does the DB→``SectionEnergy``
lift (chunk 4) and supplies the measured correlates from the ``MixReport``.
"""
from __future__ import annotations

import math
import warnings
from typing import Mapping, Sequence

from scipy.stats import ConstantInputWarning, spearmanr

from .report import EnergyInversion, EnergyRealization, SectionEnergy

# The correlate keys the lens ranks. Open by design (DR-3): a correlate adds a
# key here without a shape change. SPECTRAL_CENTROID (AUD-8T3K) fills the slot
# energy.py:38 reserved — section brightness as a spectral-intensity correlate
# (brighter mixes read as more energetic). A neutral ρ, never a grade — like
# loudness and onset density. (ARR-2S9D, when built, adds further keys the same
# way; the registry is the coordination point, not a conflict.)
LOUDNESS = "loudness"
ONSET_DENSITY = "onset_density"
SPECTRAL_CENTROID = "spectral_centroid"


def _is_finite(x: "float | None") -> bool:
    return x is not None and not math.isnan(x) and not math.isinf(x)


def realize_energy(
    declared: Sequence[SectionEnergy],
    measured: Mapping[str, Mapping[float, "float | None"]],
    *,
    surfacing_floor: float = 0.0,
) -> "EnergyRealization | None":
    """Compute the energy-realization read.

    ``declared`` is the energy-declared sections (NULL-energy already excluded by
    the caller), each carrying its ``start_beat``. ``measured`` maps a correlate
    name (``"loudness"`` / ``"onset_density"``) to a ``{start_beat: value}`` map
    of that correlate's per-section measurement; a value that is ``None`` / NaN /
    Inf marks a section whose measured correlate is unavailable (out-of-capture,
    too-quiet, degenerate window).

    ``surfacing_floor`` (DR-5) is the magnitude gate for INVERSIONS: a pair whose
    measured-delta magnitude is below it is DSP noise, not a notable inversion,
    and is dropped from the list. The default ``0.0`` is the conservative
    surface-everything setting (every inversion kept) — the final value awaits a
    human-ear render calibration (see ``analyze._ENERGY_INVERSION_SURFACING_FLOOR``).
    ρ is never gated — it is always computed over the finite-paired sections.

    Returns ``None`` when fewer than 2 energy-declared sections are supplied
    (Spearman needs >= 2 ranks) — the caller records a ``skipped_analyses``
    entry, never a fabricated ρ. Otherwise returns an :class:`EnergyRealization`
    whose ``correlate_rho`` values are ``None``-or-finite by construction (NEVER
    ``nan``), with every exclusion named in ``skipped``.
    """
    declared = list(declared)
    if len(declared) < 2:
        return None

    sections_ranked = sorted(declared, key=lambda s: s.start_beat)

    correlate_rho: dict[str, "float | None"] = {}
    inversions: list[EnergyInversion] = []
    skipped: list[str] = []

    for correlate, by_beat in measured.items():
        # Join by start_beat. Keep sections that have a FINITE measured value;
        # exclude (name) any section whose measured correlate is missing/nan —
        # symmetric with NULL-declared exclusion (W2).
        paired: list[tuple[SectionEnergy, float]] = []
        for sec in sections_ranked:
            val = by_beat.get(sec.start_beat)
            if _is_finite(val):
                paired.append((sec, float(val)))
            else:
                skipped.append(
                    f"{correlate} excluded section {sec.name!r} "
                    f"(start_beat={sec.start_beat:g}): measured value "
                    f"missing/nan"
                )

        if len(paired) < 2:
            correlate_rho[correlate] = None
            skipped.append(
                f"{correlate} ρ undefined: fewer than 2 sections have a finite "
                f"measured correlate"
            )
            continue

        # Inversions: every unordered pair where the higher-DECLARED-energy
        # section renders LOWER measured intensity. Per-pair magnitude is
        # well-defined regardless of whether the aggregate ρ is defined.
        for a_i in range(len(paired)):
            for b_i in range(a_i + 1, len(paired)):
                sec_a, val_a = paired[a_i]
                sec_b, val_b = paired[b_i]
                if sec_a.energy == sec_b.energy:
                    continue  # no "higher" — not an inversion either way
                if sec_a.energy > sec_b.energy:
                    higher, h_val, lower, l_val = sec_a, val_a, sec_b, val_b
                else:
                    higher, h_val, lower, l_val = sec_b, val_b, sec_a, val_a
                measured_delta = h_val - l_val
                # An inversion: higher-declared renders LOWER. The surfacing
                # floor (DR-5) drops sub-threshold magnitudes as DSP noise; the
                # default 0.0 surfaces every inversion (abs > 0.0 keeps all
                # genuine flips, drops only exact-zero non-flips).
                if measured_delta < 0.0 and abs(measured_delta) > surfacing_floor:
                    inversions.append(EnergyInversion(
                        higher_energy_start_beat=higher.start_beat,
                        higher_energy_section=higher.name,
                        lower_energy_start_beat=lower.start_beat,
                        lower_energy_section=lower.name,
                        declared_energy_delta=higher.energy - lower.energy,
                        correlate=correlate,
                        measured_higher=h_val,
                        measured_lower=l_val,
                        measured_delta=measured_delta,
                    ))

        # Spearman ρ over the finite-paired sections. A constant/tied measured
        # correlate makes spearmanr return statistic=nan (ConstantInputWarning) —
        # detect it and record None + a reason; NEVER put nan in correlate_rho.
        energies = [sec.energy for sec, _ in paired]
        values = [val for _, val in paired]
        # A constant/tied correlate emits ConstantInputWarning and returns
        # statistic=nan; that's the EXPECTED, HANDLED case (recorded as None
        # below), so silence the warning rather than letting it leak as noise.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConstantInputWarning)
            rho = float(spearmanr(energies, values).statistic)
        if math.isnan(rho):
            correlate_rho[correlate] = None
            skipped.append(
                f"{correlate} ρ undefined: measured values tied/constant across "
                f"sections (Spearman undefined)"
            )
        else:
            correlate_rho[correlate] = rho

    return EnergyRealization(
        correlate_rho=correlate_rho,
        inversions=inversions,
        sections_ranked=sections_ranked,
        skipped=skipped,
    )


__all__ = ["realize_energy", "LOUDNESS", "ONSET_DENSITY", "SPECTRAL_CENTROID"]
