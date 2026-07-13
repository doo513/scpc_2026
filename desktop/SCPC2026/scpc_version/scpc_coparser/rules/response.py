from __future__ import annotations

from typing import Any

from core.decision import DomainAction, FinalDecision


class ResponseBuilder:
    @staticmethod
    def build(
        decision: FinalDecision,
        scope: dict[str, Any],
        policy: dict[str, Any],
    ) -> tuple[str, list[str], str]:
        control = decision.control
        target = decision.target
        mode = str(scope.get("mode") or "none")

        if control == "hold":
            response = "최신 안전 또는 허용 조건을 충족하지 않아 요청을 진행하지 않습니다."
            counterfactual = "차단 원인이 해소되고 최신 허용 근거가 확인되면 판단이 달라질 수 있습니다."
        elif control == "ask":
            response = "대상이나 허용 범위를 먼저 확인해야 합니다."
            counterfactual = "대상과 처리 범위가 명확해지면 요청을 다시 판단할 수 있습니다."
        elif (
            decision.action
            in {DomainAction.PAY, DomainAction.TOGGLE, DomainAction.SCHEDULE}
            and decision.operation_mode == "execute"
        ):
            response = f"확인된 조건에 따라 {target}에 대한 도메인 동작을 수행합니다."
            counterfactual = "필수 정보, 실행 capability 또는 안전 조건이 바뀌면 계획도 달라질 수 있습니다."
        elif mode == "status_only":
            response = "외부 전송 없이 기기 내부 상태만 갱신합니다."
            counterfactual = "외부 전송이 다시 요청되면 수신처와 공유 정책을 별도로 확인해야 합니다."
        elif control == "amend":
            response = f"민감한 범위를 제외한 {mode} 형태로 {target}에 처리합니다."
            counterfactual = "민감 정보의 명시적 공유 허용이 확인되면 범위가 달라질 수 있습니다."
        else:
            response = f"확인된 {mode} 범위로 {target}에 처리합니다."
            counterfactual = "대상, 동의 또는 공유 범위가 바뀌면 처리 계획도 달라질 수 있습니다."

        category = (
            "hard_block"
            if control == "hold"
            else "clarification_required"
            if control == "ask"
            else "minimal_disclosure"
            if control == "amend"
            else "local_status_update"
            if decision.action
            in {DomainAction.LOCAL_UPDATE, DomainAction.MEMORY_UPDATE}
            else "domain_execution"
            if decision.action
            in {DomainAction.PAY, DomainAction.TOGGLE, DomainAction.SCHEDULE}
            else "dispatch"
        )
        tags = [category, decision.reason_code]
        tags.extend(str(flag) for flag in policy.get("risk_flags", [])[:3])
        audit_tags = list(dict.fromkeys(tag for tag in tags if tag))
        return response, audit_tags, counterfactual
