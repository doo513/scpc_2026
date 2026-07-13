from __future__ import annotations

import copy
from typing import Any

from core.consistency import ConsistencyValidator
from core.decision import DecisionEngine
from core.production_projection import ProductionProjectionPipeline
from core.session_state import (
    AtomicSessionCommitter,
    MemoryStore,
    update_session_state,
)
from core.state import StateAssembler
from core.task_view import TaskView
from rules.response import ResponseBuilder


class FinalHarness:
    """Deterministic SCPC answer engine with no filesystem side effects."""

    def __init__(self) -> None:
        self.memory_store = MemoryStore()

    def prepare(self, tasks: list[dict[str, Any]] | None = None) -> None:
        # The task list is intentionally ignored: a harness may not preview the
        # screening stream before normal session/turn execution.
        self.memory_store.clear()

    def answer_task(
        self,
        task: dict[str, Any],
        session: dict[str, Any],
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        view = TaskView(task, session)

        state = StateAssembler.assemble(view, self.memory_store, session)
        decision_matrix, final_decision = DecisionEngine.decide(state)
        projection = ProductionProjectionPipeline.compile(final_decision)
        content_scope = projection.fields["content_scope"]
        policy = projection.fields["policy"]
        plan_events = projection.fields["plan_events"]
        user_response, audit_tags, counterfactual = ResponseBuilder.build(
            final_decision,
            content_scope,
            policy,
        )

        trace = {
            "task_id": view.task_id,
            "state": state.to_trace(),
            "focal": state.focal_decision.to_trace(),
            "final_decision": final_decision.to_trace(),
            "evidence": state.evidence.to_trace(),
            "records": view.record_index.to_trace(),
            "relations": state.relation_graph.to_trace(),
            "decision_matrix": decision_matrix.to_trace(),
            "scope_mode": content_scope["mode"],
            "projection_lock": {
                "decision_id": projection.decision_id,
                "bundle_id": projection.bundle_id,
                "lock_digest": projection.lock_digest,
                "compiler": "core.projection_compilers.ProjectionCompiler",
            },
            "commit": {
                "validation_status": "pending",
                "status": "not_requested" if not commit else "pending",
            },
        }
        answer = {
            "focal_id": final_decision.focal_id,
            "target": final_decision.target,
            "control": final_decision.control,
            "content_scope": content_scope,
            "policy": policy,
            "plan_events": plan_events,
            "user_response": user_response,
            "audit_tags": audit_tags,
            "counterfactual": counterfactual,
            "_trace": trace,
        }
        public_answer = {
            key: value for key, value in answer.items() if not key.startswith("_")
        }
        ConsistencyValidator.validate_strict(
            public_answer,
            view,
            trace,
            final_decision,
        )
        trace["commit"]["validation_status"] = "passed"
        if commit:
            staged_session = copy.deepcopy(session)
            staged_memory = self.memory_store.clone()
            self._commit_memory(
                view,
                final_decision,
                plan_events,
                memory_store=staged_memory,
            )
            update_session_state(staged_session, public_answer)
            if state.focal:
                staged_session["last_focal_id"] = final_decision.focal_id
                staged_session["last_focal_snapshot"] = copy.deepcopy(state.focal)
                staged_session["last_focal_source_task"] = view.task_id
                staged_session["last_focal_source_turn"] = view.turn_index
            AtomicSessionCommitter.commit(
                session,
                self.memory_store,
                staged_session=staged_session,
                staged_memory=staged_memory,
            )
            trace["commit"]["status"] = "committed"
        return answer

    def _commit_memory(
        self,
        view: TaskView,
        decision: Any,
        plan_events: list[dict[str, Any]],
        *,
        memory_store: MemoryStore | None = None,
    ) -> None:
        memory_store = memory_store or self.memory_store
        if decision.control not in {"proceed", "amend"}:
            return
        if decision.action.value != "memory_update":
            return
        if not any(event.get("verb") == "update" for event in plan_events):
            return
        for value in view.memory_write_values():
            payload = value.as_payload()
            if payload:
                memory_store.write(
                    payload,
                    task_id=view.task_id,
                    session_id=view.session_id,
                    turn_index=view.turn_index,
                )
