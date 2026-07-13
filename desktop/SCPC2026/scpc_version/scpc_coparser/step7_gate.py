from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from build_manifest import sha256_file, source_files, source_tree_hash
from core.constraints import (
    GLOBAL_CONSTRAINT_REGISTRY,
    PAIR_CONSTRAINT_REGISTRY,
    ConstraintActivationState,
    ConstraintCandidateContext,
    ConstraintEffectAlgebra,
    ConstraintFactPolarity,
    EffectAlgebraStatus,
    PairConstraintActivator,
    validate_constraint_registries,
)
from core.ontology import Domain, Operation, TargetLocality, TargetRole
from core.rulepacks import (
    CONSTRAINT_CATALOG,
    RULEPACK_REGISTRY,
    RegistryImplementationStatus,
    RulePackKey,
)
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
from utils.io import find_data_dir, load_jsonl


def contract_files() -> tuple[Path, ...]:
    return (
        BASE_DIR / "core" / "contracts.py",
        BASE_DIR / "core" / "ontology.py",
        BASE_DIR / "core" / "ownership.py",
        BASE_DIR / "core" / "rulepacks.py",
        BASE_DIR / "core" / "constraints.py",
        BASE_DIR / "core" / "plan_requirements.py",
    )


def registry_snapshot() -> dict[str, Any]:
    return {
        "production_active": {
            "global": GLOBAL_CONSTRAINT_REGISTRY.production_active,
            "pair": PAIR_CONSTRAINT_REGISTRY.production_active,
        },
        "global_rules": [
            {
                "record_type": item.record_type.value,
                "constraint_type": item.constraint_type.value,
                "inactive_codes": [code.value for code in item.inactive_codes],
            }
            for item in GLOBAL_CONSTRAINT_REGISTRY.rules
        ],
        "pair_specs": [
            {
                "constraint_id": item.constraint_id,
                "constraint_type": item.constraint_type.value,
                "applicability": [
                    {
                        "key": {
                            "domain": applicability.key.domain.value,
                            "operation": applicability.key.operation.value,
                            "variant": (
                                applicability.key.variant.value
                                if applicability.key.variant
                                else None
                            ),
                        },
                        "target_localities": [
                            locality.value
                            for locality in applicability.target_localities
                        ],
                    }
                    for applicability in item.applicability
                ],
                "source_record_types": [
                    record_type.value for record_type in item.source_record_types
                ],
                "effect_rules": [
                    {
                        "source_record_type": rule.source_record_type.value,
                        "effect": rule.effect.value,
                        "reason_code": rule.reason_code.value,
                        "required_codes": [
                            code.value for code in rule.required_codes
                        ],
                        "parameter_source": rule.parameter_source.value,
                    }
                    for rule in item.effect_rules
                ],
                "contract_status": item.contract_status.value,
                "basis_refs": [ref.value for ref in item.basis_refs],
                "assumption_refs": list(item.assumption_refs),
                "version": item.version,
            }
            for item in PAIR_CONSTRAINT_REGISTRY.specs
        ],
    }


def audit_official_constraint_facts() -> dict[str, Any]:
    data_dir = find_data_dir()
    tasks = load_jsonl(data_dir / "dev_tasks.jsonl") + load_jsonl(
        data_dir / "screening_tasks.jsonl"
    )
    fact_types: Counter[str] = Counter()
    polarities: Counter[str] = Counter()
    errors: list[str] = []
    for task in tasks:
        task_id = str(task.get("id") or "")
        try:
            view = TaskView(task)
            facts = GLOBAL_CONSTRAINT_REGISTRY.collect(view.typed_records)
            for fact in facts:
                fact_types[fact.record_type.value] += 1
                polarities[fact.polarity.value] += 1
        except Exception as exc:
            errors.append(f"{task_id}: {type(exc).__name__}: {exc}")
    return {
        "task_count": len(tasks),
        "structurally_processed": len(tasks) - len(errors),
        "fact_types": dict(sorted(fact_types.items())),
        "polarities": dict(sorted(polarities.items())),
        "errors": errors,
        "accuracy_claimed": False,
    }


def _synthetic_view(records: list[dict[str, object]]) -> TaskView:
    return TaskView(
        {
            "id": "gate:constraint",
            "session_id": "gate:session",
            "turn_index": 1,
            "prompt": "",
            "visible_history": [],
            "personal_memory": [],
            "device_state": {"objects": [], "records": records},
            "available_actions": [],
        }
    )


def _content_context(locality: TargetLocality) -> ConstraintCandidateContext:
    return ConstraintCandidateContext(
        candidate_id="gate:candidate",
        rulepack_key=RulePackKey(Domain.CONTENT, Operation.SHARE),
        focal_id="gate:focal",
        target_id="gate:target",
        target_role=TargetRole.DISPATCH_DESTINATION,
        target_locality=locality,
    )


def audit_counterfactuals() -> dict[str, Any]:
    records = [
        {"id": "consent", "type": "consent", "value": "revoked"},
        {
            "id": "policy",
            "type": "external_share_policy",
            "value": "raw_quote_forbidden",
        },
    ]
    view = _synthetic_view(records)
    direct_first = GLOBAL_CONSTRAINT_REGISTRY.collect(view.direct_record_facts)
    direct_reversed = GLOBAL_CONSTRAINT_REGISTRY.collect(
        reversed(view.direct_record_facts)
    )
    resolution = RULEPACK_REGISTRY.resolve_exact(
        RulePackKey(Domain.CONTENT, Operation.SHARE)
    )
    assert resolution.rulepack is not None
    external = PairConstraintActivator.activate(
        context=_content_context(TargetLocality.EXTERNAL),
        rulepack=resolution.rulepack,
        global_facts=direct_first,
    )
    local = PairConstraintActivator.activate(
        context=_content_context(TargetLocality.LOCAL),
        rulepack=resolution.rulepack,
        global_facts=direct_first,
    )
    composed = ConstraintEffectAlgebra.compose(external.constraints)
    reversed_composed = ConstraintEffectAlgebra.compose(
        reversed(external.constraints)
    )
    duplicated = ConstraintEffectAlgebra.compose(
        external.constraints + external.constraints
    )

    conflict_view = _synthetic_view(
        [
            {"id": "consent-a", "type": "consent", "value": "granted"},
            {"id": "consent-b", "type": "consent", "value": "revoked"},
        ]
    )
    conflict_facts = GLOBAL_CONSTRAINT_REGISTRY.collect(
        conflict_view.direct_record_facts
    )
    conflicted = PairConstraintActivator.activate(
        context=_content_context(TargetLocality.EXTERNAL),
        rulepack=resolution.rulepack,
        global_facts=conflict_facts,
    )
    conflict_algebra = ConstraintEffectAlgebra.compose(conflicted.constraints)

    return {
        "record_permutation_equal": direct_first == direct_reversed,
        "effect_permutation_equal": composed == reversed_composed,
        "effect_idempotent": composed == duplicated,
        "external_blocks": composed.blocks_execution,
        "external_effects": [item.effect.value for item in composed.effects],
        "local_active_constraints": len(local.active_constraints),
        "conflicted_fact_preserved": any(
            item.polarity == ConstraintFactPolarity.CONFLICTED
            for item in conflict_facts
        ),
        "conflicted_activation_preserved": any(
            item.state == ConstraintActivationState.CONFLICTED
            for item in conflicted.evaluations
        ),
        "conflicted_algebra_status": conflict_algebra.status.value,
        "composed_status": composed.status.value,
    }


def audit_boundaries() -> dict[str, Any]:
    production_imports: list[str] = []
    for relative in ("core/decision.py", "harness.py", "rules/plan.py"):
        source = (BASE_DIR / relative).read_text(encoding="utf-8")
        if "from .constraints" in source or "core.constraints" in source:
            production_imports.append(relative)
    constraint_source = (BASE_DIR / "core" / "constraints.py").read_text(
        encoding="utf-8"
    )
    prohibited_tokens = (
        "ExecutionDisposition",
        "CandidateDispositionPolicy",
        "default_dispatch",
        "visible_history",
        "re.compile",
    )
    return {
        "production_imports": production_imports,
        "production_active": (
            GLOBAL_CONSTRAINT_REGISTRY.production_active
            or PAIR_CONSTRAINT_REGISTRY.production_active
        ),
        "prohibited_tokens": [
            token for token in prohibited_tokens if token in constraint_source
        ],
        "catalog_implemented": all(
            item.implementation_status == RegistryImplementationStatus.IMPLEMENTED
            and item.activation_stage == 7
            for item in CONSTRAINT_CATALOG
        ),
    }


def contract_markdown() -> str:
    return "\n".join(
        [
            "# Step 7 Constraint Effect Algebra 계약",
            "",
            "## Fact와 Activation 분리",
            "",
            "GlobalConstraintRegistry는 TypedRecordFact를 canonical GlobalConstraintFact로 정규화한다. record presence 자체는 control이 아니며, exact RulePack의 PairConstraintSpec과 target locality가 일치할 때만 후보별 effect가 활성화된다.",
            "",
            "## 상태 보존",
            "",
            "ACTIVE, INACTIVE, CONFLICTED, UNRESOLVED를 분리한다. 서로 다른 값의 duplicate record에는 배열 순서나 임의 최신값을 적용하지 않는다.",
            "",
            "## Effect Algebra",
            "",
            "동일 `(effect, scope, parameters)`는 멱등 병합하면서 모든 source constraint와 fact ID를 보존한다. canonical 순서는 redact, summarize, confirmation, duration, target restriction, block이다. 서로 다른 duration limit처럼 공식 우선순위가 없는 충돌은 CONFLICTED다. BLOCK_EXECUTION을 해제하는 effect는 등록하지 않는다.",
            "",
            "## 계약 경계",
            "",
            "ConstraintEffect는 disposition이나 output control을 확정하지 않는다. record type/value에서 exact effect로의 mapping은 supported interpretation이며 `ASSUMPTION-CONSTRAINT-EFFECT-001`로 추적한다. Step 8 전까지 registry는 shadow-only다.",
            "",
        ]
    )


def build_report(result: dict[str, Any]) -> str:
    tests = result["tests"]
    official = result["official_fact_audit"]
    counterfactual = result["counterfactual_audit"]
    boundary = result["boundary_audit"]
    gate = result["release_gate"]
    return "\n".join(
        [
            "# Step 7 Constraint Registry 보고서",
            "",
            "## 구현 범위",
            "",
            "Typed record fact 수집, exact pair activation, canonical effect algebra를 shadow path로 구현했다. CandidateState, control, fallback은 이 단계에서 결정하지 않는다.",
            "",
            "## 검증 결과",
            "",
            f"- Global fact rule: `{len(GLOBAL_CONSTRAINT_REGISTRY.rules)}`개",
            f"- PairConstraintSpec: `{len(PAIR_CONSTRAINT_REGISTRY.specs)}`개",
            f"- 공식 task 구조 처리: `{official['structurally_processed']}/{official['task_count']}`",
            f"- 공식 task fact 수집 오류: `{len(official['errors'])}`개",
            f"- record permutation 동일: `{counterfactual['record_permutation_equal']}`",
            f"- effect permutation 동일: `{counterfactual['effect_permutation_equal']}`",
            f"- duplicate effect 멱등성: `{counterfactual['effect_idempotent']}`",
            f"- local counterfactual active constraint: `{counterfactual['local_active_constraints']}`개",
            f"- production import: `{len(boundary['production_imports'])}`개",
            "",
            "`structurally_processed`는 accuracy가 아니다. 정답 없는 screening의 semantic correctness를 주장하지 않는다.",
            "",
            "## 회귀",
            "",
            f"- Step 7 invariant: exit `{tests['stage_specific']['exit_code']}`, {', '.join(tests['stage_specific']['summary'])}",
            f"- 전체 pytest: exit `{tests['full']['exit_code']}`, {', '.join(tests['full']['summary'])}",
            f"- 알려진 dev gate 제외: exit `{tests['without_known_dev_gate']['exit_code']}`, {', '.join(tests['without_known_dev_gate']['summary'])}",
            f"- dev overall: `{result['dev']['overall']:.4f}` (Step 6와 동일: `{result['dev_unchanged']}`)",
            f"- screening submission 동일: `{result['screening_submission_unchanged']}`",
            "",
            "전체 pytest의 dev hard gate 1건은 기존 baseline debt로 남아 있다.",
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
    output_dir = (args.output_dir or report_root / "step7_constraints").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_failed_attempt(
        output_dir,
        result_filename="step7_result.json",
        report_filename="STEP7_REPORT.md",
    )
    previous_dir, previous_result, previous_stage = resolve_previous_stage(
        report_root.resolve(),
        PreviousStageSpec("step6_blueprints", "step6_blueprints", "step6_result.json"),
    )
    source_hash_before = source_tree_hash(source_files())

    validation_errors: list[str] = []
    try:
        validate_constraint_registries()
    except Exception as exc:
        validation_errors.append(
            f"validate_constraint_registries: {type(exc).__name__}: {exc}"
        )

    snapshot = registry_snapshot()
    snapshot_path = output_dir / "constraint_registry.json"
    snapshot_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    contract_path = output_dir / "CONSTRAINT_EFFECT_ALGEBRA.md"
    contract_path.write_text(contract_markdown(), encoding="utf-8")
    official_audit = audit_official_constraint_facts()
    counterfactual_audit = audit_counterfactuals()
    boundary_audit = audit_boundaries()
    audit_path = output_dir / "constraint_audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "official_facts": official_audit,
                "counterfactuals": counterfactual_audit,
                "boundaries": boundary_audit,
            },
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
            "tests/test_constraints.py",
            "tests/test_plan_requirements.py",
            "tests/test_rulepacks.py",
            "tests/test_ontology.py",
            "tests/test_architecture.py",
        ),
        previous_dir=previous_dir,
        previous_result=previous_result,
    )
    source_hash_after = source_tree_hash(source_files())
    checks = {
        "step6_artifact_integrity": bool(previous_stage.get("checks"))
        and all(previous_stage["checks"].values()),
        "constraint_registries_valid": not validation_errors,
        "catalog_implemented": boundary_audit["catalog_implemented"],
        "official_shapes_processed": not official_audit["errors"]
        and official_audit["structurally_processed"] == official_audit["task_count"],
        "record_permutation": counterfactual_audit["record_permutation_equal"],
        "effect_permutation": counterfactual_audit["effect_permutation_equal"],
        "effect_idempotence": counterfactual_audit["effect_idempotent"],
        "pair_specific_counterfactual": counterfactual_audit[
            "local_active_constraints"
        ]
        == 0,
        "hard_block_monotonic": counterfactual_audit["external_blocks"],
        "conflict_preserved": counterfactual_audit[
            "conflicted_fact_preserved"
        ]
        and counterfactual_audit["conflicted_activation_preserved"]
        and counterfactual_audit["conflicted_algebra_status"]
        == EffectAlgebraStatus.CONFLICTED.value,
        "shadow_only": not boundary_audit["production_active"]
        and not boundary_audit["production_imports"],
        "boundary_isolation": not boundary_audit["prohibited_tokens"],
        "source_stable_during_gate": source_hash_before == source_hash_after,
        **standard_regression_checks(regression),
    }
    gate_passed = all(checks.values())
    release_gate = {
        "status": "PASS_WITH_BASELINE_DEBT" if gate_passed else "FAIL",
        "next_stage_allowed": gate_passed,
        "checks": checks,
        "reasons": [
            "Global fact와 pair activation 경계가 전수 구조 검사와 반례를 통과했다.",
            "effect permutation, idempotence, conflict 보존 검증이 통과했다.",
            "constraint가 control을 직접 소유하지 않고 production에서 비활성임을 확인했다.",
            "Step 6 대비 public dev 수치와 screening submission이 변하지 않았다.",
        ]
        if gate_passed
        else [
            f"실패한 Step 7 gate: {name}"
            for name, passed in checks.items()
            if not passed
        ]
        + validation_errors
        + official_audit["errors"]
        + list(previous_stage.get("errors") or []),
    }
    result = {
        "stage": "step7_constraints",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_command": f"{sys.executable} {Path(__file__).name}",
        "report_root": str(report_root.resolve()),
        "report_root_source": root_source,
        "output_dir": str(output_dir),
        "previous_stage": previous_stage,
        "source_tree_sha256": source_hash_after,
        "contract_sha256": combined_hash(contract_files(), root=BASE_DIR),
        "constraint_registry_sha256": sha256_file(snapshot_path),
        "official_fact_audit": official_audit,
        "counterfactual_audit": counterfactual_audit,
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
    result_path = output_dir / "step7_result.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path = output_dir / "STEP7_REPORT.md"
    report_path.write_text(build_report(result), encoding="utf-8")
    write_stage_manifest(
        output_dir,
        stage="step7_constraints",
        source_hash=source_hash_after,
        artifact_paths=(
            snapshot_path,
            contract_path,
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
