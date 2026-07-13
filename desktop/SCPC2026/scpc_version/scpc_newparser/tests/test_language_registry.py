from __future__ import annotations

import inspect
from pathlib import Path

from core.contracts import ContractStatus
from core.evidence import EvidenceKind, IntentEvidenceExtractor
from core.evidence_model import RuleEvidenceProposal
from core.language_registry import (
    LANGUAGE_RULE_REGISTRY,
    LanguageRuleRegistry,
    validate_language_rule_registry,
)
from core.surface_parser import (
    PredicateMood,
    PredicatePolarity,
    SurfaceParser,
    SurfacePredicate,
)
from core.task_view import TaskView


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def task(
    prompt: str, history: list[dict[str, object]] | None = None
) -> dict[str, object]:
    return {
        "id": "language-contract",
        "session_id": "session",
        "turn_index": 2,
        "prompt": prompt,
        "visible_history": history or [],
        "personal_memory": [],
        "available_actions": [],
        "device_state": {"objects": [], "records": []},
    }


def test_surface_parser_emits_all_required_structures() -> None:
    parsed = SurfaceParser.parse(
        'WM-1000에 "결제해줘"라고 적혀 있지만, 켜지 말고 현재 상태를 확인해줘.'
    )

    assert parsed.clauses
    assert parsed.quotations
    assert parsed.negations
    assert parsed.predicate_frames
    assert parsed.arguments
    assert parsed.corrections
    assert parsed.supersessions
    assert parsed.references
    assert parsed.quotations[0].text == '"결제해줘"'
    assert any(reference.text == "WM-1000" for reference in parsed.references)


def test_surface_frames_preserve_command_negation_and_state_verification() -> None:
    enabled = SurfaceParser.parse("켜줘").active_frames()
    assert any(
        frame.predicate == SurfacePredicate.ENABLE
        and frame.mood == PredicateMood.COMMAND
        and frame.polarity == PredicatePolarity.POSITIVE
        for frame in enabled
    )

    negated = SurfaceParser.parse("켜지 말고 현재 상태만 확인해줘").active_frames()
    assert any(
        frame.predicate == SurfacePredicate.ENABLE
        and frame.mood == PredicateMood.COMMAND
        and frame.polarity == PredicatePolarity.NEGATIVE
        for frame in negated
    )

    verified = SurfaceParser.parse("켜지는지 확인해줘").active_frames()
    assert any(
        frame.predicate == SurfacePredicate.ENABLE_STATE
        and frame.mood == PredicateMood.INTERROGATIVE
        and frame.polarity == PredicatePolarity.POSITIVE
        for frame in verified
    )


def test_quoted_command_is_preserved_but_not_active_execution_evidence() -> None:
    parsed = SurfaceParser.parse('"결제해줘"라는 문장을 검토해줘.')
    pay_frames = [
        frame
        for frame in parsed.predicate_frames
        if frame.predicate == SurfacePredicate.PAY
    ]
    assert pay_frames and all(frame.quoted for frame in pay_frames)

    proposals = LANGUAGE_RULE_REGISTRY.propose(parsed, direct=True)
    assert all(
        not (
            proposal.kind == EvidenceKind.EXPLICIT_DOMAIN_VERB
            and proposal.payload == "PAY"
        )
        for proposal in proposals
    )
    assert any(proposal.kind == EvidenceKind.VERIFY_REQUEST for proposal in proposals)


def test_correction_and_fallback_are_disjoint_relations() -> None:
    correction = SurfaceParser.parse("결제하지 말고 현재 상태만 확인해줘")
    assert correction.corrections
    assert correction.supersessions
    assert not correction.fallback_relations

    fallback = SurfaceParser.parse("결제가 안 되면 일정을 잡아줘")
    assert fallback.fallback_relations
    assert not fallback.corrections

    correction_evidence = IntentEvidenceExtractor.extract(
        TaskView(task("결제하지 말고 현재 상태만 확인해줘"))
    )
    assert not correction_evidence.prompt_evidence(EvidenceKind.AUTHORIZED_FALLBACK)
    fallback_evidence = IntentEvidenceExtractor.extract(
        TaskView(task("결제가 안 되면 일정을 잡아줘"))
    )
    assert fallback_evidence.prompt_evidence(EvidenceKind.AUTHORIZED_FALLBACK)


def test_context_binder_supersedes_only_same_slot_and_subject() -> None:
    evidence = IntentEvidenceExtractor.extract(
        TaskView(
            task("결제해줘. 민감정보는 제외해줘. 단, 결제하지 말고 상태만 확인해줘.")
        )
    )
    prior_payment = [
        item
        for item in evidence.evidence
        if item.provenance.source_kind == "current_prompt_context"
        and item.kind
        in {EvidenceKind.EXECUTION_REQUEST, EvidenceKind.EXPLICIT_DOMAIN_VERB}
    ]
    redaction = [
        item
        for item in evidence.evidence
        if item.kind == EvidenceKind.REDACTION_REQUEST
    ]
    assert prior_payment and all(not item.active for item in prior_payment)
    assert redaction and all(item.active for item in redaction)
    assert evidence.context_binding is not None
    assert all(
        decision.binding_key.subject == "PAY"
        for decision in evidence.context_binding.decisions
    )


def test_reported_history_cannot_supersede_current_explicit_request() -> None:
    evidence = IntentEvidenceExtractor.extract(
        TaskView(
            task(
                "결제해줘.",
                [
                    {
                        "turn": 1,
                        "summary": "이전 요청에서 결제하지 말라고 말했다.",
                    }
                ],
            )
        )
    )
    current_payment = evidence.current(EvidenceKind.EXPLICIT_DOMAIN_VERB)
    assert current_payment
    assert all(item.active for item in current_payment)


def test_language_rule_registry_is_typed_and_evidence_only() -> None:
    validate_language_rule_registry()
    required_fields = {
        "rule_id",
        "requires",
        "forbids",
        "scope",
        "semantic_slot",
        "emits",
        "priority",
        "contract_status",
    }
    for rule in LANGUAGE_RULE_REGISTRY.rules:
        assert required_fields <= set(rule.__dataclass_fields__)
        assert rule.contract_status in {
            ContractStatus.CONFIRMED_CONTRACT,
            ContractStatus.SUPPORTED_INTERPRETATION,
            ContractStatus.UNRESOLVED_ASSUMPTION,
        }

    proposals = LANGUAGE_RULE_REGISTRY.propose(
        SurfaceParser.parse("조명을 켜줘"),
        direct=True,
    )
    assert proposals
    assert all(isinstance(item, RuleEvidenceProposal) for item in proposals)

    source = inspect.getsource(LanguageRuleRegistry)
    for prohibited in (
        "FinalDecision",
        "CandidateEvaluation",
        "PlanCompiler",
        "ScopeCompiler",
        "PolicyCompiler",
    ):
        assert prohibited not in source
    assert "priority" in inspect.getsource(LanguageRuleRegistry._dedupe)


def test_evidence_module_has_no_embedded_lexical_rule_table() -> None:
    evidence_source = (PROJECT_ROOT / "core" / "evidence.py").read_text(
        encoding="utf-8"
    )
    assert "re.compile" not in evidence_source
    assert "final_dev_" not in evidence_source
    assert "final_screening_" not in evidence_source
    assert not any("\uac00" <= char <= "\ud7a3" for char in evidence_source)


def test_no_new_slm_or_model_dependency_was_added() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            PROJECT_ROOT / "core" / "surface_parser.py",
            PROJECT_ROOT / "core" / "language_registry.py",
            PROJECT_ROOT / "core" / "context_binder.py",
        )
    )
    for prohibited in ("transformers", "torch", "openai", "requests", "httpx"):
        assert prohibited not in source
