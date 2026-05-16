"""GeneratorOutput — the return type that generators emit.

A generator returns either:
  - a `GeneratorOutput` (canonical), or
  - a legacy `list[NoteDict]` (wrapped by the normalizer at call sites).

Generators stay pure: they may build envelope specs but do NOT touch the DB.
The caller threads the resulting notes / envelopes through mutators.

EnvelopeDict shape mirrors the `create_envelope` mutator kwargs plus an inline
`breakpoints` list:

    {
        "target_kind": "mixer_volume",
        "target_track_id": "<uuid>",          # exactly the right *_id field for the kind
        # ... other target_*_id default to None / omitted
        "parameter_path": None,                # set when kind requires it (cc / mpe axis / param name)
        "breakpoints": [
            {"time_beats": 0.0, "value": 0.0, "curve_kind": "linear"},
            ...
        ],
    }

Generators are pure and don't know DB ids; the caller passes target ids in as
opaque strings (the schema doesn't care where they come from).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

NoteDict = dict[str, Any]
EnvelopeDict = dict[str, Any]


@dataclass
class GeneratorOutput:
    """Canonical generator return type.

    Defaults to empty lists so generators that produce only notes (or only
    envelopes) can populate the field they care about and ignore the other.
    """

    notes: list[NoteDict] = field(default_factory=list)
    envelopes: list[EnvelopeDict] = field(default_factory=list)

    def extend(self, other: "GeneratorOutput | Iterable[NoteDict]") -> "GeneratorOutput":
        """In-place merge. Accepts another GeneratorOutput or a bare note list."""
        if isinstance(other, GeneratorOutput):
            self.notes.extend(other.notes)
            self.envelopes.extend(other.envelopes)
        else:
            self.notes.extend(other)
        return self

    def __add__(self, other: "GeneratorOutput | Iterable[NoteDict]") -> "GeneratorOutput":
        merged = GeneratorOutput(notes=list(self.notes), envelopes=list(self.envelopes))
        return merged.extend(other)

    def __iadd__(self, other: "GeneratorOutput | Iterable[NoteDict]") -> "GeneratorOutput":
        return self.extend(other)


def as_generator_output(value: Any) -> GeneratorOutput:
    """Normalize a generator return value to a GeneratorOutput.

    Accepts:
      - `GeneratorOutput` (passed through unchanged)
      - `list[NoteDict]` (legacy — wrapped as `GeneratorOutput(notes=value)`)
      - `None` (empty output)

    Anything else raises TypeError.
    """
    if value is None:
        return GeneratorOutput()
    if isinstance(value, GeneratorOutput):
        return value
    if isinstance(value, list):
        return GeneratorOutput(notes=value)
    raise TypeError(
        f"cannot normalize {type(value).__name__} to GeneratorOutput; "
        "expected GeneratorOutput, list[NoteDict], or None"
    )
