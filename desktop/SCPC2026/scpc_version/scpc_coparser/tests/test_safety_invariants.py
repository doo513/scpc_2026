from __future__ import annotations

import copy

from core.task_view import TaskView
from harness import FinalHarness
from run_submission import run_tasks
from tests.test_generalization import ALL_ACTIONS, answer, task_with_object


def test_task_view_is_an_immutable_snapshot() -> None:
    task = task_with_object(
        prompt="이 자료를 검토해줘.",
        object_type="file",
        attrs={"ref_code": "WM-4101", "contains": ["summary"]},
    )
    view = TaskView(task)

    task["prompt"] = "변조된 요청"
    task["device_state"]["objects"][0]["attrs"]["ref_code"] = "WM-MUTATED"

    assert view.prompt == "이 자료를 검토해줘."
    assert view.objects[0]["attrs"]["ref_code"] == "WM-4101"
    assert set(view.objects_by_ref_code()) == {"WM-4101"}


def test_full_plan_capability_is_checked_before_compilation() -> None:
    task = task_with_object(
        prompt="이 결제 요청을 처리해줘.",
        object_type="payment_request",
        attrs={
            "ref_code": "WM-4102",
            "merchant": "Store",
            "amount": 1000,
            "method": "card_token",
        },
        actions=[action for action in ALL_ACTIONS if action != "read"],
    )

    result = answer(task)
    assert result["control"] == "hold"
    assert all(
        event["verb"] in task["available_actions"]
        for event in result["plan_events"]
    )
    assert result["_trace"]["final_decision"]["capability_status"] == "unavailable"


def test_temporary_toggle_amend_preserves_toggle_semantics() -> None:
    result = answer(
        task_with_object(
            prompt="조명을 켜줘.",
            object_type="device_setting",
            attrs={
                "ref_code": "WM-4103",
                "name": "living_room_light",
                "current": "off",
            },
            records=[
                {
                    "id": "temporary_override",
                    "type": "temporary_override_allowed",
                    "value": "2h",
                }
            ],
        )
    )

    assert result["control"] == "amend"
    assert [event["verb"] for event in result["plan_events"]][-1] == "toggle"
    assert "dispatch" not in {event["verb"] for event in result["plan_events"]}
    assert result["plan_events"][-1]["args"]["duration"] == "2h"


def test_action_candidate_ids_include_operation_mode() -> None:
    task = task_with_object(
        prompt="이 결제를 결제하고 바로 취소해줘.",
        object_type="payment_request",
        attrs={
            "ref_code": "WM-4104",
            "merchant": "Store",
            "amount": 1000,
            "method": "card_token",
        },
        actions=list(ALL_ACTIONS) + ["cancel"],
    )

    result = answer(task)
    evaluations = result["_trace"]["decision_matrix"]["evaluations"]
    ids = [item["candidate_id"] for item in evaluations]
    assert len(ids) == len(set(ids))
    assert "dispatch" not in {event["verb"] for event in result["plan_events"]}


def test_held_memory_write_is_not_committed() -> None:
    harness = FinalHarness()
    session: dict[str, object] = {}
    task = task_with_object(
        prompt=(
            "사용자 메모리에 이 내용을 저장해줘. "
            "단, 실행하지 말고 중단해야 한다."
        ),
        object_type="personal_note",
        attrs={"ref_code": "WM-4105", "contains": ["preference"]},
        records=[
            {
                "id": "memory_write",
                "type": "persistent_memory_write",
                "value": {
                    "memory_key": "blocked_memory",
                    "person": "alpha",
                    "preferred_channel": "private_channel",
                },
            }
        ],
    )

    result = harness.answer_task(copy.deepcopy(task), session)
    assert result["control"] == "hold"
    assert "blocked_memory" not in harness.memory_store.snapshot()


def test_same_turn_siblings_do_not_read_each_others_session_state() -> None:
    first = task_with_object(
        prompt="이 자료를 channel_a에 보내줘.",
        object_type="message",
        attrs={"ref_code": "WM-BRANCH-A", "recipient": "channel_a"},
        task_id="branch_a",
    )
    second = task_with_object(
        prompt="같은 곳에 이 자료를 보내줘.",
        object_type="file",
        attrs={"ref_code": "WM-BRANCH-B"},
        task_id="branch_b",
    )

    payload = run_tasks([first, second])

    assert payload["answers"]["branch_b"]["control"] == "ask"
    lifecycle = {
        trace["task_id"]: trace["session_lifecycle"]
        for trace in payload["_traces"]
    }
    assert lifecycle["branch_a"]["commit_status"] == (
        "isolated_uncommitted_branch"
    )
    assert lifecycle["branch_b"]["commit_status"] == (
        "isolated_uncommitted_branch"
    )


def test_multi_operation_request_is_not_reduced_to_one_execution() -> None:
    result = answer(
        task_with_object(
            prompt=(
                "사용자 메모리에 이 내용을 저장해줘. "
                "그리고 이 자료를 channel_a에 보내줘."
            ),
            object_type="message",
            attrs={"ref_code": "WM-BUNDLE", "recipient": "channel_a"},
        )
    )

    bundle = result["_trace"]["decision_matrix"]["operation_bundle"]
    assert bundle["status"] == "multiple_unresolved"
    assert result["control"] == "ask"
    assert not {
        "dispatch",
        "update",
        "pay",
        "toggle",
        "schedule",
    }.intersection(event["verb"] for event in result["plan_events"])
