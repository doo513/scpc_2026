from __future__ import annotations

from core.evidence_graph import IntentOverride, EvidenceGraph, has_local_update_intent
from core.ontology import FactStatus
from core.task_view import TaskView


def test_latest_clause_and_local_override() -> None:
    task = {
        "id": "task",
        "session_id": "session",
        "turn_index": 2,
        "prompt": "자료를 보내줘. 단, 외부 공유가 아니라 상태만 갱신해줘.",
        "visible_history": [],
        "personal_memory": [],
        "available_actions": ["read", "verify", "update"],
        "device_state": {"objects": [], "records": []},
    }
    view = TaskView(task)
    assert view.latest_clause().startswith("단,")
    assert EvidenceGraph.from_view(view).intent_override == IntentOverride.LOCAL_ONLY


def test_duplicate_records_are_stable_and_ambiguous() -> None:
    base = {
        "id": "task",
        "session_id": "session",
        "turn_index": 1,
        "prompt": "",
        "visible_history": [],
        "personal_memory": [],
        "available_actions": [],
        "device_state": {
            "objects": [],
            "records": [
                {"type": "resolved_target", "value": "zeta"},
                {"type": "resolved_target", "value": "alpha"},
            ],
        },
    }
    first = TaskView(base)
    reversed_task = {**base, "device_state": {**base["device_state"], "records": list(reversed(base["device_state"]["records"]))}}
    second = TaskView(reversed_task)
    assert first.record_is_ambiguous("resolved_target")
    assert first.record_status("resolved_target") == FactStatus.CONFLICTED
    assert first.record_fact("resolved_target") == second.record_fact(
        "resolved_target"
    )


def test_duplicate_object_bindings_are_stable_and_explicitly_ambiguous() -> None:
    base = {
        "id": "task",
        "session_id": "session",
        "turn_index": 1,
        "prompt": "",
        "visible_history": [],
        "personal_memory": [],
        "available_actions": [],
        "device_state": {
            "objects": [
                {
                    "id": "obj_a",
                    "type": "file",
                    "attrs": {"ref_code": "WM-DUP", "name": "zeta"},
                },
                {
                    "id": "obj_b",
                    "type": "file",
                    "attrs": {"ref_code": "WM-DUP", "name": "alpha"},
                },
            ],
            "records": [],
        },
    }
    reversed_task = {
        **base,
        "device_state": {
            **base["device_state"],
            "objects": list(reversed(base["device_state"]["objects"])),
        },
    }

    first = TaskView(base)
    second = TaskView(reversed_task)

    assert first.conflicting_ref_codes() == {"WM-DUP"}
    assert first.object_binding_is_ambiguous("obj_a")
    assert first.object_binding_is_ambiguous("obj_b")
    assert first.objects_by_ref_code()["WM-DUP"] == second.objects_by_ref_code()[
        "WM-DUP"
    ]


def test_local_intent_parser_distinguishes_redaction_from_cancellation() -> None:
    assert has_local_update_intent(
        "단, 실제 보내기는 접고 내 기기 안에서 완료 상태만 남긴다."
    )
    assert has_local_update_intent(
        "단, 공유 채널로 넘기는 대신 내부 기록을 갱신한다."
    )
    assert not has_local_update_intent(
        "단, 요약 공유는 허용되지만 raw 문장과 위치는 포함하지 않는다."
    )
    assert not has_local_update_intent(
        "이번 턴에서는 보이는 요청과 최신 상태 기록을 함께 적용한다."
    )
