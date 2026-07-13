from __future__ import annotations

import json

from local_score import _plan_score, evaluate_dev_payload
from official_scorer import evaluate_current_scorer_parity
from run_submission import run_tasks
from utils.io import find_data_dir, load_jsonl


def test_plan_ties_keep_the_first_best_match_like_official_notebook() -> None:
    predictions = [
        {"verb": "read", "target": "object", "args": {}},
        {"verb": "read", "target": "object", "args": {"reason": "scope_check"}},
    ]
    references = [
        {"verb": "read", "target": "object", "args": {}},
        {"verb": "read", "target": "object", "args": {"reason": "scope_check"}},
    ]

    assert _plan_score(predictions, references, {"scope_check"}) == 1.0


def test_current_dev_result_does_not_regress_below_official_scorer_snapshot() -> None:
    data_dir = find_data_dir()
    tasks = load_jsonl(data_dir / "dev_tasks.jsonl")
    references = json.loads(
        (data_dir / "dev_answers.json").read_text(encoding="utf-8")
    )

    result, _ = evaluate_dev_payload(run_tasks(tasks), references)

    assert result["overall"] >= 0.8186
    assert result["axes"]["plan"] >= 0.7723


def test_local_scorer_matches_current_official_notebook_cell() -> None:
    parity = evaluate_current_scorer_parity()

    assert parity["identical"] is True
