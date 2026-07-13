from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from local_score import score_answer
from run_submission import run_tasks
from utils.io import find_data_dir, load_jsonl


BASE_DIR = Path(__file__).resolve().parent
AXES = ("focal", "target", "control", "content_scope", "policy", "plan")


def analyze_errors() -> list[dict[str, Any]]:
    data_dir = find_data_dir()
    tasks = load_jsonl(data_dir / "dev_tasks.jsonl")
    reference_payload = json.loads((data_dir / "dev_answers.json").read_text(encoding="utf-8"))
    refs = reference_payload["answers"]
    public_values = set(reference_payload["plan_arg_ontology"]["values"])
    payload = run_tasks(tasks)
    traces = {trace["task_id"]: trace for trace in payload.get("_traces", [])}
    task_map = {str(task["id"]): task for task in tasks}

    cases: list[dict[str, Any]] = []
    for task_id, reference in refs.items():
        pred = payload["answers"][task_id]
        scores = score_answer(pred, reference, public_values)
        bad_axes = [axis for axis in AXES if scores[axis] < 1.0]
        if not bad_axes:
            continue
        task = task_map[task_id]
        cases.append(
            {
                "task_id": task_id,
                "bad_axes": bad_axes,
                "scores": {axis: round(scores[axis], 4) for axis in AXES},
                "expected": {
                    "focal_id": reference.get("focal_id"),
                    "target": reference.get("target"),
                    "control": reference.get("control"),
                    "content_scope": reference.get("content_scope"),
                    "policy": reference.get("policy"),
                    "plan_events": reference.get("expected_events"),
                },
                "actual": pred,
                "record_types": sorted(
                    str(record.get("type"))
                    for record in (task.get("device_state") or {}).get("records", [])
                ),
                "trace": traces.get(task_id, {}),
            }
        )

    reports = BASE_DIR / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    with (reports / "error_cases.jsonl").open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n")
    counts = Counter(axis for case in cases for axis in case["bad_axes"])
    print(json.dumps({"cases": len(cases), "axis_counts": counts}, ensure_ascii=False, indent=2))
    return cases


if __name__ == "__main__":
    analyze_errors()
