"""ableton_probe schema + handler behavior — constrained LOM introspection."""
from __future__ import annotations

import pytest

from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.handlers.probe import (
    MAX_VECTOR_ITEMS,
    _request_differs,
    call_handler,
    describe_handler,
    get_handler,
    resolve_path,
    serialize,
    set_handler,
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


class FakeEnvelope:
    def __init__(self) -> None:
        self.steps: list[tuple] = []

    def insert_step(self, time: float, length: float, value: float) -> None:
        self.steps.append((time, length, value))

    def value_at_time(self, time: float) -> float:
        return 0.5


class FakeClip:
    def __init__(self) -> None:
        self.name = "Probe Clip"
        self.is_audio_clip = True
        self.envelope_args: list = []
        self.last_envelope: FakeEnvelope | None = None

    def create_automation_envelope(self, parameter):
        """create_automation_envelope( (Clip)self, (DeviceParameter)p) -> object"""
        self.envelope_args.append(parameter)
        self.last_envelope = FakeEnvelope()
        return self.last_envelope


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
        self._back_to_arranger = True

    @property
    def back_to_arranger(self) -> bool:
        return self._back_to_arranger

    @back_to_arranger.setter
    def back_to_arranger(self, value) -> None:
        # Mirror the real LOM quirk: the setattr is accepted (no exception)
        # but silently ignored — only Live's GUI button clears the latch.
        pass


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

    def run_on_main(self, fn, **_kwargs):
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


# ---------- set ----------


class TestSet:
    def test_primitive_write_returns_old_new_and_changed(self):
        ctx = FakeCtx()
        out = set_handler(ctx, "song.tempo", 140.0)
        assert out == {
            "path": "song.tempo",
            "old": 120.0,
            "new": 140.0,
            "changed": True,
        }
        assert ctx.song.tempo == 140.0

    def test_bool_write(self):
        ctx = FakeCtx()
        set_handler(ctx, "song.tracks[0].arm", True)
        assert ctx.song.tracks[0].arm is True

    def test_set_to_same_value_reports_unchanged_without_warning(self):
        # A legitimate no-op (request == current): changed is False, but the
        # write was NOT silently ignored, so no applied/warning flag.
        ctx = FakeCtx()
        out = set_handler(ctx, "song.tempo", 120.0)
        assert out["changed"] is False
        assert "applied" not in out
        assert "warning" not in out

    def test_silently_ignored_write_is_flagged(self):
        # song.back_to_arranger accepts the setattr but Live drops it; the
        # caller asked for a different value yet the read-back did not move.
        ctx = FakeCtx()
        out = set_handler(ctx, "song.back_to_arranger", False)
        assert out["old"] is True
        assert out["new"] is True
        assert out["changed"] is False
        assert out["applied"] is False
        assert "did not land" in out["warning"]
        assert "back_to_arranger" in out["warning"]

    def test_silently_ignored_write_with_int_coercion_is_flagged(self):
        # The reported case used value=0 against a bool latch (0 != True).
        ctx = FakeCtx()
        out = set_handler(ctx, "song.back_to_arranger", 0)
        assert out["changed"] is False
        assert out["applied"] is False

    def test_request_differs_tolerates_float_repr_noise(self):
        # The no-op guard must not flag a float request as "silently ignored"
        # just because its repr differs from the stored value by epsilon.
        assert _request_differs(0.1 + 0.2, 0.3) is False  # numerically equal
        assert _request_differs(120, 120.0) is False  # int/float cross-type
        assert _request_differs(140.0, 120.0) is True  # genuinely different
        # bool stays exact (an int subclass, but not a numeric near-miss).
        assert _request_differs(0, True) is True
        assert _request_differs(True, True) is False
        assert _request_differs("a", "b") is True

    def test_dollar_path_value(self):
        ctx = FakeCtx()
        out = set_handler(
            ctx,
            "song.tracks[0].mixer_device.volume",
            {"$path": "song.tracks[1].mixer_device.volume"},
        )
        assert (
            ctx.song.tracks[0].mixer_device.volume
            is ctx.song.tracks[1].mixer_device.volume
        )
        # A $path (dict) request must NOT be no-op-flagged: the read-back is a
        # LOM object, not comparable to the requested marker, so the scalar
        # no-op guard excludes it. This pins the is_scalar_request exclusion.
        assert "applied" not in out
        assert "warning" not in out

    def test_list_request_is_not_no_op_flagged(self):
        # A list-valued request is likewise excluded from the scalar no-op
        # check — the guard keys on "not a dict/list", so collection writes
        # never get an applied/warning flag.
        ctx = FakeCtx()
        out = set_handler(ctx, "song.tracks[0].arm", [1, 2])
        assert "applied" not in out
        assert "warning" not in out

    def test_unknown_attribute_rejected_before_write(self):
        with pytest.raises(AttributeError, match="no attribute 'nonexistent'"):
            set_handler(FakeCtx(), "song.nonexistent", 1)

    @pytest.mark.parametrize("bad", ["song", "song.tracks[0]"])
    def test_path_must_end_in_attribute(self, bad):
        with pytest.raises(ValueError, match="must end in '.attribute'"):
            set_handler(FakeCtx(), bad, 1)


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

    def test_then_step_runs_on_returned_object(self):
        ctx = FakeCtx()
        slot = ctx.song.tracks[0].clip_slots[0]
        slot.create_audio_clip("/tmp/probe.wav")
        out = call_handler(
            ctx,
            "song.tracks[0].clip_slots[0].clip",
            "create_automation_envelope",
            args=[{"$path": "song.tracks[0].mixer_device.volume"}],
            then=[{"method": "insert_step", "args": [0.0, 4.0, 0.5]}],
        )
        assert slot.clip.last_envelope.steps == [(0.0, 4.0, 0.5)]
        assert out["then"] == [{"method": "insert_step", "result": None}]

    def test_then_step_result_serialized(self):
        ctx = FakeCtx()
        slot = ctx.song.tracks[0].clip_slots[0]
        slot.create_audio_clip("/tmp/probe.wav")
        out = call_handler(
            ctx,
            "song.tracks[0].clip_slots[0].clip",
            "create_automation_envelope",
            args=[{"$path": "song.tracks[0].mixer_device.volume"}],
            then=[{"method": "value_at_time", "args": [2.0]}],
        )
        assert out["then"] == [{"method": "value_at_time", "result": 0.5}]

    def test_then_step_on_none_return_is_clear_error(self):
        ctx = FakeCtx()
        slot = ctx.song.tracks[0].clip_slots[0]
        slot.create_audio_clip("/tmp/probe.wav")
        with pytest.raises(ValueError, match=r"then\[1\].*returned\s+None"):
            call_handler(
                ctx,
                "song.tracks[0].clip_slots[0].clip",
                "create_automation_envelope",
                args=[{"$path": "song.tracks[0].mixer_device.volume"}],
                then=[
                    {"method": "insert_step", "args": [0.0, 4.0, 0.5]},
                    {"method": "value_at_time", "args": [2.0]},
                ],
            )

    def test_then_malformed_step_rejected(self):
        with pytest.raises(ValueError, match=r"then\[0\].*'method'"):
            call_handler(
                FakeCtx(),
                "song.tracks[0].clip_slots[0]",
                "create_audio_clip",
                args=["/tmp/probe.wav"],
                then=["not-a-dict"],
            )

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
            assert {"help", "describe", "get", "set", "call"} <= names

    def test_dispatch_set_through_wire(self):
        # The 'any'-typed value param must survive wire validation for every
        # JSON shape — a regression here kills every set call on the wire
        # while the handler-level suite stays green.
        with isolated_actions():
            ctx = FakeCtx()
            for value, expect in [(140.0, 140.0), (True, True), ("x", "x")]:
                resp = dispatch(
                    Request(
                        tool="ableton_probe",
                        action="set",
                        params={"path": "song.tempo", "value": value},
                    ),
                    context=ctx,
                )
                assert resp.ok, resp.error
                assert resp.result["new"] == expect

    def test_dispatch_set_readonly_style_failure_is_structured(self):
        with isolated_actions():
            resp = dispatch(
                Request(
                    tool="ableton_probe",
                    action="set",
                    params={"path": "song.nonexistent", "value": 1},
                ),
                context=FakeCtx(),
            )
            assert not resp.ok
            assert "nonexistent" in resp.error

    def test_dispatch_call_with_then_through_wire(self):
        with isolated_actions():
            ctx = FakeCtx()
            ctx.song.tracks[0].clip_slots[0].create_audio_clip("/tmp/probe.wav")
            resp = dispatch(
                Request(
                    tool="ableton_probe",
                    action="call",
                    params={
                        "path": "song.tracks[0].clip_slots[0].clip",
                        "method": "create_automation_envelope",
                        "args": [{"$path": "song.tracks[0].mixer_device.volume"}],
                        "then": [{"method": "value_at_time", "args": [2.0]}],
                    },
                ),
                context=ctx,
            )
            assert resp.ok, resp.error
            assert resp.result["then"] == [
                {"method": "value_at_time", "result": 0.5}
            ]

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
