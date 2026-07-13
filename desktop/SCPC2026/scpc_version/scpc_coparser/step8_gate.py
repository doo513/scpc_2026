from __future__ import annotations

import argparse
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
import sys
from typing import Any

from build_manifest import sha256_file, source_files, source_tree_hash
from core.candidate_evaluation import (
    CandidateEvaluationContext,
    CandidateEvaluationEngine,
    CandidateIdentity,
    CandidateInformationStatus,
    CandidateOrigin,
    CandidateRankingPolicy,
    CandidateSelectionStatus,
    CandidateSemanticKey,
    CandidateSetBuilder,
    CapabilityEvaluationStatus,
    EvaluationCandidate,
    InformationBinding,
    InformationBindingStatus,
    validate_candidate_evaluation_contract,
)
from core.constraints import GLOBAL_CONSTRAINT_REGISTRY
from core.contracts import ContractStatus
from core.facts import CapabilitySnapshot
from core.fallbacks import (
    AuthorizedFallbackSolver,
    CandidatePattern,
    FallbackActivationCondition,
    FallbackAuthorization,
    FallbackAuthorizationSource,
    FallbackEdge,
    FallbackEdgeRegistry,
    FallbackResolutionStatus,
    SemanticPreservation,
    validate_fallback_registry,
)
from core.ontology import (
    CandidateState,
    CapabilityType,
    Domain,
    FactStatus,
    InformationSlot,
    Operation,
    ReasonCode,
)
from core.plan_requirements import InternalTransformType
from core.rulepacks import (
    RULEPACK_REGISTRY,
    DomainOperationRulePack,
    RulePackKey,
    RuleVariant,
    SourceField,
)
from core.slm_contract import EvidenceAuthorityClass, PipelineStage
from core.task_view import TaskView
from stage_gate_common import (
    PreviousStageSpec,
    archive_failed_attempt,
    resolve_previous_stage,
    run_standard_regression,
    standard_regression_checks,
    write_stage_manifest,
)
from step1_baseline import BASE_DIR, combined_hash, resolve_report_root


def contract_files() -> tuple[Path, ...]:
    return (
        BASE_DIR / "core" / "contracts.py",
        BASE_DIR / "core" / "ontology.py",
        BASE_DIR / "core" / "ownership.py",
        BASE_DIR / "core" / "rulepacks.py",
        BASE_DIR / "core" / "plan_requirements.py",
        BASE_DIR / "core" / "constraints.py",
        BASE_DIR / "core" / "candidate_evaluation.py",
        BASE_DIR / "core" / "fallbacks.py",
        BASE_DIR / "core" / "slm_contract.py",
    )


def _target_id(pack: DomainOperationRulePack) -> str:
    return {
        Domain.PAYMENT: "merchant:gate",
        Domain.DEVICE: "device:gate",
        Domain.CALENDAR: "event:gate",
        Domain.MEMORY: "memory_store",
        Domain.GENERAL: "user",
    }.get(pack.key.domain, "destination:gate")


def _information(pack: DomainOperationRulePack):
    fields: tuple[tuple[SourceField, str], ...] = ()
    arguments: tuple[tuple[SourceField, str], ...] = ()
    bindings: tuple[InformationBinding, ...] = ()
    key = pack.key
    if key.domain == Domain.PAYMENT and key.operation != Operation.VERIFY:
        fields = (
            (SourceField.MERCHANT, "merchant:gate"),
            (SourceField.AMOUNT, "1000"),
            (SourceField.METHOD, "method:gate"),
        )
    elif key.domain == Domain.DEVICE and key.operation != Operation.VERIFY:
        fields = ((SourceField.NAME, "device:gate"),)
        arguments = ((SourceField.DESIRED_STATE, "enabled"),)
    elif key.domain == Domain.CALENDAR and key.operation != Operation.VERIFY:
        fields = (
            (SourceField.TITLE, "event:gate"),
            (SourceField.TIME, "10:00"),
        )
    elif key.operation == Operation.VERIFY:
        fields = ((SourceField.OPERATION_REFERENCE, "operation:gate"),)
    if key.domain == Domain.MEMORY and key.variant == RuleVariant.PERSISTENT_MEMORY:
        bindings = (
            InformationBinding(
                InformationSlot.MEMORY_VALUE,
                InformationBindingStatus.PRESENT,
                "memory:gate",
                ("record:memory:gate",),
            ),
        )
    return fields, arguments, bindings


def _candidate(
    pack: DomainOperationRulePack,
    *,
    clause: str,
    rank: int = 50,
) -> EvaluationCandidate:
    role_spec = RULEPACK_REGISTRY.role_spec(pack.required_role_spec_id)
    fields, arguments, bindings = _information(pack)
    return EvaluationCandidate(
        identity=CandidateIdentity(
            sub_operation_id=f"operation:{clause}",
            source_clause_id=clause,
            evidence_group_id=f"evidence:{clause}",
            semantic_key=CandidateSemanticKey(
                pack.key,
                "object:gate",
                _target_id(pack),
            ),
        ),
        target_role=role_spec.allowed_roles[0],
        target_locality=role_spec.locality_constraints[0],
        target_identity_type=role_spec.identity_type_constraints[0],
        satisfied_role_predicates=role_spec.compatibility_predicates,
        failed_role_predicates=(),
        focal_fields=fields,
        operation_arguments=arguments,
        information_bindings=bindings,
        requested_disclosure=None,
        intent_rank=rank,
        origin=CandidateOrigin.STRUCTURAL,
        provenance_ids=(f"evidence:{clause}",),
    )


def _global_facts(records: list[dict[str, object]] | None = None):
    view = TaskView(
        {
            "id": "step8-gate",
            "device_state": {"objects": [], "records": records or []},
            "available_actions": [],
        }
    )
    return GLOBAL_CONSTRAINT_REGISTRY.collect(view.typed_records)


def _context(
    *,
    capabilities: frozenset[CapabilityType] = frozenset(CapabilityType),
    records: list[dict[str, object]] | None = None,
) -> CandidateEvaluationContext:
    return CandidateEvaluationContext(
        global_constraint_facts=_global_facts(records),
        capability_snapshot=CapabilitySnapshot(FactStatus.PRESENT, capabilities),
        internal_transform_capabilities=frozenset(InternalTransformType),
    )


def audit_rulepack_matrix() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    ablation_errors: list[str] = []
    expected_order = (
        PipelineStage.RULEPACK_LOOKUP,
        PipelineStage.BASE_BLUEPRINT_LOAD,
        PipelineStage.REQUIRED_ROLE_EVALUATION,
        PipelineStage.INFORMATION_EVALUATION,
        PipelineStage.GLOBAL_CONSTRAINT_ACTIVATION,
        PipelineStage.PAIR_CONSTRAINT_ACTIVATION,
        PipelineStage.CONDITIONAL_INFORMATION_FINALIZATION,
        PipelineStage.CONSTRAINT_EFFECT_COMPOSITION,
        PipelineStage.FINAL_PLAN_REQUIREMENTS,
        PipelineStage.FULL_CAPABILITY_EVALUATION,
    )
    for index, pack in enumerate(RULEPACK_REGISTRY.rulepacks):
        candidate = _candidate(pack, clause=f"matrix:{index}")
        try:
            evaluation = CandidateEvaluationEngine.evaluate_set(
                CandidateSetBuilder.build((candidate,)),
                _context(),
            )[0]
            requirements = evaluation.assessment.final_plan_requirements
            rows.append(
                {
                    "rulepack_id": pack.rule_id,
                    "candidate_state": evaluation.candidate_state.value,
                    "information_status": (
                        evaluation.assessment.information.status.value
                        if evaluation.assessment.information
                        else None
                    ),
                    "capability_status": evaluation.assessment.capability.status.value,
                    "assessment_order": [
                        stage.value for stage in evaluation.assessment.assessment_order
                    ],
                    "platform_capabilities": [
                        item.value
                        for item in (
                            requirements.platform_required_capabilities
                            if requirements
                            else ()
                        )
                    ],
                }
            )
            if evaluation.assessment.assessment_order != expected_order:
                errors.append(f"{pack.rule_id}: pipeline order mismatch")
            if evaluation.candidate_state != CandidateState.VIABLE:
                errors.append(f"{pack.rule_id}: not viable")
            if requirements is None:
                errors.append(f"{pack.rule_id}: missing FinalPlanRequirements")
                continue
            for capability in requirements.platform_required_capabilities:
                ablated_context = _context(
                    capabilities=frozenset(
                        item for item in CapabilityType if item != capability
                    )
                )
                ablated = CandidateEvaluationEngine.evaluate_set(
                    CandidateSetBuilder.build((candidate,)),
                    ablated_context,
                )[0]
                if (
                    ablated.assessment.capability.status
                    != CapabilityEvaluationStatus.UNAVAILABLE
                    or capability
                    not in ablated.assessment.capability.missing_platform_capabilities
                ):
                    ablation_errors.append(
                        f"{pack.rule_id}:{capability.value}"
                    )
        except Exception as exc:
            errors.append(f"{pack.rule_id}: {type(exc).__name__}: {exc}")
    return {
        "rulepack_count": len(RULEPACK_REGISTRY.rulepacks),
        "evaluated_count": len(rows),
        "rows": rows,
        "errors": errors,
        "capability_ablation_errors": ablation_errors,
    }


def audit_candidate_counterfactuals() -> dict[str, Any]:
    content_pack = RULEPACK_REGISTRY.lookup(
        RulePackKey(Domain.CONTENT, Operation.SHARE)
    )
    memory_pack = RULEPACK_REGISTRY.lookup(
        RulePackKey(
            Domain.MEMORY,
            Operation.LOCAL_UPDATE,
            RuleVariant.LOCAL_STATE,
        )
    )
    assert content_pack is not None and memory_pack is not None
    blocked = _candidate(content_pack, clause="blocked", rank=100)
    local = _candidate(memory_pack, clause="local", rank=10)
    evaluations = CandidateEvaluationEngine.evaluate_set(
        CandidateSetBuilder.build((blocked, local)),
        _context(
            records=[
                {"id": "consent", "type": "consent", "value": "revoked"}
            ]
        ),
    )
    selection = CandidateRankingPolicy.select(evaluations)
    by_id = {item.candidate.candidate_id: item for item in evaluations}

    repeated_a = _candidate(content_pack, clause="repeat:a", rank=50)
    repeated_b = _candidate(content_pack, clause="repeat:b", rank=50)
    repeated_set = CandidateSetBuilder.build((repeated_a, repeated_b))
    repeated_selection = CandidateRankingPolicy.select(
        CandidateEvaluationEngine.evaluate_set(repeated_set, _context())
    )
    return {
        "blocked_state": by_id[blocked.candidate_id].candidate_state.value,
        "local_state": by_id[local.candidate_id].candidate_state.value,
        "selected_candidate_id": selection.selected_candidate_id,
        "local_candidate_id": local.candidate_id,
        "rank_bypass_prevented": selection.selected_candidate_id
        == local.candidate_id,
        "same_semantic_candidate_count": len(repeated_set.candidates),
        "same_semantic_distinct_ids": repeated_a.candidate_id
        != repeated_b.candidate_id,
        "same_semantic_selection_status": repeated_selection.status.value,
        "same_semantic_lineage_count": len(
            repeated_selection.equivalent_source_candidate_ids
        ),
    }


def _fallback_edge(
    source_key: RulePackKey,
    destination_key: RulePackKey,
    *,
    edge_id: str,
) -> FallbackEdge:
    return FallbackEdge(
        edge_id=edge_id,
        source_candidate_pattern=CandidatePattern("source", (source_key,)),
        destination_candidate_pattern=CandidatePattern(
            "destination",
            (destination_key,),
        ),
        authorization=FallbackAuthorization(
            FallbackAuthorizationSource.CURRENT_USER_EXPLICIT,
            ("evidence:explicit-alternative",),
            True,
            EvidenceAuthorityClass.CURRENT_DIRECT,
        ),
        activation_condition=(
            FallbackActivationCondition.SOURCE_CAPABILITY_UNAVAILABLE
        ),
        semantic_preservation=SemanticPreservation.USER_SPECIFIED_ALTERNATIVE,
        maximum_hops=1,
        reason_code=ReasonCode.AVOIDED_BY_AUTHORIZED_FALLBACK,
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
    )


def audit_fallbacks() -> dict[str, Any]:
    payment_key = RulePackKey(Domain.PAYMENT, Operation.EXECUTE)
    content_key = RulePackKey(Domain.CONTENT, Operation.SHARE)
    payment_pack = RULEPACK_REGISTRY.lookup(payment_key)
    content_pack = RULEPACK_REGISTRY.lookup(content_key)
    assert payment_pack is not None and content_pack is not None
    source = _candidate(payment_pack, clause="fallback:source")
    destination = _candidate(content_pack, clause="fallback:destination")
    candidate_set = CandidateSetBuilder.build((source, destination))
    context = _context(
        capabilities=frozenset(
            item for item in CapabilityType if item != CapabilityType.PAY
        )
    )
    registry = FallbackEdgeRegistry(
        (_fallback_edge(payment_key, content_key, edge_id="edge:authorized"),)
    )
    applied = AuthorizedFallbackSolver.solve(
        source_candidate_id=source.candidate_id,
        candidate_set=candidate_set,
        evaluation_context=context,
        registry=registry,
    )
    without_edge = AuthorizedFallbackSolver.solve(
        source_candidate_id=source.candidate_id,
        candidate_set=candidate_set,
        evaluation_context=context,
        registry=FallbackEdgeRegistry(),
    )
    by_id = {item.candidate.candidate_id: item for item in applied.evaluations}
    source_requirements = by_id[source.candidate_id].assessment.final_plan_requirements
    destination_requirements = by_id[
        destination.candidate_id
    ].assessment.final_plan_requirements

    cycle_rejected = False
    try:
        FallbackEdgeRegistry(
            (
                _fallback_edge(payment_key, content_key, edge_id="cycle:a"),
                _fallback_edge(content_key, payment_key, edge_id="cycle:b"),
            )
        )
    except ValueError:
        cycle_rejected = True
    self_loop_rejected = False
    try:
        FallbackEdgeRegistry(
            (_fallback_edge(payment_key, payment_key, edge_id="self"),)
        )
    except ValueError:
        self_loop_rejected = True
    return {
        "applied_status": applied.resolution.status.value,
        "selected_destination_id": applied.resolution.selected_destination_candidate_id,
        "expected_destination_id": destination.candidate_id,
        "trace_destinations": [
            item.destination_candidate_id for item in applied.resolution.traces
        ],
        "without_edge_status": without_edge.resolution.status.value,
        "source_rulepack_id": (
            source_requirements.rulepack_id if source_requirements else None
        ),
        "destination_rulepack_id": (
            destination_requirements.rulepack_id
            if destination_requirements
            else None
        ),
        "cycle_rejected": cycle_rejected,
        "self_loop_rejected": self_loop_rejected,
    }


def audit_boundaries() -> dict[str, Any]:
    production_imports: list[str] = []
    for relative in ("core/decision.py", "harness.py", "rules/plan.py"):
        source = (BASE_DIR / relative).read_text(encoding="utf-8")
        if any(
            token in source
            for token in (
                "from .candidate_evaluation",
                "core.candidate_evaluation",
                "from .fallbacks",
                "core.fallbacks",
            )
        ):
            production_imports.append(relative)
    evaluator_source = inspect.getsource(
        sys.modules["core.candidate_evaluation"].CandidateEvaluator
    )
    return {
        "production_active": CandidateEvaluationEngine.production_active,
        "production_imports": production_imports,
        "candidate_evaluator_prerequisite_calls": [
            token
            for token in (
                "RULEPACK_REGISTRY",
                "PLAN_BLUEPRINT_REGISTRY",
                "PairConstraintActivator",
                "FullCapabilityEvaluator",
            )
            if token in evaluator_source
        ],
        "default_fallback_registry_empty": not FallbackEdgeRegistry().edges,
    }


def contract_markdown() -> str:
    return "\n".join(
        [
            "# Step 8 Candidate Evaluation·Fallback 계약",
            "",
            "## 후보 identity",
            "",
            "CandidateSemanticKey와 source clause, sub-operation, evidence group을 포함한 CandidateIdentity를 분리한다. 동일 semantic key의 반복 후보는 보존하며 full identity만 중복 금지한다. CandidateSetBuilder는 이미 source-bound인 pair seed만 받으며 Cartesian product API를 제공하지 않는다.",
            "",
            "## 평가 잠금",
            "",
            "RulePack, BasePlanBlueprint, role, base information, global/pair constraint, deferred conditional information, effect algebra, FinalPlanRequirements, full capability 순서로 axis를 완성한다. CandidateEvaluator는 이 결과만 종합하며 이전 registry를 조회하지 않는다.",
            "",
            "`CONSTRAINT_PRESENT` conditional slot은 base information precheck 후 constraint activation 결과로만 확정한다. 앞서 확정한 binding은 재해석하지 않는다.",
            "",
            "## 상태와 rank",
            "",
            "role-incompatible 후보는 reject한다. missing, block, conflict가 동시에 발생해 공식 precedence가 없으면 `ASSUMPTION-DISPOSITION-001`과 함께 unresolved precedence로 보존한다. rank는 VIABLE·AMENDABLE 후보 사이에서만 tie-breaker로 사용하며 SLM origin 보너스가 없다.",
            "",
            "## Fallback",
            "",
            "현재 사용자 명시 대안은 CURRENT_DIRECT authority Evidence만 authorization으로 인정한다. destination은 CandidateEvaluationEngine을 다시 통과한다. edge가 없으면 낮은 rank 후보를 자동 선택하지 않는다. 현재 구현은 1-hop만 지원하고 cycle·self-loop를 거부한다.",
            "",
            "Step 8 경로는 shadow-only이며 production decision 교체는 아직 수행하지 않았다.",
            "",
        ]
    )


def build_report(result: dict[str, Any]) -> str:
    tests = result["tests"]
    matrix = result["rulepack_matrix"]
    counterfactual = result["candidate_counterfactual"]
    fallback = result["fallback_audit"]
    boundary = result["boundary_audit"]
    gate = result["release_gate"]
    return "\n".join(
        [
            "# Step 8 Candidate Evaluator·Fallback 보고서",
            "",
            "## 구현 범위",
            "",
            "typed candidate identity, staged axis assessment, full plan capability, post-assessment CandidateEvaluator, authorized 1-hop fallback를 shadow path로 구현했다.",
            "",
            "## 구조 검증",
            "",
            f"- RulePack matrix: `{matrix['evaluated_count']}/{matrix['rulepack_count']}`",
            f"- matrix 오류: `{len(matrix['errors'])}`개",
            f"- capability ablation 오류: `{len(matrix['capability_ablation_errors'])}`개",
            f"- high-rank block 우회 방지: `{counterfactual['rank_bypass_prevented']}`",
            f"- same semantic source lineage: `{counterfactual['same_semantic_lineage_count']}`개",
            f"- authorized fallback 상태: `{fallback['applied_status']}`",
            f"- edge 없는 fallback 상태: `{fallback['without_edge_status']}`",
            f"- cycle/self-loop 차단: `{fallback['cycle_rejected']}/{fallback['self_loop_rejected']}`",
            f"- production import: `{len(boundary['production_imports'])}`개",
            "",
            "## 회귀",
            "",
            f"- Step 8 invariant: exit `{tests['stage_specific']['exit_code']}`, {', '.join(tests['stage_specific']['summary'])}",
            f"- 전체 pytest: exit `{tests['full']['exit_code']}`, {', '.join(tests['full']['summary'])}",
            f"- 알려진 dev gate 제외: exit `{tests['without_known_dev_gate']['exit_code']}`, {', '.join(tests['without_known_dev_gate']['summary'])}",
            f"- dev overall: `{result['dev']['overall']:.4f}` (Step 7과 동일: `{result['dev_unchanged']}`)",
            f"- screening submission 동일: `{result['screening_submission_unchanged']}`",
            "",
            "전체 pytest의 dev hard gate 1건은 기존 baseline debt다. shadow matrix 통과는 공식 reference 일치를 의미하지 않는다.",
            "",
            "## Release Gate",
            "",
            f"- 상태: **{gate['status']}**",
            f"- 다음 단계 진입 가능: **{gate['next_stage_allowed']}**",
            *[f"- {reason}" for reason in gate["reasons"]],
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    report_root, root_source = resolve_report_root()
    output_dir = (args.output_dir or report_root / "step8_evaluator").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_failed_attempt(
        output_dir,
        result_filename="step8_result.json",
        report_filename="STEP8_REPORT.md",
    )
    previous_dir, previous_result, previous_stage = resolve_previous_stage(
        report_root.resolve(),
        PreviousStageSpec("step7_constraints", "step7_constraints", "step7_result.json"),
    )
    source_hash_before = source_tree_hash(source_files())

    validation_errors: list[str] = []
    for validator in (
        validate_candidate_evaluation_contract,
        validate_fallback_registry,
    ):
        try:
            validator()
        except Exception as exc:
            validation_errors.append(
                f"{validator.__name__}: {type(exc).__name__}: {exc}"
            )

    matrix = audit_rulepack_matrix()
    candidate_counterfactual = audit_candidate_counterfactuals()
    fallback_audit = audit_fallbacks()
    boundary_audit = audit_boundaries()
    snapshot = {
        "rulepack_matrix": matrix,
        "candidate_counterfactual": candidate_counterfactual,
        "fallback": fallback_audit,
        "boundaries": boundary_audit,
    }
    snapshot_path = output_dir / "candidate_evaluation_audit.json"
    snapshot_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    contract_path = output_dir / "CANDIDATE_FALLBACK_CONTRACT.md"
    contract_path.write_text(contract_markdown(), encoding="utf-8")

    regression = run_standard_regression(
        output_dir,
        stage_test_files=(
            "tests/test_candidate_evaluation.py",
            "tests/test_fallbacks.py",
            "tests/test_constraints.py",
            "tests/test_plan_requirements.py",
            "tests/test_rulepacks.py",
            "tests/test_slm_contract.py",
            "tests/test_ontology.py",
            "tests/test_architecture.py",
        ),
        previous_dir=previous_dir,
        previous_result=previous_result,
    )
    source_hash_after = source_tree_hash(source_files())
    checks = {
        "step7_artifact_integrity": bool(previous_stage.get("checks"))
        and all(previous_stage["checks"].values()),
        "contracts_valid": not validation_errors,
        "rulepack_matrix": matrix["evaluated_count"] == matrix["rulepack_count"]
        and not matrix["errors"],
        "full_capability_ablation": not matrix["capability_ablation_errors"],
        "rank_cannot_bypass_block": candidate_counterfactual[
            "rank_bypass_prevented"
        ],
        "candidate_identity_preserved": candidate_counterfactual[
            "same_semantic_candidate_count"
        ]
        == 2
        and candidate_counterfactual["same_semantic_distinct_ids"]
        and candidate_counterfactual["same_semantic_lineage_count"] == 2,
        "authorized_fallback_re_evaluated": fallback_audit["applied_status"]
        == FallbackResolutionStatus.APPLIED.value
        and fallback_audit["selected_destination_id"]
        == fallback_audit["expected_destination_id"]
        and fallback_audit["source_rulepack_id"]
        != fallback_audit["destination_rulepack_id"],
        "no_automatic_fallback": fallback_audit["without_edge_status"]
        == FallbackResolutionStatus.NOT_APPLIED.value,
        "fallback_graph_valid": fallback_audit["cycle_rejected"]
        and fallback_audit["self_loop_rejected"],
        "candidate_evaluator_is_aggregator": not boundary_audit[
            "candidate_evaluator_prerequisite_calls"
        ],
        "shadow_only": not boundary_audit["production_active"]
        and not boundary_audit["production_imports"],
        "source_stable_during_gate": source_hash_before == source_hash_after,
        **standard_regression_checks(regression),
    }
    gate_passed = all(checks.values())
    release_gate = {
        "status": "PASS_WITH_BASELINE_DEBT" if gate_passed else "FAIL",
        "next_stage_allowed": gate_passed,
        "checks": checks,
        "reasons": [
            "14개 RulePack axis 평가와 full capability ablation이 통과했다.",
            "hard role·constraint가 rank로 우회되지 않음을 확인했다.",
            "authorized fallback destination 재평가와 무권한 자동 전환 금지를 확인했다.",
            "Step 7 대비 public dev 수치와 screening submission이 변하지 않았다.",
        ]
        if gate_passed
        else [
            f"실패한 Step 8 gate: {name}"
            for name, passed in checks.items()
            if not passed
        ]
        + validation_errors
        + matrix["errors"]
        + matrix["capability_ablation_errors"]
        + list(previous_stage.get("errors") or []),
    }
    result = {
        "stage": "step8_evaluator",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_command": f"{sys.executable} {Path(__file__).name}",
        "report_root": str(report_root.resolve()),
        "report_root_source": root_source,
        "output_dir": str(output_dir),
        "previous_stage": previous_stage,
        "source_tree_sha256": source_hash_after,
        "contract_sha256": combined_hash(contract_files(), root=BASE_DIR),
        "audit_sha256": sha256_file(snapshot_path),
        "rulepack_matrix": matrix,
        "candidate_counterfactual": candidate_counterfactual,
        "fallback_audit": fallback_audit,
        "boundary_audit": boundary_audit,
        "dev": regression["dev"],
        "dev_unchanged": regression["dev_unchanged"],
        "screening_submission_sha256": regression["submission_sha256"],
        "screening_submission_unchanged": regression["submission_unchanged"],
        "tests": regression["tests"],
        "validation_errors": validation_errors,
        "release_gate": release_gate,
        "stage_manifest_path": str(output_dir / "stage_manifest.json"),
    }
    result_path = output_dir / "step8_result.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path = output_dir / "STEP8_REPORT.md"
    report_path.write_text(build_report(result), encoding="utf-8")
    write_stage_manifest(
        output_dir,
        stage="step8_evaluator",
        source_hash=source_hash_after,
        artifact_paths=(
            snapshot_path,
            contract_path,
            regression["submission_path"],
            result_path,
            report_path,
            output_dir / "consistency_report.md",
            regression["shadow_diff_path"],
        ),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
