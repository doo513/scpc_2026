from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from core.candidate_evaluation import (
    CandidateEvaluationContext,
    CandidateIdentity,
    CandidateOrigin,
    CandidateSemanticKey,
    CandidateSetBuilder,
    EvaluationCandidate,
)
from core.constraints import GLOBAL_CONSTRAINT_REGISTRY
from core.contracts import ContractStatus
from core.facts import CapabilitySnapshot
from core.fallbacks import (
    FALLBACK_EDGE_REGISTRY,
    AuthorizedFallbackSolver,
    CandidatePattern,
    FallbackActivationCondition,
    FallbackAuthorization,
    FallbackAuthorizationSource,
    FallbackEdge,
    FallbackEdgeRegistry,
    FallbackResolutionStatus,
    SemanticPreservation,
    validate_fallback_registry,
)
from core.ontology import (
    CapabilityType,
    Domain,
    FactStatus,
    Operation,
    ReasonCode,
    TargetLocality,
    TargetRole,
)
from core.plan_requirements import InternalTransformType
from core.rulepacks import (
    RULEPACK_REGISTRY,
    IdentityTypeConstraint,
    RulePackKey,
    SourceField,
)
from core.task_view import TaskView
from core.slm_contract import EvidenceAuthorityClass


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _candidate(
    key: RulePackKey,
    *,
    clause: str,
    rank: int = 50,
) -> EvaluationCandidate:
    pack = RULEPACK_REGISTRY.lookup(key)
    assert pack is not None
    role = RULEPACK_REGISTRY.role_spec(pack.required_role_spec_id)
    focal_fields: tuple[tuple[SourceField, str], ...] = ()
    arguments: tuple[tuple[SourceField, str], ...] = ()
    if key.domain == Domain.PAYMENT:
        focal_fields = (
            (SourceField.MERCHANT, "merchant:one"),
            (SourceField.AMOUNT, "1000"),
            (SourceField.METHOD, "method:token"),
        )
    target_id = (
        "merchant:one"
        if key.domain == Domain.PAYMENT
        else "target:content"
    )
    return EvaluationCandidate(
        identity=CandidateIdentity(
            "operation:one",
            clause,
            f"evidence:{clause}",
            CandidateSemanticKey(key, "object:focal", target_id),
        ),
        target_role=role.allowed_roles[0],
        target_locality=role.locality_constraints[0],
        target_identity_type=role.identity_type_constraints[0],
        satisfied_role_predicates=role.compatibility_predicates,
        failed_role_predicates=(),
        focal_fields=focal_fields,
        operation_arguments=arguments,
        information_bindings=(),
        requested_disclosure=None,
        intent_rank=rank,
        origin=CandidateOrigin.PARSER,
        provenance_ids=(f"evidence:{clause}",),
    )


def _context(
    *,
    capabilities: frozenset[CapabilityType],
    records: list[dict[str, object]] | None = None,
) -> CandidateEvaluationContext:
    view = TaskView(
        {
            "id": "fallback",
            "device_state": {"objects": [], "records": records or []},
            "available_actions": [item.value for item in capabilities],
        }
    )
    return CandidateEvaluationContext(
        GLOBAL_CONSTRAINT_REGISTRY.collect(view.typed_records),
        CapabilitySnapshot(FactStatus.PRESENT, capabilities),
        frozenset(InternalTransformType),
    )


def _pattern(pattern_id: str, key: RulePackKey) -> CandidatePattern:
    return CandidatePattern(pattern_id, (key,))


def _authorization(valid: bool = True) -> FallbackAuthorization:
    return FallbackAuthorization(
        FallbackAuthorizationSource.CURRENT_USER_EXPLICIT,
        ("evidence:fallback",),
        valid,
        EvidenceAuthorityClass.CURRENT_DIRECT,
    )


def _edge(
    source: CandidatePattern,
    destination: CandidatePattern,
    *,
    edge_id: str = "fallback:one",
    authorization: FallbackAuthorization | None = None,
    maximum_hops: int = 1,
) -> FallbackEdge:
    return FallbackEdge(
        edge_id=edge_id,
        source_candidate_pattern=source,
        destination_candidate_pattern=destination,
        authorization=authorization or _authorization(),
        activation_condition=(
            FallbackActivationCondition.SOURCE_CAPABILITY_UNAVAILABLE
        ),
        semantic_preservation=SemanticPreservation.USER_SPECIFIED_ALTERNATIVE,
        maximum_hops=maximum_hops,
        reason_code=ReasonCode.AVOIDED_BY_AUTHORIZED_FALLBACK,
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
    )


def test_default_fallback_registry_is_empty_and_shadow_only() -> None:
    validate_fallback_registry()
    assert FALLBACK_EDGE_REGISTRY.edges == ()
    assert FALLBACK_EDGE_REGISTRY.production_active is False


def test_unauthorized_fallback_edge_is_rejected() -> None:
    source = _pattern("source", RulePackKey(Domain.PAYMENT, Operation.EXECUTE))
    destination = _pattern(
        "destination",
        RulePackKey(Domain.CONTENT, Operation.SHARE),
    )
    with pytest.raises(ValueError, match="unauthorized fallback"):
        FallbackEdgeRegistry(
            (_edge(source, destination, authorization=_authorization(False)),)
        )


def test_slm_proposal_cannot_authorize_a_current_user_fallback() -> None:
    source = _pattern("source", RulePackKey(Domain.PAYMENT, Operation.EXECUTE))
    destination = _pattern(
        "destination",
        RulePackKey(Domain.CONTENT, Operation.SHARE),
    )
    slm_authorization = FallbackAuthorization(
        FallbackAuthorizationSource.CURRENT_USER_EXPLICIT,
        ("slm:proposal",),
        True,
        EvidenceAuthorityClass.SLM_PROPOSAL,
    )
    with pytest.raises(ValueError, match="unauthorized fallback"):
        FallbackEdgeRegistry(
            (_edge(source, destination, authorization=slm_authorization),)
        )


def test_fallback_self_loop_and_cycle_are_rejected_statically() -> None:
    payment = _pattern("payment", RulePackKey(Domain.PAYMENT, Operation.EXECUTE))
    content = _pattern("content", RulePackKey(Domain.CONTENT, Operation.SHARE))
    with pytest.raises(ValueError, match="self-loop"):
        FallbackEdgeRegistry((_edge(payment, payment),))
    with pytest.raises(ValueError, match="cycle"):
        FallbackEdgeRegistry(
            (
                _edge(payment, content, edge_id="edge:a"),
                _edge(content, payment, edge_id="edge:b"),
            )
        )


def test_overlapping_fallback_patterns_cannot_hide_a_self_loop() -> None:
    payment_key = RulePackKey(Domain.PAYMENT, Operation.EXECUTE)
    content_key = RulePackKey(Domain.CONTENT, Operation.SHARE)
    broad = CandidatePattern("broad", (payment_key, content_key))
    content = CandidatePattern("content", (content_key,))
    with pytest.raises(ValueError, match="self-loop"):
        FallbackEdgeRegistry((_edge(broad, content),))


def test_multiple_edges_to_one_destination_preserve_all_edge_lineage() -> None:
    payment_key = RulePackKey(Domain.PAYMENT, Operation.EXECUTE)
    content_key = RulePackKey(Domain.CONTENT, Operation.SHARE)
    source = _candidate(payment_key, clause="payment")
    destination = _candidate(content_key, clause="content")
    source_pattern = _pattern("source", payment_key)
    destination_pattern = _pattern("destination", content_key)
    registry = FallbackEdgeRegistry(
        (
            _edge(source_pattern, destination_pattern, edge_id="edge:b"),
            _edge(source_pattern, destination_pattern, edge_id="edge:a"),
        )
    )
    result = AuthorizedFallbackSolver.solve(
        source_candidate_id=source.candidate_id,
        candidate_set=CandidateSetBuilder.build((source, destination)),
        evaluation_context=_context(
            capabilities=frozenset(
                item for item in CapabilityType if item != CapabilityType.PAY
            )
        ),
        registry=registry,
    )
    assert result.resolution.status == FallbackResolutionStatus.APPLIED
    assert tuple(item.edge_id for item in result.resolution.traces) == (
        "edge:a",
        "edge:b",
    )


def test_unconfirmed_multi_hop_fallback_is_rejected() -> None:
    payment = _pattern("payment", RulePackKey(Domain.PAYMENT, Operation.EXECUTE))
    content = _pattern("content", RulePackKey(Domain.CONTENT, Operation.SHARE))
    with pytest.raises(ValueError, match="multi-hop fallback"):
        FallbackEdgeRegistry(
            (_edge(payment, content, maximum_hops=2),)
        )


def test_authorized_destination_is_re_evaluated_with_its_own_rulepack() -> None:
    payment_key = RulePackKey(Domain.PAYMENT, Operation.EXECUTE)
    content_key = RulePackKey(Domain.CONTENT, Operation.SHARE)
    source = _candidate(payment_key, clause="payment")
    destination = _candidate(content_key, clause="content")
    registry = FallbackEdgeRegistry(
        (_edge(_pattern("source", payment_key), _pattern("dest", content_key)),)
    )
    capabilities = frozenset(
        item for item in CapabilityType if item != CapabilityType.PAY
    )
    result = AuthorizedFallbackSolver.solve(
        source_candidate_id=source.candidate_id,
        candidate_set=CandidateSetBuilder.build((source, destination)),
        evaluation_context=_context(capabilities=capabilities),
        registry=registry,
    )
    assert result.resolution.status == FallbackResolutionStatus.APPLIED
    assert result.resolution.selected_destination_candidate_id == (
        destination.candidate_id
    )
    by_id = {item.candidate.candidate_id: item for item in result.evaluations}
    source_plan = by_id[source.candidate_id].assessment.final_plan_requirements
    destination_plan = by_id[
        destination.candidate_id
    ].assessment.final_plan_requirements
    assert source_plan is not None and destination_plan is not None
    assert source_plan.rulepack_id != destination_plan.rulepack_id
    assert source_plan.blueprint_id != destination_plan.blueprint_id
    assert destination_plan.semantic_terminal.value == "dispatch"
    assert result.resolution.traces[0].destination_candidate_id == (
        destination.candidate_id
    )


def test_lower_rank_candidate_is_not_automatic_without_authorized_edge() -> None:
    payment_key = RulePackKey(Domain.PAYMENT, Operation.EXECUTE)
    content_key = RulePackKey(Domain.CONTENT, Operation.SHARE)
    source = _candidate(payment_key, clause="payment", rank=100)
    destination = _candidate(content_key, clause="content", rank=1)
    capabilities = frozenset(
        item for item in CapabilityType if item != CapabilityType.PAY
    )
    result = AuthorizedFallbackSolver.solve(
        source_candidate_id=source.candidate_id,
        candidate_set=CandidateSetBuilder.build((source, destination)),
        evaluation_context=_context(capabilities=capabilities),
        registry=FallbackEdgeRegistry(),
    )
    assert result.resolution.status == FallbackResolutionStatus.NOT_APPLIED
    assert result.resolution.selected_destination_candidate_id == ""
    assert result.resolution.traces == ()


def test_multiple_authorized_destinations_require_user_choice() -> None:
    payment_key = RulePackKey(Domain.PAYMENT, Operation.EXECUTE)
    content_key = RulePackKey(Domain.CONTENT, Operation.SHARE)
    source = _candidate(payment_key, clause="payment")
    first = _candidate(content_key, clause="content:a")
    second = _candidate(content_key, clause="content:b")
    registry = FallbackEdgeRegistry(
        (_edge(_pattern("source", payment_key), _pattern("dest", content_key)),)
    )
    capabilities = frozenset(
        item for item in CapabilityType if item != CapabilityType.PAY
    )
    result = AuthorizedFallbackSolver.solve(
        source_candidate_id=source.candidate_id,
        candidate_set=CandidateSetBuilder.build((source, first, second)),
        evaluation_context=_context(capabilities=capabilities),
        registry=registry,
    )
    assert result.resolution.status == (
        FallbackResolutionStatus.USER_CHOICE_REQUIRED
    )
    assert result.resolution.selected_destination_candidate_id == ""
    assert set(result.resolution.authorized_destination_candidate_ids) == {
        first.candidate_id,
        second.candidate_id,
    }


def test_blocked_destination_is_not_selected_by_fallback() -> None:
    payment_key = RulePackKey(Domain.PAYMENT, Operation.EXECUTE)
    content_key = RulePackKey(Domain.CONTENT, Operation.SHARE)
    source = _candidate(payment_key, clause="payment")
    destination = _candidate(content_key, clause="content")
    registry = FallbackEdgeRegistry(
        (_edge(_pattern("source", payment_key), _pattern("dest", content_key)),)
    )
    capabilities = frozenset(
        item for item in CapabilityType if item != CapabilityType.PAY
    )
    result = AuthorizedFallbackSolver.solve(
        source_candidate_id=source.candidate_id,
        candidate_set=CandidateSetBuilder.build((source, destination)),
        evaluation_context=_context(
            capabilities=capabilities,
            records=[
                {"id": "consent", "type": "consent", "value": "revoked"}
            ],
        ),
        registry=registry,
    )
    assert result.resolution.status == FallbackResolutionStatus.NOT_APPLIED


def test_viable_source_does_not_activate_fallback() -> None:
    payment_key = RulePackKey(Domain.PAYMENT, Operation.EXECUTE)
    content_key = RulePackKey(Domain.CONTENT, Operation.SHARE)
    source = _candidate(payment_key, clause="payment")
    destination = _candidate(content_key, clause="content")
    registry = FallbackEdgeRegistry(
        (_edge(_pattern("source", payment_key), _pattern("dest", content_key)),)
    )
    result = AuthorizedFallbackSolver.solve(
        source_candidate_id=source.candidate_id,
        candidate_set=CandidateSetBuilder.build((source, destination)),
        evaluation_context=_context(capabilities=frozenset(CapabilityType)),
        registry=registry,
    )
    assert result.resolution.status == FallbackResolutionStatus.NOT_NEEDED


def test_fallback_module_has_no_text_parser_or_default_dispatch() -> None:
    source = (PROJECT_ROOT / "core" / "fallbacks.py").read_text(encoding="utf-8")
    for prohibited in (
        "prompt",
        "visible_history",
        "re.compile",
        "default_dispatch",
        "LOWER_RANKED",
    ):
        assert prohibited not in source
    for relative in ("core/decision.py", "harness.py", "rules/plan.py"):
        production = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert "core.fallbacks" not in production
        assert "from .fallbacks" not in production
