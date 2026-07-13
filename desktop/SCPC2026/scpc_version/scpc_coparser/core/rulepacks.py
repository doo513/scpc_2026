from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from collections.abc import Callable, Hashable
from typing import Any, Iterable

from .contracts import (
    ACTIONS_ASSUMPTION_ID,
    TARGET_ASSUMPTION_ID,
    ContractStatus,
    assumption_ids,
)
from .ontology import (
    CandidateState,
    DisclosureMode,
    Domain,
    InformationSlot,
    Operation,
    TargetLocality,
    TargetRole,
)


class RuleVariant(str, Enum):
    LOCAL_STATE = "local_state"
    PERSISTENT_MEMORY = "persistent_memory"
    LEGACY_EXECUTE = "legacy_execute"


class RegistryImplementationStatus(str, Enum):
    STUB = "stub"
    IMPLEMENTED = "implemented"


class RulePackAvailability(str, Enum):
    FOUND = "found"
    UNSUPPORTED = "unsupported"


class BasisReference(str, Enum):
    TERMS_PROMPT = "OFFICIAL-TERMS-PROMPT"
    TERMS_OBJECTS = "OFFICIAL-TERMS-OBJECTS"
    TERMS_RECORDS = "OFFICIAL-TERMS-RECORDS"
    TERMS_ACTIONS = "OFFICIAL-TERMS-AVAILABLE-ACTIONS"
    STEP2_ASSUMPTIONS = "REPORT-STEP2-ASSUMPTIONS"
    STEP5_CONTRACT = "DESIGN-STEP5-RULEPACK-CONTRACT"
    STEP7_CONTRACT = "DESIGN-STEP7-CONSTRAINT-CONTRACT"


class IdentityTypeConstraint(str, Enum):
    EXTERNAL_IDENTIFIER = "external_identifier"
    OBJECT_IDENTIFIER = "object_identifier"
    DOMAIN_IDENTIFIER = "domain_identifier"
    LOCAL_RESOURCE_IDENTIFIER = "local_resource_identifier"
    INTERACTION_PRINCIPAL = "interaction_principal"


class SameAsFocalPolicy(str, Enum):
    ALLOWED = "allowed"
    REQUIRED = "required"
    FORBIDDEN = "forbidden"
    NOT_APPLICABLE = "not_applicable"


class CompatibilityPredicate(str, Enum):
    FOCAL_RECIPIENT_COMPATIBLE = "focal_recipient_compatible"
    FOCAL_MERCHANT_COMPATIBLE = "focal_merchant_compatible"
    FOCAL_DEVICE_COMPATIBLE = "focal_device_compatible"
    FOCAL_CALENDAR_COMPATIBLE = "focal_calendar_compatible"
    LOCAL_RESOURCE_COMPATIBLE = "local_resource_compatible"
    INTERACTION_AUTHORITY_COMPATIBLE = "interaction_authority_compatible"


class ConditionalPredicateKind(str, Enum):
    CONSTRAINT_PRESENT = "constraint_present"
    DISCLOSURE_REQUESTED = "disclosure_requested"
    OPERATION_VARIANT_IS = "operation_variant_is"


class InformationConflictKind(str, Enum):
    MULTIPLE_DISTINCT_VALUES = "multiple_distinct_values"
    TARGET_VALUE_MISMATCH = "target_value_mismatch"
    STRUCTURAL_BINDING_CONFLICT = "structural_binding_conflict"


class DerivationSource(str, Enum):
    FOCAL_ATTRIBUTE = "focal_attribute"
    SELECTED_TARGET = "selected_target"
    OPERATION_ARGUMENT = "operation_argument"
    TYPED_RECORD = "typed_record"
    SESSION_REFERENCE = "session_reference"
    MEMORY_VALUE = "memory_value"


class SourceField(str, Enum):
    RECIPIENT = "recipient"
    MERCHANT = "merchant"
    AMOUNT = "amount"
    METHOD = "method"
    TARGET = "target"
    NAME = "name"
    TITLE = "title"
    ATTENDEE = "attendee"
    TIME = "time"
    DESIRED_STATE = "desired_state"
    OPERATION_REFERENCE = "operation_reference"
    LOCAL_RESOURCE = "local_resource"
    CONTENT_SCOPE = "content_scope"
    MEMORY_VALUE = "memory_value"
    DURATION = "duration"


@dataclass(frozen=True)
class RulePackKey:
    domain: Domain
    operation: Operation
    variant: RuleVariant | None = None

    def __post_init__(self) -> None:
        if self.domain == Domain.UNKNOWN or self.operation == Operation.UNRESOLVED:
            raise ValueError("unsupported semantics cannot form a RulePack key")


@dataclass(frozen=True)
class RequiredRoleSpec:
    spec_id: str
    allowed_roles: tuple[TargetRole, ...]
    minimum_cardinality: int
    maximum_cardinality: int
    identity_type_constraints: tuple[IdentityTypeConstraint, ...]
    locality_constraints: tuple[TargetLocality, ...]
    same_as_focal_policy: SameAsFocalPolicy
    compatibility_predicates: tuple[CompatibilityPredicate, ...]
    missing_role_disposition: CandidateState

    def __post_init__(self) -> None:
        if not self.spec_id or not self.allowed_roles:
            raise ValueError("RequiredRoleSpec requires ID and allowed roles")
        if self.minimum_cardinality < 0 or self.maximum_cardinality < 1:
            raise ValueError("invalid role cardinality")
        if self.minimum_cardinality > self.maximum_cardinality:
            raise ValueError("minimum role cardinality exceeds maximum")


@dataclass(frozen=True)
class ConditionalSlotSpec:
    slot: InformationSlot
    predicate_kind: ConditionalPredicateKind
    predicate_ref: str


@dataclass(frozen=True)
class InformationConflictRule:
    rule_id: str
    slot: InformationSlot
    kind: InformationConflictKind


@dataclass(frozen=True)
class TypedDerivationRule:
    rule_id: str
    slot: InformationSlot
    source: DerivationSource
    source_field: SourceField


@dataclass(frozen=True)
class InformationSpec:
    spec_id: str
    required_slots: tuple[InformationSlot, ...]
    conditional_slots: tuple[ConditionalSlotSpec, ...]
    optional_slots: tuple[InformationSlot, ...]
    conflict_rules: tuple[InformationConflictRule, ...]
    typed_derivation_rules: tuple[TypedDerivationRule, ...]
    missing_slot_disposition: CandidateState

    def __post_init__(self) -> None:
        required = set(self.required_slots)
        conditional = {item.slot for item in self.conditional_slots}
        optional = set(self.optional_slots)
        if required & conditional or required & optional or conditional & optional:
            raise ValueError("information slot classes must be disjoint")
        if len(required) != len(self.required_slots):
            raise ValueError("duplicate required information slot")
        if len(conditional) != len(self.conditional_slots):
            raise ValueError("duplicate conditional information slot")
        if len(optional) != len(self.optional_slots):
            raise ValueError("duplicate optional information slot")


@dataclass(frozen=True)
class BlueprintCatalogEntry:
    blueprint_id: str
    key: RulePackKey
    schema_version: str
    implementation_status: RegistryImplementationStatus
    activation_stage: int


@dataclass(frozen=True)
class ConstraintCatalogEntry:
    constraint_id: str
    applicable_domains: tuple[Domain, ...]
    applicable_operations: tuple[Operation, ...]
    schema_version: str
    implementation_status: RegistryImplementationStatus
    activation_stage: int


@dataclass(frozen=True)
class DomainOperationRulePack:
    rule_id: str
    key: RulePackKey
    required_role_spec_id: str
    information_spec_id: str
    base_blueprint_id: str
    pair_constraint_ids: tuple[str, ...]
    permitted_disclosure_modes: tuple[DisclosureMode, ...]
    contract_status: ContractStatus
    basis_refs: tuple[BasisReference, ...]
    assumption_refs: tuple[str, ...]
    version: str


@dataclass(frozen=True)
class RulePackResolution:
    key: RulePackKey
    availability: RulePackAvailability
    rulepack: DomainOperationRulePack | None
    candidate_state: CandidateState | None

    def __post_init__(self) -> None:
        if self.availability == RulePackAvailability.FOUND:
            if self.rulepack is None or self.candidate_state is not None:
                raise ValueError("found RulePack must defer candidate evaluation")
        elif (
            self.rulepack is not None
            or self.candidate_state != CandidateState.UNSUPPORTED_RULEPACK
        ):
            raise ValueError("unsupported lookup must preserve UNSUPPORTED_RULEPACK")


ROLE_SPECS = (
    RequiredRoleSpec(
        "ROLE-DISPATCH-DESTINATION",
        (TargetRole.DISPATCH_DESTINATION,),
        1,
        1,
        (IdentityTypeConstraint.EXTERNAL_IDENTIFIER,),
        (TargetLocality.EXTERNAL,),
        SameAsFocalPolicy.FORBIDDEN,
        (CompatibilityPredicate.FOCAL_RECIPIENT_COMPATIBLE,),
        CandidateState.NEEDS_INFORMATION,
    ),
    RequiredRoleSpec(
        "ROLE-LOCAL-RESOURCE",
        (TargetRole.LOCAL_RESOURCE,),
        1,
        1,
        (IdentityTypeConstraint.LOCAL_RESOURCE_IDENTIFIER,),
        (TargetLocality.LOCAL,),
        SameAsFocalPolicy.ALLOWED,
        (CompatibilityPredicate.LOCAL_RESOURCE_COMPATIBLE,),
        CandidateState.NEEDS_INFORMATION,
    ),
    RequiredRoleSpec(
        "ROLE-MEMORY-OWNER",
        (TargetRole.MEMORY_OWNER,),
        1,
        1,
        (IdentityTypeConstraint.LOCAL_RESOURCE_IDENTIFIER,),
        (TargetLocality.LOCAL,),
        SameAsFocalPolicy.NOT_APPLICABLE,
        (CompatibilityPredicate.LOCAL_RESOURCE_COMPATIBLE,),
        CandidateState.NEEDS_INFORMATION,
    ),
    RequiredRoleSpec(
        "ROLE-MERCHANT",
        (TargetRole.MERCHANT,),
        1,
        1,
        (IdentityTypeConstraint.DOMAIN_IDENTIFIER,),
        (TargetLocality.DOMAIN,),
        SameAsFocalPolicy.FORBIDDEN,
        (CompatibilityPredicate.FOCAL_MERCHANT_COMPATIBLE,),
        CandidateState.NEEDS_INFORMATION,
    ),
    RequiredRoleSpec(
        "ROLE-DEVICE",
        (TargetRole.DEVICE_TARGET,),
        1,
        1,
        (IdentityTypeConstraint.DOMAIN_IDENTIFIER,),
        (TargetLocality.DOMAIN,),
        SameAsFocalPolicy.ALLOWED,
        (CompatibilityPredicate.FOCAL_DEVICE_COMPATIBLE,),
        CandidateState.NEEDS_INFORMATION,
    ),
    RequiredRoleSpec(
        "ROLE-CALENDAR",
        (TargetRole.CALENDAR_TARGET,),
        1,
        1,
        (IdentityTypeConstraint.DOMAIN_IDENTIFIER,),
        (TargetLocality.DOMAIN,),
        SameAsFocalPolicy.ALLOWED,
        (CompatibilityPredicate.FOCAL_CALENDAR_COMPATIBLE,),
        CandidateState.NEEDS_INFORMATION,
    ),
    RequiredRoleSpec(
        "ROLE-CLARIFICATION-AUTHORITY",
        (TargetRole.CLARIFICATION_TARGET, TargetRole.CONFIRMATION_AUTHORITY),
        1,
        1,
        (IdentityTypeConstraint.INTERACTION_PRINCIPAL,),
        (TargetLocality.INTERACTION,),
        SameAsFocalPolicy.NOT_APPLICABLE,
        (CompatibilityPredicate.INTERACTION_AUTHORITY_COMPATIBLE,),
        CandidateState.NEEDS_INFORMATION,
    ),
)


def _conflict(
    spec: str,
    slot: InformationSlot,
) -> InformationConflictRule:
    return InformationConflictRule(
        f"CONFLICT-{spec}-{slot.value.upper()}",
        slot,
        InformationConflictKind.MULTIPLE_DISTINCT_VALUES,
    )


def _derive(
    spec: str,
    slot: InformationSlot,
    source: DerivationSource,
    field: SourceField,
) -> TypedDerivationRule:
    return TypedDerivationRule(
        f"DERIVE-{spec}-{slot.value.upper()}",
        slot,
        source,
        field,
    )


INFORMATION_SPECS = (
    InformationSpec(
        "INFO-DISPATCH",
        (InformationSlot.DESTINATION,),
        (),
        (InformationSlot.CONTENT_SCOPE,),
        (_conflict("DISPATCH", InformationSlot.DESTINATION),),
        (
            _derive(
                "DISPATCH",
                InformationSlot.DESTINATION,
                DerivationSource.SELECTED_TARGET,
                SourceField.RECIPIENT,
            ),
        ),
        CandidateState.NEEDS_INFORMATION,
    ),
    InformationSpec(
        "INFO-LOCAL",
        (InformationSlot.LOCAL_RESOURCE,),
        (),
        (),
        (),
        (
            _derive(
                "LOCAL",
                InformationSlot.LOCAL_RESOURCE,
                DerivationSource.SELECTED_TARGET,
                SourceField.LOCAL_RESOURCE,
            ),
        ),
        CandidateState.NEEDS_INFORMATION,
    ),
    InformationSpec(
        "INFO-MEMORY",
        (InformationSlot.LOCAL_RESOURCE, InformationSlot.MEMORY_VALUE),
        (),
        (),
        (_conflict("MEMORY", InformationSlot.MEMORY_VALUE),),
        (
            _derive(
                "MEMORY",
                InformationSlot.MEMORY_VALUE,
                DerivationSource.TYPED_RECORD,
                SourceField.MEMORY_VALUE,
            ),
        ),
        CandidateState.NEEDS_INFORMATION,
    ),
    InformationSpec(
        "INFO-PAY-EXECUTE",
        (InformationSlot.MERCHANT, InformationSlot.AMOUNT, InformationSlot.METHOD),
        (),
        (),
        (
            _conflict("PAY", InformationSlot.MERCHANT),
            _conflict("PAY", InformationSlot.AMOUNT),
        ),
        (
            _derive(
                "PAY",
                InformationSlot.MERCHANT,
                DerivationSource.FOCAL_ATTRIBUTE,
                SourceField.MERCHANT,
            ),
            _derive(
                "PAY",
                InformationSlot.AMOUNT,
                DerivationSource.FOCAL_ATTRIBUTE,
                SourceField.AMOUNT,
            ),
            _derive(
                "PAY",
                InformationSlot.METHOD,
                DerivationSource.FOCAL_ATTRIBUTE,
                SourceField.METHOD,
            ),
        ),
        CandidateState.NEEDS_INFORMATION,
    ),
    InformationSpec(
        "INFO-DEVICE-MODIFY",
        (InformationSlot.DEVICE_TARGET, InformationSlot.DESIRED_STATE),
        (
            ConditionalSlotSpec(
                InformationSlot.DURATION,
                ConditionalPredicateKind.CONSTRAINT_PRESENT,
                "CONSTRAINT-TEMPORARY-OVERRIDE",
            ),
        ),
        (),
        (_conflict("DEVICE", InformationSlot.DESIRED_STATE),),
        (
            _derive(
                "DEVICE",
                InformationSlot.DEVICE_TARGET,
                DerivationSource.FOCAL_ATTRIBUTE,
                SourceField.NAME,
            ),
            _derive(
                "DEVICE",
                InformationSlot.DESIRED_STATE,
                DerivationSource.OPERATION_ARGUMENT,
                SourceField.DESIRED_STATE,
            ),
        ),
        CandidateState.NEEDS_INFORMATION,
    ),
    InformationSpec(
        "INFO-CALENDAR-WRITE",
        (InformationSlot.EVENT, InformationSlot.TIME),
        (),
        (InformationSlot.RECIPIENT,),
        (_conflict("CALENDAR", InformationSlot.TIME),),
        (
            _derive(
                "CALENDAR",
                InformationSlot.EVENT,
                DerivationSource.FOCAL_ATTRIBUTE,
                SourceField.TITLE,
            ),
            _derive(
                "CALENDAR",
                InformationSlot.TIME,
                DerivationSource.FOCAL_ATTRIBUTE,
                SourceField.TIME,
            ),
        ),
        CandidateState.NEEDS_INFORMATION,
    ),
    InformationSpec(
        "INFO-DOMAIN-VERIFY",
        (InformationSlot.OPERATION_REFERENCE,),
        (),
        (),
        (_conflict("VERIFY", InformationSlot.OPERATION_REFERENCE),),
        (
            _derive(
                "VERIFY",
                InformationSlot.OPERATION_REFERENCE,
                DerivationSource.FOCAL_ATTRIBUTE,
                SourceField.OPERATION_REFERENCE,
            ),
        ),
        CandidateState.NEEDS_INFORMATION,
    ),
    InformationSpec(
        "INFO-CLARIFY",
        (InformationSlot.CLARIFICATION_TARGET,),
        (),
        (),
        (),
        (),
        CandidateState.NEEDS_INFORMATION,
    ),
)


def _key(
    domain: Domain,
    operation: Operation,
    variant: RuleVariant | None = None,
) -> RulePackKey:
    return RulePackKey(domain, operation, variant)


RULEPACK_KEYS = (
    _key(Domain.CONTENT, Operation.SHARE),
    _key(Domain.MEMORY, Operation.LOCAL_UPDATE, RuleVariant.LOCAL_STATE),
    _key(Domain.MEMORY, Operation.LOCAL_UPDATE, RuleVariant.PERSISTENT_MEMORY),
    _key(Domain.MEMORY, Operation.STORE, RuleVariant.PERSISTENT_MEMORY),
    _key(Domain.PAYMENT, Operation.EXECUTE),
    _key(Domain.PAYMENT, Operation.VERIFY),
    _key(Domain.DEVICE, Operation.MODIFY),
    _key(Domain.DEVICE, Operation.EXECUTE, RuleVariant.LEGACY_EXECUTE),
    _key(Domain.DEVICE, Operation.VERIFY),
    _key(Domain.CALENDAR, Operation.CREATE),
    _key(Domain.CALENDAR, Operation.MODIFY),
    _key(Domain.CALENDAR, Operation.EXECUTE, RuleVariant.LEGACY_EXECUTE),
    _key(Domain.CALENDAR, Operation.VERIFY),
    _key(Domain.GENERAL, Operation.CLARIFY),
)


BLUEPRINT_CATALOG = tuple(
    BlueprintCatalogEntry(
        blueprint_id=f"BLUEPRINT-{index:03d}",
        key=key,
        schema_version="1.0.0",
        implementation_status=RegistryImplementationStatus.IMPLEMENTED,
        activation_stage=6,
    )
    for index, key in enumerate(RULEPACK_KEYS, start=1)
)


CONSTRAINT_CATALOG = (
    ConstraintCatalogEntry(
        "CONSTRAINT-DISPATCH-CONSENT",
        (Domain.CONTENT,),
        (Operation.SHARE,),
        "1.0.0",
        RegistryImplementationStatus.IMPLEMENTED,
        7,
    ),
    ConstraintCatalogEntry(
        "CONSTRAINT-DISPATCH-SECURITY",
        (Domain.CONTENT, Domain.PAYMENT),
        (Operation.SHARE, Operation.EXECUTE),
        "1.0.0",
        RegistryImplementationStatus.IMPLEMENTED,
        7,
    ),
    ConstraintCatalogEntry(
        "CONSTRAINT-EXTERNAL-SHARE-POLICY",
        (Domain.CONTENT,),
        (Operation.SHARE,),
        "1.0.0",
        RegistryImplementationStatus.IMPLEMENTED,
        7,
    ),
    ConstraintCatalogEntry(
        "CONSTRAINT-PAYMENT-POLICY",
        (Domain.PAYMENT,),
        (Operation.EXECUTE, Operation.VERIFY),
        "1.0.0",
        RegistryImplementationStatus.IMPLEMENTED,
        7,
    ),
    ConstraintCatalogEntry(
        "CONSTRAINT-DEVICE-SAFETY",
        (Domain.DEVICE,),
        (Operation.EXECUTE, Operation.MODIFY),
        "1.0.0",
        RegistryImplementationStatus.IMPLEMENTED,
        7,
    ),
    ConstraintCatalogEntry(
        "CONSTRAINT-TEMPORARY-OVERRIDE",
        (Domain.DEVICE,),
        (Operation.EXECUTE, Operation.MODIFY),
        "1.0.0",
        RegistryImplementationStatus.IMPLEMENTED,
        7,
    ),
    ConstraintCatalogEntry(
        "CONSTRAINT-CALENDAR-CONFLICT",
        (Domain.CALENDAR,),
        (Operation.CREATE, Operation.MODIFY, Operation.EXECUTE),
        "1.0.0",
        RegistryImplementationStatus.IMPLEMENTED,
        7,
    ),
)


def _constraint_ids_for(key: RulePackKey) -> tuple[str, ...]:
    if key == _key(Domain.CONTENT, Operation.SHARE):
        return (
            "CONSTRAINT-DISPATCH-CONSENT",
            "CONSTRAINT-DISPATCH-SECURITY",
            "CONSTRAINT-EXTERNAL-SHARE-POLICY",
        )
    if key.domain == Domain.PAYMENT:
        return (
            ("CONSTRAINT-PAYMENT-POLICY",)
            if key.operation == Operation.VERIFY
            else (
                "CONSTRAINT-DISPATCH-SECURITY",
                "CONSTRAINT-PAYMENT-POLICY",
            )
        )
    if key.domain == Domain.DEVICE and key.operation != Operation.VERIFY:
        return ("CONSTRAINT-DEVICE-SAFETY", "CONSTRAINT-TEMPORARY-OVERRIDE")
    if key.domain == Domain.CALENDAR and key.operation != Operation.VERIFY:
        return ("CONSTRAINT-CALENDAR-CONFLICT",)
    return ()


def _role_for(key: RulePackKey) -> str:
    if key.domain == Domain.MEMORY:
        return (
            "ROLE-MEMORY-OWNER"
            if key.variant == RuleVariant.PERSISTENT_MEMORY
            else "ROLE-LOCAL-RESOURCE"
        )
    return {
        Domain.CONTENT: "ROLE-DISPATCH-DESTINATION",
        Domain.PAYMENT: "ROLE-MERCHANT",
        Domain.DEVICE: "ROLE-DEVICE",
        Domain.CALENDAR: "ROLE-CALENDAR",
        Domain.GENERAL: "ROLE-CLARIFICATION-AUTHORITY",
    }[key.domain]


def _information_for(key: RulePackKey) -> str:
    if key.domain == Domain.CONTENT:
        return "INFO-DISPATCH"
    if key.domain == Domain.MEMORY:
        return (
            "INFO-MEMORY"
            if key.variant == RuleVariant.PERSISTENT_MEMORY
            else "INFO-LOCAL"
        )
    if key.domain == Domain.PAYMENT:
        return (
            "INFO-DOMAIN-VERIFY"
            if key.operation == Operation.VERIFY
            else "INFO-PAY-EXECUTE"
        )
    if key.domain == Domain.DEVICE:
        return (
            "INFO-DOMAIN-VERIFY"
            if key.operation == Operation.VERIFY
            else "INFO-DEVICE-MODIFY"
        )
    if key.domain == Domain.CALENDAR:
        return (
            "INFO-DOMAIN-VERIFY"
            if key.operation == Operation.VERIFY
            else "INFO-CALENDAR-WRITE"
        )
    return "INFO-CLARIFY"


def _disclosure_for(key: RulePackKey) -> tuple[DisclosureMode, ...]:
    if key.domain == Domain.CONTENT:
        return (
            DisclosureMode.RAW,
            DisclosureMode.SUMMARY,
            DisclosureMode.REDACTED,
        )
    if key.operation == Operation.VERIFY or key.domain == Domain.GENERAL:
        return (DisclosureMode.NONE,)
    return (DisclosureMode.STATUS_ONLY,)


RULE_PACKS = tuple(
    DomainOperationRulePack(
        rule_id=f"RULEPACK-{index:03d}",
        key=key,
        required_role_spec_id=_role_for(key),
        information_spec_id=_information_for(key),
        base_blueprint_id=f"BLUEPRINT-{index:03d}",
        pair_constraint_ids=_constraint_ids_for(key),
        permitted_disclosure_modes=_disclosure_for(key),
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=(
            BasisReference.TERMS_OBJECTS,
            BasisReference.TERMS_RECORDS,
            BasisReference.STEP5_CONTRACT,
        ),
        assumption_refs=(ACTIONS_ASSUMPTION_ID,)
        + (
            (TARGET_ASSUMPTION_ID,)
            if key.domain in {Domain.GENERAL, Domain.MEMORY}
            else ()
        ),
        version="1.0.0",
    )
    for index, key in enumerate(RULEPACK_KEYS, start=1)
)


class RulePackRegistry:
    production_active = False

    def __init__(
        self,
        rulepacks: Iterable[DomainOperationRulePack] = RULE_PACKS,
        role_specs: Iterable[RequiredRoleSpec] = ROLE_SPECS,
        information_specs: Iterable[InformationSpec] = INFORMATION_SPECS,
        blueprint_catalog: Iterable[BlueprintCatalogEntry] = BLUEPRINT_CATALOG,
        constraint_catalog: Iterable[ConstraintCatalogEntry] = CONSTRAINT_CATALOG,
    ) -> None:
        self.rulepacks = tuple(rulepacks)
        self.role_specs = tuple(role_specs)
        self.information_specs = tuple(information_specs)
        self.blueprint_catalog = tuple(blueprint_catalog)
        self.constraint_catalog = tuple(constraint_catalog)
        self._by_key = {item.key: item for item in self.rulepacks}
        self._roles = {item.spec_id: item for item in self.role_specs}
        self._information = {item.spec_id: item for item in self.information_specs}
        self._blueprints = {item.blueprint_id: item for item in self.blueprint_catalog}
        self._constraints = {
            item.constraint_id: item for item in self.constraint_catalog
        }
        self.validate()

    def lookup(self, key: RulePackKey) -> DomainOperationRulePack | None:
        return self._by_key.get(key)

    def resolve_exact(self, key: RulePackKey) -> RulePackResolution:
        rulepack = self.lookup(key)
        if rulepack is None:
            return RulePackResolution(
                key,
                RulePackAvailability.UNSUPPORTED,
                None,
                CandidateState.UNSUPPORTED_RULEPACK,
            )
        return RulePackResolution(
            key,
            RulePackAvailability.FOUND,
            rulepack,
            None,
        )

    def role_spec(self, spec_id: str) -> RequiredRoleSpec:
        return self._roles[spec_id]

    def information_spec(self, spec_id: str) -> InformationSpec:
        return self._information[spec_id]

    def validate(self) -> None:
        self._validate_unique(self.rulepacks, lambda item: item.rule_id, "rule ID")
        self._validate_unique(self.rulepacks, lambda item: item.key, "RulePack key")
        self._validate_unique(
            self.role_specs, lambda item: item.spec_id, "role spec ID"
        )
        self._validate_unique(
            self.information_specs,
            lambda item: item.spec_id,
            "information spec ID",
        )
        self._validate_unique(
            self.blueprint_catalog,
            lambda item: item.blueprint_id,
            "blueprint ID",
        )
        self._validate_unique(
            self.constraint_catalog,
            lambda item: item.constraint_id,
            "constraint ID",
        )
        registered_assumptions = assumption_ids()
        for pack in self.rulepacks:
            if pack.required_role_spec_id not in self._roles:
                raise ValueError(f"unknown role spec: {pack.required_role_spec_id}")
            if pack.information_spec_id not in self._information:
                raise ValueError(
                    f"unknown information spec: {pack.information_spec_id}"
                )
            information_spec = self._information[pack.information_spec_id]
            conditional_constraint_refs = {
                item.predicate_ref
                for item in information_spec.conditional_slots
                if item.predicate_kind
                == ConditionalPredicateKind.CONSTRAINT_PRESENT
            }
            if not conditional_constraint_refs <= set(pack.pair_constraint_ids):
                raise ValueError(
                    "conditional information constraint is not evaluated by "
                    f"RulePack: {pack.rule_id}"
                )
            blueprint = self._blueprints.get(pack.base_blueprint_id)
            if blueprint is None or blueprint.key != pack.key:
                raise ValueError(
                    f"invalid blueprint reference: {pack.base_blueprint_id}"
                )
            for constraint_id in pack.pair_constraint_ids:
                constraint = self._constraints.get(constraint_id)
                if constraint is None:
                    raise ValueError(f"unknown constraint reference: {constraint_id}")
                if pack.key.domain not in constraint.applicable_domains:
                    raise ValueError(
                        f"constraint domain mismatch: {pack.rule_id}:{constraint_id}"
                    )
                if pack.key.operation not in constraint.applicable_operations:
                    raise ValueError(
                        f"constraint operation mismatch: {pack.rule_id}:{constraint_id}"
                    )
            unknown_assumptions = set(pack.assumption_refs) - registered_assumptions
            if unknown_assumptions:
                raise ValueError(
                    f"unknown RulePack assumptions: {sorted(unknown_assumptions)}"
                )
            if not pack.basis_refs or not re.fullmatch(r"\d+\.\d+\.\d+", pack.version):
                raise ValueError(f"invalid RulePack metadata: {pack.rule_id}")
            if not pack.permitted_disclosure_modes:
                raise ValueError(f"RulePack has no disclosure mode: {pack.rule_id}")
            if not isinstance(pack.contract_status, ContractStatus):
                raise ValueError(f"invalid RulePack contract status: {pack.rule_id}")
        self._validate_role_boundaries()
        self._validate_information_specs()
        self._validate_activation_boundaries()

    def _validate_role_boundaries(self) -> None:
        interaction_roles = {
            TargetRole.CLARIFICATION_TARGET,
            TargetRole.CONFIRMATION_AUTHORITY,
            TargetRole.MEMORY_OWNER,
        }
        for spec in self.role_specs:
            roles = set(spec.allowed_roles)
            if roles & interaction_roles and roles - interaction_roles:
                raise ValueError(
                    f"interaction and execution roles mixed: {spec.spec_id}"
                )
            if roles - interaction_roles and (
                IdentityTypeConstraint.INTERACTION_PRINCIPAL
                in spec.identity_type_constraints
            ):
                raise ValueError(
                    f"execution role accepts interaction principal: {spec.spec_id}"
                )

    def _validate_information_specs(self) -> None:
        for spec in self.information_specs:
            declared = (
                set(spec.required_slots)
                | {item.slot for item in spec.conditional_slots}
                | set(spec.optional_slots)
            )
            if any(item.slot not in declared for item in spec.conflict_rules):
                raise ValueError(
                    f"conflict rule references undeclared slot: {spec.spec_id}"
                )
            if any(item.slot not in declared for item in spec.typed_derivation_rules):
                raise ValueError(
                    f"derivation rule references undeclared slot: {spec.spec_id}"
                )
            for conditional in spec.conditional_slots:
                if (
                    conditional.predicate_kind
                    == ConditionalPredicateKind.CONSTRAINT_PRESENT
                    and conditional.predicate_ref not in self._constraints
                ):
                    raise ValueError(
                        f"conditional slot has unknown constraint: {spec.spec_id}"
                    )
            self._validate_unique(
                spec.conflict_rules,
                lambda item: item.rule_id,
                f"conflict rule ID in {spec.spec_id}",
            )
            self._validate_unique(
                spec.typed_derivation_rules,
                lambda item: item.rule_id,
                f"derivation rule ID in {spec.spec_id}",
            )

    def _validate_activation_boundaries(self) -> None:
        if self.production_active:
            raise ValueError("Step 5 RulePack registry must remain shadow-only")
        if any(
            item.implementation_status != RegistryImplementationStatus.IMPLEMENTED
            or item.activation_stage != 6
            or not re.fullmatch(r"\d+\.\d+\.\d+", item.schema_version)
            for item in self.blueprint_catalog
        ):
            raise ValueError("blueprint catalog must contain Step 6 implementations")
        if any(
            item.implementation_status != RegistryImplementationStatus.IMPLEMENTED
            or item.activation_stage != 7
            or not re.fullmatch(r"\d+\.\d+\.\d+", item.schema_version)
            for item in self.constraint_catalog
        ):
            raise ValueError("constraint catalog must contain Step 7 implementations")

    @staticmethod
    def _validate_unique(
        values: Iterable[object],
        key: Callable[[Any], Hashable],
        label: str,
    ) -> None:
        rows = list(values)
        keys = [key(item) for item in rows]
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate {label}")


RULEPACK_REGISTRY = RulePackRegistry()


def validate_rulepack_registry() -> None:
    RULEPACK_REGISTRY.validate()
