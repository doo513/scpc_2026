from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.relations import RelationGraph
from core.task_view import TaskView


@dataclass(frozen=True)
class FocalDecision:
    focal_id: str
    source: str
    confidence: str
    candidates: tuple[str, ...]
    reasons: tuple[str, ...]
    resolution_status: str = "resolved"
    selected_reference: str = ""
    integrity_checks: tuple[str, ...] = ()
    derived_from: tuple[str, ...] = ()

    def to_trace(self) -> dict[str, Any]:
        return {
            "focal_id": self.focal_id,
            "source": self.source,
            "confidence": self.confidence,
            "candidates": list(self.candidates),
            "reasons": list(self.reasons),
            "resolution_status": self.resolution_status,
            "selected_reference": self.selected_reference,
            "integrity_checks": list(self.integrity_checks),
            "derived_from": list(self.derived_from),
        }


class FocalResolver:
    @staticmethod
    def resolve(view: TaskView, evidence: Any, session: dict[str, Any]) -> str:
        return FocalResolver.resolve_decision(view, evidence, session).focal_id

    @staticmethod
    def resolve_decision(
        view: TaskView,
        evidence: Any,
        session: dict[str, Any],
        *,
        relation_graph: RelationGraph | None = None,
    ) -> FocalDecision:
        if not view.objects:
            return FocalDecision("", "empty", "none", (), ("no_objects",))

        relation_resolution = (relation_graph or RelationGraph(view)).resolve_focal()
        if relation_resolution.focal_id:
            return FocalDecision(
                relation_resolution.focal_id,
                relation_resolution.method,
                relation_resolution.confidence,
                relation_resolution.candidate_ids,
                (f"selected_by:{relation_resolution.method}",),
                relation_resolution.resolution_status,
                relation_resolution.selected_reference,
                relation_resolution.integrity_checks,
                relation_resolution.derived_from,
            )

        steps = (
            ("direct_record", "high", FocalResolver._from_direct_record_value),
        )
        for source, confidence, resolver in steps:
            obj = resolver(view)
            if obj:
                focal_id = str(obj.get("id") or "")
                return FocalDecision(
                    focal_id,
                    source,
                    confidence,
                    (focal_id,),
                    (f"selected_by:{source}",),
                )

        return FocalDecision(
            "",
            "unresolved",
            "none",
            (),
            ("no_focal_candidate",),
            "unresolved",
            "",
            ("no_unique_structural_or_semantic_candidate",),
        )

    @staticmethod
    def _from_direct_record_value(view: TaskView) -> dict[str, Any] | None:
        candidates: dict[str, dict[str, Any]] = {}
        for fact in view.typed_records:
            for value in fact.object_references:
                if (
                    value in view.conflicting_object_ids()
                    or value in view.conflicting_ref_codes()
                ):
                    continue
                obj = view.objects_by_id().get(value) or view.objects_by_ref_code().get(value)
                if obj and obj.get("id"):
                    candidates[str(obj["id"])] = obj
        if len(candidates) == 1:
            return next(iter(candidates.values()))
        return None
