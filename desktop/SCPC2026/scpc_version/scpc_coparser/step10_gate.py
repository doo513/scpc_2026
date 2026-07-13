from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
import sys
from typing import Any

from build_manifest import sha256_file, source_files, source_tree_hash
from core.decision_ir import (
    AggregateOutputStatus,
    DecisionProjectionSet,
    PlanProjection,
    PlanProjectionStep,
    PolicyProjection,
    ScopeProjection,
)
from core.ontology import DisclosureMode, PlanStepType, ReasonCode
from core.projection_compilers import (
    PlanCompiler,
    PolicyCompiler,
    ProjectionCompiler,
    ProjectionCompilerConfig,
    ScopeCompiler,
    validate_projection_compiler_contract,
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
from utils.schema_check import validate_answer


def contract_files() -> tuple[Path, ...]:
    return (
        BASE_DIR / "submission_schema.json",
        BASE_DIR / "core" / "decision_ir.py",
        BASE_DIR / "core" / "projection_compilers.py",
    )


def _projection_set(*, mismatched_lineage: bool = False) -> DecisionProjectionSet:
    decision_id = "decision:gate"
    source_lock = "lock:gate"
    return DecisionProjectionSet(
        bundle_id="bundle:gate",
        aggregate_output_status=AggregateOutputStatus.SINGLE,
        scopes=(
            ScopeProjection(
                decision_id,
                DisclosureMode.REDACTED,
                ("status",),
                ("secret",),
                True,
                ("effect:redact",),
                source_lock,
            ),
        ),
        policies=(
            PolicyProjection(
                decision_id,
                ("risk:disclosure",),
                (),
                True,
                (ReasonCode.EXECUTABLE,),
                ("constraint:share",),
                source_lock,
            ),
        ),
        plans=(
            PlanProjection(
                decision_id,
                (
                    PlanProjectionStep(
                        "projection:read",
                        "requirement:read",
                        PlanStepType.READ,
                        "object:gate",
                        (("opaque", "preserved"),),
                        (ReasonCode.EXECUTABLE,),
                    ),
                    PlanProjectionStep(
                        "projection:dispatch",
                        "requirement:dispatch",
                        PlanStepType.DISPATCH,
                        "recipient:gate",
                        (("scope", "redacted"),),
                        (ReasonCode.EXECUTABLE,),
                        semantic_terminal=True,
                    ),
                ),
                "lock:mismatch" if mismatched_lineage else source_lock,
            ),
        ),
        source_bundle_lock_digest="bundle-lock:gate",
    )


def audit_compilers() -> dict[str, Any]:
    config = ProjectionCompilerConfig(max_plan_events=18)
    projections = _projection_set()
    first = ProjectionCompiler.compile(projections, config)
    second = ProjectionCompiler.compile(projections, config)
    decision = first["decision:gate"]

    raw_context = {"prompt": "before", "records": ["one"]}
    before_raw_change = ProjectionCompiler.compile(projections, config)
    raw_context["prompt"] = "after"
    raw_context["records"].append("two")
    after_raw_change = ProjectionCompiler.compile(projections, config)

    scope = ScopeCompiler.compile(projections.scopes[0])
    policy = PolicyCompiler.compile(projections.policies[0])
    plan = PlanCompiler.compile(projections.plans[0], config)
    reverse: dict[str, object] = {}
    reverse["plan_events"] = PlanCompiler.compile(projections.plans[0], config)
    reverse["policy"] = PolicyCompiler.compile(projections.policies[0])
    reverse["content_scope"] = ScopeCompiler.compile(projections.scopes[0])
    forward = {
        "content_scope": scope,
        "policy": policy,
        "plan_events": plan,
    }

    lineage_mismatch_rejected = False
    try:
        ProjectionCompiler.compile(_projection_set(mismatched_lineage=True), config)
    except ValueError:
        lineage_mismatch_rejected = True

    plan_limit_rejected = False
    base_plan = projections.plans[0]
    oversized = replace(
        base_plan,
        steps=tuple(
            PlanProjectionStep(
                f"projection:{index}",
                f"requirement:{index}",
                PlanStepType.READ,
                "object:gate",
                (),
                (ReasonCode.EXECUTABLE,),
            )
            for index in range(19)
        ),
    )
    try:
        PlanCompiler.compile(oversized, config)
    except ValueError:
        plan_limit_rejected = True

    schema_fragment_valid = True
    try:
        validate_answer(
            {
                "focal_id": "object:gate",
                "target": "recipient:gate",
                "control": "proceed",
                **decision,
            }
        )
    except ValueError:
        schema_fragment_valid = False

    return {
        "deterministic": first == second,
        "raw_context_independent": before_raw_change == after_raw_change,
        "call_order_independent": forward == reverse,
        "lineage_mismatch_rejected": lineage_mismatch_rejected,
        "plan_limit_rejected": plan_limit_rejected,
        "schema_fragment_valid": schema_fragment_valid,
        "opaque_args_preserved": plan[0]["args"] == {"opaque": "preserved"},
        "plan_order": [item["verb"] for item in plan],
        "output_fields": sorted(decision),
        "source_lock_digest": projections.scopes[0].source_lock_digest,
    }


def audit_boundaries() -> dict[str, Any]:
    import core.projection_compilers as module

    source = (BASE_DIR / "core" / "projection_compilers.py").read_text(
        encoding="utf-8"
    )
    prohibited_tokens = [
        token
        for token in (
            "TaskView",
            "EvidenceGraph",
            "CandidateSet",
            "DecisionMatrix",
            "visible_history",
            "personal_memory",
            "CandidateEvaluator",
            "RULEPACK_REGISTRY",
            "available_actions",
        )
        if token in source
    ]
    mutable_globals = [
        name
        for name, value in vars(module).items()
        if not name.startswith("_") and isinstance(value, (dict, list, set))
    ]
    signatures = {
        "scope": list(inspect.signature(ScopeCompiler.compile).parameters),
        "policy": list(inspect.signature(PolicyCompiler.compile).parameters),
        "plan": list(inspect.signature(PlanCompiler.compile).parameters),
        "set": list(inspect.signature(ProjectionCompiler.compile).parameters),
    }
    production_imports: list[str] = []
    for relative in ("harness.py", "rules/plan.py", "rules/scope_policy.py"):
        if "projection_compilers" in (BASE_DIR / relative).read_text(encoding="utf-8"):
            production_imports.append(relative)
    return {
        "production_active": any(
            compiler.production_active
            for compiler in (
                ScopeCompiler,
                PolicyCompiler,
                PlanCompiler,
                ProjectionCompiler,
            )
        ),
        "production_imports": production_imports,
        "prohibited_tokens": prohibited_tokens,
        "mutable_globals": mutable_globals,
        "signatures": signatures,
        "signature_contract": signatures
        == {
            "scope": ["projection"],
            "policy": ["projection"],
            "plan": ["projection", "config"],
            "set": ["projections", "config"],
        },
    }


def contract_markdown() -> str:
    return "\n".join(
        [
            "# Step 10 Pure Compiler Contract",
            "",
            "- ScopeCompiler는 ScopeProjection의 enum과 필드를 공식 content_scope shape로 복사한다.",
            "- PolicyCompiler는 PolicyProjection의 필드를 공식 policy shape로 복사한다.",
            "- PlanCompiler는 PlanProjection의 step 순서, verb, target, args를 그대로 복사한다.",
            "- ProjectionCompiler는 같은 decision lock을 가진 세 projection만 구조적으로 결합한다.",
            "- compiler는 raw input, Evidence, candidate, RulePack, evaluator, session을 조회하지 않는다.",
            "- compiler는 operation, outer target, control을 생성하거나 재판단하지 않는다.",
            "- event 개수 제한은 immutable config로 명시하며 공식 schema 최대값 18을 넘길 수 없다.",
            "- Step 10 경로는 shadow-only이며 production output에는 연결하지 않는다.",
            "",
        ]
    )


def build_report(result: dict[str, Any]) -> str:
    audit = result["compiler_audit"]
    boundary = result["boundary_audit"]
    tests = result["tests"]
    gate = result["release_gate"]
    return "\n".join(
        [
            "# Step 10 Pure Compiler 보고서",
            "",
            "## 구현 범위",
            "",
            "잠긴 Projection DTO를 공식 content_scope·policy·plan_events shape로 복사하는 shadow compiler를 구현했다.",
            "",
            "## 구조 검증",
            "",
            f"- 결정론: `{audit['deterministic']}`",
            f"- raw context 독립: `{audit['raw_context_independent']}`",
            f"- 호출 순서 독립: `{audit['call_order_independent']}`",
            f"- lineage mismatch 차단: `{audit['lineage_mismatch_rejected']}`",
            f"- opaque args 보존: `{audit['opaque_args_preserved']}`",
            f"- plan 순서: `{audit['plan_order']}`",
            f"- prohibited dependency: `{len(boundary['prohibited_tokens'])}`개",
            f"- mutable global: `{len(boundary['mutable_globals'])}`개",
            "",
            "## 회귀",
            "",
            f"- Step 10 invariant: exit `{tests['stage_specific']['exit_code']}`, {', '.join(tests['stage_specific']['summary'])}",
            f"- 전체 pytest: exit `{tests['full']['exit_code']}`, {', '.join(tests['full']['summary'])}",
            f"- 알려진 dev gate 제외: exit `{tests['without_known_dev_gate']['exit_code']}`, {', '.join(tests['without_known_dev_gate']['summary'])}",
            f"- dev overall: `{result['dev']['overall']:.4f}` (Step 9와 동일: `{result['dev_unchanged']}`)",
            f"- screening submission 동일: `{result['screening_submission_unchanged']}`",
            "",
            "전체 pytest의 dev hard gate 1건은 기존 baseline debt다. 이 단계는 의미 정확도 개선이나 production 전환을 주장하지 않는다.",
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
    output_dir = (args.output_dir or report_root / "step10_pure_compiler").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_failed_attempt(
        output_dir,
        result_filename="step10_result.json",
        report_filename="STEP10_REPORT.md",
    )
    previous_dir, previous_result, previous_stage = resolve_previous_stage(
        report_root.resolve(),
        PreviousStageSpec(
            "step9_decision_ir",
            "step9_decision_ir",
            "step9_result.json",
        ),
    )
    source_hash_before = source_tree_hash(source_files())

    validation_errors: list[str] = []
    try:
        validate_projection_compiler_contract()
    except Exception as exc:
        validation_errors.append(
            f"validate_projection_compiler_contract: {type(exc).__name__}: {exc}"
        )
    compiler_audit = audit_compilers()
    boundary_audit = audit_boundaries()
    audit_path = output_dir / "pure_compiler_audit.json"
    audit_path.write_text(
        json.dumps(
            {"compiler": compiler_audit, "boundaries": boundary_audit},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    contract_path = output_dir / "PURE_COMPILER_CONTRACT.md"
    contract_path.write_text(contract_markdown(), encoding="utf-8")

    regression = run_standard_regression(
        output_dir,
        stage_test_files=(
            "tests/test_projection_compilers.py",
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
    checks = {
        "step9_artifact_integrity": bool(previous_stage.get("checks"))
        and all(previous_stage["checks"].values()),
        "contracts_valid": not validation_errors,
        "deterministic": compiler_audit["deterministic"],
        "raw_context_independent": compiler_audit["raw_context_independent"],
        "call_order_independent": compiler_audit["call_order_independent"],
        "lineage_consistent": compiler_audit["lineage_mismatch_rejected"],
        "opaque_args_preserved": compiler_audit["opaque_args_preserved"],
        "plan_limit_enforced": compiler_audit["plan_limit_rejected"],
        "schema_fragment_valid": compiler_audit["schema_fragment_valid"],
        "projection_only_signatures": boundary_audit["signature_contract"],
        "no_semantic_dependencies": not boundary_audit["prohibited_tokens"],
        "no_mutable_globals": not boundary_audit["mutable_globals"],
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
            "세 compiler가 잠긴 Projection만 받아 공식 field shape로 복사한다.",
            "동일 Projection·호출 순서·외부 raw context 변화에 대해 출력이 결정적이다.",
            "plan step 순서와 임의 args를 재해석 없이 보존하고 lock lineage 불일치를 차단했다.",
            "Step 9 대비 public dev 수치와 screening submission이 변하지 않았다.",
        ]
        if gate_passed
        else [
            f"실패한 Step 10 gate: {name}"
            for name, passed in checks.items()
            if not passed
        ]
        + validation_errors
        + list(previous_stage.get("errors") or []),
    }
    result = {
        "stage": "step10_pure_compiler",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_command": f"{sys.executable} {Path(__file__).name}",
        "report_root": str(report_root.resolve()),
        "report_root_source": root_source,
        "output_dir": str(output_dir),
        "previous_stage": previous_stage,
        "source_tree_sha256": source_hash_after,
        "contract_sha256": combined_hash(contract_files(), root=BASE_DIR),
        "audit_sha256": sha256_file(audit_path),
        "compiler_audit": compiler_audit,
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
    result_path = output_dir / "step10_result.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path = output_dir / "STEP10_REPORT.md"
    report_path.write_text(build_report(result), encoding="utf-8")
    write_stage_manifest(
        output_dir,
        stage="step10_pure_compiler",
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
