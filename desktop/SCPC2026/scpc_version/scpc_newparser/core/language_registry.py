from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable

from .contracts import ContractStatus
from .evidence_model import (
    EvidenceKind,
    EvidenceStrength,
    RuleEvidenceProposal,
)
from .language_features import (
    EXTERNAL_CANCEL_RE,
    clarification_payload,
    domain_actions,
    domain_references,
    has_positive_share,
    is_decisive_stop_clause,
    is_memory_write_clause,
    is_redaction_clause,
    is_strong_local_clause,
    negated_domain_actions,
    operation_arguments,
)
from .surface_parser import (
    PredicateMood,
    PredicatePolarity,
    SurfaceParse,
    SurfacePredicate,
)


class LanguageRuleScope(str, Enum):
    PREDICATE_FRAME = "predicate_frame"
    CORRECTION_RELATION = "correction_relation"
    FALLBACK_RELATION = "fallback_relation"
    REFERENCE_MENTION = "reference_mention"


class SemanticSlot(str, Enum):
    OPERATION = "operation"
    DOMAIN = "domain"
    OPERATION_ARGUMENT = "operation_argument"
    TARGET = "target"
    CONTENT = "content"
    MEMORY = "memory"
    FALLBACK = "fallback"
    FOCAL = "focal"
    AUTHORITY = "authority"


class SurfaceFeature(str, Enum):
    DIRECT = "direct"
    NOT_QUOTED = "not_quoted"
    COMMAND = "command"
    INTERROGATIVE = "interrogative"
    POSITIVE = "positive"
    NEGATIVE = "negative"
    DOMAIN_PREDICATE = "domain_predicate"
    SAME_SEMANTIC_SLOT = "same_semantic_slot"
    EXPLICIT_FALLBACK_CONNECTOR = "explicit_fallback_connector"


@dataclass(frozen=True)
class LanguageRule:
    rule_id: str
    requires: tuple[SurfaceFeature, ...]
    forbids: tuple[SurfaceFeature, ...]
    scope: LanguageRuleScope
    semantic_slot: SemanticSlot
    emits: tuple[EvidenceKind, ...]
    priority: int
    contract_status: ContractStatus
    basis_refs: tuple[str, ...]
    assumption_refs: tuple[str, ...] = ()


LANGUAGE_RULES = (
    LanguageRule(
        rule_id="LANG-DOMAIN-EXECUTE-001",
        requires=(
            SurfaceFeature.NOT_QUOTED,
            SurfaceFeature.COMMAND,
            SurfaceFeature.POSITIVE,
            SurfaceFeature.DOMAIN_PREDICATE,
        ),
        forbids=(SurfaceFeature.NEGATIVE,),
        scope=LanguageRuleScope.PREDICATE_FRAME,
        semantic_slot=SemanticSlot.DOMAIN,
        emits=(EvidenceKind.EXPLICIT_DOMAIN_VERB, EvidenceKind.EXECUTION_REQUEST),
        priority=100,
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=("TERMS_GUIDE.md#prompt", "STEP4_SURFACE_CONTRACT"),
    ),
    LanguageRule(
        rule_id="LANG-DOMAIN-NEGATION-001",
        requires=(
            SurfaceFeature.NOT_QUOTED,
            SurfaceFeature.NEGATIVE,
            SurfaceFeature.DOMAIN_PREDICATE,
        ),
        forbids=(),
        scope=LanguageRuleScope.PREDICATE_FRAME,
        semantic_slot=SemanticSlot.DOMAIN,
        emits=(EvidenceKind.NEGATED_DOMAIN_VERB,),
        priority=110,
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=("STEP4_SURFACE_CONTRACT",),
    ),
    LanguageRule(
        rule_id="LANG-DOMAIN-VERIFY-001",
        requires=(
            SurfaceFeature.NOT_QUOTED,
            SurfaceFeature.INTERROGATIVE,
            SurfaceFeature.DOMAIN_PREDICATE,
        ),
        forbids=(SurfaceFeature.COMMAND,),
        scope=LanguageRuleScope.PREDICATE_FRAME,
        semantic_slot=SemanticSlot.DOMAIN,
        emits=(
            EvidenceKind.DOMAIN_REFERENCE,
            EvidenceKind.DOMAIN_VERIFY_REQUEST,
            EvidenceKind.VERIFY_REQUEST,
        ),
        priority=105,
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=("STEP4_SURFACE_CONTRACT",),
    ),
    LanguageRule(
        rule_id="LANG-DOMAIN-REFERENCE-001",
        requires=(
            SurfaceFeature.NOT_QUOTED,
            SurfaceFeature.DOMAIN_PREDICATE,
        ),
        forbids=(SurfaceFeature.COMMAND, SurfaceFeature.INTERROGATIVE),
        scope=LanguageRuleScope.PREDICATE_FRAME,
        semantic_slot=SemanticSlot.DOMAIN,
        emits=(EvidenceKind.DOMAIN_REFERENCE,),
        priority=10,
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=("TERMS_GUIDE.md#prompt",),
    ),
    LanguageRule(
        rule_id="LANG-TOGGLE-ARGUMENT-001",
        requires=(SurfaceFeature.NOT_QUOTED, SurfaceFeature.DOMAIN_PREDICATE),
        forbids=(),
        scope=LanguageRuleScope.PREDICATE_FRAME,
        semantic_slot=SemanticSlot.OPERATION_ARGUMENT,
        emits=(EvidenceKind.OPERATION_ARGUMENT,),
        priority=50,
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=("STEP4_SURFACE_CONTRACT",),
    ),
    LanguageRule(
        rule_id="LANG-SHARE-001",
        requires=(SurfaceFeature.NOT_QUOTED, SurfaceFeature.POSITIVE),
        forbids=(SurfaceFeature.NEGATIVE,),
        scope=LanguageRuleScope.PREDICATE_FRAME,
        semantic_slot=SemanticSlot.OPERATION,
        emits=(EvidenceKind.SHARE_REQUEST,),
        priority=70,
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=("TERMS_GUIDE.md#prompt",),
    ),
    LanguageRule(
        rule_id="LANG-SHARE-CANCEL-001",
        requires=(SurfaceFeature.NOT_QUOTED, SurfaceFeature.NEGATIVE),
        forbids=(),
        scope=LanguageRuleScope.PREDICATE_FRAME,
        semantic_slot=SemanticSlot.OPERATION,
        emits=(EvidenceKind.CANCEL_ACTION,),
        priority=80,
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=("STEP4_SURFACE_CONTRACT",),
    ),
    LanguageRule(
        rule_id="LANG-FALLBACK-001",
        requires=(SurfaceFeature.EXPLICIT_FALLBACK_CONNECTOR,),
        forbids=(),
        scope=LanguageRuleScope.FALLBACK_RELATION,
        semantic_slot=SemanticSlot.FALLBACK,
        emits=(EvidenceKind.AUTHORIZED_FALLBACK,),
        priority=100,
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=("STEP4_SURFACE_CONTRACT",),
    ),
    LanguageRule(
        rule_id="LANG-CORRECTION-001",
        requires=(SurfaceFeature.SAME_SEMANTIC_SLOT,),
        forbids=(SurfaceFeature.EXPLICIT_FALLBACK_CONNECTOR,),
        scope=LanguageRuleScope.CORRECTION_RELATION,
        semantic_slot=SemanticSlot.OPERATION,
        emits=(),
        priority=100,
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=("STEP4_SURFACE_CONTRACT",),
    ),
)


def _compatibility_rule(
    rule_id: str,
    semantic_slot: SemanticSlot,
    emits: tuple[EvidenceKind, ...],
    priority: int,
) -> LanguageRule:
    return LanguageRule(
        rule_id=rule_id,
        requires=(SurfaceFeature.NOT_QUOTED,),
        forbids=(),
        scope=LanguageRuleScope.PREDICATE_FRAME,
        semantic_slot=semantic_slot,
        emits=emits,
        priority=priority,
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        basis_refs=("STEP4_COMPATIBILITY_RULE_AUDIT",),
    )


LANGUAGE_RULES += (
    _compatibility_rule(
        "LANG-STOP-001", SemanticSlot.OPERATION, (EvidenceKind.STOP_PROCESS,), 200
    ),
    _compatibility_rule(
        "LANG-LOCAL-001",
        SemanticSlot.OPERATION,
        (EvidenceKind.LOCAL_UPDATE_REQUEST,),
        190,
    ),
    _compatibility_rule(
        "LANG-CLARIFY-001",
        SemanticSlot.OPERATION,
        (EvidenceKind.CLARIFICATION_REQUEST,),
        180,
    ),
    _compatibility_rule(
        "LANG-REDACTION-001",
        SemanticSlot.CONTENT,
        (EvidenceKind.REDACTION_REQUEST,),
        170,
    ),
    _compatibility_rule(
        "LANG-CONTENT-VARIANT-001",
        SemanticSlot.CONTENT,
        (EvidenceKind.CONTENT_VARIANT_SELECTION,),
        160,
    ),
    _compatibility_rule(
        "LANG-VALUE-TRANSFER-001",
        SemanticSlot.DOMAIN,
        (EvidenceKind.VALUE_TRANSFER_REQUEST,),
        150,
    ),
    _compatibility_rule(
        "LANG-MEMORY-CONTEXT-001",
        SemanticSlot.MEMORY,
        (EvidenceKind.MEMORY_CONTEXT_REFERENCE,),
        140,
    ),
    _compatibility_rule(
        "LANG-MEMORY-REJECTION-001",
        SemanticSlot.MEMORY,
        (EvidenceKind.MEMORY_REJECTION,),
        130,
    ),
    _compatibility_rule(
        "LANG-SESSION-TARGET-001",
        SemanticSlot.TARGET,
        (EvidenceKind.SESSION_TARGET_REFERENCE,),
        120,
    ),
    _compatibility_rule(
        "LANG-HISTORICAL-FOCAL-001",
        SemanticSlot.FOCAL,
        (EvidenceKind.HISTORICAL_FOCAL_REFERENCE,),
        120,
    ),
    _compatibility_rule(
        "LANG-POLICY-OVERRIDE-001",
        SemanticSlot.AUTHORITY,
        (EvidenceKind.POLICY_OVERRIDE_ATTEMPT,),
        210,
    ),
    _compatibility_rule(
        "LANG-VERIFY-001",
        SemanticSlot.OPERATION,
        (EvidenceKind.VERIFY_REQUEST,),
        60,
    ),
    _compatibility_rule(
        "LANG-EXECUTION-001",
        SemanticSlot.OPERATION,
        (EvidenceKind.EXECUTION_REQUEST,),
        60,
    ),
    _compatibility_rule(
        "LANG-MEMORY-WRITE-001",
        SemanticSlot.MEMORY,
        (EvidenceKind.MEMORY_WRITE_REQUEST,),
        100,
    ),
    _compatibility_rule(
        "LANG-DOMAIN-CANCEL-001",
        SemanticSlot.DOMAIN,
        (EvidenceKind.DOMAIN_CANCEL_REQUEST,),
        115,
    ),
)


class LanguageRuleRegistry:
    def __init__(self, rules: Iterable[LanguageRule] = LANGUAGE_RULES) -> None:
        self._rules = tuple(rules)
        self._by_id = {rule.rule_id: rule for rule in self._rules}
        self.validate()

    @property
    def rules(self) -> tuple[LanguageRule, ...]:
        return self._rules

    def validate(self) -> None:
        ids = [rule.rule_id for rule in self._rules]
        if len(ids) != len(set(ids)):
            raise ValueError("LanguageRuleRegistry contains duplicate rule IDs")
        for rule in self._rules:
            if not rule.rule_id or not rule.basis_refs:
                raise ValueError("language rule requires ID and basis refs")
            if rule.priority < 0:
                raise ValueError(f"negative language-rule priority: {rule.rule_id}")
            if not isinstance(rule.contract_status, ContractStatus):
                raise ValueError(f"invalid contract status: {rule.rule_id}")

    def propose(
        self,
        surface: SurfaceParse,
        *,
        direct: bool,
    ) -> tuple[RuleEvidenceProposal, ...]:
        proposals: list[RuleEvidenceProposal] = []
        for frame in surface.predicate_frames:
            if frame.quoted:
                continue
            if frame.predicate == SurfacePredicate.VERIFY:
                proposals.append(
                    self._proposal(
                        "LANG-VERIFY-001",
                        EvidenceKind.VERIFY_REQUEST,
                        "precondition",
                        "positive",
                        "operation",
                        frame.span,
                        direct,
                    )
                )
                continue
            domain = self._domain_for(frame.predicate)
            if frame.predicate == SurfacePredicate.SHARE:
                rule_id = (
                    "LANG-SHARE-CANCEL-001"
                    if frame.polarity == PredicatePolarity.NEGATIVE
                    else "LANG-SHARE-001"
                )
                kind = (
                    EvidenceKind.CANCEL_ACTION
                    if frame.polarity == PredicatePolarity.NEGATIVE
                    else EvidenceKind.SHARE_REQUEST
                )
                proposals.append(
                    self._proposal(
                        rule_id,
                        kind,
                        "dispatch",
                        "negative"
                        if frame.polarity == PredicatePolarity.NEGATIVE
                        else "positive",
                        "external",
                        frame.span,
                        direct,
                    )
                )
                continue
            if not domain:
                continue
            if frame.polarity == PredicatePolarity.NEGATIVE:
                proposals.append(
                    self._proposal(
                        "LANG-DOMAIN-NEGATION-001",
                        EvidenceKind.NEGATED_DOMAIN_VERB,
                        domain,
                        "negative",
                        "domain",
                        frame.span,
                        direct,
                    )
                )
            elif frame.mood == PredicateMood.INTERROGATIVE:
                for kind, payload, scope in (
                    (EvidenceKind.DOMAIN_REFERENCE, domain, "domain"),
                    (EvidenceKind.DOMAIN_VERIFY_REQUEST, domain, "domain"),
                    (EvidenceKind.VERIFY_REQUEST, "precondition", "operation"),
                ):
                    proposals.append(
                        self._proposal(
                            "LANG-DOMAIN-VERIFY-001",
                            kind,
                            payload,
                            "positive",
                            scope,
                            frame.span,
                            direct,
                        )
                    )
            elif frame.mood == PredicateMood.COMMAND:
                for kind, payload, scope in (
                    (EvidenceKind.EXPLICIT_DOMAIN_VERB, domain, "domain"),
                    (EvidenceKind.EXECUTION_REQUEST, "primary_action", "operation"),
                ):
                    proposals.append(
                        self._proposal(
                            "LANG-DOMAIN-EXECUTE-001",
                            kind,
                            payload,
                            "positive",
                            scope,
                            frame.span,
                            direct,
                        )
                    )
            else:
                proposals.append(
                    self._proposal(
                        "LANG-DOMAIN-REFERENCE-001",
                        EvidenceKind.DOMAIN_REFERENCE,
                        domain,
                        "positive",
                        "domain",
                        frame.span,
                        direct,
                    )
                )
            if frame.polarity == PredicatePolarity.POSITIVE and frame.predicate in {
                SurfacePredicate.ENABLE,
                SurfacePredicate.ENABLE_STATE,
                SurfacePredicate.DISABLE,
                SurfacePredicate.DISABLE_STATE,
            }:
                desired_state = (
                    "enabled"
                    if frame.predicate
                    in {SurfacePredicate.ENABLE, SurfacePredicate.ENABLE_STATE}
                    else "disabled"
                )
                proposals.append(
                    self._proposal(
                        "LANG-TOGGLE-ARGUMENT-001",
                        EvidenceKind.OPERATION_ARGUMENT,
                        f"TOGGLE:desired_state:{desired_state}",
                        "positive",
                        "operation_argument",
                        frame.span,
                        direct,
                    )
                )

        fallback_rule = self._by_id["LANG-FALLBACK-001"]
        for relation in surface.fallback_relations:
            proposals.append(
                RuleEvidenceProposal(
                    rule_id=fallback_rule.rule_id,
                    kind=EvidenceKind.AUTHORIZED_FALLBACK,
                    payload="user_explicit_alternative",
                    polarity="positive",
                    scope="fallback",
                    strength=(
                        EvidenceStrength.STRONG
                        if direct
                        else EvidenceStrength.SUPPORTING
                    ),
                    semantic_slot=SemanticSlot.FALLBACK.value,
                    source_span=relation.span,
                    contract_status=fallback_rule.contract_status,
                    assumption_refs=fallback_rule.assumption_refs,
                )
            )
        return self._dedupe(proposals)

    def propose_clause(
        self,
        clause: str,
        *,
        direct: bool,
        source_span: tuple[int, int],
    ) -> tuple[RuleEvidenceProposal, ...]:
        """Compatibility rule path; emits evidence only, never a decision."""
        proposals: list[RuleEvidenceProposal] = []
        decisive = EvidenceStrength.DECISIVE if direct else EvidenceStrength.STRONG
        strong = EvidenceStrength.STRONG if direct else EvidenceStrength.SUPPORTING

        def add(
            rule_id: str,
            kind: EvidenceKind,
            payload: str,
            polarity: str,
            scope: str,
            strength: EvidenceStrength,
        ) -> None:
            proposals.append(
                self._proposal_at_strength(
                    rule_id,
                    kind,
                    payload,
                    polarity,
                    scope,
                    source_span,
                    strength,
                )
            )

        clarification = clarification_payload(clause)
        if is_decisive_stop_clause(clause) and not clarification:
            add(
                "LANG-STOP-001",
                EvidenceKind.STOP_PROCESS,
                "primary_action",
                "negative",
                "operation",
                decisive,
            )
        if is_strong_local_clause(clause):
            add(
                "LANG-LOCAL-001",
                EvidenceKind.LOCAL_UPDATE_REQUEST,
                "local_state",
                "positive",
                "local",
                decisive,
            )
        elif any(
            term in clause
            for term in ("로컬", "내부 상태", "상태 기록", "local_update_boundary")
        ):
            add(
                "LANG-LOCAL-001",
                EvidenceKind.LOCAL_UPDATE_REQUEST,
                "local_state",
                "positive",
                "local",
                EvidenceStrength.SUPPORTING,
            )

        if clarification:
            add(
                "LANG-CLARIFY-001",
                EvidenceKind.CLARIFICATION_REQUEST,
                clarification,
                "positive",
                "operation",
                decisive,
            )
        if is_redaction_clause(clause):
            add(
                "LANG-REDACTION-001",
                EvidenceKind.REDACTION_REQUEST,
                "sensitive_fields",
                "negative",
                "content",
                strong,
            )

        variant_roots = {
            root
            for root in ("원본", "원문", "사진", "이미지", "익명", "요약")
            if root in clause
        }
        if len(variant_roots) >= 2 and any(
            root in clause for root in ("고르", "선택", "중", "무엇")
        ):
            add(
                "LANG-CONTENT-VARIANT-001",
                EvidenceKind.CONTENT_VARIANT_SELECTION,
                "content_variant",
                "positive",
                "content",
                strong,
            )
        if "쿠폰" in clause and any(
            root in clause for root in ("보내", "전달", "사용", "결제")
        ):
            add(
                "LANG-VALUE-TRANSFER-001",
                EvidenceKind.VALUE_TRANSFER_REQUEST,
                "stored_value",
                "positive",
                "domain",
                strong,
            )
        recalls_context = any(
            root in clause for root in ("지난번", "저장한", "메모리", "기억")
        )
        if recalls_context and any(root in clause for root in ("조명", "루틴")):
            add(
                "LANG-MEMORY-CONTEXT-001",
                EvidenceKind.MEMORY_CONTEXT_REFERENCE,
                "lighting_routine",
                "positive",
                "memory",
                strong,
            )
        if recalls_context and any(
            root in clause for root in ("검진", "점검", "병원", "캘린더")
        ):
            add(
                "LANG-MEMORY-CONTEXT-001",
                EvidenceKind.MEMORY_CONTEXT_REFERENCE,
                "health_schedule",
                "positive",
                "memory",
                strong,
            )
        rejects_memory = (
            any(root in clause for root in ("기록", "메모리", "이전 설정"))
            and any(root in clause for root in ("무시", "사용하지", "버리고"))
        ) or (
            "수신처" in clause
            and any(root in clause for root in ("새로운", "새로", "변경"))
        )
        if rejects_memory:
            add(
                "LANG-MEMORY-REJECTION-001",
                EvidenceKind.MEMORY_REJECTION,
                "stored_context",
                "negative",
                "memory",
                strong,
            )
        has_anaphora = any(
            root in clause for root in ("같은", "이전", "지난번", "그곳", "직전")
        )
        has_target_role = any(
            root in clause
            for root in ("곳", "수신처", "target", "대상", "방식", "성공")
        )
        if has_anaphora and has_target_role:
            add(
                "LANG-SESSION-TARGET-001",
                EvidenceKind.SESSION_TARGET_REFERENCE,
                "prior_target",
                "positive",
                "target",
                strong,
            )
        if any(
            root in clause
            for root in ("방금", "그거", "그것", "지운", "삭제", "되돌", "undo")
        ):
            add(
                "LANG-HISTORICAL-FOCAL-001",
                EvidenceKind.HISTORICAL_FOCAL_REFERENCE,
                "prior_focal",
                "positive",
                "focal",
                strong,
            )
        if any(
            root in clause for root in ("이전 지시", "규칙", "보안", "정책")
        ) and any(root in clause for root in ("무시", "건너뛰", "우회")):
            add(
                "LANG-POLICY-OVERRIDE-001",
                EvidenceKind.POLICY_OVERRIDE_ATTEMPT,
                "authority_override",
                "negative",
                "authority",
                strong,
            )
        if any(
            root in clause
            for root in ("할 수 없으면", "안 되면", "불가능하면", "실패하면")
        ):
            add(
                "LANG-FALLBACK-001",
                EvidenceKind.AUTHORIZED_FALLBACK,
                "user_explicit_alternative",
                "positive",
                "fallback",
                strong,
            )

        if has_positive_share(clause):
            add(
                "LANG-SHARE-001",
                EvidenceKind.SHARE_REQUEST,
                "dispatch",
                "positive",
                "external",
                strong,
            )
        if any(term in clause for term in ("확인", "검토", "점검")):
            add(
                "LANG-VERIFY-001",
                EvidenceKind.VERIFY_REQUEST,
                "precondition",
                "positive",
                "operation",
                EvidenceStrength.SUPPORTING,
            )
        if any(
            term in clause
            for term in (
                "처리해",
                "수행",
                "실행",
                "바꿔",
                "켜줘",
                "꺼줘",
                "결제해",
                "저장해",
            )
        ):
            add(
                "LANG-EXECUTION-001",
                EvidenceKind.EXECUTION_REQUEST,
                "primary_action",
                "positive",
                "operation",
                strong,
            )
        if EXTERNAL_CANCEL_RE.search(clause) or re.search(
            r"(?:보내|공유|전달)[^.!?]{0,20}(?:지\s*마|말고|취소)", clause
        ):
            add(
                "LANG-SHARE-CANCEL-001",
                EvidenceKind.CANCEL_ACTION,
                "dispatch",
                "negative",
                "external",
                decisive,
            )
        if is_memory_write_clause(clause):
            add(
                "LANG-MEMORY-WRITE-001",
                EvidenceKind.MEMORY_WRITE_REQUEST,
                "memory",
                "positive",
                "local",
                decisive,
            )
        actions = domain_actions(clause)
        negated_actions = negated_domain_actions(clause)
        references = domain_references(clause)
        if actions and not any(
            item.kind == EvidenceKind.EXECUTION_REQUEST for item in proposals
        ):
            add(
                "LANG-DOMAIN-EXECUTE-001",
                EvidenceKind.EXECUTION_REQUEST,
                "primary_action",
                "positive",
                "operation",
                strong,
            )
        for action in actions:
            add(
                "LANG-DOMAIN-EXECUTE-001",
                EvidenceKind.EXPLICIT_DOMAIN_VERB,
                action,
                "positive",
                "domain",
                strong,
            )
        for action in negated_actions:
            add(
                "LANG-DOMAIN-NEGATION-001",
                EvidenceKind.NEGATED_DOMAIN_VERB,
                action,
                "negative",
                "domain",
                decisive,
            )
        for action, argument in operation_arguments(clause):
            add(
                "LANG-TOGGLE-ARGUMENT-001",
                EvidenceKind.OPERATION_ARGUMENT,
                f"{action}:{argument}",
                "positive",
                "operation_argument",
                strong,
            )
        for action in references:
            add(
                "LANG-DOMAIN-REFERENCE-001",
                EvidenceKind.DOMAIN_REFERENCE,
                action,
                "positive",
                "domain",
                strong,
            )
        domain_cancel = (
            bool(references)
            and not EXTERNAL_CANCEL_RE.search(clause)
            and any(root in clause for root in ("취소", "철회", "되돌", "중지"))
        )
        if domain_cancel:
            for action in references:
                add(
                    "LANG-DOMAIN-CANCEL-001",
                    EvidenceKind.DOMAIN_CANCEL_REQUEST,
                    action,
                    "negative",
                    "domain",
                    decisive,
                )
        domain_verify_only = (
            bool(references)
            and not actions
            and not any(item.kind == EvidenceKind.SHARE_REQUEST for item in proposals)
            and not any(
                item.kind == EvidenceKind.EXECUTION_REQUEST for item in proposals
            )
            and bool(re.search(r"(?:확인|검증|점검)(?:해|하|할|해야|하고)", clause))
        )
        if domain_verify_only:
            for action in references:
                add(
                    "LANG-DOMAIN-VERIFY-001",
                    EvidenceKind.DOMAIN_VERIFY_REQUEST,
                    action,
                    "positive",
                    "domain",
                    strong,
                )
        return tuple(proposals)

    def _proposal(
        self,
        rule_id: str,
        kind: EvidenceKind,
        payload: str,
        polarity: str,
        scope: str,
        span: tuple[int, int],
        direct: bool,
    ) -> RuleEvidenceProposal:
        return self._proposal_at_strength(
            rule_id,
            kind,
            payload,
            polarity,
            scope,
            span,
            EvidenceStrength.STRONG if direct else EvidenceStrength.SUPPORTING,
        )

    def _proposal_at_strength(
        self,
        rule_id: str,
        kind: EvidenceKind,
        payload: str,
        polarity: str,
        scope: str,
        span: tuple[int, int],
        strength: EvidenceStrength,
    ) -> RuleEvidenceProposal:
        rule = self._by_id[rule_id]
        if kind not in rule.emits:
            raise ValueError(f"rule {rule_id} cannot emit {kind.value}")
        return RuleEvidenceProposal(
            rule_id=rule_id,
            kind=kind,
            payload=payload,
            polarity=polarity,
            scope=scope,
            strength=strength,
            semantic_slot=rule.semantic_slot.value,
            source_span=span,
            contract_status=rule.contract_status,
            assumption_refs=rule.assumption_refs,
        )

    @staticmethod
    def _domain_for(predicate: SurfacePredicate) -> str:
        if predicate == SurfacePredicate.PAY:
            return "PAY"
        if predicate in {
            SurfacePredicate.ENABLE,
            SurfacePredicate.ENABLE_STATE,
            SurfacePredicate.DISABLE,
            SurfacePredicate.DISABLE_STATE,
        }:
            return "TOGGLE"
        if predicate == SurfacePredicate.SCHEDULE:
            return "SCHEDULE"
        return ""

    def _dedupe(
        self,
        proposals: list[RuleEvidenceProposal],
    ) -> tuple[RuleEvidenceProposal, ...]:
        rows: list[RuleEvidenceProposal] = []
        positions: dict[tuple[object, ...], int] = {}
        for item in proposals:
            key = (
                item.kind,
                item.payload,
                item.polarity,
                item.scope,
                item.semantic_slot,
                item.source_span,
            )
            if key not in positions:
                positions[key] = len(rows)
                rows.append(item)
                continue
            current_index = positions[key]
            current = rows[current_index]
            if (
                self._by_id[item.rule_id].priority
                > self._by_id[current.rule_id].priority
            ):
                rows[current_index] = item
        return tuple(rows)


LANGUAGE_RULE_REGISTRY = LanguageRuleRegistry()


def validate_language_rule_registry() -> None:
    LANGUAGE_RULE_REGISTRY.validate()
