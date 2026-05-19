"""MCP prompts — 5 workflow templates that orchestrate multi-step
tool sequences for common Ableton authoring patterns.

Prompts differ structurally from tools and resources:
  - **Tools**: imperative, one call per turn.
  - **Resources**: addressable content, read implicitly without a turn.
  - **Prompts**: invokable templates that return *messages* — typically
    user-role instructions guiding the agent through a multi-call
    sequence. The agent then executes the calls itself.

Wave M-7 ships 5 prompts:

  - ``create_midi_track_with_instrument`` — create + name + optional
    instrument load (2 tool calls)
  - ``setup_sidechain_compression`` — ensure Compressor + set sidechain
  - ``build_return_bus`` — create return + load effect + optionally
    initialize sends from a list of source tracks
  - ``humanize_clip_velocity`` — instructions for the agent on how to
    perform a humanization pass given the MCP gap #4 limitation
  - ``compose_section_pattern`` — generate a named pattern (trip-hop,
    tresillo, bossa, ...) into a clip

Carry-forward principle #9 (M-6 pattern): prompts live in their own
module, registered via ``register_prompts(mcp)`` called from
``server.create_server``. The same lock-the-surface negative-test
pattern (#3) applies — ``PROMPT_NAMES`` enumerates the canonical
5; tests assert the exact set is registered.

Per principle #1 (DB-as-source-of-truth), prompts that involve
note-timing or note-velocity transforms (humanize, compose) instruct
the agent to compute the note array in Hallucinote-space and push via
``ableton_clip(action='replace_notes', ...)`` — the MCP server itself
exposes no quantize/swing/groove/humanize actions. The prompts are
honest about this: they describe the workflow that the agent should
follow, including any Hallucinote-side computation.
"""
from __future__ import annotations

from typing import Any


# Canonical prompt name list — locked by test.
PROMPT_NAMES: tuple[str, ...] = (
    "create_midi_track_with_instrument",
    "setup_sidechain_compression",
    "build_return_bus",
    "humanize_clip_velocity",
    "compose_section_pattern",
    # W9-C: scaffold-then-compose orchestration for new songs.
    "start_new_song",
)


# Message shape FastMCP accepts: {role: "user"|"assistant", content: str | dict}.
# We always emit role="user" — the prompt is instructions FROM the user TO the
# agent. Content is text (one instruction blob per message); multi-step
# workflows use one message because chunking doesn't add value here.
_Msg = dict[str, Any]


def _msg(text: str) -> _Msg:
    return {"role": "user", "content": text}


# ---------------------------------------------------------------------------
# Workflow templates
# ---------------------------------------------------------------------------


def _create_midi_track_with_instrument(
    name: str,
    instrument_uri: str,
    index: int | None = None,
    initial_volume: float | None = None,
) -> list[_Msg]:
    """Create a MIDI track + load an instrument + (optional) initial volume."""
    steps: list[str] = [
        f"1. Create the track: `ableton_track(action='create', kind='midi', "
        f"name={name!r}"
        + (f", index={index}" if index is not None else "")
        + ")`.\n"
        "   Capture the returned `track_index`.",
        f"2. Load the instrument onto the new track: "
        f"`ableton_device(action='load', track_index=<from step 1>, "
        f"kind=<Live device class name>, preset_uri={instrument_uri!r})`. "
        "`kind` is REQUIRED — look up the Live class name for this preset "
        "via `ableton://reference/device-params` (common: 'Operator', "
        "'Wavetable', 'Simpler', 'DrumGroupDevice'). The URI's browser "
        "path is NOT a substitute — Live won't infer the class.",
    ]
    if initial_volume is not None:
        steps.append(
            f"3. Set initial volume: `ableton_track(action='set_property', "
            f"track_index=<from step 1>, property='volume', "
            f"value={initial_volume})`."
        )
    return [_msg(
        f"Workflow: create a MIDI track named {name!r} with the instrument "
        f"at {instrument_uri!r}"
        + (f" placed at chain index {index}" if index else "")
        + (f", initial volume {initial_volume}" if initial_volume is not None else "")
        + ".\n\nSteps:\n\n" + "\n\n".join(steps)
    )]


def _setup_sidechain_compression(
    target_track: int,
    source_track: int,
    compressor_uri: str | None = None,
) -> list[_Msg]:
    """Place a Compressor on target_track and route its sidechain from source_track."""
    text = (
        f"Workflow: set up sidechain compression on track {target_track} "
        f"with the trigger coming from track {source_track}.\n\n"
        f"Steps:\n\n"
        f"1. List devices on the target track to see if a Compressor is "
        f"already present: `ableton_device(action='list', "
        f"track_index={target_track})`. Look for `class_name='Compressor2'`.\n\n"
        f"2. If no Compressor: load one. "
        f"`ableton_device(action='load', track_index={target_track}, "
        f"kind='Compressor2'"
        + (f", preset_uri={compressor_uri!r}" if compressor_uri else "")
        + ")` — capture the returned `device_index`.\n   "
        + ("If a Compressor IS present at index N, use that device_index "
           "instead of loading a new one.")
        + "\n\n"
        f"3. Look up source track {source_track}'s display name via "
        f"`ableton_track(action='list')` — the W6-E `set_sidechain` "
        f"surface addresses routing by display_name (e.g. '1-Drums', "
        f"'A-Reverb', 'Main'), not by index. The 1-based track index "
        f"is for tool addressing; the display_name is what Live's "
        f"routing dropdown shows.\n\n"
        f"4. Configure sidechain routing: "
        f"`ableton_device(action='set_sidechain', track_index={target_track}, "
        f"device_index=<from step 2>, enabled=True, "
        f"source_display_name='<name from step 3>', gain_db=0.0)`. The "
        f"call uses capability probing — it works on any device with the "
        f"canonical `S/C On` parameter (Compressor / Compressor2 / Glue "
        f"Compressor / Gate / Multiband Dynamics + third-party plugins "
        f"with the same naming pattern). If source routing fails on a "
        f"device that doesn't expose `input_routing_*` (Glue / Gate / "
        f"Multiband — the teaching error names the constraint), use "
        f"`ableton_device(action='capabilities', ...)` to confirm and "
        f"fall back to manual UI routing.\n\n"
        f"5. (Optional) Tune the compressor parameters via "
        f"`ableton_device(action='set_parameter', ...)`. Common starting "
        f"point for a kick-triggered duck on a synth bus: Threshold=-24, "
        f"Ratio=4, Attack=1ms, Release=120ms. See "
        f"`ableton://reference/device-params` for the canonical names."
    )
    return [_msg(text)]


def _build_return_bus(
    name: str,
    effect_uri: str,
    initial_sends_from: list[int] | None = None,
) -> list[_Msg]:
    """Create a return track + load an effect + optionally initialize sends."""
    steps = [
        f"1. Create the return: `ableton_return(action='create', name={name!r})`. "
        "Capture the returned `return_index`.",
        f"2. Load the effect on the new return: "
        f"`ableton_device(action='load', return_index=<from step 1>, "
        f"kind=<Live device class name>, preset_uri={effect_uri!r})`. "
        "`kind` is REQUIRED — look up the Live class name via "
        "`ableton://reference/device-params` (common: 'Reverb', 'Delay', "
        "'EchoDelay', 'Compressor2').",
    ]
    if initial_sends_from:
        send_calls = ", ".join(str(t) for t in initial_sends_from)
        steps.append(
            f"3. Initialize sends from source tracks {send_calls} → the new "
            f"return at a moderate level (default 0.4): for each source "
            f"track_index in [{send_calls}], call "
            f"`ableton_track(action='set_send', track_index=<src>, "
            f"return_index=<from step 1>, value=0.4)`."
        )
    return [_msg(
        f"Workflow: build a new return bus named {name!r} with the effect at "
        f"{effect_uri!r}"
        + (f" and initial sends from tracks {initial_sends_from}" if initial_sends_from else "")
        + ".\n\nSteps:\n\n" + "\n\n".join(steps)
    )]


def _humanize_clip_velocity(
    track_index: int,
    clip_index: int,
    jitter_percent: float | None = None,
) -> list[_Msg]:
    """Humanize clip-note velocities — honest about the MCP gap #4 limitation."""
    jitter = jitter_percent if jitter_percent is not None else 10.0
    text = (
        f"Workflow: humanize the velocities of clip {clip_index} on track "
        f"{track_index} by ±{jitter}% jitter.\n\n"
        "**Important — MCP gap #4**: this server cannot READ a clip's "
        "notes (no per-note IDs from Live's API yet — see "
        "`ableton://guides/gaps`). Humanization is a Hallucinote-side "
        "compute that requires the source notes from your DB (or "
        "regeneration from a generator). The MCP can only WRITE the "
        "result via `ableton_clip(action='replace_notes', ...)`.\n\n"
        "Steps:\n\n"
        f"1. Source the canonical note array for this clip from "
        f"Hallucinote DB (preferred) OR regenerate from your generator. "
        f"You need the full array — partial updates are not possible.\n\n"
        f"2. Apply a per-note velocity jitter in Python/SQL space. "
        f"`jitter_percent={jitter}` means the jitter range is "
        f"±({jitter}/100)*127 ≈ ±{round((jitter / 100.0) * 127, 1)} velocity "
        f"units (MIDI velocity is 1-127). Pseudocode:\n"
        f"   `for note in notes:`\n"
        f"   `    delta = uniform(-1.0, 1.0) * ({jitter} / 100.0) * 127`\n"
        f"   `    note['velocity'] = clamp(note['velocity'] + delta, 1, 127)`\n"
        "   (Decide whether to floor at the original velocity vs symmetric "
        "around it based on your project's musical taste.)\n\n"
        f"3. Push the result: "
        f"`ableton_clip(action='replace_notes', track_index={track_index}, "
        f"location='session', clip_index={clip_index}, notes=<jittered array>)`. "
        "Remember: this REPLACES the entire note array — any manual edits "
        "since the canonical version are lost."
    )
    return [_msg(text)]


_PATTERN_KINDS = (
    "trip-hop", "tresillo", "bossa", "swing-8ths", "straight-16ths",
    "shuffle", "boom-bap",
)


def _compose_section_pattern(
    track_index: int,
    pattern_kind: str,
    bars: int,
    start_bar: int,
) -> list[_Msg]:
    """Generate notes for a named rhythmic pattern + place in the arrangement."""
    if pattern_kind not in _PATTERN_KINDS:
        # The prompt-time guard returns a teaching message rather than
        # raising — FastMCP wraps prompt exceptions but a friendly
        # "use one of these" is more useful than a stack trace.
        return [_msg(
            f"`pattern_kind={pattern_kind!r}` is not a recognized pattern. "
            f"Choose one of: {list(_PATTERN_KINDS)}, OR generate the notes "
            "directly via your own pattern library and skip this prompt."
        )]
    # Pre-compute the bar→beats value so the call expression in the
    # rendered template contains a literal float, not a comment-suffixed
    # expression that would be invalid Python if an agent copy-pastes.
    # The 4/4 assumption caveat lives in adjacent prose, not inside the call.
    start_beats_value = (start_bar - 1) * 4
    text = (
        f"Workflow: compose a {bars}-bar {pattern_kind} pattern on track "
        f"{track_index}, placed at bar {start_bar} in the arrangement.\n\n"
        "Steps:\n\n"
        f"1. Generate the note array for the {pattern_kind} pattern in "
        "Hallucinote-space (your generator library OR write the array "
        "directly based on the pattern's known shape). Length should be "
        f"{bars} bars; each note dict needs "
        "`{pitch, start_time (beats), duration (beats), velocity}`. "
        "For drum patterns, use the General MIDI drum map (kick=36, "
        "snare=38, closed-hat=42, open-hat=46) or a project-specific map.\n\n"
        f"2. Create the arrangement clip with the notes in one call: "
        f"`ableton_clip(action='create', track_index={track_index}, "
        f"location='arrangement', kind='midi', "
        f"start_beats={start_beats_value}.0, length={bars * 4}.0, "
        f"notes=<from step 1>)`. "
        f"(start_beats={start_beats_value}.0 assumes 4/4 — for other "
        "meters, convert bar→beats via the song's time-signature map "
        "before the call.) The atomic create-and-populate avoids the "
        "two-call create-then-replace pattern.\n\n"
        f"3. (Optional) name the clip: "
        f"`ableton_clip(action='rename', track_index={track_index}, "
        f"location='arrangement', clip_index=<from step 2>, "
        f"name={pattern_kind!r})`."
    )
    return [_msg(text)]


def _start_new_song(
    slug: str,
    title: str,
    tempo: float,
    signature: str = "4/4",
    sections: str = "intro,verse,chorus,outro",
    key: str | None = None,
    intent_hint: str | None = None,
) -> list[_Msg]:
    """W9-C: scaffold-then-compose orchestration for new songs.

    Returns user-role instructions guiding the agent through:
      1. Run the `/new-song` skill to scaffold the directory.
      2. Confirm shape tests pass.
      3. Author the compose-half (clips + arrangement) directly in
         the generated build.py, optionally with intent_hint as
         the seed for the LLM-driven composition.
      4. Push to Live with `--auto-session` (W9-B) for first push.

    The prompt is honest about the scaffold being a starting point —
    the synthetic snapshot is a placeholder until the user stages
    Live and captures.
    """
    key_clause = f" in key {key}" if key else ""
    intent_clause = (
        f"\n\nComposer intent: {intent_hint}" if intent_hint else ""
    )
    sections_csv = sections.replace(" ", "")
    text = (
        f"Workflow: scaffold a new Hallucinote song {slug!r} (titled "
        f"{title!r}, tempo {tempo}, signature {signature}{key_clause}) "
        f"with sections [{sections_csv}], then compose its first pass."
        f"{intent_clause}\n\n"
        f"Steps:\n\n"
        f"1. **Scaffold** the song directory by invoking the `/new-song` "
        f"skill — pass slug={slug!r}, title={title!r}, tempo={tempo}, "
        f"signature={signature!r}, sections={sections_csv!r}"
        + (f", key={key!r}" if key else "")
        + (f", intent={intent_hint!r}" if intent_hint else "")
        + ". The skill runs `tools.scaffold_song` and creates "
        f"`songs/{slug}/` with build.py (state-converger, W12-A), "
        f"captured_session.json (synthetic 4 MIDI + 2 returns), tests, "
        f"and decision/annotation directories.\n\n"
        f"2. **Confirm scaffold**: run `python3 songs/{slug}/build.py "
        f"--reset` and `pytest songs/{slug}/tests/ -v`. Both should pass "
        f"on first run.\n\n"
        f"3. **Compose**: open `songs/{slug}/build.py` and replace the "
        f"`=== Compose-half ===` placeholder with your musical authoring. "
        f"For each section: pick clips, generate or hand-author notes, "
        f"call `M.create_clip` + `M.replace_clip_notes`, then "
        f"`M.add_arrangement_clip` to place them. Generators in "
        f"`hallucinote.generators.*` are 4/4-only today (Wave 0 finding "
        f"H2); for non-4/4 songs hand-author until W14-B parametrizes "
        f"them.\n\n"
        f"4. **Iterate**: re-run `python3 songs/{slug}/build.py` "
        f"(no --reset) after each edit. W12-A guarantees re-runs are "
        f"no-ops if nothing changed — events only emit for real diffs. "
        f"Re-run tests as you go.\n\n"
        f"5. **Push to Live** when you're ready: ask the user to stage "
        f"Live (open a new set or one matching the synthetic snapshot's "
        f"shape), then run `/ableton-push {slug} --new-session` — the "
        f"W9-B `--auto-session` path bootstraps the binding row on "
        f"first push. Tell the user the new session_id so they can "
        f"reuse it for subsequent pushes.\n\n"
        f"6. **Capture for real**: once Live is populated with the "
        f"target shape, run `tools/capture.py` to overwrite the "
        f"synthetic `captured_session.json` with the real Live state. "
        f"Re-run build to converge.\n\n"
        f"Stop at any step if a prerequisite fails — surface the error "
        f"to the user rather than guessing past it."
    )
    return [_msg(text)]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_prompts(mcp: Any) -> None:
    """Wire all 5 workflow prompts onto a FastMCP instance.

    Called once at server boot from ``server.create_server``. Each
    prompt is a function whose signature defines the prompt arguments;
    FastMCP introspects the signature to build the argument schema for
    the MCP client.
    """
    mcp.prompt(
        name="create_midi_track_with_instrument",
        description=(
            "Create a MIDI track named X with the instrument at "
            "instrument_uri loaded onto it. Optional index controls chain "
            "position; optional initial_volume sets the mixer slider."
        ),
    )(_create_midi_track_with_instrument)

    mcp.prompt(
        name="setup_sidechain_compression",
        description=(
            "Configure sidechain compression: place (or reuse) a Compressor "
            "on target_track and route its sidechain input from source_track."
        ),
    )(_setup_sidechain_compression)

    mcp.prompt(
        name="build_return_bus",
        description=(
            "Create a new return track named X with an effect (reverb / "
            "delay / etc) loaded, optionally initializing sends from a list "
            "of source tracks at a moderate level."
        ),
    )(_build_return_bus)

    mcp.prompt(
        name="humanize_clip_velocity",
        description=(
            "Humanize the velocities of a clip's notes by a jitter "
            "percentage. Note: cannot READ notes (gap #4); requires "
            "Hallucinote-side source notes + push via replace_notes."
        ),
    )(_humanize_clip_velocity)

    mcp.prompt(
        name="compose_section_pattern",
        description=(
            "Generate a named rhythmic pattern (trip-hop / tresillo / bossa "
            "/ swing-8ths / straight-16ths / shuffle / boom-bap) into an "
            "arrangement clip on the given track at the given start bar."
        ),
    )(_compose_section_pattern)

    mcp.prompt(
        name="start_new_song",
        description=(
            "Scaffold a new Hallucinote song from templates (via /new-song), "
            "verify the scaffold builds + tests pass, then guide the agent "
            "through composing the first pass and pushing to Live with "
            "--auto-session bootstrap."
        ),
    )(_start_new_song)


__all__ = ["PROMPT_NAMES", "register_prompts"]
