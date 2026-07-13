from __future__ import annotations

import csv
import json
from pathlib import Path
from collections import Counter
from core.relations import RelationGraph
from core.task_view import TaskView
from .io import find_data_dir, load_jsonl


def generate_distribution_report(path: Path) -> str:
    csv.field_size_limit(10000000)
    with open(path, encoding="utf-8") as f:
        r = csv.reader(f)
        next(r)
        payload = json.loads(next(r)[0])
        
    answers = payload.get("answers", {})
    
    # Load screening tasks to check marker trace matching
    try:
        data_dir = find_data_dir()
        screening_tasks = load_jsonl(data_dir / "screening_tasks.jsonl")
        task_map = {t["id"]: t for t in screening_tasks}
    except Exception as e:
        task_map = {}
        print(f"Warning: could not load screening tasks for marker trace match check: {e}")
        
    controls = []
    modes = []
    targets = []
    confirmations = 0
    plan_sequences = []
    excluded_fields_count = 0
    focal_methods: Counter[str] = Counter()
    structurally_resolved = 0
    structural_agreement = 0
    
    for task_id, ans in answers.items():
        controls.append(ans.get("control"))
        scope = ans.get("content_scope", {})
        modes.append(scope.get("mode"))
        targets.append(ans.get("target"))
        
        if ans.get("policy", {}).get("requires_confirmation"):
            confirmations += 1
            
        plan_seq = tuple(ev.get("verb") for ev in ans.get("plan_events", []))
        plan_sequences.append(plan_seq)
        
        excluded_fields_count += len(scope.get("excluded_fields", []))
        
        task = task_map.get(task_id)
        if task:
            resolution = RelationGraph(TaskView(task)).resolve_focal()
            focal_methods[resolution.method] += 1
            if resolution.resolution_status == "resolved":
                structurally_resolved += 1
                if ans.get("focal_id") == resolution.focal_id:
                    structural_agreement += 1
                    
    lines = [
        f"# Screening Structural Report for {path.name}",
        "",
        "## Control Distribution",
    ]
    for k, v in sorted(Counter(controls).items()):
        lines.append(f"- `{k}`: {v}")
        
    lines.append("")
    lines.append("## Scope Mode Distribution")
    for k, v in sorted(Counter(modes).items()):
        lines.append(f"- `{k}`: {v}")
        
    lines.append("")
    lines.append("## Target Top 30")
    for k, v in sorted(Counter(targets).items(), key=lambda x: x[1], reverse=True)[:30]:
        lines.append(f"- `{k}`: {v}")
        
    lines.append("")
    lines.append("## Policy Requires Confirmation Distribution")
    lines.append(f"- `True`: {confirmations}")
    lines.append(f"- `False`: {len(answers) - confirmations}")
    
    lines.append("")
    lines.append("## Plan Sequence Distribution")
    seq_counter = Counter(plan_sequences)
    for k, v in seq_counter.most_common(20):
        seq_str = " -> ".join(k)
        lines.append(f"- `[{seq_str}]`: {v}")
        
    lines.append("")
    lines.append("## Diagnostics (not scoring priors)")
    lines.append("- Screening labels are unavailable; focal counts below are coverage/integrity, not accuracy.")
    lines.append(f"- **total excluded fields**: {excluded_fields_count}")
    lines.append(f"- **structurally resolved focal count**: {structurally_resolved} / {len(answers)}")
    lines.append(f"- **submission/structural focal agreement**: {structural_agreement} / {structurally_resolved}")
    lines.extend(
        f"- **focal method `{method}`**: {count}"
        for method, count in sorted(focal_methods.items())
    )
    lines.append(f"- **memory_store count**: {targets.count('memory_store')}")
    lines.append(f"- **status_only count**: {modes.count('status_only')}")
    lines.append(f"- **redacted count**: {modes.count('redacted')}")
    lines.append(f"- **proceed count**: {controls.count('proceed')}")
    
    return "\n".join(lines)
