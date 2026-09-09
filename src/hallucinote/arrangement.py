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

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from hallucinote.db import mutations as M
from hallucinote.melody.lens import SectionMelody
from hallucinote.melody.profile import MelodicProfile
from hallucinote.performance.lens import SectionPerf
from hallucinote.recurrence.lens import SectionRecurrenceInput
from hallucinote.theory.lint import SectionLint
from hallucinote.theory.model import Mode, Progression
from hallucinote.theory.model import mode as _resolve_mode
from hallucinote.theory.model import pitch_class as _resolve_pitch_class

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
    """A section after sequential bar placement — the pure output of ``plan()``.

    Carries the resolved harmonic axis alongside the energy axis: ``key_pc`` +
    ``mode`` (the section's tonal center / modal palette) and ``progression``
    (the authored chord timeline, already resolved — a per-section progression as
    authored, or the song-level plan sliced to this section's span, or ``None``
    for a section that declared no harmony). ``key_pc``/``mode`` are carried
    INDEPENDENTLY of ``progression`` so a modal/static section with no chord
    changes can still declare (and be linted against) a mode.
    """

    name: str
    function: str
    start_bar: int
    end_bar: int
    energy: float
    genre: str | None
    layers: Layers
    key_pc: int | None = None
    mode: Mode | None = None
    progression: Progression | None = None


@dataclass
class _SectionSpec:
    name: str
    function: str
    bars: int
    energy: float
    genre: str | None
    layers: Layers
    key: str | None = None
    mode: str | None = None
    progression: Progression | str | None = None  # a Progression, "inherit", or None


class Arrangement:
    """An ordered sequence of sections that materializes into a song.

    Sections are appended in playback order; ``plan()`` assigns each its bar
    range sequentially. A section's ``layers`` map ``track name -> notes``
    (0-based within the section); a track absent from the map simply doesn't
    play that section (e.g. organ tacet in the metal sections).

    **Single meter only.** Bar arithmetic here multiplies by ONE
    ``beats_per_bar`` for the whole arrangement. The DB, meanwhile, records a
    song's real ``time_signature_map`` and push converts bar positions through
    it, so for a song with a within-song meter change the two disagree at every
    position after the change: push's number gains the extra beats that every bar
    after the change adds. In a 4/4 song that turns 7/4 at bar 9, this class puts
    bar 13 at beat 48 and push puts it at 60. Push detects and reports the
    divergence when it materializes the arrangement, but cannot repair it.

    So: for a multi-meter song, do not rely on this class's bar accumulation
    past the first meter change. Author those placements directly (the
    ``add_arrangement_clip`` / ``create_section`` mutators take float bars and
    push resolves them through the map), or keep the song single-meter and
    carry the odd groupings as accent instead. Making this class meter-aware
    is tracked as ARR-4M3T.
    """

    def __init__(self, *, beats_per_bar: float = 4.0) -> None:
        self._specs: list[_SectionSpec] = []
        self.motifs: dict[str, Motif] = {}
        self.beats_per_bar = beats_per_bar
        self._harmonic_plan: Progression | None = None

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
        key: str | None = None,
        mode: str | None = None,
        progression: Progression | str | None = None,
    ) -> "Arrangement":
        """Append a section. Returns self for chaining.

        ``function`` is its structural role (intro / verse / prechorus / chorus
        / bridge / break / outro). ``energy`` is the authored intensity intent
        (0..1); direction across transitions is implied by the sequence of
        energies and is never auto-smoothed. ``layers`` is ``track -> notes``.

        Harmony (the co-equal axis, all optional — a section that declares none
        materializes exactly as before, the graceful degradation to the note
        floor): ``key`` (e.g. ``"E"``) + ``mode`` (e.g. ``"Dorian"``) declare the
        tonal center / modal palette; ``progression`` is the authored chord
        timeline — a :class:`~hallucinote.theory.model.Progression`, or the
        string ``"inherit"`` to slice this section's span out of a song-level
        :meth:`harmonic_plan`. ``key``/``mode`` default from the progression when
        present, and can be set independently for a modal section with no chord
        changes. The composer authors the harmony; the model only carries it.
        """
        if bars <= 0:
            raise ValueError(f"section {name!r}: bars must be > 0, got {bars}")
        if isinstance(progression, str) and progression != "inherit":
            raise ValueError(
                f"section {name!r}: progression string must be 'inherit', got "
                f"{progression!r}"
            )
        self._specs.append(
            _SectionSpec(
                name=name,
                function=function,
                bars=bars,
                energy=energy,
                genre=genre,
                key=key,
                mode=mode,
                progression=progression,
                layers={t: _copy_notes(ns) for t, ns in layers.items()},
            )
        )
        return self

    def harmonic_plan(self, progression: Progression) -> "Arrangement":
        """Register a SONG-LEVEL harmonic plan that sections slice into via
        ``progression="inherit"`` (the lead-sheet mental model: changes first,
        sections carve their span out). 0-based from the first section's
        downbeat. Per-section progressions remain the primary path; this is the
        opt-in alternative. Returns self for chaining."""
        self._harmonic_plan = progression
        return self

    # -- planning (pure) ---------------------------------------------------

    def plan(self, *, start_bar: int = 1) -> list[PlacedSection]:
        """Assign each section its bar range sequentially and resolve its
        harmony. Pure — no DB."""
        placed: list[PlacedSection] = []
        bar = start_bar
        for s in self._specs:
            section_len_beats = s.bars * self.beats_per_bar
            offset_beats = (bar - start_bar) * self.beats_per_bar
            prog = self._resolve_progression(s, offset_beats, section_len_beats)
            key_pc, mode_obj = self._resolve_key_mode(s, prog)
            placed.append(
                PlacedSection(
                    name=s.name,
                    function=s.function,
                    start_bar=bar,
                    end_bar=bar + s.bars,
                    energy=s.energy,
                    genre=s.genre,
                    layers=s.layers,
                    key_pc=key_pc,
                    mode=mode_obj,
                    progression=prog,
                )
            )
            bar += s.bars
        return placed

    def _resolve_progression(
        self, s: _SectionSpec, offset_beats: float, length_beats: float
    ) -> Progression | None:
        """Resolve a section's progression: a per-section Progression is stored
        as authored (0-based; its ``chord_at`` is cyclic so it tiles to the
        section); ``"inherit"`` slices the song-level plan to this section's span;
        ``None`` is no declared harmony."""
        p = s.progression
        if p is None:
            return None
        if p == "inherit":
            if self._harmonic_plan is None:
                raise ValueError(
                    f"section {s.name!r} uses progression='inherit' but no "
                    f"harmonic_plan() was registered on the arrangement"
                )
            return self._harmonic_plan.slice(offset_beats, length_beats)
        if isinstance(p, str):
            raise ValueError(
                f"section {s.name!r} has invalid progression {p!r} — the only "
                f"string form is 'inherit'"
            )
        return p

    @staticmethod
    def _resolve_key_mode(
        s: _SectionSpec, prog: Progression | None
    ) -> tuple[int | None, Mode | None]:
        """key/mode default from the progression but can be set independently
        (a modal section with no chord changes still declares a mode)."""
        key_pc = _resolve_pitch_class(s.key) if s.key else (
            prog.key_pc if prog else None)
        mode_obj = _resolve_mode(s.mode) if s.mode else (prog.mode if prog else None)
        return key_pc, mode_obj

    @property
    def total_bars(self) -> int:
        return sum(s.bars for s in self._specs)

    @property
    def energy_curve(self) -> list[tuple[str, float]]:
        """The authored (section, energy) sequence — the curve a review lens
        reads derivatives off (never stored as velocity/accel; computed)."""
        return [(s.name, s.energy) for s in self._specs]

    @property
    def harmonic_curve(self) -> list[tuple[str, int | None, str | None, int]]:
        """The resolved (section, key_pc, mode_name, distinct_chords) sequence —
        the harmonic axis's read-side view, parallel to ``energy_curve``. The
        key-area arc (does the recap land home?) and the harmonic-rhythm /
        ambition shape are read off this; never stored."""
        return [
            (p.name, p.key_pc, p.mode.name if p.mode else None,
             p.progression.distinct_chords if p.progression else 0)
            for p in self.plan()
        ]

    def section_lints(
        self, *, harmony_layers: Sequence[str] | None = None, start_bar: int = 1
    ) -> list[SectionLint]:
        """Adapt the planned sections into the harmonic-conformance lens inputs
        (the ``PlacedSection -> SectionLint`` bridge). ``harmony_layers`` names
        the pitched, harmony-bearing tracks (exclude drums) for the stasis check.
        Feed the result to ``theory.lint.lint_harmony``."""
        layers_tuple = tuple(harmony_layers) if harmony_layers is not None else None
        return [
            SectionLint(
                name=p.name,
                length_beats=(p.end_bar - p.start_bar) * self.beats_per_bar,
                progression=p.progression,
                layers=p.layers,
                harmony_layers=layers_tuple,
            )
            for p in self.plan(start_bar=start_bar)
        ]

    def section_perf_inputs(self, *, start_bar: int = 1) -> list[SectionPerf]:
        """Adapt the planned sections into the symbolic-performance-lens inputs
        (the ``PlacedSection -> SectionPerf`` bridge, parallel to
        ``section_lints``). Every layer is carried — unlike harmony, drums are
        primary timing carriers, so no track is excluded. Feed the result to
        ``performance.lens.analyze_performance``."""
        return [
            SectionPerf(
                name=p.name,
                length_beats=(p.end_bar - p.start_bar) * self.beats_per_bar,
                layers=p.layers,
            )
            for p in self.plan(start_bar=start_bar)
        ]

    def section_melody_inputs(
        self,
        *,
        melody_layers: Sequence[str] | None = None,
        start_bar: int = 1,
        profiles: Mapping[str, MelodicProfile] | None = None,
    ) -> list[SectionMelody]:
        """Adapt the planned sections into the symbolic-melody-lens inputs (the
        ``PlacedSection -> SectionMelody`` bridge, parallel to ``section_lints`` /
        ``section_perf_inputs``). ``melody_layers`` names the monophonic melodic
        lines (lead / vocal / riff) to analyze — exclude drums and chordal pads;
        ``None`` analyzes every layer. Carries the section's ``progression``
        (melody's pitch reads harmony) + ``beats_per_bar`` (the strong-beat read).

        ``profiles`` (phase 2b) is the song's declared ``{layer_name:
        MelodicProfile}`` map, carried onto every section so the lens grades each
        line against its declared intent (``None`` = the unchanged 2a path). The
        profile lives in build.py, never on the arrangement (Decision-Record 1) — so
        it rides through here as a passthrough, not a stored field. Feed the result
        to ``melody.lens.analyze_melody``."""
        layers_tuple = tuple(melody_layers) if melody_layers is not None else None
        return [
            SectionMelody(
                name=p.name,
                length_beats=(p.end_bar - p.start_bar) * self.beats_per_bar,
                layers=p.layers,
                progression=p.progression,
                melody_layers=layers_tuple,
                beats_per_bar=self.beats_per_bar,
                profiles=profiles,
            )
            for p in self.plan(start_bar=start_bar)
        ]

    def section_recurrence_inputs(
        self, *, start_bar: int = 1
    ) -> list[SectionRecurrenceInput]:
        """Adapt the planned sections into the symbolic-recurrence-lens inputs (the
        ``PlacedSection -> SectionRecurrenceInput`` bridge, parallel to
        ``section_lints`` / ``section_perf_inputs`` / ``section_melody_inputs``).

        **Takes NO layer filter (W2) — it scans EVERY layer of every section.** This
        is the deliberate divergence from ``section_melody_inputs(melody_layers=…)``:
        a *line* read is meaningless on chordal/drum layers, but cross-instrument
        recurrence is the whole point — a motif can recur on any instrument (the
        polyrhythm recall lives on ``04 Organ``, not the lead). Carries each
        section's absolute ``start_beat`` so a recall's section-relative offset is
        reportable. Feed the result + ``arr.motifs`` to
        ``recurrence.lens.analyze_recurrence`` (or use ``analyze_arrangement``)."""
        return [
            SectionRecurrenceInput(
                name=p.name,
                length_beats=(p.end_bar - p.start_bar) * self.beats_per_bar,
                layers=p.layers,
                start_beat=(p.start_bar - start_bar) * self.beats_per_bar,
            )
            for p in self.plan(start_bar=start_bar)
        ]

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
                    energy=sec.energy,
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
