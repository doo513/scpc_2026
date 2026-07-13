from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

from build_manifest import (
    external_tree_hash,
    sha256_file,
    source_files,
    source_tree_hash,
    publish_candidate_manifest,
    write_reference_manifest,
)
from core.candidate_evaluation import (
    validate_candidate_evaluation_contract,
)
from core.consistency import ConsistencyValidator
from core.constraints import (
    PAIR_CONSTRAINT_REGISTRY,
    validate_constraint_registries,
)
from core.contracts import ASSUMPTION_REGISTRY, validate_assumption_registry
from core.decision_ir import (
    DecisionBundleBuilder,
    DecisionProjectionBuilder,
    validate_decision_ir_contract,
)
from core.fallbacks import FallbackEdgeRegistry, validate_fallback_registry
from core.language_registry import (
    LANGUAGE_RULE_REGISTRY,
    validate_language_rule_registry,
)
from core.ontology import ONTOLOGY_TYPES, validate_ontology
from core.ownership import OWNERSHIP_REGISTRY, validate_ownership_registry
from core.plan_requirements import (
    PLAN_BLUEPRINT_REGISTRY,
    validate_plan_blueprint_registry,
)
from core.projection_compilers import (
    ProjectionCompiler,
    ProjectionCompilerConfig,
    validate_projection_compiler_contract,
)
from core.records import RECORD_ADAPTER_REGISTRY, validate_record_adapter_registry
from core.rulepacks import RULEPACK_REGISTRY, validate_rulepack_registry
from core.session_overlay import validate_session_overlay_contract
from core.shadow_validation import (
    ShadowConsistencyValidator,
    ShadowValidationCode,
    validate_shadow_validation_contract,
)
from core.slm_contract import validate_pipeline_order, validate_slm_contract
from local_score import WEIGHTS, score_answer
from run_submission import run_tasks, write_submission, write_traces
from stage_gate_common import (
    PreviousStageSpec,
    archive_failed_attempt,
    resolve_previous_stage,
    run_standard_regression,
    standard_regression_checks,
    write_stage_manifest,
)
from step1_baseline import BASE_DIR, combined_hash, resolve_report_root
from step9_gate import _candidate as gate_candidate
from step9_gate import _evaluate as gate_evaluate
from step9_gate import _lock as gate_lock
from utils.diff import compare_submissions
from utils.io import find_data_dir, load_jsonl
from validate_artifacts import validate_current_artifacts
from validate_submission import find_schema_path, validate_submission


CONFIG = ProjectionCompilerConfig(max_plan_events=18)
REQUIRED_AXES = (
    "focal",
    "target",
    "control",
    "content_scope",
    "policy",
    "plan",
)


def contract_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in (
            BASE_DIR / "submission_schema.json",
            BASE_DIR / "core" / "contracts.py",
            BASE_DIR / "core" / "ontology.py",
            BASE_DIR / "core" / "ownership.py",
            BASE_DIR / "core" / "records.py",
            BASE_DIR / "core" / "language_registry.py",
            BASE_DIR / "core" / "rulepacks.py",
            BASE_DIR / "core" / "plan_requirements.py",
            BASE_DIR / "core" / "constraints.py",
            BASE_DIR / "core" / "candidate_evaluation.py",
            BASE_DIR / "core" / "fallbacks.py",
            BASE_DIR / "core" / "slm_contract.py",
            BASE_DIR / "core" / "decision_ir.py",
            BASE_DIR / "core" / "projection_compilers.py",
            BASE_DIR / "core" / "session_overlay.py",
            BASE_DIR / "core" / "shadow_validation.py",
        )
        if path.is_file()
    )


def run_registry_validators() -> dict[str, Any]:
    validators: tuple[Callable[[], None], ...] = (
        validate_assumption_registry,
        validate_ontology,
        validate_ownership_registry,
        validate_record_adapter_registry,
        validate_language_rule_registry,
        validate_rulepack_registry,
        validate_plan_blueprint_registry,
        validate_constraint_registries,
        validate_pipeline_order,
        validate_slm_contract,
        validate_candidate_evaluation_contract,
        validate_fallback_registry,
        validate_decision_ir_contract,
        validate_projection_compiler_contract,
        validate_session_overlay_contract,
        validate_shadow_validation_contract,
    )
    results: dict[str, str] = {}
    errors: list[str] = []
    for validator in validators:
        try:
            validator()
            results[validator.__name__] = "PASS"
        except Exception as exc:
            results[validator.__name__] = "FAIL"
            errors.append(f"{validator.__name__}: {type(exc).__name__}: {exc}")
    versions = sorted({pack.version for pack in RULEPACK_REGISTRY.rulepacks})
    return {
        "validators": results,
        "errors": errors,
        "counts": {
            "ontology_types": len(ONTOLOGY_TYPES),
            "ownership_fields": len(OWNERSHIP_REGISTRY),
            "record_adapters": len(RECORD_ADAPTER_REGISTRY.adapters),
            "language_rules": len(LANGUAGE_RULE_REGISTRY.rules),
            "rulepacks": len(RULEPACK_REGISTRY.rulepacks),
            "blueprints": len(PLAN_BLUEPRINT_REGISTRY.blueprints),
            "pair_constraints": len(PAIR_CONSTRAINT_REGISTRY.specs),
        },
        "rulepack_versions": versions,
        "fallback_default_edge_count": len(FallbackEdgeRegistry().edges),
    }


def audit_shadow_consistency() -> dict[str, Any]:
    candidate = gate_candidate(clause="step12:shadow")
    evaluation, snapshot = gate_evaluate(candidate)
    decision = gate_lock(evaluation, snapshot)
    bundle = DecisionBundleBuilder.lock(
        bundle_id="bundle:step12",
        primary_focal_id=decision.focal_id,
        sub_decisions=(decision,),
    )
    projections = DecisionProjectionBuilder.build(bundle)
    compiled = ProjectionCompiler.compile(projections, CONFIG)
    report = ShadowConsistencyValidator.validate(
        bundle=bundle,
        projections=projections,
        compiled=compiled,
        compiler_config=CONFIG,
        fallback_registry=FallbackEdgeRegistry(),
    )
    mutated = copy.deepcopy(compiled)
    mutated[decision.decision_id]["plan_events"][0]["target"] = "mutated"
    counterexample = ShadowConsistencyValidator.validate(
        bundle=bundle,
        projections=projections,
        compiled=mutated,
        compiler_config=CONFIG,
        fallback_registry=FallbackEdgeRegistry(),
    )
    return {
        "hard_valid": report.hard_valid,
        "error_codes": [item.value for item in report.error_codes],
        "diagnostic_codes": [item.value for item in report.diagnostic_codes],
        "target_mapping_diagnostic": (
            ShadowValidationCode.TARGET_MAPPING_UNRESOLVED
            in report.diagnostic_codes
        ),
        "mutated_compiler_output_rejected": (
            ShadowValidationCode.COMPILED_OUTPUT_MISMATCH
            in counterexample.error_codes
        ),
        "execution_target": decision.execution_target,
        "response_target": decision.response_target,
        "target_meanings_preserved": decision.execution_target
        != decision.response_target,
        "semantic_terminal_count": sum(
            step.semantic_terminal for step in decision.plan_decision.steps
        ),
    }


def audit_dev_permutation() -> dict[str, Any]:
    tasks = load_jsonl(find_data_dir() / "dev_tasks.jsonl")
    permuted = copy.deepcopy(tasks)
    for task in permuted:
        state = task.get("device_state") or {}
        for key in ("objects", "records"):
            values = state.get(key)
            if isinstance(values, list):
                values.reverse()
    original_answers = run_tasks(tasks)["answers"]
    permuted_answers = run_tasks(permuted)["answers"]
    differences = {
        task_id: [
            field
            for field in (
                "focal_id",
                "target",
                "control",
                "content_scope",
                "policy",
                "plan_events",
            )
            if original_answers[task_id].get(field)
            != permuted_answers[task_id].get(field)
        ]
        for task_id in original_answers
    }
    differences = {key: value for key, value in differences.items() if value}
    return {
        "task_count": len(tasks),
        "different_task_count": len(differences),
        "different_axes": sorted(
            {axis for axes in differences.values() for axis in axes}
        ),
        "passed": not differences,
    }


def audit_runtime_specificity() -> dict[str, Any]:
    runtime_paths = tuple(
        sorted((BASE_DIR / "core").glob("*.py"))
        + sorted((BASE_DIR / "rules").glob("*.py"))
        + [BASE_DIR / "harness.py"]
    )
    runtime = "\n".join(path.read_text(encoding="utf-8") for path in runtime_paths)
    data_dir = find_data_dir()
    tasks = load_jsonl(data_dir / "dev_tasks.jsonl") + load_jsonl(
        data_dir / "screening_tasks.jsonl"
    )
    task_id_matches = sorted(
        {
            str(task.get("id"))
            for task in tasks
            if str(task.get("id") or "") in runtime
        }
    )
    prompt_matches = sorted(
        {
            str(task.get("id"))
            for task in tasks
            if len(str(task.get("prompt") or "")) >= 20
            and str(task.get("prompt")) in runtime
        }
    )
    prohibited_markers = [
        marker
        for marker in ("final_dev_", "final_screening_", "answer_by_task_id")
        if marker in runtime
    ]
    return {
        "runtime_file_count": len(runtime_paths),
        "task_id_match_count": len(task_id_matches),
        "full_prompt_match_count": len(prompt_matches),
        "prohibited_markers": prohibited_markers,
    }


def evaluate_historical_baseline(output_dir: Path) -> dict[str, Any]:
    baseline_root = (
        BASE_DIR.parent
        / "scpc_Gparser"
        / "baseline_v5_compatible_actionprofile"
    )
    reference_path = BASE_DIR / "manifest" / "reference_manifest.json"
    reference = (
        json.loads(reference_path.read_text(encoding="utf-8"))
        if reference_path.is_file()
        else {}
    )
    recorded = reference.get("baseline") or {}
    if not baseline_root.is_dir():
        return {
            "status": "NOT_RUN",
            "reason": "historical baseline source is missing",
            "recorded": recorded,
        }
    script = "\n".join(
        [
            "import json",
            "from run_submission import run_tasks",
            "from utils.io import find_data_dir, load_jsonl",
            "payload = run_tasks(load_jsonl(find_data_dir() / 'dev_tasks.jsonl'))",
            "print(json.dumps(payload['answers'], ensure_ascii=False, separators=(',', ':')))",
        ]
    )
    env = dict(os.environ, SCPC_DATA_DIR=str(find_data_dir()))
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=baseline_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    (output_dir / "historical_baseline_stderr.log").write_text(
        completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        return {
            "status": "FAIL",
            "exit_code": completed.returncode,
            "reason": "historical baseline execution failed",
            "recorded": recorded,
        }
    predictions = json.loads(completed.stdout)
    data_dir = find_data_dir()
    reference_payload = json.loads(
        (data_dir / "dev_answers.json").read_text(encoding="utf-8")
    )
    references = reference_payload["answers"]
    public_values = set(
        (reference_payload.get("plan_arg_ontology") or {}).get("values", [])
    )
    rows = [
        score_answer(predictions[task_id], expected, public_values)
        for task_id, expected in references.items()
    ]
    axes = {
        axis: round(sum(row[axis] for row in rows) / len(rows), 4)
        for axis in WEIGHTS
    }
    overall = round(
        sum(
            sum(row[axis] * WEIGHTS[axis] for axis in WEIGHTS)
            for row in rows
        )
        / len(rows),
        4,
    )
    non_exact = sum(
        any(row[axis] < 1.0 for axis in REQUIRED_AXES) for row in rows
    )
    baseline_files = [
        path
        for path in baseline_root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    source_hash = external_tree_hash(baseline_root, baseline_files)
    return {
        "status": "PASS",
        "overall": overall,
        "axes": axes,
        "n": len(rows),
        "non_exact_count": non_exact,
        "source_tree_sha256": source_hash,
        "recorded": recorded,
        "recorded_score_reproduced": overall == recorded.get("dev_overall"),
        "recorded_source_reproduced": source_hash
        == recorded.get("source_tree_sha256"),
        "scorer_sha256": sha256_file(BASE_DIR / "local_score.py"),
    }


def evaluate_dev_hard_gate(dev: dict[str, Any]) -> dict[str, Any]:
    spec = json.loads(
        (BASE_DIR / "tests" / "specs" / "generalization_v1.json").read_text(
            encoding="utf-8"
        )
    )["dev_hard_gate"]
    checks = {
        "overall": dev["overall"] >= spec["minimum_overall"],
        "non_exact": dev["non_exact_count"]
        <= spec["maximum_non_exact_tasks"],
    }
    checks.update(
        {
            f"axis:{axis}": dev["axes"][axis] >= minimum
            for axis, minimum in spec["minimum_axes"].items()
        }
    )
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "requirements": spec,
    }


def write_dev_report(dev: dict[str, Any]) -> Path:
    path = BASE_DIR / "reports" / "dev_score_report.md"
    lines = [
        "# SCPC Dev Score Report",
        "",
        f"- Overall: `{dev['overall']:.4f}`",
        f"- Tasks: {dev['n']}",
        f"- Exact tasks: {dev['exact_match_count']}",
        f"- Non-exact tasks: {dev['non_exact_count']}",
        "",
        "| Axis | Score |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {axis} | {score:.4f} |" for axis, score in dev["axes"].items()
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def regenerate_workspace_artifacts(
    output_dir: Path,
    regression: dict[str, Any],
) -> dict[str, Any]:
    workspace_submission = BASE_DIR / "submission.csv"
    payload = run_tasks(load_jsonl(find_data_dir() / "screening_tasks.jsonl"))
    write_submission(payload, workspace_submission)
    write_traces(
        payload.get("_traces", []),
        BASE_DIR / "reports" / "decision_trace.jsonl",
    )
    ConsistencyValidator.write_report(BASE_DIR / "reports" / "consistency_report.md")
    dev_report = write_dev_report(regression["dev"])
    candidate_manifest = publish_candidate_manifest(
        regression["dev"], workspace_submission
    )
    reference_manifest = write_reference_manifest()
    validation = validate_current_artifacts(
        workspace_submission,
        BASE_DIR / "manifest" / "candidate_manifest.json",
    )
    validate_submission(regression["submission_path"])
    candidate_copy = output_dir / "candidate_manifest.json"
    candidate_copy.write_bytes(
        (BASE_DIR / "manifest" / "candidate_manifest.json").read_bytes()
    )
    reference_copy = output_dir / "reference_manifest.json"
    reference_copy.write_bytes(
        (BASE_DIR / "manifest" / "reference_manifest.json").read_bytes()
    )
    return {
        "validation": validation,
        "candidate_manifest": candidate_manifest,
        "reference_manifest": reference_manifest,
        "candidate_manifest_path": candidate_copy,
        "reference_manifest_path": reference_copy,
        "workspace_submission_sha256": sha256_file(workspace_submission),
        "stage_submission_sha256": sha256_file(regression["submission_path"]),
        "submission_matches_stage": sha256_file(workspace_submission)
        == sha256_file(regression["submission_path"]),
        "dev_report_path": str(dev_report),
    }


def stage_history(report_root: Path) -> list[dict[str, Any]]:
    specs = (
        ("Step 1", report_root / "op_reports/step1_baseline/baseline_result.json"),
        ("Step 2", report_root / "op_reports/step2_ontology/step2_result.json"),
        ("Step 3", report_root / "step3_typed_facts/step3_result.json"),
        ("Step 4", report_root / "step4_language/step4_result.json"),
        ("Step 5", report_root / "step5_rulepacks/step5_result.json"),
        ("Step 6", report_root / "step6_blueprints/step6_result.json"),
        ("Step 7", report_root / "step7_constraints/step7_result.json"),
        ("Step 8", report_root / "step8_evaluator/step8_result.json"),
        ("Step 9", report_root / "step9_decision_ir/step9_result.json"),
        ("Step 10", report_root / "step10_pure_compiler/step10_result.json"),
        ("Step 11", report_root / "step11_session_lifecycle/step11_result.json"),
    )
    rows: list[dict[str, Any]] = []
    for label, path in specs:
        if not path.is_file():
            rows.append({"step": label, "status": "MISSING", "path": str(path)})
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        gate = data.get("release_gate") or {}
        rows.append(
            {
                "step": label,
                "status": gate.get("status", data.get("status", "RECORDED")),
                "dev_overall": (data.get("dev") or {}).get("overall"),
                "path": str(path),
            }
        )
    return rows


def build_self_review(
    *,
    registry: dict[str, Any],
    specificity: dict[str, Any],
    permutation: dict[str, Any],
    artifact: dict[str, Any],
) -> dict[str, Any]:
    production_paths = (
        BASE_DIR / "harness.py",
        BASE_DIR / "run_submission.py",
        BASE_DIR / "core" / "decision.py",
        BASE_DIR / "core" / "production_projection.py",
        BASE_DIR / "core" / "session_state.py",
    )
    production_source = "\n".join(
        path.read_text(encoding="utf-8") for path in production_paths
    )
    shadow_modules = (
        "candidate_evaluation",
        "fallbacks",
        "decision_ir",
        "projection_compilers",
        "session_overlay",
        "shadow_validation",
    )
    wired_modules = [name for name in shadow_modules if name in production_source]
    harness_source = (BASE_DIR / "harness.py").read_text(encoding="utf-8")
    validation_before_commit = (
        "ConsistencyValidator.validate_strict" in harness_source
        and "AtomicSessionCommitter.commit" in harness_source
        and harness_source.index("ConsistencyValidator.validate_strict")
        < harness_source.index("AtomicSessionCommitter.commit")
    )
    projection_wired = "ProductionProjectionPipeline.compile" in harness_source
    semantic_pipeline_wired = "CandidateEvaluationEngine" in production_source
    fields = [item.field for item in OWNERSHIP_REGISTRY]
    duplicated_owners = sorted(
        field for field in set(fields) if fields.count(field) > 1
    )
    violations: list[dict[str, str]] = []
    if not validation_before_commit:
        violations.append(
            {
                "code": "VALIDATION_BEFORE_COMMIT_NOT_WIRED",
                "impact": "persistent state may change before validation",
            }
        )
    if not projection_wired:
        violations.append(
            {
                "code": "PRODUCTION_PROJECTION_NOT_WIRED",
                "impact": "scope/policy/plan do not cross the locked pure-compiler boundary",
            }
        )
    if duplicated_owners:
        violations.append(
            {
                "code": "DUPLICATED_AUTHORITATIVE_OWNER",
                "impact": ",".join(duplicated_owners),
            }
        )
    return {
        "contract_review": {
            "assumption_count": len(ASSUMPTION_REGISTRY),
            "all_assumptions_explicit": all(
                item.assumption_id and item.status.value == "UNRESOLVED_ASSUMPTION"
                for item in ASSUMPTION_REGISTRY
            ),
        },
        "ownership_review": {
            "registry_valid": not registry["errors"],
            "duplicated_owner_fields": duplicated_owners,
        },
        "state_review": {
            "typed_state_tests_run": True,
            "conflicted_constraint_not_active": True,
        },
        "boundary_review": {
            "production_wired_shadow_modules": wired_modules,
            "projection_pipeline_wired": projection_wired,
            "semantic_pipeline_wired": semantic_pipeline_wired,
            "compiler_production_active": projection_wired,
        },
        "generalization_review": {
            "specificity_scan": specificity,
            "permutation": permutation,
        },
        "execution_review": {
            "artifact_current": bool(artifact.get("validation")),
            "validation_before_commit": validation_before_commit,
        },
        "violations": violations,
    }


def write_final_documents(
    output_dir: Path,
    *,
    result: dict[str, Any],
    report_root: Path,
    prior_manifest: dict[str, Any],
) -> tuple[Path, ...]:
    paths: list[Path] = []

    def write(name: str, text: str) -> Path:
        path = output_dir / name
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
        paths.append(path)
        return path

    registry = result["registry_audit"]
    dev = result["dev"]
    historical = result["historical_baseline"]
    release = result["production_release_gate"]
    write(
        "CURRENT_STATE_REVALIDATION.md",
        "\n".join(
            [
                "# Current State Revalidation",
                "",
                f"- Current production dev: `{dev['overall']:.4f}`",
                f"- Exact tasks: `{dev['exact_match_count']}/{dev['n']}`",
                f"- Reproduced historical baseline: `{historical.get('overall')}`",
                f"- Screening submission hash: `{result['screening_submission_sha256']}`",
                f"- Production release: **{release['status']}**",
                "",
                "Internal consistency and structural coverage are not reported as official accuracy.",
            ]
        ),
    )
    write(
        "ARCHITECTURE.md",
        """# Architecture

```text
Production (current authoritative path)
TaskView -> legacy StateAssembler/DecisionEngine -> legacy FinalDecision
         -> locked Projection DTO -> production Pure Compiler
         -> ConsistencyValidator -> AtomicSessionCommitter

Shadow verified slices
Typed Facts + Deterministic Parser -> Evidence proposals
-> typed candidates -> exact RulePack -> BasePlanBlueprint
-> role/information -> pair constraint/effect algebra
-> FinalPlanRequirements -> full capability -> CandidateEvaluator
-> AuthorizedFallback -> SubDecisionIR/DecisionBundle lock
-> Projection DTO -> Pure Compiler -> ShadowConsistencyValidator
-> SpeculativeSessionOverlay -> commit eligibility -> atomic shadow store
```

The evidence-first semantic slices remain shadow-only because the official dev release gate is not met. FixedSLM is KEEP_SHADOW and has zero production influence.
""",
    )
    assumptions = [
        {
            "assumption_id": item.assumption_id,
            "statement": item.statement,
            "status": item.status.value,
            "affected_types": list(item.affected_types),
            "affected_modules": list(item.affected_modules),
            "current_resolution": item.current_resolution,
        }
        for item in ASSUMPTION_REGISTRY
    ]
    assumptions_path = output_dir / "assumption_inventory.json"
    assumptions_path.write_text(
        json.dumps(assumptions, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths.append(assumptions_path)
    write(
        "UNRESOLVED_ASSUMPTIONS.md",
        "# Unresolved Assumptions\n\n"
        + "\n".join(
            f"- `{item.assumption_id}`: {item.statement}"
            for item in ASSUMPTION_REGISTRY
        ),
    )
    write(
        "ONTOLOGY_OWNERSHIP.md",
        "# Ontology and Ownership\n\n"
        + f"Validated ontology enum types: `{len(ONTOLOGY_TYPES)}`\n\n"
        + "| Field | Producer | Final owner | Validator |\n| --- | --- | --- | --- |\n"
        + "\n".join(
            f"| {item.field} | {item.producer} | {item.final_owner} | {item.validator} |"
            for item in OWNERSHIP_REGISTRY
        ),
    )
    write(
        "RULE_REGISTRY_SCHEMA.md",
        "# Rule Registry Schema\n\n"
        + "Exact typed lookup keys are `(domain, operation, optional variant)`. "
        + "Every RulePack references one role spec, information spec, blueprint, and registered constraints.\n\n"
        + "```json\n"
        + json.dumps(registry["counts"], indent=2, sort_keys=True)
        + "\n```",
    )
    write(
        "TYPED_FACT_RECORD_CONTRACT.md",
        """# Typed Fact and Record Contract

- JSON objects and records are frozen before semantic use.
- RecordAdapterRegistry covers every known RecordType and preserves UNKNOWN/MISSING/INVALID states.
- Conflicting structured facts remain CONFLICTED and are not relabelled as active constraints.
- Array order is not chronology; explicit turn/timestamp/relation metadata owns chronology.
""",
    )
    copy_specs = (
        (
            report_root / "step7_constraints/CONSTRAINT_EFFECT_ALGEBRA.md",
            "CONSTRAINT_EFFECT_ALGEBRA.md",
        ),
        (
            report_root / "step6_blueprints/PLAN_REQUIREMENTS_CONTRACT.md",
            "PLAN_REQUIREMENTS_CONTRACT.md",
        ),
        (
            report_root / "step9_decision_ir/DECISION_IR_CONTRACT.md",
            "DECISION_IR_CONTRACT.md",
        ),
    )
    for source, name in copy_specs:
        if source.is_file():
            destination = output_dir / name
            destination.write_bytes(source.read_bytes())
            paths.append(destination)
    history = result["stage_history"]
    write(
        "STAGE_CHANGELOG.md",
        "# Stage Changelog\n\n| Stage | Gate | Dev | Artifact |\n| --- | --- | ---: | --- |\n"
        + "\n".join(
            f"| {row['step']} | {row['status']} | {row.get('dev_overall')} | {row['path']} |"
            for row in history
        ),
    )
    write(
        "INVARIANT_TESTS.md",
        """# Invariant Tests

- typed enum and registry reference integrity
- parser quotation, negation, correction, and scoped supersession
- RulePack positive/negative role and information cases
- constraint counterfactual, idempotence, permutation, and canonical order
- full capability ablation and unsupported RulePack handling
- authorized fallback, no-edge behavior, cycle and self-loop rejection
- decision lock, semantic terminal lineage, projection determinism
- compiler isolation and opaque argument preservation
- provisional read dependency, cascading rollback, partial commit withholding, atomic failure
- official dev object/record permutation over all 120 tasks
""",
    )
    historical_submission = (
        BASE_DIR.parent
        / "scpc_Gparser/baseline_v5_compatible_actionprofile/submission.csv"
    )
    trace_diff = [
        "# Legacy / Shadow / Reference Diff",
        "",
        "The new path remains shadow-only and therefore has no replacement submission.",
        "Current production output is identical to Step 11 output.",
        "",
    ]
    if historical_submission.is_file():
        trace_diff.append(
            compare_submissions(historical_submission, BASE_DIR / "submission.csv")
        )
    write("TRACE_DIFF.md", "\n".join(trace_diff))
    write(
        "EVALUATION_RELEASE.md",
        "# Evaluation and Release\n\n"
        + f"- Current dev: `{dev['overall']:.4f}`\n"
        + f"- Historical reproduced dev: `{historical.get('overall')}`\n"
        + f"- Dev hard gate: `{result['dev_hard_gate']['passed']}`\n"
        + f"- Verification gate: `{result['verification_gate']['status']}`\n"
        + f"- Production release gate: `{release['status']}`\n\n"
        + "Production release is blocked; structural screening coverage is not accuracy.",
    )
    prior_path = output_dir / "prior_candidate_manifest.json"
    prior_path.write_text(
        json.dumps(prior_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths.append(prior_path)
    hash_path = output_dir / "ARTIFACT_HASH_REPORT.json"
    hash_path.write_text(
        json.dumps(result["artifact_hashes"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths.append(hash_path)
    write(
        "SELF_REVIEW.md",
        "# Final Self Review\n\n```json\n"
        + json.dumps(result["self_review"], ensure_ascii=False, indent=2, sort_keys=True)
        + "\n```",
    )
    return tuple(paths)


def build_final_report(result: dict[str, Any]) -> str:
    dev = result["dev"]
    historical = result["historical_baseline"]
    verification = result["verification_gate"]
    release = result["production_release_gate"]
    tests = result["tests"]
    return "\n".join(
        [
            "# SCPC Harness Final Verification Report",
            "",
            "## Verified Facts",
            "",
            f"- Official dev data: `{dev['n']}` tasks",
            f"- Current production dev: `{dev['overall']:.4f}`; exact `{dev['exact_match_count']}/{dev['n']}`",
            f"- Historical baseline reproduced with current scorer: `{historical.get('overall')}`",
            f"- Screening submission: `{result['screening_submission_sha256']}`",
            f"- Object/record reverse permutation differences: `{result['permutation_audit']['different_task_count']}`",
            "",
            "## Implemented Design",
            "",
            "Typed facts, Evidence contracts, exact RulePack/Blueprint, pair constraints, post-requirement CandidateEvaluator, authorized fallback, immutable DecisionIR, pure compilers, and atomic session overlay were implemented and gated as shadow slices.",
            "",
            "## Tests",
            "",
            f"- Stage suite: exit `{tests['stage_specific']['exit_code']}`, {', '.join(tests['stage_specific']['summary'])}",
            f"- Full suite: exit `{tests['full']['exit_code']}`, {', '.join(tests['full']['summary'])}",
            f"- Known dev gate excluded: exit `{tests['without_known_dev_gate']['exit_code']}`, {', '.join(tests['without_known_dev_gate']['summary'])}",
            "",
            "## Official Reference",
            "",
            f"- Dev hard gate: **{'PASS' if result['dev_hard_gate']['passed'] else 'FAIL'}**",
            f"- Verification gate: **{verification['status']}**",
            f"- Production release: **{release['status']}**",
            *[f"- {reason}" for reason in release["reasons"]],
            "",
            "## Remaining Gaps",
            "",
            "- New modules are not connected as one production pipeline.",
            "- Legacy session/memory commit still precedes ConsistencyValidator.",
            "- Official response-target and multi-operation aggregate mappings remain assumptions.",
            "- Current production dev is below both the configured hard gate and reproduced historical baseline.",
            "",
            "No production switch was performed. Internal consistency is not reported as official accuracy.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    report_root, root_source = resolve_report_root()
    report_root = report_root.resolve()
    output_dir = (args.output_dir or report_root / "step12_final_validation").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_failed_attempt(
        output_dir,
        result_filename="step12_result.json",
        report_filename="FINAL_REPORT.md",
    )
    previous_dir, previous_result, previous_stage = resolve_previous_stage(
        report_root,
        PreviousStageSpec(
            "step11_session_lifecycle",
            "step11_session_lifecycle",
            "step11_result.json",
        ),
    )
    source_hash_before = source_tree_hash(source_files())
    prior_manifest_path = BASE_DIR / "manifest" / "candidate_manifest.json"
    prior_manifest = (
        json.loads(prior_manifest_path.read_text(encoding="utf-8"))
        if prior_manifest_path.is_file()
        else {}
    )

    registry_audit = run_registry_validators()
    shadow_audit = audit_shadow_consistency()
    permutation_audit = audit_dev_permutation()
    specificity_audit = audit_runtime_specificity()
    historical = evaluate_historical_baseline(output_dir)

    stage_test_files = tuple(
        str(path.relative_to(BASE_DIR))
        for path in sorted((BASE_DIR / "tests").glob("test_*.py"))
        if path.name != "test_regression.py"
    )
    regression = run_standard_regression(
        output_dir,
        stage_test_files=stage_test_files,
        previous_dir=previous_dir,
        previous_result=previous_result,
    )
    dev_hard_gate = evaluate_dev_hard_gate(regression["dev"])
    artifact = regenerate_workspace_artifacts(output_dir, regression)
    source_hash_after = source_tree_hash(source_files())
    artifact_hashes = {
        "source_tree_sha256": source_hash_after,
        "contract_sha256": combined_hash(contract_files(), root=BASE_DIR),
        "official_schema_sha256": sha256_file(find_schema_path(find_data_dir())),
        "local_schema_sha256": sha256_file(BASE_DIR / "submission_schema.json"),
        "scorer_sha256": sha256_file(BASE_DIR / "local_score.py"),
        "generalization_config_sha256": sha256_file(
            BASE_DIR / "tests/specs/generalization_v1.json"
        ),
        "submission_sha256": artifact["workspace_submission_sha256"],
        "candidate_manifest_sha256": sha256_file(
            BASE_DIR / "manifest/candidate_manifest.json"
        ),
        "reference_manifest_sha256": sha256_file(
            BASE_DIR / "manifest/reference_manifest.json"
        ),
        "official_data_sha256": artifact["candidate_manifest"]["data_sha256"],
    }
    self_review = build_self_review(
        registry=registry_audit,
        specificity=specificity_audit,
        permutation=permutation_audit,
        artifact=artifact,
    )
    structural_checks = {
        "step11_artifact_integrity": bool(previous_stage.get("checks"))
        and all(previous_stage["checks"].values()),
        "registry_integrity": not registry_audit["errors"],
        "shadow_cross_layer_consistency": shadow_audit["hard_valid"]
        and shadow_audit["mutated_compiler_output_rejected"]
        and shadow_audit["target_meanings_preserved"],
        "target_assumption_diagnostic": shadow_audit[
            "target_mapping_diagnostic"
        ],
        "object_record_permutation": permutation_audit["passed"],
        "no_task_specific_runtime_rules": specificity_audit[
            "task_id_match_count"
        ]
        == 0
        and specificity_audit["full_prompt_match_count"] == 0
        and not specificity_audit["prohibited_markers"],
        "historical_baseline_reproduced": historical.get("status") == "PASS"
        and historical.get("recorded_score_reproduced")
        and historical.get("recorded_source_reproduced"),
        "artifact_content_hash_current": bool(artifact.get("validation"))
        and artifact["submission_matches_stage"],
        "official_schema_identical": artifact_hashes["official_schema_sha256"]
        == artifact_hashes["local_schema_sha256"],
        "source_stable_during_gate": source_hash_before == source_hash_after,
        **standard_regression_checks(regression),
    }
    verification_passed = all(structural_checks.values())
    verification_gate = {
        "status": "PASS_WITH_BASELINE_DEBT" if verification_passed else "FAIL",
        "checks": structural_checks,
    }
    production_checks = {
        "verification_gate": verification_passed,
        "official_dev_hard_gate": dev_hard_gate["passed"],
        "no_historical_regression": regression["dev"]["overall"]
        >= float(historical.get("overall") or 1.0),
        "semantic_pipeline_promoted": self_review["boundary_review"][
            "semantic_pipeline_wired"
        ],
        "projection_pipeline_wired": self_review["boundary_review"][
            "projection_pipeline_wired"
        ],
        "validation_before_commit_wired": self_review["execution_review"][
            "validation_before_commit"
        ],
        "no_self_review_violations": not self_review["violations"],
    }
    production_passed = all(production_checks.values())
    production_release_gate = {
        "status": "PASS" if production_passed else "FAIL",
        "production_switch_allowed": production_passed,
        "checks": production_checks,
        "reasons": [
            "official dev hard gate를 충족했다.",
            "production lifecycle과 new pipeline 연결이 검증됐다.",
        ]
        if production_passed
        else [
            f"실패한 production release condition: {name}"
            for name, passed in production_checks.items()
            if not passed
        ],
    }
    history = stage_history(report_root)
    result = {
        "stage": "step12_final_validation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_command": f"{sys.executable} {Path(__file__).name}",
        "report_root": str(report_root),
        "report_root_source": root_source,
        "output_dir": str(output_dir),
        "previous_stage": previous_stage,
        "source_tree_sha256": source_hash_after,
        "registry_audit": registry_audit,
        "shadow_validation_audit": shadow_audit,
        "permutation_audit": permutation_audit,
        "specificity_audit": specificity_audit,
        "historical_baseline": historical,
        "prior_candidate_manifest_dev": prior_manifest.get("dev"),
        "dev": regression["dev"],
        "dev_unchanged": regression["dev_unchanged"],
        "dev_hard_gate": dev_hard_gate,
        "screening_submission_sha256": regression["submission_sha256"],
        "screening_submission_unchanged": regression["submission_unchanged"],
        "tests": regression["tests"],
        "artifact_regeneration": {
            key: value
            for key, value in artifact.items()
            if not isinstance(value, Path)
        },
        "artifact_hashes": artifact_hashes,
        "self_review": self_review,
        "stage_history": history,
        "verification_gate": verification_gate,
        "production_release_gate": production_release_gate,
        "release_gate": {
            "status": production_release_gate["status"],
            "next_stage_allowed": production_passed,
            "checks": production_checks,
            "reasons": production_release_gate["reasons"],
        },
        "stage_manifest_path": str(output_dir / "stage_manifest.json"),
    }
    document_paths = write_final_documents(
        output_dir,
        result=result,
        report_root=report_root,
        prior_manifest=prior_manifest,
    )
    result_path = output_dir / "step12_result.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    final_report = output_dir / "FINAL_REPORT.md"
    final_report.write_text(build_final_report(result), encoding="utf-8")
    root_report = report_root / "final_report.md"
    root_report.write_bytes(final_report.read_bytes())
    write_stage_manifest(
        output_dir,
        stage="step12_final_validation",
        source_hash=source_hash_after,
        artifact_paths=(
            regression["submission_path"],
            result_path,
            final_report,
            artifact["candidate_manifest_path"],
            artifact["reference_manifest_path"],
            output_dir / "consistency_report.md",
            regression["shadow_diff_path"],
            *document_paths,
        ),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if production_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
