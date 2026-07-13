from __future__ import annotations

from .ontology import DisclosureMode, ExecutionDisposition, PlanStepType


CONTROL_VALUES = {item.value for item in ExecutionDisposition}

SCOPE_MODES = {item.value for item in DisclosureMode}

PLAN_VERBS = {item.value for item in PlanStepType}

FIXED_META = {
    "uses_external_api": False,
    "fixed_slm_policy": "local_fixed_slm_only",
    "model_id": "scpc-final-fixed-slm-local-facade",
    "temperature": 0.0,
    "seed": 42,
}

# Plan args canonical buckets (Ontology)
PLAN_PURPOSES = {
    "inspect_context",
    "minimal_disclosure",
    "local_update",
    "route_resolution_required",
    "invalidated_precondition",
    "strict_share_policy",
    "clarify_precondition",
}

PLAN_REASONS = {
    "precondition_invalidated",
    "route_resolution_required",
    "user_confirmation_required",
    "security_or_safety_block",
    "memory_conflict",
    "precondition_changed",
}

PLAN_SCOPES = {
    "raw",
    "summary",
    "redacted",
    "status_only",
    "none",
    "local_update",
}
