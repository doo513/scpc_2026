from __future__ import annotations

from typing import Any

from core.decision import FinalDecision


class ScopeCompiler:
    """Pure projection of disclosure semantics locked in FinalDecision."""

    @staticmethod
    def compile(decision: FinalDecision) -> dict[str, Any]:
        return {
            "mode": decision.disclosure_mode,
            "allowed_fields": list(decision.allowed_fields),
            "excluded_fields": list(decision.excluded_fields),
            "requires_user_confirmation": decision.requires_user_confirmation,
        }


class PolicyCompiler:
    """Pure projection of policy semantics locked in FinalDecision."""

    @staticmethod
    def compile(decision: FinalDecision) -> dict[str, Any]:
        return {
            "risk_flags": list(decision.risk_flags),
            "violations": list(decision.violations),
            "requires_confirmation": decision.requires_user_confirmation,
        }
