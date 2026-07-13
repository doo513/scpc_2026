from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable

from .evidence_model import AssertionMode, EvidenceKind, IntentEvidence
from .surface_parser import SurfaceParse


class EvidenceSourceClass(str, Enum):
    CURRENT_EXPLICIT = "current_explicit"
    CURRENT_INFERRED = "current_inferred"
    HISTORY_REFERENCE = "history_reference"
    SESSION_STATE = "session_state"
    PERSONAL_MEMORY = "personal_memory"
    REPORTED_OR_QUOTED = "reported_or_quoted"


@dataclass(frozen=True)
class EvidenceBindingKey:
    semantic_slot: str
    subject: str


@dataclass(frozen=True)
class BindingDecision:
    superseding_id: str
    superseded_ids: tuple[str, ...]
    binding_key: EvidenceBindingKey
    reason: str


@dataclass(frozen=True)
class ContextBindingResult:
    evidence: tuple[IntentEvidence, ...]
    decisions: tuple[BindingDecision, ...]
    independent_evidence_ids: tuple[str, ...]

    def to_trace(self) -> dict[str, object]:
        return {
            "scope_limited_partial_order": True,
            "structural_facts_participate": False,
            "hard_constraints_participate": False,
            "partial_order": [
                EvidenceSourceClass.CURRENT_EXPLICIT.value,
                EvidenceSourceClass.CURRENT_INFERRED.value,
                EvidenceSourceClass.HISTORY_REFERENCE.value,
                EvidenceSourceClass.SESSION_STATE.value,
                EvidenceSourceClass.PERSONAL_MEMORY.value,
            ],
            "decisions": [
                {
                    "superseding_id": item.superseding_id,
                    "superseded_ids": list(item.superseded_ids),
                    "semantic_slot": item.binding_key.semantic_slot,
                    "subject": item.binding_key.subject,
                    "reason": item.reason,
                }
                for item in self.decisions
            ],
            "independent_evidence_ids": list(self.independent_evidence_ids),
        }


class ContextBinder:
    """Applies supersession only within a shared semantic slot and subject."""

    @classmethod
    def bind(
        cls,
        evidence: Iterable[IntentEvidence],
        surface: SurfaceParse | None = None,
    ) -> ContextBindingResult:
        rows = list(evidence)
        replacements: dict[str, IntentEvidence] = {}
        decisions: list[BindingDecision] = []
        superseders = [
            item
            for item in rows
            if item.active
            and item.provenance.source_kind == "current_prompt"
            and item.provenance.assertion_mode == AssertionMode.DIRECT.value
            and item.kind
            in {EvidenceKind.NEGATED_DOMAIN_VERB, EvidenceKind.CANCEL_ACTION}
        ]
        correction_spans = {
            relation.span for relation in (surface.corrections if surface else ())
        }

        for superseder in superseders:
            key = cls.binding_key(superseder)
            if key is None:
                continue
            superseded = [
                item
                for item in rows
                if item.active
                and item.evidence_id != superseder.evidence_id
                and cls._lower_authority_source(item)
                and cls._matches_supersession(superseder, item, rows)
            ]
            if not superseded:
                continue
            superseded_ids = tuple(item.evidence_id for item in superseded)
            replacements[superseder.evidence_id] = replace(
                superseder,
                supersedes=superseded_ids,
            )
            for item in superseded:
                replacements[item.evidence_id] = replace(
                    item,
                    active=False,
                    superseded_by=(superseder.evidence_id,),
                )
            decisions.append(
                BindingDecision(
                    superseding_id=superseder.evidence_id,
                    superseded_ids=superseded_ids,
                    binding_key=key,
                    reason=(
                        "same_slot_explicit_correction"
                        if correction_spans
                        else "same_slot_explicit_negation"
                    ),
                )
            )

        bound = tuple(replacements.get(item.evidence_id, item) for item in rows)
        touched = {
            item_id
            for decision in decisions
            for item_id in (decision.superseding_id, *decision.superseded_ids)
        }
        return ContextBindingResult(
            evidence=bound,
            decisions=tuple(decisions),
            independent_evidence_ids=tuple(
                item.evidence_id for item in bound if item.evidence_id not in touched
            ),
        )

    @staticmethod
    def binding_key(item: IntentEvidence) -> EvidenceBindingKey | None:
        if item.kind in {
            EvidenceKind.EXPLICIT_DOMAIN_VERB,
            EvidenceKind.NEGATED_DOMAIN_VERB,
            EvidenceKind.DOMAIN_REFERENCE,
            EvidenceKind.DOMAIN_CANCEL_REQUEST,
            EvidenceKind.DOMAIN_VERIFY_REQUEST,
        }:
            return EvidenceBindingKey("domain_operation", item.payload)
        if item.kind == EvidenceKind.OPERATION_ARGUMENT:
            domain = item.payload.split(":", 1)[0]
            return EvidenceBindingKey("operation_argument", domain)
        if item.kind in {EvidenceKind.SHARE_REQUEST, EvidenceKind.CANCEL_ACTION}:
            return EvidenceBindingKey("operation", "dispatch")
        if item.kind == EvidenceKind.EXECUTION_REQUEST:
            return EvidenceBindingKey("operation", "primary_action")
        return EvidenceBindingKey(item.scope, item.payload)

    @staticmethod
    def _lower_authority_source(item: IntentEvidence) -> bool:
        if item.provenance.assertion_mode != AssertionMode.DIRECT.value:
            return True
        return item.provenance.source_kind in {
            "current_prompt_context",
            "visible_history",
            "session_state",
            "personal_memory",
        }

    @classmethod
    def _matches_supersession(
        cls,
        superseder: IntentEvidence,
        candidate: IntentEvidence,
        all_evidence: list[IntentEvidence],
    ) -> bool:
        if superseder.kind == EvidenceKind.NEGATED_DOMAIN_VERB:
            if candidate.kind == EvidenceKind.EXPLICIT_DOMAIN_VERB:
                return candidate.payload == superseder.payload
            if candidate.kind == EvidenceKind.OPERATION_ARGUMENT:
                return candidate.payload.startswith(f"{superseder.payload}:")
            if candidate.kind == EvidenceKind.EXECUTION_REQUEST:
                return any(
                    peer.kind == EvidenceKind.EXPLICIT_DOMAIN_VERB
                    and peer.payload == superseder.payload
                    and peer.provenance.source_kind == candidate.provenance.source_kind
                    and peer.provenance.span == candidate.provenance.span
                    for peer in all_evidence
                )
            return False
        return (
            superseder.kind == EvidenceKind.CANCEL_ACTION
            and superseder.payload == "dispatch"
            and candidate.kind == EvidenceKind.SHARE_REQUEST
        )
