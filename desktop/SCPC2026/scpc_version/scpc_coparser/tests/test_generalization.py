from __future__ import annotations

import copy
from dataclasses import fields
import json
from pathlib import Path

from core.decision import (
    CandidateDisposition,
    CandidateEvaluation,
    CandidateEvaluator,
    FallbackEdge,
)
from core.evidence import (
    EvidenceKind,
    IntentEvidence,
    IntentEvidenceExtractor,
    latest_clause_from_text,
)
from core.evidence_graph import EvidenceGraph
from core.relations import RelationGraph
from core.task_view import TaskView
from harness import FinalHarness
from rules.target import TargetCandidate
from utils.io import find_data_dir, load_jsonl


PROJECT_ROOT = Path(__file__).resolve().parents[1]
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


def marker_records(ref_code: str) -> list[dict[str, object]]:
    return [
        {
            "id": "rec_markers",
            "type": "focal_marker_refs",
            "value": {"marker_to_ref": {"marker_alpha": ref_code}},
        },
        {
            "id": "rec_trace",
            "type": "focal_resolution_trace",
            "value": {
                "latest_phase": "draft",
                "phase_to_marker": {"draft": "marker_alpha"},
            },
        },
    ]


def task_with_object(
    *,
    prompt: str,
    object_type: str,
    attrs: dict[str, object],
    actions: list[str] | None = None,
    records: list[dict[str, object]] | None = None,
    task_id: str = "synthetic",
) -> dict[str, object]:
    ref_code = str(attrs.get("ref_code") or "WM-1000")
    attrs = {**attrs, "ref_code": ref_code}
    return {
        "schema": "scpc.final.task.v1",
        "id": task_id,
        "session_id": "synthetic_session",
        "turn_index": 1,
        "prompt": prompt,
        "visible_history": [],
        "personal_memory": [],
        "available_actions": actions or list(ALL_ACTIONS),
        "device_state": {
            "objects": [{"id": "obj_focal", "type": object_type, "attrs": attrs}],
            "records": marker_records(ref_code) + list(records or []),
        },
    }


def answer(task: dict[str, object]) -> dict[str, object]:
    return FinalHarness().answer_task(task, {})


def selected_evaluation(result: dict[str, object]) -> dict[str, object]:
    matrix = result["_trace"]["decision_matrix"]
    return next(
        item
        for item in matrix["evaluations"]
        if item["candidate_id"] == matrix["selected_candidate"]
    )


def test_versioned_spec_is_tied_to_reference_manifest() -> None:
    spec = json.loads(
        (PROJECT_ROOT / "tests/specs/generalization_v1.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (PROJECT_ROOT / spec["baseline_manifest"]).read_text(encoding="utf-8")
    )
    assert spec["spec_version"] == "2.0.0"
    assert spec["baseline_source_tree_sha256"] == manifest["baseline"]["source_tree_sha256"]
    assert spec["dev_hard_gate"]["score_exclusions_allowed"] is False
    assert spec["regression_policy"]["official_reference_is_primary"] is True


def test_connector_boundary_does_not_split_lexical_suffix() -> None:
    assert latest_clause_from_text("가능할 듯하지만 아직 실행 근거는 없다.") == ("", None)
    clause, span = latest_clause_from_text("자료를 검토한다. 하지만 실행은 멈춰야 한다.")
    assert clause.startswith("하지만")
    assert span is not None


def test_clause_scope_prevents_cross_sentence_clarification() -> None:
    task = task_with_object(
        prompt=(
            "세션 상태를 확인해서 처리해줘. "
            "장기 사용자 메모리를 저장해줘."
        ),
        object_type="personal_note",
        attrs={"ref_code": "WM-1001", "contains": ["preference"]},
    )
    evidence = IntentEvidenceExtractor.extract(TaskView(task))
    assert evidence.current(EvidenceKind.MEMORY_WRITE_REQUEST)
    assert not evidence.current(EvidenceKind.CLARIFICATION_REQUEST)


def test_canonical_group_retains_current_and_history_provenance() -> None:
    latest = "단, 외부로 전달하지 말고 내부 상태만 갱신해줘."
    task = task_with_object(
        prompt=f"자료를 보내줘. {latest}",
        object_type="message",
        attrs={"ref_code": "WM-1002", "recipient": "caregiver"},
    )
    task["visible_history"] = [{"turn": 1, "summary": latest}]
    evidence = IntentEvidenceExtractor.extract(TaskView(task))
    members = {item.evidence_id: item for item in evidence.evidence}
    matching = [
        group
        for group in evidence.groups
        if any(members[item_id].provenance.source_kind == "current_prompt" for item_id in group.member_ids)
        and any(members[item_id].provenance.source_kind == "visible_history" for item_id in group.member_ids)
    ]
    assert matching
    assert matching[0].current_prompt_reasserted is True
    assert matching[0].quoted_or_reported is True
    assert all(members[item_id].provenance.span is not None for item_id in matching[0].member_ids)


def test_derived_decisions_do_not_claim_direct_provenance() -> None:
    evidence_fields = {field.name for field in fields(IntentEvidence)}
    decision_fields = {field.name for field in fields(CandidateEvaluation)}
    assert "provenance" in evidence_fields
    assert "derived_from" in decision_fields
    assert not ({"source", "turn", "span", "provenance"} & decision_fields)


def test_consent_is_scoped_to_dispatch_not_local_update() -> None:
    task = task_with_object(
        prompt=(
            "이 기록을 caregiver에게 공유해줘. "
            "단, 외부 전달은 취소하고 내 기기 내부 상태만 갱신해줘."
        ),
        object_type="message",
        attrs={"ref_code": "WM-1003", "recipient": "caregiver"},
        records=[{"id": "rec_consent", "type": "consent", "value": "revoked"}],
    )
    result = answer(task)
    matrix = result["_trace"]["decision_matrix"]
    local = [item for item in matrix["evaluations"] if item["action"] == "local_update"]
    dispatch = [item for item in matrix["evaluations"] if item["action"] == "dispatch"]
    assert result["control"] == "proceed"
    assert local and all("consent_revoked" not in item["active_constraints"] for item in local)
    assert dispatch and all("consent_revoked" in item["active_constraints"] for item in dispatch)


def test_pay_promotion_capability_and_missing_slot_axes() -> None:
    base = task_with_object(
        prompt="이 결제 요청을 처리해줘.",
        object_type="payment_request",
        attrs={
            "ref_code": "WM-1004",
            "merchant": "Store",
            "amount": 48000,
            "method": "card_token",
        },
    )
    promoted = answer(base)
    trace = promoted["_trace"]["decision_matrix"]["domain_promotion"][0]
    assert promoted["control"] == "proceed"
    assert trace["promotion_eligible"] is trace["promotion_applied"] is True

    no_capability = copy.deepcopy(base)
    no_capability["available_actions"].remove("pay")
    blocked = answer(no_capability)
    blocked_trace = blocked["_trace"]["decision_matrix"]["domain_promotion"][0]
    assert blocked["control"] == "hold"
    assert blocked_trace["promotion_rejected_reason"] == "CAPABILITY_UNAVAILABLE"

    no_amount = copy.deepcopy(base)
    del no_amount["device_state"]["objects"][0]["attrs"]["amount"]
    missing = answer(no_amount)
    missing_trace = missing["_trace"]["decision_matrix"]["domain_promotion"][0]
    assert missing["control"] == "ask"
    assert missing_trace["promotion_rejected_reason"] == "REQUIRED_SLOT_MISSING"

    merchant_mismatch = copy.deepcopy(base)
    merchant_mismatch["device_state"]["records"].append(
        {
            "id": "rec_subscription",
            "type": "trusted_subscription",
            "value": "DifferentStore",
        }
    )
    mismatch = answer(merchant_mismatch)
    assert mismatch["control"] == "ask"
    assert "trusted_subscription_mismatch" in selected_evaluation(mismatch)["active_constraints"]

    security_alert = copy.deepcopy(base)
    security_alert["device_state"]["records"].append(
        {"id": "rec_security", "type": "security_alert", "value": "active"}
    )
    secured = answer(security_alert)
    assert secured["control"] == "hold"
    assert "security_alert" in selected_evaluation(secured)["active_constraints"]


def test_domain_focal_mismatch_is_traced_without_promotion() -> None:
    task = task_with_object(
        prompt="저장된 선호 선물을 결제해줘.",
        object_type="personal_note",
        attrs={"ref_code": "WM-1005", "contains": ["gift_hint"]},
    )
    result = answer(task)
    promotion = result["_trace"]["decision_matrix"]["domain_promotion"][0]
    assert result["_trace"]["decision_matrix"]["selected_action"] != "pay"
    assert promotion["promotion_rejected_reason"] == "FOCAL_DOMAIN_MISMATCH"


def test_equal_executable_targets_require_user_choice() -> None:
    task = task_with_object(
        prompt="이 자료를 보내줘.",
        object_type="file",
        attrs={"ref_code": "WM-1006", "contains": ["summary"]},
    )
    view = TaskView(task)
    graph = EvidenceGraph.from_view(view, "obj_focal")
    matrix = CandidateEvaluator.build_matrix(
        view,
        graph,
        view.objects_by_id()["obj_focal"],
        (
            TargetCandidate("channel_a", "explicit_a", "high"),
            TargetCandidate("channel_b", "explicit_b", "high"),
        ),
    )
    assert (
        matrix.selection.disposition
        == CandidateDisposition.NEEDS_CLARIFICATION
    )
    assert any(
        gate.kind == "multiple_executable_alternatives"
        for gate in matrix.selection.gates
    )


def test_capability_fallback_zero_one_and_many_alternatives() -> None:
    actions = [action for action in ALL_ACTIONS if action != "update"]
    no_fallback = task_with_object(
        prompt="사용자 메모리에 이 내용을 저장해줘.",
        object_type="personal_note",
        attrs={"ref_code": "WM-1008", "contains": ["preference"]},
        actions=actions,
    )
    blocked = answer(no_fallback)
    assert blocked["control"] == "hold"
    assert selected_evaluation(blocked)["capability_status"] == "unavailable"

    independent_request = task_with_object(
        prompt="사용자 메모리에 이 내용을 저장해줘. 이 자료를 채널에 공유해줘.",
        object_type="message",
        attrs={"ref_code": "WM-1009", "recipient": "channel_a"},
        actions=actions,
    )
    independent = answer(independent_request)
    assert independent["control"] == "hold"
    assert independent["_trace"]["decision_matrix"]["fallback"]["reason"] == (
        "NO_AUTHORIZED_FALLBACK"
    )

    one_fallback = task_with_object(
        prompt=(
            "사용자 메모리에 이 내용을 저장해줘. "
            "저장할 수 없으면 대신 이 자료를 채널에 공유해줘."
        ),
        object_type="message",
        attrs={"ref_code": "WM-1009", "recipient": "channel_a"},
        actions=actions,
    )
    fallback = answer(one_fallback)
    assert fallback["control"] == "hold"
    assert fallback["_trace"]["decision_matrix"]["fallback"]["reason"] == (
        "NO_AUTHORIZED_FALLBACK"
    )

    view = TaskView(one_fallback)
    graph = EvidenceGraph.from_view(view, "obj_focal")
    source_id = (
        "pair:memory_update:local_update:local_resource:memory_store"
    )
    destination_a = "pair:dispatch:share:dispatch_destination:channel_a"
    authorized = CandidateEvaluator.build_matrix(
        view,
        graph,
        view.objects_by_id()["obj_focal"],
        (TargetCandidate("channel_a", "explicit_a", "high"),),
        fallback_edges=(
            FallbackEdge(
                "fallback:test:a",
                source_id,
                destination_a,
                    "official_policy",
                    "policy_equivalent_operation",
                "source_non_executable",
                "TEST_AUTHORIZED",
                ("test:authorization",),
            ),
        ),
    )
    assert authorized.selected.candidate.candidate_id == destination_a
    assert authorized.fallback.fallback_applied is True

    matrix = CandidateEvaluator.build_matrix(
        view,
        graph,
        view.objects_by_id()["obj_focal"],
        (
            TargetCandidate("channel_a", "explicit_a", "high"),
            TargetCandidate("channel_b", "explicit_b", "high"),
        ),
        fallback_edges=(
            FallbackEdge(
                "fallback:test:a",
                source_id,
                destination_a,
                    "official_policy",
                    "policy_equivalent_operation",
                "source_non_executable",
                "TEST_AUTHORIZED",
                ("test:authorization:a",),
            ),
            FallbackEdge(
                "fallback:test:b",
                source_id,
                "pair:dispatch:share:dispatch_destination:channel_b",
                    "official_policy",
                    "policy_equivalent_operation",
                "source_non_executable",
                "TEST_AUTHORIZED",
                ("test:authorization:b",),
            ),
        ),
    )
    assert matrix.selected.candidate.action_candidate.action.value == "dispatch"
    assert (
        matrix.selection.disposition
        == CandidateDisposition.NEEDS_CLARIFICATION
    )
    assert any(
        gate.kind == "multiple_authorized_fallbacks"
        for gate in matrix.selection.gates
    )

    unauthorized = CandidateEvaluator.build_matrix(
        view,
        graph,
        view.objects_by_id()["obj_focal"],
        (TargetCandidate("channel_a", "explicit_a", "high"),),
        fallback_edges=(
            FallbackEdge(
                "fallback:test:unauthorized",
                source_id,
                destination_a,
                "free_form_claim",
                "looks_similar",
                "source_non_executable",
                "UNREGISTERED_AUTHORITY",
                ("test:unsupported_authorization",),
            ),
        ),
    )
    assert unauthorized.fallback.fallback_applied is False
    assert unauthorized.selected.candidate.candidate_id == source_id


def test_conflicting_target_records_are_information_conflict_not_array_choice() -> None:
    task = task_with_object(
        prompt="이 자료를 보내줘.",
        object_type="file",
        attrs={"ref_code": "WM-1010", "contains": ["summary"]},
        records=[
            {"id": "rec_target_a", "type": "resolved_target", "value": "channel_a"},
            {"id": "rec_target_b", "type": "resolved_target", "value": "channel_b"},
        ],
    )
    result = answer(task)
    assert result["control"] == "ask"
    assert "conflicting_record:resolved_target" in selected_evaluation(result)["active_constraints"]


def test_latest_constraint_preserves_earlier_domain_action() -> None:
    tasks = load_jsonl(find_data_dir() / "screening_tasks.jsonl")
    task = next(item for item in tasks if item["id"] == "final_screening_07e174f7625e")
    result = answer(task)
    matrix = result["_trace"]["decision_matrix"]
    assert matrix["selected_action"] == "toggle"
    assert result["_trace"]["final_decision"]["control"] == "amend"
    assert matrix["domain_promotion"][0]["promotion_applied"] is True


def test_schedule_content_share_is_not_promoted_to_schedule() -> None:
    tasks = load_jsonl(find_data_dir() / "screening_tasks.jsonl")
    task = next(item for item in tasks if item["id"] == "final_screening_9cfb4b6455d1")
    matrix = answer(task)["_trace"]["decision_matrix"]
    assert matrix["selected_action"] == "dispatch"
    assert all(item["domain_action_candidate"] != "schedule" for item in matrix["domain_promotion"])

    schedule_task = task_with_object(
        prompt="이 일정을 캘린더에 등록해줘.",
        object_type="calendar_event",
        attrs={
            "ref_code": "WM-1011",
            "attendee": "caregiver",
            "time": "10:00",
        },
    )
    scheduled = answer(schedule_task)
    schedule_matrix = scheduled["_trace"]["decision_matrix"]
    assert schedule_matrix["selected_action"] == "schedule"
    assert scheduled["control"] == "proceed"
    assert schedule_matrix["domain_promotion"][0]["promotion_applied"] is True


def test_missing_memory_is_name_invariant_and_explicitly_missing() -> None:
    def memory_task(person: str) -> dict[str, object]:
        return task_with_object(
            prompt=f"날이 어두워질 때 {person}에게 맞춰 조명을 지난번 저장한 공간대로 처리해줘.",
            object_type="iot_routine",
            attrs={
                "ref_code": "WM-1007",
                "name": "저녁 조명 루틴",
                "target": "entryway",
                "actions": ["light"],
            },
            records=[
                {
                    "id": "rec_memory",
                    "type": "persistent_memory_recall",
                    "value": {"memory_key": f"missing_{person}", "person": person},
                }
            ],
        )

    first = answer(memory_task("alpha"))
    second = answer(memory_task("beta"))
    assert (first["target"], first["control"]) == ("user", "ask")
    assert (second["target"], second["control"]) == ("user", "ask")
    for result in (first, second):
        slots = selected_evaluation(result)["slots"]
        assert slots["memory_value"] == {
            "status": "missing",
            "reason_code": "REQUIRED_MEMORY_UNAVAILABLE",
        }


def test_screening_focal_is_structurally_resolved_not_scored_as_accuracy() -> None:
    tasks = load_jsonl(find_data_dir() / "screening_tasks.jsonl")
    methods = [RelationGraph(TaskView(task)).resolve_focal().method for task in tasks]
    assert len(methods) == 700
    assert set(methods) <= {"marker_trace", "history_binding"}
    assert "unresolved" not in methods
