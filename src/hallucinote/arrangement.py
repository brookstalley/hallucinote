"""hallucinote.arrangement — the song-structure layer (rulers, not stamps).

Carries arrangement BOOKKEEPING — section identity, ordering, sequential
bar-range assignment, the song's METER, layer presence, and clip / placement /
section / cue emission — so the composer spends attention on the music, not the
plumbing. See `.prawduct/artifacts/arrangement-model.md` for the design
foundation.

Bar positions resolve through `hallucinote.meter` — the same ruler
`sync.geometry` resolves push's positions through. There is exactly one bar
ruler in this tree, and this module declares the map it reads.

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

from hallucinote.db import mutations as M, queries as Q
from hallucinote.melody.lens import SectionMelody
from hallucinote.melody.profile import MelodicProfile
from hallucinote.meter import MeterMap, MeterPoint, parse_meter
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

    ``start_beat`` and ``length_beats`` are the section's position and span in
    absolute beats, resolved through the song's meter map — ``start_beat``
    measured from the arrangement's own first bar (``plan(start_bar=…)``). They
    are carried rather than recomputed because bar arithmetic against a single
    ``beats_per_bar`` is exactly what #566 retired: a consumer that multiplies
    bars by a scalar is wrong for every bar after a meter change.

    Both are **required**, deliberately. They are derived facts that must agree
    with ``start_bar``/``end_bar``, so there is no neutral default — a zero
    agrees with no bar range at all, and the lens bridges read them rather than
    recompute, so a section constructed with one would grade silently wrong.
    """

    name: str
    function: str
    start_bar: int
    end_bar: int
    energy: float
    genre: str | None
    layers: Layers
    start_beat: float
    length_beats: float
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
    meter: str | None = None  # sugar for a meter point at this section's start bar


class Arrangement:
    """An ordered sequence of sections that materializes into a song.

    Sections are appended in playback order; ``plan()`` assigns each its bar
    range sequentially. A section's ``layers`` map ``track name -> notes``
    (0-based within the section); a track absent from the map simply doesn't
    play that section (e.g. organ tacet in the metal sections).

    **The arrangement is where a song declares its meter.** Every position this
    class computes is resolved through a :class:`~hallucinote.meter.MeterMap` —
    the same ruler push resolves bar positions through — so a section boundary
    after a meter change lands on the beat push will put it on. There is no
    second ruler and no ``beats_per_bar`` accumulation.

    Meter is declared in one of three ways, which differ in **which bar they
    name**:

    - ``Arrangement(meter="7/4")`` — the meter from bar 1 (``beats_per_bar=7.0``
      is the scalar spelling of the same thing, kept for songs that use it; a
      scalar cannot tell 6/8 from 3/4, so declare ``"6/8"`` when you mean it).
    - ``meter_change(at_bar=86, meter="7/4")`` — a point at an **absolute song
      bar**, wherever the layout starts.
    - ``section(..., meter="7/4")`` — sugar for a point at **that section's own
      start bar**, and nothing more. Under ``plan(start_bar=17)`` the section
      moves and its meter point moves with it; an ``at_bar=`` point does not.

    Those two coordinate systems agree whenever the layout starts at bar 1,
    which is every song in the tree. Mixing them under a non-1 ``start_bar`` is
    the case to be careful with: ``meter_map`` prints the bar-1 layout, so read
    ``meter_map_at(start_bar)`` — what ``plan()`` and ``materialize()`` actually
    use — when the layout starts anywhere else.

    **A meter persists until the next point.** That is what a map means, and a
    section does not own a meter or restore the previous one when it ends. So a
    single borrowed bar is two points, not one::

        arr.meter_change(at_bar=86, meter="7/4")   # the bar that breathes
        arr.meter_change(at_bar=87, meter="4/4")   # and back

    ``arr.meter_map.describe()`` prints what you actually declared.
    """

    def __init__(
        self,
        *,
        beats_per_bar: float | None = None,
        meter: str | None = None,
    ) -> None:
        if beats_per_bar is not None and meter is not None:
            raise ValueError(
                "declare the bar-1 meter once: pass meter='7/4' or "
                "beats_per_bar=7.0, not both"
            )
        self._specs: list[_SectionSpec] = []
        self.motifs: dict[str, Motif] = {}
        if meter is not None:
            self._meter_map = MeterMap.parse(meter)
        elif beats_per_bar is not None:
            self._meter_map = MeterMap.uniform(beats_per_bar)
        else:
            self._meter_map = MeterMap.parse("4/4")
        self._harmonic_plan: Progression | None = None

    # -- meter (the song's one ruler) --------------------------------------

    def meter_map_at(self, start_bar: int = 1) -> MeterMap:
        """The declared meter for a plan laid out from ``start_bar``.

        Section bar NUMBERS never depended on meter — they accumulate whole
        bars — so the per-section ``meter=`` sugar resolves to a point at the
        section's start bar without needing the map it contributes to.
        """
        resolved = self._meter_map
        bar = start_bar
        for spec in self._specs:
            if spec.meter is not None:
                numerator, denominator = parse_meter(spec.meter)
                resolved = resolved.with_point(
                    MeterPoint(float(bar), numerator, denominator)
                )
            bar += spec.bars
        return resolved

    @property
    def meter_map(self) -> MeterMap:
        """The declared meter of the canonical layout (from bar 1), per-section
        sugar included. Sugar that is not inspectable is how a second ruler
        hides, so this is a property and not a private field."""
        return self.meter_map_at()

    @property
    def beats_per_bar(self) -> float:
        """Beats in bar 1. The song's meter is :attr:`meter_map`; this is the
        bar-1 reading of it, and it is wrong for any bar after a meter change —
        never place against it."""
        return self._meter_map.beats_per_bar_at(1.0)

    def meter_change(self, *, at_bar: float, meter: str) -> "Arrangement":
        """Declare a meter point: from ``at_bar`` on, the song is in ``meter``.

        Returns self for chaining. Declaring one bar twice with different
        meters raises — the composer has said two things about one bar.
        """
        numerator, denominator = parse_meter(meter)
        self._meter_map = self._meter_map.with_point(
            MeterPoint(float(at_bar), numerator, denominator)
        )
        return self

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
        meter: str | None = None,
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

        ``meter`` (e.g. ``"7/4"``) is sugar for :meth:`meter_change` at this
        section's start bar — and nothing more. It does NOT revert at the
        section's end: a meter persists until the next point, because that is
        what the song's meter map means. A section that follows an odd one and
        should be in 4/4 says so.
        """
        if bars <= 0:
            raise ValueError(f"section {name!r}: bars must be > 0, got {bars}")
        if isinstance(progression, str) and progression != "inherit":
            raise ValueError(
                f"section {name!r}: progression string must be 'inherit', got "
                f"{progression!r}"
            )
        if meter is not None:
            parse_meter(meter)  # fail at the call site, not at plan time
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
                meter=meter,
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
        """Assign each section its bar range and resolve its harmony and its
        position in absolute beats. Pure — no DB.

        Bar numbers accumulate (a 16-bar section starting at bar 13 ends at 29
        whatever the meter); BEATS are resolved through the song's meter map, so
        a boundary after a meter change lands where push puts it rather than
        where uniform bar math would.
        """
        meter_map = self.meter_map_at(start_bar)
        origin_beats = meter_map.beats_at(float(start_bar))
        placed: list[PlacedSection] = []
        bar = start_bar
        for s in self._specs:
            end_bar = bar + s.bars
            start_beats = meter_map.beats_at(float(bar))
            section_len_beats = meter_map.beats_at(float(end_bar)) - start_beats
            offset_beats = start_beats - origin_beats
            prog = self._resolve_progression(s, offset_beats, section_len_beats)
            key_pc, mode_obj = self._resolve_key_mode(s, prog)
            placed.append(
                PlacedSection(
                    name=s.name,
                    function=s.function,
                    start_bar=bar,
                    end_bar=end_bar,
                    energy=s.energy,
                    genre=s.genre,
                    layers=s.layers,
                    start_beat=offset_beats,
                    length_beats=section_len_beats,
                    key_pc=key_pc,
                    mode=mode_obj,
                    progression=prog,
                )
            )
            bar = end_bar
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
                length_beats=p.length_beats,
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
                length_beats=p.length_beats,
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
        (melody's pitch reads harmony) + its ``bars`` grid — the strong-beat
        read, per bar, so a section spanning a meter change grades each bar
        against its own meter rather than the song's opening one.

        ``profiles`` (phase 2b) is the song's declared ``{layer_name:
        MelodicProfile}`` map, carried onto every section so the lens grades each
        line against its declared intent (``None`` = the unchanged 2a path). The
        profile lives in build.py, never on the arrangement (Decision-Record 1) — so
        it rides through here as a passthrough, not a stored field. Feed the result
        to ``melody.lens.analyze_melody``."""
        layers_tuple = tuple(melody_layers) if melody_layers is not None else None
        meter_map = self.meter_map_at(start_bar)
        return [
            SectionMelody(
                name=p.name,
                length_beats=p.length_beats,
                layers=p.layers,
                progression=p.progression,
                melody_layers=layers_tuple,
                bars=meter_map.grid_for(p.start_bar, p.end_bar),
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
                length_beats=p.length_beats,
                layers=p.layers,
                start_beat=p.start_beat,
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

        **The declared meter is written first**, as ``time_signature_map``
        points, and then read back: if the song's map is not the map this
        arrangement declares, nothing further is written and the disagreement
        raises. Two places declaring one song's meter is how the two bar rulers
        happened; a build that would create a second one fails where the second
        one was introduced rather than at push time, where it can be reported
        and not repaired.

        Rows take the mutator's ``bar_ruler="map"`` default like every other
        writer — the positions above ARE map-resolved. ``uniform`` survives only
        as provenance on rows written before that was true.
        """
        placed = self.plan(start_bar=start_bar)
        self._author_meter_map(conn, song_id=song_id, start_bar=start_bar,
                               actor=actor)
        created = {"clips": 0, "notes": 0, "placements": 0, "sections": 0, "cues": 0}
        for idx, sec in enumerate(placed):
            slot = idx + 1
            length_beats = sec.length_beats

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
                    name=sec.name,
                    actor=actor, reason=f"{sec.name} cue",
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

    def _author_meter_map(
        self, conn, *, song_id: str, start_bar: int, actor: str,
    ) -> None:
        """Write the declared meter into ``time_signature_map`` — but only once
        the song's existing map is known to say nothing different.

        **The check comes before the write**, because the write would otherwise
        hide what it is checking for: ``add_time_signature_point`` UPDATES the
        row at a bar it already holds, so an arrangement declaring 4/4 at bar 1
        would silently overwrite a song declaring 3/4 there and then read back
        perfect agreement. Every point the song already holds must be a point
        this arrangement declares, identically.

        Points the arrangement re-declares identically — every song's build.py
        authors its own bar-1 row — pass through as the no-ops they are.
        """
        declared = self.meter_map_at(start_bar)
        stored = MeterMap.from_rows(Q.get_time_signature_map(conn, song_id))
        declared_at = {p.start_bar: p for p in declared.points}
        for point in stored.points:
            mine = declared_at.get(point.start_bar)
            if mine is None or (mine.numerator, mine.denominator) != (
                point.numerator, point.denominator
            ):
                raise ValueError(
                    f"song {song_id!r} declares a meter this arrangement does "
                    f"not: stored [{stored.describe()}] vs arrangement "
                    f"[{declared.describe()}] — they first differ at bar "
                    f"{point.start_bar:g}. A song's meter is its map, declared "
                    f"once; reconcile them before materializing."
                )
        for point in declared.points:
            M.add_time_signature_point(
                conn, song_id=song_id, start_bar=point.start_bar,
                numerator=point.numerator, denominator=point.denominator,
                actor=actor, reason=f"meter {point.meter} from bar {point.start_bar:g}",
            )
        written = MeterMap.from_rows(Q.get_time_signature_map(conn, song_id))
        if written != declared:
            raise ValueError(
                f"song {song_id!r} meter map did not take: wrote "
                f"[{declared.describe()}], read back [{written.describe()}]"
            )


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
