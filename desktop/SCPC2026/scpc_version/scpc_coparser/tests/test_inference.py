from __future__ import annotations

from core.session_state import MemoryStore
from harness import FinalHarness


def test_memory_store_uses_key_and_person_provenance() -> None:
    store = MemoryStore()
    store.write(
        {"memory_key": "shared", "person": "alpha", "preferred_channel": "room_a"},
        task_id="a",
        session_id="s1",
        turn_index=1,
    )
    store.write(
        {"memory_key": "shared", "person": "beta", "preferred_channel": "room_b"},
        task_id="b",
        session_id="s2",
        turn_index=1,
    )
    assert store.recall({"memory_key": "shared", "person": "alpha"}).value["preferred_channel"] == "room_a"
    assert store.recall({"memory_key": "shared", "person": "beta"}).value["preferred_channel"] == "room_b"


def test_plan_never_emits_unavailable_action() -> None:
    task = {
        "id": "task",
        "session_id": "session",
        "turn_index": 1,
        "prompt": "이 자료를 보내줘.",
        "visible_history": [],
        "personal_memory": [],
        "available_actions": ["read", "guard"],
        "device_state": {
            "objects": [
                {
                    "id": "obj",
                    "type": "file",
                    "attrs": {"ref_code": "WM-1"},
                }
            ],
            "records": [
                {
                    "id": "markers",
                    "type": "focal_marker_refs",
                    "value": {"marker_to_ref": {"marker_alpha": "WM-1"}},
                },
                {
                    "id": "trace",
                    "type": "focal_resolution_trace",
                    "value": {
                        "latest_phase": "draft",
                        "phase_to_marker": {"draft": "marker_alpha"},
                    },
                },
            ],
        },
    }
    answer = FinalHarness().answer_task(task, {})
    assert answer["control"] == "hold"
    assert {event["verb"] for event in answer["plan_events"]} <= {
        "read",
        "guard",
    }
