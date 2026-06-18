"""``ableton_analysis`` action schemas.

Companion to ``ableton_render``. ``ableton_render`` produces the
``captures/<ts>/`` directory of WAVs + ``manifest.json``;
``ableton_analysis`` consumes that to produce a ``MixReport`` JSON at
``songs/<slug>/analysis/<ts>.json``.

Two surfaces:

  - ``analyze`` — read a captures dir, run the analyses (per-stem
    loudness, master-bus contribution attribution, declared-send reverb
    verification, per-section loudness windowing), write a MixReport
    JSON, return its path.
  - ``get_latest_report`` — return the most recent MixReport JSON
    contents for a song (and its path) without re-running the analysis.

Both are ``runs_server_side=True`` — analysis touches disk + the song
DB only, never the Live API.
"""
from __future__ import annotations

from . import analysis as analysis_handlers
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
            "each to top contributors per band, verifies reverb RT60 "
            "per-return from each return's captured ring-out (one result per "
            "return with a declared send, dry-source-free), verifies declared "
            "automation was realized in audio (a device-parameter timbre flip "
            "like Amp Type, a dynamic send level), and scopes per-stem loudness "
            "to each named section (verse / chorus / bridge) declared via "
            "create_section. Pass compare_to=<seq> to diff against a "
            "previous report (per-surface loudness deltas + significance "
            "flags). Writes the MixReport to "
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
            ParamSpec(
                name="compare_to",
                type="int",
                required=False,
                description=(
                    "Song audit-log seq of the baseline: the previous "
                    "analysis JSON whose db_seq matches (captures record "
                    "theirs in manifest.db_seq at render time; each "
                    "report carries it as db_seq). The report's "
                    "compare_to field gets per-surface loudness deltas + "
                    "significance flags vs that baseline — neutral "
                    "evidence for did-the-change-do-what-it-predicted, "
                    "graded against intent by the reader. Errors "
                    "teach the available seqs when nothing matches. "
                    "Caveat: the tag is the DB's latest seq at render "
                    "time — render after pushing, or the audio won't "
                    "reflect the state the seq names."
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
            "summary, analysis_code}. The summary names the master peak "
            "true-peak, the overshoot count, the per-section count, and any "
            "out-of-tolerance reverb returns — enough for the LLM to decide "
            "whether to read the full JSON.",
            "analysis_code = {signature, stale}: the content hash of the "
            "loaded analysis pipeline + whether it differs from disk. "
            "stale=true means this server is running pre-edit code — run "
            "/mcp to respawn before trusting the report.",
            "Declared intent drives three passes: set_send_intended_rt60 "
            "feeds reverb verification, automation envelopes "
            "(create_enum_envelope / volume_swell / dynamic sends) feed "
            "report.automation_verifications (realized-vs-declared per "
            "breakpoint; mixer_volume/pan are verified on the MASTER — "
            "master_rms_db / master_balance_db — with measurable=false only "
            "when the predicted effect is below the detectability floor or "
            "the prediction model breaks down), and create_section feeds "
            "per-section loudness (report.per_section, keyed by section name; a "
            "master_overshoot finding's db_reference names the section it "
            "lands in). When any is undeclared, skipped_analyses "
            "explains how to declare it. Per-section contribution "
            "attribution is post-MVP backlog.",
            "compare_to=<seq> resolves the baseline by db_seq, so the diff "
            "answers 'did the mutations since that seq do what they "
            "predicted?' — the summary carries significant_delta_count; "
            "the report's compare_to field has the per-metric rows. "
            "Reports written before seq tagging have db_seq=null and "
            "can't be resolved by seq.",
        ),
    )
)


register(
    Action(
        tool="ableton_analysis",
        name="extract",
        description=(
            "Return a raw structural dump of a song straight from its "
            "Hallucinote DB — tracks, clips, notes (exact pitch / "
            "start_beats / duration / velocity), sections, device chains + "
            "parameters, arrangement-clip placements, sends, returns, cue "
            "points, and the tempo / time-signature maps. This is the "
            "score-as-data tier the audio + compose analyzers can't see "
            "(phase relationships, exact note timings); read it directly "
            "rather than hand-querying the sqlite DB. Read-only — never "
            "touches Live, never mutates."
        ),
        params=(
            ParamSpec(
                name="song_slug",
                type="str",
                description=(
                    "Hallucinote song slug — directs the dump at "
                    "songs/<slug>/'s DB."
                ),
            ),
        ),
        handler=analysis_handlers.extract_structure_handler,
        runs_server_side=True,
        example=(
            "ableton_analysis(action='extract', song_slug='reich-phase')"
        ),
        tips=(
            "Returns {song_slug, extract}. extract has top-level keys song, "
            "tempo_map, time_signature_map, sections, cue_points, tracks, "
            "returns. Each track nests clips (with notes), arrangement_clips, "
            "devices (with parameters), and sends; each return nests devices.",
            "Devices are top-level-chain only — nested rack chains aren't "
            "flattened in (a song using Instrument/Audio-Effect Racks reports "
            "the rack container, not the devices inside it).",
            "Built for the musical-work eval judge's --db-extract input: when "
            "a request outran the compose/mix analyzers (a known-gap or novel "
            "result), save this extract to JSON and pass it so the judge can "
            "evaluate what the analyzer can't read.",
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
            "Returns {report_path, report, analysis_code} where report is "
            "the parsed MixReport dict — same shape that analyze produces. "
            "analysis_code = {signature, stale} flags whether this server's "
            "loaded analysis code differs from disk (run /mcp if stale).",
        ),
    )
)
