from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .candidate_evaluation import (
    CandidateEvaluationContext,
    CandidateEvaluationEngine,
    CandidateEvaluationResult,
    CandidateSet,
    CapabilityEvaluationStatus,
    EvaluationCandidate,
)
from .contracts import ContractStatus
from .ontology import CandidateState, ReasonCode, TargetLocality, TargetRole
from .rulepacks import RulePackKey
from .slm_contract import EvidenceAuthorityClass


class FallbackAuthorizationSource(str, Enum):
    CURRENT_USER_EXPLICIT = "current_user_explicit"
    OFFICIAL_POLICY = "official_policy"
    OFFICIAL_TRANSFORMATION = "official_transformation"


class FallbackActivationCondition(str, Enum):
    SOURCE_CAPABILITY_UNAVAILABLE = "source_capability_unavailable"
    SOURCE_BLOCKED = "source_blocked"
    SOURCE_NON_EXECUTABLE = "source_non_executable"


class SemanticPreservation(str, Enum):
    USER_SPECIFIED_ALTERNATIVE = "user_specified_alternative"
    POLICY_AUTHORIZED_REDUCTION = "policy_authorized_reduction"
    OFFICIAL_EQUIVALENT_OPERATION = "official_equivalent_operation"


class FallbackResolutionStatus(str, Enum):
    NOT_NEEDED = "not_needed"
    NOT_APPLIED = "not_applied"
    APPLIED = "applied"
    USER_CHOICE_REQUIRED = "user_choice_required"


@dataclass(frozen=True)
class CandidatePattern:
    pattern_id: str
    rulepack_keys: tuple[RulePackKey, ...]
    target_roles: tuple[TargetRole, ...] = ()
    target_localities: tuple[TargetLocality, ...] = ()

    def __post_init__(self) -> None:
        if not self.pattern_id or not self.rulepack_keys:
            raise ValueError("fallback candidate pattern requires typed semantics")
        if len(self.rulepack_keys) != len(set(self.rulepack_keys)):
            raise ValueError("fallback candidate pattern has duplicate RulePack keys")
        if len(self.target_roles) != len(set(self.target_roles)):
            raise ValueError("fallback candidate pattern has duplicate target roles")
        if len(self.target_localities) != len(set(self.target_localities)):
            raise ValueError("fallback candidate pattern has duplicate target localities")

    def matches(self, candidate: EvaluationCandidate) -> bool:
        return (
            candidate.semantic_key.rulepack_key in self.rulepack_keys
            and (
                not self.target_roles
                or candidate.target_role in self.target_roles
            )
            and (
                not self.target_localities
                or candidate.target_locality in self.target_localities
            )
        )

    @property
    def graph_key(self) -> tuple[object, ...]:
        keys = tuple(
            sorted(
                self.rulepack_keys,
                key=lambda item: (
                    item.domain.value,
                    item.operation.value,
                    item.variant.value if item.variant else "",
                ),
            )
        )
        return (
            keys,
            tuple(sorted(self.target_roles, key=lambda item: item.value)),
            tuple(sorted(self.target_localities, key=lambda item: item.value)),
        )


@dataclass(frozen=True)
class FallbackAuthorization:
    source: FallbackAuthorizationSource
    reference_ids: tuple[str, ...]
    structurally_validated: bool
    evidence_authority_class: EvidenceAuthorityClass | None = None

    def __post_init__(self) -> None:
        if tuple(sorted(set(self.reference_ids))) != self.reference_ids:
            raise ValueError("fallback authorization references must be canonical")


@dataclass(frozen=True)
class FallbackEdge:
    edge_id: str
    source_candidate_pattern: CandidatePattern
    destination_candidate_pattern: CandidatePattern
    authorization: FallbackAuthorization
    activation_condition: FallbackActivationCondition
    semantic_preservation: SemanticPreservation
    maximum_hops: int
    reason_code: ReasonCode
    contract_status: ContractStatus

    def __post_init__(self) -> None:
        if not self.edge_id or self.maximum_hops < 1:
            raise ValueError("fallback edge requires identity and positive hop limit")

    @property
    def is_authorized(self) -> bool:
        return (
            self.authorization.structurally_validated
            and bool(self.authorization.reference_ids)
            and (
                self.authorization.source
                != FallbackAuthorizationSource.CURRENT_USER_EXPLICIT
                or self.authorization.evidence_authority_class
                == EvidenceAuthorityClass.CURRENT_DIRECT
            )
            and self.contract_status
            in {
                ContractStatus.CONFIRMED_CONTRACT,
                ContractStatus.SUPPORTED_INTERPRETATION,
            }
        )


class FallbackEdgeRegistry:
    production_active = False

    def __init__(self, edges: Iterable[FallbackEdge] = ()) -> None:
        self.edges = tuple(edges)
        self.validate()

    def validate(self) -> None:
        ids = [item.edge_id for item in self.edges]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate fallback edge ID")
        for edge in self.edges:
            if not edge.is_authorized:
                raise ValueError(f"unauthorized fallback edge: {edge.edge_id}")
            if self._patterns_overlap(
                edge.source_candidate_pattern,
                edge.destination_candidate_pattern,
            ):
                raise ValueError(f"fallback self-loop: {edge.edge_id}")
            if edge.maximum_hops != 1:
                raise ValueError(
                    f"multi-hop fallback is not implemented: {edge.edge_id}"
                )
        self._reject_cycles()

    def _reject_cycles(self) -> None:
        adjacency = {
            index: {
                other_index
                for other_index, other in enumerate(self.edges)
                if self._patterns_overlap(
                    edge.destination_candidate_pattern,
                    other.source_candidate_pattern,
                )
            }
            for index, edge in enumerate(self.edges)
        }
        visiting: set[int] = set()
        visited: set[int] = set()

        def visit(node: int) -> None:
            if node in visiting:
                raise ValueError("fallback graph contains a cycle")
            if node in visited:
                return
            visiting.add(node)
            for child in adjacency[node]:
                visit(child)
            visiting.remove(node)
            visited.add(node)

        for node in adjacency:
            visit(node)

    @staticmethod
    def _patterns_overlap(
        left: CandidatePattern,
        right: CandidatePattern,
    ) -> bool:
        if not (set(left.rulepack_keys) & set(right.rulepack_keys)):
            return False
        roles_overlap = (
            not left.target_roles
            or not right.target_roles
            or bool(set(left.target_roles) & set(right.target_roles))
        )
        localities_overlap = (
            not left.target_localities
            or not right.target_localities
            or bool(set(left.target_localities) & set(right.target_localities))
        )
        return roles_overlap and localities_overlap


FALLBACK_EDGE_REGISTRY = FallbackEdgeRegistry()


@dataclass(frozen=True)
class FallbackTrace:
    edge_id: str
    source_candidate_id: str
    destination_candidate_id: str
    authorization_source: FallbackAuthorizationSource
    authorization_reference_ids: tuple[str, ...]
    reason_code: ReasonCode


@dataclass(frozen=True)
class FallbackResolution:
    status: FallbackResolutionStatus
    source_candidate_id: str
    selected_destination_candidate_id: str
    authorized_destination_candidate_ids: tuple[str, ...]
    traces: tuple[FallbackTrace, ...]
    reason_code: ReasonCode | None


@dataclass(frozen=True)
class FallbackSolveResult:
    evaluations: tuple[CandidateEvaluationResult, ...]
    resolution: FallbackResolution


class AuthorizedFallbackSolver:
    """Re-evaluates every destination through CandidateEvaluationEngine."""

    @classmethod
    def solve(
        cls,
        *,
        source_candidate_id: str,
        candidate_set: CandidateSet,
        evaluation_context: CandidateEvaluationContext,
        registry: FallbackEdgeRegistry,
    ) -> FallbackSolveResult:
        evaluations = CandidateEvaluationEngine.evaluate_set(
            candidate_set,
            evaluation_context,
        )
        by_id = {item.candidate.candidate_id: item for item in evaluations}
        source = by_id.get(source_candidate_id)
        if source is None:
            raise ValueError("fallback source was not evaluated")
        if source.candidate_state in {CandidateState.VIABLE, CandidateState.AMENDABLE}:
            return FallbackSolveResult(
                evaluations,
                FallbackResolution(
                    FallbackResolutionStatus.NOT_NEEDED,
                    source_candidate_id,
                    "",
                    (),
                    (),
                    None,
                ),
            )

        applicable_edges = tuple(
            sorted(
                (
                    edge
                    for edge in registry.edges
                    if edge.source_candidate_pattern.matches(source.candidate)
                    and cls._condition_matches(edge.activation_condition, source)
                ),
                key=lambda item: item.edge_id,
            )
        )
        destination_rows: dict[
            str,
            tuple[CandidateEvaluationResult, list[FallbackEdge]],
        ] = {}
        for edge in applicable_edges:
            for evaluation in evaluations:
                if not edge.destination_candidate_pattern.matches(
                    evaluation.candidate
                ):
                    continue
                if evaluation.candidate_state not in {
                    CandidateState.VIABLE,
                    CandidateState.AMENDABLE,
                }:
                    continue
                if (
                    evaluation.assessment.capability.status
                    != CapabilityEvaluationStatus.AVAILABLE
                ):
                    continue
                row = destination_rows.setdefault(
                    evaluation.candidate.candidate_id,
                    (evaluation, []),
                )
                row[1].append(edge)
        destination_ids = tuple(sorted(destination_rows))
        traces = tuple(
            FallbackTrace(
                edge_id=edge.edge_id,
                source_candidate_id=source_candidate_id,
                destination_candidate_id=candidate_id,
                authorization_source=edge.authorization.source,
                authorization_reference_ids=edge.authorization.reference_ids,
                reason_code=edge.reason_code,
            )
            for candidate_id in destination_ids
            for edge in destination_rows[candidate_id][1]
        )
        if len(destination_ids) == 1:
            return FallbackSolveResult(
                evaluations,
                FallbackResolution(
                    FallbackResolutionStatus.APPLIED,
                    source_candidate_id,
                    destination_ids[0],
                    destination_ids,
                    traces,
                    ReasonCode.AVOIDED_BY_AUTHORIZED_FALLBACK,
                ),
            )
        if len(destination_ids) > 1:
            return FallbackSolveResult(
                evaluations,
                FallbackResolution(
                    FallbackResolutionStatus.USER_CHOICE_REQUIRED,
                    source_candidate_id,
                    "",
                    destination_ids,
                    traces,
                    ReasonCode.FALLBACK_USER_CHOICE_REQUIRED,
                ),
            )
        return FallbackSolveResult(
            evaluations,
            FallbackResolution(
                FallbackResolutionStatus.NOT_APPLIED,
                source_candidate_id,
                "",
                (),
                (),
                None,
            ),
        )

    @staticmethod
    def _condition_matches(
        condition: FallbackActivationCondition,
        source: CandidateEvaluationResult,
    ) -> bool:
        if condition == FallbackActivationCondition.SOURCE_CAPABILITY_UNAVAILABLE:
            return (
                source.assessment.capability.status
                == CapabilityEvaluationStatus.UNAVAILABLE
            )
        if condition == FallbackActivationCondition.SOURCE_BLOCKED:
            return source.candidate_state == CandidateState.BLOCKED
        return source.candidate_state not in {
            CandidateState.VIABLE,
            CandidateState.AMENDABLE,
        }


def validate_fallback_registry() -> None:
    FALLBACK_EDGE_REGISTRY.validate()
