from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import language_features as _language_features
from .context_binder import ContextBinder, ContextBindingResult
from .evidence_model import (
    AssertionMode,
    EvidenceKind,
    EvidenceStrength,
    IntentEvidence,
    RuleEvidenceProposal,
)
from .language_registry import LANGUAGE_RULE_REGISTRY
from .prompt_document import (
    PromptDocument,
    TextAuthority,
    canonical_text,
    latest_clause_from_text,
    normalize_text,
)
from .records import Provenance
from .surface_parser import SurfaceParse, SurfaceParser


is_clarification_request = _language_features.is_clarification_request
is_decisive_stop = _language_features.is_decisive_stop
is_redaction_request = _language_features.is_redaction_request
is_reported_clause = _language_features.is_reported_clause
is_strong_local = _language_features.is_strong_local


@dataclass(frozen=True)
class CanonicalEvidenceGroup:
    group_id: str
    canonical_text_key: str
    member_ids: tuple[str, ...]
    current_prompt_reasserted: bool
    history_only: bool
    quoted_or_reported: bool


@dataclass(frozen=True)
class IntentEvidenceSet:
    evidence: tuple[IntentEvidence, ...]
    groups: tuple[CanonicalEvidenceGroup, ...]
    latest_clause: str
    prompt_document: PromptDocument | None = None
    surface_parse: SurfaceParse | None = None
    context_binding: ContextBindingResult | None = None
    registry_proposals: tuple[RuleEvidenceProposal, ...] = ()

    def of_kind(self, kind: EvidenceKind) -> tuple[IntentEvidence, ...]:
        return tuple(
            item for item in self.evidence if item.kind == kind and item.active
        )

    def has(self, kind: EvidenceKind, *, minimum: EvidenceStrength | None = None) -> bool:
        ranks = {
            EvidenceStrength.SUPPORTING: 1,
            EvidenceStrength.STRONG: 2,
            EvidenceStrength.DECISIVE: 3,
        }
        return any(
            item.kind == kind
            and item.active
            and (minimum is None or ranks[item.strength] >= ranks[minimum])
            for item in self.evidence
        )

    def ids(self, kind: EvidenceKind) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.of_kind(kind))

    def current(
        self,
        kind: EvidenceKind | None = None,
        *,
        minimum: EvidenceStrength | None = None,
    ) -> tuple[IntentEvidence, ...]:
        ranks = {
            EvidenceStrength.SUPPORTING: 1,
            EvidenceStrength.STRONG: 2,
            EvidenceStrength.DECISIVE: 3,
        }
        return tuple(
            item
            for item in self.evidence
            if item.provenance.source_kind == "current_prompt"
            and item.provenance.assertion_mode == AssertionMode.DIRECT.value
            and item.active
            and (kind is None or item.kind == kind)
            and (minimum is None or ranks[item.strength] >= ranks[minimum])
        )

    def current_ids(
        self,
        kind: EvidenceKind,
        *,
        minimum: EvidenceStrength | None = None,
    ) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.current(kind, minimum=minimum))

    def prompt_evidence(
        self,
        kind: EvidenceKind | None = None,
        *,
        minimum: EvidenceStrength | None = None,
    ) -> tuple[IntentEvidence, ...]:
        ranks = {
            EvidenceStrength.SUPPORTING: 1,
            EvidenceStrength.STRONG: 2,
            EvidenceStrength.DECISIVE: 3,
        }
        return tuple(
            item
            for item in self.evidence
            if item.provenance.source_kind
            in {"current_prompt", "current_prompt_context"}
            and item.provenance.assertion_mode == AssertionMode.DIRECT.value
            and item.active
            and (kind is None or item.kind == kind)
            and (minimum is None or ranks[item.strength] >= ranks[minimum])
        )

    def prompt_ids(
        self,
        kind: EvidenceKind,
        *,
        minimum: EvidenceStrength | None = None,
    ) -> tuple[str, ...]:
        return tuple(
            item.evidence_id
            for item in self.prompt_evidence(kind, minimum=minimum)
        )

    def to_trace(self) -> dict[str, Any]:
        return {
            "latest_clause": self.latest_clause,
            "evidence": [
                {
                    "id": item.evidence_id,
                    "kind": item.kind.value,
                    "payload": item.payload,
                    "polarity": item.polarity,
                    "scope": item.scope,
                    "strength": item.strength.value,
                    "source_kind": item.provenance.source_kind,
                    "source_id": item.provenance.source_id,
                    "turn": item.provenance.turn,
                    "span": list(item.provenance.span) if item.provenance.span else None,
                    "assertion_mode": item.provenance.assertion_mode,
                    "active": item.active,
                    "supersedes": list(item.supersedes),
                    "superseded_by": list(item.superseded_by),
                    "authority": item.authority,
                    "rule_id": item.rule_id,
                    "contract_status": item.contract_status.value,
                    "assumption_refs": list(item.assumption_refs),
                    "semantic_slot": item.semantic_slot,
                }
                for item in self.evidence
            ],
            "groups": [
                {
                    "id": group.group_id,
                    "member_ids": list(group.member_ids),
                    "current_prompt_reasserted": group.current_prompt_reasserted,
                    "history_only": group.history_only,
                    "quoted_or_reported": group.quoted_or_reported,
                }
                for group in self.groups
            ],
            "prompt_document": (
                self.prompt_document.to_trace() if self.prompt_document else None
            ),
            "surface_parse": (
                self.surface_parse.to_trace() if self.surface_parse else None
            ),
            "context_binding": (
                self.context_binding.to_trace() if self.context_binding else None
            ),
            "registry_proposals": [
                {
                    "rule_id": item.rule_id,
                    "kind": item.kind.value,
                    "payload": item.payload,
                    "polarity": item.polarity,
                    "scope": item.scope,
                    "strength": item.strength.value,
                    "semantic_slot": item.semantic_slot,
                    "source_span": list(item.source_span),
                    "contract_status": item.contract_status.value,
                    "assumption_refs": list(item.assumption_refs),
                }
                for item in self.registry_proposals
            ],
        }


class IntentEvidenceExtractor:
    @classmethod
    def extract(cls, view: Any) -> IntentEvidenceSet:
        prompt = normalize_text(view.prompt)
        prompt_document = PromptDocument.parse(prompt)
        surface_parse = SurfaceParser.parse(prompt)
        registry_proposals = LANGUAGE_RULE_REGISTRY.propose(
            surface_parse,
            direct=True,
        )
        latest_clause, latest_span = latest_clause_from_text(prompt)
        evidence: list[IntentEvidence] = []

        if latest_clause and latest_span:
            context = prompt[: latest_span[0]].rstrip()
            if context:
                evidence.extend(
                    cls._extract_text(
                        context,
                        source_kind="current_prompt_context",
                        source_id=f"{view.task_id}:context",
                        session_id=view.session_id,
                        turn=view.turn_index,
                        span=(0, len(context)),
                        assertion_mode=AssertionMode.DIRECT,
                        id_prefix="prompt_context",
                    )
                )
        evidence.extend(
            cls._extract_text(
                latest_clause or prompt,
                source_kind="current_prompt",
                source_id=f"{view.task_id}:latest" if latest_clause else view.task_id,
                session_id=view.session_id,
                turn=view.turn_index,
                span=latest_span or (0, len(prompt)),
                assertion_mode=AssertionMode.DIRECT,
                id_prefix="prompt",
            )
        )

        history_items = sorted(
            view.history,
            key=lambda item: (cls._turn(item), normalize_text(item.get("summary", item))),
        )
        for index, item in enumerate(history_items):
            summary = normalize_text(item.get("summary", item))
            if not summary:
                continue
            mode = AssertionMode.REPORTED
            if _language_features.reports_quoted_instruction(summary):
                mode = AssertionMode.QUOTED
            history_evidence = cls._extract_text(
                summary,
                source_kind="visible_history",
                source_id=f"{view.task_id}:history:{index}",
                session_id=view.session_id,
                turn=cls._turn(item),
                span=(0, len(summary)),
                assertion_mode=mode,
                id_prefix=f"history_{index}",
            )
            evidence.extend(history_evidence)

        context_binding = ContextBinder.bind(evidence, surface_parse)
        evidence = list(context_binding.evidence)
        groups_by_key: dict[str, list[IntentEvidence]] = {}
        for item in evidence:
            groups_by_key.setdefault(item.canonical_text_key, []).append(item)
        groups = tuple(
            CanonicalEvidenceGroup(
                group_id=f"evidence_group:{index}",
                canonical_text_key=key,
                member_ids=tuple(item.evidence_id for item in members),
                current_prompt_reasserted=any(
                    item.provenance.source_kind == "current_prompt" for item in members
                ),
                history_only=all(
                    item.provenance.source_kind == "visible_history" for item in members
                ),
                quoted_or_reported=any(
                    item.provenance.assertion_mode != AssertionMode.DIRECT.value for item in members
                ),
            )
            for index, (key, members) in enumerate(sorted(groups_by_key.items()))
        )
        return IntentEvidenceSet(
            tuple(evidence),
            groups,
            latest_clause,
            prompt_document,
            surface_parse,
            context_binding,
            registry_proposals,
        )

    @classmethod
    def _extract_text(
        cls,
        text: str,
        *,
        source_kind: str,
        source_id: str,
        session_id: str,
        turn: int | None,
        span: tuple[int, int],
        assertion_mode: AssertionMode,
        id_prefix: str,
    ) -> list[IntentEvidence]:
        normalized = normalize_text(text)
        if not normalized:
            return []
        extracted: list[IntentEvidence] = []
        base_offset = span[0]
        evidence_index = 0

        authority = (
            TextAuthority.DIRECT_USER
            if assertion_mode == AssertionMode.DIRECT
            else TextAuthority.REPORTED_CONTEXT
        )
        document = PromptDocument.parse(normalized, authority=authority)
        for clause_span in document.clauses:
            clause = clause_span.directive_text
            original_clause = clause_span.text
            clause_start, clause_end = clause_span.span
            if not normalize_text(clause):
                continue
            clause_mode = assertion_mode
            if assertion_mode == AssertionMode.DIRECT and is_reported_clause(clause):
                clause_mode = AssertionMode.REPORTED
            direct = source_kind == "current_prompt" and clause_mode == AssertionMode.DIRECT
            proposals = LANGUAGE_RULE_REGISTRY.propose_clause(
                clause,
                direct=direct,
                source_span=(clause_start, clause_end),
            )

            provenance = Provenance(
                source_kind=source_kind,
                source_id=source_id,
                session_id=session_id,
                turn=turn,
                span=(base_offset + clause_start, base_offset + clause_end),
                assertion_mode=clause_mode.value,
            )
            key = canonical_text(original_clause)
            for proposal in proposals:
                extracted.append(
                    IntentEvidence(
                        evidence_id=(
                            f"intent:{id_prefix}:{evidence_index}:"
                            f"{proposal.kind.value}"
                        ),
                        kind=proposal.kind,
                        payload=proposal.payload,
                        polarity=proposal.polarity,
                        scope=proposal.scope,
                        strength=proposal.strength,
                        text=original_clause,
                        canonical_text_key=key,
                        provenance=provenance,
                        authority=clause_span.authority.value,
                        rule_id=proposal.rule_id,
                        contract_status=proposal.contract_status,
                        assumption_refs=proposal.assumption_refs,
                        semantic_slot=proposal.semantic_slot,
                    )
                )
                evidence_index += 1
        return extracted

    @staticmethod
    def _turn(item: dict[str, Any]) -> int:
        try:
            return int(item.get("turn", -1))
        except (TypeError, ValueError):
            return -1
