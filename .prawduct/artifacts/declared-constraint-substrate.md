# Declared-Constraint Substrate — the framework verifies a rule it never knows

**Status:** designed (2026-06-03). Not yet built — this is the spec.
**Backlog:** CON-7K3D. **Related:** LNT-1V9K (gate-verdict policy — this is its next
layer), MEL-1A7K (`MelodicProfile` — the fixed-schema precedent this generalizes
under), ARR-1H9C (harmony lint), GEN-1S4K (generator-altitude — sibling ruler-not-stamp).
Principles: `feedback_great_art_not_software`, `feedback_tools_are_conveniences_not_limits`,
`feedback_generalize_research_first` (uniform mechanism > registry > whitelist),
`feedback_prefer_llm_over_deterministic_module`, `project_melody_model_meta_answer`
(declared-profile-over-universal).

## The trigger (the song that asked for it)

`missing` (in the songs repo) is built on a single conceit: **every chord is voiced
without its root.** Reviewing it raised the obvious tooling question — should the
framework gain a "rootless voicing" capability? The user's answer, verbatim
(2026-06-03):

> *"This 'rootless voicings' thing is important, but we DO NOT want to promote
> rootless voicings to a high level framework capability. Tomorrow I'll say 'no
> fifths', or 'only inversions where the root is in the middle' or whatever. How can
> this be generalized, while supporting creativity?"*

And on why the abstraction earns its place at all:

> *"this is how I write (and how many artists write, I think) — set up interesting
> rules and explore what falls out."*

That creative stance — **declare a rule, then explore the space it carves out** — is
the thing to support. Not any particular rule.

## The trap

A named `rootless` helper (or a `Chord.voicing(omit={root})` parameter, or a registry
of `{rootless, no-fifths, root-in-middle}`) is a **whitelist**. It caps creativity at
the set of rules someone thought to enumerate. Tomorrow's "only inversions where the
root is in the middle" isn't in it, so the composer is back to hand-rolling — and the
framework has acquired a musical opinion it shouldn't hold. Every named constraint is
the framework making a musical decision (a *stamp*), which `feedback_great_art_not_software`
forbids.

## The principle — mechanism, not policy

> **The framework knows how to VERIFY a declared rule against composed notes. It never
> knows what the rule IS. The rule lives entirely in the song.**

`rootless`, `no fifths`, `root-in-the-middle` are all the same *shape* — **a predicate
over the notes sounding at a moment, relative to the declared harmony and time** —
differing only in the predicate body. So the framework owns the universal half (the
slot, the runner, the finding shape, the never-block policy, the per-song-test gate),
and the song owns the particular half (the predicate). This is the
uniform-mechanism-over-registry move from `feedback_generalize_research_first`.

## This is the 4th application of an existing pattern

The codebase has already built "declared intent → lens grades against it → coaching
finding → ship → the song's own test is the gate" three times. This substrate is the
same pattern with an **open schema** instead of a fixed one:

| Axis | Declared intent | Lens | Finding | Where intent lives |
|---|---|---|---|---|
| Harmony | `Progression` | `theory.lint.lint_harmony` | `HarmonyFinding` (`theory/lint.py:64`) | `build.py` |
| Melody | `MelodicProfile` (`melody/profile.py:83`) | `melody.lens.analyze_melody` (`:825`) | `MelodyFinding` (`:162`) | `build.py` |
| Performance | (P1 baseline) | `performance.lens.analyze_performance` | `PerfFinding` (`performance/lens.py:114`) | `build.py` |
| **Constraint (this)** | **arbitrary predicate** | `constraint.lens.analyze_constraints` | `ConstraintFinding` | `build.py` (the predicate itself) |

`MelodicProfile` is a *fixed-schema* declared intent (9 known fields, graded by a fixed
lens). The constraint substrate is the **open-schema layer that sits underneath it**:
anything nobody curated into a profile is expressible as a predicate. Curated profiles
like `MelodicProfile` become *sugar* on top of the substrate — convenience for the one
or two axes common enough to deserve a named schema. Uniform mechanism first; curated
profiles second.

## The mechanism — a Constraint is (declared intent, evaluator)

One abstraction. The evaluator is interchangeable between two **registers**.

### Register A — a code predicate (deterministic; can back a hard gate)

The song writes a `Callable` in its own `build.py` — exactly how it already hands a
`transform=Callable` to `arrangement.vary()` (`arrangement.py:457`). Composer-supplied
logic in the authoring layer is not new; what's new is composer-supplied logic in the
*measuring* layer.

```python
# proposed shapes — src/hallucinote/constraint/ (pure stdlib, render-free,
# the 4th sibling to theory.lint / melody.lens / performance.lens)

Severity = Literal["info", "warning", "blocking"]   # shared with the other lenses

ConstraintPredicate = Callable[[Sequence[NoteDict], "ConstraintCtx"],
                               "ConstraintFinding | None"]

@dataclass(frozen=True)
class Constraint:
    """A composer-declared rule for ONE song. The framework never inspects what the
    rule means — it only runs `predicate` and reports whatever it returns."""
    name: str                       # "root-withheld" — a label, NOT a known type
    intent: str                     # one-line prose: the rule + why (the WHY anchor)
    predicate: ConstraintPredicate  # the evaluator
    decision_ref: str | None = None # link to the decision doc that owns the rationale

@dataclass(frozen=True)
class ConstraintCtx:
    """Everything a predicate needs to be time- and harmony-aware. This is what lets
    'withhold X until bar N' fall out as an ordinary predicate (see below)."""
    section: str
    start_bar: float
    end_bar: float
    bars: "BarGrid"          # NOT a scalar: a 7/4 bar's length is per-bar (#566)
    key_pc: int
    mode: str
    progression: "Progression | None"
    def bar_of(self, note: "NoteDict") -> float: ...   # convenience

@dataclass(frozen=True)
class ConstraintFinding:        # the SAME 6-field shape as every other lens
    kind: str
    severity: Severity          # "info"/"warning" for a choice — NEVER "blocking"
    section: str
    detail: str                 # phrased as a question, never a verdict
    metric: float | None = None
    track: str | None = None
```

The arrangement adapter mirrors `section_melody_inputs` (`arrangement.py:321`) — a pure
passthrough, so the constraints live in `build.py`, not on the arrangement:

```python
def section_constraint_inputs(
    self, *, start_bar: int = 1,
    constraints: Sequence[Constraint] | None = None,
) -> list[SectionConstraint]: ...

def analyze_constraints(sections: Sequence[SectionConstraint]) -> ConstraintReport: ...
```

`rootless` is then ~5 lines the **song** owns — the framework ships zero of it:

```python
# songs/missing/build.py — NOT in the framework
def root_withheld(notes, ctx):
    landed = [n for n in notes
              if n["pitch"] % 12 == ctx.key_pc          # the tonic pitch class
              and n["duration_beats"] >= 1.0            # "with weight"
              and ctx.bar_of(n) < CODA_BAR]             # before the reveal
    if landed:
        return ConstraintFinding(
            kind="root-present-early", severity="info", section=ctx.section,
            detail=f"{len(landed)} weighted tonic notes before the coda — intended?",
            metric=float(len(landed)))
```

Tomorrow's "no fifths" is a *different* 5-line predicate the song owns. "Root in the
middle" is a third. **The framework is byte-for-byte unchanged across all of them.**
The predicate space is Turing-complete, so it can never cap what a song can declare.

### Register B — a prose rubric, LLM-evaluated (advisory only)

Some rules don't reduce to code — "even the false dawn has the wound in it," "the
voicings should *feel* like reaching." For those the declaration is the prose already
in the song's decision doc, and the evaluator is a model call that reads a compact
rendering of the notes plus the prose and returns the *same* `ConstraintFinding` shape.
This honors `feedback_prefer_llm_over_deterministic_module` for the cases deterministic
code can't reach.

**Architectural boundary (load-bearing):** the deterministic substrate
(`src/hallucinote/constraint/`) stays **pure stdlib, render-free**, like its three
sibling lenses — so it can back a committed regression test. The LLM-rubric evaluator
lives at the **orchestration / skill layer** (`/compose-review`), where model calls are
allowed; it is **advisory only and never the basis of a committed `assert`**
(non-determinism must not gate CI). Same finding shape, same never-block policy; two
layers, two reliability classes.

## Authoring stays with the LLM — no voicing engine, ever

The original review proposed a "rootless ruler" (`Chord.voicing(omit={root})`). That is
the mistake this design corrects: a parameterized voicing engine (`omit=…`,
`position={root: middle}`) is a **covert registry** — it caps at the manipulations
someone coded. The genuinely general authoring tool is the **LLM writing notes against
the declared constraint in context.** So the split is clean and total:

- **The framework VERIFIES** — the constraint lens (deterministic) or rubric (LLM).
- **The LLM AUTHORS** — notes that satisfy the declared rule, the decision doc + the
  `intent` string in context.

No voicing engine is added now or later. That is what makes
`feedback_tools_are_conveniences_not_limits` literally true here: the only "tool" is a
measurement; it removes no authoring freedom because it does no authoring.

## Why this supports creativity (the load-bearing half)

Four guarantees, all inherited from or extending `gate-verdict-policy.md` (LNT-1V9K):

1. **Open predicate space.** Any rule, code or prose. The framework imposes no
   vocabulary of constraints.
2. **Asks, never blocks.** A *violation* surfaces as *"you declared X; the notes break
   it here — intended?"*, `severity="info"/"warning"`, never `"blocking"` (blocking
   stays reserved for the technical-error list in LNT-1V9K). So you can break your own
   rule for the art. **`missing`'s coda is a deliberate violation of "no E"** — the
   predicate knows the release bar (`ctx.bar_of`), expects the arrival there, and flags
   only the *un*intended early grounding. A constraint must never become a cage.
3. **Per-song, never universal.** The framework ships no blessed constraints, so nothing
   biases composition toward a "correct" voicing vocabulary. (The melody meta-answer
   again: no universal verdict, only intent-relative.)
4. **The composer owns the gate.** If a song wants the rule enforced as a regression,
   the *song* writes the test — `assert report.violations == ()` — exactly as
   sun-zone-done owns `test_harmony_realization_has_no_stasis`. The framework never
   decides a constraint is mandatory.

## Two simplifications that fall out

- **"Withholding-and-release" is not a separate primitive.** A withheld-then-released
  foundation (root, sub-octave, kick-on-3) is just a *time-aware predicate*: absent
  with weight before `ctx.bar_of(n) < release`, present at/after. Because `ConstraintCtx`
  carries bar position, the temporal contract falls out of the general mechanism — no
  bespoke "contract" type needed.
- **`MelodicProfile` is sugar on the substrate.** A fixed-schema profile is a curated
  convenience over the open predicate layer, for the one axis common enough to deserve
  it. Recurrence/`Motif` matching is similar — a curated matcher over the same notes.
  The substrate is the floor they all stand on.

## First instance — `missing`'s three withheld axes (pressure-test the shape)

The song's identity is three foundations withheld until one instant in the coda
(`annotations/00-theme.md`, `decisions/03,04,08`). Each becomes one predicate over the
*same* notes, sharing one mechanism:

| Predicate | Axis | Fires when (before coda) |
|---|---|---|
| `root_withheld` | pitch class | the tonic PC lands with weight/duration on a strong beat |
| `sub_octave_reserved` | register | any note below ~E2 carries weight |
| `kick_off_three` | rhythm | a kick onset lands on beat 3 |

…and each *confirms the arrival* at the release. `missing`'s
`test_root_absence_until_coda` (and siblings) assert `report.violations == ()`,
promoting the rules the song cares about to real gates while leaving the framework
opinion-free. If the three predicates author cleanly and the findings read well, the
shape is confirmed; if they fight `ConstraintCtx`, the ctx surface is wrong — that is
the thing to learn from the first build.

## When to build it (proportionality — the honest challenge)

The **zero-framework version works today**: a per-song pytest that queries notes and
asserts, plus the LLM keeping the rule in context while composing. The substrate's only
adds are (a) the *coaching* channel during the compose loop (a raw test is binary at
test time; a finding asks continuously, beside the other lens reports), (b) a uniform
finding shape, and (c) clean handling of the *intended* violation at the release. For a
**one-off** song, skip the abstraction and write the test.

It earns its keep because `missing` is **variation 1 of a planned series** of
constraint-driven songs (`decisions/09-variation-roadmap.md`) — a body of work whose
whole method is "declare a rule, explore the space." Recommended sequencing, in two
refinements over the naive "ship the song, then build after song 2":

**(1) Author the first song's predicates in the substrate's eventual shape — against a
~15-line local shim in the song, NOT raw `assert`s.** A song-local `_constraint.py`
(a `ConstraintCtx` namedtuple, a `ConstraintFinding` namedtuple, a runner loop) lets
`missing` ship now AND exercise the real predicate ergonomics, so the first song is a
genuine interface probe with **zero rewrite debt** — promotion to `src/` later is a
mechanical lift, not a redo. This is song-first in *sequencing*, framework-shaped in
*form*: the asymmetry that justifies it — wrong-interface rework ≫ a 15-line lift, and
the song ships either way — favors the reversible path.

**(2) "Confirm the surface" means a *differently-shaped* second use, not any second
song.** `missing`'s three predicates are all the SAME shape — "absence of X before bar
N" (vertical + temporal). They validate one corner and say almost nothing about the
interface's riskiest unknown: **relational / cross-section** predicates ("no fifths,"
"only inversions with the root in the middle," "this chorus's motif must differ from the
last"), where `ConstraintCtx` is least designed. So **deliberately pick the second
constraint song to be relational/cross-section**, and promote the shim to `src/` only
once you've felt where `ctx` fights a differently-shaped rule — not after a second
withholding song that merely re-confirms corner one.

**When to flip to framework-first** (neither holds for `missing` today): (a) a near-term
song needs **Register B** (the LLM prose rubric) — a per-song pytest can't evaluate a
fuzzy aesthetic rule, so that layer isn't extractable from a shim and must be built; or
(b) the variation series is written in **rapid succession** (3–4 back-to-back) — which
compresses the timeline (build after song 2, not song 5) but never reverses the order,
since you still want two *differing* uses before freezing the interface.

## Open questions / risks

- **`ConstraintCtx` surface.** What exactly must a predicate see? First draft: section
  name + bar span + a `BarGrid` (#566 retired the `beats_per_bar` scalar: a scalar cannot
  say whether 3 beats is 3/4 or 6/8, and a predicate reading bars must ask the grid which
  bar a note is in) + `key_pc`/`mode`/`progression` + `bar_of()`. Cross-
  section predicates (e.g. "this motif's pitch set must differ from the last chorus's")
  may need a song-level variant, `analyze_constraints` over the whole arrangement rather
  than per-section. Decide from a second, *deliberately relational* constraint (see the
  sequencing refinements above) — not from `missing`, which only probes the vertical+
  temporal corner.
- **Whole-chord (vertical) vs. line (horizontal) predicates.** `rootless` is vertical
  (what sounds together); a melody rule is horizontal. The lens passes `layers` (per-
  track note lists) and the section's combined surface; a predicate picks its slice.
  Confirm both read cleanly on `missing` (vertical: the rootless pad/arp) and a future
  horizontal case.
- **LLM-rubric drift.** Advisory-only mitigates the gate risk, but rubric findings
  should be reproducible enough to be useful. Capture the rendering + prompt the rubric
  sees so a finding is auditable. Defer until a fuzzy constraint actually needs it.
- **Don't let the substrate grow a constraint *library*.** The standing temptation will
  be to "just add the common ones" to the framework. Resist: predicates live in songs.
  If a predicate is reused across songs, it belongs in a *shared songs-repo* helper, not
  the framework. (Re-read this section before adding anything named to `src/`.)
