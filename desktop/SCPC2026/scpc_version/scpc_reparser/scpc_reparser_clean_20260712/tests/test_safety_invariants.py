from __future__ import annotations

import copy

import pytest

from core.consistency import ConsistencyValidator
from core.decision import DecisionEngine, FinalDecision
from core.session_state import MemoryStore
from core.state import StateAssembler
from core.task_view import TaskView
from harness import FinalHarness
from run_submission import run_tasks
from tests.test_generalization import ALL_ACTIONS, answer, task_with_object


def _immutable_decision_authority(task: dict[str, object]) -> FinalDecision:
    view = TaskView(task)
    state = StateAssembler.assemble(view, MemoryStore(), {})
    _matrix, decision = DecisionEngine.decide(state)
    return decision


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

    with pytest.raises(
        ValueError,
        match="required plan capability is unavailable: read",
    ):
        answer(task)


def test_temporary_toggle_amend_uses_canonical_minimal_disclosure_plan() -> None:
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
    assert result["content_scope"]["mode"] == "status_only"
    assert [event["verb"] for event in result["plan_events"]] == [
        "read",
        "verify",
        "toggle",
    ]
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


def test_alias_only_memory_record_never_reparses_prompt_during_commit() -> None:
    harness = FinalHarness()
    task = task_with_object(
        prompt=(
            "사용자 메모리에 저장해줘. 홍길동은 피하고 서울병원은 제외. "
            "실패 기록은 결제실패이고 기업 기본 규정은 외부공유금지이고 "
            "승인 채널은 보안검토로 기억해."
        ),
        object_type="personal_note",
        attrs={"ref_code": "WM-ALIAS-ONLY"},
        records=[
            {
                "id": "memory_write",
                "type": "persistent_memory_write",
                "value": "korean_alias",
            }
        ],
    )

    result = harness.answer_task(task, {})

    assert result["_trace"]["commit"]["validation_status"] == "passed"
    assert "korean_alias" not in harness.memory_store.snapshot()


def test_structured_korean_memory_fields_commit_without_prompt_reparsing() -> None:
    harness = FinalHarness()
    task = task_with_object(
        prompt="이 구조화된 사용자 메모리를 저장해줘.",
        object_type="personal_note",
        attrs={"ref_code": "WM-STRUCTURED-KO"},
        records=[
            {
                "id": "memory_write",
                "type": "persistent_memory_write",
                "value": {
                    "memory_key": "korean_structured",
                    "person": "홍길동",
                    "avoid": "야간외출",
                    "preferred_channel": "보안검토",
                },
            }
        ],
    )

    harness.answer_task(task, {})

    assert harness.memory_store.snapshot()["korean_structured"] == {
        "memory_key": "korean_structured",
        "person": "홍길동",
        "avoid": "야간외출",
        "preferred_channel": "보안검토",
    }


def test_validator_rejects_every_execution_verb_under_hold() -> None:
    task = task_with_object(
        prompt="이 자료를 보내지 말고 중단해줘.",
        object_type="message",
        attrs={"ref_code": "WM-HOLD-VALIDATION", "recipient": "channel_a"},
    )
    result = FinalHarness().answer_task(copy.deepcopy(task), {}, commit=False)
    trace = copy.deepcopy(result["_trace"])
    public = {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if not key.startswith("_")
    }
    tampered_events = [
        {
            "verb": "read",
            "target": public["focal_id"],
            "args": {"purpose": "invalidated_precondition"},
        },
        {
            "verb": "update",
            "target": public["focal_id"],
            "args": {"state": "must_not_execute"},
        },
    ]
    public["plan_events"] = tampered_events
    trace["final_decision"]["plan_steps"] = tampered_events
    trace["final_decision"]["final_plan_capabilities"] = [
        "read",
        "update",
    ]
    authority = _immutable_decision_authority(task)

    with pytest.raises(ValueError, match="hold must.*not execute"):
        ConsistencyValidator.validate_strict(
            public,
            TaskView(task),
            trace,
            authority,
        )


def test_validator_rejects_scope_and_serialized_trace_tampering_together() -> None:
    task = task_with_object(
        prompt="이 자료를 channel_a에 보내줘.",
        object_type="file",
        attrs={"ref_code": "WM-SCOPE-LOCK", "contains": ["summary"]},
        records=[
            {
                "id": "resolved_scope_target",
                "type": "resolved_target",
                "value": "channel_a",
            }
        ],
    )
    result = FinalHarness().answer_task(copy.deepcopy(task), {}, commit=False)
    trace = copy.deepcopy(result["_trace"])
    authority = _immutable_decision_authority(task)
    public = {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if not key.startswith("_")
    }
    assert authority.effective_blueprint.scope_mode == "summary"
    public["content_scope"]["mode"] = "raw"
    trace["final_decision"]["disclosure"]["mode"] = "raw"

    with pytest.raises(
        ValueError,
        match="serialized FinalDecision trace differs from authority",
    ):
        ConsistencyValidator.validate_strict(
            public,
            TaskView(task),
            trace,
            authority,
        )


def test_validator_rejects_policy_and_serialized_trace_tampering_together() -> None:
    task = task_with_object(
        prompt="이 자료를 channel_a에 보내줘.",
        object_type="file",
        attrs={"ref_code": "WM-POLICY-LOCK", "contains": ["summary"]},
        records=[
            {
                "id": "resolved_policy_target",
                "type": "resolved_target",
                "value": "channel_a",
            }
        ],
    )
    result = FinalHarness().answer_task(copy.deepcopy(task), {}, commit=False)
    trace = copy.deepcopy(result["_trace"])
    authority = _immutable_decision_authority(task)
    public = {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if not key.startswith("_")
    }
    public["policy"]["violations"] = ["tampered_violation"]
    trace["final_decision"]["violations"] = ["tampered_violation"]

    with pytest.raises(
        ValueError,
        match="serialized FinalDecision trace differs from authority",
    ):
        ConsistencyValidator.validate_strict(
            public,
            TaskView(task),
            trace,
            authority,
        )


@pytest.mark.parametrize(
    "attrs, field_name, expected_source",
    [
        (
            {"ref_code": "WM-UNKNOWN-DECLARED", "contains": ["account_password"]},
            "account_password",
            "contains",
        ),
        (
            {"ref_code": "WM-UNKNOWN-ATTR", "account_password": "secret"},
            "account_password",
            "direct_attr",
        ),
        (
            {"ref_code": "WM-NOVEL-DECLARED", "contains": ["novel_field_123"]},
            "novel_field_123",
            "contains",
        ),
        (
            {"ref_code": "WM-NOVEL-ATTR", "novel_field_123": "secret"},
            "novel_field_123",
            "direct_attr",
        ),
    ],
)
def test_unknown_properties_fail_closed_with_typed_provenance(
    attrs: dict[str, object],
    field_name: str,
    expected_source: str,
) -> None:
    task = task_with_object(
        prompt="이 자료를 channel_a에 보내줘.",
        object_type="file",
        attrs=attrs,
        records=[
            {
                "id": "resolved_unknown_target",
                "type": "resolved_target",
                "value": "channel_a",
            }
        ],
    )
    result = answer(task)
    properties = result["_trace"]["evidence"]["properties"]
    novel = next(item for item in properties if item["name"] == field_name)
    constraints = result["_trace"]["final_decision"]["active_constraints"]

    assert novel["classification"] == "unknown"
    assert novel["source"] == expected_source
    assert novel["subject_id"] == result["focal_id"]
    assert result["control"] == "hold"
    assert result["content_scope"] == {
        "mode": "none",
        "allowed_fields": [],
        "excluded_fields": [field_name],
        "requires_user_confirmation": False,
    }
    assert any(
        item["kind"] == "unknown_property_disclosure"
        and item["severity"] == "hard"
        for item in constraints
    )


def test_known_attrs_only_object_is_not_an_inventory_anomaly() -> None:
    result = answer(
        task_with_object(
            prompt="이 메시지를 channel_a에 보내줘.",
            object_type="message",
            attrs={
                "ref_code": "WM-KNOWN-ATTRS",
                "body": "hello",
                "recipient": "channel_a",
                "thread_id": "thread-1",
            },
            records=[
                {
                    "id": "resolved_known_target",
                    "type": "resolved_target",
                    "value": "channel_a",
                }
            ],
        )
    )

    assert not any(
        item["kind"] == "unknown_property_disclosure"
        for item in result["_trace"]["final_decision"]["active_constraints"]
    )


def test_unknown_object_type_fails_closed_even_with_known_field_name() -> None:
    result = answer(
        task_with_object(
            prompt="이 자료를 channel_a에 보내줘.",
            object_type="novel_object_type",
            attrs={
                "ref_code": "WM-UNKNOWN-TYPE",
                "contains": ["summary"],
            },
            records=[
                {
                    "id": "resolved_unknown_type_target",
                    "type": "resolved_target",
                    "value": "channel_a",
                }
            ],
        )
    )

    summary = next(
        item
        for item in result["_trace"]["evidence"]["properties"]
        if item["name"] == "summary"
    )
    assert summary["classification"] == "unknown"
    assert result["control"] == "hold"
    assert result["content_scope"]["mode"] == "none"
    assert "summary" in result["content_scope"]["excluded_fields"]


def test_empty_contains_cannot_shadow_unknown_fields_inventory() -> None:
    result = answer(
        task_with_object(
            prompt="이 자료를 channel_a에 보내줘.",
            object_type="file",
            attrs={
                "ref_code": "WM-MERGED-INVENTORY",
                "contains": [],
                "fields": ["novel_field_123"],
            },
            records=[
                {
                    "id": "resolved_inventory_target",
                    "type": "resolved_target",
                    "value": "channel_a",
                }
            ],
        )
    )

    novel = next(
        item
        for item in result["_trace"]["evidence"]["properties"]
        if item["name"] == "novel_field_123"
    )
    assert novel["source"] == "fields"
    assert novel["classification"] == "unknown"
    assert result["control"] == "hold"
    assert result["content_scope"]["mode"] == "none"
    assert result["content_scope"]["excluded_fields"] == [
        "novel_field_123"
    ]
    exclusion = result["_trace"]["final_decision"]["disclosure"][
        "exclusion_provenance"
    ][0]
    assert exclusion == {
        "field": "novel_field_123",
        "source_ids": [
            "property:obj_focal:fields:novel_field_123:"
            "scpc.property-metadata.v1"
        ],
        "policy_version": "scpc.policy-exclusion.v1",
        "provenance_id": (
            "policy-exclusion:novel_field_123:scpc.policy-exclusion.v1"
        ),
    }


@pytest.mark.parametrize(
    (
        "attrs",
        "classification",
        "control",
        "mode",
        "constraint_severity",
        "constraint_effect",
    ),
    [
        ({"contains": ["summary"]}, "public", "proceed", "summary", None, None),
        (
            {"contains": ["tone"]},
            "internal",
            "amend",
            "summary",
            "amend",
            "force_summary",
        ),
        (
            {"contains": ["doctor_note"]},
            "restricted",
            "amend",
            "redacted",
            "amend",
            "add_redaction",
        ),
        (
            {"password": "secret-value"},
            "secret",
            "amend",
            "redacted",
            "amend",
            "add_redaction",
        ),
    ],
)
def test_property_classification_derives_disclosure_policy(
    attrs: dict[str, object],
    classification: str,
    control: str,
    mode: str,
    constraint_severity: str | None,
    constraint_effect: str | None,
) -> None:
    result = answer(
        task_with_object(
            prompt="이 자료를 channel_a에 보내줘.",
            object_type="file",
            attrs={"ref_code": "WM-CLASSIFICATION-MATRIX", **attrs},
            records=[
                {
                    "id": "resolved_classification_target",
                    "type": "resolved_target",
                    "value": "channel_a",
                }
            ],
        )
    )
    classified = next(
        item for item in result["_trace"]["evidence"]["properties"]
        if item["classification"] == classification
    )
    constraints = result["_trace"]["final_decision"]["active_constraints"]

    assert classified["classification"] == classification
    assert result["control"] == control
    assert result["content_scope"]["mode"] == mode
    if constraint_severity is None:
        assert not any(
            item["kind"] in {
                "classified_property_disclosure",
                "secret_property_disclosure",
            }
            for item in constraints
        )
    else:
        constraint = next(
            item
            for item in constraints
            if item["parameters"].get("classification") == classification
        )
        assert constraint["severity"] == constraint_severity
        assert constraint["effect"] == constraint_effect


def test_unknown_object_direct_attr_uses_object_type_context() -> None:
    result = answer(
        task_with_object(
            prompt="이 자료를 channel_a에 보내줘.",
            object_type="novel_object_type",
            attrs={"ref_code": "WM-UNKNOWN-DIRECT", "summary": "x"},
            records=[
                {
                    "id": "resolved_unknown_direct_target",
                    "type": "resolved_target",
                    "value": "channel_a",
                }
            ],
        )
    )
    summary = next(
        item
        for item in result["_trace"]["evidence"]["properties"]
        if item["name"] == "summary"
    )

    assert summary["classification"] == "unknown"
    assert summary["source"] == "direct_attr"
    assert result["control"] == "hold"
    assert result["content_scope"]["excluded_fields"] == ["summary"]


def test_validator_rejects_mutable_mapping_as_decision_authority() -> None:
    task = task_with_object(
        prompt="이 자료를 channel_a에 보내줘.",
        object_type="file",
        attrs={"ref_code": "WM-MUTABLE-AUTHORITY", "contains": ["summary"]},
        records=[
            {
                "id": "resolved_mutable_authority_target",
                "type": "resolved_target",
                "value": "channel_a",
            }
        ],
    )
    result = FinalHarness().answer_task(copy.deepcopy(task), {}, commit=False)
    trace = copy.deepcopy(result["_trace"])
    public = {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if not key.startswith("_")
    }
    public["content_scope"]["mode"] = "raw"
    trace["final_decision"]["disclosure"]["mode"] = "raw"
    trace["final_decision"]["effective_blueprint"]["scope_mode"] = "raw"

    with pytest.raises(
        ValueError,
        match="decision authority must be an immutable FinalDecision",
    ):
        ConsistencyValidator.validate_strict(
            public,
            TaskView(task),
            trace,
            trace["final_decision"],
        )


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


def test_validated_sibling_memory_write_is_available_to_later_recall() -> None:
    memory_write = task_with_object(
        prompt="사용자 메모리에 이 내용을 저장해줘.",
        object_type="personal_note",
        attrs={"ref_code": "WM-BRANCH-MEMORY"},
        records=[
            {
                "id": "memory_write",
                "type": "persistent_memory_write",
                "value": {
                    "memory_key": "branch_memory",
                    "person": "alpha",
                    "preferred_channel": "channel_a",
                },
            }
        ],
        task_id="branch_memory_write",
    )
    sibling = task_with_object(
        prompt="이 자료를 검토해줘.",
        object_type="file",
        attrs={"ref_code": "WM-BRANCH-OTHER"},
        task_id="branch_other",
    )
    recall = task_with_object(
        prompt="같은 곳에 이 자료를 보내줘.",
        object_type="file",
        attrs={"ref_code": "WM-LATER-RECALL"},
        records=[
            {
                "id": "memory_recall",
                "type": "persistent_memory_recall",
                "value": {
                    "memory_key": "branch_memory",
                    "person": "alpha",
                },
            }
        ],
        task_id="later_recall",
    )
    for task in (memory_write, sibling):
        task.update(session_id="session_a", turn_index=1)
    recall.update(session_id="session_b", turn_index=2)

    payload = run_tasks([memory_write, sibling, recall])

    assert payload["answers"]["later_recall"]["target"] == "channel_a"
    assert payload["answers"]["later_recall"]["control"] == "proceed"
    write_trace = next(
        trace
        for trace in payload["_traces"]
        if trace["task_id"] == "branch_memory_write"
    )
    assert write_trace["session_lifecycle"]["commit_status"] == (
        "isolated_uncommitted_branch"
    )
    assert write_trace["session_lifecycle"]["memory_commit_status"] == (
        "committed_after_validation"
    )


def test_scope_and_policy_confirmation_are_independent_projections() -> None:
    result = answer(
        task_with_object(
            prompt="이 자료는 외부로 공유하지 말고 내 기기 안에서 상태만 갱신해줘.",
            object_type="message",
            attrs={
                "ref_code": "WM-CONFIRMATION-SPLIT",
                "recipient": "visible_channel",
                "contains": ["raw_quote"],
            },
            records=[
                {
                    "id": "ambiguous_target",
                    "type": "ambiguous_target",
                    "value": "surface_recipient_and_resolved_target_both_recent",
                },
                {
                    "id": "resolved_target",
                    "type": "resolved_target",
                    "value": "project_room",
                },
                {
                    "id": "session_policy",
                    "type": "session_share_policy",
                    "value": "strict",
                },
                {
                    "id": "route_candidates",
                    "type": "route_candidate_snapshot",
                    "value": "single_internal_candidate",
                },
                {
                    "id": "dispatch_authority",
                    "type": "dispatch_authority_check",
                    "value": "internal_binding_confirmed",
                },
                {
                    "id": "share_boundary",
                    "type": "share_boundary_update",
                    "value": "local_update_boundary",
                },
            ],
        )
    )

    assert result["control"] == "proceed"
    assert result["content_scope"]["requires_user_confirmation"] is False
    assert result["policy"]["requires_confirmation"] is True
    assert result["_trace"]["final_decision"][
        "policy_requires_confirmation"
    ] is True


def test_ask_preserves_compiled_redaction_scope_without_executing() -> None:
    result = answer(
        task_with_object(
            prompt="이 자료를 channel_a에 보내기 전에 사용자에게 확인해줘.",
            object_type="file",
            attrs={
                "ref_code": "WM-ASK-SCOPE",
                "contains": ["doctor_note"],
            },
            records=[
                {
                    "id": "resolved_target",
                    "type": "resolved_target",
                    "value": "channel_a",
                }
            ],
        )
    )

    assert result["control"] == "ask"
    assert result["content_scope"] == {
        "mode": "redacted",
        "allowed_fields": ["summary"],
        "excluded_fields": ["doctor_note"],
        "requires_user_confirmation": True,
    }
    assert [event["verb"] for event in result["plan_events"]] == [
        "read",
        "clarify",
    ]
    assert not {
        "dispatch",
        "update",
        "schedule",
        "toggle",
        "pay",
    } & {event["verb"] for event in result["plan_events"]}


def test_hold_plan_reads_invalidated_precondition_before_guarding() -> None:
    result = answer(
        task_with_object(
            prompt="이 자료를 보내지 말고 중단해줘.",
            object_type="message",
            attrs={"ref_code": "WM-HOLD-PLAN", "recipient": "channel_a"},
        )
    )

    assert result["control"] == "hold"
    assert result["plan_events"] == [
        {
            "verb": "read",
            "target": "obj_focal",
            "args": {"purpose": "invalidated_precondition"},
        },
        {
            "verb": "guard",
            "target": "obj_focal",
            "args": {"reason": "precondition_invalidated"},
        },
    ]


def test_redaction_uses_aggregate_argument_for_multiple_sensitive_fields() -> None:
    result = answer(
        task_with_object(
            prompt="민감정보를 가리고 channel_a에 보내줘.",
            object_type="message",
            attrs={
                "ref_code": "WM-AGGREGATE-REDACTION",
                "recipient": "channel_a",
                "contains": ["name", "raw_quote", "numeric_value"],
            },
            records=[
                {
                    "id": "external_policy",
                    "type": "external_share_policy",
                    "value": "raw_sensitive_forbidden",
                }
            ],
        )
    )

    redact = next(
        event for event in result["plan_events"] if event["verb"] == "redact"
    )
    assert result["content_scope"]["excluded_fields"] == [
        "name",
        "numeric_value",
        "raw_quote",
    ]
    assert redact["args"] == {"remove": "sensitive_fields"}


def test_hard_blocked_dispatch_can_only_select_nonexecuting_clarification() -> None:
    result = answer(
        task_with_object(
            prompt=(
                "오늘 건강 기록을 공유해줘. 단, 누구에게 어떤 범위로 "
                "처리할지 먼저 사용자에게 확인해줘."
            ),
            object_type="health_record",
            attrs={"ref_code": "WM-HEALTH-ASK", "status": "current"},
            records=[
                {
                    "id": "resolved_target",
                    "type": "resolved_target",
                    "value": "caregiver",
                },
                {
                    "id": "external_policy",
                    "type": "external_share_policy",
                    "value": "doctor_note_forbidden",
                },
            ],
        )
    )

    assert result["control"] == "ask"
    assert result["target"] == "user"
    assert [event["verb"] for event in result["plan_events"]] == [
        "read",
        "clarify",
    ]
    constraints = result["_trace"]["final_decision"]["active_constraints"]
    assert any(
        item["kind"] == "health_external_share_blocked"
        and item["severity"] == "hard"
        for item in constraints
    )


def test_typed_local_boundary_selects_local_operation_upstream() -> None:
    result = answer(
        task_with_object(
            prompt=(
                "원본과 익명 요약 중 현재 자료를 고르고 보내도 되는 "
                "범위와 보류 여부를 판정해줘."
            ),
            object_type="file",
            attrs={
                "ref_code": "WM-LOCAL-BOUNDARY",
                "contains": ["summary", "raw_quote", "name", "rrn", "amount"],
            },
            records=[
                {
                    "id": "resolved_target",
                    "type": "resolved_target",
                    "value": "project_room",
                },
                {
                    "id": "share_boundary",
                    "type": "share_boundary_update",
                    "value": "local_update_boundary",
                },
            ],
        )
    )

    assert result["control"] == "proceed"
    assert result["target"] == "project_room"
    assert result["_trace"]["final_decision"]["action"] == "local_update"
    assert [event["verb"] for event in result["plan_events"]] == [
        "read",
        "verify",
        "update",
    ]


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
