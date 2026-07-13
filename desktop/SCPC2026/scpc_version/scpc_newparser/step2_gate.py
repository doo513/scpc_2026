from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from build_manifest import sha256_file, source_files, source_tree_hash
from core.consistency import ConsistencyValidator
from core.contracts import (
    ASSUMPTION_REGISTRY,
    validate_assumption_registry,
)
from core.ontology import ONTOLOGY_TYPES, validate_ontology
from core.ownership import OWNERSHIP_REGISTRY, validate_ownership_registry
from run_submission import run_tasks, write_submission
from step1_baseline import (
    BASE_DIR,
    combined_hash,
    evaluate_dev,
    registry_ontology_files,
    resolve_report_root,
    run_command,
)
from utils.diff import compare_submissions
from utils.io import find_data_dir, load_jsonl
from validate_submission import validate_submission


def ontology_snapshot() -> dict[str, Any]:
    return {
        enum_type.__name__: {
            "canonical": [member.value for member in enum_type],
            "members": {
                name: member.value
                for name, member in enum_type.__members__.items()
            },
        }
        for enum_type in ONTOLOGY_TYPES
    }


def ownership_markdown() -> str:
    lines = [
        "# Step 2 Semantic Ownership",
        "",
        "| Field | Producer | Final owner | Validator |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {item.field} | {item.producer} | {item.final_owner} | {item.validator} |"
        for item in OWNERSHIP_REGISTRY
    )
    return "\n".join(lines) + "\n"


def build_report(result: dict[str, Any]) -> str:
    tests = result["tests"]
    gate = result["release_gate"]
    return "\n".join(
        [
            "# Step 2 공통 Ontology·단일 소유권 보고서",
            "",
            "## 변경 범위",
            "",
            "Step 2에서는 Typed Fact, NLP 규칙, RulePack 실행 의미를 변경하지 않았다. 공통 의미 타입과 candidate disposition owner를 도입하고 기존 중복 enum을 compatibility alias로 전환했다.",
            "",
            "## Data Contract",
            "",
            f"- ontology type 수: `{result['ontology_type_count']}`",
            f"- ownership field 수: `{result['ownership_field_count']}`",
            f"- unresolved assumption 수: `{result['assumption_count']}`",
            f"- ontology snapshot SHA-256: `{result['ontology_snapshot_sha256']}`",
            f"- source SHA-256: `{result['source_tree_sha256']}`",
            "",
            "`OperationMode`, `CandidateDisposition`, `InformationStatus`, `BlueprintEffectKind`의 독립 enum 정의를 제거했다. 기존 import 호환 이름은 각각 공통 `Operation`, `CandidateState`, `InformationStatus`, `ConstraintEffect` 객체를 가리킨다.",
            "",
            "## 단일 소유권",
            "",
            "- candidate state와 execution disposition 매핑: `CandidateDispositionPolicy`",
            "- target role/locality 조합 검증: `TargetBindingContract`",
            "- semantic field owner registry: `core/ownership.py`",
            "- Compiler는 semantic field의 final owner로 등록되지 않았다.",
            "",
            "## Assumption Trace",
            "",
            "공식 우선순위가 확인되지 않은 candidate-state mapping과 answer.target mapping은 `FinalDecision.unresolved_assumption_refs`에 남긴다. 등록되지 않은 assumption ID는 consistency validation에서 실패한다.",
            "",
            "## 검증",
            "",
            f"- Step 2 invariant: exit `{tests['stage_specific']['exit_code']}`, {', '.join(tests['stage_specific']['summary'])}",
            f"- 전체 pytest: exit `{tests['full']['exit_code']}`, {', '.join(tests['full']['summary'])}",
            f"- 알려진 dev gate 제외: exit `{tests['without_known_dev_gate']['exit_code']}`, {', '.join(tests['without_known_dev_gate']['summary'])}",
            f"- dev overall: `{result['dev']['overall']:.4f}` (Step 1과 동일: `{result['dev_unchanged']}`)",
            f"- screening public submission 동일: `{result['screening_submission_unchanged']}`",
            "",
            "전체 pytest의 dev hard gate 실패는 Step 1에서 고정한 baseline debt이며 해결됐다고 보지 않는다.",
            "",
            "## Step 2 Release Gate",
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
    output_dir = (
        args.output_dir or report_root / "step2_ontology"
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    step1_dir = report_root.resolve() / "step1_baseline"
    step1_result_path = step1_dir / "baseline_result.json"
    step1_result = (
        json.loads(step1_result_path.read_text(encoding="utf-8"))
        if step1_result_path.is_file()
        else None
    )

    validation_errors: list[str] = []
    for validator in (
        validate_ontology,
        validate_ownership_registry,
        validate_assumption_registry,
    ):
        try:
            validator()
        except Exception as exc:
            validation_errors.append(f"{validator.__name__}: {exc}")

    tests = {
        "stage_specific": run_command(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_ontology.py",
                "tests/test_architecture.py",
            ],
            output_dir / "pytest_stage2.log",
        ),
        "full": run_command(
            [sys.executable, "-m", "pytest", "-q"],
            output_dir / "pytest_full.log",
        ),
        "without_known_dev_gate": run_command(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-k",
                "not test_dev_score_and_optional_fields",
            ],
            output_dir / "pytest_without_known_dev_gate.log",
        ),
    }

    dev, dev_diagnostics = evaluate_dev()
    step1_dev = (step1_result or {}).get("dev")
    dev_unchanged = step1_dev == dev

    snapshot = ontology_snapshot()
    snapshot_path = output_dir / "ontology_snapshot.json"
    snapshot_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    ownership_path = output_dir / "ownership.json"
    ownership_path.write_text(
        json.dumps(
            [asdict(item) for item in OWNERSHIP_REGISTRY],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "OWNERSHIP.md").write_text(
        ownership_markdown(), encoding="utf-8"
    )
    (output_dir / "assumptions.json").write_text(
        json.dumps(
            [
                {
                    **asdict(item),
                    "status": item.status.value,
                }
                for item in ASSUMPTION_REGISTRY
            ],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "dev_error_distribution.json").write_text(
        json.dumps(dev_diagnostics, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    data_dir = find_data_dir()
    screening_payload = run_tasks(
        load_jsonl(data_dir / "screening_tasks.jsonl")
    )
    submission_path = output_dir / "submission.csv"
    write_submission(screening_payload, submission_path)
    validate_submission(submission_path)
    ConsistencyValidator.write_report(output_dir / "consistency_report.md")

    step1_submission = step1_dir / "submission.csv"
    screening_submission_unchanged = (
        step1_submission.is_file()
        and sha256_file(step1_submission) == sha256_file(submission_path)
    )
    if step1_submission.is_file():
        (output_dir / "shadow_diff_vs_step1.md").write_text(
            compare_submissions(step1_submission, submission_path) + "\n",
            encoding="utf-8",
        )

    known_failure = "tests/test_regression.py::test_dev_score_and_optional_fields"
    checks = {
        "step1_gate_available": bool(
            step1_result
            and step1_result.get("release_gate", {}).get("next_stage_allowed")
        ),
        "ontology_valid": not validation_errors,
        "stage_specific_tests": tests["stage_specific"]["exit_code"] == 0,
        "without_known_dev_gate": (
            tests["without_known_dev_gate"]["exit_code"] == 0
        ),
        "only_known_full_test_failure": (
            tests["full"]["exit_code"] == 1
            and tests["full"]["failed_tests"] == [known_failure]
        ),
        "dev_unchanged": dev_unchanged,
        "screening_submission_unchanged": screening_submission_unchanged,
    }
    gate_passed = all(checks.values())
    release_gate = {
        "status": "PASS_WITH_BASELINE_DEBT" if gate_passed else "FAIL",
        "next_stage_allowed": gate_passed,
        "checks": checks,
        "reasons": [
            "공통 ontology, ownership, assumption registry 무결성 검증이 통과했다.",
            "Step 1 대비 public dev 수치와 screening submission이 변하지 않았다.",
            "기존 dev hard gate 실패 1건은 baseline debt로 유지한다.",
        ]
        if gate_passed
        else [
            f"실패한 Step 2 gate: {name}"
            for name, passed in checks.items()
            if not passed
        ]
        + validation_errors,
    }

    result = {
        "stage": "step2_ontology",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_command": f"{sys.executable} {Path(__file__).name}",
        "report_root": str(report_root.resolve()),
        "report_root_source": root_source,
        "output_dir": str(output_dir),
        "source_tree_sha256": source_tree_hash(source_files()),
        "registry_ontology_sha256": combined_hash(
            registry_ontology_files(), root=BASE_DIR
        ),
        "ontology_snapshot_sha256": sha256_file(snapshot_path),
        "ontology_type_count": len(ONTOLOGY_TYPES),
        "ownership_field_count": len(OWNERSHIP_REGISTRY),
        "assumption_count": len(ASSUMPTION_REGISTRY),
        "dev": dev,
        "dev_unchanged": dev_unchanged,
        "screening_submission_sha256": sha256_file(submission_path),
        "screening_submission_unchanged": screening_submission_unchanged,
        "tests": tests,
        "validation_errors": validation_errors,
        "release_gate": release_gate,
    }
    (output_dir / "step2_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "STEP2_REPORT.md").write_text(
        build_report(result), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
