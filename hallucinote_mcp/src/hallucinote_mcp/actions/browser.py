"""``ableton_browser`` action schema.

Four actions covering Live's content browser:

  - **tree**: bounded-depth walk from a named root
  - **at_path**: navigate to a specific node by path
  - **plugins_list**: flat list of installed VST/AU plugins
  - **help**: dispatcher-special

M-5 ships these as actions for callability. M-6 (Resources) considers
moving the heavy reads (full tree dumps) behind ``ableton://browser/*``
resource URIs to reduce per-call token cost.
"""
from __future__ import annotations

from ..handlers import browser as browser_handlers
from ..schema import Action, ParamSpec, register


_ROOTS = (
    "instruments", "audio_effects", "midi_effects", "drums", "plugins",
    "samples", "user_library", "packs",
)


register(
    Action(
        tool="ableton_browser",
        name="help",
        description=(
            "List all actions on ableton_browser, with required/optional "
            "params, examples, and tips."
        ),
        example="ableton_browser(action='help')",
    )
)


register(
    Action(
        tool="ableton_browser",
        name="tree",
        description=(
            "Read a bounded-depth browser tree from one root. depth=2 "
            "(default) returns root + immediate children + grandchildren — "
            "enough for category browsing without dumping the whole library."
        ),
        params=(
            ParamSpec(
                name="root", type="str", required=False, enum=_ROOTS,
                description="Default 'instruments'.",
            ),
            ParamSpec(
                name="depth", type="int", required=False, minimum=0, maximum=6,
                description=(
                    "Recursion depth. 0 = identity only. Default 2. "
                    "Capped at 6 to prevent runaway walks."
                ),
            ),
        ),
        handler=browser_handlers.tree_handler,
        example="ableton_browser(action='tree', root='instruments', depth=2)",
        tips=(
            "M-6 may move full-tree reads behind ableton://browser/* "
            "resources to reduce per-call token cost. Use action='at_path' "
            "for narrow lookups today.",
        ),
    )
)


register(
    Action(
        tool="ableton_browser",
        name="at_path",
        description=(
            "Navigate to a specific browser node by path. path is a list "
            "of name segments rooted at one of the browser roots "
            "(instruments / audio_effects / midi_effects / drums / "
            "plugins / samples / user_library / packs). Returns the node "
            "+ its immediate children."
        ),
        params=(
            ParamSpec(
                name="path", type="list",
                description=(
                    "List of name segments. path[0] is the root; subsequent "
                    "segments are matched by exact folder name."
                ),
            ),
        ),
        handler=browser_handlers.at_path_handler,
        example=(
            "ableton_browser(action='at_path', "
            "path=['instruments', 'Operator', 'Bass'])"
        ),
        tips=(
            "If a segment isn't found, the error lists what IS available "
            "at that level — useful for narrowing the search.",
        ),
    )
)


register(
    Action(
        tool="ableton_browser",
        name="plugins_list",
        description=(
            "Flat list of installed VST/AU plugins (loadable nodes under "
            "browser.plugins). Returns [{name, uri}, ...] + count."
        ),
        handler=browser_handlers.plugins_list_handler,
        example="ableton_browser(action='plugins_list')",
        tips=(
            "Use the returned uri with ableton_device(action='load', "
            "kind=..., preset_uri=...) to instantiate.",
        ),
    )
)


__all__: list[str] = []  # registry side-effects only
