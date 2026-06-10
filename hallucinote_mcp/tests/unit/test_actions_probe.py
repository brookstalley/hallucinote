"""ableton_probe schema + handler behavior — constrained LOM introspection."""
from __future__ import annotations

import pytest

from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.handlers import probe as probe_handlers
from hallucinote_mcp.handlers.probe import (
    MAX_VECTOR_ITEMS,
    call_handler,
    describe_handler,
    get_handler,
    resolve_path,
    serialize,
)
from hallucinote_mcp.schema import actions_for
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------- Fakes ----------


class FakeVolume:
    """Stands in for a DeviceParameter."""

    def __init__(self) -> None:
        self.value = 0.85


class FakeMixer:
    def __init__(self) -> None:
        self.volume = FakeVolume()


class FakeClip:
    def __init__(self) -> None:
        self.name = "Probe Clip"
        self.is_audio_clip = True
        self.envelope_args: list = []

    def create_automation_envelope(self, parameter):
        """create_automation_envelope( (Clip)self, (DeviceParameter)p) -> object"""
        self.envelope_args.append(parameter)
        return object()


class FakeClipSlot:
    def __init__(self, clip: FakeClip | None = None) -> None:
        self.clip = clip
        self.created_paths: list[str] = []

    def create_audio_clip(self, path: str):
        """create_audio_clip( (ClipSlot)self, (str)path) -> Clip"""
        self.created_paths.append(path)
        new = FakeClip()
        self.clip = new
        return new


class FakeTrack:
    def __init__(self, *, slots: int = 2) -> None:
        self.name = "Vox"
        self.arm = False
        self.clip_slots = [FakeClipSlot() for _ in range(slots)]
        self.mixer_device = FakeMixer()

    @property
    def exploding_property(self) -> str:
        raise RuntimeError("state-dependent LOM read failure")


class FakeSong:
    def __init__(self) -> None:
        self.tempo = 120.0
        self.tracks = [FakeTrack(), FakeTrack()]


class FakeApplication:
    def __init__(self) -> None:
        self.major_version = 12


class FakeCtx:
    def __init__(self) -> None:
        self._song = FakeSong()
        self._app = FakeApplication()

    @property
    def song(self) -> FakeSong:
        return self._song

    @property
    def application(self) -> FakeApplication:
        return self._app

    def run_on_main(self, fn):
        return fn()


# ---------- Path resolution ----------


class TestResolvePath:
    def test_song_root(self):
        ctx = FakeCtx()
        assert resolve_path(ctx, "song") is ctx.song

    def test_application_root_and_alias(self):
        ctx = FakeCtx()
        assert resolve_path(ctx, "application") is ctx.application
        assert resolve_path(ctx, "app") is ctx.application

    def test_nested_attr_and_index(self):
        ctx = FakeCtx()
        obj = resolve_path(ctx, "song.tracks[1].clip_slots[0]")
        assert obj is ctx.song.tracks[1].clip_slots[0]

    def test_whitespace_tolerated(self):
        ctx = FakeCtx()
        assert resolve_path(ctx, "  song.tempo ") == 120.0

    @pytest.mark.parametrize(
        "bad",
        [
            "tracks[0]",                      # no root
            "song.tracks[0]; import os",      # not in grammar
            "song.tracks[-1]",                # negative index not in grammar
            "song.tracks[x]",                 # non-numeric index
            "song..tracks",                   # empty step
            "__import__('os')",               # not even close
        ],
    )
    def test_grammar_violations_rejected(self, bad):
        with pytest.raises(ValueError, match="invalid probe path"):
            resolve_path(FakeCtx(), bad)

    def test_unknown_attribute_names_walk_position(self):
        with pytest.raises(AttributeError, match=r"song\.tracks\[0\]"):
            resolve_path(FakeCtx(), "song.tracks[0].nonexistent")

    def test_index_out_of_range_names_walk_position(self):
        with pytest.raises(IndexError, match=r"song\.tracks"):
            resolve_path(FakeCtx(), "song.tracks[99]")


# ---------- Serialization ----------


class TestSerialize:
    @pytest.mark.parametrize("value", [None, True, 3, 2.5, "hi"])
    def test_primitives_pass_through(self, value):
        assert serialize(value) == value

    def test_object_becomes_lom_summary(self):
        out = serialize(FakeVolume())
        assert out["__lom__"] == "FakeVolume"
        assert "repr" in out

    def test_sequence_of_primitives(self):
        assert serialize([1, 2, 3]) == [1, 2, 3]

    def test_sequence_elements_below_top_level_summarize(self):
        out = serialize([[1, 2], FakeVolume()])
        assert out[0]["__lom__"] == "list"
        assert out[1]["__lom__"] == "FakeVolume"

    def test_long_vector_truncates_with_marker(self):
        out = serialize(list(range(MAX_VECTOR_ITEMS + 50)))
        assert out["__truncated__"] is True
        assert out["shown"] == MAX_VECTOR_ITEMS
        assert out["total"] == MAX_VECTOR_ITEMS + 50
        assert len(out["items"]) == MAX_VECTOR_ITEMS

    def test_string_is_not_treated_as_sequence(self):
        assert serialize("abcdef") == "abcdef"

    def test_dict_values_serialized(self):
        out = serialize({"beat_time": 4.0, "param": FakeVolume()})
        assert out["beat_time"] == 4.0
        assert out["param"]["__lom__"] == "FakeVolume"


# ---------- describe ----------


class TestDescribe:
    def test_shape_and_split(self):
        out = describe_handler(FakeCtx(), "song.tracks[0].clip_slots[0]")
        assert out["class"] == "FakeClipSlot"
        prop_names = {p["name"] for p in out["properties"]}
        method_names = {m["name"] for m in out["methods"]}
        assert "clip" in prop_names
        assert "create_audio_clip" in method_names

    def test_method_doc_carried(self):
        out = describe_handler(FakeCtx(), "song.tracks[0].clip_slots[0]")
        doc = next(
            m["doc"] for m in out["methods"] if m["name"] == "create_audio_clip"
        )
        assert "create_audio_clip" in doc

    def test_raising_property_captured_not_fatal(self):
        out = describe_handler(FakeCtx(), "song.tracks[0]")
        errored = next(
            p for p in out["properties"] if p["name"] == "exploding_property"
        )
        assert "RuntimeError" in errored["error"]
        # and the rest of the object still described
        assert any(p["name"] == "name" for p in out["properties"])

    def test_dunders_excluded(self):
        out = describe_handler(FakeCtx(), "song")
        all_names = {p["name"] for p in out["properties"]} | {
            m["name"] for m in out["methods"]
        }
        assert not any(n.startswith("__") for n in all_names)


# ---------- get ----------


class TestGet:
    def test_primitive(self):
        out = get_handler(FakeCtx(), "song.tempo")
        assert out == {"path": "song.tempo", "type": "float", "value": 120.0}

    def test_lom_object(self):
        out = get_handler(FakeCtx(), "song.tracks[0].mixer_device.volume")
        assert out["value"]["__lom__"] == "FakeVolume"


# ---------- call ----------


class TestCall:
    def test_positional_args(self):
        ctx = FakeCtx()
        out = call_handler(
            ctx,
            "song.tracks[0].clip_slots[0]",
            "create_audio_clip",
            args=["/tmp/probe.wav"],
        )
        assert ctx.song.tracks[0].clip_slots[0].created_paths == ["/tmp/probe.wav"]
        assert out["result"]["__lom__"] == "FakeClip"

    def test_dollar_path_arg_resolves_to_live_object(self):
        ctx = FakeCtx()
        slot = ctx.song.tracks[0].clip_slots[0]
        slot.create_audio_clip("/tmp/probe.wav")
        call_handler(
            ctx,
            "song.tracks[0].clip_slots[0].clip",
            "create_automation_envelope",
            args=[{"$path": "song.tracks[0].mixer_device.volume"}],
        )
        assert slot.clip.envelope_args == [ctx.song.tracks[0].mixer_device.volume]

    def test_dollar_path_nested_inside_dict_and_list(self):
        ctx = FakeCtx()
        slot = ctx.song.tracks[0].clip_slots[0]
        captured: list = []
        slot.takes_structured = lambda payload: captured.append(payload)  # type: ignore[attr-defined]
        call_handler(
            ctx,
            "song.tracks[0].clip_slots[0]",
            "takes_structured",
            args=[
                {
                    "params": [{"$path": "song.tracks[0].mixer_device.volume"}],
                    "beat_time": 4.0,
                }
            ],
        )
        assert captured[0]["params"][0] is ctx.song.tracks[0].mixer_device.volume
        assert captured[0]["beat_time"] == 4.0

    def test_kwargs_forwarded(self):
        ctx = FakeCtx()
        seen: dict = {}
        ctx.song.tracks[0].clip_slots[0].fire = (  # type: ignore[attr-defined]
            lambda **kw: seen.update(kw)
        )
        call_handler(
            ctx,
            "song.tracks[0].clip_slots[0]",
            "fire",
            kwargs={"record_length": 8.0},
        )
        assert seen == {"record_length": 8.0}

    def test_missing_method_is_attribute_error(self):
        with pytest.raises(AttributeError, match="no attribute 'nope'"):
            call_handler(FakeCtx(), "song", "nope")

    def test_property_not_callable_is_type_error(self):
        with pytest.raises(TypeError, match="not a\\s+method"):
            call_handler(FakeCtx(), "song", "tempo")

    def test_method_exception_propagates(self):
        ctx = FakeCtx()

        def boom() -> None:
            raise RuntimeError("Live refused")

        ctx.song.tracks[0].clip_slots[0].explode = boom  # type: ignore[attr-defined]
        with pytest.raises(RuntimeError, match="Live refused"):
            call_handler(ctx, "song.tracks[0].clip_slots[0]", "explode")


# ---------- registration + dispatch wiring ----------


class TestRegistration:
    def test_actions_registered(self):
        with isolated_actions():
            names = {a.name for a in actions_for("ableton_probe")}
            assert {"help", "describe", "get", "call"} <= names

    def test_dispatch_get_through_wire(self):
        with isolated_actions():
            resp = dispatch(
                Request(tool="ableton_probe", action="get", params={"path": "song.tempo"}),
                context=FakeCtx(),
            )
            assert resp.ok
            assert resp.result["value"] == 120.0

    def test_dispatch_grammar_violation_is_structured_error(self):
        with isolated_actions():
            resp = dispatch(
                Request(
                    tool="ableton_probe",
                    action="get",
                    params={"path": "song.tracks[0]; rm -rf"},
                ),
                context=FakeCtx(),
            )
            assert not resp.ok
            assert "invalid probe path" in resp.error

    def test_dispatch_call_failure_is_structured_error(self):
        with isolated_actions():
            resp = dispatch(
                Request(
                    tool="ableton_probe",
                    action="call",
                    params={"path": "song", "method": "nope"},
                ),
                context=FakeCtx(),
            )
            assert not resp.ok
            assert "nope" in resp.error
