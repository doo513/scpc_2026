from __future__ import annotations

import hashlib
import json
import csv
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable

from official_baseline import find_official_notebook
from utils.io import (
    OFFICIAL_DATA_FILES,
    find_baseline_submission,
    find_data_dir,
    find_official_archive,
)


BASE_DIR = Path(__file__).resolve().parent
MANIFEST_SCHEMA = "scpc.artifact-manifest.v2"
MANIFEST_PRODUCER = "build_manifest.publish_candidate_manifest"
AUTHORITATIVE_MANIFEST_PATH = BASE_DIR / "manifest" / "candidate_manifest.json"
FIXED_SLM_STATUS_PATH = BASE_DIR / "manifest" / "fixed_slm_status.json"
REPRODUCIBLE_ARTIFACTS = (
    "reports/dev_score_report.md",
    "reports/decision_trace.jsonl",
    "reports/consistency_report.md",
    "reports/screening_structural_report.md",
    "reports/diff_vs_baseline.md",
    "reports/error_cases.jsonl",
    "reports/stage3_fixed_slm_report.md",
    "reports/release_gate_report.json",
    "reports/release_gate_report.md",
)
VOLATILE_JSON_FIELDS = frozenset({"generated_at"})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _without_volatile_json_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_volatile_json_fields(item)
            for key, item in value.items()
            if key not in VOLATILE_JSON_FIELDS
        }
    if isinstance(value, list):
        return [_without_volatile_json_fields(item) for item in value]
    return value


def artifact_content_hash(path: Path) -> str:
    """Hash semantic artifact content, excluding declared volatile JSON fields."""
    if path.suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        return _canonical_hash(_without_volatile_json_fields(value))
    return sha256_file(path)


def source_tree_hash(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        relative = path.relative_to(BASE_DIR).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def external_tree_hash(root: Path, paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def source_files() -> list[Path]:
    roots = [BASE_DIR / "core", BASE_DIR / "rules", BASE_DIR / "utils", BASE_DIR / "tests"]
    files = [path for root in roots for path in root.rglob("*.py")]
    files.extend((BASE_DIR / "tests" / "specs").rglob("*.json"))
    files.extend(BASE_DIR.glob("*.py"))
    files.extend(
        path
        for path in (
            BASE_DIR / "README.md",
            BASE_DIR / "requirements.txt",
            BASE_DIR / "submission_schema.json",
            BASE_DIR / ".gitignore",
        )
        if path.is_file()
    )
    return files


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def manifest_content_fingerprint(manifest: dict[str, Any]) -> str:
    stable = {
        key: value
        for key, value in manifest.items()
        if key not in {"generated_at", "content_fingerprint_sha256"}
    }
    return _canonical_hash(stable)


def official_archive_path() -> Path | None:
    """Return only the official archive vendored at the workspace root."""
    return find_official_archive()


def _fixed_slm_status() -> dict[str, Any]:
    if not FIXED_SLM_STATUS_PATH.is_file():
        raise FileNotFoundError(
            f"FixedSLM promotion decision missing: {FIXED_SLM_STATUS_PATH}"
        )
    status = json.loads(FIXED_SLM_STATUS_PATH.read_text(encoding="utf-8"))
    decision = status.get("decision")
    if decision not in {"PROMOTE", "KEEP_SHADOW", "REMOVE"}:
        raise ValueError("FixedSLM decision must be PROMOTE, KEEP_SHADOW, or REMOVE")
    if decision != "PROMOTE" and status.get("production_influence") is not False:
        raise ValueError("unpromoted FixedSLM must have zero production influence")
    return status


def _default_artifacts() -> tuple[Path, ...]:
    candidates = tuple(BASE_DIR / relative for relative in REPRODUCIBLE_ARTIFACTS)
    return tuple(path for path in candidates if path.is_file())


def build_candidate_manifest_payload(
    dev_result: dict[str, Any],
    submission_path: Path,
    *,
    artifact_paths: Iterable[Path] | None = None,
) -> dict[str, Any]:
    data_dir = find_data_dir()
    baseline_submission = find_baseline_submission()
    baseline_notebook = find_official_notebook()
    data_files = {
        name: sha256_file(data_dir / name)
        for name in OFFICIAL_DATA_FILES
    }
    csv.field_size_limit(20_000_000)
    with submission_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader)
        answer_count = len(json.loads(next(reader)[0]).get("answers", {}))
    fixed_slm = _fixed_slm_status()
    archive = official_archive_path()
    artifacts = tuple(artifact_paths) if artifact_paths is not None else _default_artifacts()
    artifact_hashes = {
        path.relative_to(BASE_DIR).as_posix(): artifact_content_hash(path)
        for path in sorted(artifacts, key=lambda item: item.as_posix())
        if path.is_file() and path.is_relative_to(BASE_DIR)
    }
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "producer": MANIFEST_PRODUCER,
        "candidate": "scpc_reparser_authoritative_pipeline",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_tree_sha256": source_tree_hash(source_files()),
        "data_sha256": data_files,
        "baseline_submission_sha256": sha256_file(baseline_submission),
        "official_baseline_notebook_sha256": sha256_file(
            baseline_notebook
        ),
        "official_archive_sha256": sha256_file(archive) if archive else None,
        "scorer": {
            "implementation": "local_score.py",
            "sha256": sha256_file(BASE_DIR / "local_score.py"),
            "official_notebook_rule": "strict-first-best-tie",
        },
        "submission_sha256": sha256_file(submission_path),
        "submission_answers": answer_count,
        "artifacts": artifact_hashes,
        "dev": dev_result,
        "fixed_slm": {
            "decision": fixed_slm["decision"],
            "production_influence": fixed_slm["production_influence"],
            "status_path": FIXED_SLM_STATUS_PATH.relative_to(BASE_DIR).as_posix(),
            "status_sha256": sha256_file(FIXED_SLM_STATUS_PATH),
        },
        "contract": {
            "schema": "scpc.final.answer.v1",
            "uses_external_api": False,
            "fixed_slm_policy": "local_fixed_slm_only",
        },
        "reproduction": {
            "submission": "python run_submission.py --output submission.csv",
            "report_bundle": "python generate_reports.py, then python release_gate.py",
            "validation": "python validate_artifacts.py --reproduce",
        },
        "notes": [
            "screening distributions are diagnostic only",
            "semantic_response is not locally scoreable from public references",
            "official dev score includes every task without regression exclusions",
            "missing persistent memory values never trigger person- or task-specific target defaults",
            "generated_at is informational and is never freshness evidence",
        ],
    }
    manifest["content_fingerprint_sha256"] = manifest_content_fingerprint(manifest)
    return manifest


def publish_candidate_manifest(
    dev_result: dict[str, Any],
    submission_path: Path,
    *,
    output_path: Path | None = None,
    artifact_paths: Iterable[Path] | None = None,
) -> dict[str, Any]:
    """The sole candidate-manifest writer.

    Callers may request publication, but must not construct or write an
    independent candidate-manifest shape.
    """
    manifest = build_candidate_manifest_payload(
        dev_result,
        submission_path,
        artifact_paths=artifact_paths,
    )
    output = output_path or AUTHORITATIVE_MANIFEST_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    with tempfile.NamedTemporaryFile(
        dir=output.parent,
        prefix=f".{output.name}.",
        delete=False,
    ) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    os.replace(temporary, output)
    return manifest


def promote_validated_candidate_manifest(
    staged_path: Path,
    validation_result: dict[str, Any],
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Atomically promote a staged manifest only after content validation."""
    manifest = json.loads(staged_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("staged candidate manifest has the wrong schema")
    if manifest.get("producer") != MANIFEST_PRODUCER:
        raise ValueError("staged candidate manifest has the wrong producer")
    fingerprint = manifest_content_fingerprint(manifest)
    if manifest.get("content_fingerprint_sha256") != fingerprint:
        raise ValueError("staged candidate manifest fingerprint is invalid")
    if validation_result.get("manifest_content_fingerprint_sha256") != fingerprint:
        raise ValueError("staged candidate manifest was not the validated content")
    output = output_path or AUTHORITATIVE_MANIFEST_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged_path, output)
    return manifest


def build_manifest(dev_result: dict[str, Any], submission_path: Path) -> dict[str, Any]:
    """Compatibility entry point delegated to the sole publisher."""
    return publish_candidate_manifest(dev_result, submission_path)


def write_reference_manifest() -> dict[str, Any]:
    data_dir = find_data_dir()
    baseline_submission = find_baseline_submission()
    baseline_notebook = find_official_notebook()
    spec = json.loads(
        (BASE_DIR / "tests" / "specs" / "generalization_v1.json").read_text(
            encoding="utf-8"
        )
    )
    legacy = spec["legacy_reference"]
    manifest = {
        "official_data": {
            name: sha256_file(data_dir / name)
            for name in OFFICIAL_DATA_FILES
        },
        "baseline": {
            "name": "baseline_v5_compatible_actionprofile",
            "dev_overall": legacy["dev_overall"],
            "focal": legacy["dev_focal"],
            "target": legacy["dev_target"],
            "control": legacy["dev_control"],
            "source_tree_sha256": spec["baseline_source_tree_sha256"],
            "source_tree_hash_status": "PINNED_REFERENCE_NOT_REPRODUCED",
        },
        "report_baseline": {
            "name": "official_notebook_baseline",
            "notebook_sha256": sha256_file(baseline_notebook),
            "submission_sha256": sha256_file(baseline_submission),
        },
    }
    archive = official_archive_path()
    if archive is not None:
        manifest["official_archive_sha256"] = sha256_file(archive)
    output = BASE_DIR / "manifest" / "reference_manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest
