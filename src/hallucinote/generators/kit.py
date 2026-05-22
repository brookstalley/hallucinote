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
``Kit.pitch_of("kick")`` correctly without per-kit configuration.

Three resolution paths exist for callers, intentionally distinct:

* :meth:`Kit.pitch_of` — strict resolver. Returns the matched note;
  warn-and-fall-through to GM ONLY when the GM-default note is empty on
  this kit (harmless silence); **raises** when the GM-default note is
  taken by a differently-named chain (the wrong-sound case that the
  sun-zone-done cautionary tale named — Hot Rod Kit's pad 51 is cowbell,
  not ride). Use when the pattern fundamentally needs that pad.
* :meth:`Kit.try_pitch_of` — optional resolver. Returns ``None`` when
  the kit has captured chains but no match. Use when composition can
  react to absence (e.g., "drop the ride pattern if this kit has no
  ride").
* :meth:`Kit.assert_has` — bulk fail-fast validation. Refuses at
  composition start when the kit can't deliver a required pad set.
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

        Three cases:

        1. **Match.** The kit has a chain whose name fuzzy-matches the
           canonical (e.g. ``"Kick Drum"`` matches ``"kick"``) — return
           that chain's note.
        2. **GM-default points at empty slot.** The kit has captured
           mappings but no matching chain, AND the GM-default note for
           ``canonical_name`` isn't taken by another chain on this kit.
           Falling through to GM plays silence (the pad is empty) — that's
           harmless, so warn-and-fall-through is fine.
        3. **GM-default points at a different chain (wrong-sound case).**
           The kit has captured mappings but no matching chain, AND the
           GM-default note IS taken by a *different-named* chain. Falling
           through here would play the wrong sound (Hot Rod Kit pad 51 is
           "Cowbell Fenk Chick", so ``kit.pitch_of("ride")`` falling
           through to GM 51 would play cowbell instead of ride — the
           sun-zone-done cautionary tale). **Raise** with a teaching
           message naming the colliding chain so the caller can decide
           explicitly: use a different pattern, switch to
           :meth:`try_pitch_of`, or pick a chain by name.

        Empty ``mappings_by_note`` (pre-capture state) short-circuits to
        the GM default silently — the kit just isn't characterized yet.

        Raises :class:`KeyError` when ``canonical_name`` isn't a known
        canonical pad at all (typo). Also raises :class:`KeyError` on the
        wrong-sound case (case 3 above) — the message distinguishes the
        two.
        """
        if canonical_name not in _GM_DEFAULTS:
            raise KeyError(
                f"pitch_of: unknown canonical pad name {canonical_name!r}; "
                f"known: {sorted(_GM_DEFAULTS)}"
            )
        if self.mappings_by_note:
            note = _canonical_to_chain(canonical_name, self.mappings_by_note)
            if note is not None:
                return note
            gm_note = _GM_DEFAULTS[canonical_name]
            colliding_chain = self.mappings_by_note.get(gm_note)
            if colliding_chain is not None:
                raise KeyError(
                    f"pitch_of({canonical_name!r}): kit {self.name!r} has no "
                    f"chain matching {canonical_name!r}, and the GM-default "
                    f"pad at note {gm_note} holds chain {colliding_chain!r} — "
                    "falling through to GM would play that sound instead "
                    "of silence. Use `kit.try_pitch_of(...)` if you want "
                    "None on absence and intend to skip the pattern, or "
                    f"pick a chain by name from {sorted(self.mappings_by_note.values())}."
                )
            warnings.warn(
                f"Kit {self.name!r} has no chain matching canonical pad "
                f"{canonical_name!r}; falling through to GM default "
                f"(note {gm_note}, empty pad on this kit). Captured chain "
                f"names: {sorted(self.mappings_by_note.values())}",
                UserWarning,
                stacklevel=2,
            )
        return _GM_DEFAULTS[canonical_name]

    def try_pitch_of(self, canonical_name: str) -> int | None:
        """Optional resolver. Returns ``None`` when the kit has captured
        mappings AND no chain matches ``canonical_name`` — including the
        wrong-sound case that :meth:`pitch_of` raises on. Empty kit
        (pre-capture) returns the GM default for symmetry with
        :meth:`pitch_of`.

        Use this when composition can react to absence (e.g., "if this
        kit has no ride, drop the ride pattern" rather than "play GM 51
        and hope for the best"). Raises :class:`KeyError` only on unknown
        canonical names — pad-name typos remain a programming error.
        """
        if canonical_name not in _GM_DEFAULTS:
            raise KeyError(
                f"try_pitch_of: unknown canonical pad name {canonical_name!r}; "
                f"known: {sorted(_GM_DEFAULTS)}"
            )
        if not self.mappings_by_note:
            return _GM_DEFAULTS[canonical_name]
        return _canonical_to_chain(canonical_name, self.mappings_by_note)

    def assert_has(
        self, *canonical_names: str, strict: bool = False,
    ) -> None:
        """Refuse early if this kit can't deliver every named canonical pad.

        Bulk fail-fast validation — call at the top of ``build.py`` before
        composing a section that fundamentally needs a specific pad set
        (e.g., a metal section that needs kick / snare / ride / crash).
        If any canonical doesn't resolve via :meth:`try_pitch_of`, raises
        :class:`KeyError` naming the missing pads and the kit's captured
        chains.

        Modes:

        - **Default (``strict=False``)**: empty kit (pre-capture) treats
          every canonical as present via the GM-default fall-through in
          :meth:`try_pitch_of`. The method only catches genuine kit-
          incompleteness — "the kit can deliver these canonicals or fall
          through to GM."

        - **``strict=True``**: refuse on empty mappings too. Use when
          you want "I want to know the kit's pads are characterized AND
          deliver these canonicals" — guards against the sequence where
          ``assert_has`` silently passes pre-capture, then the next
          session populates ``drum_pad_mappings`` and ``pitch_of`` raises
          on the wrong-sound case. Run capture first (e.g., via
          ``/song-pick-instruments`` or ``/song-snapshot``) before
          calling with ``strict=True``.
        """
        if strict and not self.mappings_by_note:
            raise KeyError(
                f"Kit {self.name!r} has no captured pad mappings yet — "
                "strict assert_has refuses pre-capture state because the "
                "GM-default fall-through would silently pass every "
                "canonical, then surface the wrong-sound case on a later "
                "session once drum_pad_mappings is populated. Run capture "
                "first (e.g. /song-snapshot or /song-pick-instruments) and "
                "retry."
            )
        missing = [c for c in canonical_names if self.try_pitch_of(c) is None]
        if missing:
            raise KeyError(
                f"Kit {self.name!r} is missing canonical pad(s) {missing}; "
                f"captured chains: {sorted(self.mappings_by_note.values())}. "
                "Either pick a different kit or rewrite the part(s) that "
                "need the missing pad(s)."
            )

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
