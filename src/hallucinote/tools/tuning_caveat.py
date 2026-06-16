"""The gated lens caveat for songs authored in a non-12 tuning (MICROTUNE Chunk 3).

The symbolic melody/recurrence lenses read intervals as MIDI-step counts and label
them in semitones ("step vs leap", "ambitus N semitones", "transposed up a 3rd").
For a song in an alternate tuning the loaded tuning *reinterprets* every MIDI
number, so those readings are 12-TET-relative, not scale-aware. The lenses do not
become tuning-aware in v1 (that's deliberately out of scope — full step-aware
lenses are a later axis); instead, when a song carries a tuning, their output
carries a one-line **honesty caveat** so a reader of ``/compose-review`` doesn't
mistake a 12-TET interval reading for a scale-aware one.

**Isolation.** This module is on the core side (``tools/`` is scanned by the FR-6
isolation test), so it must **not** import ``hallucinote.tuning``. It needs only
the one bit "is a tuning set?", which it reads through the *tuning-agnostic* core
query :func:`hallucinote.db.queries.get_song_tuning` (it returns the raw
``tuning_ref`` string; this module never deserializes the blob). The lens is the
only core touchpoint of MICROTUNE here, and it is inert for the 99.99%: a 12-TET
song has ``tuning_ref IS NULL`` and sees no caveat (and, on the common path where
no DB exists yet, the lookup degrades quietly to "no tuning").
"""
from __future__ import annotations

import logging

from hallucinote.db import queries as Q
from hallucinote.db.connection import init_db, resolve_db_path
from hallucinote.workspace import resolve_song_dir

logger = logging.getLogger("hallucinote.tools.tuning_caveat")


def song_tuning_ref(slug: str) -> str | None:
    """The song-relative ``.ascl`` ref for ``slug``, or ``None`` for a 12-TET song.

    Resolves the song's per-branch DB (with the legacy bare ``<slug>.db``
    fallback, mirroring ``sync.push_cli``), reads the song row by name (the slug
    *is* the song name — the convention ``Q.get_song_by_name`` relies on), and
    returns its ``tuning_ref``. Returns ``None`` — the 12-TET default — whenever
    the tuning can't be determined (no DB on disk yet, no song row, the column
    NULL): the caveat is purely additive, so a missing signal must fail toward
    "no caveat", never toward a spurious one.
    """
    db_path = resolve_db_path(slug)
    if not db_path.exists():
        # The per-branch DB may not be built yet; try the legacy bare name in
        # the same song dir before giving up (same fallback as push_cli).
        legacy = resolve_song_dir(slug) / f"{slug}.db"
        if not legacy.exists():
            return None
        db_path = legacy

    conn = None
    try:
        # init_db is inside the guard on purpose: a migrate-on-open failure
        # (schema canary, a corrupt/incompatible DB) must NOT crash the lens —
        # its real job is the symbolic reading, which never touches this DB.
        conn = init_db(db_path)
        song = Q.get_song_by_name(conn, slug)
        if song is None:
            return None
        row = Q.get_song_tuning(conn, song["id"])
        return row["tuning_ref"] if row is not None else None
    except Exception as exc:  # prawduct:allow prawduct/broad-except -- the OPTIONAL tuning caveat lookup must never break the lens; any open/read failure degrades to "no caveat" with a logged warning (mirrors the push-side notice)
        logger.warning("tuning caveat lookup skipped for %r: %s", slug, exc)
        return None
    finally:
        if conn is not None:
            conn.close()


def lens_caveat(tuning_ref: str | None) -> str | None:
    """The one-line caveat banner for a lens, or ``None`` when 12-TET.

    Pure (no I/O) so it is trivially unit-testable; callers pass the ref from
    :func:`song_tuning_ref`. The interval math is unchanged — this is only an
    honest-confidence banner naming the tuning file the reading is relative to.
    """
    if not tuning_ref:
        return None
    return (
        f"⚠ tuning: this song is in a non-12 tuning ({tuning_ref}) — the "
        "interval/semitone readings below are 12-TET-relative (raw MIDI-step "
        "counts), not scale-aware. Read them as relative shape, not as "
        "scale-degree distances."
    )


__all__ = ["song_tuning_ref", "lens_caveat"]
