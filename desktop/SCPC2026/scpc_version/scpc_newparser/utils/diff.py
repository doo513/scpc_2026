from __future__ import annotations

import csv
import json
from pathlib import Path
from collections import Counter


def compare_submissions(
    ref_path: Path,
    new_path: Path,
    *,
    reference_label: str | None = None,
    new_label: str | None = None,
) -> str:
    csv.field_size_limit(10000000)
    
    with open(ref_path, encoding="utf-8") as f:
        r = csv.reader(f)
        next(r)
        ref_payload = json.loads(next(r)[0])
        
    with open(new_path, encoding="utf-8") as f:
        r = csv.reader(f)
        next(r)
        new_payload = json.loads(next(r)[0])
        
    ref_answers = ref_payload.get("answers", {})
    new_answers = new_payload.get("answers", {})
    
    focal_diff = 0
    target_diff = 0
    control_diff = 0
    mode_diff = 0
    policy_diff = 0
    plan_diff = 0
    
    transitions = []
    
    for task_id in sorted(new_answers.keys()):
        if task_id not in ref_answers:
            continue
        ref_ans = ref_answers[task_id]
        new_ans = new_answers[task_id]
        
        if ref_ans.get("focal_id") != new_ans.get("focal_id"):
            focal_diff += 1
        if ref_ans.get("target") != new_ans.get("target"):
            target_diff += 1
        if ref_ans.get("control") != new_ans.get("control"):
            control_diff += 1
            transitions.append(f"{ref_ans.get('control')} -> {new_ans.get('control')}")
        if ref_ans.get("content_scope", {}).get("mode") != new_ans.get("content_scope", {}).get("mode"):
            mode_diff += 1
        if ref_ans.get("policy", {}).get("requires_confirmation") != new_ans.get("policy", {}).get("requires_confirmation"):
            policy_diff += 1
            
        ref_plan = [(ev.get("verb"), ev.get("target")) for ev in ref_ans.get("plan_events", [])]
        new_plan = [(ev.get("verb"), ev.get("target")) for ev in new_ans.get("plan_events", [])]
        if ref_plan != new_plan:
            plan_diff += 1
            
    new_label = new_label or f"{new_path.parent.name}/{new_path.name}"
    reference_label = reference_label or f"{ref_path.parent.name}/{ref_path.name}"
    lines = [
        f"# Comparison: {new_label} vs {reference_label}",
        "",
        "## Changed Counts",
        f"- **focal changed count**: {focal_diff}",
        f"- **target changed count**: {target_diff}",
        f"- **control changed count**: {control_diff}",
        f"- **scope mode changed count**: {mode_diff}",
        f"- **policy confirmation changed count**: {policy_diff}",
        f"- **plan sequence changed count**: {plan_diff}",
        "",
        "## Major Transitions (Control)",
    ]
    for k, v in sorted(Counter(transitions).items(), key=lambda x: x[1], reverse=True):
        lines.append(f"- `{k}`: {v}")
        
    return "\n".join(lines)
