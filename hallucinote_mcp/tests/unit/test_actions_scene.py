"""ableton_scene schema + handler behavior."""
from __future__ import annotations

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------- Fakes ----------


class FakeClipSlot:
    def __init__(self, has_clip: bool = False):
        self.clip = object() if has_clip else None


class FakeScene:
    def __init__(
        self,
        name: str = "",
        *,
        color: int | None = None,
        tempo: float = -1.0,
        sig_num: int = 4,
        sig_den: int = 4,
        clip_count: int = 0,
    ):
        self.name = name
        self.color = color
        self.tempo = tempo
        self.time_signature_numerator = sig_num
        self.time_signature_denominator = sig_den
        self.clip_slots = [FakeClipSlot(has_clip=True) for _ in range(clip_count)]
        self.fire_calls = 0

    def fire(self) -> None:
        self.fire_calls += 1


class FakeSong:
    def __init__(self, scenes: list[FakeScene] | None = None):
        self.scenes = scenes if scenes is not None else [
            FakeScene("Intro"), FakeScene("Verse"), FakeScene("Chorus"),
        ]
        self._created: list[FakeScene] = []
        self._deleted: list[int] = []

    def create_scene(self, insert_at: int) -> FakeScene:
        new = FakeScene("")
        self._created.append(new)
        if insert_at == -1:
            self.scenes.append(new)
        else:
            self.scenes.insert(insert_at, new)
        return new

    def delete_scene(self, index_0based: int) -> None:
        self._deleted.append(index_0based)
        del self.scenes[index_0based]


class FakeCtx:
    def __init__(self, song: FakeSong | None = None):
        self._song = song or FakeSong()
        self.run_on_main_calls = 0

    @property
    def song(self):
        return self._song

    def run_on_main(self, fn, **_kwargs):
        self.run_on_main_calls += 1
        return fn()


@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


# ---------- Schema sanity ----------


_EXPECTED_SCENE_ACTIONS = {
    "help", "list", "info", "create", "ensure_count", "delete", "rename",
    "fire", "set_tempo", "set_signature",
}


def test_scene_registers_ten_actions(loaded_actions):
    """Note: design doc lists `insert_at` separately; we absorbed it into
    `create` since Live's create_scene primitive handles both append and
    insert via its index arg. Locking the absence so the consolidation
    doesn't quietly come undone. `ensure_count` (SYN-4P2D) is the tenth
    action — the push 'scenes' phase's provisioning verb.
    """
    names = {a.name for a in schema.actions_for("ableton_scene")}
    assert names == _EXPECTED_SCENE_ACTIONS
    assert schema.get("ableton_scene", "insert_at") is None, (
        "insert_at must NOT be a separate action — absorbed into create per "
        "M-5 design reconciliation (one Live primitive ↔ one MCP action)."
    )


def test_scene_help_lists_all_actions(loaded_actions):
    resp = dispatch(Request(tool="ableton_scene", action="help"))
    assert resp.ok is True
    names = {a["name"] for a in resp.result["actions"]}
    assert names == _EXPECTED_SCENE_ACTIONS - {"help"}


# ---------- list / info ----------


def test_list_returns_thin_index(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(tool="ableton_scene", action="list"),
        context=ctx,
    )
    assert resp.ok is True
    scenes = resp.result["scenes"]
    assert len(scenes) == 3
    assert scenes[0]["name"] == "Intro"
    assert scenes[0]["tempo"] is None  # -1 sentinel → null


def test_list_returns_scene_tempo_when_set(loaded_actions):
    ctx = FakeCtx(FakeSong(scenes=[
        FakeScene("Verse", tempo=140.0),
    ]))
    resp = dispatch(
        Request(tool="ableton_scene", action="list"),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["scenes"][0]["tempo"] == 140.0


def test_info_includes_clip_count(loaded_actions):
    ctx = FakeCtx(FakeSong(scenes=[FakeScene("Verse", clip_count=3)]))
    resp = dispatch(
        Request(
            tool="ableton_scene", action="info",
            params={"scene_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["clip_count"] == 3


# ---------- create / delete ----------


def test_create_appends_when_no_position(loaded_actions):
    ctx = FakeCtx()
    before = len(ctx.song.scenes)
    resp = dispatch(
        Request(
            tool="ableton_scene", action="create",
            params={"name": "Bridge"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["scene_index"] == before + 1
    assert resp.result["name"] == "Bridge"
    assert ctx.song.scenes[-1].name == "Bridge"


def test_create_inserts_at_position(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_scene", action="create",
            params={"name": "Pre-Chorus", "position": 3},
        ),
        context=ctx,
    )
    assert resp.ok is True
    # Original: [Intro, Verse, Chorus]; insert at 3 → [Intro, Verse, Pre-Chorus, Chorus]
    assert ctx.song.scenes[2].name == "Pre-Chorus"


# Regression: real Live re-wraps API objects on each property access, so
# scanning ``song.scenes`` for ``new_scene`` by ``is`` identity used to
# spuriously fail and the handler raised a false-positive "Live API bug".
# The fix computes the new index from the create-call's known semantics
# (append → len-after; insert_at-N → N+1).


class _ReWrappingSceneSong:
    """Underlying data is stable; every ``scenes`` access returns a fresh
    list of fresh wrappers. ``new_scene is song.scenes[i]`` always False."""

    def __init__(self) -> None:
        self._underlying: list[dict] = [
            {"name": "Intro"}, {"name": "Verse"}, {"name": "Chorus"},
        ]
        self.view = type("V", (), {"selected_scene": None})()

    @property
    def scenes(self):
        return [_FreshSceneWrapper(d) for d in self._underlying]

    def create_scene(self, insert_at: int = -1):
        d = {"name": "New"}
        if insert_at == -1:
            self._underlying.append(d)
        else:
            self._underlying.insert(insert_at, d)
        return _FreshSceneWrapper(d)


class _FreshSceneWrapper:
    def __init__(self, data: dict) -> None:
        self._data = data

    @property
    def name(self) -> str:
        return self._data["name"]

    @name.setter
    def name(self, value: str) -> None:
        self._data["name"] = value


class _SceneCtx:
    def __init__(self) -> None:
        self._song = _ReWrappingSceneSong()

    @property
    def song(self):
        return self._song

    def run_on_main(self, fn, **_kwargs):
        return fn()


def test_create_scene_handles_live_wrapper_recreation(loaded_actions):
    """Append path: new index is len-after, computed without scanning."""
    ctx = _SceneCtx()
    resp = dispatch(
        Request(tool="ableton_scene", action="create", params={"name": "Bridge"}),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    assert resp.result["scene_index"] == 4  # appended to a 3-scene song
    assert resp.result["name"] == "Bridge"


def test_create_scene_with_position_handles_wrapper_recreation(loaded_actions):
    """Insert path: new index is the requested 1-based position."""
    ctx = _SceneCtx()
    resp = dispatch(
        Request(
            tool="ableton_scene", action="create",
            params={"name": "Pre-Chorus", "position": 3},
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    assert resp.result["scene_index"] == 3


# ---------- ensure_count (SYN-4P2D) ----------


def test_ensure_count_grows_to_requested_count(loaded_actions):
    """A 9-section song into a default-3-scene fake set: ensure_count(9)
    appends the 6-scene deficit and reports it."""
    ctx = FakeCtx()  # default FakeSong has 3 scenes
    resp = dispatch(
        Request(
            tool="ableton_scene", action="ensure_count",
            params={"count": 9},
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    assert resp.result == {"scene_count": 9, "created": 6}
    assert len(ctx.song.scenes) == 9
    # Grew via -1 append, never insert.
    assert ctx.song._created and len(ctx.song._created) == 6


def test_ensure_count_is_idempotent_no_op_when_enough(loaded_actions):
    """needed <= 0 creates nothing and reports created=0 — re-running a
    whole push is a no-op for this phase. count == current is the boundary."""
    ctx = FakeCtx()  # 3 scenes
    resp = dispatch(
        Request(
            tool="ableton_scene", action="ensure_count",
            params={"count": 3},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result == {"scene_count": 3, "created": 0}
    assert ctx.song._created == []
    # Asking for fewer than current is also a no-op (grows only, never trims).
    resp2 = dispatch(
        Request(
            tool="ableton_scene", action="ensure_count",
            params={"count": 1},
        ),
        context=ctx,
    )
    assert resp2.ok is True
    assert resp2.result == {"scene_count": 3, "created": 0}
    assert ctx.song._created == []


def test_ensure_count_rejects_count_below_one(loaded_actions):
    """count < 1 is meaningless (a set always has >= 1 scene). The schema
    ParamSpec(minimum=1) rejects it before the handler runs, with a teaching
    'below minimum' validation error."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_scene", action="ensure_count",
            params={"count": 0},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "below minimum" in (resp.error or "")


class _NoCreateSceneSong:
    """A Live build that doesn't expose Song.create_scene. Has scenes but
    no way to grow them."""

    def __init__(self, n_scenes: int = 8) -> None:
        self.scenes = [FakeScene(f"s{i}") for i in range(n_scenes)]


def test_ensure_count_refuses_and_teaches_when_create_scene_absent(loaded_actions):
    """DR-2 option (c): a deficit exists but this Live build can't provision.
    Raise the single actionable message (one teaching error, NOT N raw
    per-clip IndexErrors at the later clips phase)."""
    ctx = FakeCtx(_NoCreateSceneSong(n_scenes=8))  # type: ignore[arg-type]
    resp = dispatch(
        Request(
            tool="ableton_scene", action="ensure_count",
            params={"count": 9},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "song needs 9 scenes" in err
    assert "set has 8" in err
    assert "add 1 scenes manually" in err
    assert "re-run the push" in err


def test_ensure_count_no_op_does_not_touch_missing_create_scene(loaded_actions):
    """When no deficit exists, the absence of create_scene is irrelevant —
    the handler returns before probing for it (idempotent re-push on a build
    that can't grow scenes but already has enough must still succeed)."""
    ctx = FakeCtx(_NoCreateSceneSong(n_scenes=9))  # type: ignore[arg-type]
    resp = dispatch(
        Request(
            tool="ableton_scene", action="ensure_count",
            params={"count": 9},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result == {"scene_count": 9, "created": 0}


def test_ensure_count_handles_live_wrapper_recreation(loaded_actions):
    """Re-wrapping discipline: ensure_count reads len(song.scenes) before and
    after and appends via create_scene(-1) — never scans for object identity.
    The _ReWrappingSceneSong returns fresh wrappers on each scenes access, so
    a stray `is`-scan would misbehave; len-based deficit math is immune."""
    ctx = _SceneCtx()  # 3 scenes underlying
    resp = dispatch(
        Request(
            tool="ableton_scene", action="ensure_count",
            params={"count": 5},
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    assert resp.result == {"scene_count": 5, "created": 2}
    assert len(ctx.song.scenes) == 5


def test_delete_removes_scene(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_scene", action="delete",
            params={"scene_index": 2},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["deleted_scene_index"] == 2
    assert [s.name for s in ctx.song.scenes] == ["Intro", "Chorus"]


def test_delete_refuses_last_remaining_scene(loaded_actions):
    """W18-E symmetry with track delete: Live requires the set to contain
    at least one scene. Refuse with a teaching error before the LOM raises."""
    song = FakeSong(scenes=[FakeScene("OnlyOne")])
    ctx = FakeCtx(song)
    resp = dispatch(
        Request(
            tool="ableton_scene", action="delete",
            params={"scene_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert len(song.scenes) == 1
    assert song._deleted == []
    assert "at least one scene" in resp.error
    assert "ableton_scene(action='create')" in resp.error


# ---------- rename / fire ----------


def test_rename_updates_name(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_scene", action="rename",
            params={"scene_index": 1, "name": "Opener"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.scenes[0].name == "Opener"


def test_fire_calls_fire(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_scene", action="fire",
            params={"scene_index": 2},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.scenes[1].fire_calls == 1


# ---------- set_tempo / set_signature ----------


def test_set_tempo_writes_value(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_scene", action="set_tempo",
            params={"scene_index": 1, "bpm": 132.0},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.scenes[0].tempo == 132.0
    assert resp.result["tempo"] == 132.0


def test_set_tempo_clear_via_negative_one(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_scene", action="set_tempo",
            params={"scene_index": 1, "bpm": -1.0},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["tempo"] is None  # -1 → null in response shape


@pytest.mark.parametrize("bad_bpm", [
    10.0,    # below 20
    1000.0,  # above 999
    -0.5,    # in the (-1, 0] gap admitted by schema enum (-1.0 minimum)
    0.0,     # in the gap
    19.999,  # just below the lower bound
])
def test_set_tempo_out_of_range(loaded_actions, bad_bpm):
    """Tighter validation than the schema bounds allow: Live's per-scene
    tempo accepts -1 OR [20, 999]. The (-1, 0] gap and (0, 20) gap must
    both be rejected — schema enum minimum=-1.0 admits them, handler
    catches.
    """
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_scene", action="set_tempo",
            params={"scene_index": 1, "bpm": bad_bpm},
        ),
        context=ctx,
    )
    assert resp.ok is False
    # Schema enum bounds catch above/below the (-1, 999) range with
    # "above maximum" / "below minimum"; handler catches the (-1, 20)
    # interior gap with "out of Live's allowed range".
    err = resp.error or ""
    assert (
        "out of Live's allowed range" in err
        or "above maximum" in err
        or "below minimum" in err
    ), f"unexpected error shape for bpm={bad_bpm}: {err!r}"


def test_set_signature_writes(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_scene", action="set_signature",
            params={"scene_index": 1, "numerator": 7, "denominator": 8},
        ),
        context=ctx,
    )
    assert resp.ok is True
    s = ctx.song.scenes[0]
    assert s.time_signature_numerator == 7
    assert s.time_signature_denominator == 8


def test_set_signature_rejects_non_power_of_two_denominator(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_scene", action="set_signature",
            params={"scene_index": 1, "numerator": 5, "denominator": 6},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "power of 2" in (resp.error or "")


# ---------- run_on_main ----------


def test_scene_execution_marshals_to_main_thread(loaded_actions):
    ctx = FakeCtx()
    dispatch(
        Request(tool="ableton_scene", action="list"),
        context=ctx,
    )
    assert ctx.run_on_main_calls == 1
