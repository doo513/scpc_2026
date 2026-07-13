from __future__ import annotations

from typing import Any
from core.spec import CONTROL_VALUES, SCOPE_MODES, PLAN_VERBS


def validate_answer(answer: dict[str, Any]) -> None:
    for key in ("focal_id", "target", "control", "content_scope", "policy", "plan_events"):
        if key not in answer:
            raise ValueError(f"answer missing {key}")
            
    if answer["control"] not in CONTROL_VALUES:
        raise ValueError(f"bad control: {answer['control']}")
    if not isinstance(answer["focal_id"], str) or not answer["focal_id"]:
        raise ValueError("focal_id must be a non-empty string")
    if not isinstance(answer["target"], str) or not answer["target"]:
        raise ValueError("target must be a non-empty string")
        
    scope = answer["content_scope"]
    if not isinstance(scope, dict):
        raise ValueError("content_scope must be a dict")
        
    if scope.get("mode") not in SCOPE_MODES:
        raise ValueError(f"bad scope mode: {scope.get('mode')}")
        
    for key in ("allowed_fields", "excluded_fields"):
        if not isinstance(scope.get(key), list):
            raise ValueError(f"bad scope {key}")
            
    if not isinstance(scope.get("requires_user_confirmation"), bool):
        raise ValueError("bad scope requires_user_confirmation")
        
    policy = answer["policy"]
    if not isinstance(policy, dict):
        raise ValueError("policy must be a dict")
        
    for key in ("risk_flags", "violations"):
        if not isinstance(policy.get(key), list):
            raise ValueError(f"bad policy {key}")
            
    if not isinstance(policy.get("requires_confirmation"), bool):
        raise ValueError("bad policy requires_confirmation")
        
    events = answer["plan_events"]
    if not isinstance(events, list):
        raise ValueError("plan_events must be a list")
    if len(events) > 18:
        raise ValueError("plan_events length exceeds 18")
        
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("each event in plan_events must be a dict")
        for key in ("verb", "target", "args"):
            if key not in event:
                raise ValueError(f"event missing {key}")
        if event["verb"] not in PLAN_VERBS:
            raise ValueError(f"bad plan event verb: {event['verb']}")
        if not isinstance(event["target"], str) or not event["target"]:
            raise ValueError("plan event target must be a non-empty string")
        if not isinstance(event["args"], dict):
            raise ValueError("event args must be a dict")

    if "user_response" in answer and not isinstance(answer["user_response"], str):
        raise ValueError("user_response must be a string")
    if "audit_tags" in answer:
        if not isinstance(answer["audit_tags"], list) or not all(
            isinstance(tag, str) for tag in answer["audit_tags"]
        ):
            raise ValueError("audit_tags must be a string array")
    if "counterfactual" in answer and not isinstance(answer["counterfactual"], str):
        raise ValueError("counterfactual must be a string")
