from __future__ import annotations

import argparse
import copy
import csv
from itertools import groupby
import json
from pathlib import Path
from typing import Any

from core.consistency import ConsistencyValidator
from core.spec import FIXED_META
from core.task_view import TaskView
from harness import FinalHarness
from utils.io import find_data_dir, load_jsonl


SUBMISSION_SCHEMA = "scpc.final.answer.v1"
BASE_DIR = Path(__file__).resolve().parent


def participant_task_view(task: dict[str, Any]) -> dict[str, Any]:
    view = json.loads(json.dumps(task, ensure_ascii=False))
    for key in list(view):
        if (
            key in {"expected_events", "answer"}
            or key.startswith("expected_")
            or key.endswith(("_brief", "_notes", "_rubric", "_keywords", "_tags"))
        ):
            view.pop(key, None)
    return view


def run_tasks(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    harness = FinalHarness()
    harness.prepare([])
    sessions: dict[str, dict[str, Any]] = {}
    answers: dict[str, dict[str, Any]] = {}
    traces: list[dict[str, Any]] = []

    ConsistencyValidator.reset()
    ordered = sorted(
        tasks,
        key=lambda task: (
            str(task.get("session_id", "")),
            int(task.get("turn_index", 0)),
            str(task.get("id", "")),
        ),
    )
    for (session_id, turn_index), grouped_tasks in groupby(
        ordered,
        key=lambda task: (
            str(task.get("session_id", "")),
            int(task.get("turn_index", 0)),
        ),
    ):
        siblings = list(grouped_tasks)
        session = sessions.setdefault(session_id, {})
        base_session = copy.deepcopy(session)
        branch_isolated = len(siblings) > 1
        for task in siblings:
            visible_task = participant_task_view(task)
            evaluation_session = (
                copy.deepcopy(base_session) if branch_isolated else session
            )
            validation_view = TaskView(visible_task, evaluation_session)
            raw_answer = harness.answer_task(
                visible_task,
                evaluation_session,
                commit=not branch_isolated,
            )
            trace = raw_answer.get("_trace")
            if isinstance(trace, dict):
                trace["session_lifecycle"] = {
                    "session_id": session_id,
                    "turn_index": turn_index,
                    "sibling_count": len(siblings),
                    "commit_status": (
                        "isolated_uncommitted_branch"
                        if branch_isolated
                        else "committed"
                    ),
                }
                traces.append(trace)
            answer = {
                key: value
                for key, value in raw_answer.items()
                if not key.startswith("_")
            }
            ConsistencyValidator.validate_or_warn(
                answer,
                validation_view,
                trace,
                trace,
            )
            answers[str(task["id"])] = answer

    payload = {
        "schema": SUBMISSION_SCHEMA,
        "meta": {
            "harness_name": "scpc_coparser_final_decision",
            **FIXED_META,
        },
        "answers": answers,
        "_traces": traces,
    }
    _validate_payload(payload, {str(task["id"]) for task in tasks})
    return payload


def _validate_payload(payload: dict[str, Any], expected_ids: set[str]) -> None:
    if payload.get("schema") != SUBMISSION_SCHEMA:
        raise ValueError("bad schema")
    meta = payload.get("meta") or {}
    if meta.get("uses_external_api") is not False:
        raise ValueError("meta.uses_external_api must be false")
    if meta.get("fixed_slm_policy") != "local_fixed_slm_only":
        raise ValueError("bad fixed_slm_policy")
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise ValueError("answers missing")
    missing, extra = expected_ids - set(answers), set(answers) - expected_ids
    if missing or extra:
        raise ValueError(f"answer id mismatch missing={len(missing)} extra={len(extra)}")


def write_submission(payload: dict[str, Any], output_path: Path) -> None:
    public_payload = {key: value for key, value in payload.items() if not key.startswith("_")}
    public_payload["answers"] = {
        task_id: public_payload["answers"][task_id]
        for task_id in sorted(public_payload["answers"])
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["submission"])
        writer.writerow([json.dumps(public_payload, ensure_ascii=False, separators=(",", ":"))])


def write_traces(traces: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for trace in traces:
            handle.write(json.dumps(trace, ensure_ascii=False, sort_keys=True) + "\n")


def run_submission(output_path: Path | None = None) -> Path:
    data_dir = find_data_dir()
    tasks = load_jsonl(data_dir / "screening_tasks.jsonl")
    payload = run_tasks(tasks)
    output_path = output_path or BASE_DIR / "submission.csv"
    write_submission(payload, output_path)
    write_traces(payload.get("_traces", []), BASE_DIR / "reports" / "decision_trace.jsonl")
    ConsistencyValidator.write_report()
    print(f"wrote {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=BASE_DIR / "submission.csv")
    args = parser.parse_args()
    run_submission(args.output)


if __name__ == "__main__":
    main()
