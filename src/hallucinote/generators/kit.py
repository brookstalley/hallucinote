"""Drum-kit lookup: canonical pad name → MIDI note for the loaded kit.

M1-C. Drum Rack pads in Live use kit-specific MIDI notes — Late Nite Kit
puts the kick at 36, Hot Rod Kit might put crash at 51 instead of 49,
and a third-party kit (Goldbaby, Wave Alchemy) puts everything wherever
its sample author decided. Generators like :func:`hallucinote.generators
.drums.kick_stumble` need to author *the right note for this kit*, not a
hardcoded GM-standard guess.

The :class:`Kit` object is the typed read surface. Build one of three ways:

* :meth:`Kit.from_device` — load mappings persisted by
  ``tools/capture_cli.py`` for the Drum Rack at ``device_id``. The
  authoritative path for songs whose snapshot has been captured.
* :meth:`Kit.from_dict` — pass an explicit ``{canonical_name: midi_note}``
  dict. Test-friendly; also useful for songs whose author has measured
  the kit by hand.
* :meth:`Kit.gm_default` — General-MIDI-flavored pad layout. Reasonable
  default for songs whose snapshot hasn't been captured yet, and
  symmetric with the constants in :mod:`primitives` that the pre-M1-C
  generators relied on.

Canonical names are lower-snake-case strings: ``"kick"``, ``"snare"``,
``"hat_closed"``, etc. The fuzzy matcher in :func:`_canonical_to_chain`
recognizes a chain whose name *contains* the canonical token (case-
insensitive) — so a kit with a chain named ``"Kick Drum"`` resolves
``Kit.pitch_of("kick")`` correctly without per-kit configuration. Names
without a canonical match warn-and-fall-through to the GM default,
keeping composition flowing for kits that don't expose every pad.
"""
from __future__ import annotations

import sqlite3
import warnings
from dataclasses import dataclass, field

from hallucinote.db import queries as Q


# General-MIDI-flavored canonical pad layout. Mirror of the constants in
# :mod:`hallucinote.generators.primitives` that pre-M1-C generators read
# directly. ``Kit.gm_default()`` returns a Kit with this dict.
_GM_DEFAULTS: dict[str, int] = {
    "kick": 36,
    "snare": 38,
    "clap": 39,
    "rim": 37,
    "hat_closed": 42,
    "hat_open": 46,
    "tom_lo": 47,
    "tom_mid": 48,
    "tom_hi": 50,
    "ride": 51,
    "ride_bell": 53,
    "crash": 49,
    "crash_1": 49,
    "crash_2": 57,
    "splash": 55,
    "china": 52,
    "shaker": 70,
    "tambourine": 54,
    "cowbell": 56,
}


# Substrings that disambiguate "closed" vs "open" hi-hat chain names.
# Match order matters — ``"closed"`` MUST be checked before bare ``"hat"``,
# otherwise ``"Closed Hat"`` would resolve to ``"hat_open"`` via the
# negative-of-closed pattern. See :func:`_chain_matches_canonical`.
_HAT_CLOSED_HINTS = ("closed", "cl ", "cl.", "chh", "ch ")
_HAT_OPEN_HINTS = ("open", "oh ", "ohh", "op ")


def _normalize(s: str) -> str:
    """Lowercase + collapse internal whitespace for matcher comparisons."""
    return " ".join(s.lower().split())


def _chain_matches_canonical(chain_name: str, canonical: str) -> bool:
    """Fuzzy match: does ``chain_name`` look like the canonical pad?

    Rules (each canonical token gets a small bespoke matcher because
    drum-kit naming conventions vary):

    * ``kick``: chain contains 'kick' or starts with 'bd' or 'bass drum'.
    * ``snare``: chain contains 'snare' or starts with 'sd' or 'sn '.
    * ``hat_closed``: chain mentions 'hat' / 'hh' AND has a closed-hint.
    * ``hat_open``: chain mentions 'hat' / 'hh' AND has an open-hint.
    * Everything else: simple substring match on the canonical token
      (with underscores replaced by spaces for multi-word tokens like
      ``ride_bell``).
    """
    name = _normalize(chain_name)
    if canonical == "kick":
        return (
            "kick" in name
            or name.startswith("bd")
            or "bass drum" in name
        )
    if canonical == "snare":
        return (
            "snare" in name
            or name.startswith("sd")
            or name.startswith("sn ")
            or name == "sn"
        )
    if canonical in ("hat_closed", "hat_open"):
        is_hatlike = "hat" in name or "hh" in name
        if not is_hatlike:
            return False
        closed_signal = any(h in name for h in _HAT_CLOSED_HINTS)
        open_signal = any(h in name for h in _HAT_OPEN_HINTS)
        if canonical == "hat_closed":
            return closed_signal or (not open_signal and "hh" in name)
        return open_signal
    if canonical == "crash":
        # 'crash' or 'crash_1' both match a chain named "Crash" — the
        # canonical-specific lookup picks the more specific match first.
        return "crash" in name
    token = canonical.replace("_", " ")
    return token in name


def _canonical_to_chain(
    canonical: str, mappings_by_note: dict[int, str],
) -> int | None:
    """Pick the MIDI note for ``canonical`` from a {midi_note: chain_name} dict.

    Returns the lowest matching MIDI note (Drum Racks number bottom-up,
    so the canonical "kick" is typically the lowest-numbered pad). When
    nothing matches, returns ``None`` — the caller decides whether to
    fall through to GM defaults or raise.
    """
    candidates = sorted(
        (note, chain) for note, chain in mappings_by_note.items()
        if _chain_matches_canonical(chain, canonical)
    )
    if not candidates:
        return None
    return candidates[0][0]


@dataclass(frozen=True)
class Kit:
    """A typed read surface over a Drum Rack's pad layout.

    Instances are immutable so passing a Kit through generator helpers
    can't accidentally mutate shared state across clips.
    """
    name: str
    device_id: str | None
    mappings_by_note: dict[int, str] = field(default_factory=dict)

    @classmethod
    def from_device(
        cls,
        conn: sqlite3.Connection,
        device_id: str,
        *,
        name: str | None = None,
    ) -> "Kit":
        """Build a Kit from the DB's ``drum_pad_mappings`` rows for ``device_id``.

        ``name`` defaults to a stub derived from the device_id — pass the
        device's display_name explicitly when you want the warning text
        to be informative.
        """
        rows = Q.get_drum_pad_mappings(conn, device_id)
        mappings = {int(r["midi_note"]): str(r["chain_name"]) for r in rows}
        return cls(
            name=name or f"device:{device_id[:8]}",
            device_id=device_id,
            mappings_by_note=mappings,
        )

    @classmethod
    def from_dict(
        cls,
        canonical_to_note: dict[str, int],
        *,
        name: str = "explicit",
        device_id: str | None = None,
    ) -> "Kit":
        """Build a Kit from a ``{canonical_name: midi_note}`` dict.

        The canonical names become synthetic chain names ("kick" → chain
        named ``"kick"``) so the fuzzy matcher in :meth:`pitch_of` finds
        them. Useful for tests and for songs whose author has measured
        the kit by hand without going through capture.
        """
        return cls(
            name=name, device_id=device_id,
            mappings_by_note={
                int(note): canonical for canonical, note in canonical_to_note.items()
            },
        )

    @classmethod
    def gm_default(cls) -> "Kit":
        """Return a Kit pre-populated with the General-MIDI pad layout."""
        return cls.from_dict(_GM_DEFAULTS, name="GM Default")

    def pitch_of(self, canonical_name: str) -> int:
        """Resolve ``canonical_name`` to the kit's MIDI note for that pad.

        Falls through to :data:`_GM_DEFAULTS` with a warning when the kit
        has no chain matching ``canonical_name``. Raises :class:`KeyError`
        only when the name isn't even a known canonical pad.
        """
        if self.mappings_by_note:
            note = _canonical_to_chain(canonical_name, self.mappings_by_note)
            if note is not None:
                return note
        if canonical_name not in _GM_DEFAULTS:
            raise KeyError(
                f"pitch_of: unknown canonical pad name {canonical_name!r}; "
                f"known: {sorted(_GM_DEFAULTS)}"
            )
        if self.mappings_by_note:
            warnings.warn(
                f"Kit {self.name!r} has no chain matching canonical pad "
                f"{canonical_name!r}; falling through to GM default "
                f"(note {_GM_DEFAULTS[canonical_name]}). Captured chain "
                f"names: {sorted(self.mappings_by_note.values())}",
                UserWarning,
                stacklevel=2,
            )
        return _GM_DEFAULTS[canonical_name]

    # Convenience attribute access for common pads — `kit.kick` reads better
    # than `kit.pitch_of("kick")` in generator code.
    @property
    def kick(self) -> int: return self.pitch_of("kick")
    @property
    def snare(self) -> int: return self.pitch_of("snare")
    @property
    def hat_closed(self) -> int: return self.pitch_of("hat_closed")
    @property
    def hat_open(self) -> int: return self.pitch_of("hat_open")
    @property
    def tom_lo(self) -> int: return self.pitch_of("tom_lo")
    @property
    def tom_hi(self) -> int: return self.pitch_of("tom_hi")
    @property
    def ride_bell(self) -> int: return self.pitch_of("ride_bell")
    @property
    def crash(self) -> int: return self.pitch_of("crash")


__all__ = ["Kit"]
