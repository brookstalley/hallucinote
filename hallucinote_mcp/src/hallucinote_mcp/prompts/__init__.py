"""MCP prompts — workflow templates that orchestrate multi-step
tool sequences for common Ableton authoring patterns.

Prompts differ structurally from tools and resources:
  - **Tools**: imperative, one call per turn.
  - **Resources**: addressable content, read implicitly without a turn.
  - **Prompts**: invokable templates that return *messages* — typically
    user-role instructions guiding the agent through a multi-call
    sequence. The agent then executes the calls itself.

Current set (canonical names locked in ``PROMPT_NAMES``):

Wave M-7 (5):
  - ``create_midi_track_with_instrument`` — create + name + optional
    instrument load (2 tool calls)
  - ``setup_sidechain_compression`` — ensure Compressor + set sidechain
  - ``build_return_bus`` — create return + load effect + optionally
    initialize sends from a list of source tracks
  - ``humanize_clip_velocity`` — instructions for the agent on how to
    perform a humanization pass given the MCP gap #4 limitation
  - ``compose_section_pattern`` — generate a named pattern (trip-hop,
    tresillo, bossa, ...) into a clip

Wave 9 (1):
  - ``start_new_song`` — scaffold-then-compose orchestration: drives
    /new-song to scaffold the song dir, then guides composition + the
    first push with --auto-session bootstrap (W9-C).

Wave 14 (1):
  - ``pick_instruments_for_song`` — browser-driven instrument picker
    with portability modes (strict / relaxed / unrestricted). Tells the
    agent how to filter against ``ableton://browser/instruments`` and
    ``ableton://plugins/installed``, suggest a fit per track, and load
    via ``ableton_device(action='load')`` (W14-A).

Carry-forward principle #9 (M-6 pattern): prompts live in their own
module, registered via ``register_prompts(mcp)`` called from
``server.create_server``. The same lock-the-surface negative-test
pattern (#3) applies — ``PROMPT_NAMES`` enumerates the canonical
set; tests assert the exact set is registered.

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
    # W14-A: browser-driven instrument picker with portability modes.
    "pick_instruments_for_song",
)


# Portability modes for pick_instruments_for_song. Strict = stock Live
# devices only (guarantees round-trip on any Live install with the same
# edition); relaxed = stock + common third-party (collaborators may need
# to install a few well-known plugins); unrestricted = anything installed
# (W13-B's REQUIREMENTS.md emerges on the consumer side).
_PORTABILITY_MODES: tuple[str, ...] = ("strict", "relaxed", "unrestricted")


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
        f"2b. **Pick instruments** (W14-A): invoke the "
        f"`pick_instruments_for_song` prompt to browse "
        f"`ableton://browser/instruments` (and "
        f"`ableton://plugins/installed` if you go past `strict`) and "
        f"suggest a fit per track. Default to `portability='strict'` "
        f"unless the user signals tolerance for third-party plugins or "
        f"the style hint demands something the stock devices can't "
        f"reach. Confirm picks with the user, then load them via "
        f"`ableton_device(action='load', ...)` after the first push "
        f"(step 5) so the loaded instrument lives on the real Live "
        f"track. Re-run `tools/capture.py` so the picks land in "
        f"`captured_session.json`.\n\n"
        f"3. **Compose**: open `songs/{slug}/build.py` and replace the "
        f"`=== Compose-half ===` placeholder with your musical authoring. "
        f"For each section: pick clips, generate or hand-author notes, "
        f"call `M.create_clip` + `M.replace_clip_notes`, then "
        f"`M.add_arrangement_clip` to place them. Generators in "
        f"`hallucinote.generators.*` accept a `beats_per_bar` kwarg "
        f"(W14-B) so bar iteration scales through non-4/4 sections; "
        f"within-bar layout still assumes a 4/4 shape, so hand-author "
        f"non-4/4 patterns where that matters.\n\n"
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


def _pick_instruments_for_song(
    tracks: str,
    portability: str = "strict",
    style_hint: str | None = None,
) -> list[_Msg]:
    """W14-A: browser-driven instrument picker with portability modes.

    `tracks` is a CSV of track descriptors — names alone ("Drums,Bass,
    Lead,Pads") or name + role ("Drums (kit), Bass (sub), Lead (mono
    saw), Pads (warm)"). The prompt instructs the agent to read the
    browser + plugin resources, filter by portability mode, and
    suggest a fit per track.

    The cross-machine portability story lives in Wave 13: strict mode
    side-steps it (stock devices are everywhere), relaxed mode trusts
    the few well-known third-party plugins, unrestricted mode hands the
    consumer-side problem to W13-B (``compat check`` + REQUIREMENTS.md).
    """
    if portability not in _PORTABILITY_MODES:
        return [_msg(
            f"`portability={portability!r}` is not a recognized mode. "
            f"Choose one of: {list(_PORTABILITY_MODES)}."
        )]

    if portability == "strict":
        mode_clause = (
            "**Strict**: stock Live devices only. Read "
            "`ableton://browser/instruments` — every node there ships "
            "with Live (modulo edition tier: Operator / Analog / "
            "Electric / Tension / Collision / Drift / Meld are Suite-"
            "only; Wavetable / Simpler / Sampler / Drum Rack / Impulse "
            "ship with Standard). Do NOT pull from "
            "`ableton://plugins/installed`. Strict guarantees the "
            "resulting song opens on any Live install of the same "
            "edition with no missing-device errors — the Wave 13 "
            "portability problem is structurally avoided."
        )
    elif portability == "relaxed":
        mode_clause = (
            "**Relaxed**: stock + common third-party. Read "
            "`ableton://browser/instruments` (stock) AND "
            "`ableton://plugins/installed` (third-party). When picking "
            "third-party, prefer well-known names a collaborator "
            "plausibly already owns (e.g. Serum / Massive X / Diva / "
            "Spire / Omnisphere / Kontakt). Avoid niche / boutique "
            "plugins in this mode — those belong in `unrestricted`. "
            "Consumers may still need to install one or two of the "
            "third-party picks; W13-B's `compat check` will flag them."
        )
    else:  # unrestricted
        mode_clause = (
            "**Unrestricted**: anything in `ableton://plugins/installed` "
            "OR `ableton://browser/instruments`. Pick the best musical "
            "fit without portability concern — assume the consumer "
            "side will resolve missing plugins via W13-B's "
            "`python -m hallucinote.sync.compat check <slug>` and the "
            "emitted `songs/<slug>/REQUIREMENTS.md`. Tell the user "
            "explicitly that this song is not strict-portable and that "
            "collaborators will need to install whatever's listed in "
            "REQUIREMENTS before pushing."
        )

    style_clause = (
        f"\n\nStyle hint from the user: {style_hint!r}. Let this steer "
        "tonal choice (e.g. 'warm vintage analog' → Operator FM bells, "
        "Analog subtractive; 'aggressive modern EDM' → Wavetable "
        "saws, Serum-style sounds in relaxed/unrestricted)."
        if style_hint else ""
    )

    tracks_clean = tracks.strip()
    text = (
        f"Workflow: pick instruments for the tracks [{tracks_clean}] "
        f"under portability mode `{portability}`.\n\n"
        f"{mode_clause}{style_clause}\n\n"
        f"Steps:\n\n"
        f"1. **Read the catalogue.** Open the resources listed in the "
        f"mode clause above. Each node has fields "
        f"`{{name, uri, is_loadable, is_folder?, children?}}` — `name` "
        f"is Live's browser display name (e.g. 'Operator', 'Drum Rack', "
        f"'Meld', 'EQ Eight'), `uri` is the `query:...` or "
        f"`plugins:...` string passable to "
        f"`ableton_device(action='load', preset_uri=...)`. Filter to "
        f"`is_loadable=true` leaves only the pickable nodes.\n\n"
        f"2. **Match per track.** For each of [{tracks_clean}], propose "
        f"ONE primary pick + 1-2 alternates. Each pick records: track "
        f"name, suggested instrument display name (from the node's "
        f"`name`), `preset_uri`, and a one-sentence rationale (why "
        f"this fits this track's role). Drum tracks should pick Drum "
        f"Rack (display name 'Drum Rack', class `DrumGroupDevice`) or "
        f"Impulse (display + class both 'Impulse') — single-pitch "
        f"synths don't make sense for a kit.\n\n"
        f"3. **Confirm with the user.** Present the picks as a compact "
        f"table (track / pick / rationale). Wait for OK or "
        f"substitutions before loading anything. The user may steer "
        f"individual picks (\"use Wavetable instead of Analog for "
        f"Lead\"); honour the steer and re-confirm.\n\n"
        f"4. **Load instruments.** For each confirmed pick, either:\n"
        f"   - Use the `create_midi_track_with_instrument` prompt "
        f"(creates the track + loads the instrument in one workflow), "
        f"OR\n"
        f"   - If the tracks already exist, call "
        f"`ableton_device(action='load', track_index=<i>, "
        f"kind=<name from step 1>, preset_uri=<uri>)` directly. `kind` "
        f"is REQUIRED — the URI's browser path is NOT a substitute, "
        f"Live won't infer the class. Pass the browser node's `name` "
        f"as `kind`; the handler resolves display names "
        f"('Drum Rack' → `DrumGroupDevice`, 'EQ Eight' → `Eq8`, "
        f"'Wavetable' → `InstrumentVector`, etc.) via the project's "
        f"`device_names.class_name_to_display` translation table. "
        f"Third-party plugins use the same string in both spaces.\n\n"
        f"5. **Capture for the DB.** After loading, run "
        f"`tools/capture.py` (or invoke the `/song-snapshot` skill) so "
        f"the song's `captured_session.json` reflects the picks. The "
        f"instrument's `(class, display_name, manufacturer, pack_name, "
        f"params_dialed)` is what Wave 13-A's fallback-identity path "
        f"will use to re-find the same instrument on another machine."
        + (
            "\n\n6. **Flag the unrestricted scope.** Tell the user the "
            "song is not strict-portable; collaborators will need to "
            "install whatever W13-B's `compat check` flags before "
            "their push."
            if portability == "unrestricted" else ""
        )
    )
    return [_msg(text)]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_prompts(mcp: Any) -> None:
    """Wire all 7 workflow prompts onto a FastMCP instance.

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

    mcp.prompt(
        name="pick_instruments_for_song",
        description=(
            "Browser-driven instrument picker: filter "
            "ableton://browser/instruments and ableton://plugins/installed "
            "by portability mode (strict / relaxed / unrestricted) and "
            "suggest a fit per track. Integrates with start_new_song for "
            "the compose-half. Strict mode side-steps Wave 13 portability "
            "concerns; unrestricted hands the cross-machine problem to "
            "W13-B's compat check + REQUIREMENTS.md."
        ),
    )(_pick_instruments_for_song)


__all__ = ["PROMPT_NAMES", "register_prompts"]
