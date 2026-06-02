"""``ableton_render`` action schema.

Two actions:

  - ``ensure_loaded`` — idempotent silent sweep that places a
    HallucinoteAnalyzer on every audio track + return + master.
    Wired into ``/song-new``, ``/track-new-with-instrument``, and
    ``/return-new`` skill postludes so analyzer placement keeps up
    with structural changes silently.

  - ``render`` — full end-to-end capture pass: ensure → deliver
    paths + windows over OSC → arm → play → wait → stop → write
    manifest. Produces one WAV per surface plus ``manifest.json``
    in the captures directory.

Both actions live behind one tool because they share lifecycle:
``render`` always calls ``ensure_loaded`` in its preamble, and the
``ensure_loaded`` surface gives callers a side door for "place the
analyzers without rendering yet" workflows (e.g. a `/song-new`
postlude that runs before any composition exists).
"""
from __future__ import annotations

from ..handlers import render as render_handlers
from ..schema import Action, ParamSpec, register


register(
    Action(
        tool="ableton_render",
        name="help",
        description=(
            "List all actions on ableton_render, with required/optional "
            "params, examples, and tips."
        ),
        example="ableton_render(action='help')",
    )
)


register(
    Action(
        tool="ableton_render",
        name="ensure_loaded",
        description=(
            "Idempotent silent sweep — place a HallucinoteAnalyzer on every "
            "audio track + return + master where it's missing. Detection "
            "requires both class_display_name='Max Audio Effect' (every "
            "M4L audio-effect shares this class) AND name='HallucinoteAnalyzer' "
            "(our specific .amxd identity); existing instances are recorded "
            "but not duplicated. Returns the per-surface layout "
            "(track_id + OSC port + device_index)."
        ),
        handler=render_handlers.ensure_loaded_handler,
        runs_on_worker=True,
        example="ableton_render(action='ensure_loaded')",
        tips=(
            "Wired into /song-new, /track-new-with-instrument, and "
            "/return-new skill postludes so structural mutations don't "
            "leave the analyzer placement stale.",
            "Running twice produces an identical layout — port "
            "assignment is a pure function of the surface address.",
        ),
    )
)


register(
    Action(
        tool="ableton_render",
        name="render",
        description=(
            "End-to-end capture pass. Ensure analyzers are present, deliver "
            "per-instance WAV paths + transport-position windows via OSC, "
            "arm, play the arrangement, record a reverb ring-out past the "
            "arrangement end (ring_out_beats), stop, disarm, and write the "
            "captures manifest. Produces one WAV per surface plus "
            "manifest.json in the captures directory."
        ),
        params=(
            ParamSpec(
                name="song_slug",
                type="str",
                description=(
                    "Hallucinote song slug. Drives the default output_dir "
                    "(songs/<slug>/captures/<iso-timestamp>/). Required — "
                    "captures live next to the song they belong to."
                ),
            ),
            ParamSpec(
                name="output_dir",
                type="str",
                required=False,
                description=(
                    "Where to write WAVs + manifest.json. Created if it "
                    "doesn't exist. Overrides the slug-derived default."
                ),
            ),
            ParamSpec(
                name="start_at_beat",
                type="int",
                required=False,
                minimum=0,
                description=(
                    "Beat at which recording should start (0-based, "
                    "matches Live's beat counter). Default 0 — the "
                    "arrangement's start."
                ),
            ),
            ParamSpec(
                name="stop_at_beat",
                type="int",
                required=False,
                minimum=1,
                description=(
                    "Beat at which recording should stop. Default: the "
                    "arrangement's last_event_time (full song)."
                ),
            ),
            ParamSpec(
                name="ring_out_beats",
                type="float",
                required=False,
                minimum=0.0,
                description=(
                    "Beats of reverb RING-OUT to record AFTER stop_at_beat. "
                    "The dry arrangement stops at stop_at_beat; recording "
                    "continues this many beats more while the returns decay "
                    "into silence, so reverb RT60 is measurable from the "
                    "captured tail (ableton_analysis verifies it per return). "
                    "Default 8. Raise it for a long (3 s+) hall, especially "
                    "at a fast session tempo — analysis degrades to an honest "
                    "'insufficient ring-out, re-render with more' skip if too "
                    "short. 0 skips the ring-out (no reverb to verify)."
                ),
            ),
            ParamSpec(
                name="post_roll_beats",
                type="float",
                required=False,
                minimum=0.0,
                description=(
                    "Extra beats to let transport run past the recording "
                    "stop (stop_at_beat + ring_out_beats) before issuing "
                    "Live's stop. Gives the patch's beat observer time to "
                    "fire sfrecord~'s stop+finalize. Default 4 (one bar at "
                    "4/4)."
                ),
            ),
            ParamSpec(
                name="pre_roll_beats",
                type="float",
                required=False,
                minimum=0.0,
                description=(
                    "Beats BEFORE start_at_beat to seek-then-play from, "
                    "so the patch's transport-cross detector sees a real "
                    "edge (prev < threshold then curr >= threshold) "
                    "instead of starting at the threshold. The pre-roll "
                    "audio is NOT in the captured WAV — sfrecord~ only "
                    "starts when transport crosses start_at_beat. "
                    "Default 4 (one bar at 4/4), symmetric to post_roll."
                ),
            ),
        ),
        handler=render_handlers.render_handler,
        runs_on_worker=True,
        example=(
            "ableton_render(action='render', song_slug='falling-walking')"
        ),
        tips=(
            "Per analyzer instance: WAV path + track_id + start/stop "
            "beats are delivered out-of-band via OSC (Live params can't "
            "carry strings); Arm is the gate (Live param), the patch's "
            "beat observer is the boundary. See "
            "m4l/HallucinoteAnalyzer.amxd.spec.md.",
            "Returns {captures_dir, manifest_path, manifest, status}. "
            "status='ok' on clean exit, 'incomplete' if transport "
            "didn't reach stop_at_beat within the wait window (Live's "
            "audio thread may have stalled; the partial WAVs are still "
            "on disk).",
        ),
    )
)
