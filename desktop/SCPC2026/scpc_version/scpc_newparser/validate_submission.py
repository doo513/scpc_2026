from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from utils.io import find_data_dir, load_jsonl
from utils.schema_check import validate_answer


BASE_DIR = Path(__file__).resolve().parent


def find_schema_path(data_dir: Path) -> Path:
    candidates = (
        data_dir / "submission_schema.json",
        data_dir.parent / "submission_schema.json",
        BASE_DIR / "submission_schema.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("submission_schema.json not found")


def load_submission(path: Path) -> dict[str, Any]:
    csv.field_size_limit(20_000_000)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if len(rows) != 2:
        raise ValueError(f"CSV must contain one header and one data row; got {len(rows)} rows")
    if rows[0] != ["submission"] or len(rows[1]) != 1:
        raise ValueError("CSV must be a single 'submission' column")
    payload = json.loads(rows[1][0])
    if not isinstance(payload, dict):
        raise ValueError("submission cell must contain a JSON object")
    return payload


def validate_submission(path: Path) -> dict[str, Any]:
    data_dir = find_data_dir()
    payload = load_submission(path)
    schema = json.loads(find_schema_path(data_dir).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        raise ValueError("official schema validation failed: " + "; ".join(error.message for error in errors[:5]))

    meta = payload.get("meta") or {}
    if meta.get("uses_external_api") is not False:
        raise ValueError("meta.uses_external_api must be false")
    if meta.get("fixed_slm_policy") != "local_fixed_slm_only":
        raise ValueError("meta.fixed_slm_policy must be local_fixed_slm_only")
    if meta.get("model_id") != "scpc-final-fixed-slm-local-facade":
        raise ValueError("unexpected meta.model_id")

    tasks = load_jsonl(data_dir / "screening_tasks.jsonl")
    expected_ids = {str(task["id"]) for task in tasks}
    answers = payload.get("answers") or {}
    missing, extra = expected_ids - set(answers), set(answers) - expected_ids
    if missing or extra:
        raise ValueError(f"answer IDs mismatch: missing={len(missing)} extra={len(extra)}")
    for answer in answers.values():
        validate_answer(answer)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=BASE_DIR / "submission.csv")
    args = parser.parse_args()
    payload = validate_submission(args.path)
    print(f"validation succeeded: {args.path} ({len(payload['answers'])} answers)")


if __name__ == "__main__":
    main()
