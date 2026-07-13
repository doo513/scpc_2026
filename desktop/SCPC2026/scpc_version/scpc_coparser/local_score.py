from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from run_submission import run_tasks
from utils.io import find_data_dir, load_jsonl


WEIGHTS = {
    "focal": 0.18,
    "target": 0.12,
    "control": 0.18,
    "content_scope": 0.17,
    "policy": 0.13,
    "plan": 0.18,
    "semantic_response": 0.04,
    "counterfactual": 0.0,
}
BASE_DIR = Path(__file__).resolve().parent
PLAN_ARG_KEYS = {
    "purpose",
    "reason",
    "scope",
    "state",
    "remove",
    "mode",
    "status",
    "duration",
    "person",
    "check",
    "condition",
    "lesson",
    "time",
    "rule",
    "method",
    "date",
    "principle",
}
PLAN_ARG_ALIASES = {
    "inspect": "inspect_context",
    "inspect_fields": "inspect_context",
    "inspect_task_context": "inspect_context",
    "local_update_only": "local_update",
    "latest_local_update_override": "local_update",
    "persistent_memory_write": "memory_write",
    "persistent_memory_recall": "memory_read",
    "raw_quote_location_numeric_value": "sensitive_fields",
    "enterprise_sensitive_fields": "sensitive_fields",
    "guardrail_sensitive_fields": "sensitive_fields",
    "recipient_conflicts_with_latest_target": "target_conflict",
    "resolved_target_precedence": "latest_target_precedence",
    "target_changed_after_turn": "target_changed",
    "temporary_override": "temporary_override",
    "internal_binding_confirmed": "route_verified",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).strip()


def _set(value: Any) -> set[str]:
    values = value if isinstance(value, list) else ([] if value is None else [value])
    return {_text(item).lower() for item in values if _text(item)}


def _f1(pred: set[str], reference: set[str]) -> float:
    if not pred and not reference:
        return 1.0
    if not pred or not reference:
        return 0.0
    hit = len(pred & reference)
    if not hit:
        return 0.0
    precision = hit / len(pred)
    recall = hit / len(reference)
    return 2 * precision * recall / (precision + recall)


def _normalize_arg(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _canonical_arg(value: Any, public_values: set[str]) -> str:
    token = _normalize_arg(value)
    if re.fullmatch(r"\d{2}_\d{2}", token):
        first = int(token.split("_", 1)[0])
        return "scheduled_date" if first <= 12 else "scheduled_time"
    token = PLAN_ARG_ALIASES.get(token, token)
    return token if token in public_values else ""


def _plan_arg_sets(
    event: dict[str, Any],
    public_values: set[str],
) -> tuple[set[str], set[str]]:
    pairs: set[str] = set()
    values: set[str] = set()
    args = event.get("args")
    if not isinstance(args, dict):
        return pairs, values
    for key, value in args.items():
        normalized_key = _normalize_arg(key)
        if normalized_key not in PLAN_ARG_KEYS:
            continue
        normalized_value = _canonical_arg(value, public_values)
        if normalized_value:
            pairs.add(f"{normalized_key}:{normalized_value}")
            values.add(normalized_value)
    return pairs, values


def _plan_arg_similarity(
    pred: dict[str, Any],
    reference: dict[str, Any],
    public_values: set[str],
) -> float:
    pred_pairs, pred_values = _plan_arg_sets(pred, public_values)
    ref_pairs, ref_values = _plan_arg_sets(reference, public_values)
    if not ref_values:
        return 1.0
    value_score = _f1(pred_values, ref_values)
    pair_score = _f1(pred_pairs, ref_pairs) if ref_pairs else value_score
    return round(0.65 * value_score + 0.35 * pair_score, 4)


def _similar_scope(pred: dict[str, Any], ref: dict[str, Any]) -> float:
    pred = pred or {}
    ref = ref or {}
    return (
        0.40 * (_text(pred.get("mode")) == _text(ref.get("mode")))
        + 0.25 * _f1(_set(pred.get("allowed_fields")), _set(ref.get("allowed_fields")))
        + 0.25 * _f1(_set(pred.get("excluded_fields")), _set(ref.get("excluded_fields")))
        + 0.10
        * (
            bool(pred.get("requires_user_confirmation"))
            == bool(ref.get("requires_user_confirmation"))
        )
    )


def _similar_policy(pred: dict[str, Any], ref: dict[str, Any]) -> float:
    pred = pred or {}
    ref = ref or {}
    return (
        0.45 * _f1(_set(pred.get("risk_flags")), _set(ref.get("risk_flags")))
        + 0.35 * _f1(_set(pred.get("violations")), _set(ref.get("violations")))
        + 0.20
        * (bool(pred.get("requires_confirmation")) == bool(ref.get("requires_confirmation")))
    )


def _event_similarity(
    pred: Any,
    reference: Any,
    public_values: set[str],
) -> float:
    if not isinstance(pred, dict) or not isinstance(reference, dict):
        return 0.0
    if _text(pred.get("verb")) != _text(reference.get("verb")):
        return 0.0
    score = 0.40
    if _text(pred.get("target")) == _text(reference.get("target")):
        score += 0.30
    score += 0.30 * _plan_arg_similarity(pred, reference, public_values)
    return min(score, 1.0)


def _plan_score(pred: Any, ref: Any, public_values: set[str]) -> float:
    pred_events = pred if isinstance(pred, list) else []
    ref_events = ref if isinstance(ref, list) else []
    if not ref_events:
        return 1.0 if not pred_events else 0.5

    used: set[int] = set()
    unordered_total = 0.0
    for expected in ref_events:
        choices = [
            (_event_similarity(actual, expected, public_values), index)
            for index, actual in enumerate(pred_events)
            if index not in used
        ]
        best, best_index = max(choices, default=(0.0, -1))
        if best_index >= 0:
            used.add(best_index)
        unordered_total += best

    ordered_total = 0.0
    cursor = 0
    for expected in ref_events:
        choices = [
            (_event_similarity(pred_events[index], expected, public_values), index)
            for index in range(cursor, len(pred_events))
        ]
        best, best_index = max(choices, default=(0.0, -1))
        if best_index >= 0:
            cursor = best_index + 1
        ordered_total += best

    recall = 0.5 * unordered_total / len(ref_events) + 0.5 * ordered_total / len(ref_events)
    extra = max(0, len(pred_events) - len(used))
    return max(0.0, recall - min(0.30, 0.06 * extra))


def score_answer(
    pred: dict[str, Any],
    ref: dict[str, Any],
    public_values: set[str] | None = None,
) -> dict[str, float]:
    public_values = public_values or {
        _normalize_arg(value)
        for event in ref.get("expected_events", [])
        for value in (event.get("args") or {}).values()
    }
    focal = float(_text(pred.get("focal_id")) == _text(ref.get("focal_id")))
    target = focal * float(_text(pred.get("target")) == _text(ref.get("target")))
    control = focal * float(_text(pred.get("control")) == _text(ref.get("control")))
    downstream = target * control
    return {
        "focal": focal,
        "target": target,
        "control": control,
        "content_scope": downstream
        * _similar_scope(pred.get("content_scope", {}), ref.get("content_scope", {})),
        "policy": downstream * _similar_policy(pred.get("policy", {}), ref.get("policy", {})),
        "plan": downstream
        * _plan_score(pred.get("plan_events"), ref.get("expected_events"), public_values),
        # The public references do not include a semantic response target.
        "semantic_response": 0.0,
        "counterfactual": 0.0,
    }


def score_dev() -> dict[str, Any]:
    data_dir = find_data_dir()
    tasks = load_jsonl(data_dir / "dev_tasks.jsonl")
    reference_payload = json.loads((data_dir / "dev_answers.json").read_text(encoding="utf-8"))
    refs = reference_payload["answers"]
    public_values = set((reference_payload.get("plan_arg_ontology") or {}).get("values", []))
    payload = run_tasks(tasks)
    traces = {trace["task_id"]: trace for trace in payload.get("_traces", [])}

    rows: list[dict[str, float]] = []
    input_visibility_gap_cases = 0
    wrong: list[tuple[str, dict[str, float]]] = []
    control_confusion: Counter[tuple[str, str]] = Counter()
    mode_confusion: Counter[tuple[str, str]] = Counter()
    for task_id, ref in refs.items():
        pred = payload["answers"][task_id]
        scores = score_answer(pred, ref, public_values)
        rows.append(scores)
        trace = traces.get(task_id, {})
        matrix = trace.get("decision_matrix") or {}
        selected_id = matrix.get("selected_candidate")
        selected = next(
            (
                item
                for item in matrix.get("evaluations", [])
                if item.get("candidate_id") == selected_id
            ),
            {},
        )
        missing_memory = any(
            slot.get("reason_code") == "REQUIRED_MEMORY_UNAVAILABLE"
            for slot in (selected.get("slots") or {}).values()
            if isinstance(slot, dict)
        )
        if missing_memory:
            input_visibility_gap_cases += 1
        control_confusion[(str(ref.get("control")), str(pred.get("control")))] += 1
        mode_confusion[
            (
                str((ref.get("content_scope") or {}).get("mode")),
                str((pred.get("content_scope") or {}).get("mode")),
            )
        ] += 1
        if any(scores[key] < 1.0 for key in ("focal", "target", "control", "content_scope", "policy", "plan")):
            wrong.append((task_id, scores))

    axes = {key: round(sum(row[key] for row in rows) / len(rows), 4) for key in WEIGHTS}
    overall = round(
        sum(sum(row[key] * WEIGHTS[key] for key in WEIGHTS) for row in rows) / len(rows),
        4,
    )
    result = {
        "overall": overall,
        "input_visibility_gap_cases": input_visibility_gap_cases,
        "n": len(rows),
        "axes": axes,
        "wrong": len(wrong),
        "control_confusion": {f"{a}->{b}": n for (a, b), n in sorted(control_confusion.items())},
        "mode_confusion": {f"{a}->{b}": n for (a, b), n in sorted(mode_confusion.items())},
    }
    _write_report(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _write_report(result: dict[str, Any]) -> None:
    lines = [
        "# SCPC Dev Score Report",
        "",
        f"- Overall: `{result['overall']:.4f}`",
        f"- Required-memory input visibility gaps: {result['input_visibility_gap_cases']}",
        f"- Tasks: {result['n']}",
        f"- Non-exact tasks: {result['wrong']}",
        "",
        "## Axes",
        "",
        "| Axis | Score | Weight |",
        "| --- | ---: | ---: |",
    ]
    for key in WEIGHTS:
        lines.append(f"| {key} | {result['axes'][key]:.4f} | {WEIGHTS[key]:.2f} |")
    lines.extend(["", "## Control Confusion"])
    lines.extend(f"- {key}: {value}" for key, value in result["control_confusion"].items())
    lines.extend(["", "## Scope Mode Confusion"])
    lines.extend(f"- {key}: {value}" for key, value in result["mode_confusion"].items())
    reports = BASE_DIR / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "dev_score_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    score_dev()
