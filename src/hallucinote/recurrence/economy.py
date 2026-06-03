"""hallucinote.recurrence.economy — the motivic-economy summary (a FACT, never a verdict).

The description-length-style economy read off the already-known motif set —
research.md §2 (Meredith COSIATEC ⟨P, V⟩ with P GIVEN, so the discovery half is
skipped). Three reported facts:

  * **cell-set size** — distinct registered motifs that recur at least once BEYOND
    their home section.
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

    ``registered_motifs`` is the size of the query set; ``recurring_motifs`` the
    cell-set size (distinct motifs recalled beyond home); ``recall_coverage`` the
    fraction; ``recalled_note_mass`` the total note count across NON-home recalls
    (the realized material the dictionary explains); ``library_note_mass`` the
    motif-library note count; ``occurrence_records`` the count of non-home recalls
    (each a ⟨placement, variation⟩ record); ``compression_ratio`` the proxy
    (recalled note-mass ÷ encoded size). ``never_recalled`` names the registered
    motifs that never recur (a fact worth surfacing, not a verdict)."""

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


def _recurring_motifs(recalls: Sequence["MotifRecall"]) -> set[str]:
    """The distinct motifs that recur BEYOND their home section (``is_home`` False)."""
    return {r.motif for r in recalls if not r.is_home}


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
    ⟨placement, variation⟩ record per non-home recall). A high ratio = a tight
    cell-set reused widely; a low one = scattered material. Reported, never judged."""
    n_registered = len(registered)
    recurring = _recurring_motifs(recalls)
    n_recurring = len(recurring)
    non_home = [r for r in recalls if not r.is_home]
    # Realized recalled note-mass: each non-home recall realizes its motif's notes
    # scaled by its coverage (a fragment realizes only its sub-window's share).
    recalled_note_mass = sum(
        round(motif_note_counts.get(r.motif, 0) * r.coverage) for r in non_home)
    occurrence_records = len(non_home)
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
    Returns one finding per never-recalled motif (or an empty list)."""
    from hallucinote.recurrence.lens import RecurrenceFinding

    recurring = _recurring_motifs(recalls)
    out: list[RecurrenceFinding] = []
    for name in registered:
        if name in recurring:
            continue
        out.append(RecurrenceFinding(
            kind="registered-never-recalled",
            severity="info",
            section=None,
            motif=name,
            detail=(
                f"motif {name!r} was registered but never recurs beyond its home "
                f"section — intended one-shot material, or a planned recall that "
                f"didn't land?"
            ),
        ))
    return out
