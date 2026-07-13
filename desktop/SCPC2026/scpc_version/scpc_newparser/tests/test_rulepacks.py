from __future__ import annotations

from dataclasses import replace
import inspect
from pathlib import Path

import pytest

from core.contracts import assumption_ids
from core.ontology import (
    CandidateState,
    Domain,
    InformationSlot,
    Operation,
    TargetRole,
)
from core.rulepacks import (
    BLUEPRINT_CATALOG,
    CONSTRAINT_CATALOG,
    INFORMATION_SPECS,
    ROLE_SPECS,
    RULEPACK_REGISTRY,
    RULE_PACKS,
    ConditionalPredicateKind,
    DomainOperationRulePack,
    IdentityTypeConstraint,
    RegistryImplementationStatus,
    RulePackAvailability,
    RulePackKey,
    RulePackRegistry,
    RuleVariant,
    validate_rulepack_registry,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_rulepack_lookup_is_exact_and_never_falls_back() -> None:
    supported_key = RulePackKey(Domain.PAYMENT, Operation.EXECUTE)
    supported = RULEPACK_REGISTRY.resolve_exact(supported_key)
    assert supported.availability == RulePackAvailability.FOUND
    assert supported.rulepack is not None
    assert supported.rulepack.key == supported_key
    assert supported.candidate_state is None

    unsupported = RULEPACK_REGISTRY.resolve_exact(
        RulePackKey(Domain.PAYMENT, Operation.CANCEL)
    )
    assert unsupported.availability == RulePackAvailability.UNSUPPORTED
    assert unsupported.rulepack is None
    assert unsupported.candidate_state == CandidateState.UNSUPPORTED_RULEPACK

    wrong_variant = RULEPACK_REGISTRY.resolve_exact(
        RulePackKey(Domain.MEMORY, Operation.LOCAL_UPDATE)
    )
    assert wrong_variant.availability == RulePackAvailability.UNSUPPORTED
    assert RULEPACK_REGISTRY.lookup(supported_key) is supported.rulepack


def test_invalid_candidate_lookup_does_not_remove_other_rulepacks() -> None:
    unsupported = RULEPACK_REGISTRY.resolve_exact(
        RulePackKey(Domain.CALENDAR, Operation.CANCEL)
    )
    payment = RULEPACK_REGISTRY.resolve_exact(
        RulePackKey(Domain.PAYMENT, Operation.EXECUTE)
    )
    device = RULEPACK_REGISTRY.resolve_exact(
        RulePackKey(Domain.DEVICE, Operation.MODIFY)
    )
    assert unsupported.candidate_state == CandidateState.UNSUPPORTED_RULEPACK
    assert payment.availability == RulePackAvailability.FOUND
    assert device.availability == RulePackAvailability.FOUND


def test_rulepack_references_are_typed_and_registered() -> None:
    validate_rulepack_registry()
    role_ids = {item.spec_id for item in ROLE_SPECS}
    information_ids = {item.spec_id for item in INFORMATION_SPECS}
    blueprint_ids = {item.blueprint_id for item in BLUEPRINT_CATALOG}
    constraint_ids = {item.constraint_id for item in CONSTRAINT_CATALOG}
    known_assumptions = assumption_ids()

    for pack in RULE_PACKS:
        assert pack.required_role_spec_id in role_ids
        assert pack.information_spec_id in information_ids
        assert pack.base_blueprint_id in blueprint_ids
        assert set(pack.pair_constraint_ids) <= constraint_ids
        assert set(pack.assumption_refs) <= known_assumptions
        assert pack.basis_refs


def test_unregistered_reference_and_duplicate_key_are_rejected() -> None:
    broken_reference = replace(
        RULE_PACKS[0],
        rule_id="RULEPACK-BROKEN-REFERENCE",
        base_blueprint_id="BLUEPRINT-NOT-REGISTERED",
    )
    with pytest.raises(ValueError, match="invalid blueprint reference"):
        RulePackRegistry(rulepacks=(broken_reference,))

    duplicate_key = replace(RULE_PACKS[0], rule_id="RULEPACK-DUPLICATE")
    with pytest.raises(ValueError, match="duplicate RulePack key"):
        RulePackRegistry(rulepacks=(RULE_PACKS[0], duplicate_key))


def test_blueprints_and_constraints_are_implemented_but_new_path_is_inactive() -> None:
    from core.constraints import PAIR_CONSTRAINT_REGISTRY
    from core.plan_requirements import PLAN_BLUEPRINT_REGISTRY

    assert RULEPACK_REGISTRY.production_active is False
    assert PLAN_BLUEPRINT_REGISTRY.production_active is False
    assert PAIR_CONSTRAINT_REGISTRY.production_active is False
    assert all(
        item.implementation_status == RegistryImplementationStatus.IMPLEMENTED
        and item.activation_stage == 6
        for item in BLUEPRINT_CATALOG
    )
    assert all(
        item.implementation_status == RegistryImplementationStatus.IMPLEMENTED
        and item.activation_stage == 7
        for item in CONSTRAINT_CATALOG
    )
    decision_source = (PROJECT_ROOT / "core" / "decision.py").read_text(
        encoding="utf-8"
    )
    assert "core.rulepacks" not in decision_source
    assert "from .rulepacks" not in decision_source


def test_execution_roles_cannot_accept_interaction_principals() -> None:
    interaction_roles = {
        TargetRole.CLARIFICATION_TARGET,
        TargetRole.CONFIRMATION_AUTHORITY,
        TargetRole.MEMORY_OWNER,
    }
    for spec in ROLE_SPECS:
        roles = set(spec.allowed_roles)
        if roles - interaction_roles:
            assert not (roles & interaction_roles)
            assert (
                IdentityTypeConstraint.INTERACTION_PRINCIPAL
                not in spec.identity_type_constraints
            )

    source = (PROJECT_ROOT / "core" / "rulepacks.py").read_text(encoding="utf-8")
    assert '"user"' not in source
    assert "'user'" not in source


def test_information_slot_classes_are_disjoint_and_capability_free() -> None:
    saw_required = saw_conditional = saw_optional = False
    for spec in INFORMATION_SPECS:
        required = set(spec.required_slots)
        conditional = {item.slot for item in spec.conditional_slots}
        optional = set(spec.optional_slots)
        assert not (required & conditional)
        assert not (required & optional)
        assert not (conditional & optional)
        saw_required |= bool(required)
        saw_conditional |= bool(conditional)
        saw_optional |= bool(optional)
    assert saw_required and saw_conditional and saw_optional

    device = next(
        item for item in INFORMATION_SPECS if item.spec_id == "INFO-DEVICE-MODIFY"
    )
    assert device.conditional_slots[0].slot == InformationSlot.DURATION
    assert (
        device.conditional_slots[0].predicate_kind
        == ConditionalPredicateKind.CONSTRAINT_PRESENT
    )

    source = inspect.getsource(type(INFORMATION_SPECS[0]))
    assert "Capability" not in source


def test_rulepack_registry_has_no_fuzzy_or_task_specific_lookup() -> None:
    source = (PROJECT_ROOT / "core" / "rulepacks.py").read_text(encoding="utf-8")
    for prohibited in (
        "final_dev_",
        "final_screening_",
        "difflib",
        "SequenceMatcher",
        "closest",
        "default_dispatch",
    ):
        assert prohibited not in source
    lookup_source = inspect.getsource(RulePackRegistry.lookup)
    assert "self._by_key.get(key)" in lookup_source
    assert "for " not in lookup_source


def test_rulepack_key_rejects_unknown_semantics() -> None:
    with pytest.raises(ValueError, match="unsupported semantics"):
        RulePackKey(Domain.UNKNOWN, Operation.EXECUTE)
    with pytest.raises(ValueError, match="unsupported semantics"):
        RulePackKey(Domain.GENERAL, Operation.UNRESOLVED)


def test_memory_variants_are_explicit_keys() -> None:
    local = RULEPACK_REGISTRY.lookup(
        RulePackKey(
            Domain.MEMORY,
            Operation.LOCAL_UPDATE,
            RuleVariant.LOCAL_STATE,
        )
    )
    persistent = RULEPACK_REGISTRY.lookup(
        RulePackKey(
            Domain.MEMORY,
            Operation.LOCAL_UPDATE,
            RuleVariant.PERSISTENT_MEMORY,
        )
    )
    assert isinstance(local, DomainOperationRulePack)
    assert isinstance(persistent, DomainOperationRulePack)
    assert local.rule_id != persistent.rule_id
    assert local.information_spec_id != persistent.information_spec_id
