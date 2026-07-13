from __future__ import annotations

import argparse
import ast
import copy
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable

from build_manifest import sha256_file, source_files, source_tree_hash
from core.consistency import ConsistencyValidator
from core.ontology import FactStatus, validate_ontology
from core.records import (
    RECORD_ADAPTER_REGISTRY,
    validate_record_adapter_registry,
)
from core.task_view import TaskView
from run_submission import run_tasks, write_submission
from step1_baseline import (
    BASE_DIR,
    combined_hash,
    evaluate_dev,
    resolve_report_root,
    run_command,
)
from utils.diff import compare_submissions
from utils.io import find_data_dir, load_jsonl
from validate_submission import validate_submission


KNOWN_DEV_FAILURE = "tests/test_regression.py::test_dev_score_and_optional_fields"


def archive_failed_attempt(output_dir: Path) -> None:
    result_path = output_dir / "step3_result.json"
    if not result_path.is_file():
        return
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if result.get("release_gate", {}).get("status") != "FAIL":
        return
    attempts_dir = output_dir / "gate_attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)
    index = 1
    while (attempts_dir / f"attempt_{index:03d}_result.json").exists():
        index += 1
    (attempts_dir / f"attempt_{index:03d}_result.json").write_bytes(
        result_path.read_bytes()
    )
    report_path = output_dir / "STEP3_REPORT.md"
    if report_path.is_file():
        (attempts_dir / f"attempt_{index:03d}_report.md").write_bytes(
            report_path.read_bytes()
        )


def resolve_previous_stage(
    report_root: Path,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    candidates = (
        report_root / "step2_ontology",
        report_root / "op_reports" / "step2_ontology",
    )
    errors: list[str] = []
    for directory in candidates:
        result_path = directory / "step2_result.json"
        submission_path = directory / "submission.csv"
        if not result_path.is_file():
            continue
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{result_path}: {exc}")
            continue
        checks = {
            "stage_name": result.get("stage") == "step2_ontology",
            "release_gate": bool(
                result.get("release_gate", {}).get("next_stage_allowed")
            ),
            "submission_present": submission_path.is_file(),
            "submission_hash": (
                submission_path.is_file()
                and result.get("screening_submission_sha256")
                == sha256_file(submission_path)
            ),
            "dev_result_present": isinstance(result.get("dev"), dict),
        }
        integrity = {
            "resolved_directory": str(directory.resolve()),
            "declared_output_directory": result.get("output_dir"),
            "relocated": str(directory.resolve())
            != str(result.get("output_dir") or ""),
            "checks": checks,
            "errors": errors,
        }
        if all(checks.values()):
            return directory, result, integrity
        errors.append(
            f"{directory}: failed checks "
            + ", ".join(name for name, passed in checks.items() if not passed)
        )
    return (
        report_root / "step2_ontology",
        {},
        {
            "resolved_directory": "",
            "declared_output_directory": "",
            "relocated": False,
            "checks": {},
            "errors": errors or ["Step 2 result not found"],
        },
    )


def step3_contract_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in (
            BASE_DIR / "core" / "ontology.py",
            BASE_DIR / "core" / "facts.py",
            BASE_DIR / "core" / "records.py",
            BASE_DIR / "core" / "task_view.py",
            BASE_DIR / "core" / "relations.py",
        )
        if path.is_file()
    )


def adapter_snapshot() -> list[dict[str, Any]]:
    return [
        {
            "adapter_id": adapter.adapter_id,
            "supported_record_type": adapter.supported_record_type.value,
            "validation_rules": list(adapter.validation_rules),
            "unknown_value_policy": adapter.unknown_value_policy.value,
            "contract_status": adapter.contract_status.value,
            "basis_refs": list(adapter.basis_refs),
            "assumption_refs": list(adapter.assumption_refs),
        }
        for adapter in RECORD_ADAPTER_REGISTRY.adapters
    ]


def runtime_raw_record_violations() -> list[str]:
    allowed = {BASE_DIR / "core" / "records.py"}
    paths = [BASE_DIR / "harness.py"]
    paths.extend((BASE_DIR / "core").glob("*.py"))
    paths.extend((BASE_DIR / "rules").glob("*.py"))
    prohibited_calls = {"latest_record_value", "record_values", "latest_value"}
    violations: list[str] = []
    for path in paths:
        if path in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in prohibited_calls:
                    violations.append(
                        f"{path.relative_to(BASE_DIR)}:{node.lineno}:{node.func.attr}"
                    )
                if (
                    node.func.attr == "get"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "value"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in {"record", "raw_record"}
                ):
                    violations.append(
                        f"{path.relative_to(BASE_DIR)}:{node.lineno}:raw value get"
                    )
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id in {"record", "raw_record"}
                and isinstance(node.slice, ast.Constant)
                and node.slice.value == "value"
            ):
                violations.append(
                    f"{path.relative_to(BASE_DIR)}:{node.lineno}:raw value subscript"
                )
    return sorted(violations)


def audit_official_typed_facts() -> dict[str, Any]:
    data_dir = find_data_dir()
    tasks: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    for filename in ("dev_tasks.jsonl", "screening_tasks.jsonl"):
        source_tasks = load_jsonl(data_dir / filename)
        source_counts[filename] = len(source_tasks)
        tasks.extend(source_tasks)

    collection_statuses: Counter[str] = Counter()
    object_statuses: Counter[str] = Counter()
    record_statuses: Counter[str] = Counter()
    record_types: Counter[str] = Counter()
    chronology_domains: Counter[str] = Counter()
    permutation_failures: list[str] = []
    non_present_examples: list[dict[str, str]] = []
    snapshot_hash = hashlib.sha256()

    for task in tasks:
        task_id = str(task.get("id") or "")
        view = TaskView(task, {})
        snapshot = view.typed_facts
        collection_statuses[f"objects:{snapshot.object_collection_status.value}"] += 1
        collection_statuses[f"records:{snapshot.record_collection_status.value}"] += 1
        collection_statuses[f"capabilities:{snapshot.capabilities.status.value}"] += 1
        for fact in snapshot.objects:
            object_statuses[fact.status.value] += 1
            if fact.status != FactStatus.PRESENT and len(non_present_examples) < 20:
                non_present_examples.append(
                    {
                        "task_id": task_id,
                        "kind": "object",
                        "type": fact.source_type,
                        "status": fact.status.value,
                    }
                )
        for fact in snapshot.records:
            record_statuses[fact.status.value] += 1
            record_types[fact.source_type] += 1
            if fact.chronology is not None:
                chronology_domains[fact.chronology.domain.value] += 1
            if fact.status != FactStatus.PRESENT and len(non_present_examples) < 20:
                non_present_examples.append(
                    {
                        "task_id": task_id,
                        "kind": "record",
                        "type": fact.source_type,
                        "status": fact.status.value,
                    }
                )

        snapshot_payload = {
            "task_id": task_id,
            "snapshot": snapshot.to_trace(),
            "objects": [
                {
                    **fact.to_trace(),
                    "attributes": fact.attributes.to_dict(),
                }
                for fact in snapshot.objects
            ],
            "records": [
                {
                    **fact.to_trace(),
                    "conflict_key": fact.conflict_key,
                    "semantic_value": repr(fact.semantic_value),
                }
                for fact in snapshot.records
            ],
            "capabilities": sorted(snapshot.capabilities.action_values),
            "unknown_actions": list(snapshot.capabilities.unknown_actions),
            "session": snapshot.session.values.to_dict(),
        }
        snapshot_hash.update(
            json.dumps(
                snapshot_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        permuted = copy.deepcopy(task)
        state = permuted.get("device_state")
        if isinstance(state, dict):
            if isinstance(state.get("objects"), list):
                state["objects"] = list(reversed(state["objects"]))
            if isinstance(state.get("records"), list):
                state["records"] = list(reversed(state["records"]))
        if TaskView(permuted, {}).typed_facts != snapshot:
            permutation_failures.append(task_id)

    expected_collection_count = len(tasks)
    collection_contract_ok = all(
        collection_statuses.get(f"{kind}:present", 0) == expected_collection_count
        for kind in ("objects", "records", "capabilities")
    )
    return {
        "task_count": len(tasks),
        "source_counts": source_counts,
        "collection_statuses": dict(sorted(collection_statuses.items())),
        "object_statuses": dict(sorted(object_statuses.items())),
        "record_statuses": dict(sorted(record_statuses.items())),
        "record_types": dict(sorted(record_types.items())),
        "chronology_domains": dict(sorted(chronology_domains.items())),
        "snapshot_sha256": snapshot_hash.hexdigest(),
        "permutation_failures": permutation_failures,
        "non_present_examples": non_present_examples,
        "collection_contract_ok": collection_contract_ok,
        "all_facts_present": (
            set(object_statuses) <= {FactStatus.PRESENT.value}
            and set(record_statuses) <= {FactStatus.PRESENT.value}
        ),
    }


def typed_fact_contract_markdown(snapshot: list[dict[str, Any]]) -> str:
    lines = [
        "# Step 3 Typed Fact 및 RecordAdapter 계약",
        "",
        "## 처리 경계",
        "",
        "`TaskView`는 공식 입력을 `TypedObjectFact`, `TypedRecordFact`, `CapabilitySnapshot`, `SessionSnapshot`으로 변환한다. runtime evaluator, target resolver, compiler는 raw record `value`를 읽지 않는다.",
        "",
        "## FactStatus",
        "",
        "| 상태 | 의미 |",
        "| --- | --- |",
        "| `PRESENT` | adapter 검증을 통과한 현재 fact |",
        "| `MISSING` | 입력 필드 또는 요청한 record가 없음 |",
        "| `UNKNOWN` | type은 알지만 value vocabulary를 해석하지 못함 |",
        "| `CONFLICTED` | 비교 가능한 chronology 없이 값이 충돌함 |",
        "| `INVALID` | shape, JSON 값 또는 chronology 형식이 잘못됨 |",
        "| `NOT_APPLICABLE` | 해당 후보·도메인에 적용되지 않음 |",
        "",
        "## Chronology",
        "",
        "`turn_index`, `turn`, `timestamp`, `updated_at`, `created_at`은 각각 별도 domain이다. 동일 domain과 동일 value kind인 경우에만 비교하며, 배열 위치는 최신성 근거로 사용하지 않는다.",
        "",
        "## Adapter Registry",
        "",
        "| Record type | Unknown policy | Contract status |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| `{item['supported_record_type']}` | `{item['unknown_value_policy']}` | `{item['contract_status']}` |"
        for item in snapshot
    )
    lines.extend(
        [
            "",
            "구조화된 record token의 의미 연결은 공식 용어집과 공개 데이터에서 확인된 범위의 `SUPPORTED_INTERPRETATION`으로 관리한다. unknown token은 default action이나 target으로 변환하지 않는다.",
            "",
        ]
    )
    return "\n".join(lines)


def build_report(result: dict[str, Any]) -> str:
    tests = result["tests"]
    audit = result["typed_fact_audit"]
    gate = result["release_gate"]
    previous = result["previous_stage"]
    return "\n".join(
        [
            "# Step 3 공식 입력 계약·Typed Fact·RecordAdapter 보고서",
            "",
            "## 작업 범위",
            "",
            "Step 3에서는 공식 JSON 입력을 typed fact로 변환하는 경계를 고정했다. 자연어 parser, RulePack, candidate 평가 규칙은 변경하지 않았다.",
            "",
            "## 구현 결과",
            "",
            "- `TaskView`에 object, record, capability, session snapshot을 추가했다.",
            "- `FactStatus`는 missing, unknown, conflict, invalid를 서로 다른 상태로 보존한다.",
            "- raw record value 해석은 type별 `RecordAdapter`로 제한했다.",
            "- record chronology는 동일 domain 안에서만 비교한다.",
            "- `gallery_item`과 공식 용어집에 기재된 record type을 ontology에 반영했다.",
            "",
            "## 공식 입력 Audit",
            "",
            f"- 검사 task: `{audit['task_count']}`개",
            f"- object 상태: `{json.dumps(audit['object_statuses'], ensure_ascii=False, sort_keys=True)}`",
            f"- record 상태: `{json.dumps(audit['record_statuses'], ensure_ascii=False, sort_keys=True)}`",
            f"- permutation 실패: `{len(audit['permutation_failures'])}`개",
            f"- typed snapshot SHA-256: `{audit['snapshot_sha256']}`",
            "",
            "공식 820개 입력에서 typed parsing 오류가 없다는 결과는 입력 계약의 구조적 적합성을 뜻한다. semantic answer accuracy로 해석하지 않는다.",
            "",
            "## 검증 결과",
            "",
            f"- Step 2 기준 산출물: `{previous['resolved_directory']}` (이동 감지: `{previous['relocated']}`)",
            f"- Step 3 invariant: exit `{tests['stage_specific']['exit_code']}`, {', '.join(tests['stage_specific']['summary'])}",
            f"- 전체 pytest: exit `{tests['full']['exit_code']}`, {', '.join(tests['full']['summary'])}",
            f"- 알려진 dev gate 제외: exit `{tests['without_known_dev_gate']['exit_code']}`, {', '.join(tests['without_known_dev_gate']['summary'])}",
            f"- dev overall: `{result['dev']['overall']:.4f}` (Step 2와 동일: `{result['dev_unchanged']}`)",
            f"- screening public submission 동일: `{result['screening_submission_unchanged']}`",
            f"- runtime raw record 접근 위반: `{len(result['raw_record_violations'])}`건",
            "",
            "전체 pytest의 dev hard gate 1건은 Step 1에서 확인한 baseline debt다. 이번 단계에서 해소됐다고 보고하지 않는다.",
            "",
            "## 계약 등급과 한계",
            "",
            "record type과 기본 의미는 공식 용어집을 근거로 삼았다. 공개 자료가 모든 value vocabulary를 열거하지 않으므로, 구체 token mapping은 `SUPPORTED_INTERPRETATION`으로 유지한다. 등록되지 않은 token은 `UNKNOWN`으로 보존하며 실행 의미로 승격하지 않는다.",
            "",
            "## Step 3 Release Gate",
            "",
            f"- 상태: **{gate['status']}**",
            f"- 다음 단계 진입 가능: **{gate['next_stage_allowed']}**",
            *[f"- {reason}" for reason in gate["reasons"]],
            "",
        ]
    )


def write_stage_manifest(
    output_dir: Path,
    *,
    source_hash: str,
    artifact_paths: Iterable[Path],
) -> Path:
    data_dir = find_data_dir()
    manifest = {
        "stage": "step3_typed_facts",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_tree_sha256": source_hash,
        "official_data_sha256": {
            name: sha256_file(data_dir / name)
            for name in (
                "dev_tasks.jsonl",
                "dev_answers.json",
                "screening_tasks.jsonl",
            )
        },
        "artifacts": {
            path.name: sha256_file(path) for path in artifact_paths if path.is_file()
        },
    }
    path = output_dir / "stage_manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    report_root, root_source = resolve_report_root()
    output_dir = (args.output_dir or report_root / "step3_typed_facts").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_failed_attempt(output_dir)
    step2_dir, step2_result, previous_stage = resolve_previous_stage(
        report_root.resolve()
    )

    source_hash_before = source_tree_hash(source_files())
    validation_errors: list[str] = []
    for validator in (validate_ontology, validate_record_adapter_registry):
        try:
            validator()
        except Exception as exc:
            validation_errors.append(f"{validator.__name__}: {exc}")

    snapshot = adapter_snapshot()
    adapter_path = output_dir / "record_adapter_registry.json"
    adapter_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    contract_path = output_dir / "TYPED_FACT_CONTRACT.md"
    contract_path.write_text(
        typed_fact_contract_markdown(snapshot),
        encoding="utf-8",
    )

    raw_violations = runtime_raw_record_violations()
    audit = audit_official_typed_facts()
    audit_path = output_dir / "typed_fact_audit.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    tests = {
        "stage_specific": run_command(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_typed_facts.py",
                "tests/test_task_view.py",
                "tests/test_architecture.py",
                "tests/test_ontology.py",
            ],
            output_dir / "pytest_stage3.log",
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
    (output_dir / "dev_error_distribution.json").write_text(
        json.dumps(dev_diagnostics, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    step2_dev = (step2_result or {}).get("dev")
    dev_unchanged = step2_dev == dev

    data_dir = find_data_dir()
    screening_payload = run_tasks(load_jsonl(data_dir / "screening_tasks.jsonl"))
    submission_path = output_dir / "submission.csv"
    write_submission(screening_payload, submission_path)
    validate_submission(submission_path)
    ConsistencyValidator.write_report(output_dir / "consistency_report.md")

    step2_submission = step2_dir / "submission.csv"
    screening_submission_unchanged = step2_submission.is_file() and sha256_file(
        step2_submission
    ) == sha256_file(submission_path)
    if step2_submission.is_file():
        (output_dir / "shadow_diff_vs_step2.md").write_text(
            compare_submissions(step2_submission, submission_path) + "\n",
            encoding="utf-8",
        )

    source_hash_after = source_tree_hash(source_files())
    checks = {
        "step2_gate_available": bool(
            step2_result
            and step2_result.get("release_gate", {}).get("next_stage_allowed")
        ),
        "step2_artifact_integrity": bool(previous_stage.get("checks"))
        and all(previous_stage["checks"].values()),
        "ontology_and_adapter_registry_valid": not validation_errors,
        "raw_record_boundary_clean": not raw_violations,
        "official_collection_contract": audit["collection_contract_ok"],
        "official_fact_parsing": audit["all_facts_present"],
        "typed_fact_permutation": not audit["permutation_failures"],
        "stage_specific_tests": tests["stage_specific"]["exit_code"] == 0,
        "without_known_dev_gate": (tests["without_known_dev_gate"]["exit_code"] == 0),
        "only_known_full_test_failure": (
            tests["full"]["exit_code"] == 1
            and tests["full"]["failed_tests"] == [KNOWN_DEV_FAILURE]
        ),
        "dev_unchanged": dev_unchanged,
        "screening_submission_unchanged": screening_submission_unchanged,
        "source_stable_during_gate": source_hash_before == source_hash_after,
    }
    gate_passed = all(checks.values())
    release_gate = {
        "status": "PASS_WITH_BASELINE_DEBT" if gate_passed else "FAIL",
        "next_stage_allowed": gate_passed,
        "checks": checks,
        "reasons": [
            "Typed Fact 상태 분리와 RecordAdapter 경계 검증이 통과했다.",
            "공식 820개 입력의 typed parsing과 배열 permutation 검증이 통과했다.",
            "Step 2 대비 public dev 수치와 screening submission이 변하지 않았다.",
            "기존 dev hard gate 실패 1건은 baseline debt로 유지한다.",
        ]
        if gate_passed
        else [
            f"실패한 Step 3 gate: {name}"
            for name, passed in checks.items()
            if not passed
        ]
        + validation_errors
        + raw_violations
        + list(previous_stage.get("errors") or []),
    }

    result = {
        "stage": "step3_typed_facts",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_command": f"{sys.executable} {Path(__file__).name}",
        "report_root": str(report_root.resolve()),
        "report_root_source": root_source,
        "output_dir": str(output_dir),
        "previous_stage": previous_stage,
        "source_tree_sha256": source_hash_after,
        "step3_contract_sha256": combined_hash(step3_contract_files(), root=BASE_DIR),
        "adapter_registry_sha256": sha256_file(adapter_path),
        "adapter_count": len(snapshot),
        "adapter_contract_statuses": dict(
            Counter(item["contract_status"] for item in snapshot)
        ),
        "typed_fact_audit": audit,
        "raw_record_violations": raw_violations,
        "dev": dev,
        "dev_unchanged": dev_unchanged,
        "screening_submission_sha256": sha256_file(submission_path),
        "screening_submission_unchanged": screening_submission_unchanged,
        "tests": tests,
        "validation_errors": validation_errors,
        "release_gate": release_gate,
        "stage_manifest_path": str(output_dir / "stage_manifest.json"),
    }
    result_path = output_dir / "step3_result.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path = output_dir / "STEP3_REPORT.md"
    report_path.write_text(build_report(result), encoding="utf-8")
    write_stage_manifest(
        output_dir,
        source_hash=source_hash_after,
        artifact_paths=(
            adapter_path,
            contract_path,
            audit_path,
            submission_path,
            result_path,
            report_path,
            output_dir / "consistency_report.md",
            output_dir / "shadow_diff_vs_step2.md",
        ),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
