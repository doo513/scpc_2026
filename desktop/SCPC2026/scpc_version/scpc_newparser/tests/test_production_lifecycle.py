from __future__ import annotations

import copy

import pytest

from core.consistency import ConsistencyValidator
from core.production_projection import ProductionProjectionPipeline
from harness import FinalHarness


ALL_ACTIONS = [
    "read",
    "verify",
    "redact",
    "summarize",
    "dispatch",
    "guard",
    "clarify",
    "update",
    "schedule",
    "toggle",
    "pay",
]


def _task() -> dict[str, object]:
    return {
        "schema": "scpc.final.task.v1",
        "id": "synthetic-lifecycle",
        "session_id": "synthetic-session",
        "turn_index": 0,
        "prompt": "WM-9000 파일의 요약을 내부 채널로 공유해줘.",
        "visible_history": [],
        "personal_memory": [],
        "available_actions": ALL_ACTIONS,
        "device_state": {
            "objects": [
                {
                    "id": "object-file",
                    "type": "file",
                    "attrs": {
                        "ref_code": "WM-9000",
                        "name": "meeting_note",
                        "contains": ["summary"],
                    },
                }
            ],
            "records": [
                {
                    "id": "record-markers",
                    "type": "focal_marker_refs",
                    "value": {"marker_to_ref": {"marker-current": "WM-9000"}},
                },
                {
                    "id": "record-trace",
                    "type": "focal_resolution_trace",
                    "value": {
                        "latest_phase": "current",
                        "phase_to_marker": {"current": "marker-current"},
                    },
                },
                {
                    "id": "record-target",
                    "type": "resolved_target",
                    "value": "internal_channel",
                }
            ],
        },
    }


def test_projection_lock_is_present_on_production_output() -> None:
    result = FinalHarness().answer_task(_task(), {}, commit=False)

    lock = result["_trace"]["projection_lock"]
    assert len(lock["lock_digest"]) == 64
    assert lock["compiler"] == "core.projection_compilers.ProjectionCompiler"
    assert ProductionProjectionPipeline.production_active is True


def test_validation_failure_prevents_session_and_memory_commit(monkeypatch) -> None:
    harness = FinalHarness()
    session = {"existing": {"value": 1}}
    session_before = copy.deepcopy(session)
    memory_before = harness.memory_store.snapshot()

    def reject(*_args, **_kwargs):
        raise ValueError("injected validation failure")

    monkeypatch.setattr(ConsistencyValidator, "validate_strict", reject)

    with pytest.raises(ValueError, match="injected validation failure"):
        harness.answer_task(_task(), session, commit=True)

    assert session == session_before
    assert harness.memory_store.snapshot() == memory_before
