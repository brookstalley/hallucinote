"""Shared classifier for the live ``song.tuning_system`` probe read (MICROTUNE).

Two surfaces re-read Live's active tuning and must answer the same question — *is
no alternate tuning loaded?* — about the **identical** wire shape: the tuning
bolt-on (``tuning/read.py``, deriving a ``TuningData``) and the push drift-warn
(``sync/push/tuning_notice.py``, re-reading the loaded tuning). The FR-6 isolation
invariant forbids the core importing the bolt-on, so the shared predicate lives
**here, core-side**, and the bolt-on imports it (``tuning`` → core is the allowed
direction). One predicate ⇒ the two surfaces can never give opposite verdicts for
the same read (the contradiction a Critic caught when they each had their own).

**Narrowness is the hard-won Chunk-1 lesson** (``api-notes-tuning.md``): classify
``None`` ONLY against the *live-confirmed* none shapes — unwrapped ``None`` and the
``ableton_probe`` wrapper ``{"type": "NoneType", ...}`` observed on a 12-TET Set.
A generic ``value is None`` test is explicitly **not** a none-signal: the loaded
``TuningSystem`` dict shape is still PENDING (verify-api), so a null ``value`` on
an unconfirmed shape must fall through to the loud loaded path, never be mistaken
for "nothing loaded" (pinned by ``tuning/test_read.py`` + this module's own test).
"""
from __future__ import annotations


def is_no_tuning_loaded(raw: object) -> bool:
    """True when ``raw`` (a read of ``song.tuning_system``) means "no alternate
    tuning loaded" (= 12-TET). Matches only the live-confirmed none shapes; any
    other shape returns False so the caller hits the loud loaded path."""
    if raw is None:
        return True
    return isinstance(raw, dict) and raw.get("type") == "NoneType"


__all__ = ["is_no_tuning_loaded"]
