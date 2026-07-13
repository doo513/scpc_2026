from __future__ import annotations

import json
import re
from typing import Any, Callable

from local_score import evaluate_dev_payload
from official_baseline import find_official_notebook
from run_submission import run_tasks
from utils.io import find_data_dir, load_jsonl


SUBMISSION_SCHEMA = "scpc.final.answer.v1"
FIXED_SLM_ID = "scpc-final-fixed-slm-local-facade"


def _load_official_score_function() -> Callable[
    [dict[str, Any], dict[str, Any]], dict[str, Any]
]:
    notebook = find_official_notebook()
    document = json.loads(notebook.read_text(encoding="utf-8"))
    scorer_source = next(
        (
            "".join(cell.get("source") or [])
            for cell in document.get("cells") or []
            if cell.get("cell_type") == "code"
            and "def score_dev_submission" in "".join(
                cell.get("source") or []
            )
        ),
        "",
    )
    if not scorer_source:
        raise RuntimeError("official notebook scorer cell is missing")
    namespace: dict[str, Any] = {
        "Any": Any,
        "FIXED_SLM_ID": FIXED_SLM_ID,
        "SUBMISSION_SCHEMA": SUBMISSION_SCHEMA,
        "json": json,
        "re": re,
    }
    exec(
        compile(scorer_source, f"{notebook}:official-scorer", "exec"),
        namespace,
    )
    scorer = namespace.get("score_dev_submission")
    if not callable(scorer):
        raise RuntimeError("official notebook scorer is not callable")
    return scorer


def evaluate_official_dev_payload(
    payload: dict[str, Any],
    references: dict[str, Any],
) -> dict[str, Any]:
    return _load_official_score_function()(payload, references)


def evaluate_current_scorer_parity() -> dict[str, Any]:
    data_dir = find_data_dir()
    references = json.loads(
        (data_dir / "dev_answers.json").read_text(encoding="utf-8")
    )
    payload = run_tasks(load_jsonl(data_dir / "dev_tasks.jsonl"))
    local, _diagnostics = evaluate_dev_payload(payload, references)
    official = evaluate_official_dev_payload(payload, references)
    comparable_local = {
        "overall": local["overall"],
        "n": local["n"],
        "axes": local["axes"],
    }
    return {
        "identical": official == comparable_local,
        "official": official,
        "local": comparable_local,
    }


if __name__ == "__main__":
    print(
        json.dumps(
            evaluate_current_scorer_parity(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
