from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Iterable

from .prompt_document import ClauseSpan, PromptDocument, normalize_text


class SurfacePredicate(str, Enum):
    ENABLE = "enable"
    DISABLE = "disable"
    ENABLE_STATE = "enable_state"
    DISABLE_STATE = "disable_state"
    PAY = "pay"
    SCHEDULE = "schedule"
    SHARE = "share"
    STORE = "store"
    DELETE = "delete"
    CANCEL = "cancel"
    VERIFY = "verify"
    CLARIFY = "clarify"


class PredicateMood(str, Enum):
    COMMAND = "command"
    INTERROGATIVE = "interrogative"
    CONDITIONAL = "conditional"
    DECLARATIVE = "declarative"


class PredicatePolarity(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class ArgumentRole(str, Enum):
    DESIRED_STATE = "desired_state"
    AMOUNT = "amount"
    RECIPIENT = "recipient"
    REFERENCE = "reference"


class ReferenceKind(str, Enum):
    OBJECT_REF = "object_ref"
    MARKER = "marker"
    ANAPHORA = "anaphora"


@dataclass(frozen=True)
class QuotationSpan:
    quotation_id: str
    text: str
    span: tuple[int, int]
    kind: str


@dataclass(frozen=True)
class NegationSpan:
    negation_id: str
    text: str
    span: tuple[int, int]
    predicate_frame_id: str


@dataclass(frozen=True)
class PredicateFrame:
    frame_id: str
    predicate: SurfacePredicate
    mood: PredicateMood
    polarity: PredicatePolarity
    text: str
    span: tuple[int, int]
    clause_id: str
    quoted: bool
    semantic_slot: str = "operation"


@dataclass(frozen=True)
class ArgumentSpan:
    argument_id: str
    role: ArgumentRole
    text: str
    span: tuple[int, int]
    clause_id: str
    predicate_frame_id: str
    quoted: bool


@dataclass(frozen=True)
class CorrectionRelation:
    relation_id: str
    prior_frame_id: str
    replacement_frame_id: str
    semantic_slot: str
    connector: str
    span: tuple[int, int]


@dataclass(frozen=True)
class SupersessionRelation:
    relation_id: str
    superseded_frame_id: str
    superseding_frame_id: str
    semantic_slot: str
    source_relation_id: str


@dataclass(frozen=True)
class FallbackConditionRelation:
    relation_id: str
    source_frame_id: str
    fallback_frame_id: str
    connector: str
    span: tuple[int, int]


@dataclass(frozen=True)
class ReferenceMention:
    mention_id: str
    kind: ReferenceKind
    text: str
    span: tuple[int, int]
    clause_id: str
    quoted: bool


@dataclass(frozen=True)
class PredicateLexeme:
    lexeme_id: str
    predicate: SurfacePredicate
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class SurfaceParse:
    document: PromptDocument
    clauses: tuple[ClauseSpan, ...]
    quotations: tuple[QuotationSpan, ...]
    negations: tuple[NegationSpan, ...]
    predicate_frames: tuple[PredicateFrame, ...]
    arguments: tuple[ArgumentSpan, ...]
    corrections: tuple[CorrectionRelation, ...]
    supersessions: tuple[SupersessionRelation, ...]
    fallback_relations: tuple[FallbackConditionRelation, ...]
    references: tuple[ReferenceMention, ...]

    def active_frames(self) -> tuple[PredicateFrame, ...]:
        return tuple(frame for frame in self.predicate_frames if not frame.quoted)

    def to_trace(self) -> dict[str, Any]:
        return {
            "quotations": [
                {
                    "id": item.quotation_id,
                    "span": list(item.span),
                    "kind": item.kind,
                }
                for item in self.quotations
            ],
            "negations": [
                {
                    "id": item.negation_id,
                    "span": list(item.span),
                    "predicate_frame_id": item.predicate_frame_id,
                }
                for item in self.negations
            ],
            "predicate_frames": [
                {
                    "id": item.frame_id,
                    "predicate": item.predicate.value,
                    "mood": item.mood.value,
                    "polarity": item.polarity.value,
                    "span": list(item.span),
                    "clause_id": item.clause_id,
                    "quoted": item.quoted,
                    "semantic_slot": item.semantic_slot,
                }
                for item in self.predicate_frames
            ],
            "arguments": [
                {
                    "id": item.argument_id,
                    "role": item.role.value,
                    "span": list(item.span),
                    "predicate_frame_id": item.predicate_frame_id,
                    "quoted": item.quoted,
                }
                for item in self.arguments
            ],
            "corrections": [
                {
                    "id": item.relation_id,
                    "prior_frame_id": item.prior_frame_id,
                    "replacement_frame_id": item.replacement_frame_id,
                    "semantic_slot": item.semantic_slot,
                    "connector": item.connector,
                    "span": list(item.span),
                }
                for item in self.corrections
            ],
            "supersessions": [
                {
                    "id": item.relation_id,
                    "superseded_frame_id": item.superseded_frame_id,
                    "superseding_frame_id": item.superseding_frame_id,
                    "semantic_slot": item.semantic_slot,
                    "source_relation_id": item.source_relation_id,
                }
                for item in self.supersessions
            ],
            "fallback_relations": [
                {
                    "id": item.relation_id,
                    "source_frame_id": item.source_frame_id,
                    "fallback_frame_id": item.fallback_frame_id,
                    "connector": item.connector,
                    "span": list(item.span),
                }
                for item in self.fallback_relations
            ],
            "references": [
                {
                    "id": item.mention_id,
                    "kind": item.kind.value,
                    "span": list(item.span),
                    "clause_id": item.clause_id,
                    "quoted": item.quoted,
                }
                for item in self.references
            ],
        }


PREDICATE_LEXICON = (
    PredicateLexeme(
        "predicate:enable",
        SurfacePredicate.ENABLE,
        re.compile(r"켜(?:줘|주세요|라|고|야|도록|지|지는|짐|기)?"),
    ),
    PredicateLexeme(
        "predicate:disable",
        SurfacePredicate.DISABLE,
        re.compile(r"(?:끄|꺼)(?:줘|주세요|라|고|야|도록|지|지는|짐|기)?"),
    ),
    PredicateLexeme(
        "predicate:pay", SurfacePredicate.PAY, re.compile(r"(?:결제|지불|구매)")
    ),
    PredicateLexeme(
        "predicate:schedule",
        SurfacePredicate.SCHEDULE,
        re.compile(r"(?:일정|캘린더|예약|등록|추가)"),
    ),
    PredicateLexeme(
        "predicate:share",
        SurfacePredicate.SHARE,
        re.compile(r"(?:공유|보내|전달|올려)"),
    ),
    PredicateLexeme(
        "predicate:store", SurfacePredicate.STORE, re.compile(r"(?:저장|기억|기록)")
    ),
    PredicateLexeme(
        "predicate:delete", SurfacePredicate.DELETE, re.compile(r"(?:삭제|지워)")
    ),
    PredicateLexeme(
        "predicate:cancel",
        SurfacePredicate.CANCEL,
        re.compile(r"(?:취소|철회|되돌|중지)"),
    ),
    PredicateLexeme(
        "predicate:verify",
        SurfacePredicate.VERIFY,
        re.compile(r"(?:확인|검토|점검|검증)"),
    ),
    PredicateLexeme(
        "predicate:clarify",
        SurfacePredicate.CLARIFY,
        re.compile(r"(?:질문|물어|명확히)"),
    ),
)

NEGATION_RE = re.compile(
    r"(?:지\s*(?:말(?:고|라|아)?|마|않(?:고|아|는)?|못)|하면\s*안|"
    r"하지\s*(?:말|마|않|못|안)|말고|아니라)"
)
COMMAND_RE = re.compile(
    r"(?:해\s*(?:줘|주세요|라)|하라|하세요|십시오|켜줘|꺼줘|바꿔|남겨|올려|"
    r"잡아줘|등록해줘|추가해줘|예약해줘)"
)
INTERROGATIVE_RE = re.compile(r"(?:는지|인지|맞는지|상태|확인|검증|점검|\?)")
CONDITIONAL_RE = re.compile(r"(?:할\s*수\s*없으면|안\s*되면|불가능하면|실패하면|면\b)")
CORRECTION_RE = re.compile(r"(?:말고|아니라|대신|정정(?:하면|해서|하자면)?)")
FALLBACK_RE = re.compile(r"(?:할\s*수\s*없으면|안\s*되면|불가능하면|실패하면)")
REFERENCE_PATTERNS = (
    (ReferenceKind.OBJECT_REF, re.compile(r"WM-\d+")),
    (ReferenceKind.MARKER, re.compile(r"marker_[a-z]+")),
    (
        ReferenceKind.ANAPHORA,
        re.compile(r"(?:그거|그것|그곳|방금\s*지운\s*것|같은\s*(?:곳|대상|수신처))"),
    ),
)


class SurfaceParser:
    @classmethod
    def parse(cls, text: Any) -> SurfaceParse:
        normalized = normalize_text(text)
        document = PromptDocument.parse(normalized)
        quotations = cls._quotations(document)
        frames: list[PredicateFrame] = []
        negations: list[NegationSpan] = []
        arguments: list[ArgumentSpan] = []
        references: list[ReferenceMention] = []

        for clause in document.clauses:
            clause_frames, clause_negations, clause_arguments = cls._frames_for_segment(
                clause.directive_text,
                base_offset=clause.span[0],
                clause_id=clause.clause_id,
                quoted=False,
            )
            frames.extend(clause_frames)
            negations.extend(clause_negations)
            arguments.extend(clause_arguments)
            references.extend(
                cls._references_for_segment(
                    clause.directive_text,
                    base_offset=clause.span[0],
                    clause_id=clause.clause_id,
                    quoted=False,
                )
            )

        for quotation in quotations:
            inner_text, inner_offset = cls._quotation_content(quotation)
            quoted_frames, quoted_negations, quoted_arguments = cls._frames_for_segment(
                inner_text,
                base_offset=inner_offset,
                clause_id=cls._clause_id_for_span(document.clauses, quotation.span),
                quoted=True,
            )
            frames.extend(quoted_frames)
            negations.extend(quoted_negations)
            arguments.extend(quoted_arguments)
            references.extend(
                cls._references_for_segment(
                    inner_text,
                    base_offset=inner_offset,
                    clause_id=cls._clause_id_for_span(document.clauses, quotation.span),
                    quoted=True,
                )
            )

        frames = sorted(
            frames, key=lambda item: (item.span, item.predicate.value, item.quoted)
        )
        negations = sorted(
            negations, key=lambda item: (item.span, item.predicate_frame_id)
        )
        arguments = sorted(arguments, key=lambda item: (item.span, item.role.value))
        references = sorted(references, key=lambda item: (item.span, item.kind.value))
        corrections, supersessions = cls._correction_relations(document, frames)
        fallback_relations = cls._fallback_relations(document, frames)
        return SurfaceParse(
            document=document,
            clauses=document.clauses,
            quotations=quotations,
            negations=tuple(negations),
            predicate_frames=tuple(frames),
            arguments=tuple(arguments),
            corrections=corrections,
            supersessions=supersessions,
            fallback_relations=fallback_relations,
            references=tuple(references),
        )

    @classmethod
    def _frames_for_segment(
        cls,
        text: str,
        *,
        base_offset: int,
        clause_id: str,
        quoted: bool,
    ) -> tuple[list[PredicateFrame], list[NegationSpan], list[ArgumentSpan]]:
        frames: list[PredicateFrame] = []
        negations: list[NegationSpan] = []
        arguments: list[ArgumentSpan] = []
        frame_index = 0
        for lexeme in PREDICATE_LEXICON:
            for match in lexeme.pattern.finditer(text):
                predicate = lexeme.predicate
                local_window = text[match.start() : min(len(text), match.end() + 24)]
                negation_match = NEGATION_RE.search(local_window)
                polarity = (
                    PredicatePolarity.NEGATIVE
                    if negation_match is not None
                    else PredicatePolarity.POSITIVE
                )
                mood = cls._mood(text, match.span(), predicate)
                if (
                    predicate == SurfacePredicate.ENABLE
                    and mood == PredicateMood.INTERROGATIVE
                ):
                    predicate = SurfacePredicate.ENABLE_STATE
                elif (
                    predicate == SurfacePredicate.DISABLE
                    and mood == PredicateMood.INTERROGATIVE
                ):
                    predicate = SurfacePredicate.DISABLE_STATE
                span = (base_offset + match.start(), base_offset + match.end())
                frame_id = (
                    f"frame:{clause_id}:{span[0]}:{span[1]}:{predicate.value}:"
                    f"{'quoted' if quoted else 'direct'}:{frame_index}"
                )
                frame = PredicateFrame(
                    frame_id=frame_id,
                    predicate=predicate,
                    mood=mood,
                    polarity=polarity,
                    text=match.group(0),
                    span=span,
                    clause_id=clause_id,
                    quoted=quoted,
                )
                frames.append(frame)
                if negation_match is not None:
                    negation_span = (
                        base_offset + match.start() + negation_match.start(),
                        base_offset + match.start() + negation_match.end(),
                    )
                    negations.append(
                        NegationSpan(
                            negation_id=f"negation:{frame_id}",
                            text=negation_match.group(0),
                            span=negation_span,
                            predicate_frame_id=frame_id,
                        )
                    )
                desired_state = {
                    SurfacePredicate.ENABLE: "enabled",
                    SurfacePredicate.ENABLE_STATE: "enabled",
                    SurfacePredicate.DISABLE: "disabled",
                    SurfacePredicate.DISABLE_STATE: "disabled",
                }.get(predicate)
                if desired_state:
                    arguments.append(
                        ArgumentSpan(
                            argument_id=f"argument:{frame_id}:desired_state",
                            role=ArgumentRole.DESIRED_STATE,
                            text=desired_state,
                            span=span,
                            clause_id=clause_id,
                            predicate_frame_id=frame_id,
                            quoted=quoted,
                        )
                    )
                frame_index += 1
        return frames, negations, arguments

    @staticmethod
    def _mood(
        text: str,
        predicate_span: tuple[int, int],
        predicate: SurfacePredicate,
    ) -> PredicateMood:
        start, end = predicate_span
        tail = text[end : min(len(text), end + 24)]
        local = text[start : min(len(text), end + 32)]
        if CONDITIONAL_RE.search(local):
            return PredicateMood.CONDITIONAL
        if NEGATION_RE.search(local) and re.search(r"(?:말|마|않|못|안)", local):
            return PredicateMood.COMMAND
        if predicate in {SurfacePredicate.ENABLE, SurfacePredicate.DISABLE} and (
            re.search(r"(?:지는지|는지)", local)
            or re.search(r"(?:확인|검증|점검)", tail)
        ):
            return PredicateMood.INTERROGATIVE
        if predicate == SurfacePredicate.VERIFY or "?" in local:
            return PredicateMood.INTERROGATIVE
        if COMMAND_RE.search(local) or re.search(
            r"(?:해|하|켜|꺼|바꿔)(?:줘|주세요|라|세요|십시오)", local
        ):
            return PredicateMood.COMMAND
        return PredicateMood.DECLARATIVE

    @staticmethod
    def _quotations(document: PromptDocument) -> tuple[QuotationSpan, ...]:
        quote_kinds = {
            "double_quote",
            "single_quote",
            "curly_double_quote",
            "curly_single_quote",
            "corner_quote",
            "double_corner_quote",
        }
        return tuple(
            QuotationSpan(
                quotation_id=f"quotation:{index}",
                text=document.normalized_text[item.start : item.end],
                span=(item.start, item.end),
                kind=item.kind,
            )
            for index, item in enumerate(document.protected_spans)
            if item.kind in quote_kinds
        )

    @staticmethod
    def _quotation_content(quotation: QuotationSpan) -> tuple[str, int]:
        text = quotation.text
        if len(text) >= 2:
            return text[1:-1], quotation.span[0] + 1
        return text, quotation.span[0]

    @staticmethod
    def _clause_id_for_span(
        clauses: Iterable[ClauseSpan],
        span: tuple[int, int],
    ) -> str:
        for clause in clauses:
            if clause.span[0] <= span[0] and clause.span[1] >= span[1]:
                return clause.clause_id
        return "clause:quoted"

    @staticmethod
    def _references_for_segment(
        text: str,
        *,
        base_offset: int,
        clause_id: str,
        quoted: bool,
    ) -> list[ReferenceMention]:
        references: list[ReferenceMention] = []
        for kind, pattern in REFERENCE_PATTERNS:
            for match in pattern.finditer(text):
                span = (base_offset + match.start(), base_offset + match.end())
                references.append(
                    ReferenceMention(
                        mention_id=f"reference:{clause_id}:{span[0]}:{kind.value}",
                        kind=kind,
                        text=match.group(0),
                        span=span,
                        clause_id=clause_id,
                        quoted=quoted,
                    )
                )
        return references

    @classmethod
    def _correction_relations(
        cls,
        document: PromptDocument,
        frames: list[PredicateFrame],
    ) -> tuple[tuple[CorrectionRelation, ...], tuple[SupersessionRelation, ...]]:
        direct_frames = [frame for frame in frames if not frame.quoted]
        corrections: list[CorrectionRelation] = []
        for match in CORRECTION_RE.finditer(document.normalized_text):
            if FALLBACK_RE.fullmatch(match.group(0)):
                continue
            before = [
                frame for frame in direct_frames if frame.span[1] <= match.start()
            ]
            after = [frame for frame in direct_frames if frame.span[0] >= match.end()]
            if not before or not after:
                continue
            prior = max(before, key=lambda frame: frame.span)
            replacement = min(after, key=lambda frame: frame.span)
            if prior.semantic_slot != replacement.semantic_slot:
                continue
            relation_id = (
                f"correction:{match.start()}:{prior.frame_id}:{replacement.frame_id}"
            )
            corrections.append(
                CorrectionRelation(
                    relation_id=relation_id,
                    prior_frame_id=prior.frame_id,
                    replacement_frame_id=replacement.frame_id,
                    semantic_slot=prior.semantic_slot,
                    connector=match.group(0),
                    span=match.span(),
                )
            )
        supersessions = tuple(
            SupersessionRelation(
                relation_id=f"supersession:{index}",
                superseded_frame_id=relation.prior_frame_id,
                superseding_frame_id=relation.replacement_frame_id,
                semantic_slot=relation.semantic_slot,
                source_relation_id=relation.relation_id,
            )
            for index, relation in enumerate(corrections)
        )
        return tuple(corrections), supersessions

    @staticmethod
    def _fallback_relations(
        document: PromptDocument,
        frames: list[PredicateFrame],
    ) -> tuple[FallbackConditionRelation, ...]:
        direct_frames = [frame for frame in frames if not frame.quoted]
        relations: list[FallbackConditionRelation] = []
        for match in FALLBACK_RE.finditer(document.normalized_text):
            before = [
                frame for frame in direct_frames if frame.span[1] <= match.start()
            ]
            after = [frame for frame in direct_frames if frame.span[0] >= match.end()]
            if not before or not after:
                continue
            source = max(before, key=lambda frame: frame.span)
            fallback = min(after, key=lambda frame: frame.span)
            relations.append(
                FallbackConditionRelation(
                    relation_id=f"fallback:{match.start()}:{source.frame_id}:{fallback.frame_id}",
                    source_frame_id=source.frame_id,
                    fallback_frame_id=fallback.frame_id,
                    connector=match.group(0),
                    span=match.span(),
                )
            )
        return tuple(relations)
