"""hallucinote.recurrence — the cross-instrument / arrangement-level recurrence READ.

The read side of the RECURRENCE/FORM dimension (the authoring side ships via
``Arrangement.motif`` / ``vary`` + ``generators.variations``). A pure SYMBOLIC,
render-free lens — sibling to ``theory.lint`` (harmony), ``melody.lens`` (line), and
``performance.lens`` (feel) — that, given an in-memory ``Arrangement``, reports which
registered motifs recur where and as which variation — the product of a pitch map
(transpose / invert) with a time map (identity / augment·diminish / retrograde /
fragment), so a composed recall like ``transpose +12 ∘ diminish ×2`` is recovered and
named by the same search — plus a motivic-economy summary. Info-only, never a verdict (ruler-not-stamp).

See ``.prawduct/artifacts/arrangement-model.md`` and the ARR-9K4T design.
"""
from __future__ import annotations

from hallucinote.recurrence.economy import MotivicEconomy, summarize_economy
from hallucinote.recurrence.lens import (
    MotifRecall,
    RecurrenceFinding,
    RecurrenceReport,
    SectionRecurrence,
    SectionRecurrenceInput,
    analyze_arrangement,
    analyze_recurrence,
)
from hallucinote.recurrence.match import MatchResult, match_motif_in_window

__all__ = [
    # lens (read side)
    "RecurrenceFinding",
    "MotifRecall",
    "SectionRecurrence",
    "RecurrenceReport",
    "SectionRecurrenceInput",
    "analyze_recurrence",
    "analyze_arrangement",
    # economy
    "MotivicEconomy",
    "summarize_economy",
    # matcher
    "MatchResult",
    "match_motif_in_window",
]
