from __future__ import annotations

import argparse
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
import sys
from typing import Any

from build_manifest import sha256_file, source_files, source_tree_hash
from core.contracts import (
    PARTIAL_COMMIT_ASSUMPTION_ID,
    validate_assumption_registry,
)
from core.decision_ir import (
    AggregateOutputStatus,
    DecisionProjectionSet,
    PlanProjection,
    PlanProjectionStep,
    PolicyProjection,
    ScopeProjection,
)
from core.ontology import DisclosureMode, ExecutionDisposition, PlanStepType, ReasonCode
from core.projection_compilers import ProjectionCompiler, ProjectionCompilerConfig
from core.session_overlay import (
    AtomicCommitCoordinator,
    CommitEligibility,
    CommitEligibilityEvaluator,
    CommitStatus,
    CommittedSessionState,
    DecisionDispositionSet,
    InMemoryAtomicSessionStore,
    OverlayReadSource,
    RollbackPlanValidator,
    RollbackStatus,
    SessionNamespace,
    SessionValueKey,
    SpeculativeSessionOverlay,
    ValidationResult,
    ValidationStatus,
    validate_session_overlay_contract,
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


CONFIG = ProjectionCompilerConfig(max_plan_events=18)
SESSION_KEY = SessionValueKey(SessionNamespace.SESSION, "last_target")
MEMORY_KEY = SessionValueKey(SessionNamespace.MEMORY, "preference")


def contract_files() -> tuple[Path, ...]:
    return (
        BASE_DIR / "core" / "contracts.py",
        BASE_DIR / "core" / "decision_ir.py",
        BASE_DIR / "core" / "projection_compilers.py",
        BASE_DIR / "core" / "session_overlay.py",
    )


def _projections(terminals: dict[str, bool]) -> DecisionProjectionSet:
    decision_ids = tuple(sorted(terminals))
    return DecisionProjectionSet(
        "bundle:session-gate",
        (
            AggregateOutputStatus.SINGLE
            if len(decision_ids) == 1
            else AggregateOutputStatus.MULTIPLE_UNRESOLVED
        ),
        tuple(
            ScopeProjection(
                decision_id,
                DisclosureMode.STATUS_ONLY,
                ("status",),
                (),
                False,
                (),
                f"lock:{decision_id}",
            )
            for decision_id in decision_ids
        ),
        tuple(
            PolicyProjection(
                decision_id,
                (),
                (),
                False,
                (ReasonCode.EXECUTABLE,),
                (),
                f"lock:{decision_id}",
            )
            for decision_id in decision_ids
        ),
        tuple(
            PlanProjection(
                decision_id,
                (
                    PlanProjectionStep(
                        f"projection:{decision_id}",
                        f"requirement:{decision_id}",
                        (
                            PlanStepType.UPDATE
                            if terminals[decision_id]
                            else PlanStepType.GUARD
                        ),
                        "state:session",
                        (),
                        (ReasonCode.EXECUTABLE,),
                        semantic_terminal=terminals[decision_id],
                    ),
                ),
                f"lock:{decision_id}",
            )
            for decision_id in decision_ids
        ),
        "bundle-lock:session-gate",
    )


def _plan_validation(
    overlay: SpeculativeSessionOverlay,
    terminals: dict[str, bool],
):
    projections = _projections(terminals)
    return RollbackPlanValidator.validate(
        overlay.snapshot(),
        projections,
        ProjectionCompiler.compile(projections, CONFIG),
    )


def _validation(*decision_ids: str, passed: bool = True) -> ValidationResult:
    return ValidationResult(
        ValidationStatus.PASSED if passed else ValidationStatus.FAILED,
        tuple(sorted(decision_ids)),
        "ConsistencyValidator",
        "sha256:step11-gate-validation",
        () if passed else ("consistency_failure",),
    )


def _dispositions(
    values: dict[str, ExecutionDisposition],
) -> DecisionDispositionSet:
    return DecisionDispositionSet(tuple(sorted(values.items())))


def audit_overlay_lifecycle() -> dict[str, Any]:
    initial = CommittedSessionState.from_values({SESSION_KEY: "committed"})
    store = InMemoryAtomicSessionStore(initial)
    overlay = SpeculativeSessionOverlay(initial)
    overlay.write(
        write_id="write:a",
        key=SESSION_KEY,
        value={"target": "provisional"},
        producer_decision_id="decision:a",
        provenance_ids=("evidence:a",),
    )
    dependencies_before_read = len(overlay.snapshot().dependency_edges)
    read = overlay.read(
        read_id="read:b",
        key=SESSION_KEY,
        consumer_decision_id="decision:b",
    )
    overlay.write(
        write_id="write:b",
        key=MEMORY_KEY,
        value="dependent",
        producer_decision_id="decision:b",
        provenance_ids=("evidence:b",),
    )
    independent_key = SessionValueKey(SessionNamespace.SESSION, "independent")
    overlay.write(
        write_id="write:c",
        key=independent_key,
        value="independent",
        producer_decision_id="decision:c",
        provenance_ids=("evidence:c",),
    )
    affected = overlay.rollback_decision(
        "decision:a",
        reason="producer_validation_failed",
    )
    snapshot = overlay.snapshot()
    write_status = {
        write.producer_decision_id: write.rollback_status.value
        for write in snapshot.provisional_writes
    }
    plan_validation = _plan_validation(
        overlay,
        {"decision:a": False, "decision:b": False, "decision:c": True},
    )
    assessment = CommitEligibilityEvaluator.evaluate(
        overlay,
        _dispositions(
            {
                "decision:a": ExecutionDisposition.HOLD,
                "decision:b": ExecutionDisposition.HOLD,
                "decision:c": ExecutionDisposition.PROCEED,
            }
        ),
        _validation("decision:a", "decision:b", "decision:c"),
        plan_validation,
    )
    result = AtomicCommitCoordinator.commit(overlay, store, assessment)
    return {
        "dependencies_before_read": dependencies_before_read,
        "dependencies_after_read": len(snapshot.dependency_edges),
        "provisional_read_source": read.source.value,
        "provisional_read_value": read.thawed_value(),
        "affected_decisions": list(affected),
        "write_rollback_status": write_status,
        "independent_write_visible": next(
            write.visible
            for write in snapshot.provisional_writes
            if write.producer_decision_id == "decision:c"
        ),
        "plan_validation_valid": plan_validation.valid,
        "commit_eligibility": assessment.eligibility.value,
        "partial_commit_assumption": PARTIAL_COMMIT_ASSUMPTION_ID
        in assessment.assumption_refs,
        "commit_status": result.status.value,
        "persistent_unchanged": store.snapshot() == initial,
        "read_set": [key.canonical_text for key in snapshot.read_set],
        "write_set": [key.canonical_text for key in snapshot.write_set],
    }


def audit_validation_and_atomic_commit() -> dict[str, Any]:
    initial = CommittedSessionState.from_values({SESSION_KEY: "old"}, version=7)

    failed_store = InMemoryAtomicSessionStore(initial)
    failed_overlay = SpeculativeSessionOverlay(initial)
    failed_overlay.write(
        write_id="write:validation",
        key=SESSION_KEY,
        value="invalid",
        producer_decision_id="decision:validation",
        provenance_ids=("evidence:validation",),
    )
    failed_assessment = CommitEligibilityEvaluator.evaluate(
        failed_overlay,
        _dispositions({"decision:validation": ExecutionDisposition.PROCEED}),
        _validation("decision:validation", passed=False),
        _plan_validation(failed_overlay, {"decision:validation": True}),
    )
    failed_result = AtomicCommitCoordinator.commit(
        failed_overlay,
        failed_store,
        failed_assessment,
    )

    success_store = InMemoryAtomicSessionStore(initial)
    success_overlay = SpeculativeSessionOverlay(initial)
    success_overlay.write(
        write_id="write:success",
        key=SESSION_KEY,
        value="new",
        producer_decision_id="decision:success",
        provenance_ids=("evidence:success",),
    )
    success_assessment = CommitEligibilityEvaluator.evaluate(
        success_overlay,
        _dispositions({"decision:success": ExecutionDisposition.PROCEED}),
        _validation("decision:success"),
        _plan_validation(success_overlay, {"decision:success": True}),
    )
    success_result = AtomicCommitCoordinator.commit(
        success_overlay,
        success_store,
        success_assessment,
    )

    atomic_store = InMemoryAtomicSessionStore(
        initial,
        fail_on_keys=frozenset({MEMORY_KEY}),
    )
    atomic_overlay = SpeculativeSessionOverlay(initial)
    for write_id, decision_id, key in (
        ("write:x", "decision:x", SESSION_KEY),
        ("write:y", "decision:y", MEMORY_KEY),
    ):
        atomic_overlay.write(
            write_id=write_id,
            key=key,
            value=write_id,
            producer_decision_id=decision_id,
            provenance_ids=(f"evidence:{decision_id}",),
        )
    atomic_assessment = CommitEligibilityEvaluator.evaluate(
        atomic_overlay,
        _dispositions(
            {
                "decision:x": ExecutionDisposition.PROCEED,
                "decision:y": ExecutionDisposition.PROCEED,
            }
        ),
        _validation("decision:x", "decision:y"),
        _plan_validation(
            atomic_overlay,
            {"decision:x": True, "decision:y": True},
        ),
    )
    atomic_result = AtomicCommitCoordinator.commit(
        atomic_overlay,
        atomic_store,
        atomic_assessment,
    )
    return {
        "validation_failure_eligibility": failed_assessment.eligibility.value,
        "validation_failure_status": failed_result.status.value,
        "validation_failure_unchanged": failed_store.snapshot() == initial,
        "success_status": success_result.status.value,
        "success_version": success_store.snapshot().version,
        "success_trace_decision": success_result.decision_traces[0].decision_id,
        "atomic_failure_status": atomic_result.status.value,
        "atomic_failure_persistent_changed": atomic_result.persistent_state_changed,
        "atomic_failure_unchanged": atomic_store.snapshot() == initial,
    }


def audit_rollback_release() -> dict[str, Any]:
    overlay = SpeculativeSessionOverlay(CommittedSessionState(0))
    overlay.write(
        write_id="write:producer",
        key=SESSION_KEY,
        value="producer",
        producer_decision_id="decision:producer",
        provenance_ids=("evidence:producer",),
    )
    overlay.read(
        read_id="read:consumer",
        key=SESSION_KEY,
        consumer_decision_id="decision:consumer",
    )
    overlay.rollback_decision("decision:producer", reason="producer_failed")
    invalid = _plan_validation(
        overlay,
        {"decision:consumer": True, "decision:producer": False},
    )
    corrected = _plan_validation(
        overlay,
        {"decision:consumer": False, "decision:producer": False},
    )

    stale_overlay = SpeculativeSessionOverlay(CommittedSessionState(0))
    stale_overlay.write(
        write_id="write:stale",
        key=SESSION_KEY,
        value="stale",
        producer_decision_id="decision:stale",
        provenance_ids=("evidence:stale",),
    )
    stale_validation = _plan_validation(stale_overlay, {"decision:stale": True})
    stale_overlay.read(
        read_id="read:late",
        key=SESSION_KEY,
        consumer_decision_id="decision:stale",
    )
    stale_assessment = CommitEligibilityEvaluator.evaluate(
        stale_overlay,
        _dispositions({"decision:stale": ExecutionDisposition.PROCEED}),
        _validation("decision:stale"),
        stale_validation,
    )
    return {
        "rolled_back_decisions": list(invalid.rolled_back_decision_ids),
        "terminal_decisions": list(invalid.terminal_decision_ids),
        "terminal_release_rejected": not invalid.valid,
        "corrected_non_terminal_valid": corrected.valid,
        "stale_validation_eligibility": stale_assessment.eligibility.value,
        "stale_validation_reason": list(stale_assessment.reason_codes),
    }


def audit_boundaries() -> dict[str, Any]:
    source = (BASE_DIR / "core" / "session_overlay.py").read_text(
        encoding="utf-8"
    )
    production_imports: list[str] = []
    for relative in ("harness.py", "run_submission.py", "core/session_state.py"):
        if "session_overlay" in (BASE_DIR / relative).read_text(encoding="utf-8"):
            production_imports.append(relative)
    overlay_methods = {
        name
        for name, value in inspect.getmembers(
            SpeculativeSessionOverlay,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    prohibited_tokens = [
        token
        for token in (
            "TaskView",
            "EvidenceGraph",
            "visible_history",
            "personal_memory",
            "raw prompt",
            "re.compile",
        )
        if token in source
    ]
    harness_source = (BASE_DIR / "harness.py").read_text(encoding="utf-8")
    validation_before_commit = (
        "ConsistencyValidator.validate_strict" in harness_source
        and "AtomicSessionCommitter.commit" in harness_source
        and harness_source.index("ConsistencyValidator.validate_strict")
        < harness_source.index("AtomicSessionCommitter.commit")
    )
    return {
        "production_active": any(
            component.production_active
            for component in (
                SpeculativeSessionOverlay,
                InMemoryAtomicSessionStore,
                AtomicCommitCoordinator,
            )
        ),
        "production_imports": production_imports,
        "prohibited_tokens": prohibited_tokens,
        "public_overlay_methods": sorted(overlay_methods),
        "manual_dependency_method_present": any(
            "dependency" in name for name in overlay_methods
        ),
        "dependency_constructor_count": source.count("SessionDependencyEdge("),
        "legacy_commits_before_validation": not validation_before_commit,
        "production_validation_before_commit": validation_before_commit,
    }


def contract_markdown() -> str:
    return "\n".join(
        [
            "# Step 11 Session Lifecycle Contract",
            "",
            "- committed state와 speculative overlay를 분리하고 overlay는 frozen JSON 값과 explicit provenance만 저장한다.",
            "- dependency는 provisional read가 실제 producer write를 참조할 때만 생성한다.",
            "- producer rollback은 read dependency consumer에만 cascade하며 독립 write를 자동 rollback하지 않는다.",
            "- 독립 성공·실패가 섞이면 부분 commit 공식 근거가 없으므로 persistent commit을 보류하고 ASSUMPTION-PARTIAL-COMMIT-001을 남긴다.",
            "- validation artifact lineage와 rollback-plan validation이 통과한 전체 unit만 atomic store에 commit한다.",
            "- rollback된 decision에 semantic terminal이 남으면 plan을 후처리하지 않고 release를 거부한다.",
            "- commit failure는 성공 answer로 승격할 수 없으며 persistent snapshot은 그대로 유지된다.",
            "- speculative overlay는 shadow-only지만 production harness는 validator 이후 AtomicSessionCommitter를 호출한다.",
            "",
        ]
    )


def build_report(result: dict[str, Any]) -> str:
    lifecycle = result["lifecycle_audit"]
    atomic = result["atomic_commit_audit"]
    release = result["rollback_release_audit"]
    boundary = result["boundary_audit"]
    tests = result["tests"]
    gate = result["release_gate"]
    return "\n".join(
        [
            "# Step 11 Session Lifecycle 보고서",
            "",
            "## 구현 범위",
            "",
            "CommittedSessionState, speculative read/write overlay, dependency rollback, validation-before-commit, atomic shadow store를 구현했다.",
            "",
            "## 구조 검증",
            "",
            f"- actual read dependency: `{lifecycle['dependencies_before_read']} → {lifecycle['dependencies_after_read']}`",
            f"- provisional read: `{lifecycle['provisional_read_source']}`",
            f"- cascade/independent: `{lifecycle['write_rollback_status']}`",
            f"- partial commit: `{lifecycle['commit_eligibility']}`",
            f"- validation failure unchanged: `{atomic['validation_failure_unchanged']}`",
            f"- atomic failure unchanged: `{atomic['atomic_failure_unchanged']}`",
            f"- rollback terminal release 차단: `{release['terminal_release_rejected']}`",
            f"- stale validation: `{release['stale_validation_eligibility']}`",
            "",
            "## Production 경계",
            "",
            f"- shadow production import: `{len(boundary['production_imports'])}`개",
            f"- production validation-before-commit: `{boundary['production_validation_before_commit']}`",
            "",
            "production 경로는 answer 검증이 끝난 뒤 staged session과 memory를 원자적으로 반영한다. 복수 sub-decision speculative overlay는 공식 부분 commit 계약이 없어 shadow-only다.",
            "",
            "## 회귀",
            "",
            f"- Step 11 invariant: exit `{tests['stage_specific']['exit_code']}`, {', '.join(tests['stage_specific']['summary'])}",
            f"- 전체 pytest: exit `{tests['full']['exit_code']}`, {', '.join(tests['full']['summary'])}",
            f"- 알려진 dev gate 제외: exit `{tests['without_known_dev_gate']['exit_code']}`, {', '.join(tests['without_known_dev_gate']['summary'])}",
            f"- dev overall: `{result['dev']['overall']:.4f}` (Step 10과 동일: `{result['dev_unchanged']}`)",
            f"- screening submission 동일: `{result['screening_submission_unchanged']}`",
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
    output_dir = (args.output_dir or report_root / "step11_session_lifecycle").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_failed_attempt(
        output_dir,
        result_filename="step11_result.json",
        report_filename="STEP11_REPORT.md",
    )
    previous_dir, previous_result, previous_stage = resolve_previous_stage(
        report_root.resolve(),
        PreviousStageSpec(
            "step10_pure_compiler",
            "step10_pure_compiler",
            "step10_result.json",
        ),
    )
    source_hash_before = source_tree_hash(source_files())

    validation_errors: list[str] = []
    for validator in (
        validate_assumption_registry,
        validate_session_overlay_contract,
    ):
        try:
            validator()
        except Exception as exc:
            validation_errors.append(
                f"{validator.__name__}: {type(exc).__name__}: {exc}"
            )
    lifecycle_audit = audit_overlay_lifecycle()
    atomic_audit = audit_validation_and_atomic_commit()
    release_audit = audit_rollback_release()
    boundary_audit = audit_boundaries()
    audit_path = output_dir / "session_lifecycle_audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "lifecycle": lifecycle_audit,
                "atomic_commit": atomic_audit,
                "rollback_release": release_audit,
                "boundaries": boundary_audit,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    contract_path = output_dir / "SESSION_LIFECYCLE_CONTRACT.md"
    contract_path.write_text(contract_markdown(), encoding="utf-8")

    regression = run_standard_regression(
        output_dir,
        stage_test_files=(
            "tests/test_session_overlay.py",
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
        "step10_artifact_integrity": bool(previous_stage.get("checks"))
        and all(previous_stage["checks"].values()),
        "contracts_valid": not validation_errors,
        "dependency_only_from_actual_read": lifecycle_audit[
            "dependencies_before_read"
        ]
        == 0
        and lifecycle_audit["dependencies_after_read"] == 1
        and boundary_audit["dependency_constructor_count"] == 1
        and not boundary_audit["manual_dependency_method_present"],
        "provisional_read_visible": lifecycle_audit["provisional_read_source"]
        == OverlayReadSource.PROVISIONAL.value
        and lifecycle_audit["provisional_read_value"]
        == {"target": "provisional"},
        "dependency_rollback_scoped": lifecycle_audit["write_rollback_status"]
        == {
            "decision:a": RollbackStatus.DIRECT.value,
            "decision:b": RollbackStatus.CASCADED.value,
            "decision:c": RollbackStatus.NONE.value,
        }
        and lifecycle_audit["independent_write_visible"],
        "partial_commit_withheld": lifecycle_audit["commit_eligibility"]
        == CommitEligibility.PARTIAL_COMMIT_UNRESOLVED.value
        and lifecycle_audit["partial_commit_assumption"]
        and lifecycle_audit["commit_status"] == CommitStatus.REJECTED.value
        and lifecycle_audit["persistent_unchanged"],
        "validation_before_commit": atomic_audit[
            "validation_failure_eligibility"
        ]
        == CommitEligibility.VALIDATION_FAILED.value
        and atomic_audit["validation_failure_unchanged"],
        "atomic_commit_success_trace": atomic_audit["success_status"]
        == CommitStatus.COMMITTED.value
        and atomic_audit["success_version"] == 8
        and atomic_audit["success_trace_decision"] == "decision:success",
        "atomic_failure_rolls_back": atomic_audit["atomic_failure_status"]
        == CommitStatus.ATOMIC_FAILURE.value
        and not atomic_audit["atomic_failure_persistent_changed"]
        and atomic_audit["atomic_failure_unchanged"],
        "rollback_terminal_not_released": release_audit[
            "terminal_release_rejected"
        ]
        and release_audit["terminal_decisions"] == ["decision:consumer"]
        and release_audit["corrected_non_terminal_valid"],
        "stale_validation_rejected": release_audit[
            "stale_validation_eligibility"
        ]
        == CommitEligibility.RELEASE_INVALID.value
        and "stale_rollback_plan_validation"
        in release_audit["stale_validation_reason"],
        "shadow_only": not boundary_audit["production_active"]
        and not boundary_audit["production_imports"],
        "no_language_or_raw_dependencies": not boundary_audit["prohibited_tokens"],
        "production_validation_wired": boundary_audit[
            "production_validation_before_commit"
        ],
        "source_stable_during_gate": source_hash_before == source_hash_after,
        **standard_regression_checks(regression),
    }
    gate_passed = all(checks.values())
    release_gate = {
        "status": "PASS_WITH_BASELINE_DEBT" if gate_passed else "FAIL",
        "next_stage_allowed": gate_passed,
        "checks": checks,
        "reasons": [
            "provisional read에만 dependency를 만들고 dependency rollback과 독립 write를 분리했다.",
            "검증 실패·부분 성공·atomic write 실패에서 persistent state가 변하지 않았다.",
            "rollback terminal은 후처리하지 않고 release를 거부하며 stale validation도 차단했다.",
            "Step 10 대비 public dev 수치와 screening submission이 변하지 않았다.",
            "production validation-before-commit과 atomic in-process commit을 연결했다.",
        ]
        if gate_passed
        else [
            f"실패한 Step 11 gate: {name}"
            for name, passed in checks.items()
            if not passed
        ]
        + validation_errors
        + list(previous_stage.get("errors") or []),
    }
    result = {
        "stage": "step11_session_lifecycle",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_command": f"{sys.executable} {Path(__file__).name}",
        "report_root": str(report_root.resolve()),
        "report_root_source": root_source,
        "output_dir": str(output_dir),
        "previous_stage": previous_stage,
        "source_tree_sha256": source_hash_after,
        "contract_sha256": combined_hash(contract_files(), root=BASE_DIR),
        "audit_sha256": sha256_file(audit_path),
        "lifecycle_audit": lifecycle_audit,
        "atomic_commit_audit": atomic_audit,
        "rollback_release_audit": release_audit,
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
    result_path = output_dir / "step11_result.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path = output_dir / "STEP11_REPORT.md"
    report_path.write_text(build_report(result), encoding="utf-8")
    write_stage_manifest(
        output_dir,
        stage="step11_session_lifecycle",
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
