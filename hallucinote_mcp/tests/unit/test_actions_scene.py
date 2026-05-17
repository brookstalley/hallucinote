"""ableton_scene schema + handler behavior."""
from __future__ import annotations

from typing import Any

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

    def run_on_main(self, fn):
        self.run_on_main_calls += 1
        return fn()


@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


# ---------- Schema sanity ----------


_EXPECTED_SCENE_ACTIONS = {
    "help", "list", "info", "create", "delete", "rename", "fire",
    "set_tempo", "set_signature",
}


def test_scene_registers_nine_actions(loaded_actions):
    """Note: design doc lists `insert_at` separately; we absorbed it into
    `create` since Live's create_scene primitive handles both append and
    insert via its index arg. Locking the absence so the consolidation
    doesn't quietly come undone.
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
