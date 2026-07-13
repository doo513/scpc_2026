from __future__ import annotations

import copy
from typing import Any

from core.decision import DecisionEngine
from core.session_state import MemoryStore, extract_memory_payload, update_session_state
from core.state import StateAssembler
from core.task_view import TaskView
from rules.plan import PlanCompiler
from rules.response import ResponseBuilder
from rules.scope_policy import PolicyCompiler, ScopeCompiler


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
        content_scope = ScopeCompiler.compile(final_decision)
        policy = PolicyCompiler.compile(final_decision)
        plan_events = PlanCompiler.compile(final_decision)
        user_response, audit_tags, counterfactual = ResponseBuilder.build(
            final_decision,
            content_scope,
            policy,
        )

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
            "_trace": {
                "task_id": view.task_id,
                "state": state.to_trace(),
                "focal": state.focal_decision.to_trace(),
                "final_decision": final_decision.to_trace(),
                "evidence": state.evidence.to_trace(),
                "records": view.record_index.to_trace(),
                "relations": state.relation_graph.to_trace(),
                "decision_matrix": decision_matrix.to_trace(),
                "scope_mode": content_scope["mode"],
            },
        }
        if commit:
            self._commit_memory(view, final_decision, plan_events)
            update_session_state(session, answer)
            if state.focal:
                session["last_focal_id"] = final_decision.focal_id
                session["last_focal_snapshot"] = copy.deepcopy(state.focal)
                session["last_focal_source_task"] = view.task_id
                session["last_focal_source_turn"] = view.turn_index
        return answer

    def _commit_memory(
        self,
        view: TaskView,
        decision: Any,
        plan_events: list[dict[str, Any]],
    ) -> None:
        if decision.control not in {"proceed", "amend"}:
            return
        if decision.action.value != "memory_update":
            return
        if not any(event.get("verb") == "update" for event in plan_events):
            return
        for value in view.memory_write_values():
            payload = value.as_payload()
            if payload:
                self.memory_store.write(
                    payload,
                    task_id=view.task_id,
                    session_id=view.session_id,
                    turn_index=view.turn_index,
                )
            elif value.alias:
                self.memory_store.write(
                    extract_memory_payload(view.prompt, value.alias),
                    task_id=view.task_id,
                    session_id=view.session_id,
                    turn_index=view.turn_index,
                )
