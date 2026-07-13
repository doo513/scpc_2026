from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from build_manifest import (
    FIXED_SLM_STATUS_PATH,
    MANIFEST_PRODUCER,
    MANIFEST_SCHEMA,
    REPRODUCIBLE_ARTIFACTS,
    artifact_content_hash,
    manifest_content_fingerprint,
    official_archive_path,
    sha256_file,
    source_files,
    source_tree_hash,
)
from official_baseline import find_official_notebook
from utils.io import (
    OFFICIAL_DATA_FILES,
    find_baseline_submission,
    find_data_dir,
    load_jsonl,
)
from validate_submission import find_schema_path, validate_submission


BASE_DIR = Path(__file__).resolve().parent
REPRODUCTION_ROOT = BASE_DIR / ".reproduction"


@contextmanager
def _temporary_reproduction_directory(prefix: str):
    REPRODUCTION_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix=prefix,
            dir=REPRODUCTION_ROOT,
        ) as directory:
            yield Path(directory)
    finally:
        try:
            REPRODUCTION_ROOT.rmdir()
        except OSError:
            pass


def _copy_workspace_snapshot(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    excluded = {
        ".reproduction",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
    }
    nested_ignore = shutil.ignore_patterns(
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "*.pyc",
        ".candidate_manifest.*",
    )
    for source in tuple(BASE_DIR.iterdir()):
        if source.name in excluded or source.name.startswith(
            ".candidate_manifest."
        ):
            continue
        target = destination / source.name
        if source.is_dir():
            shutil.copytree(source, target, ignore=nested_ignore)
        elif source.is_file():
            shutil.copy2(source, target)


def validate_current_artifacts(
    submission_path: Path | None = None,
    manifest_path: Path | None = None,
    *,
    reproduce: bool = False,
    reproduce_reports: bool = True,
    require_complete_reports: bool = True,
) -> dict[str, Any]:
    submission_path = submission_path or BASE_DIR / "submission.csv"
    manifest_path = (
        manifest_path or BASE_DIR / "manifest" / "candidate_manifest.json"
    )
    if not submission_path.is_file():
        raise FileNotFoundError(f"submission missing: {submission_path}")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"candidate manifest missing: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("candidate manifest schema is not authoritative v2")
    if manifest.get("producer") != MANIFEST_PRODUCER:
        raise ValueError("candidate manifest has a non-authoritative producer")
    expected_fingerprint = manifest_content_fingerprint(manifest)
    if manifest.get("content_fingerprint_sha256") != expected_fingerprint:
        raise ValueError("candidate manifest content fingerprint is stale")

    current_sources = source_files()
    current_source_hash = source_tree_hash(current_sources)
    manifest_source_hash = str(manifest.get("source_tree_sha256") or "")
    if current_source_hash != manifest_source_hash:
        raise ValueError("candidate manifest source hash is stale")

    submission_hash = sha256_file(submission_path)
    if submission_hash != manifest.get("submission_sha256"):
        raise ValueError("candidate manifest submission hash is stale")

    data_dir = find_data_dir()
    baseline_submission = find_baseline_submission()
    baseline_notebook = find_official_notebook()
    actual_data_hashes = {
        name: sha256_file(data_dir / name)
        for name in OFFICIAL_DATA_FILES
    }
    if manifest.get("data_sha256") != actual_data_hashes:
        raise ValueError("candidate manifest official-data hash is stale")
    if manifest.get("baseline_submission_sha256") != sha256_file(
        baseline_submission
    ):
        raise ValueError("candidate manifest baseline-submission hash is stale")
    if manifest.get("official_baseline_notebook_sha256") != sha256_file(
        baseline_notebook
    ):
        raise ValueError("candidate manifest official-baseline hash is stale")

    scorer = manifest.get("scorer") or {}
    if scorer.get("sha256") != sha256_file(BASE_DIR / "local_score.py"):
        raise ValueError("candidate manifest scorer hash is stale")

    archive = official_archive_path()
    actual_archive_hash = sha256_file(archive) if archive is not None else None
    if manifest.get("official_archive_sha256") != actual_archive_hash:
        raise ValueError("candidate manifest official-archive hash is stale")

    fixed_slm = manifest.get("fixed_slm") or {}
    fixed_status = json.loads(FIXED_SLM_STATUS_PATH.read_text(encoding="utf-8"))
    if fixed_slm.get("status_sha256") != sha256_file(FIXED_SLM_STATUS_PATH):
        raise ValueError("candidate manifest FixedSLM status hash is stale")
    if fixed_slm.get("decision") != fixed_status.get("decision"):
        raise ValueError("candidate manifest FixedSLM decision is stale")
    if fixed_slm.get("production_influence") != fixed_status.get(
        "production_influence"
    ):
        raise ValueError("candidate manifest FixedSLM influence is stale")
    if (
        fixed_status.get("decision") != "PROMOTE"
        and fixed_status.get("production_influence") is not False
    ):
        raise ValueError("unpromoted FixedSLM influences production evidence")

    artifact_hashes = manifest.get("artifacts") or {}
    if not isinstance(artifact_hashes, dict):
        raise ValueError("candidate manifest artifacts must be an object")
    if require_complete_reports and set(artifact_hashes) != set(
        REPRODUCIBLE_ARTIFACTS
    ):
        missing = sorted(set(REPRODUCIBLE_ARTIFACTS) - set(artifact_hashes))
        extra = sorted(set(artifact_hashes) - set(REPRODUCIBLE_ARTIFACTS))
        raise ValueError(
            "candidate manifest report set is incomplete "
            f"missing={missing} extra={extra}"
        )
    for relative, expected_hash in artifact_hashes.items():
        artifact = (BASE_DIR / relative).resolve()
        if not artifact.is_relative_to(BASE_DIR.resolve()):
            raise ValueError(f"manifest artifact escapes workspace: {relative}")
        if not artifact.is_file():
            raise FileNotFoundError(f"manifest artifact missing: {artifact}")
        if artifact_content_hash(artifact) != expected_hash:
            raise ValueError(f"manifest artifact content is stale: {relative}")

    official_schema = find_schema_path(data_dir)
    local_schema = BASE_DIR / "submission_schema.json"
    if not official_schema.is_file():
        raise FileNotFoundError(f"official schema missing: {official_schema}")
    if sha256_file(official_schema) != sha256_file(local_schema):
        raise ValueError("local submission schema differs from official schema")

    payload = validate_submission(submission_path)
    result: dict[str, Any] = {
        "answers": len(payload.get("answers") or {}),
        "source_tree_sha256": current_source_hash,
        "submission_sha256": submission_hash,
        "official_schema_sha256": sha256_file(official_schema),
        "manifest_content_fingerprint_sha256": expected_fingerprint,
        "data_sha256": actual_data_hashes,
        "baseline_submission_sha256": sha256_file(baseline_submission),
        "official_baseline_notebook_sha256": sha256_file(
            baseline_notebook
        ),
        "scorer_sha256": scorer["sha256"],
        "fixed_slm_decision": fixed_status["decision"],
        "timestamp_used_for_freshness": False,
    }
    if reproduce:
        result["reproduction"] = reproduce_current_artifacts(
            submission_path,
            manifest,
        )
        if reproduce_reports:
            result["report_reproduction"] = reproduce_report_artifacts(manifest)
    return result


def reproduce_current_artifacts(
    submission_path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Regenerate submission and dev metrics without overwriting workspace artifacts."""
    from local_score import evaluate_dev_payload
    from run_submission import run_tasks, write_submission

    data_dir = find_data_dir()
    screening_tasks = load_jsonl(data_dir / "screening_tasks.jsonl")
    dev_tasks = load_jsonl(data_dir / "dev_tasks.jsonl")
    references = json.loads(
        (data_dir / "dev_answers.json").read_text(encoding="utf-8")
    )
    with _temporary_reproduction_directory(
        "artifact-"
    ) as directory:
        regenerated = directory / "submission.csv"
        write_submission(run_tasks(screening_tasks), regenerated)
        regenerated_hash = sha256_file(regenerated)
    dev, _diagnostics = evaluate_dev_payload(run_tasks(dev_tasks), references)
    submission_match = regenerated_hash == sha256_file(submission_path)
    dev_match = dev == manifest.get("dev")
    if not submission_match:
        raise ValueError("isolated submission regeneration differs from manifest artifact")
    if not dev_match:
        raise ValueError("isolated dev regeneration differs from manifest metrics")
    return {
        "submission_sha256": regenerated_hash,
        "submission_byte_identical": submission_match,
        "dev_metrics_identical": dev_match,
        "dev_overall": dev["overall"],
    }


def _run_report_producer(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    accepted_exit_codes: set[int],
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode not in accepted_exit_codes:
        tail = completed.stdout[-8_000:]
        raise RuntimeError(
            f"report reproduction failed ({completed.returncode}): "
            f"{' '.join(command)}\n{tail}"
        )
    return completed


def reproduce_report_artifacts(manifest: dict[str, Any]) -> dict[str, Any]:
    """Rebuild every published report in an isolated workspace and compare content."""
    expected_artifacts = manifest.get("artifacts") or {}
    if set(expected_artifacts) != set(REPRODUCIBLE_ARTIFACTS):
        raise ValueError("full report reproduction requires the authoritative report set")

    data_dir = find_data_dir().resolve()
    baseline_submission = find_baseline_submission().resolve()
    workspace = BASE_DIR.resolve()
    data_relative = data_dir.relative_to(workspace)
    baseline_relative = baseline_submission.relative_to(workspace)

    with _temporary_reproduction_directory("reports-") as temporary_root:
        clone = temporary_root / "workspace"
        _copy_workspace_snapshot(clone)

        env = os.environ.copy()
        env["SCPC_DATA_DIR"] = str(clone / data_relative)
        env["SCPC_BASELINE_SUBMISSION"] = str(clone / baseline_relative)
        env["PYTHONPYCACHEPREFIX"] = str(temporary_root / "pycache")

        _run_report_producer(
            [sys.executable, "generate_reports.py", "--reproduction-child"],
            cwd=clone,
            env=env,
            accepted_exit_codes={0},
        )
        release = _run_report_producer(
            [sys.executable, "release_gate.py", "--reproduction-child"],
            cwd=clone,
            env=env,
            accepted_exit_codes={0, 1},
        )

        reproduced_manifest_path = clone / "manifest" / "candidate_manifest.json"
        reproduced_manifest = json.loads(
            reproduced_manifest_path.read_text(encoding="utf-8")
        )
        reproduced_artifacts = reproduced_manifest.get("artifacts") or {}
        if set(reproduced_artifacts) != set(REPRODUCIBLE_ARTIFACTS):
            raise ValueError("reproduced manifest report set is incomplete")

        actual_hashes: dict[str, str] = {}
        for relative in REPRODUCIBLE_ARTIFACTS:
            regenerated = clone / relative
            actual_hash = artifact_content_hash(regenerated)
            actual_hashes[relative] = actual_hash
            if actual_hash != expected_artifacts[relative]:
                raise ValueError(
                    f"isolated report regeneration differs from manifest: {relative}"
                )
            if reproduced_artifacts.get(relative) != actual_hash:
                raise ValueError(
                    f"reproduced manifest did not bind report content: {relative}"
                )

        expected_fingerprint = manifest.get("content_fingerprint_sha256")
        reproduced_fingerprint = reproduced_manifest.get(
            "content_fingerprint_sha256"
        )
        if reproduced_fingerprint != expected_fingerprint:
            raise ValueError(
                "isolated report regeneration produced a different manifest fingerprint"
            )

    return {
        "artifacts_compared": len(actual_hashes),
        "artifact_content_sha256": actual_hashes,
        "report_contents_identical": True,
        "manifest_content_fingerprint_identical": True,
        "release_gate_exit_code": release.returncode,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--submission", type=Path, default=BASE_DIR / "submission.csv"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=BASE_DIR / "manifest" / "candidate_manifest.json",
    )
    parser.add_argument(
        "--reproduce",
        action="store_true",
        help="regenerate submission and dev metrics in isolation and compare content",
    )
    args = parser.parse_args()
    result = validate_current_artifacts(
        args.submission,
        args.manifest,
        reproduce=args.reproduce,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
