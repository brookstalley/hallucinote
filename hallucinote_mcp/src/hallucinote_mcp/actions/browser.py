"""``ableton_browser`` action schema.

Five actions covering Live's content browser:

  - **tree**: bounded-depth walk from a named root
  - **at_path**: navigate to a specific node by path
  - **search**: pattern-match leaves under a root (agent-facing — lets the
    agent NOT have to know exact names)
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
        name="search",
        description=(
            "Pattern-match nodes under a browser root. Lets the agent find "
            "instruments / presets / plugins without knowing exact names. "
            "Returns matches with name, uri, full path, and is_loadable. "
            "The categorical structure IS the typing — a match at "
            "path=['instruments', 'Operator', 'Bass', 'Pluck'] is an "
            "Operator-engine Bass preset; the agent disambiguates among "
            "same-name results using the path."
        ),
        params=(
            ParamSpec(
                name="pattern", type="str", required=True,
                description=(
                    "Match pattern. Default mode is case-insensitive "
                    "substring — '909' matches 'Kit-Core 909'. Use mode= "
                    "to switch to glob ('*909*') or regex syntax."
                ),
            ),
            ParamSpec(
                name="root", type="str", required=False, enum=_ROOTS,
                description="Browser root to search under. Default 'instruments'.",
            ),
            ParamSpec(
                name="path_prefix", type="list", required=False,
                description=(
                    "Optional list of name segments under root to narrow the "
                    "search space. e.g. path_prefix=['Operator'] only "
                    "searches Operator presets. Cheaper than walking the "
                    "whole root."
                ),
            ),
            ParamSpec(
                name="mode", type="str", required=False,
                enum=("substring", "glob", "regex"),
                description=(
                    "Match mode. 'substring' (default): in-string match. "
                    "'glob': fnmatch syntax (* ? [abc]). 'regex': full "
                    "Python re. All modes are case-insensitive unless "
                    "case_sensitive=true is passed."
                ),
            ),
            ParamSpec(
                name="case_sensitive", type="bool", required=False,
                description="Match case-sensitively. Default False.",
            ),
            ParamSpec(
                name="loadable_only", type="bool", required=False,
                description=(
                    "Return only nodes that browser.load_item can "
                    "instantiate (filters out pure category folders). "
                    "Default True — usually what you want."
                ),
            ),
            ParamSpec(
                name="depth", type="int", required=False,
                minimum=0, maximum=12,
                description=(
                    "Walk depth from root (or from path_prefix's deepest "
                    "node). Default 8; max 12. Some pack libraries nest "
                    "deep — increase if depth_exhausted=true in the result."
                ),
            ),
            ParamSpec(
                name="limit", type="int", required=False,
                minimum=1, maximum=200,
                description=(
                    "Max matches to return. Default 20; max 200. "
                    "Walk stops early once this is hit; truncated=true "
                    "in the result tells the agent to narrow the pattern."
                ),
            ),
        ),
        handler=browser_handlers.search_handler,
        example=(
            "ableton_browser(action='search', pattern='909', root='drums')"
        ),
        tips=(
            "If the agent doesn't know exact names: search by category root "
            "+ a loose pattern, then pick from the returned paths.",
            "For drum kits, try root='drums' or path_prefix=['Impulse'] "
            "under instruments.",
            "truncated=true means you hit the limit — narrow the pattern "
            "or set a higher limit. depth_exhausted=true means leaves at "
            "deeper levels weren't reached — increase depth.",
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
