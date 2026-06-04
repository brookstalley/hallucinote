"""hallucinote.melody.profile — the authoring side (phase 2b).

The read-side lens (``lens`` + ``contour`` + ``intervals`` + ``harmony_fit``)
answers *"what does this line measure?"* as genre-general substrate facts. This
module is its authoring counterpart: it lets a composer **declare** what a line is
*trying to be* — its contour intent, range, step↔leap appetite, harmonic freedom,
repetition appetite — so the lens can answer the SECOND question:
*"is the line doing what its declared profile intends?"* (melody-model.md §1, §4).

**Ruler, not stamp — and this is the decisive difference from ``PerformanceProfile``
(melody-model.md §2, design §1).** A :class:`PerformanceProfile` has an
``apply_profile()`` that *realizes* it — it computes micro-timing deviations and
writes them onto notes, which is legitimate because breathing is arithmetic, not a
musical idea. **The melodic profile has NO ``apply_*`` that writes pitches**: pitch
*is* the musical idea, inventing the line is the art (``feedback_great_art_not_
software``; research C9), so there is no ``melody()`` generator and no
``realize_melody(profile)``. The profile is **read-only declared intent the lens
grades AGAINST**, and every grading is a coaching QUESTION (``severity="info"``),
never a verdict the composer did not ask for.

**Why mirror ``PerformanceProfile`` exactly** (the proven precedent in
``performance/realization.py``): a frozen dataclass of declared intent + a ``name``
+ ``__post_init__`` validation + a ``to_dict()`` boundary for recording it in the
song's decision corpus. The intelligence is in the *declared choice* (the LLM picks
the profile / writes the line); the module carries only the literals + validation.

**Learn-back = declaring the profile in build.py** (design §0 Success / §1): once
the revealed intent is written down as a ``MelodicProfile``, the line grades as
matched and never re-flags. The declaration IS the learn-back — no separate
markdown-annotation surface this phase (``project_intent_home_rationalization``:
WHAT in build.py, WHY in markdown; a disposable DB annotation is a data-loss trap).

**Every field is optional** (``None``-default). A profile that declares nothing is
legal and produces zero gradings — the line reads as unconstrained substrate facts,
exactly the 2a behavior (graceful degradation, never forcing a part to declare).

Pure stdlib — matching the rest of ``melody`` + ``theory`` + ``performance``.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Literal

#: low ↔ moderate ↔ high — a coarse appetite band, NOT a numeric target. The
#: appetite→fraction grading edges live in ``lens`` as named (PENDING by-ear)
#: constants; the profile only declares the band.
Appetite = Literal["low", "moderate", "high"]

#: The declared contour SHAPE intent. Every member except ``"free"`` is
#: byte-identical to the read-side ``contour.ContourShape`` value-space MINUS
#: ``"insufficient-data"`` (a measurement-only "too few notes" state, never an
#: *intent*) so a declared ``contour_intent`` compares directly to a measured
#: ``contour_shape`` by string equality — no translation table (design §3, W2).
#: ``"level"`` (NOT ``"static"``) matches the measured shape exactly. ``"free"``
#: is intent-only — an explicit "no declared shape" that suppresses the contour
#: grading entirely (you cannot declare an intent to be shapeless against).
ContourIntent = Literal[
    "arch", "ascending", "descending", "valley", "level", "free"
]

#: The exact v1 field set, pinned so the W3 deferral of ``phrase_arch`` /
#: ``motif_dna`` (no guaranteed read side this plan) is semantic, not accidental.
#: A regression test asserts ``MelodicProfile`` has EXACTLY these and NOT the
#: deferred two (design §3; learnings "pin the NEW convention with a test").
V1_FIELDS = (
    "name",
    "idiom",
    "contour_intent",
    "apex_position",
    "ambitus_min",
    "ambitus_max",
    "step_appetite",
    "harmonic_freedom",
    "repetition_appetite",
)

_VALID_APPETITES = ("low", "moderate", "high")
_VALID_CONTOUR_INTENTS = (
    "arch", "ascending", "descending", "valley", "level", "free"
)


@dataclass(frozen=True)
class MelodicProfile:
    """A declared melodic profile — the ruler's input (melody-model.md §4).

    The composer/LLM declares *what* the line intends; the lens reads each declared
    intent and reports the line's measured value AGAINST it (design §4). There is no
    ``apply_*`` — pitch is the musical idea, so the profile never produces a line.

    Fields (all optional; an all-``None`` profile is legal and grades nothing):
      ``name`` — a reusable declared-intent label (``"reggae-hook"``). Names are how
        profiles become reusable, declared intent rather than raw numbers.
      ``idiom`` — a named reference point (free text): ``"singable-pop-hook"``,
        ``"bebop-head"``, ``"modal-chant"``, ``"riff-motif"``, ``"through-composed"``
        — sets defaults a human reads; never a computed key.
      ``contour_intent`` — an arch / terraced-descent / level / free PRIOR (§3.7
        continuous, never a discrete-type target). ``None`` = unstated.
      ``apex_position`` — 0..1 where the climax is intended (early / golden / final
        lift).
      ``ambitus_min`` / ``ambitus_max`` — the intended range band in semitones;
        singability is genre-relative, never a universal ceiling.
      ``step_appetite`` — low | moderate | high — proximity vs leap; a bebop head
        (low step appetite) and a hymn (high) are both valid.
      ``harmonic_freedom`` — low (chord-tone-locked) ↔ high (freely chromatic) — the
        rate harmony-fit is graded AGAINST (§5); flattens in rock/modal idioms.
      ``repetition_appetite`` — low (through-composed) ↔ high (cell-driven hook) —
        the rate the within-line motivic-economy reading is graded against (C4).

    DEFERRED OUT OF v1 (design §3, W3): ``phrase_arch`` and ``motif_dna`` — neither
    has a guaranteed read side in this plan (``phrase_arch``'s is the OPTIONAL Chunk
    5; ``motif_dna`` is read by no chunk), so landing them would be an author-side-
    without-read-side BOTH-SIDES violation + the speculative catalog this layer
    forbids. They enter the profile when their read side ships.
    """

    name: str
    idiom: str | None = None
    contour_intent: ContourIntent | None = None
    apex_position: float | None = None
    ambitus_min: int | None = None
    ambitus_max: int | None = None
    step_appetite: Appetite | None = None
    harmonic_freedom: Appetite | None = None
    repetition_appetite: Appetite | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("MelodicProfile.name must be non-empty")
        if self.contour_intent is not None and self.contour_intent not in _VALID_CONTOUR_INTENTS:
            raise ValueError(
                f"MelodicProfile.contour_intent={self.contour_intent!r} must be one "
                f"of {_VALID_CONTOUR_INTENTS} or None"
            )
        for field_name in ("step_appetite", "harmonic_freedom", "repetition_appetite"):
            value = getattr(self, field_name)
            if value is not None and value not in _VALID_APPETITES:
                raise ValueError(
                    f"MelodicProfile.{field_name}={value!r} must be one of "
                    f"{_VALID_APPETITES} or None"
                )
        if self.apex_position is not None and not (0.0 <= self.apex_position <= 1.0):
            raise ValueError(
                f"MelodicProfile.apex_position must be in [0, 1]; got {self.apex_position}"
            )
        if (
            self.ambitus_min is not None
            and self.ambitus_max is not None
            and self.ambitus_min > self.ambitus_max
        ):
            raise ValueError(
                f"MelodicProfile.ambitus_min ({self.ambitus_min}) must be <= "
                f"ambitus_max ({self.ambitus_max})"
            )
        for field_name in ("ambitus_min", "ambitus_max"):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(
                    f"MelodicProfile.{field_name} must be >= 0; got {value}"
                )

    def to_dict(self) -> dict[str, Any]:
        """The declared profile as a plain dict — the boundary for recording it in
        the song's decision/annotation corpus (the *why* lives in markdown)."""
        return {f.name: getattr(self, f.name) for f in fields(self)}
