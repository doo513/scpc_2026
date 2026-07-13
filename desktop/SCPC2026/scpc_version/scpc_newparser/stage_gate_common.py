from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Iterable

from build_manifest import sha256_file
from core.consistency import ConsistencyValidator
from run_submission import run_tasks, write_submission
from step1_baseline import evaluate_dev, run_command
from utils.diff import compare_submissions
from utils.io import find_data_dir, load_jsonl
from validate_submission import validate_submission


KNOWN_DEV_FAILURE = "tests/test_regression.py::test_dev_score_and_optional_fields"


@dataclass(frozen=True)
class PreviousStageSpec:
    stage: str
    directory_name: str
    result_filename: str


def archive_failed_attempt(
    output_dir: Path,
    *,
    result_filename: str,
    report_filename: str,
) -> None:
    result_path = output_dir / result_filename
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
    report_path = output_dir / report_filename
    if report_path.is_file():
        (attempts_dir / f"attempt_{index:03d}_report.md").write_bytes(
            report_path.read_bytes()
        )


def resolve_previous_stage(
    report_root: Path,
    spec: PreviousStageSpec,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    candidates = (
        report_root / spec.directory_name,
        report_root / "op_reports" / spec.directory_name,
    )
    errors: list[str] = []
    for directory in candidates:
        result_path = directory / spec.result_filename
        submission_path = directory / "submission.csv"
        manifest_path = directory / "stage_manifest.json"
        if not result_path.is_file():
            continue
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            manifest = (
                json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.is_file()
                else {}
            )
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{directory}: {exc}")
            continue
        checks = {
            "stage_name": result.get("stage") == spec.stage,
            "release_gate": bool(
                result.get("release_gate", {}).get("next_stage_allowed")
            ),
            "submission_present": submission_path.is_file(),
            "submission_hash": (
                submission_path.is_file()
                and result.get("screening_submission_sha256")
                == sha256_file(submission_path)
            ),
            "manifest_present": manifest_path.is_file(),
            "manifest_submission_hash": (
                manifest.get("artifacts", {}).get("submission.csv")
                == result.get("screening_submission_sha256")
            ),
            "result_manifest_hash": (
                manifest.get("artifacts", {}).get(spec.result_filename)
                == sha256_file(result_path)
            ),
        }
        integrity = {
            "resolved_directory": str(directory.resolve()),
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
        report_root / spec.directory_name,
        {},
        {
            "resolved_directory": "",
            "checks": {},
            "errors": errors or [f"{spec.stage} result not found"],
        },
    )


def run_standard_regression(
    output_dir: Path,
    *,
    stage_test_files: Iterable[str],
    previous_dir: Path,
    previous_result: dict[str, Any],
) -> dict[str, Any]:
    tests = {
        "stage_specific": run_command(
            [sys.executable, "-m", "pytest", "-q", *stage_test_files],
            output_dir / "pytest_stage.log",
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
    dev, diagnostics = evaluate_dev()
    (output_dir / "dev_error_distribution.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    data_dir = find_data_dir()
    payload = run_tasks(load_jsonl(data_dir / "screening_tasks.jsonl"))
    submission_path = output_dir / "submission.csv"
    write_submission(payload, submission_path)
    validate_submission(submission_path)
    ConsistencyValidator.write_report(output_dir / "consistency_report.md")
    previous_submission = previous_dir / "submission.csv"
    submission_unchanged = previous_submission.is_file() and sha256_file(
        previous_submission
    ) == sha256_file(submission_path)
    shadow_diff_path = output_dir / "shadow_diff_vs_previous.md"
    if previous_submission.is_file():
        shadow_diff_path.write_text(
            compare_submissions(previous_submission, submission_path) + "\n",
            encoding="utf-8",
        )
    return {
        "tests": tests,
        "dev": dev,
        "dev_unchanged": previous_result.get("dev") == dev,
        "submission_path": submission_path,
        "submission_sha256": sha256_file(submission_path),
        "submission_unchanged": submission_unchanged,
        "shadow_diff_path": shadow_diff_path,
    }


def standard_regression_checks(result: dict[str, Any]) -> dict[str, bool]:
    tests = result["tests"]
    return {
        "stage_specific_tests": tests["stage_specific"]["exit_code"] == 0,
        "without_known_dev_gate": tests["without_known_dev_gate"]["exit_code"] == 0,
        "only_known_full_test_failure": (
            tests["full"]["exit_code"] == 1
            and tests["full"]["failed_tests"] == [KNOWN_DEV_FAILURE]
        ),
        "dev_unchanged": result["dev_unchanged"],
        "screening_submission_unchanged": result["submission_unchanged"],
    }


def write_stage_manifest(
    output_dir: Path,
    *,
    stage: str,
    source_hash: str,
    artifact_paths: Iterable[Path],
) -> Path:
    data_dir = find_data_dir()
    manifest = {
        "stage": stage,
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
