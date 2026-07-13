from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_manifest import sha256_file, source_files, source_tree_hash
from utils.io import find_data_dir
from validate_submission import find_schema_path, validate_submission


BASE_DIR = Path(__file__).resolve().parent


def validate_current_artifacts(
    submission_path: Path | None = None,
    manifest_path: Path | None = None,
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
    current_sources = source_files()
    current_source_hash = source_tree_hash(current_sources)
    manifest_source_hash = str(manifest.get("source_tree_sha256") or "")
    if current_source_hash != manifest_source_hash:
        raise ValueError("candidate manifest source hash is stale")

    submission_hash = sha256_file(submission_path)
    if submission_hash != manifest.get("submission_sha256"):
        raise ValueError("candidate manifest submission hash is stale")

    newest_source_mtime_ns = max(
        path.stat().st_mtime_ns for path in current_sources
    )
    submission_mtime_ns = submission_path.stat().st_mtime_ns
    if submission_mtime_ns < newest_source_mtime_ns:
        raise ValueError("submission predates a source or test file")

    data_dir = find_data_dir()
    official_schema = find_schema_path(data_dir)
    local_schema = BASE_DIR / "submission_schema.json"
    if not official_schema.is_file():
        raise FileNotFoundError(f"official schema missing: {official_schema}")
    if sha256_file(official_schema) != sha256_file(local_schema):
        raise ValueError("local submission schema differs from official schema")

    payload = validate_submission(submission_path)
    return {
        "answers": len(payload.get("answers") or {}),
        "source_tree_sha256": current_source_hash,
        "submission_sha256": submission_hash,
        "official_schema_sha256": sha256_file(official_schema),
        "newest_source_mtime_ns": newest_source_mtime_ns,
        "submission_mtime_ns": submission_mtime_ns,
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
    args = parser.parse_args()
    result = validate_current_artifacts(args.submission, args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
