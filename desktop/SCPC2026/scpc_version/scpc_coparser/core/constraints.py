from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Iterable

from .contracts import (
    CONSTRAINT_EFFECT_ASSUMPTION_ID,
    ContractStatus,
    assumption_ids,
)
from .ontology import (
    ConstraintEffect,
    ConstraintType,
    Domain,
    FactStatus,
    Operation,
    ReasonCode,
    RecordType,
    TargetLocality,
    TargetRole,
    constraint_effect_rank,
)
from .plan_requirements import (
    PlanRequirementDelta,
    PlanRequirementDeltaSource,
)
from .records import (
    DurationValue,
    FactRole,
    RecordCode,
    TypedRecordFact,
)
from .rulepacks import (
    CONSTRAINT_CATALOG,
    RULEPACK_REGISTRY,
    BasisReference,
    DomainOperationRulePack,
    RegistryImplementationStatus,
    RulePackKey,
    RuleVariant,
)


class ConstraintFactPolarity(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    CONFLICTED = "conflicted"
    UNRESOLVED = "unresolved"


class ConstraintActivationState(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    CONFLICTED = "conflicted"
    UNRESOLVED = "unresolved"


class EffectParameterSource(str, Enum):
    NONE = "none"
    FACT_PARAMETERS = "fact_parameters"


class EffectAlgebraStatus(str, Enum):
    COMPOSED = "composed"
    CONFLICTED = "conflicted"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class GlobalConstraintRule:
    record_type: RecordType
    constraint_type: ConstraintType
    inactive_codes: tuple[RecordCode, ...] = ()


GLOBAL_CONSTRAINT_RULES = (
    GlobalConstraintRule(RecordType.AMBIGUOUS_FOCAL, ConstraintType.TARGET_BINDING),
    GlobalConstraintRule(RecordType.AMBIGUOUS_TARGET, ConstraintType.TARGET_BINDING),
    GlobalConstraintRule(
        RecordType.AMOUNT_CHANGED,
        ConstraintType.INFORMATION_CONFLICT,
    ),
    GlobalConstraintRule(
        RecordType.CALENDAR_CONFLICT,
        ConstraintType.CALENDAR_CONFLICT,
    ),
    GlobalConstraintRule(
        RecordType.CONSENT,
        ConstraintType.CONSENT,
        (RecordCode.CONSENT_GRANTED,),
    ),
    GlobalConstraintRule(
        RecordType.DURATION_AMBIGUOUS,
        ConstraintType.INFORMATION_CONFLICT,
    ),
    GlobalConstraintRule(
        RecordType.EXTERNAL_SHARE_POLICY,
        ConstraintType.LOCAL_BOUNDARY,
    ),
    GlobalConstraintRule(
        RecordType.GUARDRAIL_LADDER_SIGNAL,
        ConstraintType.UNKNOWN,
    ),
    GlobalConstraintRule(
        RecordType.HEALTH_SHARE_POLICY,
        ConstraintType.SAFETY,
    ),
    GlobalConstraintRule(
        RecordType.MEMORY_CONFLICT,
        ConstraintType.INFORMATION_CONFLICT,
    ),
    GlobalConstraintRule(
        RecordType.MERCHANT_VERIFICATION,
        ConstraintType.PAYMENT_POLICY,
    ),
    GlobalConstraintRule(
        RecordType.PAYMENT_POLICY,
        ConstraintType.PAYMENT_POLICY,
    ),
    GlobalConstraintRule(RecordType.PRIVACY_GUARD, ConstraintType.SECURITY),
    GlobalConstraintRule(RecordType.ROUTINE_SCOPE, ConstraintType.LOCAL_BOUNDARY),
    GlobalConstraintRule(RecordType.SAFETY_MODE, ConstraintType.SAFETY),
    GlobalConstraintRule(RecordType.SECURITY_ALERT, ConstraintType.SECURITY),
    GlobalConstraintRule(
        RecordType.SESSION_SHARE_POLICY,
        ConstraintType.LOCAL_BOUNDARY,
    ),
    GlobalConstraintRule(
        RecordType.TEMPORARY_OVERRIDE_ALLOWED,
        ConstraintType.TEMPORARY_OVERRIDE,
    ),
)


@dataclass(frozen=True)
class GlobalConstraintFact:
    canonical_fact_id: str
    record_type: RecordType
    constraint_type: ConstraintType
    polarity: ConstraintFactPolarity
    semantic_codes: tuple[RecordCode, ...]
    parameters: tuple[tuple[str, str], ...]
    source_fact_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.canonical_fact_id or not self.source_fact_ids:
            raise ValueError("global constraint fact requires identity and provenance")
        if tuple(sorted(set(self.source_fact_ids))) != self.source_fact_ids:
            raise ValueError("constraint source IDs must be unique and sorted")


class GlobalConstraintRegistry:
    production_active = False

    def __init__(
        self,
        rules: Iterable[GlobalConstraintRule] = GLOBAL_CONSTRAINT_RULES,
    ) -> None:
        self.rules = tuple(rules)
        self._by_record_type = {item.record_type: item for item in self.rules}
        self.validate()

    def validate(self) -> None:
        record_types = [item.record_type for item in self.rules]
        if len(record_types) != len(set(record_types)):
            raise ValueError("duplicate global constraint record rule")
        if RecordType.UNKNOWN in self._by_record_type:
            raise ValueError("unknown record type cannot define a constraint rule")

    def collect(
        self,
        records: Iterable[TypedRecordFact],
    ) -> tuple[GlobalConstraintFact, ...]:
        grouped: dict[RecordType, list[TypedRecordFact]] = {}
        for fact in records:
            if fact.status == FactStatus.MISSING:
                continue
            if fact.role != FactRole.CONSTRAINT:
                continue
            if fact.record_type not in self._by_record_type:
                continue
            grouped.setdefault(fact.record_type, []).append(fact)
        return tuple(
            self._normalize(self._by_record_type[record_type], grouped[record_type])
            for record_type in sorted(grouped, key=lambda item: item.value)
        )

    @staticmethod
    def _normalize(
        rule: GlobalConstraintRule,
        facts: list[TypedRecordFact],
    ) -> GlobalConstraintFact:
        source_ids = tuple(
            sorted(
                {
                    source_id
                    for fact in facts
                    for source_id in ((fact.fact_id,) + fact.derived_from)
                }
            )
        )
        codes = tuple(
            sorted(
                {fact.code for fact in facts if fact.code is not None},
                key=lambda item: item.value,
            )
        )
        parameter_sets = {
            (("duration", value.canonical),)
            for fact in facts
            if isinstance((value := fact.semantic_value), DurationValue)
        }
        parameters = next(iter(parameter_sets)) if len(parameter_sets) == 1 else ()
        statuses = {fact.status for fact in facts}
        if FactStatus.CONFLICTED in statuses or len(codes) > 1 or len(parameter_sets) > 1:
            polarity = ConstraintFactPolarity.CONFLICTED
        elif statuses & {FactStatus.INVALID, FactStatus.UNKNOWN}:
            polarity = ConstraintFactPolarity.UNRESOLVED
        elif codes and set(codes) <= set(rule.inactive_codes):
            polarity = ConstraintFactPolarity.INACTIVE
        else:
            polarity = ConstraintFactPolarity.ACTIVE
        return GlobalConstraintFact(
            canonical_fact_id=f"constraint_fact:{rule.record_type.value}",
            record_type=rule.record_type,
            constraint_type=rule.constraint_type,
            polarity=polarity,
            semantic_codes=codes,
            parameters=tuple(sorted(parameters)),
            source_fact_ids=source_ids,
        )


GLOBAL_CONSTRAINT_REGISTRY = GlobalConstraintRegistry()


@dataclass(frozen=True)
class PairApplicability:
    key: RulePackKey
    target_localities: tuple[TargetLocality, ...]

    def __post_init__(self) -> None:
        if not self.target_localities:
            raise ValueError("pair applicability requires a target locality")


@dataclass(frozen=True)
class ConstraintEffectRule:
    source_record_type: RecordType
    effect: ConstraintEffect
    reason_code: ReasonCode
    required_codes: tuple[RecordCode, ...] = ()
    parameter_source: EffectParameterSource = EffectParameterSource.NONE

    def __post_init__(self) -> None:
        constraint_effect_rank(self.effect)


@dataclass(frozen=True)
class PairConstraintSpec:
    constraint_id: str
    constraint_type: ConstraintType
    applicability: tuple[PairApplicability, ...]
    source_record_types: tuple[RecordType, ...]
    effect_rules: tuple[ConstraintEffectRule, ...]
    contract_status: ContractStatus
    basis_refs: tuple[BasisReference, ...]
    assumption_refs: tuple[str, ...]
    version: str

    def __post_init__(self) -> None:
        if not self.constraint_id or not self.applicability:
            raise ValueError("PairConstraintSpec requires identity and applicability")
        if not self.source_record_types or not self.effect_rules:
            raise ValueError("PairConstraintSpec requires facts and effect rules")
        if any(
            rule.source_record_type not in self.source_record_types
            for rule in self.effect_rules
        ):
            raise ValueError("effect rule references undeclared source record type")

    def applicability_for(self, key: RulePackKey) -> PairApplicability | None:
        return next((item for item in self.applicability if item.key == key), None)


def _key(
    domain: Domain,
    operation: Operation,
    variant: RuleVariant | None = None,
) -> RulePackKey:
    return RulePackKey(domain, operation, variant)


def _application(
    key: RulePackKey,
    locality: TargetLocality,
) -> PairApplicability:
    return PairApplicability(key, (locality,))


_CONTENT_SHARE = _key(Domain.CONTENT, Operation.SHARE)
_PAYMENT_EXECUTE = _key(Domain.PAYMENT, Operation.EXECUTE)
_PAYMENT_VERIFY = _key(Domain.PAYMENT, Operation.VERIFY)
_DEVICE_MODIFY = _key(Domain.DEVICE, Operation.MODIFY)
_DEVICE_EXECUTE = _key(
    Domain.DEVICE,
    Operation.EXECUTE,
    RuleVariant.LEGACY_EXECUTE,
)
_CALENDAR_CREATE = _key(Domain.CALENDAR, Operation.CREATE)
_CALENDAR_MODIFY = _key(Domain.CALENDAR, Operation.MODIFY)
_CALENDAR_EXECUTE = _key(
    Domain.CALENDAR,
    Operation.EXECUTE,
    RuleVariant.LEGACY_EXECUTE,
)


PAIR_CONSTRAINT_SPECS = (
    PairConstraintSpec(
        constraint_id="CONSTRAINT-DISPATCH-CONSENT",
        constraint_type=ConstraintType.CONSENT,
        applicability=(
            _application(_CONTENT_SHARE, TargetLocality.EXTERNAL),
        ),
        source_record_types=(RecordType.CONSENT,),
        effect_rules=(
            ConstraintEffectRule(
                RecordType.CONSENT,
                ConstraintEffect.BLOCK_EXECUTION,
                ReasonCode.CONSENT_REVOKED,
                (RecordCode.CONSENT_REVOKED,),
            ),
        ),
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=(BasisReference.TERMS_RECORDS, BasisReference.STEP7_CONTRACT),
        assumption_refs=(CONSTRAINT_EFFECT_ASSUMPTION_ID,),
        version="1.0.0",
    ),
    PairConstraintSpec(
        constraint_id="CONSTRAINT-DISPATCH-SECURITY",
        constraint_type=ConstraintType.SECURITY,
        applicability=(
            _application(_CONTENT_SHARE, TargetLocality.EXTERNAL),
            _application(_PAYMENT_EXECUTE, TargetLocality.DOMAIN),
        ),
        source_record_types=(RecordType.SECURITY_ALERT,),
        effect_rules=(
            ConstraintEffectRule(
                RecordType.SECURITY_ALERT,
                ConstraintEffect.BLOCK_EXECUTION,
                ReasonCode.SECURITY_BLOCK,
            ),
        ),
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=(BasisReference.TERMS_RECORDS, BasisReference.STEP7_CONTRACT),
        assumption_refs=(CONSTRAINT_EFFECT_ASSUMPTION_ID,),
        version="1.0.0",
    ),
    PairConstraintSpec(
        constraint_id="CONSTRAINT-EXTERNAL-SHARE-POLICY",
        constraint_type=ConstraintType.LOCAL_BOUNDARY,
        applicability=(
            _application(_CONTENT_SHARE, TargetLocality.EXTERNAL),
        ),
        source_record_types=(RecordType.EXTERNAL_SHARE_POLICY,),
        effect_rules=(
            ConstraintEffectRule(
                RecordType.EXTERNAL_SHARE_POLICY,
                ConstraintEffect.ADD_REDACTION,
                ReasonCode.EXTERNAL_DISCLOSURE_RESTRICTED,
                (
                    RecordCode.EXTERNAL_RAW_QUOTE_FORBIDDEN,
                    RecordCode.EXTERNAL_RAW_SENSITIVE_FORBIDDEN,
                ),
            ),
            ConstraintEffectRule(
                RecordType.EXTERNAL_SHARE_POLICY,
                ConstraintEffect.FORCE_SUMMARY,
                ReasonCode.EXTERNAL_DISCLOSURE_RESTRICTED,
                (RecordCode.EXTERNAL_SUMMARY_ONLY,),
            ),
            ConstraintEffectRule(
                RecordType.EXTERNAL_SHARE_POLICY,
                ConstraintEffect.BLOCK_EXECUTION,
                ReasonCode.EXTERNAL_DISCLOSURE_BLOCKED,
                (RecordCode.EXTERNAL_DOCTOR_NOTE_FORBIDDEN,),
            ),
        ),
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=(BasisReference.TERMS_RECORDS, BasisReference.STEP7_CONTRACT),
        assumption_refs=(CONSTRAINT_EFFECT_ASSUMPTION_ID,),
        version="1.0.0",
    ),
    PairConstraintSpec(
        constraint_id="CONSTRAINT-PAYMENT-POLICY",
        constraint_type=ConstraintType.PAYMENT_POLICY,
        applicability=(
            _application(_PAYMENT_EXECUTE, TargetLocality.DOMAIN),
            _application(_PAYMENT_VERIFY, TargetLocality.DOMAIN),
        ),
        source_record_types=(RecordType.PAYMENT_POLICY,),
        effect_rules=(
            ConstraintEffectRule(
                RecordType.PAYMENT_POLICY,
                ConstraintEffect.ADD_CONFIRMATION,
                ReasonCode.PAYMENT_POLICY_REVIEW,
            ),
        ),
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=(BasisReference.TERMS_RECORDS, BasisReference.STEP7_CONTRACT),
        assumption_refs=(CONSTRAINT_EFFECT_ASSUMPTION_ID,),
        version="1.0.0",
    ),
    PairConstraintSpec(
        constraint_id="CONSTRAINT-DEVICE-SAFETY",
        constraint_type=ConstraintType.SAFETY,
        applicability=(
            _application(_DEVICE_MODIFY, TargetLocality.DOMAIN),
            _application(_DEVICE_EXECUTE, TargetLocality.DOMAIN),
        ),
        source_record_types=(RecordType.SAFETY_MODE,),
        effect_rules=(
            ConstraintEffectRule(
                RecordType.SAFETY_MODE,
                ConstraintEffect.BLOCK_EXECUTION,
                ReasonCode.SAFETY_BLOCK,
            ),
        ),
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=(BasisReference.TERMS_RECORDS, BasisReference.STEP7_CONTRACT),
        assumption_refs=(CONSTRAINT_EFFECT_ASSUMPTION_ID,),
        version="1.0.0",
    ),
    PairConstraintSpec(
        constraint_id="CONSTRAINT-TEMPORARY-OVERRIDE",
        constraint_type=ConstraintType.TEMPORARY_OVERRIDE,
        applicability=(
            _application(_DEVICE_MODIFY, TargetLocality.DOMAIN),
            _application(_DEVICE_EXECUTE, TargetLocality.DOMAIN),
        ),
        source_record_types=(
            RecordType.TEMPORARY_OVERRIDE_ALLOWED,
            RecordType.DURATION_AMBIGUOUS,
        ),
        effect_rules=(
            ConstraintEffectRule(
                RecordType.TEMPORARY_OVERRIDE_ALLOWED,
                ConstraintEffect.LIMIT_DURATION,
                ReasonCode.TEMPORARY_OVERRIDE_LIMIT,
                parameter_source=EffectParameterSource.FACT_PARAMETERS,
            ),
            ConstraintEffectRule(
                RecordType.DURATION_AMBIGUOUS,
                ConstraintEffect.ADD_CONFIRMATION,
                ReasonCode.DURATION_REQUIRES_CLARIFICATION,
            ),
        ),
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=(BasisReference.TERMS_RECORDS, BasisReference.STEP7_CONTRACT),
        assumption_refs=(CONSTRAINT_EFFECT_ASSUMPTION_ID,),
        version="1.0.0",
    ),
    PairConstraintSpec(
        constraint_id="CONSTRAINT-CALENDAR-CONFLICT",
        constraint_type=ConstraintType.CALENDAR_CONFLICT,
        applicability=(
            _application(_CALENDAR_CREATE, TargetLocality.DOMAIN),
            _application(_CALENDAR_MODIFY, TargetLocality.DOMAIN),
            _application(_CALENDAR_EXECUTE, TargetLocality.DOMAIN),
        ),
        source_record_types=(RecordType.CALENDAR_CONFLICT,),
        effect_rules=(
            ConstraintEffectRule(
                RecordType.CALENDAR_CONFLICT,
                ConstraintEffect.ADD_CONFIRMATION,
                ReasonCode.CALENDAR_CONFLICT,
            ),
        ),
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=(BasisReference.TERMS_RECORDS, BasisReference.STEP7_CONTRACT),
        assumption_refs=(CONSTRAINT_EFFECT_ASSUMPTION_ID,),
        version="1.0.0",
    ),
)


class PairConstraintRegistry:
    production_active = False

    def __init__(
        self,
        specs: Iterable[PairConstraintSpec] = PAIR_CONSTRAINT_SPECS,
    ) -> None:
        self.specs = tuple(specs)
        self._by_id = {item.constraint_id: item for item in self.specs}
        self.validate()

    def lookup(self, constraint_id: str) -> PairConstraintSpec | None:
        return self._by_id.get(constraint_id)

    def validate(self) -> None:
        ids = [item.constraint_id for item in self.specs]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate PairConstraintSpec ID")
        catalog_ids = {item.constraint_id for item in CONSTRAINT_CATALOG}
        if set(ids) != catalog_ids:
            raise ValueError("PairConstraintSpec catalog coverage mismatch")
        if any(
            item.implementation_status != RegistryImplementationStatus.IMPLEMENTED
            or item.activation_stage != 7
            for item in CONSTRAINT_CATALOG
        ):
            raise ValueError("PairConstraintSpec catalog is not implemented")

        known_assumptions = assumption_ids()
        known_record_types = {
            item.record_type for item in GLOBAL_CONSTRAINT_REGISTRY.rules
        }
        pack_by_key = {item.key: item for item in RULEPACK_REGISTRY.rulepacks}
        for spec in self.specs:
            if set(spec.assumption_refs) - known_assumptions:
                raise ValueError(f"unknown constraint assumption: {spec.constraint_id}")
            if not spec.basis_refs:
                raise ValueError(f"missing constraint basis: {spec.constraint_id}")
            if set(spec.source_record_types) - known_record_types:
                raise ValueError(
                    f"constraint source lacks global fact rule: {spec.constraint_id}"
                )
            keys = [item.key for item in spec.applicability]
            if len(keys) != len(set(keys)):
                raise ValueError(
                    f"duplicate constraint applicability: {spec.constraint_id}"
                )
            for key in keys:
                pack = pack_by_key.get(key)
                if pack is None or spec.constraint_id not in pack.pair_constraint_ids:
                    raise ValueError(
                        f"constraint applicability differs from RulePack: {spec.constraint_id}"
                    )
        for pack in RULEPACK_REGISTRY.rulepacks:
            for constraint_id in pack.pair_constraint_ids:
                spec = self._by_id[constraint_id]
                if spec.applicability_for(pack.key) is None:
                    raise ValueError(
                        f"RulePack constraint lacks applicability: {pack.rule_id}:{constraint_id}"
                    )


PAIR_CONSTRAINT_REGISTRY = PairConstraintRegistry()


@dataclass(frozen=True)
class ConstraintCandidateContext:
    candidate_id: str
    rulepack_key: RulePackKey
    focal_id: str
    target_id: str
    target_role: TargetRole
    target_locality: TargetLocality

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.focal_id or not self.target_id:
            raise ValueError("constraint candidate context requires stable identities")
        if self.target_role == TargetRole.UNRESOLVED:
            raise ValueError("unresolved target role cannot activate pair constraints")
        if self.target_locality == TargetLocality.UNKNOWN:
            raise ValueError("unknown target locality cannot activate pair constraints")


@dataclass(frozen=True)
class ConstraintActivationScope:
    domain: Domain
    operation: Operation
    target_id: str
    target_role: TargetRole
    target_locality: TargetLocality

    @property
    def canonical_key(self) -> tuple[str, ...]:
        return (
            self.domain.value,
            self.operation.value,
            self.target_id,
            self.target_role.value,
            self.target_locality.value,
        )

    @property
    def canonical_text(self) -> str:
        return "|".join(self.canonical_key)


@dataclass(frozen=True)
class ConstraintEffectInstance:
    effect_id: str
    effect: ConstraintEffect
    activation_scope: ConstraintActivationScope
    parameters: tuple[tuple[str, str], ...]
    source_constraint_ids: tuple[str, ...]
    source_fact_ids: tuple[str, ...]
    reason_code_ids: tuple[ReasonCode, ...]

    def __post_init__(self) -> None:
        constraint_effect_rank(self.effect)
        if not self.effect_id or not self.source_constraint_ids:
            raise ValueError("constraint effect requires identity and source")
        if tuple(sorted(self.parameters)) != self.parameters:
            raise ValueError("constraint effect parameters must be canonical")
        if tuple(sorted(set(self.source_constraint_ids))) != self.source_constraint_ids:
            raise ValueError("constraint effect source IDs must be unique and sorted")
        if tuple(sorted(set(self.source_fact_ids))) != self.source_fact_ids:
            raise ValueError("constraint effect fact IDs must be unique and sorted")
        if tuple(
            sorted(set(self.reason_code_ids), key=lambda item: item.value)
        ) != self.reason_code_ids:
            raise ValueError("constraint effect reason codes must be unique and sorted")

    @property
    def canonical_key(self) -> tuple[object, ...]:
        return (
            self.effect,
            self.activation_scope.canonical_key,
            tuple(sorted(self.parameters)),
        )


@dataclass(frozen=True)
class CandidateConstraint:
    constraint_id: str
    constraint_type: ConstraintType
    source_fact_ids: tuple[str, ...]
    activation_scope: ConstraintActivationScope
    applied_candidate_id: str
    effects: tuple[ConstraintEffectInstance, ...]
    reason_code_ids: tuple[ReasonCode, ...]
    state: ConstraintActivationState

    def __post_init__(self) -> None:
        if not self.constraint_id or not self.applied_candidate_id:
            raise ValueError("candidate constraint requires stable identity")
        if tuple(sorted(set(self.source_fact_ids))) != self.source_fact_ids:
            raise ValueError("candidate constraint fact IDs must be unique and sorted")
        if any(
            effect.activation_scope != self.activation_scope
            for effect in self.effects
        ):
            raise ValueError("constraint effect scope differs from its constraint")
        if self.state != ConstraintActivationState.ACTIVE and self.effects:
            raise ValueError("non-active constraint cannot emit effects")

    @property
    def effect_ids(self) -> tuple[str, ...]:
        return tuple(item.effect_id for item in self.effects)


@dataclass(frozen=True)
class PairConstraintEvaluation:
    constraint_id: str
    candidate_id: str
    state: ConstraintActivationState
    reason: str
    constraint: CandidateConstraint | None = None

    def __post_init__(self) -> None:
        if self.constraint is not None:
            if self.constraint.constraint_id != self.constraint_id:
                raise ValueError("constraint evaluation identity mismatch")
            if self.constraint.applied_candidate_id != self.candidate_id:
                raise ValueError("constraint evaluation candidate mismatch")
            if self.constraint.state != self.state:
                raise ValueError("constraint evaluation state mismatch")


@dataclass(frozen=True)
class ConstraintActivationBundle:
    candidate_id: str
    evaluations: tuple[PairConstraintEvaluation, ...]

    def __post_init__(self) -> None:
        if any(item.candidate_id != self.candidate_id for item in self.evaluations):
            raise ValueError("activation bundle contains a different candidate")
        ids = [item.constraint_id for item in self.evaluations]
        if len(ids) != len(set(ids)):
            raise ValueError("activation bundle contains duplicate constraint IDs")

    @property
    def constraints(self) -> tuple[CandidateConstraint, ...]:
        return tuple(
            item.constraint
            for item in self.evaluations
            if item.constraint is not None
        )

    @property
    def active_constraints(self) -> tuple[CandidateConstraint, ...]:
        return tuple(
            item
            for item in self.constraints
            if item.state == ConstraintActivationState.ACTIVE
        )


class PairConstraintActivator:
    @classmethod
    def activate(
        cls,
        *,
        context: ConstraintCandidateContext,
        rulepack: DomainOperationRulePack,
        global_facts: Iterable[GlobalConstraintFact],
    ) -> ConstraintActivationBundle:
        if context.rulepack_key != rulepack.key:
            raise ValueError("candidate and RulePack keys differ")
        facts = tuple(global_facts)
        fact_by_type = {item.record_type: item for item in facts}
        if len(fact_by_type) != len(facts):
            raise ValueError("global constraint facts contain duplicate record types")
        evaluations = tuple(
            cls._evaluate_spec(
                context,
                PAIR_CONSTRAINT_REGISTRY.lookup(constraint_id),
                fact_by_type,
            )
            for constraint_id in sorted(rulepack.pair_constraint_ids)
        )
        return ConstraintActivationBundle(context.candidate_id, evaluations)

    @classmethod
    def _evaluate_spec(
        cls,
        context: ConstraintCandidateContext,
        spec: PairConstraintSpec | None,
        fact_by_type: dict[RecordType, GlobalConstraintFact],
    ) -> PairConstraintEvaluation:
        if spec is None:
            raise ValueError("RulePack references an unknown PairConstraintSpec")
        applicability = spec.applicability_for(context.rulepack_key)
        if applicability is None:
            raise ValueError("PairConstraintSpec does not cover the candidate RulePack")
        if context.target_locality not in applicability.target_localities:
            return PairConstraintEvaluation(
                spec.constraint_id,
                context.candidate_id,
                ConstraintActivationState.INACTIVE,
                "target_scope_mismatch",
            )
        facts = tuple(
            fact_by_type[record_type]
            for record_type in spec.source_record_types
            if record_type in fact_by_type
        )
        if not facts:
            return PairConstraintEvaluation(
                spec.constraint_id,
                context.candidate_id,
                ConstraintActivationState.INACTIVE,
                "source_fact_absent",
            )
        if any(item.polarity == ConstraintFactPolarity.CONFLICTED for item in facts):
            return cls._non_active_constraint(
                context,
                spec,
                facts,
                ConstraintActivationState.CONFLICTED,
                ReasonCode.CONSTRAINT_FACT_CONFLICT,
                "source_fact_conflicted",
            )
        if any(item.polarity == ConstraintFactPolarity.UNRESOLVED for item in facts):
            return cls._non_active_constraint(
                context,
                spec,
                facts,
                ConstraintActivationState.UNRESOLVED,
                ReasonCode.UNKNOWN,
                "source_fact_unresolved",
            )
        active_facts = tuple(
            item for item in facts if item.polarity == ConstraintFactPolarity.ACTIVE
        )
        if not active_facts:
            return PairConstraintEvaluation(
                spec.constraint_id,
                context.candidate_id,
                ConstraintActivationState.INACTIVE,
                "source_fact_inactive",
            )

        scope = cls._scope(context)
        effects: list[ConstraintEffectInstance] = []
        used_facts: list[GlobalConstraintFact] = []
        for rule in spec.effect_rules:
            fact = next(
                (
                    item
                    for item in active_facts
                    if item.record_type == rule.source_record_type
                    and (
                        not rule.required_codes
                        or bool(set(item.semantic_codes) & set(rule.required_codes))
                    )
                ),
                None,
            )
            if fact is None:
                continue
            parameters = (
                fact.parameters
                if rule.parameter_source == EffectParameterSource.FACT_PARAMETERS
                else ()
            )
            if (
                rule.parameter_source == EffectParameterSource.FACT_PARAMETERS
                and not parameters
            ):
                return cls._non_active_constraint(
                    context,
                    spec,
                    (fact,),
                    ConstraintActivationState.UNRESOLVED,
                    ReasonCode.UNKNOWN,
                    "required_effect_parameters_missing",
                )
            used_facts.append(fact)
            effects.append(
                ConstraintEffectInstance(
                    effect_id=cls._effect_id(
                        context,
                        spec,
                        rule.source_record_type,
                        rule.effect,
                        parameters,
                    ),
                    effect=rule.effect,
                    activation_scope=scope,
                    parameters=parameters,
                    source_constraint_ids=(spec.constraint_id,),
                    source_fact_ids=fact.source_fact_ids,
                    reason_code_ids=(rule.reason_code,),
                )
            )
        if not effects:
            return cls._non_active_constraint(
                context,
                spec,
                active_facts,
                ConstraintActivationState.UNRESOLVED,
                ReasonCode.UNKNOWN,
                "active_fact_has_no_effect_rule",
            )
        source_ids = tuple(
            sorted(
                {
                    source_id
                    for fact in used_facts
                    for source_id in fact.source_fact_ids
                }
            )
        )
        reason_codes = tuple(
            sorted(
                {code for effect in effects for code in effect.reason_code_ids},
                key=lambda item: item.value,
            )
        )
        constraint = CandidateConstraint(
            constraint_id=spec.constraint_id,
            constraint_type=spec.constraint_type,
            source_fact_ids=source_ids,
            activation_scope=scope,
            applied_candidate_id=context.candidate_id,
            effects=tuple(
                sorted(
                    effects,
                    key=lambda item: (
                        constraint_effect_rank(item.effect),
                        item.effect_id,
                    ),
                )
            ),
            reason_code_ids=reason_codes,
            state=ConstraintActivationState.ACTIVE,
        )
        return PairConstraintEvaluation(
            spec.constraint_id,
            context.candidate_id,
            ConstraintActivationState.ACTIVE,
            "pair_scope_and_fact_matched",
            constraint,
        )

    @classmethod
    def _non_active_constraint(
        cls,
        context: ConstraintCandidateContext,
        spec: PairConstraintSpec,
        facts: tuple[GlobalConstraintFact, ...],
        state: ConstraintActivationState,
        reason_code: ReasonCode,
        reason: str,
    ) -> PairConstraintEvaluation:
        source_ids = tuple(
            sorted(
                {
                    source_id
                    for fact in facts
                    for source_id in fact.source_fact_ids
                }
            )
        )
        constraint = CandidateConstraint(
            constraint_id=spec.constraint_id,
            constraint_type=spec.constraint_type,
            source_fact_ids=source_ids,
            activation_scope=cls._scope(context),
            applied_candidate_id=context.candidate_id,
            effects=(),
            reason_code_ids=(reason_code,),
            state=state,
        )
        return PairConstraintEvaluation(
            spec.constraint_id,
            context.candidate_id,
            state,
            reason,
            constraint,
        )

    @staticmethod
    def _scope(context: ConstraintCandidateContext) -> ConstraintActivationScope:
        return ConstraintActivationScope(
            domain=context.rulepack_key.domain,
            operation=context.rulepack_key.operation,
            target_id=context.target_id,
            target_role=context.target_role,
            target_locality=context.target_locality,
        )

    @staticmethod
    def _effect_id(
        context: ConstraintCandidateContext,
        spec: PairConstraintSpec,
        record_type: RecordType,
        effect: ConstraintEffect,
        parameters: tuple[tuple[str, str], ...],
    ) -> str:
        payload = json.dumps(
            {
                "candidate": context.candidate_id,
                "constraint": spec.constraint_id,
                "record_type": record_type.value,
                "effect": effect.value,
                "parameters": parameters,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("ascii")).hexdigest()[:16]
        return f"constraint_effect:{digest}"


@dataclass(frozen=True)
class EffectConflict:
    conflict_id: str
    effect: ConstraintEffect | None
    reason: str
    source_constraint_ids: tuple[str, ...] = ()
    source_effect_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EffectAlgebraResult:
    status: EffectAlgebraStatus
    effects: tuple[ConstraintEffectInstance, ...]
    conflicts: tuple[EffectConflict, ...]

    @property
    def blocks_execution(self) -> bool:
        return any(item.effect == ConstraintEffect.BLOCK_EXECUTION for item in self.effects)

    def to_plan_requirement_deltas(self) -> tuple[PlanRequirementDelta, ...]:
        if self.status != EffectAlgebraStatus.COMPOSED:
            raise ValueError("unresolved effect algebra cannot modify plan requirements")
        return tuple(
            PlanRequirementDelta(
                effect_id=item.effect_id,
                effect_kind=item.effect,
                source_id=item.effect_id,
                scope=item.activation_scope.canonical_text,
                source_kind=PlanRequirementDeltaSource.ACTIVE_CONSTRAINT,
                parameters=item.parameters,
            )
            for item in self.effects
        )


class ConstraintEffectAlgebra:
    @classmethod
    def compose(
        cls,
        constraints: Iterable[CandidateConstraint],
    ) -> EffectAlgebraResult:
        rows = tuple(constraints)
        candidate_ids = {item.applied_candidate_id for item in rows}
        scopes = {item.activation_scope for item in rows}
        if len(candidate_ids) > 1 or len(scopes) > 1:
            raise ValueError("effect algebra cannot combine different candidates or scopes")
        unresolved = tuple(
            item
            for item in rows
            if item.state == ConstraintActivationState.UNRESOLVED
        )
        conflicted = tuple(
            item
            for item in rows
            if item.state == ConstraintActivationState.CONFLICTED
        )
        if unresolved or conflicted:
            state = (
                EffectAlgebraStatus.CONFLICTED
                if conflicted
                else EffectAlgebraStatus.UNRESOLVED
            )
            sources = tuple(
                sorted(
                    {
                        item.constraint_id
                        for item in unresolved + conflicted
                    }
                )
            )
            return EffectAlgebraResult(
                state,
                (),
                (
                    EffectConflict(
                        conflict_id="constraint_activation_not_resolved",
                        effect=None,
                        reason=state.value,
                        source_constraint_ids=sources,
                    ),
                ),
            )

        effects = [
            effect
            for constraint in rows
            if constraint.state == ConstraintActivationState.ACTIVE
            for effect in constraint.effects
        ]
        for effect in effects:
            constraint_effect_rank(effect.effect)
        merged = cls._merge_idempotent(effects)
        conflicts = cls._parameter_conflicts(merged)
        return EffectAlgebraResult(
            EffectAlgebraStatus.CONFLICTED
            if conflicts
            else EffectAlgebraStatus.COMPOSED,
            merged,
            conflicts,
        )

    @classmethod
    def _merge_idempotent(
        cls,
        effects: Iterable[ConstraintEffectInstance],
    ) -> tuple[ConstraintEffectInstance, ...]:
        grouped: dict[tuple[object, ...], list[ConstraintEffectInstance]] = {}
        for effect in effects:
            grouped.setdefault(effect.canonical_key, []).append(effect)
        merged = [cls._merge_group(group) for group in grouped.values()]
        return tuple(
            sorted(
                merged,
                key=lambda item: (
                    constraint_effect_rank(item.effect),
                    item.activation_scope.canonical_key,
                    item.parameters,
                    item.effect_id,
                ),
            )
        )

    @staticmethod
    def _merge_group(
        group: list[ConstraintEffectInstance],
    ) -> ConstraintEffectInstance:
        first = min(group, key=lambda item: item.effect_id)
        payload = json.dumps(
            {
                "effect": first.effect.value,
                "scope": first.activation_scope.canonical_key,
                "parameters": first.parameters,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("ascii")).hexdigest()[:16]
        return ConstraintEffectInstance(
            effect_id=f"effective_constraint:{digest}",
            effect=first.effect,
            activation_scope=first.activation_scope,
            parameters=first.parameters,
            source_constraint_ids=tuple(
                sorted(
                    {
                        source
                        for item in group
                        for source in item.source_constraint_ids
                    }
                )
            ),
            source_fact_ids=tuple(
                sorted(
                    {
                        source
                        for item in group
                        for source in item.source_fact_ids
                    }
                )
            ),
            reason_code_ids=tuple(
                sorted(
                    {
                        code
                        for item in group
                        for code in item.reason_code_ids
                    },
                    key=lambda item: item.value,
                )
            ),
        )

    @staticmethod
    def _parameter_conflicts(
        effects: tuple[ConstraintEffectInstance, ...],
    ) -> tuple[EffectConflict, ...]:
        duration_effects = tuple(
            item for item in effects if item.effect == ConstraintEffect.LIMIT_DURATION
        )
        parameter_sets = {item.parameters for item in duration_effects}
        if len(parameter_sets) <= 1:
            return ()
        return (
            EffectConflict(
                conflict_id="conflicting_duration_limits",
                effect=ConstraintEffect.LIMIT_DURATION,
                reason="no_confirmed_duration_precedence",
                source_constraint_ids=tuple(
                    sorted(
                        {
                            constraint_id
                            for item in duration_effects
                            for constraint_id in item.source_constraint_ids
                        }
                    )
                ),
                source_effect_ids=tuple(
                    sorted(item.effect_id for item in duration_effects)
                ),
            ),
        )


def validate_constraint_registries() -> None:
    GLOBAL_CONSTRAINT_REGISTRY.validate()
    PAIR_CONSTRAINT_REGISTRY.validate()
