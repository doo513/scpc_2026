from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from core.blueprint import project_scope_mode
from core.contracts import assumption_ids
from core.decision import FinalDecision
from utils.schema_check import validate_answer


BASE_DIR = Path(__file__).resolve().parent.parent
EXECUTION_VERBS = {"dispatch", "update", "schedule", "toggle", "pay"}
KNOWN_TARGET_STATES = {
    "authority_incomplete",
    "user_binding_pending",
    "local_update_boundary",
    "redacted_external_boundary",
    "redacted_after_selection_boundary",
    "dispatch_blocked_until_binding",
    "boundary_after_authority",
    "authority_after_candidates",
    "strict",
    "normal",
}
class ConsistencyValidator:
    errors: list[str] = []
    controls: Counter[str] = Counter()
    modes: Counter[str] = Counter()

    @classmethod
    def reset(cls) -> None:
        cls.errors = []
        cls.controls = Counter()
        cls.modes = Counter()

    @classmethod
    def validate_strict(
        cls,
        answer: dict[str, Any],
        view: Any,
        evidence: Any,
        decision_authority: FinalDecision,
    ) -> None:
        task_errors: list[str] = []
        task_id = view.task_id
        validate_answer(answer)
        if type(decision_authority) is not FinalDecision:
            raise ValueError(
                f"[{task_id}] decision authority must be an immutable FinalDecision"
            )

        focal_id = str(answer.get("focal_id") or "")
        target = str(answer.get("target") or "")
        control = str(answer.get("control") or "")
        scope = answer.get("content_scope") or {}
        mode = str(scope.get("mode") or "")
        events = answer.get("plan_events") or []
        verbs = [str(event.get("verb") or "") for event in events]

        final_trace = (
            evidence.get("final_decision", {})
            if isinstance(evidence, dict)
            else {}
        )
        authority_trace = decision_authority.to_trace()
        if final_trace and final_trace != authority_trace:
            task_errors.append("serialized FinalDecision trace differs from authority")
        expected_trace = authority_trace
        matrix_trace = (
            evidence.get("decision_matrix", {})
            if isinstance(evidence, dict)
            else {}
        )
        blueprint = expected_trace.get("effective_blueprint") or {}
        blueprint_terminal = str(blueprint.get("terminal_verb") or "")
        blueprint_effects = {
            str(item.get("kind") or "")
            for item in blueprint.get("effects", [])
            if isinstance(item, dict)
        }
        if expected_trace:
            unknown_assumptions = set(
                expected_trace.get("unresolved_assumption_refs") or []
            ) - assumption_ids()
            if unknown_assumptions:
                task_errors.append(
                    "FinalDecision references unknown assumptions: "
                    f"{sorted(unknown_assumptions)}"
                )
            if focal_id != str(expected_trace.get("focal_id") or ""):
                task_errors.append("answer focal_id differs from FinalDecision")
            if target != str(expected_trace.get("target") or ""):
                task_errors.append("answer target differs from FinalDecision")
            if control != str(expected_trace.get("control") or ""):
                task_errors.append("answer control differs from FinalDecision")
            disclosure = expected_trace.get("disclosure") or {}
            expected_mode = project_scope_mode(
                str(blueprint.get("scope_mode") or "none"),
                str(expected_trace.get("control") or ""),
            )
            expected_scope = {
                "mode": expected_mode,
                "allowed_fields": list(disclosure.get("allowed_fields") or []),
                "excluded_fields": list(disclosure.get("excluded_fields") or []),
                "requires_user_confirmation": bool(
                    disclosure.get("requires_user_confirmation")
                ),
            }
            if scope != expected_scope:
                task_errors.append("content_scope is not a pure FinalDecision projection")
            policy = answer.get("policy") or {}
            expected_policy = {
                "risk_flags": list(expected_trace.get("risk_flags") or []),
                "violations": list(expected_trace.get("violations") or []),
                "requires_confirmation": bool(
                    expected_trace.get("policy_requires_confirmation")
                ),
            }
            if policy != expected_policy:
                task_errors.append("policy is not a pure FinalDecision projection")
            if events != list(expected_trace.get("plan_steps") or []):
                task_errors.append("plan_events are not a pure FinalDecision projection")
            expected_plan_verbs = [
                capability
                for capability in expected_trace.get(
                    "final_plan_capabilities", []
                )
            ]
            if verbs != expected_plan_verbs:
                task_errors.append(
                    "plan verbs differ from the final capability contract"
                )

        if matrix_trace and expected_trace:
            if str(matrix_trace.get("selected_candidate") or "") != str(
                expected_trace.get("selected_pair_id") or ""
            ):
                task_errors.append("selected pair differs from FinalDecision")
            if str(matrix_trace.get("selected_action") or "") != str(
                expected_trace.get("action") or ""
            ):
                task_errors.append("selected action differs from FinalDecision")
            if str(matrix_trace.get("selected_operation_mode") or "") != str(
                expected_trace.get("operation_mode") or ""
            ):
                task_errors.append("selected operation differs from FinalDecision")
            if str(matrix_trace.get("selected_target") or "") != str(
                expected_trace.get("operation_target") or ""
            ):
                task_errors.append("selected target differs from FinalDecision")
            selected_evaluation = next(
                (
                    item
                    for item in matrix_trace.get("evaluations", [])
                    if item.get("candidate_id")
                    == matrix_trace.get("selected_candidate")
                ),
                {},
            )
            if str(selected_evaluation.get("target_role") or "") != str(
                expected_trace.get("operation_target_role") or ""
            ):
                task_errors.append("selected target role differs from FinalDecision")
            if str(selected_evaluation.get("target_locality") or "") != str(
                expected_trace.get("operation_target_locality") or ""
            ):
                task_errors.append(
                    "selected target locality differs from FinalDecision"
                )
            gates = matrix_trace.get("decision_gates") or []
            if gates:
                gate_disposition = str(gates[0].get("disposition") or "")
                expected_control = {
                    "blocked": "hold",
                    "needs_clarification": "ask",
                    "amendable": "amend",
                    "executable": "proceed",
                }.get(gate_disposition)
                if expected_control and control != expected_control:
                    task_errors.append("decision gate disposition differs from control")
        if focal_id not in view.objects_by_id():
            task_errors.append(f"focal_id '{focal_id}' is not a current object")
        if not target:
            task_errors.append("target is empty")
        if target in KNOWN_TARGET_STATES:
            task_errors.append(f"target '{target}' is a record state")
        if any(verb not in view.available_actions for verb in verbs):
            task_errors.append("plan contains an unavailable action")
        if len(events) > 18:
            task_errors.append("plan exceeds 18 events")

        if control == "hold" and (
            mode != "none" or EXECUTION_VERBS & set(verbs)
        ):
            task_errors.append(
                "hold must use none scope and must not execute"
            )
        if control == "ask" and ("clarify" not in verbs or EXECUTION_VERBS & set(verbs)):
            task_errors.append("ask must clarify without an execution event")
        if control == "amend":
            if not blueprint_effects.intersection(
                {
                    "add_redaction",
                    "force_summary",
                    "limit_duration",
                    "restrict_target",
                }
            ):
                task_errors.append("amend requires a projected modification effect")
            if blueprint_terminal and blueprint_terminal not in verbs:
                task_errors.append("amend must preserve the blueprint terminal")
            if "add_redaction" in blueprint_effects and (
                mode != "redacted" or "redact" not in verbs
            ):
                task_errors.append("redaction effect must be projected")
            if (
                "force_summary" in blueprint_effects
                and "add_redaction" not in blueprint_effects
                and (mode != "summary" or "summarize" not in verbs)
            ):
                task_errors.append(
                    "summary restriction must be projected as summary or redaction"
                )
            if "limit_duration" in blueprint_effects:
                terminal_events = [
                    event
                    for event in events
                    if event.get("verb") == blueprint_terminal
                ]
                if not terminal_events or not any(
                    (event.get("args") or {}).get("duration")
                    for event in terminal_events
                ):
                    task_errors.append("duration effect must be projected")
        if mode == "status_only" and "dispatch" in verbs:
            task_errors.append("status_only must not dispatch")
        if mode == "status_only" and not ({"update", "pay", "toggle", "schedule"} & set(verbs)):
            task_errors.append("status_only must contain a non-disclosure execution event")
        if (
            target == "memory_store"
            and control in {"proceed", "amend"}
            and mode != "status_only"
            and "update" not in verbs
        ):
            task_errors.append("memory_store target requires status_only scope or an update event")
        if mode == "none" and scope.get("allowed_fields"):
            task_errors.append("none scope must have no allowed fields")

        cls._validate_order(verbs, task_errors)
        property_names = {
            item.name for item in view.properties_for_object(focal_id)
        }
        for field in scope.get("excluded_fields") or []:
            if field not in property_names:
                task_errors.append(
                    f"exclusion '{field}' has no focal-field provenance"
                )

        cls.controls[control] += 1
        cls.modes[mode] += 1
        if task_errors:
            cls.errors.extend(f"{task_id}: {message}" for message in task_errors)
            raise ValueError("; ".join(task_errors))

    @staticmethod
    def _validate_order(verbs: list[str], errors: list[str]) -> None:
        def before(first: str, second: str) -> bool:
            return first not in verbs or second not in verbs or verbs.index(first) < verbs.index(second)

        if not before("read", "dispatch"):
            errors.append("read must precede dispatch")
        if not before("redact", "dispatch"):
            errors.append("redact must precede dispatch")
        if not before("summarize", "dispatch"):
            errors.append("summarize must precede dispatch")
        if not before("verify", "update"):
            errors.append("verify must precede update")
        if not before("verify", "pay"):
            errors.append("verify must precede pay")
        if not before("verify", "toggle"):
            errors.append("verify must precede toggle")
        if not before("verify", "schedule"):
            errors.append("verify must precede schedule")

    @classmethod
    def write_report(cls, output_path: Path | None = None) -> Path:
        output_path = output_path or BASE_DIR / "reports" / "consistency_report.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Consistency Report",
            "",
            f"- Hard errors: {len(cls.errors)}",
            "",
            "## Structural Statistics",
        ]
        lines.extend(f"- control.{key}: {value}" for key, value in sorted(cls.controls.items()))
        lines.extend(f"- scope.{key}: {value}" for key, value in sorted(cls.modes.items()))
        lines.extend(["", "## Errors"])
        lines.extend(f"- {message}" for message in cls.errors) if cls.errors else lines.append("- None")
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return output_path
