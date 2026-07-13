from __future__ import annotations

import copy
from dataclasses import fields
import inspect
from pathlib import Path
import pytest

from build_manifest import sha256_file
from core.decision import CandidateEvaluation, FinalDecision
from core.consistency import ConsistencyValidator
from core.evidence_graph import EvidenceGraph
from core.session_state import MemoryStore
from core.state import StateAssembler
from core.task_view import TaskView
from harness import FinalHarness
from rules.focal import FocalResolver
from rules.plan import PlanCompiler
from rules.scope_policy import PolicyCompiler, ScopeCompiler
from tests.test_generalization import ALL_ACTIONS, answer, task_with_object
from utils.io import find_data_dir


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_final_decision_is_the_only_control_owner_and_pipeline_is_linear() -> None:
    candidate_fields = {field.name for field in fields(CandidateEvaluation)}
    final_fields = {field.name for field in fields(FinalDecision)}
    harness_source = (PROJECT_ROOT / "harness.py").read_text(encoding="utf-8")

    assert "control" not in candidate_fields
    assert "control" in final_fields
    assert "ActionProfile" not in harness_source
    assert "TargetResolver.finalize" not in harness_source
    assert harness_source.index("DecisionEngine.decide") < harness_source.index(
        "ScopeCompiler.compile"
    )
    assert harness_source.index("ScopeCompiler.compile") < harness_source.index(
        "PolicyCompiler.compile"
    )
    assert harness_source.index("PolicyCompiler.compile") < harness_source.index(
        "PlanCompiler.compile"
    )
    assert not (PROJECT_ROOT / "rules/action_profile.py").exists()


def test_output_compilers_are_pure_final_decision_projections() -> None:
    for compiler in (ScopeCompiler, PolicyCompiler, PlanCompiler):
        parameters = tuple(inspect.signature(compiler.compile).parameters)
        assert parameters == ("decision",)
        source = inspect.getsource(compiler)
        for prohibited in (
            "latest_record_value",
            "EvidenceGraph",
            "DecisionMatrix",
            "CandidateEvaluator",
            "view.prompt",
        ):
            assert prohibited not in source


def test_state_assembly_extracts_evidence_and_relations_once() -> None:
    source = inspect.getsource(StateAssembler.assemble)

    assert source.count("EvidenceGraph.from_view") == 1
    assert source.count("RelationGraph(view)") == 1
    assert "relation_graph=relation_graph" in source
    assert "evidence.with_focal" in source


def test_unresolved_operation_is_not_defaulted_to_dispatch() -> None:
    result = answer(
        task_with_object(
            prompt="자료입니다.",
            object_type="file",
            attrs={"ref_code": "WM-UNRESOLVED"},
        )
    )

    final = result["_trace"]["final_decision"]
    assert (final["action"], final["operation_mode"]) == (
        "unresolved",
        "unresolved",
    )
    assert result["control"] == "ask"
    assert result["_trace"]["state"]["target_candidates"] == []
    assert "dispatch" not in {
        event["verb"] for event in result["plan_events"]
    }


def test_validator_rejects_output_that_differs_from_locked_decision() -> None:
    task = task_with_object(
        prompt="이 자료를 channel_a에 보내줘.",
        object_type="message",
        attrs={"ref_code": "WM-LOCK", "recipient": "channel_a"},
    )
    raw = FinalHarness().answer_task(copy.deepcopy(task), {})
    trace = raw["_trace"]
    public = {
        key: value for key, value in raw.items() if not key.startswith("_")
    }
    public["target"] = "tampered_target"

    with pytest.raises(ValueError, match="FinalDecision"):
        ConsistencyValidator.validate_or_warn(
            public,
            TaskView(task),
            trace,
            trace,
        )


def test_domain_operation_matrix_keeps_context_for_cancel_verify_and_share() -> None:
    payment = task_with_object(
        prompt="이 결제 요청을 처리해줘.",
        object_type="payment_request",
        attrs={
            "ref_code": "WM-2001",
            "merchant": "Store",
            "amount": 1000,
            "method": "card_token",
        },
    )
    executed = answer(payment)
    assert executed["_trace"]["final_decision"]["action"] == "pay"
    assert executed["_trace"]["final_decision"]["operation_mode"] == "execute"
    assert [event["verb"] for event in executed["plan_events"]][-1] == "pay"

    cancelled_task = copy.deepcopy(payment)
    cancelled_task["prompt"] = "예약된 결제 요청 건을 취소해줘."
    cancelled = answer(cancelled_task)
    cancel_decision = cancelled["_trace"]["final_decision"]
    cancel_trace = cancelled["_trace"]["decision_matrix"]["domain_promotion"][0]
    assert (cancel_decision["action"], cancel_decision["operation_mode"]) == (
        "pay",
        "cancel",
    )
    assert cancelled["control"] == "hold"
    assert cancel_trace["domain_context_applied"] is True
    assert cancel_trace["promotion_rejected_reason"] == (
        "UNSUPPORTED_OPERATION_BLUEPRINT"
    )
    assert "dispatch" not in {event["verb"] for event in cancelled["plan_events"]}

    verified = answer(
        task_with_object(
            prompt="기기 설정 바꾼 것을 확인해줘.",
            object_type="device_setting",
            attrs={"ref_code": "WM-2002", "name": "wifi", "target": "wifi"},
        )
    )
    verify_decision = verified["_trace"]["final_decision"]
    assert (verify_decision["action"], verify_decision["operation_mode"]) == (
        "toggle",
        "verify",
    )
    assert [event["verb"] for event in verified["plan_events"]] == [
        "read",
        "verify",
    ]

    shared = answer(
        task_with_object(
            prompt="이 일정 내용을 caregiver에게 보내줘.",
            object_type="calendar_event",
            attrs={
                "ref_code": "WM-2003",
                "attendee": "caregiver",
                "time": "10:00",
            },
        )
    )
    assert shared["_trace"]["state"]["domain_context"]["family"] == "calendar"
    assert shared["_trace"]["final_decision"]["action"] == "dispatch"
    assert "schedule" not in {event["verb"] for event in shared["plan_events"]}


def test_information_and_capability_are_independent_axes() -> None:
    base = task_with_object(
        prompt="이 결제 요청을 처리해줘.",
        object_type="payment_request",
        attrs={
            "ref_code": "WM-2004",
            "merchant": "Store",
            "amount": 1000,
            "method": "card_token",
        },
    )
    no_capability = copy.deepcopy(base)
    no_capability["available_actions"] = [
        action for action in ALL_ACTIONS if action != "pay"
    ]
    blocked = answer(no_capability)
    blocked_decision = blocked["_trace"]["final_decision"]
    assert blocked_decision["information_status"] == "complete"
    assert blocked_decision["capability_status"] == "unavailable"
    assert "capability_unavailable" not in {
        item["kind"] for item in blocked_decision["active_constraints"]
    }

    missing_amount = copy.deepcopy(base)
    del missing_amount["device_state"]["objects"][0]["attrs"]["amount"]
    incomplete = answer(missing_amount)["_trace"]["final_decision"]
    assert incomplete["information_status"] == "missing"
    assert incomplete["capability_status"] == "available"


def test_domain_cancel_with_mismatched_focal_clarifies_without_dispatch() -> None:
    mismatched = answer(
        task_with_object(
            prompt="예약된 결제 요청 건을 취소해줘.",
            object_type="file",
            attrs={"ref_code": "WM-2008", "contains": ["summary"]},
        )
    )
    assert mismatched["control"] == "ask"
    assert mismatched["_trace"]["final_decision"]["action"] == "clarify"
    assert "dispatch" not in {
        event["verb"] for event in mismatched["plan_events"]
    }
    assert any(
        item["promotion_rejected_reason"] == "FOCAL_DOMAIN_MISMATCH"
        for item in mismatched["_trace"]["decision_matrix"][
            "domain_promotion"
        ]
    )


def test_constraint_counterfactual_changes_only_the_affected_pair() -> None:
    task = task_with_object(
        prompt="이 기록을 공유해줘. 단, 외부 전송은 취소하고 내부 상태만 갱신해줘.",
        object_type="message",
        attrs={"ref_code": "WM-2005", "recipient": "caregiver"},
        records=[{"id": "consent", "type": "consent", "value": "revoked"}],
    )
    constrained = answer(task)
    evaluations = constrained["_trace"]["decision_matrix"]["evaluations"]
    dispatch = [item for item in evaluations if item["action"] == "dispatch"]
    local = [item for item in evaluations if item["action"] == "local_update"]
    assert dispatch and all(
        "consent_revoked" in item["active_constraints"] for item in dispatch
    )
    assert local and all(
        "consent_revoked" not in item["active_constraints"] for item in local
    )

    unconstrained_task = copy.deepcopy(task)
    unconstrained_task["device_state"]["records"] = [
        item
        for item in unconstrained_task["device_state"]["records"]
        if item["type"] != "consent"
    ]
    unconstrained = answer(unconstrained_task)
    assert unconstrained["control"] == constrained["control"] == "proceed"


def test_session_snapshot_restores_deleted_focal_without_executing() -> None:
    harness = FinalHarness()
    session: dict[str, object] = {}
    first = task_with_object(
        prompt="이 자료를 caregiver에게 보내줘.",
        object_type="message",
        attrs={"ref_code": "WM-2006", "recipient": "caregiver"},
    )
    first_result = harness.answer_task(first, session)
    assert first_result["focal_id"] == "obj_focal"

    second = {
        "schema": "scpc.final.task.v1",
        "id": "deleted_followup",
        "session_id": "synthetic_session",
        "turn_index": 2,
        "prompt": "방금 지운 거 왜 지웠어? 그거부터 확인해줘.",
        "visible_history": [],
        "personal_memory": [],
        "available_actions": list(ALL_ACTIONS),
        "device_state": {"objects": [], "records": []},
    }
    restored = harness.answer_task(second, session)
    assert restored["focal_id"] == "obj_focal"
    assert restored["control"] == "ask"
    assert restored["_trace"]["final_decision"]["historical_focal"] is True
    assert not (
        {"dispatch", "update", "schedule", "toggle", "pay"}
        & {event["verb"] for event in restored["plan_events"]}
    )

    isolated = StateAssembler.assemble(
        TaskView(second, {}), MemoryStore(), {}
    )
    assert isolated.focal_decision.focal_id == ""


def test_focal_resolution_ablation_distinguishes_marker_and_history_evidence() -> None:
    marker_task = task_with_object(
        prompt="이 자료를 보내줘.",
        object_type="file",
        attrs={"ref_code": "WM-2007"},
    )
    marker_task["visible_history"] = [
        {"turn": 1, "summary": "기준 참조는 WM-9999"}
    ]
    marker_view = TaskView(marker_task)
    with_history = FocalResolver.resolve_decision(
        marker_view, EvidenceGraph.from_view(marker_view), {}
    )
    marker_task["visible_history"] = []
    without_history_view = TaskView(marker_task)
    without_history = FocalResolver.resolve_decision(
        without_history_view,
        EvidenceGraph.from_view(without_history_view),
        {},
    )
    assert with_history.focal_id == without_history.focal_id == "obj_focal"

    history_task = {
        "schema": "scpc.final.task.v1",
        "id": "history_only_focal",
        "session_id": "history_session",
        "turn_index": 1,
        "prompt": "이 자료를 보내줘.",
        "visible_history": [
            {"turn": 1, "summary": "현재 요청의 기준 참조는 WM-3002"}
        ],
        "personal_memory": [],
        "available_actions": list(ALL_ACTIONS),
        "device_state": {
            "objects": [
                {"id": "a", "type": "file", "attrs": {"ref_code": "WM-3001"}},
                {"id": "b", "type": "file", "attrs": {"ref_code": "WM-3002"}},
            ],
            "records": [],
        },
    }
    history_view = TaskView(history_task)
    resolved = FocalResolver.resolve_decision(
        history_view, EvidenceGraph.from_view(history_view), {}
    )
    assert resolved.focal_id == "b"
    history_task["visible_history"] = []
    ablated_view = TaskView(history_task)
    ablated = FocalResolver.resolve_decision(
        ablated_view, EvidenceGraph.from_view(ablated_view), {}
    )
    assert ablated.focal_id == ""


def test_intent_evidence_ablation_changes_operation_but_not_focal() -> None:
    redirected_task = task_with_object(
        prompt=(
            "이 자료를 caregiver에게 보내줘. "
            "단, 외부 전송은 취소하고 내부 상태만 갱신해줘."
        ),
        object_type="message",
        attrs={"ref_code": "WM-2009", "recipient": "caregiver"},
    )
    redirected = answer(redirected_task)
    ablated_task = copy.deepcopy(redirected_task)
    ablated_task["prompt"] = "이 자료를 caregiver에게 보내줘."
    ablated = answer(ablated_task)
    assert redirected["focal_id"] == ablated["focal_id"]
    assert redirected["_trace"]["final_decision"]["action"] == "local_update"
    assert ablated["_trace"]["final_decision"]["action"] == "dispatch"
    assert redirected["target"] == "memory_store"
    assert ablated["target"] == "caregiver"


def test_official_submission_schema_is_the_applied_local_schema() -> None:
    data_dir = find_data_dir()
    official = data_dir / "submission_schema.json"
    if not official.is_file():
        official = data_dir.parent / "submission_schema.json"
    local = PROJECT_ROOT / "submission_schema.json"
    assert official.read_bytes() == local.read_bytes()
    assert sha256_file(official) == sha256_file(local)


def test_runtime_has_no_task_person_or_full_prompt_answer_table() -> None:
    runtime_files = [
        path
        for root in (PROJECT_ROOT / "core", PROJECT_ROOT / "rules")
        for path in root.glob("*.py")
    ] + [PROJECT_ROOT / "harness.py"]
    runtime = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)
    for prohibited in (
        "final_dev_",
        "final_screening_",
        "jimin",
        "minho",
        "seoyeon",
        "mem_profile_",
    ):
        assert prohibited not in runtime
