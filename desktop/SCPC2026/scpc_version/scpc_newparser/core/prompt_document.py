from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
import unicodedata
from typing import Any, Iterable


class TextAuthority(str, Enum):
    DIRECT_USER = "direct_user"
    REPORTED_CONTEXT = "reported_context"
    QUOTED_CONTENT = "quoted_content"
    DATA_PAYLOAD = "data_payload"


class DiscourseRelation(str, Enum):
    CONTINUE = "continue"
    CONTRAST = "contrast"
    CORRECTION = "correction"
    EXCEPTION = "exception"


@dataclass(frozen=True)
class ProtectedSpan:
    start: int
    end: int
    kind: str


@dataclass(frozen=True)
class ClauseSpan:
    clause_id: str
    text: str
    directive_text: str
    span: tuple[int, int]
    relation: DiscourseRelation
    connector: str
    authority: TextAuthority
    protected_spans: tuple[ProtectedSpan, ...]


@dataclass(frozen=True)
class PromptDocument:
    raw_text: str
    normalized_text: str
    clauses: tuple[ClauseSpan, ...]
    protected_spans: tuple[ProtectedSpan, ...]
    latest_directive_span: tuple[int, int] | None

    @classmethod
    def parse(
        cls,
        text: Any,
        *,
        authority: TextAuthority = TextAuthority.DIRECT_USER,
    ) -> PromptDocument:
        raw = str(text or "")
        normalized = normalize_text(raw)
        protected = _protected_spans(normalized)
        latest_text, latest_span = latest_clause_from_text(normalized)
        del latest_text
        clauses: list[ClauseSpan] = []
        for index, (clause, start, end) in enumerate(clause_tuples(normalized)):
            local_spans = tuple(
                ProtectedSpan(
                    max(item.start, start) - start,
                    min(item.end, end) - start,
                    item.kind,
                )
                for item in protected
                if item.start < end and item.end > start
            )
            directive_text = mask_spans(clause, local_spans)
            connector = _leading_connector(clause)
            relation = _relation(connector, clause)
            clauses.append(
                ClauseSpan(
                    clause_id=f"clause:{index}",
                    text=clause,
                    directive_text=directive_text,
                    span=(start, end),
                    relation=relation,
                    connector=connector,
                    authority=authority,
                    protected_spans=local_spans,
                )
            )
        return cls(raw, normalized, tuple(clauses), protected, latest_span)

    def to_trace(self) -> dict[str, Any]:
        return {
            "protected_spans": [
                {"start": item.start, "end": item.end, "kind": item.kind}
                for item in self.protected_spans
            ],
            "clauses": [
                {
                    "id": clause.clause_id,
                    "span": list(clause.span),
                    "connector": clause.connector,
                    "relation": clause.relation.value,
                    "authority": clause.authority.value,
                }
                for clause in self.clauses
            ],
        }


CONNECTOR_RE = re.compile(
    r"(?:^|[.!?。！？]\s*|\n+)(?P<marker>단,|다만|하지만|그러나|대신)(?=\s|$)"
)
CLAUSE_RE = re.compile(r"[^.!?。！？\n]+(?:[.!?。！？]+|$)")
LEADING_CONNECTOR_RE = re.compile(r"^(단,|다만|하지만|그러나|대신)\s*")

PROTECTED_PATTERNS = (
    ("fenced_code", re.compile(r"```[\s\S]*?```")),
    ("inline_code", re.compile(r"`[^`\n]*`")),
    ("double_quote", re.compile(r'"(?:\\.|[^"\\])*"')),
    ("single_quote", re.compile(r"'(?:\\.|[^'\\])*'")),
    ("curly_double_quote", re.compile(r"“[^”]*”")),
    ("curly_single_quote", re.compile(r"‘[^’]*’")),
    ("corner_quote", re.compile(r"「[^」]*」")),
    ("double_corner_quote", re.compile(r"『[^』]*』")),
)


def normalize_text(text: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    return re.sub(r"\s+", " ", normalized).strip()


def canonical_text(text: str) -> str:
    normalized = normalize_text(text).lower()
    normalized = re.sub(r"[\s\u00b7,.;:!?]+", " ", normalized)
    return normalized.strip()


def latest_clause_from_text(text: str) -> tuple[str, tuple[int, int] | None]:
    normalized = normalize_text(text)
    matches = list(CONNECTOR_RE.finditer(normalized))
    if not matches:
        return "", None
    marker_start = matches[-1].start("marker")
    return normalized[marker_start:].strip(), (marker_start, len(normalized))


def clause_tuples(text: str) -> tuple[tuple[str, int, int], ...]:
    normalized = normalize_text(text)
    clauses: list[tuple[str, int, int]] = []
    for match in CLAUSE_RE.finditer(normalized):
        raw = match.group(0)
        stripped = raw.strip()
        if not stripped:
            continue
        leading = len(raw) - len(raw.lstrip())
        start = match.start() + leading
        clauses.append((stripped, start, start + len(stripped)))
    return tuple(clauses) or ((normalized, 0, len(normalized)),)


def mask_spans(text: str, spans: Iterable[ProtectedSpan]) -> str:
    chars = list(text)
    for span in spans:
        for index in range(max(0, span.start), min(len(chars), span.end)):
            chars[index] = " "
    return "".join(chars)


def _protected_spans(text: str) -> tuple[ProtectedSpan, ...]:
    rows: list[ProtectedSpan] = []
    occupied: list[tuple[int, int]] = []
    for kind, pattern in PROTECTED_PATTERNS:
        for match in pattern.finditer(text):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            rows.append(ProtectedSpan(match.start(), match.end(), kind))
            occupied.append(match.span())
    return tuple(sorted(rows, key=lambda item: (item.start, item.end, item.kind)))


def _leading_connector(text: str) -> str:
    match = LEADING_CONNECTOR_RE.match(text)
    return match.group(1) if match else ""


def _relation(connector: str, text: str) -> DiscourseRelation:
    if any(root in text for root in ("정정", "아니라", "말고", "대신")):
        return DiscourseRelation.CORRECTION
    if connector == "단,":
        return DiscourseRelation.EXCEPTION
    if connector:
        return DiscourseRelation.CONTRAST
    return DiscourseRelation.CONTINUE
