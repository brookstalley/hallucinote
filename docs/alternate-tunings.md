# Composing in an alternate tuning (microtonal songs)

> A 0.01% feature, built so the 99.99% never pay for it. If your song is in plain
> 12-tone equal temperament (12-TET) — almost every song — **none of this applies
> and nothing here is on your path.** This is for songs in 19-EDO, Bohlen-Pierce,
> a just-intonation scale, Wendy Carlos's tunings, or any non-12 system Live can
> load.

Hallucinote's design choice for tunings is **isolation over integration**: the
note generators stay tuning-unaware (they take plain MIDI integers 0–127), and a
small `hallucinote.tuning` bolt-on lets you compute *which* MIDI numbers to feed
so that Live's loaded tuning reinterprets them into the pitches you want. The core
12-TET path is byte-for-byte unchanged.

## How tuning works in Live (the mental model)

Live applies one **active tuning** to the whole Set (drag a `.ascl` onto the
Tuning section of the browser, or double-click a shipped one). The tuning
reinterprets every MIDI note number: with an alternate tuning loaded, consecutive
MIDI numbers become **consecutive scale degrees**, and the scale repeats every
`step_count` notes at the tuning's period (an octave for EDO tunings, but *not*
for non-octave tunings like Bohlen-Pierce — never assume 1200 cents).

So authoring in a tuning is just: *think in scale-degree indices, convert each to
a MIDI integer, and write that integer.* That conversion is the mapper.

## Authoring: the mapper feeds the unchanged generators

`hallucinote.tuning.mapper.degree_to_midi` turns a scale-degree index into a MIDI
integer:

```
degree_to_midi(tuning, degree, period=0) = reference_note + period*step_count + degree   (clamped 0–127)
```

You feed those integers straight into the **existing, unmodified** generators
(`chord_tones`, `chord_pad`, melody helpers, …) — they can't tell a tuning-mapped
root from a literal MIDI number. A worked I–V–I cadence in 19-EDO lives in
`tests/unit/tuning/test_authoring_example.py` (`author_cadence`) — read it as the
template for a microtonal song's `build.py` compose step.

The microtonal composer thinks in raw step indices (no non-12 note-name spelling
in v1 — the accepted "lesser experience" for this niche). Everything downstream —
the DB, events, the push — is identical to a 12-TET song.

## The cached `.ascl` and the push re-load instruction

When a song carries a tuning, Hallucinote stores two things on the song row:
`tuning_ref` (a song-relative path to a reconstructed `.ascl` under
`songs/<slug>/tunings/`) and `tuning_data` (the derived blob the mapper and the
`.ascl` writer read). The cached `.ascl` is a faithful **reconstruction** of the
tuning's interval structure — sonically identical and re-draggable — not the
byte-original (the LOM exposes no source path).

**The push cannot load a tuning** (Live's LOM tuning surface is read-only). So
`push_cli execute` emits, before the phase loop, a one-line instruction:

> tuning: song `<slug>` is in a non-12 tuning — load its `tunings/<file>.ascl`
> (under the song directory) into Live's Tuning section before playback.

It also **re-reads** what's loaded in Live and warns (non-blocking) if it drifted
from what the song stored — nothing loaded at all (playback would be a wrong
12-TET), or a *different* tuning loaded (name/period mismatch). It never blocks the
push; it's a reminder so you don't render against the wrong tuning. *(The
loaded-tuning comparison is currently name + period only — a coarse but real drift
signal; see Limitations.)*

## The lens caveat (honest review)

The symbolic melody and recurrence lenses (`/compose-review`) read intervals as
MIDI-step counts and label them in semitones ("step vs leap", "ambitus N
semitones", "transposed up a 3rd"). For a non-12 song those readings are
**12-TET-relative**, not scale-aware. The lenses don't become tuning-aware in v1
(full step-aware lenses are a later axis), so instead their output carries a
one-line caveat naming the tuning file, so you read the numbers as relative shape
rather than scale-degree distances.

## Limitations (v1, honest)

- **Acquisition is pull-from-Live only** — you load the tuning in Live; there's no
  supply-a-`.ascl`-path ingest and no `.ascl` *parser* (Hallucinote only ever
  *writes* `.ascl`). **The pull-from-Live read of a *loaded* tuning is not wired
  yet** — it's a clearly-marked stub pending a one-time API-shape capture against a
  real loaded tuning (`verify-api`, see
  `.prawduct/artifacts/plans/MICROTUNE/api-notes-tuning.md`). Until then you supply
  the derived `tuning_data`/`.ascl` via the tuning model directly (as the worked
  example does); the authoring, cache, push instruction, and lens caveat all work
  now.
- **The reconstruction preserves interval structure, not the absolute pitch
  anchor** — the cached `.ascl` reproduces the tuning's character; Live auto-assigns
  the reference pitch (no reference-frequency field in v1).
- **No tuning-aware review lenses, no non-12 note-name spelling, no fractional-pitch
  storage** — notes are integer MIDI; the tuning does the reinterpretation.
- **Push instructs + warns, never loads or sets a tuning** — the manual drag stays.

## Where the code lives

- `hallucinote/tuning/` — the isolated bolt-on (`mapper`, `ascl` writer, `cache`,
  `read` (loaded-tuning extraction stubbed), `store`, `model`). The core path
  imports none of it (grep-asserted by `tests/unit/tuning/test_isolation.py`).
- `hallucinote/tools/tuning_caveat.py` — the gated lens caveat (core side).
- `hallucinote/sync/push/tuning_notice.py` — the gated push instruction + drift-warn
  (core side).
- Design + decisions: `.prawduct/artifacts/alternate-tunings.md`.
