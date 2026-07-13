from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable

from build_manifest import sha256_file, source_files, source_tree_hash
from core.consistency import ConsistencyValidator
from core.contracts import ASSUMPTION_REGISTRY
from local_score import evaluate_dev_payload
from run_submission import run_tasks, write_submission, write_traces
from utils.diff import compare_submissions
from utils.io import find_data_dir, load_jsonl
from utils.report import generate_distribution_report
from validate_artifacts import validate_current_artifacts
from validate_submission import find_schema_path, validate_submission


BASE_DIR = Path(__file__).resolve().parent
def resolve_report_root(
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
    workspace: Path = BASE_DIR,
) -> tuple[Path, str]:
    environ = environ if environ is not None else os.environ
    configured = str(environ.get("SCPC_REPORT_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser(), "SCPC_REPORT_DIR"

    if workspace.parent.name.lower() == "desktop":
        return workspace.parent / "scpc_reports", "user_desktop"
    home = home or Path.home()
    desktop = home / "Desktop"
    if desktop.is_dir():
        return desktop / "scpc_reports", "user_desktop"
    return workspace / "scpc_reports", "workspace_fallback"


def combined_hash(paths: Iterable[Path], *, root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def config_files() -> tuple[Path, ...]:
    files = [BASE_DIR / "requirements.txt", BASE_DIR / "submission_schema.json"]
    files.extend(sorted((BASE_DIR / "tests" / "specs").glob("*.json")))
    return tuple(path for path in files if path.is_file())


def registry_ontology_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in (
            BASE_DIR / "core" / "spec.py",
            BASE_DIR / "core" / "blueprint.py",
            BASE_DIR / "core" / "records.py",
            BASE_DIR / "core" / "decision.py",
        )
        if path.is_file()
    )


def run_command(command: list[str], log_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=BASE_DIR,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log_path.write_text(completed.stdout, encoding="utf-8")
    summary_match = re.findall(
        r"(?:\d+ passed|\d+ failed|\d+ deselected)", completed.stdout
    )
    failed_tests = re.findall(r"FAILED ([^\s]+)", completed.stdout)
    return {
        "command": command,
        "exit_code": completed.returncode,
        "summary": summary_match[-3:],
        "failed_tests": sorted(set(failed_tests)),
        "log": str(log_path),
    }


def evaluate_dev() -> tuple[dict[str, Any], dict[str, Any]]:
    data_dir = find_data_dir()
    tasks = load_jsonl(data_dir / "dev_tasks.jsonl")
    reference_payload = json.loads(
        (data_dir / "dev_answers.json").read_text(encoding="utf-8")
    )
    payload = run_tasks(tasks)
    return evaluate_dev_payload(payload, reference_payload)


def audit_existing_artifacts(
    current_source_hash: str,
    actual_dev: dict[str, Any],
) -> dict[str, Any]:
    submission = BASE_DIR / "submission.csv"
    manifest_path = BASE_DIR / "manifest" / "candidate_manifest.json"
    report_path = BASE_DIR / "reports" / "dev_score_report.md"
    result: dict[str, Any] = {
        "submission_path": str(submission),
        "manifest_path": str(manifest_path),
        "dev_report_path": str(report_path),
    }
    try:
        validate_current_artifacts(submission, manifest_path)
        result["validator_status"] = "CURRENT"
    except Exception as exc:
        result["validator_status"] = "STALE"
        result["validator_error"] = f"{type(exc).__name__}: {exc}"

    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file()
        else {}
    )
    result["manifest_source_sha256"] = manifest.get("source_tree_sha256")
    result["current_source_sha256"] = current_source_hash
    result["source_hash_matches"] = (
        manifest.get("source_tree_sha256") == current_source_hash
    )
    result["manifest_dev_overall"] = (manifest.get("dev") or {}).get("overall")
    result["actual_dev_overall"] = actual_dev["overall"]
    result["dev_metric_matches"] = (
        result["manifest_dev_overall"] == actual_dev["overall"]
    )
    if submission.is_file():
        result["submission_sha256"] = sha256_file(submission)
        result["submission_hash_matches"] = (
            result["submission_sha256"] == manifest.get("submission_sha256")
        )
    if report_path.is_file():
        text = report_path.read_text(encoding="utf-8")
        match = re.search(r"Overall:\s*`([0-9.]+)`", text)
        result["report_dev_overall"] = float(match.group(1)) if match else None
        result["report_metric_matches"] = (
            result["report_dev_overall"] == actual_dev["overall"]
        )
    return result


def validate_reference_manifest(data_hashes: dict[str, str]) -> dict[str, Any]:
    path = BASE_DIR / "manifest" / "reference_manifest.json"
    if not path.is_file():
        return {"status": "NOT_RUN", "reason": "reference manifest missing"}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    recorded = manifest.get("official_data") or {}
    mismatches = {
        name: {"recorded": recorded.get(name), "actual": digest}
        for name, digest in data_hashes.items()
        if recorded.get(name) != digest
    }
    return {
        "status": "PASS" if not mismatches else "FAIL",
        "path": str(path),
        "sha256": sha256_file(path),
        "data_hash_mismatches": mismatches,
        "historical_best": manifest.get("baseline"),
    }


def assumption_inventory() -> list[dict[str, Any]]:
    return [
        {
            "assumption_id": item.assumption_id,
            "statement": item.statement,
            "status": item.status.value,
            "supporting_evidence_refs": list(item.supporting_evidence_refs),
            "counterexample_refs": list(item.counterexample_refs),
            "affected_types": list(item.affected_types),
            "affected_modules": list(item.affected_modules),
            "current_resolution": item.current_resolution,
            "review_owner": item.review_owner,
        }
        for item in ASSUMPTION_REGISTRY
    ]


def build_stage_report(result: dict[str, Any]) -> str:
    dev = result["dev"]
    tests = result["tests"]
    stale = result["existing_artifacts"]
    gate = result["release_gate"]
    lines = [
        "# Step 1 현재 상태 재검증 보고서",
        "",
        "## 실행 범위",
        "",
        "본 단계는 현재 소스, 공식 데이터, scorer, schema와 생성 산출물을 같은 환경에서 재실행해 기준선을 고정했다. 기존 보고서의 수치는 재사용하지 않았다.",
        "",
        "## 재현 명령",
        "",
        f"```bash\n{result['baseline_command']}\n```",
        "",
        "## 검증된 사실",
        "",
        f"- source SHA-256: `{result['hashes']['source_tree_sha256']}`",
        f"- data aggregate SHA-256: `{result['hashes']['data_tree_sha256']}`",
        f"- config SHA-256: `{result['hashes']['config_sha256']}`",
        f"- registry/ontology snapshot SHA-256: `{result['hashes']['registry_ontology_sha256']}`",
        f"- generated submission SHA-256: `{result['hashes']['submission_sha256']}`",
        f"- dev overall: `{dev['overall']:.4f}`",
        f"- exact match: `{dev['exact_match_count']} / {dev['n']}`",
        f"- non-exact: `{dev['non_exact_count']}`",
        f"- screening submission answers: `{result['screening_answers']}`",
        "",
        "## 필드별 dev 오류",
        "",
    ]
    lines.extend(
        f"- {axis}: {count}"
        for axis, count in dev["field_error_counts"].items()
    )
    lines.extend(
        [
            "",
            "## 테스트와 검증",
            "",
            f"- 전체 pytest: exit `{tests['full']['exit_code']}`, {', '.join(tests['full']['summary'])}",
            f"- 알려진 dev gate 제외: exit `{tests['without_known_dev_gate']['exit_code']}`, {', '.join(tests['without_known_dev_gate']['summary'])}",
            f"- generated submission validation: `{result['generated_artifact_validation']['status']}`",
            f"- reference manifest data hash: `{result['reference_manifest_validation']['status']}`",
            "",
            "전체 pytest의 유일한 실패는 현재 dev hard gate다. 이 실패는 Step 1에서 재현된 baseline debt로 유지하며 통과로 표기하지 않는다.",
            "",
            "## 기존 산출물 상태",
            "",
            f"- 기존 artifact validator: `{stale['validator_status']}`",
            f"- 기존 manifest source hash 일치: `{stale['source_hash_matches']}`",
            f"- 기존 manifest dev 수치 일치: `{stale['dev_metric_matches']}`",
            f"- 기존 dev report 수치 일치: `{stale.get('report_metric_matches')}`",
            "- 생성 시각은 freshness 근거로 사용하지 않음: `True`",
            "",
            "기존 `reports/`, `submission.csv`, candidate manifest는 삭제하거나 덮어쓰지 않았으며 stale 기준 자산으로 분리했다.",
            "",
            "## 진단 재검증",
            "",
            "- 일반화된 DomainOperationRulePack Registry: 구현돼 있으나 official dev 승격 gate를 통과하지 못해 shadow-only다.",
            "- Compiler raw state 재조회: 현재 Scope/Policy/Plan compiler는 FinalDecision만 입력받으므로 해당 주장은 재현되지 않았다.",
            "- validation-before-commit: production harness에서 validator 통과 후 AtomicSessionCommitter를 호출하므로 충족된다.",
            "- generic user execution target: TargetResolver의 일반 user fallback은 제거되어 있다. user는 clarification/stop/unresolved output에만 사용된다.",
            "- plan capability/plan 생성 중복: blueprint capability와 FinalDecisionBuilder의 plan branch가 병존하므로 부분적으로 재현된다. 현재는 verb equality assertion으로 불일치를 차단한다.",
            "- manifest/report freshness: source·data·scorer·artifact content hash와 격리 재생성 결과로만 판정한다.",
            "",
            "## 공식 계약·해석·가정",
            "",
            "- `CONFIRMED_CONTRACT`: 공식 schema, task/answer ID 집합, 제공 scorer 입력과 공식 데이터 hash.",
            "- `SUPPORTED_INTERPRETATION`: current compiler가 FinalDecision의 pure projection이라는 코드·테스트 기반 판단.",
            f"- `UNRESOLVED_ASSUMPTION`: {len(result['assumptions'])}건. 상세는 `assumptions.json`에 기록했다.",
            "",
            "## Step 1 Release Gate",
            "",
            f"- 상태: **{gate['status']}**",
            f"- 다음 단계 진입 가능: **{gate['next_stage_allowed']}**",
        ]
    )
    lines.extend(f"- {item}" for item in gate["reasons"])
    lines.extend(
        [
            "",
            "Step 1은 기준선 재현과 stale 분리를 완료했다. dev hard gate 실패는 해결된 것으로 간주하지 않으며 이후 단계의 shadow baseline debt로 유지한다.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()

    root, root_source = resolve_report_root()
    output_dir = (args.output_dir or root / "step1_baseline").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    baseline_command = f"{sys.executable} {Path(__file__).name}"
    (output_dir / "baseline_command.txt").write_text(
        baseline_command + "\n", encoding="utf-8"
    )

    source_hash = source_tree_hash(source_files())
    data_dir = find_data_dir()
    data_names = (
        "dev_tasks.jsonl",
        "dev_answers.json",
        "screening_tasks.jsonl",
    )
    data_hashes = {name: sha256_file(data_dir / name) for name in data_names}
    data_tree_hash = combined_hash(
        (data_dir / name for name in data_names), root=data_dir
    )
    config_hash = combined_hash(config_files(), root=BASE_DIR)
    registry_hash = combined_hash(registry_ontology_files(), root=BASE_DIR)

    tests: dict[str, Any]
    if args.skip_tests:
        tests = {
            "full": {"exit_code": None, "summary": ["NOT_RUN"], "failed_tests": []},
            "without_known_dev_gate": {
                "exit_code": None,
                "summary": ["NOT_RUN"],
                "failed_tests": [],
            },
        }
    else:
        tests = {
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
    existing_artifacts = audit_existing_artifacts(source_hash, dev)
    reference_validation = validate_reference_manifest(data_hashes)

    screening_tasks = load_jsonl(data_dir / "screening_tasks.jsonl")
    screening_payload = run_tasks(screening_tasks)
    submission_path = output_dir / "submission.csv"
    write_submission(screening_payload, submission_path)
    write_traces(
        screening_payload.get("_traces", []),
        output_dir / "decision_trace.jsonl",
    )
    validate_submission(submission_path)
    ConsistencyValidator.write_report(output_dir / "consistency_report.md")
    (output_dir / "screening_structural_report.md").write_text(
        generate_distribution_report(submission_path) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "candidate": "scpc_coparser_step1_baseline",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_tree_sha256": source_hash,
        "data_sha256": data_hashes,
        "submission_sha256": sha256_file(submission_path),
        "submission_answers": len(screening_payload["answers"]),
        "dev": dev,
        "contract": {
            "schema": "scpc.final.answer.v1",
            "uses_external_api": False,
            "fixed_slm_policy": "local_fixed_slm_only",
        },
        "stage": "step1_baseline",
    }
    manifest_path = output_dir / "candidate_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        artifact_validation = {
            "status": "PASS",
            **validate_current_artifacts(submission_path, manifest_path),
        }
    except Exception as exc:
        artifact_validation = {
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
        }

    stale_submission = BASE_DIR / "submission.csv"
    if stale_submission.is_file():
        (output_dir / "diff_vs_stale_submission.md").write_text(
            compare_submissions(stale_submission, submission_path) + "\n",
            encoding="utf-8",
        )
    legacy_submission = (
        BASE_DIR.parent
        / "scpc_Gparser"
        / "reference"
        / "V5_modular_harness"
        / "submission.csv"
    )
    if legacy_submission.is_file():
        (output_dir / "diff_vs_legacy_submission.md").write_text(
            compare_submissions(legacy_submission, submission_path) + "\n",
            encoding="utf-8",
        )

    assumptions = assumption_inventory()
    (output_dir / "assumptions.json").write_text(
        json.dumps(assumptions, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "dev_error_distribution.json").write_text(
        json.dumps(dev_diagnostics, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    known_failure = "tests/test_regression.py::test_dev_score_and_optional_fields"
    full_failures = tests["full"].get("failed_tests", [])
    gate_checks = {
        "reproducible_command": bool(baseline_command),
        "generated_artifact_validation": artifact_validation["status"] == "PASS",
        "reference_data_hash_validation": reference_validation["status"] == "PASS",
        "stage_specific_tests": tests["without_known_dev_gate"]["exit_code"] == 0,
        "only_known_full_test_failure": (
            tests["full"]["exit_code"] == 1
            and full_failures == [known_failure]
        ),
        "stale_artifacts_distinguished": (
            existing_artifacts["validator_status"] == "STALE"
            and not existing_artifacts["source_hash_matches"]
            and not existing_artifacts["dev_metric_matches"]
        ),
    }
    gate_passed = all(gate_checks.values())
    release_gate = {
        "status": "PASS_WITH_BASELINE_DEBT" if gate_passed else "FAIL",
        "next_stage_allowed": gate_passed,
        "checks": gate_checks,
        "reasons": [
            "재현 명령, current hash, generated artifact validation과 stage-specific test가 일치한다.",
            "전체 pytest의 dev hard gate 실패 1건은 해결되지 않은 baseline debt로 고정한다.",
            "기존 report/submission/manifest는 current baseline과 분리해 stale로 표시했다.",
        ]
        if gate_passed
        else [
            f"실패한 Step 1 gate: {name}"
            for name, passed in gate_checks.items()
            if not passed
        ],
    }

    result = {
        "stage": "step1_baseline",
        "generated_at": manifest["generated_at"],
        "project_dir": str(BASE_DIR),
        "data_dir": str(data_dir),
        "report_root": str(root.resolve()),
        "report_root_source": root_source,
        "output_dir": str(output_dir),
        "baseline_command": baseline_command,
        "hashes": {
            "source_tree_sha256": source_hash,
            "data_tree_sha256": data_tree_hash,
            "data_files": data_hashes,
            "config_sha256": config_hash,
            "registry_ontology_sha256": registry_hash,
            "registry_version": "UNVERSIONED_PARTIAL_REGISTRIES",
            "submission_sha256": manifest["submission_sha256"],
            "official_schema_sha256": sha256_file(find_schema_path(data_dir)),
            "local_schema_sha256": sha256_file(
                BASE_DIR / "submission_schema.json"
            ),
        },
        "dev": dev,
        "tests": tests,
        "existing_artifacts": existing_artifacts,
        "generated_artifact_validation": artifact_validation,
        "reference_manifest_validation": reference_validation,
        "screening_answers": len(screening_payload["answers"]),
        "assumptions": assumptions,
        "release_gate": release_gate,
    }
    (output_dir / "baseline_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "STEP1_REPORT.md").write_text(
        build_stage_report(result), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
