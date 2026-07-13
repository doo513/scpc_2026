from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .ontology import CandidateState, ConstraintEffect


BlueprintEffectKind = ConstraintEffect


def project_scope_mode(compiled_mode: str, control: str) -> str:
    """Project a compiled scope through the final execution disposition.

    HOLD exposes no content. ASK is non-executing: raw content is reduced to a
    summary and execution-only status scope is suppressed, while an already
    compiled summary/redaction restriction remains authoritative.
    """
    if control == "hold":
        return "none"
    if control == "ask":
        return {
            "raw": "summary",
            "status_only": "none",
        }.get(compiled_mode, compiled_mode)
    return compiled_mode


@dataclass(frozen=True)
class SlotSpec:
    name: str
    required: bool = True
    default: Any = None


@dataclass(frozen=True)
class BaseBlueprint:
    blueprint_id: str
    action: str
    operation_mode: str
    supported: bool
    required_target_roles: tuple[str, ...]
    slots: tuple[SlotSpec, ...]
    execution_capabilities: tuple[str, ...]
    terminal_verb: str
    default_scope: str


@dataclass(frozen=True)
class BlueprintEffect:
    kind: BlueprintEffectKind
    source_constraint_id: str
    parameters: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class EffectiveBlueprint:
    base: BaseBlueprint
    effects: tuple[BlueprintEffect, ...]
    required_slots: tuple[SlotSpec, ...]
    execution_capabilities: tuple[str, ...]
    scope_mode: str
    supported: bool

    @property
    def amended(self) -> bool:
        return any(
            effect.kind
            in {
                BlueprintEffectKind.ADD_REDACTION,
                BlueprintEffectKind.FORCE_SUMMARY,
                BlueprintEffectKind.LIMIT_DURATION,
                BlueprintEffectKind.RESTRICT_TARGET,
            }
            for effect in self.effects
        )

    @property
    def blocked(self) -> bool:
        return any(
            effect.kind == BlueprintEffectKind.BLOCK_EXECUTION
            for effect in self.effects
        )

    @property
    def requires_confirmation(self) -> bool:
        return any(
            effect.kind == BlueprintEffectKind.ADD_CONFIRMATION
            for effect in self.effects
        )

    def capabilities_for(self, disposition: str) -> tuple[str, ...]:
        if disposition in {
            CandidateState.BLOCKED.value,
            CandidateState.REJECTED.value,
            CandidateState.UNSUPPORTED_RULEPACK.value,
        }:
            return ("read", "guard")
        if disposition in {
            CandidateState.NEEDS_INFORMATION.value,
            CandidateState.NEEDS_CONFIRMATION.value,
            CandidateState.CONFLICTED.value,
        }:
            return ("read", "clarify")
        return self.execution_capabilities

    def to_trace(self) -> dict[str, Any]:
        return {
            "base_id": self.base.blueprint_id,
            "supported": self.supported,
            "required_target_roles": list(self.base.required_target_roles),
            "required_slots": [slot.name for slot in self.required_slots],
            "execution_capabilities": list(self.execution_capabilities),
            "terminal_verb": self.base.terminal_verb,
            "scope_mode": self.scope_mode,
            "effects": [
                {
                    "kind": effect.kind.value,
                    "source_constraint_id": effect.source_constraint_id,
                    "parameters": dict(effect.parameters),
                }
                for effect in self.effects
            ],
        }


@dataclass(frozen=True)
class ResolvedPlanStep:
    verb: str
    target: str
    args: tuple[tuple[str, str], ...]
    optional: bool = False

    def to_event(self) -> dict[str, Any]:
        return {
            "verb": self.verb,
            "target": self.target,
            "args": dict(self.args),
        }


class BlueprintRegistry:
    _DOMAIN_ROLES = {
        "pay": ("merchant",),
        "toggle": ("device_target",),
        "schedule": ("calendar_target",),
    }

    @classmethod
    def resolve(cls, action: str, operation_mode: str) -> BaseBlueprint:
        blueprint_id = f"{action}:{operation_mode}"
        if action == "unresolved":
            return BaseBlueprint(
                blueprint_id,
                action,
                operation_mode,
                True,
                ("unresolved",),
                (SlotSpec("operation"),),
                ("read", "clarify"),
                "clarify",
                "none",
            )
        if operation_mode == "cancel":
            return BaseBlueprint(
                blueprint_id,
                action,
                operation_mode,
                False,
                cls._DOMAIN_ROLES.get(action, ("operation_target",)),
                (SlotSpec("operation_reference"),),
                (),
                "",
                "none",
            )
        if action == "clarify":
            return BaseBlueprint(
                blueprint_id,
                action,
                operation_mode,
                True,
                ("clarification_target",),
                (SlotSpec("clarification_target"),),
                ("read", "clarify"),
                "clarify",
                "none",
            )
        if action in {"local_update", "memory_update"}:
            return BaseBlueprint(
                blueprint_id,
                action,
                operation_mode,
                True,
                ("local_resource",),
                (SlotSpec("local_resource"),),
                ("read", "verify", "update"),
                "update",
                "status_only",
            )
        if action == "dispatch":
            return BaseBlueprint(
                blueprint_id,
                action,
                operation_mode,
                True,
                ("dispatch_destination",),
                (
                    SlotSpec("destination"),
                    SlotSpec("content_scope", required=False, default="summary"),
                ),
                ("read", "summarize", "dispatch"),
                "dispatch",
                "summary",
            )
        if action == "pay":
            slots = (
                (SlotSpec("operation_reference"),)
                if operation_mode == "verify"
                else (
                    SlotSpec("merchant"),
                    SlotSpec("amount"),
                    SlotSpec("method"),
                )
            )
            capabilities = (
                ("read", "verify")
                if operation_mode == "verify"
                else ("read", "verify", "pay")
            )
            return BaseBlueprint(
                blueprint_id,
                action,
                operation_mode,
                True,
                ("merchant",),
                slots,
                capabilities,
                "verify" if operation_mode == "verify" else "pay",
                "none" if operation_mode == "verify" else "status_only",
            )
        if action == "toggle":
            slots = (
                (SlotSpec("operation_reference"),)
                if operation_mode == "verify"
                else (SlotSpec("device_target"), SlotSpec("desired_state"))
            )
            capabilities = (
                ("read", "verify")
                if operation_mode == "verify"
                else ("read", "verify", "toggle")
            )
            return BaseBlueprint(
                blueprint_id,
                action,
                operation_mode,
                True,
                ("device_target",),
                slots,
                capabilities,
                "verify" if operation_mode == "verify" else "toggle",
                "none" if operation_mode == "verify" else "status_only",
            )
        if action == "schedule":
            slots = (
                (SlotSpec("operation_reference"),)
                if operation_mode == "verify"
                else (SlotSpec("event"), SlotSpec("time"))
            )
            capabilities = (
                ("read", "verify")
                if operation_mode == "verify"
                else ("read", "verify", "schedule")
            )
            return BaseBlueprint(
                blueprint_id,
                action,
                operation_mode,
                True,
                ("calendar_target",),
                slots,
                capabilities,
                "verify" if operation_mode == "verify" else "schedule",
                "none" if operation_mode == "verify" else "status_only",
            )
        return BaseBlueprint(
            blueprint_id,
            action,
            operation_mode,
            False,
            (),
            (),
            (),
            "",
            "none",
        )


class BlueprintCompiler:
    @staticmethod
    def apply(
        base: BaseBlueprint,
        constraints: Iterable[Any],
        *,
        raw_dispatch_allowed: bool = False,
    ) -> EffectiveBlueprint:
        effects: list[BlueprintEffect] = []
        for constraint in constraints:
            constraint_id = str(
                getattr(constraint, "constraint_id", "constraint")
            )
            parameters = tuple(getattr(constraint, "parameters", ()) or ())
            effect = getattr(constraint, "effect", None)
            if effect is None:
                raise ValueError(
                    f"constraint '{constraint_id}' has no declared blueprint effect"
                )
            if not isinstance(effect, BlueprintEffectKind):
                effect = BlueprintEffectKind(str(effect))
            effects.append(BlueprintEffect(effect, constraint_id, parameters))

        if raw_dispatch_allowed and base.action == "dispatch":
            effects.append(
                BlueprintEffect(
                    BlueprintEffectKind.ALLOW_RAW,
                    "structured:raw_dispatch_allowed",
                )
            )

        scope_mode = base.default_scope
        capabilities = base.execution_capabilities
        effect_kinds = {effect.kind for effect in effects}
        if base.action == "dispatch":
            if BlueprintEffectKind.ADD_REDACTION in effect_kinds:
                scope_mode = "redacted"
                capabilities = ("read", "redact", "dispatch")
            elif BlueprintEffectKind.FORCE_SUMMARY in effect_kinds:
                scope_mode = "summary"
                capabilities = ("read", "summarize", "dispatch")
            elif BlueprintEffectKind.ALLOW_RAW in effect_kinds:
                scope_mode = "raw"
                capabilities = ("read", "dispatch")

        return EffectiveBlueprint(
            base=base,
            effects=tuple(effects),
            required_slots=base.slots,
            execution_capabilities=capabilities,
            scope_mode=scope_mode,
            supported=base.supported,
        )
