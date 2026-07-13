from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from local_score import WEIGHTS, score_answer
from run_submission import run_tasks
from utils.io import find_data_dir, load_jsonl


def _dev_payload_and_reference() -> tuple[dict, dict, set[str]]:
    data_dir = find_data_dir()
    tasks = load_jsonl(data_dir / "dev_tasks.jsonl")
    reference_payload = json.loads((data_dir / "dev_answers.json").read_text(encoding="utf-8"))
    public_values = set(reference_payload["plan_arg_ontology"]["values"])
    payload = run_tasks(tasks)
    return payload, reference_payload, public_values


def test_dev_focal_and_optional_fields_are_structurally_complete() -> None:
    payload, reference_payload, public_values = _dev_payload_and_reference()
    assert "compatibility" not in json.dumps(payload["_traces"], ensure_ascii=False)
    for task_id, reference in reference_payload["answers"].items():
        row = score_answer(payload["answers"][task_id], reference, public_values)
        assert row["focal"] == 1.0
    for answer in payload["answers"].values():
        assert answer["user_response"]
        assert answer["audit_tags"]
        assert answer["counterfactual"]


@pytest.mark.dev_score
def test_dev_score_diagnostics(record_property) -> None:
    payload, reference_payload, public_values = _dev_payload_and_reference()
    rows = []
    for task_id, reference in reference_payload["answers"].items():
        row = score_answer(payload["answers"][task_id], reference, public_values)
        rows.append(row)
    axes = {
        key: round(sum(row[key] for row in rows) / len(rows), 4)
        for key in WEIGHTS
    }
    overall = round(
        sum(
            sum(row[key] * WEIGHTS[key] for key in WEIGHTS)
            for row in rows
        )
        / len(rows),
        4,
    )
    spec = json.loads(
        (
            Path(__file__).resolve().parent
            / "specs"
            / "generalization_v1.json"
        ).read_text(encoding="utf-8")
    )
    gate = spec["dev_hard_gate"]
    non_exact = sum(
        any(row[key] < 1.0 for key in gate["required_axes"])
        for row in rows
    )
    threshold_checks = {
        "overall": overall >= gate["minimum_overall"],
        **{
            f"axis.{axis}": axes[axis] >= floor
            for axis, floor in gate["minimum_axes"].items()
        },
        "non_exact": non_exact <= gate["maximum_non_exact_tasks"],
    }

    # Dev answers remain an observable diagnostic, not release authority.
    # Keep every task in the calculation and expose threshold status without
    # turning a finite public answer set into a production success criterion.
    record_property("dev_overall", overall)
    record_property("dev_non_exact", non_exact)
    record_property("dev_thresholds_met", all(threshold_checks.values()))
    for axis, value in axes.items():
        record_property(f"dev_axis_{axis}", value)

    assert gate["release_blocking"] is False
    assert rows and len(rows) == len(reference_payload["answers"])
    assert set(payload["answers"]) == set(reference_payload["answers"])
    assert all(
        0.0 <= value <= 1.0
        for row in rows
        for value in row.values()
    )


def test_dev_output_is_invariant_to_array_order_and_input_order() -> None:
    tasks = load_jsonl(find_data_dir() / "dev_tasks.jsonl")
    original = run_tasks(tasks)["answers"]
    permuted = copy.deepcopy(tasks)
    for task in permuted:
        state = task.get("device_state") or {}
        state["objects"] = list(reversed(state.get("objects") or []))
        state["records"] = list(reversed(state.get("records") or []))
        task["visible_history"] = list(reversed(task.get("visible_history") or []))
    changed = run_tasks(list(reversed(permuted)))["answers"]
    assert changed == original


def test_screening_contract_and_screen_only_records() -> None:
    tasks = load_jsonl(find_data_dir() / "screening_tasks.jsonl")
    payload = run_tasks(tasks)
    assert len(payload["answers"]) == 700
    assert set(payload["answers"]) == {str(task["id"]) for task in tasks}
    screen_only = {"calendar_conflict", "guest_mode", "trusted_subscription", "verified_internal_target"}
    seen = {
        str(record.get("type"))
        for task in tasks
        for record in (task.get("device_state") or {}).get("records", [])
    }
    assert screen_only <= seen
