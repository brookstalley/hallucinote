"""hallucinote.theory.lint — the build-time harmonic-conformance lens.

The structural fix for "the framework that let a whole song pedal one chord."
A pure SYMBOLIC ruler over (authored notes, declared progression/mode): it runs
on NoteDicts at BUILD time — no audio render needed (unlike the masking
analyzer, which needs WAVs). It REPORTS; it never edits a note — and it never
BLOCKS a deliberate aesthetic choice (LNT-1V9K). Every finding here is WARNING or
INFO: a coaching question, never a build gate. Harmonic choices — stasis, a
pedaled change, a drone, an absent layer — are aesthetics, not technical errors,
so the lens ASKS and ships the build. The realization BUG it used to gate on (a
generator silently failing to pick up declared changes) is still NAMED, but the
"is this a bug or a choice?" verdict moves to each song's OWN test, where the
intent lives. See `.prawduct/artifacts/gate-verdict-policy.md`.

What it checks, per section that declares harmony:
  - **harmonic_stasis** (WARNING) — the declared progression has >1 distinct
    chord but the parts only ever sound ONE: the parts pedal a written change.
    Could be a deliberate sustained field, or the realization bug — the lens
    cannot tell intent from bug, so it ASKS (warning) and never gates. A song
    that intends movement asserts ``report.stasis_sections == ()`` in its own
    test. A section that *declares* a single chord (a modal drone) is NOT stasis
    — declared==1 is honored, never flagged. (Was BLOCKING; downgraded per
    LNT-1V9K — a ruler never vetoes a deliberate choice; we can ship 4'33".)
  - **harmonic_absence** (INFO) — declares >1 chord but NO harmony layer sounds
    in the section (a bass-less break, a tacet field). Absence is not stasis:
    nothing can realize movement with no harmonic agent present, so this is never
    a violation — a coaching question only. (This is the case that used to
    false-block a deliberately bare section.)
  - **out_of_chord_fraction** (WARNING over threshold) — notes whose pitch class
    is outside the chord sounding at their onset (could be intended passing/
    approach tones — a warning, the composer confirms).
  - **out_of_mode_fraction** (WARNING over threshold) — notes outside the
    declared mode (chromaticism — again, possibly intended).
  - **ambition** (INFO, never blocking) — coaching when a section is a long
    static drone: "intentional, or an unrealized opportunity?" The lens asks; it
    never prescribes a technique. Honors intentional stasis.

Output mirrors `audio/report.py` (frozen dataclasses, a `Severity` Literal, an
explicit `to_dict()` boundary) but is defined locally so the core `theory` layer
never depends on the higher `audio` layer.

Scope (ARR-4V7P boundary): in scope here = each layer's VERTICAL conformance to
the chord it is meant to be playing. Deferred = the INTER-LAYER consonance lens
(do layers X and Y clash with *each other* — intended dissonance or error). That
pairwise-interval analysis is a later read-side lens over the same NoteDicts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from hallucinote.theory.model import Progression, pc_name

NoteDict = dict[str, Any]

Severity = Literal["info", "warning", "blocking"]
_VALID_SEVERITIES = ("info", "warning", "blocking")

# A long static stretch worth a coaching question (beats). 8 bars in 4/4.
_AMBITION_STATIC_BEATS = 32.0


@dataclass(frozen=True)
class HarmonyFinding:
    """One harmonic observation, intent-keyed by ``kind`` + ``severity``."""

    kind: str            # "harmonic-stasis" | "out-of-chord" | "out-of-mode" | "ambition"
    severity: Severity
    section: str
    detail: str
    metric: float | None = None
    track: str | None = None

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
            "track": self.track,
        }


@dataclass(frozen=True)
class LayerHarmony:
    """One layer's conformance against the section's declared harmony."""

    track_name: str
    note_count: int
    out_of_chord_fraction: float
    out_of_mode_fraction: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_name": self.track_name,
            "note_count": self.note_count,
            "out_of_chord_fraction": self.out_of_chord_fraction,
            "out_of_mode_fraction": self.out_of_mode_fraction,
        }


@dataclass(frozen=True)
class SectionHarmony:
    """A section's harmonic-conformance result."""

    section: str
    declared: bool
    key_pc: int | None
    mode_name: str | None
    declared_distinct_chords: int
    sounded_distinct_chords: int
    harmonic_stasis: bool
    layers: tuple[LayerHarmony, ...]
    findings: tuple[HarmonyFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "declared": self.declared,
            "key_pc": self.key_pc,
            "mode_name": self.mode_name,
            "declared_distinct_chords": self.declared_distinct_chords,
            "sounded_distinct_chords": self.sounded_distinct_chords,
            "harmonic_stasis": self.harmonic_stasis,
            "layers": [layer.to_dict() for layer in self.layers],
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass(frozen=True)
class HarmonyReport:
    """The whole-song harmonic-conformance report."""

    song_slug: str
    sections: tuple[SectionHarmony, ...]
    findings: tuple[HarmonyFinding, ...]  # song-level rollup (all findings, flattened)

    @property
    def blocking(self) -> tuple[HarmonyFinding, ...]:
        return tuple(f for f in self.findings if f.severity == "blocking")

    @property
    def ok(self) -> bool:
        """True iff there are no BLOCKING findings.

        The harmony lens emits NO blocking findings (LNT-1V9K — harmonic choices
        are aesthetic, never a build gate), so this is always True; it is kept for
        interface symmetry with the audio/melody/performance reports. The
        realization regression a song actually guards is ``stasis_sections``
        (assert it is empty where the song intends movement), not ``ok``.
        """
        return not self.blocking

    @property
    def stasis_sections(self) -> tuple[str, ...]:
        """Sections where the parts PEDAL a declared multi-chord change — the
        realization bug-shape. This is the regression signal a song asserts in
        its own test (the "is it a bug?" verdict the lens itself no longer makes).
        Absence (no harmony layer sounding) is deliberately NOT counted here."""
        return tuple(s.section for s in self.sections if s.harmonic_stasis)

    def to_dict(self) -> dict[str, Any]:
        return {
            "song_slug": self.song_slug,
            "sections": [s.to_dict() for s in self.sections],
            "findings": [f.to_dict() for f in self.findings],
            "ok": self.ok,
        }


@dataclass(frozen=True)
class SectionLint:
    """The harmony-bearing input for one section — decoupled from
    ``PlacedSection`` so the lens is unit-testable without the arrangement layer
    (Chunk D adds the adapter). Notes are 0-based within the section; the
    ``progression`` is likewise 0-based (its ``chord_at`` is cyclic).

    ``progression=None`` means the section declared no harmony — it is SKIPPED
    (reported ``declared=False``, never a violation). ``harmony_layers`` names
    the pitched, harmony-bearing tracks (exclude drums); ``None`` lints every
    layer.
    """

    name: str
    length_beats: float
    progression: Progression | None
    layers: Mapping[str, Sequence[NoteDict]]
    harmony_layers: tuple[str, ...] | None = None


def _pc(note: NoteDict) -> int:
    return note["pitch"] % 12


def _harmony_layer_names(sec: SectionLint) -> list[str]:
    if sec.harmony_layers is not None:
        return [t for t in sec.harmony_layers if t in sec.layers]
    return list(sec.layers)


def _sounded_distinct_chords(sec: SectionLint, prog: Progression) -> int:
    """How many DISTINCT chords the harmony layers actually express.

    Tile the progression across the section, then for each change-window collect
    the combined pitch-class set the harmony layers play in it. The number of
    distinct (non-empty) such sets is what the parts actually sounded — pedalling
    one chord across a moving progression collapses every window to the same set
    (== 1), which is the stasis signal.
    """
    names = _harmony_layer_names(sec)
    windows = prog.tiled(sec.length_beats).changes
    sounded: set[frozenset[int]] = set()
    for w in windows:
        lo, hi = w.start_beat, w.start_beat + w.duration_beats
        pcs: set[int] = set()
        for t in names:
            for n in sec.layers[t]:
                if lo - 1e-9 <= n["start_beats"] < hi - 1e-9:
                    pcs.add(_pc(n))
        if pcs:
            sounded.add(frozenset(pcs))
    return len(sounded)


def _layer_conformance(
    sec: SectionLint, prog: Progression, track: str
) -> LayerHarmony:
    notes = list(sec.layers[track])
    mode_pcs = prog.mode.pitch_classes(prog.key_pc)
    out_chord = 0
    out_mode = 0
    for n in notes:
        pc = _pc(n)
        if pc not in prog.chord_at(n["start_beats"]).pitch_classes():
            out_chord += 1
        if pc not in mode_pcs:
            out_mode += 1
    total = len(notes)
    return LayerHarmony(
        track_name=track,
        note_count=total,
        out_of_chord_fraction=(out_chord / total) if total else 0.0,
        out_of_mode_fraction=(out_mode / total) if total else 0.0,
    )


def _lint_section(
    sec: SectionLint, *, out_of_chord_warn: float, out_of_mode_warn: float
) -> SectionHarmony:
    prog = sec.progression
    if prog is None:
        # No declared harmony — skip. Graceful degradation to the note floor.
        return SectionHarmony(
            section=sec.name, declared=False, key_pc=None, mode_name=None,
            declared_distinct_chords=0, sounded_distinct_chords=0,
            harmonic_stasis=False, layers=(), findings=(),
        )

    names = _harmony_layer_names(sec)
    layers = tuple(_layer_conformance(sec, prog, t) for t in names)
    declared = prog.distinct_chords
    sounded = _sounded_distinct_chords(sec, prog)
    # A build-time lens is a RULER, not a stamp (LNT-1V9K): it never BLOCKS a
    # deliberate aesthetic choice — it measures and ASKS. The two stasis shapes
    # below surface LOUDLY (warning/info) but never gate. The pedal-a-written-
    # change BUG is still NAMED (harmonic_stasis bool + stasis_sections) so a song
    # that INTENDS movement asserts against it in its OWN test — where intent
    # lives — rather than a global gate that also catches the deliberate field.
    pedaled = declared > 1 and sounded == 1   # present but pedaled — the bug-shape
    absent = declared > 1 and sounded == 0    # nothing realizes it (tacet/bare layer)
    stasis = pedaled                          # the regression signal songs assert on

    findings: list[HarmonyFinding] = []
    if pedaled:
        findings.append(HarmonyFinding(
            kind="harmonic-stasis", severity="warning", section=sec.name,
            detail=(f"declares {declared} distinct chords but the parts sound only "
                    f"one — the harmony is pedaled. A sustained field over a written "
                    f"change (deliberate), or movement the parts failed to realize "
                    f"(the one-chord bug)? The song's own test decides."),
            metric=float(sounded),
        ))
    elif absent:
        findings.append(HarmonyFinding(
            kind="harmonic-absence", severity="info", section=sec.name,
            detail=(f"declares {declared} distinct chords but no harmony layer "
                    f"sounds here — a deliberately bare / tacet section, or an "
                    f"unrealized layer? Absence is not stasis: nothing can realize "
                    f"movement with no harmonic agent present."),
            metric=0.0,
        ))
    elif declared == 1 and sec.length_beats >= _AMBITION_STATIC_BEATS:
        # Intentional stasis is honored — this is a coaching QUESTION, not a gate.
        findings.append(HarmonyFinding(
            kind="ambition", severity="info", section=sec.name,
            detail=(f"static harmony (1 chord) across {sec.length_beats:.0f} beats "
                    f"— a deliberate drone/minimalist field, or an unrealized "
                    f"opportunity to reharmonize the repeat?"),
            metric=sec.length_beats,
        ))

    for lh, t in zip(layers, names):
        if lh.out_of_chord_fraction > out_of_chord_warn:
            findings.append(HarmonyFinding(
                kind="out-of-chord", severity="warning", section=sec.name, track=t,
                detail=(f"{lh.out_of_chord_fraction:.0%} of {t} notes are outside "
                        f"the chord at their onset — intended passing tones?"),
                metric=lh.out_of_chord_fraction,
            ))
        if lh.out_of_mode_fraction > out_of_mode_warn:
            findings.append(HarmonyFinding(
                kind="out-of-mode", severity="warning", section=sec.name, track=t,
                detail=(f"{lh.out_of_mode_fraction:.0%} of {t} notes are outside "
                        f"{pc_name(prog.key_pc)} {prog.mode.name} — intended chromaticism?"),
                metric=lh.out_of_mode_fraction,
            ))

    return SectionHarmony(
        section=sec.name, declared=True, key_pc=prog.key_pc,
        mode_name=prog.mode.name, declared_distinct_chords=declared,
        sounded_distinct_chords=sounded, harmonic_stasis=stasis,
        layers=layers, findings=tuple(findings),
    )


def lint_harmony(
    sections: Sequence[SectionLint],
    *,
    song_slug: str,
    out_of_chord_warn: float = 0.25,
    out_of_mode_warn: float = 0.10,
) -> HarmonyReport:
    """Lint a song's authored harmony against its declared progressions.

    Pure symbolic conformance over the per-section note content. The headline is
    ``report.ok`` (no BLOCKING findings) and ``report.stasis_sections`` — the
    regression a song's test asserts to make the one-chord bug impossible to
    reintroduce. Thresholds are tunable; they govern only WARNING/INFO findings,
    never the blocking stasis gate.
    """
    secs = tuple(
        _lint_section(s, out_of_chord_warn=out_of_chord_warn,
                      out_of_mode_warn=out_of_mode_warn)
        for s in sections
    )
    rollup = tuple(f for s in secs for f in s.findings)
    return HarmonyReport(song_slug=song_slug, sections=secs, findings=rollup)
