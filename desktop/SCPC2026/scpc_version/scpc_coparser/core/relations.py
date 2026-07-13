from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .ontology import FactStatus, RecordType
from .records import MarkerRefsValue, Provenance, stable_value


REFERENCE_TOKEN = r"(?:WM-\d+|marker_[a-z]+)"
REFERENCE_RE = re.compile(REFERENCE_TOKEN)
DIRECT_SELECTION_PATTERNS = (
    re.compile(rf"기준 참조는\s*({REFERENCE_TOKEN})"),
    re.compile(rf"참조 코드는\s*({REFERENCE_TOKEN})"),
    re.compile(rf"최종 승인 후보\s*({REFERENCE_TOKEN})"),
    re.compile(rf"승인 표시가 남은 것은\s*({REFERENCE_TOKEN})"),
    re.compile(rf"실제 처리할 ref는\s*({REFERENCE_TOKEN})"),
    re.compile(rf"({REFERENCE_TOKEN})만 통과 항목"),
    re.compile(rf"유지된 참조는\s*({REFERENCE_TOKEN})"),
    re.compile(rf"binding은\s*({REFERENCE_TOKEN})"),
    re.compile(rf"({REFERENCE_TOKEN})(?:을|를) 현재 턴의 참조로 지정"),
)


@dataclass(frozen=True)
class RelationFact:
    relation_id: str
    subject: str
    predicate: str
    object: str
    confidence: str
    provenance: Provenance
    status: FactStatus = FactStatus.PRESENT
    derived_from: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReferenceBinding:
    selected: str
    excluded: tuple[str, ...]
    reason: str
    confidence: str
    provenance: Provenance


@dataclass(frozen=True)
class FocalResolution:
    focal_id: str
    method: str
    confidence: str
    resolution_status: str
    selected_reference: str
    candidate_ids: tuple[str, ...]
    integrity_checks: tuple[str, ...]
    derived_from: tuple[str, ...]

    def to_trace(self) -> dict[str, Any]:
        return {
            "focal_id": self.focal_id,
            "source": self.method,
            "method": self.method,
            "confidence": self.confidence,
            "resolution_status": self.resolution_status,
            "selected_reference": self.selected_reference,
            "candidates": list(self.candidate_ids),
            "integrity_checks": list(self.integrity_checks),
            "derived_from": list(self.derived_from),
            "reasons": [f"selected_by:{self.method}"] if self.focal_id else ["unresolved_focal"],
        }


class ReferenceBindingParser:
    @staticmethod
    def parse(summary: str, *, source_id: str, session_id: str, turn: int | None) -> ReferenceBinding | None:
        for pattern in DIRECT_SELECTION_PATTERNS:
            match = pattern.search(summary)
            if match:
                selected = match.group(1)
                tokens = REFERENCE_RE.findall(summary)
                return ReferenceBinding(
                    selected=selected,
                    excluded=tuple(token for token in tokens if token != selected),
                    reason="explicit_selection",
                    confidence="high",
                    provenance=Provenance(
                        source_kind="visible_history",
                        source_id=source_id,
                        session_id=session_id,
                        turn=turn,
                        span=match.span(1),
                        assertion_mode="reported",
                    ),
                )

        tokens = REFERENCE_RE.findall(summary)
        if len(tokens) >= 2 and any(
            phrase in summary for phrase in ("두 번째", "둘째", "가운데 항목")
        ):
            return ReferenceBinding(
                selected=tokens[1],
                excluded=tuple(token for index, token in enumerate(tokens) if index != 1),
                reason="ordinal_second_selection",
                confidence="high",
                provenance=Provenance(
                    source_kind="visible_history",
                    source_id=source_id,
                    session_id=session_id,
                    turn=turn,
                    assertion_mode="reported",
                ),
            )
        return None


class RelationGraph:
    """Whitelisted task relations; shared titles/owners never create edges."""

    ENDPOINT_KEYS = {
        "message": ("recipient", "thread_id"),
        "calendar_event": ("attendee",),
        "iot_routine": ("target",),
        "payment_request": ("merchant",),
        "device_setting": ("name",),
    }

    def __init__(self, view: Any) -> None:
        self.view = view
        self.edges: list[RelationFact] = []
        self.bindings: list[ReferenceBinding] = []
        self._build()

    def _build(self) -> None:
        for obj in self.view.objects:
            object_id = str(obj.get("id") or "")
            object_type = str(obj.get("type") or "")
            attrs = obj.get("attrs") or {}
            ref_code = str(attrs.get("ref_code") or "")
            if ref_code:
                self.edges.append(
                    RelationFact(
                        relation_id=f"relation:object_ref:{object_id}",
                        subject=object_id,
                        predicate="has_ref_code",
                        object=ref_code,
                        confidence="high",
                        provenance=Provenance("object", object_id, self.view.session_id),
                    )
                )
            for key in self.ENDPOINT_KEYS.get(object_type, ()):
                if attrs.get(key):
                    self.edges.append(
                        RelationFact(
                            relation_id=f"relation:{object_id}:{key}",
                            subject=object_id,
                            predicate=f"has_{key}",
                            object=str(attrs[key]),
                            confidence="medium",
                            provenance=Provenance("object", object_id, self.view.session_id),
                        )
                    )

        history = sorted(
            self.view.history,
            key=lambda item: (self._turn(item), stable_value(item)),
        )
        for index, item in enumerate(history):
            summary = str(item.get("summary", item) or "")
            binding = ReferenceBindingParser.parse(
                summary,
                source_id=f"{self.view.task_id}:history:{index}",
                session_id=self.view.session_id,
                turn=self._turn(item),
            )
            if binding:
                self.bindings.append(binding)

    def resolve_focal(self) -> FocalResolution:
        marker_refs = self.view.marker_refs()
        trace = self.view.focal_resolution_trace()
        if marker_refs is not None and trace is not None:
            phase = trace.resolved_phase(
                self.view.record_code(RecordType.ROUTE_BINDING_ORDER)
            )
            marker = trace.marker_for(phase)
            ref_code = marker_refs.reference_for(marker)
            ref_conflict = ref_code in self.view.conflicting_ref_codes()
            obj = (
                None
                if ref_conflict
                else self.view.objects_by_ref_code().get(ref_code)
            )
            if obj and self.view.object_binding_is_ambiguous(
                str(obj.get("id") or "")
            ):
                obj = None
                ref_conflict = True
            checks = [
                "trace_dict_valid",
                "phase_resolved" if phase else "phase_missing",
                "marker_resolved" if marker else "marker_missing",
                "ref_conflict"
                if ref_conflict
                else "ref_unique"
                if obj
                else "ref_unresolved",
            ]
            if obj:
                return FocalResolution(
                    focal_id=str(obj.get("id") or ""),
                    method="marker_trace",
                    confidence="high",
                    resolution_status="resolved",
                    selected_reference=ref_code,
                    candidate_ids=(str(obj.get("id") or ""),),
                    integrity_checks=tuple(checks),
                    derived_from=("record:focal_resolution_trace", "record:focal_marker_refs"),
                )

        if self.bindings:
            # Selection facts are sorted by explicit turn and stable text. If
            # equally recent facts disagree, surface a conflict instead of
            # silently using input array order.
            max_turn = max(binding.provenance.turn if binding.provenance.turn is not None else -1 for binding in self.bindings)
            latest = [
                binding for binding in self.bindings
                if (binding.provenance.turn if binding.provenance.turn is not None else -1) == max_turn
            ]
            selected = {binding.selected for binding in latest}
            if len(selected) == 1:
                token = next(iter(selected))
                ref_code = self._marker_to_ref(token, marker_refs)
                obj = (
                    None
                    if ref_code in self.view.conflicting_ref_codes()
                    else self.view.objects_by_ref_code().get(ref_code)
                )
                if obj and self.view.object_binding_is_ambiguous(
                    str(obj.get("id") or "")
                ):
                    obj = None
                if obj:
                    excluded = {item for binding in latest for item in binding.excluded}
                    return FocalResolution(
                        focal_id=str(obj.get("id") or ""),
                        method="history_binding",
                        confidence="high",
                        resolution_status="resolved",
                        selected_reference=ref_code,
                        candidate_ids=(str(obj.get("id") or ""),),
                        integrity_checks=(
                            "unique_selected_token",
                            "selected_ref_exists",
                            "selected_not_excluded" if token not in excluded else "selection_conflict",
                        ),
                        derived_from=tuple(binding.provenance.source_id for binding in latest),
                    )

        return FocalResolution(
            focal_id="",
            method="unresolved",
            confidence="none",
            resolution_status="unresolved",
            selected_reference="",
            candidate_ids=(),
            integrity_checks=("no_unique_structural_binding",),
            derived_from=(),
        )

    @staticmethod
    def _marker_to_ref(token: str, marker_refs: MarkerRefsValue | None) -> str:
        if token.startswith("WM-"):
            return token
        return marker_refs.reference_for(token) if marker_refs is not None else ""

    @staticmethod
    def _turn(item: dict[str, Any]) -> int:
        try:
            return int(item.get("turn", -1))
        except (TypeError, ValueError):
            return -1

    def to_trace(self) -> dict[str, Any]:
        return {
            "edge_count": len(self.edges),
            "binding_count": len(self.bindings),
            "bindings": [
                {
                    "selected": binding.selected,
                    "excluded": list(binding.excluded),
                    "reason": binding.reason,
                    "turn": binding.provenance.turn,
                }
                for binding in self.bindings
            ],
        }
