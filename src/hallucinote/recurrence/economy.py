"""hallucinote.recurrence.economy — the motivic-economy summary (a FACT, never a verdict).

The description-length-style economy read off the already-known motif set —
research.md §2 (Meredith COSIATEC ⟨P, V⟩ with P GIVEN, so the discovery half is
skipped). Three reported facts:

  * **cell-set size** — distinct registered motifs that recur at least once BEYOND
    their home section, counting only occurrences that clear the coverage floor.
  * **recall coverage** — ``recurring / registered``.
  * **compression-ratio proxy** — recalled note-mass ÷ (motif-library note-count +
    per-occurrence records), the ⟨P, V⟩ encoding shape: a small dictionary of
    motifs + placement/variation records reconstructs the recalled material; a high
    ratio means the song reuses a tight cell-set, a low one means it scatters.

Reported as FACTS. Per Temperley's style-relativity (research.md §2) high-vs-low
economy is NOT a universal good — a through-composed piece is *legitimately* less
economical than a minimalist one — so there is deliberately NO "be more economical"
finding (DR-3). The ONLY finding the economy path emits is the
registered-but-never-recalled coaching QUESTION (intended one-shot material, or a
planned recall that didn't land?), mirroring melody's ``static-line`` question.

Pure stdlib; ruler-not-stamp.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:  # avoid a runtime cycle — lens imports economy
    from hallucinote.recurrence.lens import MotifRecall, RecurrenceFinding


@dataclass(frozen=True)
class MotivicEconomy:
    """The description-length-style economy summary — facts, never a verdict.

    Every count here is over the occurrences that COUNT as recalls — beyond home AND
    at or above the coverage floor (``MotifRecall.counts_as_recall``). Sub-threshold
    partials are reported by the lens and excluded from every figure below.

    ``registered_motifs`` is the size of the query set; ``recurring_motifs`` the
    cell-set size (distinct motifs recalled beyond home, partials not counting);
    ``recall_coverage`` the fraction; ``recalled_note_mass`` the total note count
    across counted recalls (the realized material the dictionary explains);
    ``library_note_mass`` the motif-library note count; ``occurrence_records`` the
    count of counted recalls (each a ⟨placement, variation⟩ record);
    ``compression_ratio`` the proxy (recalled note-mass ÷ encoded size).

    ``never_recalled`` names the registered motifs OUTSIDE the cell-set — which is
    two populations, not one: motifs with no later occurrence at all, and motifs
    whose later occurrences are all sub-threshold partials. "Never recurs" is untrue
    of the second, so a reader that prints this list must split it (the CLI render
    does) or word it as "outside the cell-set" — see ``economy_finding``, which
    already says which case each motif is."""

    registered_motifs: int
    recurring_motifs: int
    recall_coverage: float
    recalled_note_mass: int
    library_note_mass: int
    occurrence_records: int
    compression_ratio: float
    never_recalled: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "registered_motifs": self.registered_motifs,
            "recurring_motifs": self.recurring_motifs,
            "recall_coverage": self.recall_coverage,
            "recalled_note_mass": self.recalled_note_mass,
            "library_note_mass": self.library_note_mass,
            "occurrence_records": self.occurrence_records,
            "compression_ratio": self.compression_ratio,
            "never_recalled": list(self.never_recalled),
        }


def _counted(recalls: Sequence["MotifRecall"]) -> list["MotifRecall"]:
    """The occurrences that COUNT as recalls: beyond their home section, and at or
    above the analysis's coverage floor.

    A sub-threshold occurrence (``partial``) is reported by the lens on purpose but
    is not evidence that the motif recurred — counting one inflates every figure
    here, and, worse, makes a motif whose only later occurrences are half-matched
    fragments read as recurring, which empties ``never_recalled`` and silences the
    single coaching question this module may emit. See
    ``lens.DEFAULT_MIN_RECALL_COVERAGE``. The predicate itself lives on
    ``MotifRecall.counts_as_recall`` — this reads it rather than restating it, so
    economy and the render cannot drift apart on what a recall is."""
    return [r for r in recalls if r.counts_as_recall]


def _recurring_motifs(recalls: Sequence["MotifRecall"]) -> set[str]:
    """The distinct motifs that recur BEYOND their home section, counting only
    occurrences at or above the coverage floor."""
    return {r.motif for r in _counted(recalls)}


def summarize_economy(
    registered: Sequence[str],
    recalls: Sequence["MotifRecall"],
    motif_note_counts: Mapping[str, int],
) -> MotivicEconomy:
    """Compute the economy summary off the registered motif set + the detected
    recalls. ``motif_note_counts`` maps each registered motif to its canonical note
    count (the ⟨P⟩ library: one stored copy per motif). All figures are FACTS — the
    COSIATEC ⟨P, V⟩ shape with P given (research.md §2).

    The compression-ratio proxy = realized recalled note-mass ÷ (library note-mass +
    occurrence records): the recalled material's realized note count over the size
    of the encoding that reconstructs it (the motif library stored once + one
    ⟨placement, variation⟩ record per counted recall). A high ratio = a tight
    cell-set reused widely; a low one = scattered material. Reported, never judged.

    Every figure counts only the occurrences that clear the analysis's coverage
    floor (``MotifRecall.partial`` False). Sub-threshold partials are still reported
    by the lens; they are simply not evidence of recall — see ``_counted``."""
    n_registered = len(registered)
    recurring = _recurring_motifs(recalls)
    n_recurring = len(recurring)
    counted = _counted(recalls)
    # Realized recalled note-mass: each counted recall realizes its motif's notes
    # scaled by its coverage (a fragment realizes only its sub-window's share).
    recalled_note_mass = sum(
        round(motif_note_counts.get(r.motif, 0) * r.coverage) for r in counted)
    occurrence_records = len(counted)
    library_note_mass = sum(motif_note_counts.get(name, 0) for name in registered)
    encoded_size = library_note_mass + occurrence_records
    compression = (recalled_note_mass / encoded_size) if encoded_size > 0 else 0.0
    never = tuple(name for name in registered if name not in recurring)
    coverage = (n_recurring / n_registered) if n_registered > 0 else 0.0
    return MotivicEconomy(
        registered_motifs=n_registered,
        recurring_motifs=n_recurring,
        recall_coverage=coverage,
        recalled_note_mass=recalled_note_mass,
        library_note_mass=library_note_mass,
        occurrence_records=occurrence_records,
        compression_ratio=compression,
        never_recalled=never,
    )


def economy_finding(
    registered: Sequence[str],
    recalls: Sequence["MotifRecall"],
) -> list["RecurrenceFinding"]:
    """The ONE finding the economy path may emit: registered-but-never-recalled, as
    an INFO coaching QUESTION (intended one-shot, or a planned recall that didn't
    land?). NEVER a "be more economical" verdict (DR-3, Temperley style-relativity).
    Returns one finding per motif outside the cell-set (or an empty list).

    Two shapes share the one ``kind``: a motif with no later occurrence at all, and
    one whose later occurrences are all sub-threshold partials. The second says so
    and names the best coverage, because "never recurs" would be untrue of it."""
    from hallucinote.recurrence.lens import RecurrenceFinding

    recurring = _recurring_motifs(recalls)
    out: list[RecurrenceFinding] = []
    for name in registered:
        if name in recurring:
            continue
        # A motif can miss the cell-set two ways, and saying "never recurs" for the
        # second would be false: it DID sound again, just never fully enough to
        # call a recall. Naming the best partial turns a flat absence into the
        # actionable version of the same question.
        partial_coverages = [
            r.coverage for r in recalls
            if r.motif == name and not r.is_home and r.partial
        ]
        if partial_coverages:
            detail = (
                f"motif {name!r} recurs beyond its home section only as partials "
                f"(best coverage {max(partial_coverages):.0%}) — material that "
                f"quotes it in passing, or a planned recall that landed incomplete?"
            )
        else:
            detail = (
                f"motif {name!r} was registered but never recurs beyond its home "
                f"section — intended one-shot material, or a planned recall that "
                f"didn't land?"
            )
        out.append(RecurrenceFinding(
            kind="registered-never-recalled",
            severity="info",
            section=None,
            motif=name,
            detail=detail,
        ))
    return out
