"""Smoke + tag-correctness tests for generators."""
from __future__ import annotations

from hallucinote.generators import drums, bass, harmony


def _has_tag(notes, tag):
    return [n for n in notes if tag in n.get("tags", [])]


def _well_formed(n):
    return (
        0 <= n["pitch"] <= 127
        and n["start_beats"] >= 0
        and n["duration_beats"] > 0
        and 0 <= n["velocity"] <= 127
    )


def test_kick_stumble_shape():
    notes = drums.kick_stumble(4)
    assert all(_well_formed(n) for n in notes)
    # Two kicks per bar (downbeat + late/early)
    assert len(notes) == 8
    # Strong every 4 -> first bar has the heaviest kick
    first = next(n for n in notes if n["start_beats"] == 0.0)
    assert first["velocity"] == 118
    assert "stumble" in first["tags"]


def test_lazy_snare_lay_back():
    notes = drums.lazy_snare(2)
    backbeats = sorted(n["start_beats"] for n in notes)
    # Each bar has snares at beat 1 + LAZY and beat 3 + LAZY
    assert backbeats == [1.04, 3.04, 5.04, 7.04]


def test_trip_hop_hats_alternation_and_boost():
    notes = drums.trip_hop_hats(4, boost_bars=[3])
    assert all(_well_formed(n) for n in notes)
    boost_ghosts = [n for n in notes if "boost" in n["tags"]]
    # Bar 3 has 4 ghost-offbeats
    assert len(boost_ghosts) == 4
    # All ghost notes are velocity 35 in non-boost bars
    plain_ghosts = [n for n in notes if "ghost" in n["tags"] and "boost" not in n["tags"]]
    assert all(n["velocity"] == 35 for n in plain_ghosts)


def test_trip_hop_pattern_composes():
    notes = drums.trip_hop_drum_pattern(4, fill_bars=[3])
    assert any("kick" in n["tags"] for n in notes)
    assert any("snare" in n["tags"] for n in notes)
    assert any("hat" in n["tags"] for n in notes)
    # Fill bar 3 brings ghost kicks + snares + open-hat lift
    assert _has_tag(notes, "ghost")
    assert _has_tag(notes, "lift")


def test_tresillo_bass_uses_root():
    notes = bass.tresillo_bass(38, bars=2)
    assert len(notes) == 12  # 6 hits per bar
    assert all(n["pitch"] == 38 for n in notes)
    assert all("tresillo_hit" in n["tags"] for n in notes)


def test_walking_bass_first_note_accents():
    notes = bass.walking_bass_to_next_chord(walk=[34, 36, 38, 41], start_beat=0.0)
    assert notes[0]["velocity"] == 100
    assert "downbeat" in notes[0]["tags"]
    assert all("walk" in n["tags"] for n in notes)


def test_chord_pad_stab():
    pad = harmony.chord_pad([53, 57, 62], start_beat=0.0, length_beats=8.0)
    assert len(pad) == 3
    assert all(n["duration_beats"] == 8.0 for n in pad)

    stab = harmony.chord_stab([53, 57, 62], start_beat=14.0)
    assert all(s["start_beats"] == 14.0 for s in stab)
    assert all("stab" in s["tags"] for s in stab)


def test_tresillo_pluck_cycles():
    notes = harmony.tresillo_pluck([62, 65, 69], bars=2)
    assert len(notes) == 12
    # Check pitches cycle through voicing
    pitches_first_bar = [n["pitch"] for n in notes[:6]]
    assert pitches_first_bar[0] == 62 and pitches_first_bar[3] == 62  # i % 3


def test_drum_generators_respect_start_beat():
    """All bar-based drum generators offset their start by `start_beat`."""
    # kick_stumble — shifted bar 0 should land at start_beat.
    notes = drums.kick_stumble(2, start_beat=16.0)
    assert min(n["start_beats"] for n in notes) == 16.0
    # lazy_snare
    notes = drums.lazy_snare(2, start_beat=16.0)
    assert min(n["start_beats"] for n in notes) >= 16.0
    # trip_hop_hats
    notes = drums.trip_hop_hats(1, start_beat=8.0)
    assert min(n["start_beats"] for n in notes) == 8.0
    # bossa_shaker
    notes = drums.bossa_shaker(1, start_beat=12.0)
    assert min(n["start_beats"] for n in notes) == 12.0
    # tresillo_hats
    notes = drums.tresillo_hats(1, start_beat=20.0)
    assert min(n["start_beats"] for n in notes) == 20.0


def test_trip_hop_drum_pattern_respects_start_beat_for_fills():
    """The composer shifts fill_bars by start_beat too — ghosts land at the right bar."""
    notes = drums.trip_hop_drum_pattern(4, start_beat=16.0, fill_bars=[3])
    # Ghost kicks at bar index 3 should now be at beat 16 + 12 = 28, plus 3.5 = 31.5
    ghosts = [n for n in notes if "ghost" in n["tags"] and "kick" in n["tags"]]
    assert any(g["start_beats"] == 31.5 for g in ghosts), \
        f"expected ghost kick at 31.5; got {[g['start_beats'] for g in ghosts]}"


def test_trip_hop_drum_pattern_handles_non_bar_aligned_start_beat():
    """Regression: non-bar-aligned start_beat must not truncate the ghost offsets.

    Before the fix, the composer used `int(start_beat // 4)` to shift fill_bars,
    which silently floored a 0.5-beat anacrusis to a full bar offset.
    """
    # 0.5-beat offset (an eighth-note anacrusis).
    notes = drums.trip_hop_drum_pattern(4, start_beat=0.5, fill_bars=[3])
    kick_ghosts = [n for n in notes
                   if "ghost" in n["tags"] and "kick" in n["tags"]]
    # Ghost kick should land at start_beat + 3*4.0 + 3.5 = 16.0, NOT 15.5
    assert any(g["start_beats"] == 16.0 for g in kick_ghosts), \
        f"expected ghost kick at 16.0 (0.5 + 12 + 3.5); got " \
        f"{[g['start_beats'] for g in kick_ghosts]}"


def test_ghost_drum_helpers_take_start_beat():
    """ghost_kicks / ghost_snares / open_hat_lifts all honor start_beat."""
    kicks = drums.ghost_kicks([0], start_beat=7.0)
    assert kicks[0]["start_beats"] == 7.0 + 3.5  # 10.5
    snares = drums.ghost_snares([0], start_beat=7.0)
    assert snares[0]["start_beats"] == 7.0 + 3.75  # 10.75
    lifts = drums.open_hat_lifts([0], start_beat=7.0)
    assert lifts[0]["start_beats"] == 7.0 + 3.5  # 10.5




# ---------------------------------------------------------------------------
# W14-B: beats_per_bar parameterization (Wave 0 trigger — every generator
# previously hard-coded `b * 4.0`; non-4/4 sections silently produced
# wrong bar starts)
# ---------------------------------------------------------------------------


def test_kick_stumble_default_beats_per_bar_unchanged():
    """W14-B: default beats_per_bar=4.0 preserves the prior 4/4 layout."""
    notes = drums.kick_stumble(2)
    starts = sorted(n["start_beats"] for n in notes)
    # Bar 0 downbeat=0, late=2.75; bar 1 downbeat=4, early=6 (b=1 → b%2==1).
    assert starts == [0.0, 2.75, 4.0, 6.0]


def test_kick_stumble_non_default_beats_per_bar_scales_bar_starts():
    """7/8 bar (3.5 beats) — bar 1's downbeat lands at beat 3.5, not 4.0."""
    notes = drums.kick_stumble(2, beats_per_bar=3.5)
    downbeats = sorted(
        n["start_beats"] for n in notes if "downbeat" in n["tags"]
    )
    assert downbeats == [0.0, 3.5]


def test_lazy_snare_beats_per_bar_scales_bar_starts():
    notes = drums.lazy_snare(2, beats_per_bar=6.0)  # e.g. 6/4
    starts = sorted(n["start_beats"] for n in notes)
    # Bar 0: lay_back snares at 1+lb, 3+lb; bar 1: 6+1+lb, 6+3+lb.
    # Bar 1 backbeat lands at 6+1+lb = 7+lb, not 4+1+lb.
    assert starts[2] > 6.0
    assert starts[2] < 8.0


def test_trip_hop_hats_beats_per_bar_scales_bar_starts():
    notes = drums.trip_hop_hats(2, beats_per_bar=3.0)
    # Each bar emits 8 hats. Bar 0 hat 0 = 0.0; bar 1 hat 0 = 3.0.
    hats_bar1 = [n for n in notes if 3.0 <= n["start_beats"] < 6.0]
    assert hats_bar1, [n["start_beats"] for n in notes]
    # The bar-1 first hat lands at exactly beats_per_bar.
    assert min(n["start_beats"] for n in hats_bar1) == 3.0


def test_bossa_shaker_beats_per_bar_scales_bar_starts():
    notes = drums.bossa_shaker(2, beats_per_bar=2.0)
    # Bar 1's first 16th lands at beat 2.0 (not 4.0).
    bar1_first = min(n["start_beats"] for n in notes if n["start_beats"] >= 2.0)
    assert bar1_first == 2.0


def test_ghost_kicks_beats_per_bar_scales_bar_offset():
    notes = drums.ghost_kicks([0, 1], beats_per_bar=3.5)
    # bar 0 → 0 + 3.5 = 3.5; bar 1 → 3.5 + 3.5 = 7.0.
    starts = sorted(n["start_beats"] for n in notes)
    assert starts == [3.5, 7.0]


def test_tresillo_bass_beats_per_bar_scales_bar_starts():
    """beats_per_bar=6.0 (e.g. 6/4) — TRESILLO_HITS fits well within 6 beats
    so each bar's emitted positions stay disjoint and the bar-1 offset is
    visible directly."""
    notes = bass.tresillo_bass(38, bars=2, beats_per_bar=6.0)
    # Bar 0 hits in [0, 4); bar 1 hits at offset 6 + each TRESILLO_HITS time.
    bar1_min = min(n["start_beats"] for n in notes if n["start_beats"] >= 6.0)
    bar0_max = max(n["start_beats"] for n in notes if n["start_beats"] < 6.0)
    assert bar1_min == 6.0
    assert bar0_max < 6.0


def test_walking_bass_beats_per_bar_scales_bar_starts():
    notes = bass.walking_bass_to_next_chord(
        walk=[34, 36, 38, 41], start_beat=0.0, bar_count=2, beats_per_bar=3.5,
    )
    downbeats = sorted(n["start_beats"] for n in notes if "downbeat" in n["tags"])
    assert downbeats == [0.0, 3.5]


def test_tresillo_pluck_beats_per_bar_scales_bar_starts():
    notes = harmony.tresillo_pluck(
        [62, 65, 69], bars=2, beats_per_bar=3.5,
    )
    # First hit of each bar is at offset 0.0.
    starts = sorted({
        n["start_beats"] for n in notes if n["start_beats"] in (0.0, 3.5)
    })
    assert starts == [0.0, 3.5]


def test_trip_hop_drum_pattern_threads_beats_per_bar_to_subprimitives():
    notes = drums.trip_hop_drum_pattern(
        2, fill_bars=[1], beats_per_bar=3.5,
    )
    # Bar 1's drum downbeats should appear at beat 3.5 not 4.0 — verify
    # via the kick_stumble downbeat tag.
    bar1_kicks = [
        n for n in notes
        if "kick" in n["tags"] and "downbeat" in n["tags"]
        and n["start_beats"] == 3.5
    ]
    assert bar1_kicks, [n["start_beats"] for n in notes if "downbeat" in n["tags"]]


def test_chord_tone_embellishment_takes_no_beats_per_bar():
    """chord_tone_embellishment is a single-bar generator (4/4-shaped);
    documented in its docstring. No beats_per_bar kwarg."""
    import inspect
    sig = inspect.signature(bass.chord_tone_embellishment)
    assert "beats_per_bar" not in sig.parameters
