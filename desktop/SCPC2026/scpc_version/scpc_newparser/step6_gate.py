from __future__ import annotations

import argparse
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
import sys
from typing import Any

from build_manifest import sha256_file, source_files, source_tree_hash
from core.ontology import ConstraintEffect, Domain, Operation
from core.plan_requirements import (
    PLAN_BLUEPRINT_REGISTRY,
    FinalPlanRequirementsBuilder,
    PlanRequirementDelta,
    PlanRequirementDeltaSource,
    validate_plan_blueprint_registry,
)
from core.rulepacks import (
    BLUEPRINT_CATALOG,
    CONSTRAINT_CATALOG,
    RULEPACK_REGISTRY,
    RegistryImplementationStatus,
    RulePackKey,
)
from core.slm_contract import (
    PIPELINE_ORDER,
    PipelineStage,
    SLMInfluenceStatus,
    SLMMergeStatus,
    SLMValidationStatus,
    validate_slm_contract,
)
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
        BASE_DIR / "core" / "ownership.py",
        BASE_DIR / "core" / "rulepacks.py",
        BASE_DIR / "core" / "plan_requirements.py",
        BASE_DIR / "core" / "slm_contract.py",
    )


def blueprint_snapshot() -> dict[str, Any]:
    return {
        "production_active": PLAN_BLUEPRINT_REGISTRY.production_active,
        "blueprints": [
            {
                "blueprint_id": item.blueprint_id,
                "rulepack_key": {
                    "domain": item.key.domain.value,
                    "operation": item.key.operation.value,
                    "variant": item.key.variant.value if item.key.variant else None,
                },
                "semantic_terminal": item.semantic_terminal.value,
                "base_steps": [
                    {
                        "step_id": step.step_id,
                        "identity": step.identity.value,
                        "requirement_class": step.requirement_class.value,
                        "platform_capability": (
                            step.platform_capability.value
                            if step.platform_capability
                            else None
                        ),
                        "output_verb": (
                            step.output_verb.value if step.output_verb else None
                        ),
                        "internal_transform": (
                            step.internal_transform.value
                            if step.internal_transform
                            else None
                        ),
                        "semantic_terminal": step.semantic_terminal,
                    }
                    for step in item.base_steps
                ],
                "platform_required_capabilities": [
                    capability.value
                    for capability in item.platform_required_capabilities
                ],
                "internal_transform_requirements": [
                    transform.value
                    for transform in item.internal_transform_requirements
                ],
                "required_target_roles": [
                    role.value for role in item.required_target_roles
                ],
                "base_information_slots": [
                    slot.value for slot in item.base_information_slots
                ],
                "conditional_information_slots": [
                    slot.value for slot in item.conditional_information_slots
                ],
                "permitted_disclosure_modes": [
                    mode.value for mode in item.permitted_disclosure_modes
                ],
                "dependency_semantics": [
                    {
                        "before": edge.before_step_id,
                        "after": edge.after_step_id,
                        "kind": edge.kind.value,
                    }
                    for edge in item.dependency_semantics
                ],
                "contract_status": item.contract_status.value,
                "assumption_refs": list(item.assumption_refs),
                "version": item.version,
            }
            for item in PLAN_BLUEPRINT_REGISTRY.blueprints
        ],
    }


def _delta(effect_id: str, effect: ConstraintEffect) -> PlanRequirementDelta:
    return PlanRequirementDelta(
        effect_id=effect_id,
        effect_kind=effect,
        source_id=f"gate:{effect_id}",
        scope="candidate:gate",
        source_kind=PlanRequirementDeltaSource.ACTIVE_CONSTRAINT,
    )


def audit_plan_requirements() -> dict[str, Any]:
    errors: list[str] = []
    terminal_counts: dict[str, int] = {}
    for pack in RULEPACK_REGISTRY.rulepacks:
        try:
            requirements = FinalPlanRequirementsBuilder.build(
                candidate_id=f"gate:{pack.rule_id}",
                resolution=RULEPACK_REGISTRY.resolve_exact(pack.key),
            )
            terminal_counts[pack.rule_id] = sum(
                step.semantic_terminal for step in requirements.required_steps
            )
        except Exception as exc:
            errors.append(f"{pack.rule_id}: {type(exc).__name__}: {exc}")

    content_resolution = RULEPACK_REGISTRY.resolve_exact(
        RulePackKey(Domain.CONTENT, Operation.SHARE)
    )
    deltas = (
        _delta("redact-b", ConstraintEffect.ADD_REDACTION),
        _delta("summary", ConstraintEffect.FORCE_SUMMARY),
        _delta("redact-a", ConstraintEffect.ADD_REDACTION),
    )
    first = FinalPlanRequirementsBuilder.build(
        candidate_id="gate:permutation",
        resolution=content_resolution,
        deltas=deltas,
    )
    second = FinalPlanRequirementsBuilder.build(
        candidate_id="gate:permutation",
        resolution=content_resolution,
        deltas=reversed(deltas),
    )

    production_imports: list[str] = []
    for relative in ("core/decision.py", "harness.py", "rules/plan.py"):
        source = (BASE_DIR / relative).read_text(encoding="utf-8")
        if "plan_requirements" in source or "slm_contract" in source:
            production_imports.append(relative)

    return {
        "blueprint_count": len(PLAN_BLUEPRINT_REGISTRY.blueprints),
        "catalog_count": len(BLUEPRINT_CATALOG),
        "catalog_implemented": all(
            item.implementation_status == RegistryImplementationStatus.IMPLEMENTED
            and item.activation_stage == 6
            for item in BLUEPRINT_CATALOG
        ),
        "constraints_still_stubbed": all(
            item.implementation_status == RegistryImplementationStatus.STUB
            and item.activation_stage == 7
            for item in CONSTRAINT_CATALOG
        ),
        "terminal_counts": terminal_counts,
        "all_terminal_counts_one": bool(terminal_counts)
        and all(count == 1 for count in terminal_counts.values()),
        "effect_permutation_equal": first == second,
        "effect_trace_ids": list(first.applied_effect_ids),
        "production_imports": production_imports,
        "production_active": PLAN_BLUEPRINT_REGISTRY.production_active,
        "errors": errors,
    }


def slm_contract_snapshot() -> dict[str, Any]:
    positions = {stage: index for index, stage in enumerate(PIPELINE_ORDER)}
    source = inspect.getsource(sys.modules["core.slm_contract"])
    runtime_tokens = (
        "transformers",
        "torch",
        "requests",
        "openai",
        "model.generate",
    )
    return {
        "pipeline_order": [stage.value for stage in PIPELINE_ORDER],
        "rulepack_before_blueprint": positions[PipelineStage.RULEPACK_LOOKUP]
        < positions[PipelineStage.BASE_BLUEPRINT_LOAD],
        "blueprint_before_constraint": positions[
            PipelineStage.BASE_BLUEPRINT_LOAD
        ]
        < positions[PipelineStage.GLOBAL_CONSTRAINT_ACTIVATION],
        "requirements_before_capability": positions[
            PipelineStage.FINAL_PLAN_REQUIREMENTS
        ]
        < positions[PipelineStage.FULL_CAPABILITY_EVALUATION],
        "capability_before_evaluator": positions[
            PipelineStage.FULL_CAPABILITY_EVALUATION
        ]
        < positions[PipelineStage.CANDIDATE_EVALUATOR],
        "validation_statuses": [item.value for item in SLMValidationStatus],
        "merge_statuses": [item.value for item in SLMMergeStatus],
        "influence_statuses": [item.value for item in SLMInfluenceStatus],
        "accepted_shortcut_absent": all(
            "ACCEPTED" not in enum.__members__
            for enum in (
                SLMValidationStatus,
                SLMMergeStatus,
                SLMInfluenceStatus,
            )
        ),
        "runtime_dependencies": [token for token in runtime_tokens if token in source],
        "production_active": False,
    }


def contract_markdown() -> str:
    return "\n".join(
        [
            "# Step 6 Blueprint·FinalPlanRequirements 계약",
            "",
            "## 구성 순서",
            "",
            "exact RulePack을 조회한 뒤 BasePlanBlueprint를 먼저 로드한다. Role과 Information을 평가하고 Global·Pair constraint를 활성화한 뒤에만 effect를 합성해 FinalPlanRequirements를 만든다. 전체 capability와 CandidateEvaluator는 그 이후 단계다.",
            "",
            "## 단일 의미 소유권",
            "",
            "BasePlanBlueprint는 base semantic terminal과 요구 사항을 소유한다. PlanRequirementComposer는 활성 constraint effect 또는 authorization reference가 있는 modification만 canonical delta로 합성한다. Compiler는 FinalPlanRequirements에 없는 의미를 추가할 수 없다.",
            "",
            "## 타입 경계",
            "",
            "platform capability와 internal requirement를 별도 enum과 필드로 유지한다. `available_actions`의 공식 적용 범위는 unresolved assumption으로 남긴다.",
            "",
            "## 단계 잠금",
            "",
            "Step 6 registry는 shadow-only다. Step 7 constraint activation과 Step 8 evaluator가 완료되기 전에는 production decision path에 연결하지 않는다. 따라서 이 단계의 consumer 일치는 new-path DTO 계약의 일치이며 production 전환 완료를 뜻하지 않는다.",
            "",
        ]
    )


def slm_amendment_markdown() -> str:
    return "\n".join(
        [
            "# SLM 통합 계약 수정",
            "",
            "- SLM은 ambiguity trigger에서만 낮은 authority proposal을 추가한다.",
            "- validation, merge, influence 상태를 서로 다른 축으로 유지한다.",
            "- 검증 직후 proposal은 `PROPOSED`이며 확정 Evidence가 아니다.",
            "- semantic proposal은 entity reference가 없어도 되며 reference proposal만 기존 ID 검증을 요구한다.",
            "- exact RulePack이 없으면 `UNSUPPORTED_RULEPACK`으로 거절하고 유사 pack이나 dispatch로 대체하지 않는다.",
            "- authority는 같은 semantic slot, scope, target 안에서 축별 partial order로만 비교한다.",
            "- SLM 실패는 disposition을 직접 만들지 않는다. parser-only disposition을 별도 trace로 기록한다.",
            "- 현재 repository에는 SLM runtime이 없으므로 adapter나 모델 dependency를 추가하지 않았다.",
            "",
        ]
    )


def build_report(result: dict[str, Any]) -> str:
    tests = result["tests"]
    audit = result["plan_audit"]
    slm = result["slm_contract"]
    gate = result["release_gate"]
    return "\n".join(
        [
            "# Step 6 Blueprint·Plan Requirements 보고서",
            "",
            "## 구현 범위",
            "",
            "14개 exact RulePack에 대응하는 BasePlanBlueprint와 canonical FinalPlanRequirements composer를 shadow registry로 구현했다. constraint registry는 Step 7 전까지 stub으로 유지했다.",
            "",
            "SLM 관련 변경은 상태·pipeline·authority 계약 타입과 invariant에 한정했다. SLM adapter, 모델 호출, production EvidenceGraph 병합은 구현하지 않았다.",
            "",
            "## 구조 검증",
            "",
            f"- Blueprint: `{audit['blueprint_count']}`개 / catalog `{audit['catalog_count']}`개",
            f"- semantic terminal 1개 보장: `{audit['all_terminal_counts_one']}`",
            f"- effect permutation 동일: `{audit['effect_permutation_equal']}`",
            f"- production import: `{len(audit['production_imports'])}`개",
            f"- Step 7 constraint stub 유지: `{audit['constraints_still_stubbed']}`",
            f"- SLM ACCEPTED shortcut 없음: `{slm['accepted_shortcut_absent']}`",
            f"- SLM runtime dependency: `{len(slm['runtime_dependencies'])}`개",
            "",
            "## 회귀 검증",
            "",
            f"- Step 6 invariant: exit `{tests['stage_specific']['exit_code']}`, {', '.join(tests['stage_specific']['summary'])}",
            f"- 전체 pytest: exit `{tests['full']['exit_code']}`, {', '.join(tests['full']['summary'])}",
            f"- 알려진 dev gate 제외: exit `{tests['without_known_dev_gate']['exit_code']}`, {', '.join(tests['without_known_dev_gate']['summary'])}",
            f"- dev overall: `{result['dev']['overall']:.4f}` (Step 5와 동일: `{result['dev_unchanged']}`)",
            f"- screening submission 동일: `{result['screening_submission_unchanged']}`",
            "",
            "전체 pytest의 dev hard gate 1건은 기존 baseline debt다. Step 6에서 해결하거나 허용한 것으로 처리하지 않았다.",
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
    output_dir = (args.output_dir or report_root / "step6_blueprints").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_failed_attempt(
        output_dir,
        result_filename="step6_result.json",
        report_filename="STEP6_REPORT.md",
    )
    previous_dir, previous_result, previous_stage = resolve_previous_stage(
        report_root.resolve(),
        PreviousStageSpec("step5_rulepacks", "step5_rulepacks", "step5_result.json"),
    )
    source_hash_before = source_tree_hash(source_files())

    validation_errors: list[str] = []
    for validator in (validate_plan_blueprint_registry, validate_slm_contract):
        try:
            validator()
        except Exception as exc:
            validation_errors.append(
                f"{validator.__name__}: {type(exc).__name__}: {exc}"
            )

    snapshot = blueprint_snapshot()
    snapshot_path = output_dir / "plan_blueprint_registry.json"
    snapshot_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    plan_contract_path = output_dir / "PLAN_REQUIREMENTS_CONTRACT.md"
    plan_contract_path.write_text(contract_markdown(), encoding="utf-8")
    slm_contract_path = output_dir / "SLM_CONTRACT_AMENDMENT.md"
    slm_contract_path.write_text(slm_amendment_markdown(), encoding="utf-8")
    plan_audit = audit_plan_requirements()
    slm_snapshot = slm_contract_snapshot()
    audit_path = output_dir / "step6_contract_audit.json"
    audit_path.write_text(
        json.dumps(
            {"plan": plan_audit, "slm": slm_snapshot},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    regression = run_standard_regression(
        output_dir,
        stage_test_files=(
            "tests/test_plan_requirements.py",
            "tests/test_slm_contract.py",
            "tests/test_rulepacks.py",
            "tests/test_ontology.py",
            "tests/test_architecture.py",
        ),
        previous_dir=previous_dir,
        previous_result=previous_result,
    )
    source_hash_after = source_tree_hash(source_files())
    checks = {
        "step5_artifact_integrity": bool(previous_stage.get("checks"))
        and all(previous_stage["checks"].values()),
        "contract_valid": not validation_errors,
        "blueprint_catalog_coverage": (
            plan_audit["blueprint_count"] == plan_audit["catalog_count"]
            and plan_audit["catalog_implemented"]
            and not plan_audit["errors"]
        ),
        "one_semantic_terminal": plan_audit["all_terminal_counts_one"],
        "effect_permutation": plan_audit["effect_permutation_equal"],
        "step7_constraints_inactive": plan_audit["constraints_still_stubbed"],
        "shadow_only": not plan_audit["production_active"]
        and not plan_audit["production_imports"],
        "slm_pipeline_order": all(
            slm_snapshot[name]
            for name in (
                "rulepack_before_blueprint",
                "blueprint_before_constraint",
                "requirements_before_capability",
                "capability_before_evaluator",
            )
        ),
        "slm_status_axes": slm_snapshot["accepted_shortcut_absent"],
        "no_slm_runtime_dependency": not slm_snapshot["runtime_dependencies"],
        "source_stable_during_gate": source_hash_before == source_hash_after,
        **standard_regression_checks(regression),
    }
    gate_passed = all(checks.values())
    release_gate = {
        "status": "PASS_WITH_BASELINE_DEBT" if gate_passed else "FAIL",
        "next_stage_allowed": gate_passed,
        "checks": checks,
        "reasons": [
            "BasePlanBlueprint coverage와 FinalPlanRequirements invariant가 통과했다.",
            "Blueprint 선행, capability 선행 CandidateEvaluator 순서를 계약으로 고정했다.",
            "SLM validation·merge·influence 상태와 scoped authority를 분리했다.",
            "Step 5 대비 public dev 수치와 screening submission이 변하지 않았다.",
        ]
        if gate_passed
        else [
            f"실패한 Step 6 gate: {name}"
            for name, passed in checks.items()
            if not passed
        ]
        + validation_errors
        + plan_audit["errors"]
        + list(previous_stage.get("errors") or []),
    }
    result = {
        "stage": "step6_blueprints",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_command": f"{sys.executable} {Path(__file__).name}",
        "report_root": str(report_root.resolve()),
        "report_root_source": root_source,
        "output_dir": str(output_dir),
        "previous_stage": previous_stage,
        "source_tree_sha256": source_hash_after,
        "contract_sha256": combined_hash(contract_files(), root=BASE_DIR),
        "blueprint_registry_sha256": sha256_file(snapshot_path),
        "plan_audit": plan_audit,
        "slm_contract": slm_snapshot,
        "dev": regression["dev"],
        "dev_unchanged": regression["dev_unchanged"],
        "screening_submission_sha256": regression["submission_sha256"],
        "screening_submission_unchanged": regression["submission_unchanged"],
        "tests": regression["tests"],
        "validation_errors": validation_errors,
        "release_gate": release_gate,
        "stage_manifest_path": str(output_dir / "stage_manifest.json"),
    }
    result_path = output_dir / "step6_result.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path = output_dir / "STEP6_REPORT.md"
    report_path.write_text(build_report(result), encoding="utf-8")
    write_stage_manifest(
        output_dir,
        stage="step6_blueprints",
        source_hash=source_hash_after,
        artifact_paths=(
            snapshot_path,
            plan_contract_path,
            slm_contract_path,
            audit_path,
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
