"""hallucinote.arrangement — the song-structure layer (rulers, not stamps).

Carries arrangement BOOKKEEPING — section identity, ordering, sequential
bar-range assignment, layer presence, and clip / placement / section / cue
emission — so the composer spends attention on the music, not the plumbing.
See `.prawduct/artifacts/arrangement-model.md` for the design foundation.

Primitives:

  ``Motif``          a named, referenceable bundle of notes (canonical, 0-based)
  ``Arrangement``    an ordered list of sections, each a ``{track: notes}`` map
  ``PlacedSection``  a section after sequential bar-range assignment (plan output)
  ``vary()``         derive a section instance's layers from a base blueprint +
                     a delta (strip / add / transform) — cumulative development

The composer authors **layers** (note lists, from motifs / generators / by hand,
0-based within the section). The ``Arrangement`` assigns bars, creates one clip
per ``(section, track)`` layer, places it in the arrangement, and authors the
sections + cue points — all through the standard mutators.

**Planning is split from materialization.** ``plan()`` is pure (bar assignment,
testable without a DB); ``materialize()`` walks the plan through mutators. This
keeps the bookkeeping verifiable in isolation and the DB emission thin.

What this module deliberately does NOT do: decide any music. It never generates
notes, never picks a variation, never smooths a transition. Layers come from the
composer; ``vary``'s deltas come from the composer. Ruler, not stamp
(`feedback_great_art_not_software`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from hallucinote.db import mutations as M

NoteDict = dict[str, Any]
Layers = dict[str, list[NoteDict]]


def _copy_notes(notes: Sequence[NoteDict]) -> list[NoteDict]:
    """Deep-enough copy: new list, new note dicts, new ``tags`` list per note.

    Matches `generators.variations._copy` so copy depth is uniform across the
    arrangement layer — a caller mutating a note dict (or its tags) in place
    after authoring can never leak into stored motif / section / vary state.
    """
    return [dict(n, tags=list(n.get("tags", []))) for n in notes]


@dataclass
class Motif:
    """A named, referenceable musical atom — notes at canonical 0-based position.

    Registered on an ``Arrangement`` so later sections can quote or develop it
    (the recapitulation/reference primitive). Apply the ``generators.variations``
    ops to transform a motif when placing it; those ops copy, so the registered
    motif is never mutated.
    """

    name: str
    notes: list[NoteDict]


@dataclass(frozen=True)
class PlacedSection:
    """A section after sequential bar placement — the pure output of ``plan()``."""

    name: str
    function: str
    start_bar: int
    end_bar: int
    energy: float
    genre: str | None
    layers: Layers


@dataclass
class _SectionSpec:
    name: str
    function: str
    bars: int
    energy: float
    genre: str | None
    layers: Layers


class Arrangement:
    """An ordered sequence of sections that materializes into a song.

    Sections are appended in playback order; ``plan()`` assigns each its bar
    range sequentially. A section's ``layers`` map ``track name -> notes``
    (0-based within the section); a track absent from the map simply doesn't
    play that section (e.g. organ tacet in the metal sections).
    """

    def __init__(self, *, beats_per_bar: float = 4.0) -> None:
        self._specs: list[_SectionSpec] = []
        self.motifs: dict[str, Motif] = {}
        self.beats_per_bar = beats_per_bar

    # -- motifs (referenceable atoms) --------------------------------------

    def motif(self, name: str, notes: Sequence[NoteDict]) -> Motif:
        """Register a referenceable motif (a defensive copy of ``notes``)."""
        if name in self.motifs:
            raise ValueError(f"motif {name!r} already registered")
        m = Motif(name, _copy_notes(notes))
        self.motifs[name] = m
        return m

    def get_motif(self, name: str) -> Motif:
        if name not in self.motifs:
            raise KeyError(
                f"motif {name!r} not registered; known: {sorted(self.motifs)}"
            )
        return self.motifs[name]

    # -- sections ----------------------------------------------------------

    def section(
        self,
        name: str,
        *,
        function: str,
        bars: int,
        layers: Mapping[str, Sequence[NoteDict]],
        energy: float = 0.5,
        genre: str | None = None,
    ) -> "Arrangement":
        """Append a section. Returns self for chaining.

        ``function`` is its structural role (intro / verse / prechorus / chorus
        / bridge / break / outro). ``energy`` is the authored intensity intent
        (0..1); direction across transitions is implied by the sequence of
        energies and is never auto-smoothed. ``layers`` is ``track -> notes``.
        """
        if bars <= 0:
            raise ValueError(f"section {name!r}: bars must be > 0, got {bars}")
        self._specs.append(
            _SectionSpec(
                name=name,
                function=function,
                bars=bars,
                energy=energy,
                genre=genre,
                layers={t: _copy_notes(ns) for t, ns in layers.items()},
            )
        )
        return self

    # -- planning (pure) ---------------------------------------------------

    def plan(self, *, start_bar: int = 1) -> list[PlacedSection]:
        """Assign each section its bar range sequentially. Pure — no DB."""
        placed: list[PlacedSection] = []
        bar = start_bar
        for s in self._specs:
            placed.append(
                PlacedSection(
                    name=s.name,
                    function=s.function,
                    start_bar=bar,
                    end_bar=bar + s.bars,
                    energy=s.energy,
                    genre=s.genre,
                    layers=s.layers,
                )
            )
            bar += s.bars
        return placed

    @property
    def total_bars(self) -> int:
        return sum(s.bars for s in self._specs)

    @property
    def energy_curve(self) -> list[tuple[str, float]]:
        """The authored (section, energy) sequence — the curve a review lens
        reads derivatives off (never stored as velocity/accel; computed)."""
        return [(s.name, s.energy) for s in self._specs]

    # -- materialization (mutators) ----------------------------------------

    def materialize(
        self,
        conn,
        *,
        song_id: str,
        tracks: Mapping[str, str],
        start_bar: int = 1,
        author_sections: bool = True,
        author_cues: bool = True,
        actor: str = "build",
    ) -> dict[str, int]:
        """Emit the planned arrangement into the DB through the mutators.

        ``tracks`` maps track name -> track id. Each section creates one clip
        per layer (slot = section index + 1), fills its notes, places it in the
        arrangement at the section's bar range, and (optionally) authors the
        section boundary + a cue at its start. Returns created-row counts.

        A layer naming a track absent from ``tracks`` raises ``KeyError`` — fail
        loud rather than silently drop a part.
        """
        placed = self.plan(start_bar=start_bar)
        created = {"clips": 0, "notes": 0, "placements": 0, "sections": 0, "cues": 0}
        for idx, sec in enumerate(placed):
            slot = idx + 1
            length_beats = (sec.end_bar - sec.start_bar) * self.beats_per_bar

            if author_sections:
                M.create_section(
                    conn, song_id=song_id, name=sec.name,
                    start_bar=float(sec.start_bar), end_bar=float(sec.end_bar),
                    actor=actor, reason=f"{sec.name} section",
                )
                created["sections"] += 1
            if author_cues:
                M.add_cue_point(
                    conn, song_id=song_id, position_bar=float(sec.start_bar),
                    name=sec.name, actor=actor, reason=f"{sec.name} cue",
                )
                created["cues"] += 1

            for track_name, notes in sec.layers.items():
                if track_name not in tracks:
                    raise KeyError(
                        f"section {sec.name!r} has a layer on unknown track "
                        f"{track_name!r}; known tracks: {sorted(tracks)}"
                    )
                clip_id = M.create_clip(
                    conn, track_id=tracks[track_name], slot=slot,
                    name=f"{sec.name} · {track_name}",
                    length_beats=length_beats, section_role=sec.name,
                    actor=actor, reason=f"{sec.name} {track_name} layer",
                )
                M.replace_clip_notes(
                    conn, clip_id=clip_id, notes=list(notes),
                    actor=actor, reason="compose",
                )
                M.add_arrangement_clip(
                    conn, song_id=song_id, track_id=tracks[track_name],
                    clip_id=clip_id, start_bar=float(sec.start_bar),
                    end_bar=float(sec.end_bar),
                    actor=actor, reason=f"{sec.name} {track_name} placement",
                )
                created["clips"] += 1
                created["notes"] += len(notes)
                created["placements"] += 1
        return created


# --------------------------------------------------------------------------
# Cumulative development — deltas on a recurring section (a ruler)
# --------------------------------------------------------------------------


def vary(
    base: Mapping[str, Sequence[NoteDict]],
    *,
    strip: Sequence[str] = (),
    add: Mapping[str, Sequence[NoteDict]] | None = None,
    transform: Mapping[str, Callable[[list[NoteDict]], list[NoteDict]]] | None = None,
) -> Layers:
    """Derive a section instance's layers from a ``base`` blueprint + a delta.

    This is how verse 1 / 2 / 3 stay the same section yet differ — per-iteration
    deltas, not independent clips. Application order is **strip -> transform ->
    add** (so a transform sees surviving layers, and an add can override).

      - ``strip``: track names to remove (subtraction matters as much as addition).
      - ``transform``: ``{track: fn}`` where ``fn(notes) -> notes`` (use the
        ``generators.variations`` ops, or any composer-authored function).
      - ``add``: ``{track: notes}`` to add or replace (reorchestration, a new
        counter-melody layer, a layer entering as the arrangement builds).

    Pure: ``base`` is never mutated; a NEW layers dict is returned. The composer
    decides the delta; ``vary`` only applies the set operations.
    """
    out: Layers = {t: _copy_notes(ns) for t, ns in base.items()}
    for t in strip:
        out.pop(t, None)
    if transform:
        for t, fn in transform.items():
            if t in out:
                out[t] = fn(out[t])
    if add:
        for t, ns in add.items():
            out[t] = _copy_notes(ns)
    return out
