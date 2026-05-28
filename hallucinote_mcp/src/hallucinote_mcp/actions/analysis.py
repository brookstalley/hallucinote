"""``ableton_analysis`` action schemas.

Companion to ``ableton_render``. ``ableton_render`` produces the
``captures/<ts>/`` directory of WAVs + ``manifest.json``;
``ableton_analysis`` consumes that to produce a ``MixReport`` JSON at
``songs/<slug>/analysis/<ts>.json``.

Two surfaces:

  - ``analyze`` — read a captures dir, run the three MVP analyses
    (per-stem loudness, master-bus contribution attribution, declared-
    send reverb verification), write a MixReport JSON, return its path.
  - ``get_latest_report`` — return the most recent MixReport JSON
    contents for a song (and its path) without re-running the analysis.

Both are ``runs_server_side=True`` — analysis touches disk + the song
DB only, never the Live API. Mirrors ``ableton_annotation``'s shape.
"""
from __future__ import annotations

from ..handlers import analysis as analysis_handlers
from ..schema import Action, ParamSpec, register


register(
    Action(
        tool="ableton_analysis",
        name="help",
        description=(
            "List all actions on ableton_analysis, with required/optional "
            "params, examples, and tips."
        ),
        example="ableton_analysis(action='help')",
    )
)


register(
    Action(
        tool="ableton_analysis",
        name="analyze",
        description=(
            "Run the audio-analysis MVP pipeline against a captures dir. "
            "Reads captures/<ts>/manifest.json + WAVs produced by "
            "ableton_render(render), measures per-stem loudness (LUFS-I/S/M "
            "+ true peak), detects master-bus overshoots and attributes "
            "each to top contributors per band, and runs reverb verification "
            "for any declared dry->wet sends. Writes the MixReport to "
            "songs/<slug>/analysis/<ts>.json and returns the path + summary."
        ),
        params=(
            ParamSpec(
                name="song_slug",
                type="str",
                description=(
                    "Hallucinote song slug. Drives the captures lookup "
                    "(songs/<slug>/captures/) when captures_dir is not "
                    "supplied, and the analysis output path "
                    "(songs/<slug>/analysis/)."
                ),
            ),
            ParamSpec(
                name="captures_dir",
                type="str",
                required=False,
                description=(
                    "Absolute path to a captures directory containing a "
                    "manifest.json + WAVs. Default: the most recent dir "
                    "under songs/<slug>/captures/ (ISO-8601 names sort "
                    "lexicographically, so 'most recent' = max())."
                ),
            ),
        ),
        handler=analysis_handlers.analyze_handler,
        runs_server_side=True,
        example=(
            "ableton_analysis(action='analyze', song_slug='reggae-metal')"
        ),
        tips=(
            "Returns {report_path, schema_version, finding_count, "
            "summary}. The summary names the master peak true-peak, the "
            "overshoot count, and any out-of-tolerance reverb sends — "
            "enough for the LLM to decide whether to read the full "
            "JSON.",
            "The MVP DB has no schema for declared RT60 sends yet; the "
            "report's reverb_verifications list will be empty and "
            "skipped_analyses will explain why. Section-windowed "
            "analysis + compare_to baseline diffs are post-MVP backlog.",
        ),
    )
)


register(
    Action(
        tool="ableton_analysis",
        name="get_latest_report",
        description=(
            "Return the most recent MixReport JSON for a song without "
            "re-running analysis. Resolves songs/<slug>/analysis/ to "
            "find the latest ISO-8601-named JSON and returns its parsed "
            "contents alongside its path."
        ),
        params=(
            ParamSpec(
                name="song_slug",
                type="str",
                description=(
                    "Hallucinote song slug — directs the lookup at "
                    "songs/<slug>/analysis/."
                ),
            ),
        ),
        handler=analysis_handlers.get_latest_report_handler,
        runs_server_side=True,
        example=(
            "ableton_analysis(action='get_latest_report', "
            "song_slug='reggae-metal')"
        ),
        tips=(
            "Returns {report_path, report} where report is the parsed "
            "MixReport dict — same shape that analyze produces.",
        ),
    )
)
