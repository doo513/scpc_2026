from __future__ import annotations

from typing import Any

from core.decision import FinalDecision
from core.spec import PLAN_PURPOSES, PLAN_REASONS, PLAN_SCOPES, PLAN_VERBS


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    verb = str(event.get("verb") or "")
    target = str(event.get("target") or "")
    args = event.get("args") or {}
    if verb not in PLAN_VERBS:
        raise ValueError(f"unknown plan event verb: {verb}")
    if not target:
        raise ValueError(f"empty target for plan event: {verb}")
    if not isinstance(args, dict):
        raise ValueError(f"plan event args must be an object: {verb}")

    allowed_keys = {
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
    unknown_keys = set(args) - allowed_keys
    if unknown_keys:
        raise ValueError(f"unknown plan argument keys: {sorted(unknown_keys)}")
    if "purpose" in args and args["purpose"] not in PLAN_PURPOSES:
        raise ValueError(f"unknown purpose: {args['purpose']}")
    if "reason" in args and args["reason"] not in PLAN_REASONS:
        raise ValueError(f"unknown reason: {args['reason']}")
    if "scope" in args and args["scope"] not in PLAN_SCOPES:
        raise ValueError(f"unknown scope: {args['scope']}")
    return {"verb": verb, "target": target, "args": dict(args)}


class PlanCompiler:
    """Pure projection of plan steps locked in FinalDecision."""

    @staticmethod
    def compile(decision: FinalDecision) -> list[dict[str, Any]]:
        events = [normalize_event(step.to_event()) for step in decision.plan_steps]
        if len(events) > 18:
            raise ValueError("plan event count exceeds schema maximum")
        unavailable = {
            event["verb"]
            for event in events
            if event["verb"] not in decision.available_actions
        }
        if unavailable:
            raise ValueError(
                f"locked plan contains unavailable actions: {sorted(unavailable)}"
            )
        return events
