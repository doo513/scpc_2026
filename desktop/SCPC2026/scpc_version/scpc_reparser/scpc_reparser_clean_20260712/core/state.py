from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterable

from core.evidence import EvidenceKind, EvidenceStrength, IntentEvidenceSet
from core.evidence_graph import EvidenceGraph
from core.ontology import Domain, Operation, RecordType
from core.relations import RelationGraph
from core.records import RecordCode
from core.session_state import MemoryStore
from core.task_view import TaskView
from rules.focal import FocalDecision, FocalResolver
from rules.target import TargetCandidate, TargetResolver


class CoarseIntent(str, Enum):
    STOP = "stop"
    CLARIFY = "clarify"
    LOCAL_UPDATE = "local_update"
    DOMAIN_OPERATION = "domain_operation"
    EXTERNAL_SHARE = "external_share"
    VERIFY = "verify"
    GENERIC_EXECUTION = "generic_execution"
    UNSPECIFIED = "unspecified"


OperationMode = Operation


@dataclass(frozen=True)
class CoarseIntentCandidate:
    intent: CoarseIntent
    rank: int
    confidence: str
    supporting_evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class FocalCandidate:
    focal_id: str
    object_type: str
    source: str
    confidence: str
    current_object: bool
    derived_from: tuple[str, ...]


@dataclass(frozen=True)
class DomainContext:
    family: Domain
    focal_type: str
    compatible_action: str
    referenced_actions: tuple[str, ...]
    operation_modes: tuple[OperationMode, ...]
    focal_compatible: bool
    supporting_evidence_ids: tuple[str, ...]

    @property
    def is_domain_bound(self) -> bool:
        return self.family != Domain.UNKNOWN and self.focal_compatible


@dataclass(frozen=True)
class OperationHypothesis:
    action: str
    mode: OperationMode
    rank: int
    confidence: str
    supporting_evidence_ids: tuple[str, ...]
    candidate_role: str = "primary"


@dataclass(frozen=True)
class OperationIntent:
    primary: CoarseIntent
    hypotheses: tuple[OperationHypothesis, ...]
    domain_context: DomainContext
    decisive_stop_ids: tuple[str, ...]
    derived_from: tuple[str, ...]


@dataclass(frozen=True)
class AssembledState:
    view: TaskView
    evidence: EvidenceGraph
    relation_graph: RelationGraph
    focal_candidates: tuple[FocalCandidate, ...]
    coarse_intents: tuple[CoarseIntentCandidate, ...]
    focal_decision: FocalDecision
    focal: dict[str, Any]
    domain_context: DomainContext
    operation_intent: OperationIntent
    target_candidates: tuple[TargetCandidate, ...]

    def to_trace(self) -> dict[str, Any]:
        return {
            "focal_candidates": [
                {
                    "focal_id": item.focal_id,
                    "object_type": item.object_type,
                    "source": item.source,
                    "confidence": item.confidence,
                    "current_object": item.current_object,
                    "derived_from": list(item.derived_from),
                }
                for item in self.focal_candidates
            ],
            "coarse_intents": [
                {
                    "intent": item.intent.value,
                    "rank": item.rank,
                    "confidence": item.confidence,
                    "supporting_evidence_ids": list(item.supporting_evidence_ids),
                }
                for item in self.coarse_intents
            ],
            "domain_context": {
                "family": self.domain_context.family.value,
                "focal_type": self.domain_context.focal_type,
                "compatible_action": self.domain_context.compatible_action,
                "referenced_actions": list(self.domain_context.referenced_actions),
                "operation_modes": [mode.value for mode in self.domain_context.operation_modes],
                "focal_compatible": self.domain_context.focal_compatible,
                "supporting_evidence_ids": list(
                    self.domain_context.supporting_evidence_ids
                ),
            },
            "operation_intent": {
                "primary": self.operation_intent.primary.value,
                "hypotheses": [
                    {
                        "action": item.action,
                        "mode": item.mode.value,
                        "rank": item.rank,
                        "confidence": item.confidence,
                        "supporting_evidence_ids": list(
                            item.supporting_evidence_ids
                        ),
                        "candidate_role": item.candidate_role,
                    }
                    for item in self.operation_intent.hypotheses
                ],
                "decisive_stop_ids": list(
                    self.operation_intent.decisive_stop_ids
                ),
                "derived_from": list(self.operation_intent.derived_from),
            },
            "target_candidates": [candidate.__dict__ for candidate in self.target_candidates],
        }


class IntentResolver:
    DOMAIN_BY_OBJECT = {
        "payment_request": (Domain.PAYMENT, "pay"),
        "device_setting": (Domain.DEVICE, "toggle"),
        "iot_routine": (Domain.DEVICE, "toggle"),
        "calendar_event": (Domain.CALENDAR, "schedule"),
    }
    @classmethod
    def coarse_candidates(
        cls, evidence: IntentEvidenceSet
    ) -> tuple[CoarseIntentCandidate, ...]:
        rows: list[CoarseIntentCandidate] = []

        def add(
            intent: CoarseIntent,
            ids: Iterable[str],
            rank: int,
            confidence: str,
        ) -> None:
            ids = tuple(dict.fromkeys(ids))
            if ids and not any(item.intent == intent for item in rows):
                rows.append(CoarseIntentCandidate(intent, rank, confidence, ids))

        add(
            CoarseIntent.STOP,
            evidence.current_ids(
                EvidenceKind.STOP_PROCESS, minimum=EvidenceStrength.DECISIVE
            ),
            120,
            "high",
        )
        add(
            CoarseIntent.CLARIFY,
            evidence.current_ids(
                EvidenceKind.CLARIFICATION_REQUEST,
                minimum=EvidenceStrength.DECISIVE,
            ),
            110,
            "high",
        )
        local_ids = evidence.prompt_ids(
            EvidenceKind.LOCAL_UPDATE_REQUEST, minimum=EvidenceStrength.STRONG
        )
        memory_ids = evidence.prompt_ids(
            EvidenceKind.MEMORY_WRITE_REQUEST, minimum=EvidenceStrength.STRONG
        )
        add(CoarseIntent.LOCAL_UPDATE, memory_ids + local_ids, 100, "high")

        domain_ids = tuple(
            item.evidence_id
            for kind in (
                EvidenceKind.EXPLICIT_DOMAIN_VERB,
                EvidenceKind.DOMAIN_REFERENCE,
                EvidenceKind.DOMAIN_CANCEL_REQUEST,
                EvidenceKind.DOMAIN_VERIFY_REQUEST,
            )
            for item in evidence.prompt_evidence(
                kind, minimum=EvidenceStrength.SUPPORTING
            )
        )
        add(CoarseIntent.DOMAIN_OPERATION, domain_ids, 90, "high")
        add(
            CoarseIntent.EXTERNAL_SHARE,
            evidence.prompt_ids(
                EvidenceKind.SHARE_REQUEST, minimum=EvidenceStrength.SUPPORTING
            ),
            80,
            "high",
        )
        add(
            CoarseIntent.VERIFY,
            evidence.prompt_ids(
                EvidenceKind.VERIFY_REQUEST, minimum=EvidenceStrength.SUPPORTING
            ),
            70,
            "medium",
        )
        add(
            CoarseIntent.GENERIC_EXECUTION,
            evidence.prompt_ids(
                EvidenceKind.EXECUTION_REQUEST,
                minimum=EvidenceStrength.SUPPORTING,
            ),
            60,
            "medium",
        )
        if not rows:
            rows.append(
                CoarseIntentCandidate(
                    CoarseIntent.UNSPECIFIED, 0, "low", ("intent:unspecified",)
                )
            )
        return tuple(sorted(rows, key=lambda item: (-item.rank, item.intent.value)))

    @classmethod
    def domain_context(
        cls,
        focal: dict[str, Any],
        evidence: IntentEvidenceSet,
    ) -> DomainContext:
        focal_type = str(focal.get("type") or "")
        family, compatible_action = cls.DOMAIN_BY_OBJECT.get(
            focal_type, (Domain.UNKNOWN, "")
        )
        references: list[str] = []
        modes: list[OperationMode] = []
        evidence_ids: list[str] = []
        kind_modes = {
            EvidenceKind.EXPLICIT_DOMAIN_VERB: OperationMode.EXECUTE,
            EvidenceKind.DOMAIN_CANCEL_REQUEST: OperationMode.CANCEL,
            EvidenceKind.DOMAIN_VERIFY_REQUEST: OperationMode.VERIFY,
        }
        for kind in (
            EvidenceKind.EXPLICIT_DOMAIN_VERB,
            EvidenceKind.DOMAIN_REFERENCE,
            EvidenceKind.DOMAIN_CANCEL_REQUEST,
            EvidenceKind.DOMAIN_VERIFY_REQUEST,
        ):
            for item in evidence.prompt_evidence(
                kind, minimum=EvidenceStrength.SUPPORTING
            ):
                action = item.payload.lower()
                if action and action not in references:
                    references.append(action)
                if kind in kind_modes and kind_modes[kind] not in modes:
                    modes.append(kind_modes[kind])
                evidence_ids.append(item.evidence_id)
        focal_compatible = bool(
            compatible_action
            and (
                not references
                or compatible_action in references
            )
        )
        return DomainContext(
            family=family,
            focal_type=focal_type,
            compatible_action=compatible_action,
            referenced_actions=tuple(references),
            operation_modes=tuple(modes),
            focal_compatible=focal_compatible,
            supporting_evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        )

    @classmethod
    def resolve_operation(
        cls,
        view: TaskView,
        evidence: IntentEvidenceSet,
        coarse: tuple[CoarseIntentCandidate, ...],
        domain: DomainContext,
    ) -> OperationIntent:
        hypotheses: list[OperationHypothesis] = []

        def add(
            action: str,
            mode: OperationMode,
            rank: int,
            confidence: str,
            ids: Iterable[str],
            candidate_role: str = "primary",
        ) -> None:
            if any(
                item.action == action and item.mode == mode for item in hypotheses
            ):
                return
            hypotheses.append(
                OperationHypothesis(
                    action=action,
                    mode=mode,
                    rank=rank,
                    confidence=confidence,
                    supporting_evidence_ids=tuple(dict.fromkeys(ids)),
                    candidate_role=candidate_role,
                )
            )

        clarification_ids = tuple(
            item.evidence_id
            for item in evidence.current(
                EvidenceKind.CLARIFICATION_REQUEST,
                minimum=EvidenceStrength.DECISIVE,
            )
            if item.payload == "clarify_user"
        )
        # A request for confirmation changes execution disposition; it does
        # not replace an otherwise resolvable domain/operation candidate.

        memory_ids = evidence.prompt_ids(
            EvidenceKind.MEMORY_WRITE_REQUEST, minimum=EvidenceStrength.STRONG
        )
        local_ids = evidence.prompt_ids(
            EvidenceKind.LOCAL_UPDATE_REQUEST, minimum=EvidenceStrength.STRONG
        )
        if memory_ids or view.record_present(RecordType.PERSISTENT_MEMORY_WRITE):
            add(
                "memory_update",
                OperationMode.LOCAL_UPDATE,
                100,
                "high",
                memory_ids or ("record:persistent_memory_write",),
            )
        elif local_ids:
            add(
                "local_update",
                OperationMode.LOCAL_UPDATE,
                95,
                "high",
                local_ids,
            )
        elif (
            view.record_code(RecordType.SHARE_BOUNDARY_UPDATE)
            == RecordCode.SHARE_BOUNDARY_LOCAL
            and domain.focal_type == "file"
        ):
            # A file is a data resource rather than an execution endpoint.
            # A typed local boundary therefore creates a local-update
            # operation candidate upstream instead of rewriting a dispatch
            # plan after selection.
            add(
                "local_update",
                OperationMode.LOCAL_UPDATE,
                85,
                "high",
                ("record:share_boundary_update:local",),
            )

        if domain.is_domain_bound:
            domain_mode_ids = {
                OperationMode.CANCEL: evidence.prompt_ids(
                    EvidenceKind.DOMAIN_CANCEL_REQUEST
                ),
                OperationMode.VERIFY: evidence.prompt_ids(
                    EvidenceKind.DOMAIN_VERIFY_REQUEST
                ),
                OperationMode.EXECUTE: evidence.prompt_ids(
                    EvidenceKind.EXPLICIT_DOMAIN_VERB
                ),
            }
            for mode in (
                OperationMode.CANCEL,
                OperationMode.VERIFY,
                OperationMode.EXECUTE,
            ):
                ids = domain_mode_ids[mode]
                if not ids:
                    continue
                add(
                    domain.compatible_action,
                    mode,
                    90 if mode != OperationMode.EXECUTE else 80,
                    "high",
                    ids,
                )
            execute_ids = evidence.prompt_ids(
                EvidenceKind.EXECUTION_REQUEST,
                minimum=EvidenceStrength.SUPPORTING,
            )
            verify_ids = evidence.prompt_ids(
                EvidenceKind.VERIFY_REQUEST,
                minimum=EvidenceStrength.SUPPORTING,
            )
            share_ids = evidence.prompt_ids(
                EvidenceKind.SHARE_REQUEST,
                minimum=EvidenceStrength.SUPPORTING,
            )
            if verify_ids and not execute_ids and not share_ids and not any(
                item.action == domain.compatible_action for item in hypotheses
            ):
                add(
                    domain.compatible_action,
                    OperationMode.VERIFY,
                    72,
                    "medium",
                    verify_ids + (f"focal_type:{domain.focal_type}",),
                )
            if execute_ids and not share_ids and not any(
                item.action == domain.compatible_action for item in hypotheses
            ):
                add(
                    domain.compatible_action,
                    OperationMode.EXECUTE,
                    75,
                    "medium",
                    execute_ids + (f"focal_type:{domain.focal_type}",),
                )
        else:
            unresolved_domain_ids = evidence.prompt_ids(
                EvidenceKind.DOMAIN_CANCEL_REQUEST
            ) + evidence.prompt_ids(EvidenceKind.DOMAIN_VERIFY_REQUEST)
            if unresolved_domain_ids:
                add(
                    "clarify",
                    OperationMode.CLARIFY,
                    105,
                    "high",
                    unresolved_domain_ids
                    + ("domain_context:focal_mismatch",),
                )

        share_ids = evidence.prompt_ids(
            EvidenceKind.SHARE_REQUEST, minimum=EvidenceStrength.SUPPORTING
        )
        cancelled_share_ids = evidence.current_ids(
            EvidenceKind.CANCEL_ACTION,
            minimum=EvidenceStrength.STRONG,
        )
        if cancelled_share_ids and not any(
            item.action == "dispatch" for item in hypotheses
        ):
            add(
                "dispatch",
                OperationMode.SHARE,
                20,
                "low",
                cancelled_share_ids,
                candidate_role="negated",
            )
        if share_ids:
            add(
                "dispatch",
                OperationMode.SHARE,
                60,
                "high",
                share_ids,
            )
        has_primary_operation = any(
            item.candidate_role == "primary" for item in hypotheses
        )
        route_evidence_ids = tuple(
            f"record:{record_type}"
            for record_type in (
                "resolved_target",
                "route_candidate_snapshot",
                "dispatch_authority_check",
                "share_boundary_update",
            )
            if view.record_present(record_type)
        )
        if not has_primary_operation and route_evidence_ids:
            add(
                "dispatch",
                OperationMode.SHARE,
                50,
                "medium",
                route_evidence_ids,
                candidate_role="structural",
            )
        if not hypotheses:
            add(
                "unresolved",
                OperationMode.UNRESOLVED,
                0,
                "none",
                clarification_ids or ("intent:operation_unresolved",),
                candidate_role="unresolved",
            )

        decisive_latest_ids = {
            item.evidence_id
            for item in evidence.current(
                minimum=EvidenceStrength.DECISIVE
            )
        }
        evidence_source_by_id = {
            item.evidence_id: item.provenance.source_kind
            for item in evidence.evidence
        }
        has_decisive_primary = any(
            item.candidate_role == "primary"
            and decisive_latest_ids.intersection(
                item.supporting_evidence_ids
            )
            for item in hypotheses
        )
        if has_decisive_primary:
            hypotheses = [
                replace(item, candidate_role="contextual")
                if item.candidate_role == "primary"
                and not decisive_latest_ids.intersection(
                    item.supporting_evidence_ids
                )
                and not any(
                    evidence_source_by_id.get(evidence_id)
                    == "current_prompt"
                    for evidence_id in item.supporting_evidence_ids
                )
                else item
                for item in hypotheses
            ]

        primary = coarse[0].intent if coarse else CoarseIntent.UNSPECIFIED
        stop_ids = evidence.current_ids(
            EvidenceKind.STOP_PROCESS, minimum=EvidenceStrength.DECISIVE
        )
        derived = tuple(
            dict.fromkeys(
                stop_ids
                + tuple(
                    evidence_id
                    for item in hypotheses
                    for evidence_id in item.supporting_evidence_ids
                )
            )
        )
        return OperationIntent(
            primary=primary,
            hypotheses=tuple(
                sorted(
                    hypotheses,
                    key=lambda item: (-item.rank, item.action, item.mode.value),
                )
            ),
            domain_context=domain,
            decisive_stop_ids=stop_ids,
            derived_from=derived,
        )


class StateAssembler:
    @classmethod
    def assemble(
        cls,
        view: TaskView,
        memory_store: MemoryStore | dict[str, Any] | None,
        session: dict[str, Any],
    ) -> AssembledState:
        evidence = EvidenceGraph.from_view(view)
        coarse = IntentResolver.coarse_candidates(evidence.intent_evidence)
        relation_graph = RelationGraph(view)
        focal_decision = FocalResolver.resolve_decision(
            view,
            evidence,
            session,
            relation_graph=relation_graph,
        )
        focal_decision = cls._joint_focal_resolution(
            view, focal_decision, coarse, evidence, session
        )
        focal = view.objects_by_id().get(focal_decision.focal_id) or {}
        if not focal and focal_decision.source == "session_snapshot":
            snapshot = session.get("last_focal_snapshot")
            focal = dict(snapshot) if isinstance(snapshot, dict) else {}

        evidence = evidence.with_focal(view, focal_decision.focal_id)
        domain = IntentResolver.domain_context(focal, evidence.intent_evidence)
        operation = IntentResolver.resolve_operation(
            view, evidence.intent_evidence, coarse, domain
        )
        target_candidates = TargetResolver.resolve_candidates(
            view,
            evidence,
            focal_decision.focal_id,
            memory_store,
            focal_override=focal,
        )
        focal_candidates = cls._focal_candidates(
            view, focal_decision, session
        )
        return AssembledState(
            view=view,
            evidence=evidence,
            relation_graph=relation_graph,
            focal_candidates=focal_candidates,
            coarse_intents=coarse,
            focal_decision=focal_decision,
            focal=focal,
            domain_context=domain,
            operation_intent=operation,
            target_candidates=target_candidates,
        )

    @classmethod
    def _joint_focal_resolution(
        cls,
        view: TaskView,
        decision: FocalDecision,
        coarse: tuple[CoarseIntentCandidate, ...],
        evidence: EvidenceGraph,
        session: dict[str, Any],
    ) -> FocalDecision:
        if decision.focal_id:
            return decision

        domain_actions = {
            item.payload.lower()
            for kind in (
                EvidenceKind.EXPLICIT_DOMAIN_VERB,
                EvidenceKind.DOMAIN_REFERENCE,
                EvidenceKind.DOMAIN_CANCEL_REQUEST,
                EvidenceKind.DOMAIN_VERIFY_REQUEST,
            )
            for item in evidence.intent_evidence.prompt_evidence(kind)
        }
        compatible = []
        for obj in view.objects:
            _family, action = IntentResolver.DOMAIN_BY_OBJECT.get(
                str(obj.get("type") or ""), (Domain.UNKNOWN, "")
            )
            if action and action in domain_actions:
                compatible.append(obj)
        if len(compatible) == 1:
            focal_id = str(compatible[0].get("id") or "")
            return FocalDecision(
                focal_id=focal_id,
                source="intent_object_joint",
                confidence="medium",
                candidates=(focal_id,),
                reasons=("unique_domain_compatible_object",),
                derived_from=tuple(
                    item.evidence_id
                    for kind in (
                        EvidenceKind.EXPLICIT_DOMAIN_VERB,
                        EvidenceKind.DOMAIN_REFERENCE,
                        EvidenceKind.DOMAIN_CANCEL_REQUEST,
                        EvidenceKind.DOMAIN_VERIFY_REQUEST,
                    )
                    for item in evidence.intent_evidence.prompt_evidence(kind)
                ),
            )

        snapshot = session.get("last_focal_snapshot")
        last_focal_id = str(session.get("last_focal_id") or "")
        if (
            last_focal_id
            and isinstance(snapshot, dict)
            and evidence.intent_evidence.prompt_evidence(
                EvidenceKind.HISTORICAL_FOCAL_REFERENCE
            )
        ):
            return FocalDecision(
                focal_id=last_focal_id,
                source="session_snapshot",
                confidence="medium",
                candidates=(last_focal_id,),
                reasons=("explicit_historical_reference",),
                resolution_status="historical",
                selected_reference=last_focal_id,
                integrity_checks=("same_session_snapshot",),
                derived_from=("session:last_focal_snapshot",),
            )
        return decision

    @staticmethod
    def _focal_candidates(
        view: TaskView,
        decision: FocalDecision,
        session: dict[str, Any],
    ) -> tuple[FocalCandidate, ...]:
        rows = [
            FocalCandidate(
                focal_id=str(obj.get("id") or ""),
                object_type=str(obj.get("type") or ""),
                source=(
                    decision.source
                    if str(obj.get("id") or "") == decision.focal_id
                    else "current_object"
                ),
                confidence=(
                    decision.confidence
                    if str(obj.get("id") or "") == decision.focal_id
                    else "low"
                ),
                current_object=True,
                derived_from=(
                    decision.derived_from
                    if str(obj.get("id") or "") == decision.focal_id
                    else (f"object:{str(obj.get('id') or '')}",)
                ),
            )
            for obj in sorted(view.objects, key=lambda item: str(item.get("id") or ""))
        ]
        if decision.source == "session_snapshot":
            snapshot = session.get("last_focal_snapshot") or {}
            rows.append(
                FocalCandidate(
                    focal_id=decision.focal_id,
                    object_type=str(snapshot.get("type") or ""),
                    source="session_snapshot",
                    confidence=decision.confidence,
                    current_object=False,
                    derived_from=decision.derived_from,
                )
            )
        return tuple(rows)
