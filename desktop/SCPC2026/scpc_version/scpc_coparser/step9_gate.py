from __future__ import annotations

import argparse
from dataclasses import fields, replace
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
    CandidateOrigin,
    CandidateSemanticKey,
    CandidateSetBuilder,
    EvaluationCandidate,
)
from core.contracts import (
    BUNDLE_ASSUMPTION_ID,
    DISPOSITION_PLAN_ASSUMPTION_ID,
    TARGET_ASSUMPTION_ID,
    ContractStatus,
)
from core.decision_ir import (
    AggregateOutputStatus,
    DecisionBundleBuilder,
    DecisionDependencyEdge,
    DecisionDependencyKind,
    DecisionProjectionBuilder,
    DisclosureDecision,
    LockedPlanDecision,
    PlanProjectionStep,
    PolicyDecision,
    ResponseTargetBinding,
    ResponseTargetMappingStatus,
    SubDecisionIRBuilder,
    validate_decision_ir_contract,
)
from core.facts import CapabilitySnapshot
from core.ontology import (
    CandidateDispositionPolicy,
    CapabilityType,
    DisclosureMode,
    Domain,
    ExecutionDisposition,
    FactStatus,
    Operation,
    PlanStepType,
    ReasonCode,
)
from core.plan_requirements import InternalTransformType
from core.rulepacks import RULEPACK_REGISTRY, RulePackKey, SourceField
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
        BASE_DIR / "core" / "decision_ir.py",
    )


def _candidate(*, clause: str, missing_amount: bool = False) -> EvaluationCandidate:
    key = RulePackKey(Domain.PAYMENT, Operation.EXECUTE)
    pack = RULEPACK_REGISTRY.lookup(key)
    assert pack is not None
    role = RULEPACK_REGISTRY.role_spec(pack.required_role_spec_id)
    focal_fields = [
        (SourceField.MERCHANT, "merchant:gate"),
        (SourceField.METHOD, "method:gate"),
    ]
    if not missing_amount:
        focal_fields.append((SourceField.AMOUNT, "1000"))
    return EvaluationCandidate(
        identity=CandidateIdentity(
            sub_operation_id="operation:payment",
            source_clause_id=clause,
            evidence_group_id=f"evidence:{clause}",
            semantic_key=CandidateSemanticKey(
                key,
                "object:payment",
                "merchant:gate",
            ),
        ),
        target_role=role.allowed_roles[0],
        target_locality=role.locality_constraints[0],
        target_identity_type=role.identity_type_constraints[0],
        satisfied_role_predicates=role.compatibility_predicates,
        failed_role_predicates=(),
        focal_fields=tuple(focal_fields),
        operation_arguments=(),
        information_bindings=(),
        requested_disclosure=DisclosureMode.STATUS_ONLY,
        intent_rank=50,
        origin=CandidateOrigin.STRUCTURAL,
        provenance_ids=(f"evidence:{clause}",),
    )


def _evaluate(
    candidate: EvaluationCandidate,
    capabilities: frozenset[CapabilityType] = frozenset(CapabilityType),
):
    snapshot = CapabilitySnapshot(FactStatus.PRESENT, capabilities)
    context = CandidateEvaluationContext(
        global_constraint_facts=(),
        capability_snapshot=snapshot,
        internal_transform_capabilities=frozenset(InternalTransformType),
    )
    evaluation = CandidateEvaluationEngine.evaluate_set(
        CandidateSetBuilder.build((candidate,)),
        context,
    )[0]
    return evaluation, snapshot


def _response_target() -> ResponseTargetBinding:
    return ResponseTargetBinding(
        response_target="interaction:user",
        mapping_status=ResponseTargetMappingStatus.ASSUMPTION_LINKED,
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        contract_reference_ids=(TARGET_ASSUMPTION_ID,),
        derived_from=("evidence:response-target",),
    )


def _plan(evaluation) -> LockedPlanDecision:
    decision_id = SubDecisionIRBuilder.decision_id_for(evaluation)
    requirements = evaluation.assessment.final_plan_requirements
    disposition = CandidateDispositionPolicy.execution_disposition(
        evaluation.candidate_state
    )
    if disposition in {ExecutionDisposition.PROCEED, ExecutionDisposition.AMEND}:
        assert requirements is not None
        return LockedPlanDecision(
            decision_id,
            tuple(
                PlanProjectionStep(
                    projection_step_id=f"projection:{step.step_id}",
                    requirement_step_id=step.step_id,
                    verb=step.output_verb,
                    target=(
                        evaluation.candidate.semantic_key.target_id
                        if step.semantic_terminal
                        else evaluation.candidate.semantic_key.focal_id
                    ),
                    args=(),
                    reason_codes=(ReasonCode.EXECUTABLE,),
                    semantic_terminal=step.semantic_terminal,
                )
                for step in requirements.required_steps
                if step.output_verb is not None
            ),
        )

    read_requirement_id = ""
    if requirements is not None:
        read_requirement_id = next(
            (
                step.step_id
                for step in requirements.required_steps
                if step.output_verb == PlanStepType.READ
            ),
            "",
        )
    reason = (
        ReasonCode.REQUIRED_INFORMATION_MISSING
        if disposition == ExecutionDisposition.ASK
        else ReasonCode.CAPABILITY_UNAVAILABLE
    )
    terminal = (
        PlanStepType.CLARIFY
        if disposition == ExecutionDisposition.ASK
        else PlanStepType.GUARD
    )
    terminal_target = (
        "interaction:user"
        if disposition == ExecutionDisposition.ASK
        else evaluation.candidate.semantic_key.focal_id
    )
    contract = (DISPOSITION_PLAN_ASSUMPTION_ID,)
    return LockedPlanDecision(
        decision_id,
        (
            PlanProjectionStep(
                "projection:read",
                read_requirement_id,
                PlanStepType.READ,
                evaluation.candidate.semantic_key.focal_id,
                (),
                (reason,),
                () if read_requirement_id else contract,
            ),
            PlanProjectionStep(
                f"projection:{terminal.value}",
                "",
                terminal,
                terminal_target,
                (),
                (reason,),
                contract,
            ),
        ),
    )


def _lock(evaluation, snapshot):
    is_hold = (
        CandidateDispositionPolicy.execution_disposition(evaluation.candidate_state)
        == ExecutionDisposition.HOLD
    )
    return SubDecisionIRBuilder.lock(
        evaluation=evaluation,
        response_target_binding=_response_target(),
        disclosure=DisclosureDecision(
            DisclosureMode.NONE if is_hold else DisclosureMode.STATUS_ONLY,
            () if is_hold else ("status",),
            (),
            False,
            (),
        ),
        policy=PolicyDecision((), (), False, ()),
        plan_decision=_plan(evaluation),
        capability_snapshot=snapshot,
    )


def audit_decision_lock() -> dict[str, Any]:
    viable_evaluation, viable_snapshot = _evaluate(
        _candidate(clause="gate:viable")
    )
    ask_evaluation, ask_snapshot = _evaluate(
        _candidate(clause="gate:ask", missing_amount=True)
    )
    hold_capabilities = frozenset(
        capability for capability in CapabilityType if capability != CapabilityType.PAY
    )
    hold_evaluation, hold_snapshot = _evaluate(
        _candidate(clause="gate:hold"),
        hold_capabilities,
    )
    viable = _lock(viable_evaluation, viable_snapshot)
    ask = _lock(ask_evaluation, ask_snapshot)
    hold = _lock(hold_evaluation, hold_snapshot)
    for decision in (viable, ask, hold):
        decision.verify_lock()

    stale_mutation_rejected = False
    try:
        replace(viable, operation=Operation.CANCEL)
    except ValueError:
        stale_mutation_rejected = True

    invalid_capability_lock_rejected = False
    try:
        SubDecisionIRBuilder.lock(
            evaluation=viable_evaluation,
            response_target_binding=_response_target(),
            disclosure=DisclosureDecision(
                DisclosureMode.STATUS_ONLY,
                ("status",),
                (),
                False,
                (),
            ),
            policy=PolicyDecision((), (), False, ()),
            plan_decision=_plan(viable_evaluation),
            capability_snapshot=CapabilitySnapshot(FactStatus.MISSING, frozenset()),
        )
    except ValueError:
        invalid_capability_lock_rejected = True

    viable_bundle = DecisionBundleBuilder.lock(
        bundle_id="bundle:single",
        primary_focal_id=viable.focal_id,
        sub_decisions=(viable,),
    )
    projection_a = DecisionProjectionBuilder.build(viable_bundle)
    projection_b = DecisionProjectionBuilder.build(viable_bundle)
    requirements = viable.final_plan_requirements
    assert requirements is not None
    expected_step_ids = tuple(
        step.step_id
        for step in requirements.required_steps
        if step.output_verb is not None
    )
    actual_step_ids = tuple(
        step.requirement_step_id for step in viable.plan_decision.steps
    )
    expected_terminals = tuple(
        step.semantic_terminal
        for step in requirements.required_steps
        if step.output_verb is not None
    )
    actual_terminals = tuple(
        step.semantic_terminal for step in viable.plan_decision.steps
    )
    return {
        "viable_disposition": viable.execution_disposition.value,
        "ask_disposition": ask.execution_disposition.value,
        "hold_disposition": hold.execution_disposition.value,
        "ask_plan": [step.verb.value for step in ask.plan_decision.steps],
        "hold_plan": [step.verb.value for step in hold.plan_decision.steps],
        "execution_target": viable.execution_target,
        "response_target": viable.response_target,
        "target_separation_preserved": viable.execution_target != viable.response_target,
        "stale_mutation_rejected": stale_mutation_rejected,
        "invalid_capability_lock_rejected": invalid_capability_lock_rejected,
        "projection_deterministic": projection_a == projection_b,
        "projection_lossless": projection_a.plans[0].steps
        == viable.plan_decision.steps,
        "plan_order_preserved": actual_step_ids == expected_step_ids,
        "semantic_terminal_preserved": actual_terminals == expected_terminals
        and sum(actual_terminals) == 1,
        "non_execution_terminal_absent": not any(
            step.semantic_terminal
            for decision in (ask, hold)
            for step in decision.plan_decision.steps
        ),
        "plan_reason_lineage_preserved": all(
            set(step.reason_codes) <= set(viable.reason_codes)
            for step in viable.plan_decision.steps
        ),
        "target_provenance_preserved": "evidence:response-target"
        in viable.provenance_ids,
        "single_aggregate_status": viable_bundle.aggregate_output_status.value,
        "single_decision": viable,
        "ask_decision": ask,
    }


def audit_bundle(single_decision, ask_decision) -> dict[str, Any]:
    edge = DecisionDependencyEdge(
        single_decision.decision_id,
        ask_decision.decision_id,
        DecisionDependencyKind.REQUIRES_SUCCESS,
        "reference:dependency",
    )
    bundle_a = DecisionBundleBuilder.lock(
        bundle_id="bundle:multi",
        primary_focal_id=single_decision.focal_id,
        sub_decisions=(single_decision, ask_decision),
        dependency_edges=(edge,),
    )
    bundle_b = DecisionBundleBuilder.lock(
        bundle_id="bundle:multi",
        primary_focal_id=single_decision.focal_id,
        sub_decisions=(ask_decision, single_decision),
        dependency_edges=(edge,),
    )
    bundle_a.verify_lock()

    reverse = DecisionDependencyEdge(
        ask_decision.decision_id,
        single_decision.decision_id,
        DecisionDependencyKind.READ_AFTER_WRITE,
        "reference:reverse",
    )
    cycle_rejected = False
    try:
        DecisionBundleBuilder.lock(
            bundle_id="bundle:cycle",
            primary_focal_id=single_decision.focal_id,
            sub_decisions=(single_decision, ask_decision),
            dependency_edges=(edge, reverse),
        )
    except ValueError:
        cycle_rejected = True

    return {
        "aggregate_status": bundle_a.aggregate_output_status.value,
        "aggregate_control_field_present": "control"
        in {item.name for item in fields(bundle_a)},
        "subdecision_dispositions": sorted(
            item.execution_disposition.value for item in bundle_a.sub_decisions
        ),
        "bundle_assumption_present": BUNDLE_ASSUMPTION_ID
        in bundle_a.unresolved_assumption_refs,
        "dependency_count": len(bundle_a.dependency_edges),
        "cycle_rejected": cycle_rejected,
        "input_order_independent": bundle_a == bundle_b,
    }


def audit_boundaries() -> dict[str, Any]:
    production_imports: list[str] = []
    for relative in (
        "core/decision.py",
        "harness.py",
        "rules/scope.py",
        "rules/policy.py",
        "rules/plan.py",
    ):
        path = BASE_DIR / relative
        if path.is_file() and "decision_ir" in path.read_text(encoding="utf-8"):
            production_imports.append(relative)
    module_source = (BASE_DIR / "core" / "decision_ir.py").read_text(
        encoding="utf-8"
    )
    projection_source = inspect.getsource(DecisionProjectionBuilder)
    prohibited_raw_dependencies = [
        token
        for token in (
            "TaskView",
            "EvidenceGraph",
            "visible_history",
            "personal_memory",
            "raw_record",
            "ActionProfile",
        )
        if token in module_source
    ]
    projection_reinterpretation_tokens = [
        token
        for token in (
            "CandidateEvaluator",
            "RULEPACK_REGISTRY",
            "PairConstraintActivator",
            "prompt",
        )
        if token in projection_source
    ]
    return {
        "builder_production_active": SubDecisionIRBuilder.production_active,
        "projection_production_active": DecisionProjectionBuilder.production_active,
        "production_imports": production_imports,
        "prohibited_raw_dependencies": prohibited_raw_dependencies,
        "projection_reinterpretation_tokens": projection_reinterpretation_tokens,
    }


def contract_markdown() -> str:
    return "\n".join(
        [
            "# Step 9 Decision IR Contract",
            "",
            "## Locked meaning",
            "",
            "- CandidateEvaluator 결과, exact RulePack lineage, target binding, disposition, disclosure, policy, safeguards, capability snapshot, plan projection을 하나의 immutable SubDecisionIR로 잠근다.",
            "- execution target과 response target은 별도 binding이며 자동 복사하지 않는다.",
            "- plan projection은 Decision Lock 전에 명시하고 FinalPlanRequirements의 순서와 verb를 바꾸지 못한다.",
            "- semantic terminal 표지는 FinalPlanRequirements에서 손실 없이 복사하며 ask/hold plan에는 terminal을 만들지 않는다.",
            "- ask/hold의 non-execution plan은 공식 미확정이므로 ASSUMPTION-DISPOSITION-PLAN-001을 남긴다.",
            "",
            "## Bundle",
            "",
            "- 단일 operation도 1개 SubDecision을 가진 bundle로 표현한다.",
            "- 복수 operation은 각 disposition과 dependency DAG를 보존한다.",
            "- 공식 aggregate 규칙이 없으므로 복수 bundle에 단일 control을 만들지 않고 MULTIPLE_UNRESOLVED로 둔다.",
            "",
            "## Projection boundary",
            "",
            "- ScopeProjection, PolicyProjection, PlanProjection은 lock digest를 가진 순수 DTO다.",
            "- projection 계층은 prompt, raw record, EvidenceGraph, RulePack, CandidateEvaluator를 재조회하지 않는다.",
            "- Step 9 경로는 shadow-only이며 production output에는 연결하지 않는다.",
            "",
        ]
    )


def build_report(result: dict[str, Any]) -> str:
    lock = result["decision_lock_audit"]
    bundle = result["bundle_audit"]
    boundary = result["boundary_audit"]
    tests = result["tests"]
    gate = result["release_gate"]
    return "\n".join(
        [
            "# Step 9 Decision IR 보고서",
            "",
            "## 구현 범위",
            "",
            "CandidateEvaluator 이후 의미를 immutable SubDecisionIR에 잠그고, 단일·복합 요청 bundle과 raw-free projection DTO를 shadow path로 구현했다.",
            "",
            "## 구조 검증",
            "",
            f"- disposition: `{lock['viable_disposition']}/{lock['ask_disposition']}/{lock['hold_disposition']}`",
            f"- ask/hold plan: `{lock['ask_plan']}/{lock['hold_plan']}`",
            f"- target 분리: `{lock['target_separation_preserved']}`",
            f"- stale mutation 차단: `{lock['stale_mutation_rejected']}`",
            f"- plan order/lineage: `{lock['plan_order_preserved']}/{lock['plan_reason_lineage_preserved']}`",
            f"- semantic terminal 보존: `{lock['semantic_terminal_preserved']}/{lock['non_execution_terminal_absent']}`",
            f"- multi aggregate: `{bundle['aggregate_status']}`",
            f"- dependency cycle 차단: `{bundle['cycle_rejected']}`",
            f"- production import: `{len(boundary['production_imports'])}`개",
            "",
            "## 회귀",
            "",
            f"- Step 9 invariant: exit `{tests['stage_specific']['exit_code']}`, {', '.join(tests['stage_specific']['summary'])}",
            f"- 전체 pytest: exit `{tests['full']['exit_code']}`, {', '.join(tests['full']['summary'])}",
            f"- 알려진 dev gate 제외: exit `{tests['without_known_dev_gate']['exit_code']}`, {', '.join(tests['without_known_dev_gate']['summary'])}",
            f"- dev overall: `{result['dev']['overall']:.4f}` (Step 8과 동일: `{result['dev_unchanged']}`)",
            f"- screening submission 동일: `{result['screening_submission_unchanged']}`",
            "",
            "전체 pytest의 dev hard gate 1건은 기존 baseline debt다. Step 9는 shadow-only이므로 공식 reference 정확도 개선을 주장하지 않는다.",
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
    output_dir = (args.output_dir or report_root / "step9_decision_ir").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_failed_attempt(
        output_dir,
        result_filename="step9_result.json",
        report_filename="STEP9_REPORT.md",
    )
    previous_dir, previous_result, previous_stage = resolve_previous_stage(
        report_root.resolve(),
        PreviousStageSpec("step8_evaluator", "step8_evaluator", "step8_result.json"),
    )
    source_hash_before = source_tree_hash(source_files())

    validation_errors: list[str] = []
    try:
        validate_decision_ir_contract()
    except Exception as exc:
        validation_errors.append(
            f"validate_decision_ir_contract: {type(exc).__name__}: {exc}"
        )

    decision_audit = audit_decision_lock()
    single_decision = decision_audit.pop("single_decision")
    ask_decision = decision_audit.pop("ask_decision")
    bundle_audit = audit_bundle(single_decision, ask_decision)
    boundary_audit = audit_boundaries()
    audit = {
        "decision_lock": decision_audit,
        "bundle": bundle_audit,
        "boundaries": boundary_audit,
    }
    audit_path = output_dir / "decision_ir_audit.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    contract_path = output_dir / "DECISION_IR_CONTRACT.md"
    contract_path.write_text(contract_markdown(), encoding="utf-8")

    regression = run_standard_regression(
        output_dir,
        stage_test_files=(
            "tests/test_decision_ir.py",
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
    lock_checks = {
        "three_dispositions_locked": (
            decision_audit["viable_disposition"] == ExecutionDisposition.PROCEED.value
            and decision_audit["ask_disposition"] == ExecutionDisposition.ASK.value
            and decision_audit["hold_disposition"] == ExecutionDisposition.HOLD.value
        ),
        "non_execution_plans_locked": decision_audit["ask_plan"]
        == [PlanStepType.READ.value, PlanStepType.CLARIFY.value]
        and decision_audit["hold_plan"]
        == [PlanStepType.READ.value, PlanStepType.GUARD.value],
        "target_binding_separate": decision_audit["target_separation_preserved"],
        "stale_mutation_rejected": decision_audit["stale_mutation_rejected"],
        "invalid_capability_lock_rejected": decision_audit[
            "invalid_capability_lock_rejected"
        ],
        "projection_is_lossless": decision_audit["projection_deterministic"]
        and decision_audit["projection_lossless"],
        "plan_order_and_lineage": decision_audit["plan_order_preserved"]
        and decision_audit["semantic_terminal_preserved"]
        and decision_audit["non_execution_terminal_absent"]
        and decision_audit["plan_reason_lineage_preserved"]
        and decision_audit["target_provenance_preserved"],
    }
    bundle_checks = {
        "multi_control_not_invented": bundle_audit["aggregate_status"]
        == AggregateOutputStatus.MULTIPLE_UNRESOLVED.value
        and not bundle_audit["aggregate_control_field_present"]
        and bundle_audit["bundle_assumption_present"],
        "dependency_dag_valid": bundle_audit["dependency_count"] == 1
        and bundle_audit["cycle_rejected"],
        "bundle_input_order_independent": bundle_audit["input_order_independent"],
    }
    checks = {
        "step8_artifact_integrity": bool(previous_stage.get("checks"))
        and all(previous_stage["checks"].values()),
        "contracts_valid": not validation_errors,
        **lock_checks,
        **bundle_checks,
        "raw_free_projection_boundary": not boundary_audit[
            "prohibited_raw_dependencies"
        ]
        and not boundary_audit["projection_reinterpretation_tokens"],
        "shadow_only": not boundary_audit["builder_production_active"]
        and not boundary_audit["projection_production_active"]
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
            "CandidateEvaluator 이후 의미와 plan 순서를 immutable SubDecisionIR에 잠갔다.",
            "execution target과 response target을 분리하고 lineage를 보존했다.",
            "복수 operation의 disposition·dependency를 보존하고 임의 aggregate control을 만들지 않았다.",
            "Step 8 대비 public dev 수치와 screening submission이 변하지 않았다.",
        ]
        if gate_passed
        else [
            f"실패한 Step 9 gate: {name}"
            for name, passed in checks.items()
            if not passed
        ]
        + validation_errors
        + list(previous_stage.get("errors") or []),
    }
    result = {
        "stage": "step9_decision_ir",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_command": f"{sys.executable} {Path(__file__).name}",
        "report_root": str(report_root.resolve()),
        "report_root_source": root_source,
        "output_dir": str(output_dir),
        "previous_stage": previous_stage,
        "source_tree_sha256": source_hash_after,
        "contract_sha256": combined_hash(contract_files(), root=BASE_DIR),
        "audit_sha256": sha256_file(audit_path),
        "decision_lock_audit": decision_audit,
        "bundle_audit": bundle_audit,
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
    result_path = output_dir / "step9_result.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path = output_dir / "STEP9_REPORT.md"
    report_path.write_text(build_report(result), encoding="utf-8")
    write_stage_manifest(
        output_dir,
        stage="step9_decision_ir",
        source_hash=source_hash_after,
        artifact_paths=(
            audit_path,
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
