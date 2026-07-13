from __future__ import annotations

import hashlib
import json
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from utils.io import find_data_dir


BASE_DIR = Path(__file__).resolve().parent


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def build_manifest(dev_result: dict[str, Any], submission_path: Path) -> dict[str, Any]:
    data_dir = find_data_dir()
    data_files = {
        name: sha256_file(data_dir / name)
        for name in ("dev_tasks.jsonl", "dev_answers.json", "screening_tasks.jsonl")
    }
    csv.field_size_limit(20_000_000)
    with submission_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader)
        answer_count = len(json.loads(next(reader)[0]).get("answers", {}))
    manifest = {
        "candidate": "scpc_coparser_final_decision",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_tree_sha256": source_tree_hash(source_files()),
        "data_sha256": data_files,
        "submission_sha256": sha256_file(submission_path),
        "submission_answers": answer_count,
        "dev": dev_result,
        "contract": {
            "schema": "scpc.final.answer.v1",
            "uses_external_api": False,
            "fixed_slm_policy": "local_fixed_slm_only",
        },
        "notes": [
            "screening distributions are diagnostic only",
            "semantic_response is not locally scoreable from public references",
            "official dev score includes every task without regression exclusions",
            "missing persistent memory values never trigger person- or task-specific target defaults",
        ],
    }
    output = BASE_DIR / "manifest" / "candidate_manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def write_reference_manifest() -> dict[str, Any]:
    data_dir = find_data_dir()
    manifest = {
        "official_data": {
            name: sha256_file(data_dir / name)
            for name in ("dev_tasks.jsonl", "dev_answers.json", "screening_tasks.jsonl")
        },
        "baseline": {
            "name": "baseline_v5_compatible_actionprofile",
            "dev_overall": 0.9468,
            "focal": 1.0,
            "target": 1.0,
            "control": 1.0,
        },
    }
    baseline_root = (
        BASE_DIR.parent
        / "scpc_Gparser"
        / "baseline_v5_compatible_actionprofile"
    )
    if baseline_root.is_dir():
        baseline_files = [
            path
            for path in baseline_root.rglob("*.py")
            if "__pycache__" not in path.parts
        ]
        manifest["baseline"]["source_tree_sha256"] = external_tree_hash(
            baseline_root, baseline_files
        )
    archive_candidates = (
        BASE_DIR / "SCPC2026_Final_data.zip",
        BASE_DIR.parent / "data" / "SCPC2026_Final_data.zip",
    )
    for archive in archive_candidates:
        if archive.is_file():
            manifest["official_archive_sha256"] = sha256_file(archive)
            break
    output = BASE_DIR / "manifest" / "reference_manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest
