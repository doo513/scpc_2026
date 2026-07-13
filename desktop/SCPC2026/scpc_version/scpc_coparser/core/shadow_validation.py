from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .contracts import BUNDLE_ASSUMPTION_ID, TARGET_ASSUMPTION_ID
from .decision_ir import (
    AggregateOutputStatus,
    DecisionBundle,
    DecisionProjectionSet,
    ResponseTargetMappingStatus,
)
from .fallbacks import FallbackEdgeRegistry
from .ontology import (
    CapabilityType,
    ConstraintEffect,
    DisclosureMode,
    ExecutionDisposition,
)
from .plan_requirements import InternalTransformType
from .projection_compilers import ProjectionCompiler, ProjectionCompilerConfig
from .session_overlay import RollbackPlanValidation


class ValidationSeverity(str, Enum):
    ERROR = "error"
    DIAGNOSTIC = "diagnostic"


class ShadowValidationCode(str, Enum):
    BUNDLE_LINEAGE_MISMATCH = "BUNDLE_LINEAGE_MISMATCH"
    PROJECTION_DECISION_MISMATCH = "PROJECTION_DECISION_MISMATCH"
    PROJECTION_LOCK_MISMATCH = "PROJECTION_LOCK_MISMATCH"
    COMPILED_OUTPUT_MISMATCH = "COMPILED_OUTPUT_MISMATCH"
    TARGET_MAPPING_UNRESOLVED = "TARGET_MAPPING_UNRESOLVED"
    MULTI_OUTPUT_UNRESOLVED = "MULTI_OUTPUT_UNRESOLVED"
    TERMINAL_MAPPING_MISMATCH = "TERMINAL_MAPPING_MISMATCH"
    CONSTRAINT_LINEAGE_MISSING = "CONSTRAINT_LINEAGE_MISSING"
    SCOPE_EFFECT_LINEAGE_MISSING = "SCOPE_EFFECT_LINEAGE_MISSING"
    SCOPE_MODE_INCOMPATIBLE = "SCOPE_MODE_INCOMPATIBLE"
    CONFIRMATION_EFFECT_MISSING = "CONFIRMATION_EFFECT_MISSING"
    TRANSFORM_REQUIREMENT_MISSING = "TRANSFORM_REQUIREMENT_MISSING"
    CAPABILITY_COVERAGE_MISMATCH = "CAPABILITY_COVERAGE_MISMATCH"
    FALLBACK_EDGE_MISSING = "FALLBACK_EDGE_MISSING"
    FALLBACK_AUTHORIZATION_MISMATCH = "FALLBACK_AUTHORIZATION_MISMATCH"
    ROLLBACK_RELEASE_INVALID = "ROLLBACK_RELEASE_INVALID"


@dataclass(frozen=True)
class ShadowValidationFinding:
    code: ShadowValidationCode
    severity: ValidationSeverity
    decision_id: str
    detail: str
    assumption_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if tuple(sorted(set(self.assumption_refs))) != self.assumption_refs:
            raise ValueError("validation assumption references must be canonical")

    @property
    def canonical_key(self) -> tuple[str, ...]:
        return (
            self.severity.value,
            self.code.value,
            self.decision_id,
            self.detail,
        )


@dataclass(frozen=True)
class ShadowValidationReport:
    findings: tuple[ShadowValidationFinding, ...]

    def __post_init__(self) -> None:
        if tuple(sorted(self.findings, key=lambda item: item.canonical_key)) != (
            self.findings
        ):
            raise ValueError("validation findings must be canonical")

    @property
    def hard_valid(self) -> bool:
        return not any(
            finding.severity == ValidationSeverity.ERROR
            for finding in self.findings
        )

    @property
    def error_codes(self) -> tuple[ShadowValidationCode, ...]:
        return tuple(
            sorted(
                {
                    finding.code
                    for finding in self.findings
                    if finding.severity == ValidationSeverity.ERROR
                },
                key=lambda item: item.value,
            )
        )

    @property
    def diagnostic_codes(self) -> tuple[ShadowValidationCode, ...]:
        return tuple(
            sorted(
                {
                    finding.code
                    for finding in self.findings
                    if finding.severity == ValidationSeverity.DIAGNOSTIC
                },
                key=lambda item: item.value,
            )
        )


class ShadowConsistencyValidator:
    production_active = False

    @classmethod
    def validate(
        cls,
        *,
        bundle: DecisionBundle,
        projections: DecisionProjectionSet,
        compiled: dict[str, dict[str, Any]],
        compiler_config: ProjectionCompilerConfig,
        fallback_registry: FallbackEdgeRegistry,
        rollback_validation: RollbackPlanValidation | None = None,
    ) -> ShadowValidationReport:
        findings: list[ShadowValidationFinding] = []
        bundle.verify_lock()
        if (
            projections.bundle_id != bundle.bundle_id
            or projections.source_bundle_lock_digest != bundle.bundle_lock_digest
        ):
            findings.append(
                cls._error(
                    ShadowValidationCode.BUNDLE_LINEAGE_MISMATCH,
                    "",
                    "ProjectionSet is not derived from the supplied DecisionBundle",
                )
            )

        decisions = {item.decision_id: item for item in bundle.sub_decisions}
        scopes = {item.decision_id: item for item in projections.scopes}
        policies = {item.decision_id: item for item in projections.policies}
        plans = {item.decision_id: item for item in projections.plans}
        decision_ids = set(decisions)
        if set(scopes) != decision_ids or set(policies) != decision_ids or set(plans) != decision_ids:
            findings.append(
                cls._error(
                    ShadowValidationCode.PROJECTION_DECISION_MISMATCH,
                    "",
                    "Projection decision IDs differ from the locked bundle",
                )
            )

        try:
            expected_compiled = ProjectionCompiler.compile(
                projections,
                compiler_config,
            )
        except ValueError as exc:
            expected_compiled = {}
            findings.append(
                cls._error(
                    ShadowValidationCode.PROJECTION_LOCK_MISMATCH,
                    "",
                    str(exc),
                )
            )
        if compiled != expected_compiled:
            findings.append(
                cls._error(
                    ShadowValidationCode.COMPILED_OUTPUT_MISMATCH,
                    "",
                    "compiled fields are not the pure Projection output",
                )
            )

        for decision_id in sorted(decision_ids & set(scopes) & set(policies) & set(plans)):
            decision = decisions[decision_id]
            source_digests = {
                scopes[decision_id].source_lock_digest,
                policies[decision_id].source_lock_digest,
                plans[decision_id].source_lock_digest,
            }
            if source_digests != {decision.lock_digest}:
                findings.append(
                    cls._error(
                        ShadowValidationCode.PROJECTION_LOCK_MISMATCH,
                        decision_id,
                        "projection fields do not share the SubDecisionIR lock",
                    )
                )
            cls._validate_target_mapping(decision, findings)
            cls._validate_terminal(decision, findings)
            cls._validate_constraint_coverage(decision, findings)
            cls._validate_scope_effects(decision, findings)
            cls._validate_capabilities(decision, findings)
            cls._validate_fallback(decision, fallback_registry, findings)

        if bundle.aggregate_output_status == AggregateOutputStatus.MULTIPLE_UNRESOLVED:
            findings.append(
                ShadowValidationFinding(
                    ShadowValidationCode.MULTI_OUTPUT_UNRESOLVED,
                    ValidationSeverity.DIAGNOSTIC,
                    "",
                    "official aggregate output rule is unresolved",
                    (BUNDLE_ASSUMPTION_ID,),
                )
            )
        if rollback_validation is not None and not rollback_validation.valid:
            findings.append(
                cls._error(
                    ShadowValidationCode.ROLLBACK_RELEASE_INVALID,
                    "",
                    ",".join(rollback_validation.error_codes),
                )
            )
        return ShadowValidationReport(
            tuple(sorted(findings, key=lambda item: item.canonical_key))
        )

    @staticmethod
    def _error(
        code: ShadowValidationCode,
        decision_id: str,
        detail: str,
    ) -> ShadowValidationFinding:
        return ShadowValidationFinding(
            code,
            ValidationSeverity.ERROR,
            decision_id,
            detail,
        )

    @classmethod
    def _validate_target_mapping(cls, decision, findings) -> None:
        binding = decision.response_target_binding
        if binding.mapping_status != ResponseTargetMappingStatus.CONFIRMED:
            assumptions = tuple(
                sorted(
                    set(binding.contract_reference_ids) | {TARGET_ASSUMPTION_ID}
                )
            )
            findings.append(
                ShadowValidationFinding(
                    ShadowValidationCode.TARGET_MAPPING_UNRESOLVED,
                    ValidationSeverity.DIAGNOSTIC,
                    decision.decision_id,
                    "response target mapping is not an official confirmed contract",
                    assumptions,
                )
            )

    @classmethod
    def _validate_terminal(cls, decision, findings) -> None:
        terminal_steps = tuple(
            step for step in decision.plan_decision.steps if step.semantic_terminal
        )
        if decision.execution_disposition in {
            ExecutionDisposition.PROCEED,
            ExecutionDisposition.AMEND,
        }:
            requirements = decision.final_plan_requirements
            valid = (
                requirements is not None
                and len(terminal_steps) == 1
                and terminal_steps[0].verb == requirements.semantic_terminal
            )
        else:
            valid = not terminal_steps
        if not valid:
            findings.append(
                cls._error(
                    ShadowValidationCode.TERMINAL_MAPPING_MISMATCH,
                    decision.decision_id,
                    "locked disposition and semantic terminal are incompatible",
                )
            )

    @classmethod
    def _validate_constraint_coverage(cls, decision, findings) -> None:
        covered = set(decision.policy.source_constraint_ids)
        covered.update(
            constraint_id
            for safeguard in decision.applied_safeguards
            for constraint_id in safeguard.source_constraint_ids
        )
        missing = {
            constraint.constraint_id
            for constraint in decision.active_constraints
            if constraint.constraint_id not in covered
        }
        if missing:
            findings.append(
                cls._error(
                    ShadowValidationCode.CONSTRAINT_LINEAGE_MISSING,
                    decision.decision_id,
                    ",".join(sorted(missing)),
                )
            )

    @classmethod
    def _validate_scope_effects(cls, decision, findings) -> None:
        by_kind: dict[ConstraintEffect, set[str]] = {}
        for safeguard in decision.applied_safeguards:
            by_kind.setdefault(safeguard.effect, set()).add(safeguard.effect_id)
        scope_effect_ids = set().union(
            by_kind.get(ConstraintEffect.ADD_REDACTION, set()),
            by_kind.get(ConstraintEffect.FORCE_SUMMARY, set()),
            by_kind.get(ConstraintEffect.ADD_CONFIRMATION, set()),
        )
        if not scope_effect_ids <= set(decision.disclosure.source_effect_ids):
            findings.append(
                cls._error(
                    ShadowValidationCode.SCOPE_EFFECT_LINEAGE_MISSING,
                    decision.decision_id,
                    "scope-affecting safeguard is absent from disclosure lineage",
                )
            )
        has_redaction = bool(by_kind.get(ConstraintEffect.ADD_REDACTION))
        has_summary = bool(by_kind.get(ConstraintEffect.FORCE_SUMMARY))
        expected_mode = (
            DisclosureMode.SUMMARY
            if has_summary
            else DisclosureMode.REDACTED
            if has_redaction
            else None
        )
        if expected_mode is not None and decision.disclosure.mode != expected_mode:
            findings.append(
                cls._error(
                    ShadowValidationCode.SCOPE_MODE_INCOMPATIBLE,
                    decision.decision_id,
                    f"expected {expected_mode.value} from active safeguard",
                )
            )
        if by_kind.get(ConstraintEffect.ADD_CONFIRMATION) and not (
            decision.disclosure.requires_user_confirmation
            and decision.policy.requires_confirmation
        ):
            findings.append(
                cls._error(
                    ShadowValidationCode.CONFIRMATION_EFFECT_MISSING,
                    decision.decision_id,
                    "confirmation safeguard is absent from locked outputs",
                )
            )
        required_transforms = set(decision.required_internal_transforms)
        required_platform = set(decision.required_platform_capabilities)
        missing_transforms: set[InternalTransformType] = set()
        if has_redaction and not (
            InternalTransformType.REDACT_CONTENT in required_transforms
            or CapabilityType.REDACT in required_platform
        ):
            missing_transforms.add(InternalTransformType.REDACT_CONTENT)
        if has_summary and not (
            InternalTransformType.SUMMARIZE_CONTENT in required_transforms
            or CapabilityType.SUMMARIZE in required_platform
        ):
            missing_transforms.add(InternalTransformType.SUMMARIZE_CONTENT)
        if missing_transforms:
            findings.append(
                cls._error(
                    ShadowValidationCode.TRANSFORM_REQUIREMENT_MISSING,
                    decision.decision_id,
                    ",".join(sorted(item.value for item in missing_transforms)),
                )
            )

    @classmethod
    def _validate_capabilities(cls, decision, findings) -> None:
        if decision.execution_disposition not in {
            ExecutionDisposition.PROCEED,
            ExecutionDisposition.AMEND,
        }:
            return
        projected = tuple(step.capability for step in decision.plan_decision.steps)
        if projected != decision.required_platform_capabilities or not set(projected) <= set(
            decision.available_platform_capabilities
        ):
            findings.append(
                cls._error(
                    ShadowValidationCode.CAPABILITY_COVERAGE_MISMATCH,
                    decision.decision_id,
                    "projected platform actions differ from locked requirements",
                )
            )

    @classmethod
    def _validate_fallback(cls, decision, registry, findings) -> None:
        origin = decision.fallback_origin
        if origin is None:
            return
        edge = next(
            (item for item in registry.edges if item.edge_id == origin.edge_id),
            None,
        )
        if edge is None:
            findings.append(
                cls._error(
                    ShadowValidationCode.FALLBACK_EDGE_MISSING,
                    decision.decision_id,
                    origin.edge_id,
                )
            )
            return
        if (
            not edge.is_authorized
            or edge.authorization.reference_ids
            != origin.authorization_reference_ids
            or origin.destination_candidate_id != decision.selected_candidate_id
        ):
            findings.append(
                cls._error(
                    ShadowValidationCode.FALLBACK_AUTHORIZATION_MISMATCH,
                    decision.decision_id,
                    origin.edge_id,
                )
            )


def validate_shadow_validation_contract() -> None:
    if ShadowConsistencyValidator.production_active:
        raise ValueError("Step 12 cross-layer validator must remain shadow-only")
