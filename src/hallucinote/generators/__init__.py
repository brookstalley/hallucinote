"""Reusable musical primitives.

Generators are pure functions: take parameters, return list[NoteDict]. They
never touch the DB. The caller decides which clip the notes attach to and
invokes `mutations.insert_notes` / `mutations.replace_clip_notes` to persist.

Notes returned carry semantic `tags` so post-hoc bulk operations
(`update_notes_by_tag(clip_id=..., tag="ghost", velocity_delta=+5)`) work
without re-running the generator.

Canonical NoteDict shape: {pitch, start_beats, duration_beats, velocity, tags?}
"""
