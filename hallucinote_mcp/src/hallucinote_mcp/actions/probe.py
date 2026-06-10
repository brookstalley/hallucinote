"""``ableton_probe`` action schema — constrained LOM introspection.

Three actions plus help:

  - **describe** — class, properties (with values), methods (with
    Boost.Python signature docstrings) of the object at a LOM path.
  - **get** — read one property.
  - **call** — invoke a LOM method with JSON args; ``{"$path": ...}``
    args resolve to live LOM objects.

This is the bridge's permanent capability-probing surface (AUD-1M4V
discovery; the third-party-device rule makes probing a recurring need).
Path grammar and the mutation-is-allowed decision are documented in
``handlers/probe.py``.
"""
from __future__ import annotations

from ..handlers import probe as probe_handlers
from ..schema import Action, ParamSpec, register


register(
    Action(
        tool="ableton_probe",
        name="help",
        description=(
            "List all actions on ableton_probe, with required/optional "
            "params, examples, and tips."
        ),
        example="ableton_probe(action='help')",
    )
)

register(
    Action(
        tool="ableton_probe",
        name="describe",
        description=(
            "Introspect the LOM object at a path: class name, properties "
            "(name/type/value; per-property read errors are captured, not "
            "fatal), methods (name + Boost.Python docstring, which carries "
            "the authoritative signature). Path grammar: root 'song' or "
            "'application', then '.attr' / '[index]' steps only."
        ),
        params=(
            ParamSpec(name="path", type="str"),
        ),
        handler=probe_handlers.describe_handler,
        example="ableton_probe(action='describe', path='song.tracks[0].clip_slots[0]')",
        tips=(
            "Method docstrings are the fastest way to learn a signature — "
            "e.g. describe a ClipSlot and read create_audio_clip's doc.",
            "Large vectors are truncated at 100 elements with a "
            "__truncated__ marker.",
        ),
    )
)

register(
    Action(
        tool="ableton_probe",
        name="get",
        description=(
            "Read the value at a LOM path. Primitives return as-is; LOM "
            "objects return a {__lom__, repr} summary; vectors return as "
            "(possibly truncated) lists."
        ),
        params=(
            ParamSpec(name="path", type="str"),
        ),
        handler=probe_handlers.get_handler,
        example="ableton_probe(action='get', path='song.tracks[2].arm')",
    )
)

register(
    Action(
        tool="ableton_probe",
        name="call",
        description=(
            "Invoke a method on the LOM object at a path. args is a JSON "
            "list, kwargs a JSON object; an argument of shape "
            "{\"$path\": \"song....\"} (also nested inside lists/dicts) is "
            "resolved to the live LOM object first. CAN MUTATE the Live set "
            "— that is the point (capability probes like create_audio_clip "
            "are calls); probe in scratch sets."
        ),
        params=(
            ParamSpec(name="path", type="str"),
            ParamSpec(name="method", type="str"),
            ParamSpec(name="args", type="list", required=False),
            ParamSpec(name="kwargs", type="dict", required=False),
            ParamSpec(
                name="then",
                type="list",
                required=False,
                description=(
                    "Chain of {method[, args][, kwargs]} steps applied to "
                    "each successive RETURN value — reaches objects with no "
                    "LOM path (e.g. the AutomationEnvelope returned by "
                    "create_automation_envelope)."
                ),
            ),
        ),
        handler=probe_handlers.call_handler,
        example=(
            "ableton_probe(action='call', path='song.tracks[3].clip_slots[0]', "
            "method='create_audio_clip', args=['/tmp/probe.wav'])"
        ),
        tips=(
            "For LOM-object arguments: "
            "args=[{\"$path\": \"song.tracks[0].mixer_device.volume\"}].",
            "Chaining: method='create_automation_envelope', "
            "args=[{\"$path\": \"...volume\"}], then=[{\"method\": "
            "\"insert_step\", \"args\": [0.0, 4.0, 0.5]}].",
            "Exceptions propagate as structured errors — an error IS a "
            "probe result (records what Live refuses).",
        ),
    )
)
