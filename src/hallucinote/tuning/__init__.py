"""Alternate-tuning bolt-on (MICROTUNE / TUN-4Q7W).

A deliberately isolated package for the 0.01% of songs authored in a non-12-TET
tuning. **The core 12-TET path never imports this package** — that inertness is
the design (see ``.prawduct/artifacts/alternate-tunings.md`` FR-6, grep-asserted
in ``tests/unit/tuning/test_isolation.py``). The only core touchpoints are
additive and NULL-inert: the ``songs.tuning_ref`` / ``songs.tuning_data``
columns and a (later-chunk) gated lens caveat + push instruction.

The flow:

1. **read** (``read.py``) — pull ``song.tuning_system`` off the Live LOM and
   derive a :class:`~hallucinote.tuning.model.TuningData`. ``tuning_system is
   None`` → 12-TET no-op; a loaded tuning is mapped against the verify-api
   shapes captured live (Wendy Carlos gamma, 2026-06-19).
2. **cache** (``ascl.py`` + ``cache.py``) — synthesize a re-draggable ``.ascl``
   from the derived data and write it under ``songs/<slug>/tunings/``.
3. **persist / load** (``store.py``) — record the cached ref + the derived blob
   on the song row (through the standard mutator), and read them back.
4. **map** (``mapper.py``) — ``degree_to_midi`` turns a scale-degree index into
   a plain MIDI integer the **unchanged** generators consume.

Acquisition is pull-from-Live only; the cached ``.ascl`` is a faithful
*reconstruction* (relative cents preserved), never the byte-original — the LOM
exposes no source path. No ``.ascl`` *parser* ships: we only ever write.
"""
from __future__ import annotations

from .ascl import write_ascl
from .cache import cache_ascl
from .mapper import degree_to_midi
from .model import TuningData
from .read import TuningReadError, read_tuning_system
from .store import load_song_tuning, persist_tuning

__all__ = [
    "TuningData",
    "write_ascl",
    "cache_ascl",
    "degree_to_midi",
    "read_tuning_system",
    "TuningReadError",
    "load_song_tuning",
    "persist_tuning",
]
