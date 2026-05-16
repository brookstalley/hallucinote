"""Reusable musical primitives.

Generators are pure functions: they take parameters and return either a
`GeneratorOutput` (canonical) or a `list[NoteDict]` (legacy — still supported
via the `as_generator_output` normalizer). They never touch the DB.

Note generators emit `NoteDict` lists tagged with semantic labels so post-hoc
bulk operations (`update_notes_by_tag(clip_id=..., tag="ghost", velocity_delta=+5)`)
work without re-running the generator.

Envelope generators emit `EnvelopeDict` specs with inline breakpoints; the
caller threads them through `mutations.create_envelope` +
`mutations.replace_breakpoints`.

Canonical shapes:
  NoteDict:     {pitch, start_beats, duration_beats, velocity, tags?}
  EnvelopeDict: {target_kind, target_*_id (one+), parameter_path?, breakpoints: [...]}
"""
from hallucinote.generators.output import (
    EnvelopeDict,
    GeneratorOutput,
    NoteDict,
    as_generator_output,
)

__all__ = [
    "EnvelopeDict",
    "GeneratorOutput",
    "NoteDict",
    "as_generator_output",
]
