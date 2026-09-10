"""hallucinote.recurrence.lens — the build-time symbolic recurrence/recap lens.

The cross-instrument, arrangement-level analog of ``theory.lint`` (harmony),
``melody.lens`` (line), and ``performance.lens`` (feel): a pure SYMBOLIC ruler that,
given an in-memory ``Arrangement``, reports **which registered motifs recur where,
and as which variation** (an ``exact`` quote, a recovered single op, any composition
of a pitch map with a time map, or an honest ``derived (<op>, <coverage>)`` partial),
plus a **motivic-economy summary**. It runs
on ``NoteDict``s at BUILD time — no audio render, no Live — and it REPORTS; it never
edits a note and never tells the composer to recall a motif. See
``.prawduct/artifacts/arrangement-model.md`` and the ARR-9K4T design.

Load-bearing framing (design.md §1 ruler-not-stamp; research.md §2 Temperley
style-relativity): there is no universal "good recurrence." Authored recapitulation
is not an error and motivic economy is style-relative (a through-composed piece is
*legitimately* less economical than a minimalist one). So **every finding is
``severity="info"``**, ``ok`` is always True, ``blocking`` always empty — kept for
contract parity with the sibling lenses. The ONLY finding emitted is the
registered-but-never-recalled coaching QUESTION (economy.py).

Two contracts diverge deliberately from the melody lens (W2): the recurrence read
scans **ALL layers** (the polyrhythm recall lives on ``04 Organ``, not the lead — a
layer filter would silently drop it), and matching is **CONTAINMENT** (M ⊆ a cell
window — the climax organ layer is a superset with extra ``FUSION_CHORD`` hits, yet
still reads ``exact``).

A known, honestly-reported blind spot: only *registered* motifs are read. A
recurring free function (e.g. sun-zone-done's ``_hybrid_hook``, never
``arr.motif(...)``) is invisible — register it to track its recall (an authoring
choice). The CLI states this plainly.

What is worth registering (DOC-7K3M motif-sizing guidance): register motifs with
enough length + contour to be *distinctive*. The matcher recovers a transform GROUP
(the product of a pitch map — transpose / invert — with a time map — identity /
augment·diminish / retrograde / fragment — so every composition of the two is
recovered, not a hand-picked subset), so a too-short or too-plain motif matches almost any layer and
inflates the recall count without musical meaning — a 2-note fragment, or a
zero-interval pedal/drone/ostinato (a single repeated pitch — which the matcher
*does* now recall, REC-4Z8Q), recurs trivially nearly everywhere. Prefer a motif of
~3+ notes with a non-trivial interval shape; treat a recall report dominated by such
degenerate motifs as a registration smell, not a finding about the music.

Output mirrors the sibling lenses (frozen dataclasses, a local ``Severity``
Literal, an explicit ``to_dict()`` boundary), defined locally so the recurrence
layer never depends on the higher ``audio`` layer. Pure stdlib — no numpy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Mapping, Sequence

if TYPE_CHECKING:  # avoid a runtime cycle — the adapter lives on the arrangement
    from hallucinote.arrangement import Arrangement, Motif

from hallucinote.recurrence.economy import MotivicEconomy, economy_finding, summarize_economy
from hallucinote.recurrence.match import match_all_in_layer

NoteDict = dict[str, Any]

Severity = Literal["info", "warning", "blocking"]
_VALID_SEVERITIES = ("info", "warning", "blocking")


@dataclass(frozen=True)
class RecurrenceFinding:
    """One recurrence observation, intent-keyed by ``kind`` + ``severity``. Every
    finding is ``info`` — a coaching question, never a verdict (design.md §5)."""

    kind: str            # "registered-never-recalled"
    severity: Severity
    section: str | None
    detail: str
    metric: float | None = None
    motif: str | None = None

    def __post_init__(self) -> None:
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"severity={self.severity!r} must be one of {_VALID_SEVERITIES}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "section": self.section,
            "detail": self.detail,
            "metric": self.metric,
            "motif": self.motif,
        }


@dataclass(frozen=True)
class MotifRecall:
    """One detected recall: motif ``motif`` recurred in this section on ``layer`` as
    ``variation`` at ``cell_offset_beats`` within the section.

    ``coverage`` is the fraction of the motif's notes accounted for (1.0 for a clean
    whole-motif op; <1.0 for a fragment or an honest ``derived (<op>, <coverage>)``
    partial). ``is_home`` marks the motif's FIRST (home) section — registered material
    first sounding is not a recall, so the economy summary excludes home occurrences.

    ``duration_match`` is False when the recall landed on ``(relative-onset, pitch)``
    but its durations were freely re-sung — the ``variation`` label then carries a
    ``(durations free)`` qualifier. The common expressive-recapitulation shape (an
    arrival statement compresses the rhythm while the notes keep their sung lengths)
    is REPORTED with the relaxation visible, never dropped as no recall."""

    motif: str
    section: str
    layer: str
    variation: str
    cell_offset_beats: float
    coverage: float
    is_home: bool = False
    duration_match: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "motif": self.motif,
            "section": self.section,
            "layer": self.layer,
            "variation": self.variation,
            "cell_offset_beats": self.cell_offset_beats,
            "coverage": self.coverage,
            "is_home": self.is_home,
            "duration_match": self.duration_match,
        }


@dataclass(frozen=True)
class SectionRecurrence:
    """A section's detected recalls (one per motif × layer where a recall was found)."""

    section: str
    recalls: tuple[MotifRecall, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "recalls": [r.to_dict() for r in self.recalls],
        }


@dataclass(frozen=True)
class RecurrenceReport:
    """The whole-song symbolic-recurrence report."""

    song_slug: str
    sections: tuple[SectionRecurrence, ...]
    economy: MotivicEconomy
    findings: tuple[RecurrenceFinding, ...]  # song-level rollup (all findings)

    @property
    def recalls(self) -> tuple[MotifRecall, ...]:
        """Every detected recall, flattened across sections (home + later)."""
        return tuple(r for s in self.sections for r in s.recalls)

    @property
    def blocking(self) -> tuple[RecurrenceFinding, ...]:
        return tuple(f for f in self.findings if f.severity == "blocking")

    @property
    def ok(self) -> bool:
        """No BLOCKING findings. This lens emits only ``info`` findings (authored
        recurrence is not error), so ``ok`` is always True — kept for contract parity
        with ``theory.lint`` / ``melody.lens`` / ``performance.lens``."""
        return not self.blocking

    def to_dict(self) -> dict[str, Any]:
        return {
            "song_slug": self.song_slug,
            "sections": [s.to_dict() for s in self.sections],
            "economy": self.economy.to_dict(),
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass(frozen=True)
class SectionRecurrenceInput:
    """Recurrence-lens input for one section — decoupled from ``PlacedSection`` so
    the lens is unit-testable without the arrangement layer (mirrors
    ``theory.lint.SectionLint`` / ``melody.lens.SectionMelody`` /
    ``performance.lens.SectionPerf``; the
    ``arrangement.Arrangement.section_recurrence_inputs`` adapter bridges the two).

    There is deliberately NO layer filter (W2 — unlike ``SectionMelody.melody_layers``):
    cross-instrument recurrence scans EVERY layer, because a motif can recur on any
    instrument (the polyrhythm recall is on ``04 Organ``, not the lead). ``layers``
    maps ``track name -> notes`` (0-based within the section). ``start_beat`` is the
    section's absolute start (so a section-relative recall offset is reportable;
    matching itself is placement-invariant)."""

    name: str
    length_beats: float
    layers: Mapping[str, Sequence[NoteDict]]
    start_beat: float = 0.0


def _registry_pairs(motifs: "Mapping[str, Motif]") -> list[tuple[str, list[NoteDict]]]:
    """The (name, notes) query set, registration order preserved (so the FIRST
    section a motif appears in is its home, used for the economy home-exclusion)."""
    return [(name, list(m.notes)) for name, m in motifs.items()]


def analyze_recurrence(
    sections: Sequence[SectionRecurrenceInput],
    motifs: "Mapping[str, Motif]",
    *,
    song_slug: str,
) -> RecurrenceReport:
    """Analyze which registered motifs recur where, per (motif × section × layer).

    Pure symbolic measurement: for each section, each layer, each registered motif,
    run the directed transform-and-match (``match.match_all_in_layer``) over the
    whole layer (containment, so a tiled recall amid extra notes still reads). The
    motif's FIRST section of appearance is its home (``is_home=True``) — registered
    material first sounding is not a recall; the economy summary counts only later
    recalls. Render-free and DB-decoupled: feed it
    ``arrangement.Arrangement.section_recurrence_inputs()`` at build time, or
    synthetic ``SectionRecurrenceInput`` inputs in a test."""
    pairs = _registry_pairs(motifs)
    seen_home: set[str] = set()
    section_results: list[SectionRecurrence] = []

    for sec in sections:
        recalls: list[MotifRecall] = []
        for motif_name, motif_notes in pairs:
            # Scan EVERY layer (W2 — no layer filter; the polyrhythm recall lives on
            # `04 Organ`, not the lead). For each layer, collect EVERY distinct-
            # variation recall the matcher finds (CONTAINMENT — the recall is read amid
            # tiling + extra non-motif notes). A layer that quotes M as both a bare
            # `fragment` (the reggae-cell answer) AND a `diminish∘fragment` (the trade-
            # cell dialogue) reports BOTH — neither silently dropped (N1; the
            # integration-trade signal). The motif's FIRST appearing section is its
            # home; later occurrences are recalls (the economy summary counts only
            # those).
            found_this_motif = False
            for layer_name in sec.layers:
                notes = sec.layers[layer_name]
                for res in match_all_in_layer(motif_notes, notes):
                    found_this_motif = True
                    recalls.append(MotifRecall(
                        motif=motif_name,
                        section=sec.name,
                        layer=layer_name,
                        variation=res.variation,
                        cell_offset_beats=sec.start_beat + res.cell_offset_beats,
                        coverage=res.coverage,
                        is_home=motif_name not in seen_home,
                        duration_match=res.duration_match,
                    ))
            if found_this_motif:
                seen_home.add(motif_name)
        section_results.append(
            SectionRecurrence(section=sec.name, recalls=tuple(recalls)))

    all_recalls = tuple(r for s in section_results for r in s.recalls)
    registered = [name for name, _ in pairs]
    motif_note_counts = {name: len(notes) for name, notes in pairs}
    economy = summarize_economy(registered, all_recalls, motif_note_counts)
    findings = tuple(economy_finding(registered, all_recalls))
    return RecurrenceReport(
        song_slug=song_slug,
        sections=tuple(section_results),
        economy=economy,
        findings=findings,
    )


def analyze_arrangement(arr: "Arrangement", *, song_slug: str) -> RecurrenceReport:
    """Run the recurrence lens over an in-memory ``Arrangement`` — the build-time
    entry point a song's ``recurrence_report()`` calls (and
    ``tools/recurrence_lens.py`` surfaces to ``/compose-review``).

    The motif registry + per-section layers are authored in ``build.py`` (the
    in-memory ``Arrangement``), not persisted to the DB, so the lens runs build-time
    over the arrangement, not over a DB read. Thin wrapper over
    ``arr.section_recurrence_inputs()`` -> ``analyze_recurrence()``; kept HERE (not
    on ``arrangement.py``) so the recurrence layer never depends on the arrangement
    layer at runtime — the adapter lives on the arrangement, the lens stays a leaf.

    **Takes NO layer filter (W2):** unlike ``melody.lens.analyze_arrangement``'s
    ``melody_layers``, this scans every layer — cross-instrument recurrence is the
    whole point, and the polyrhythm recall lives on ``04 Organ``, not the lead."""
    return analyze_recurrence(
        arr.section_recurrence_inputs(),
        arr.motifs,
        song_slug=song_slug,
    )
