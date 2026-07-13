from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from core.blueprint import BlueprintEffectKind
from core.contracts import assumption_ids, validate_assumption_registry
from core.decision import CandidateDisposition, FinalDecision
from core.ontology import (
    CandidateDispositionPolicy,
    CandidateState,
    ConstraintEffect,
    DispositionDecision,
    ExecutionDisposition,
    InformationStatus,
    Operation,
    TargetBindingContract,
    TargetLocality,
    TargetRole,
    validate_ontology,
)
from core.ownership import OWNERSHIP_REGISTRY, validate_ownership_registry
from core.state import OperationMode
from tests.test_generalization import answer, task_with_object


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_common_ontology_is_strict_and_canonical() -> None:
    validate_ontology()
    validate_assumption_registry()

    assert Operation.parse("verify") is Operation.VERIFY
    with pytest.raises(ValueError, match="unknown Operation"):
        Operation.parse("best_effort_dispatch")


def test_legacy_type_names_are_aliases_not_duplicate_enums() -> None:
    assert OperationMode is Operation
    assert CandidateDisposition is CandidateState
    assert BlueprintEffectKind is ConstraintEffect

    state_source = (PROJECT_ROOT / "core" / "state.py").read_text(
        encoding="utf-8"
    )
    decision_source = (PROJECT_ROOT / "core" / "decision.py").read_text(
        encoding="utf-8"
    )
    blueprint_source = (PROJECT_ROOT / "core" / "blueprint.py").read_text(
        encoding="utf-8"
    )
    assert "class OperationMode" not in state_source
    assert "class CandidateDisposition" not in decision_source
    assert "class InformationStatus" not in decision_source
    assert "class BlueprintEffectKind" not in blueprint_source


def test_candidate_disposition_policy_is_the_single_mapping_owner() -> None:
    assert CandidateDispositionPolicy.candidate_state(
        rulepack_supported=False,
        execution_blocked=False,
        information_status=InformationStatus.COMPLETE,
        requires_confirmation=False,
        amended=False,
    ) is CandidateState.UNSUPPORTED_RULEPACK
    assert CandidateDispositionPolicy.candidate_state(
        rulepack_supported=True,
        execution_blocked=False,
        information_status=InformationStatus.MISSING,
        requires_confirmation=False,
        amended=False,
    ) is CandidateState.NEEDS_INFORMATION
    assert CandidateDispositionPolicy.execution_disposition(
        CandidateState.NEEDS_INFORMATION
    ) is ExecutionDisposition.ASK
    assert CandidateDispositionPolicy.execution_disposition(
        CandidateState.UNSUPPORTED_RULEPACK
    ) is ExecutionDisposition.HOLD

    with pytest.raises(ValueError, match="incompatible"):
        DispositionDecision(
            CandidateState.BLOCKED,
            ExecutionDisposition.PROCEED,
        )


def test_target_role_locality_contract_rejects_impossible_combinations() -> None:
    TargetBindingContract(
        "memory_store",
        TargetRole.LOCAL_RESOURCE,
        TargetLocality.LOCAL,
    )
    with pytest.raises(ValueError, match="requires locality"):
        TargetBindingContract(
            "memory_store",
            TargetRole.LOCAL_RESOURCE,
            TargetLocality.EXTERNAL,
        )
    with pytest.raises(ValueError, match="unresolved target"):
        TargetBindingContract(
            "user",
            TargetRole.UNRESOLVED,
            TargetLocality.UNKNOWN,
        )


def test_semantic_ownership_has_one_final_owner_and_no_compiler_owner() -> None:
    validate_ownership_registry()
    fields_by_name = {item.field: item for item in OWNERSHIP_REGISTRY}

    assert fields_by_name["candidate_state"].final_owner == (
        "CandidateDispositionPolicy"
    )
    assert all(
        item.final_owner
        not in {"ScopeCompiler", "PolicyCompiler", "PlanCompiler"}
        for item in OWNERSHIP_REGISTRY
    )
    final_fields = {field.name for field in fields(FinalDecision)}
    assert {"operation_target_role", "operation_target_locality"} <= final_fields


def test_unresolved_semantics_do_not_become_dispatch_execution() -> None:
    result = answer(
        task_with_object(
            prompt="자료 상태가 제공되었다.",
            object_type="file",
            attrs={"ref_code": "WM-ONTOLOGY"},
        )
    )

    final = result["_trace"]["final_decision"]
    assert final["action"] == "unresolved"
    assert result["control"] == "ask"
    assert "dispatch" not in {
        event["verb"] for event in result["plan_events"]
    }
    assert set(final["unresolved_assumption_refs"]) <= assumption_ids()
    assert "ASSUMPTION-DISPOSITION-001" in final[
        "unresolved_assumption_refs"
    ]
