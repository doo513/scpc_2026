from __future__ import annotations

import re

from .prompt_document import clause_tuples, normalize_text


LOCAL_DESTINATION_RE = re.compile(
    r"(?:내부|로컬|기기\s*(?:안|내부)|내\s*기기|장치\s*(?:안|내부))[^.!?]{0,60}"
    r"(?:상태|기록|갱신|업데이트|완료|남기|정리)"
)
LOCAL_EXCLUSIVE_RE = re.compile(
    r"(?:상태|기록)[^.!?]{0,15}(?:만|한정)[^.!?]{0,20}(?:갱신|바꾸|남기|정리|업데이트)"
)
EXTERNAL_CANCEL_RE = re.compile(
    r"(?:외부\s*(?:공유|전송|전달)|바깥\s*(?:수신처|으로)|실제\s*보내기|보내는\s*작업|"
    r"수신처\s*전달|전달\s*(?:동작|단계)|공유\s*(?:작업|채널))"
    r"[^.!?]{0,60}(?:하지\s*말|하지\s*않|생략|접고|취소|대신|아니라|빼고)"
)

CONFIRMATION_ROOTS = ("확인", "질문", "물어", "clarification")
UNCERTAINTY_ROOTS = (
    "미확정",
    "불분명",
    "확정되지",
    "확정 정보가 없",
    "결론을 내릴 수 없",
    "유효성이 불",
    "달라진",
    "바뀐 듯",
)
USER_REFERENCE_ROOTS = ("사용자", "누구에게", "대상", "수신처", "범위")
INVALIDATION_ROOTS = ("전제", "허용", "승인", "근거", "consent")
INVALID_STATE_ROOTS = ("사라", "무효", "취소", "깨", "무너", "믿을 수 없", "뒤집")
SENSITIVE_FIELD_ROOTS = (
    "민감",
    "식별",
    "원문",
    "raw",
    "위치",
    "장소",
    "수치",
    "숫자",
    "주민",
    "rrn",
    "이름",
    "나이",
)
REDACTION_ACTION_ROOTS = ("제외", "제거", "덜어", "익명", "정제", "포함하지", "남기지")
SUMMARY_LIMIT_ROOTS = ("요약만", "최소 요약", "요약으로만", "요약 수준")
DIRECTIVE_ROOTS = (
    "해줘",
    "하라",
    "해라",
    "해야",
    "말고",
    "우선한다",
    "처리해",
    "진행해",
    "실행해",
    "바꿔",
    "켜줘",
    "꺼줘",
)
REPORTED_CONTEXT_ROOTS = (
    "지난 성공",
    "실패 기록",
    "이전 요청",
    "직전 턴",
    "과거 처리",
    "라고 말했다",
    "라고 요청했다",
)


def _clauses(text: str) -> tuple[tuple[str, int, int], ...]:
    return clause_tuples(text)


def is_reported_clause(text: str) -> bool:
    normalized = normalize_text(text)
    return any(root in normalized for root in REPORTED_CONTEXT_ROOTS) and not any(
        root in normalized for root in DIRECTIVE_ROOTS
    )


def reports_quoted_instruction(text: str) -> bool:
    normalized = normalize_text(text)
    return any(
        term in normalized for term in ("라고 말했다", "라고 요청", "인용", "원문")
    )


def is_memory_write_clause(text: str) -> bool:
    normalized = normalize_text(text)
    has_memory_object = any(
        root in normalized for root in ("메모리", "기억", "사용자 정보")
    )
    has_write_action = any(
        root in normalized
        for root in ("저장해", "저장하", "기억해", "기억하", "기록해", "남겨")
    )
    recalls_prior_write = bool(
        re.search(r"(?:지난번|이전|과거)[^.!?]{0,24}(?:저장|기억|기록)", normalized)
    )
    return has_memory_object and has_write_action and not recalls_prior_write


def is_strong_local_clause(text: str) -> bool:
    normalized = normalize_text(text)
    memory_write = is_memory_write_clause(normalized)
    has_local_anchor = any(
        root in normalized
        for root in (
            "내부",
            "로컬",
            "기기 안",
            "기기 내부",
            "내 기기",
            "장치 안",
            "장치 내부",
        )
    )
    has_state_subject = any(root in normalized for root in ("상태", "기록", "완료"))
    has_update_action = any(
        root in normalized
        for root in ("갱신", "업데이트", "바꾸", "남기", "정리", "새로 쓰")
    )
    has_exclusivity = any(
        root in normalized for root in ("만", "한정", "으로 끝", "것으로 끝")
    )
    explicit_status_only = (
        bool(LOCAL_EXCLUSIVE_RE.search(normalized))
        or (has_state_subject and has_update_action and has_exclusivity)
        or (has_local_anchor and has_state_subject and has_update_action)
    )
    redirected = bool(EXTERNAL_CANCEL_RE.search(normalized)) and (
        bool(LOCAL_DESTINATION_RE.search(normalized)) or explicit_status_only
    )
    return memory_write or explicit_status_only or redirected


def is_strong_local(text: str) -> bool:
    return any(is_strong_local_clause(clause) for clause, _, _ in _clauses(text))


def is_decisive_stop_clause(text: str) -> bool:
    normalized = normalize_text(text)
    direct_block = (
        bool(
            re.search(
                r"(?:중단|멈(?:추|춘|춰)|보류|차단|실행을\s*막)[^.!?]{0,16}"
                r"(?:해야|한다|하라|해라|하지|된다|아야)",
                normalized,
            )
        )
        and "보류 여부" not in normalized
    )
    negative_execution = bool(
        re.search(
            r"(?:실행|진행|처리|수행)[^.!?]{0,24}"
            r"(?:하면\s*안|하지\s*말|하지\s*않|할\s*수\s*없)",
            normalized,
        )
    )
    invalidated = (
        any(root in normalized for root in INVALIDATION_ROOTS)
        and any(root in normalized for root in INVALID_STATE_ROOTS)
        and (direct_block or negative_execution or "위험" in normalized)
    )
    return direct_block or negative_execution or invalidated


def is_decisive_stop(text: str) -> bool:
    return any(is_decisive_stop_clause(clause) for clause, _, _ in _clauses(text))


def clarification_payload(text: str) -> str:
    normalized = normalize_text(text)
    has_confirmation = any(root in normalized for root in CONFIRMATION_ROOTS)
    has_uncertainty = any(root in normalized for root in UNCERTAINTY_ROOTS)
    explicit_question = any(
        root in normalized for root in ("물어", "질문", "clarification")
    )
    asks_for_confirmation = any(
        root in normalized
        for root in ("먼저", "다시", "해야", "해줘", "하라는", "거친")
    )
    user_confirmation = (
        "사용자" in normalized and "확인" in normalized and asks_for_confirmation
    )
    interrogative_confirmation = has_confirmation and any(
        root in normalized
        for root in ("누구에게", "어떤 범위", "어느 대상", "어느 수신처")
    )
    scoped_confirmation = (
        has_confirmation
        and has_uncertainty
        and any(root in normalized for root in USER_REFERENCE_ROOTS)
    )
    route_gate = (
        any(
            root in normalized
            for root in ("수신처", "승인 경로", "외부 공유", "대상", "범위")
        )
        and any(
            root in normalized
            for root in ("확정되지", "아직", "닫히", "충돌", "함께 언급")
        )
        and has_confirmation
    )
    insufficient_information = has_uncertainty and any(
        root in normalized
        for root in (
            "현재 정보",
            "결론",
            "확인되지",
            "미확정",
            "확정 정보가 없",
            "유효성이 불",
        )
    )
    detected = (
        explicit_question
        or user_confirmation
        or interrogative_confirmation
        or scoped_confirmation
        or route_gate
        or insufficient_information
    )
    if not detected:
        return ""
    conditional = any(
        root in normalized for root in ("필요하면", "필요한 경우", "경우에는", "때에는")
    )
    explicitly_addresses_user = (
        user_confirmation
        or interrogative_confirmation
        or insufficient_information
        or route_gate
        or (explicit_question and not conditional)
    )
    return "clarify_user" if explicitly_addresses_user else "constraint_only"


def is_clarification_clause(text: str) -> bool:
    return bool(clarification_payload(text))


def is_clarification_request(text: str) -> bool:
    return any(is_clarification_clause(clause) for clause, _, _ in _clauses(text))


def is_redaction_clause(text: str) -> bool:
    normalized = normalize_text(text)
    has_sensitive_field = any(root in normalized for root in SENSITIVE_FIELD_ROOTS)
    removes_field = any(root in normalized for root in REDACTION_ACTION_ROOTS)
    limits_to_summary = any(root in normalized for root in SUMMARY_LIMIT_ROOTS)
    privacy_delegation = "민감" in normalized and "알아서 처리" in normalized
    return (
        (has_sensitive_field and removes_field)
        or limits_to_summary
        or privacy_delegation
    )


def is_redaction_request(text: str) -> bool:
    return any(is_redaction_clause(clause) for clause, _, _ in _clauses(text))


def domain_actions(text: str) -> tuple[str, ...]:
    normalized = normalize_text(text)
    actions: list[str] = []
    if any(root in normalized for root in ("결제", "지불", "구매")) and re.search(
        r"(?:결제|지불|구매)(?:해(?:줘|주세요|라|서|야)|하(?:고|라|자|도록|세요|십시오))",
        normalized,
    ):
        actions.append("PAY")
    if any(
        root in normalized for root in ("설정", "루틴", "조명", "기기")
    ) and re.search(
        r"(?:켜(?:줘|주세요|라|고|야|도록)|꺼(?:줘|주세요|라|고|야|도록)|"
        r"바꿔|변경해|토글해)",
        normalized,
    ):
        actions.append("TOGGLE")
    if any(root in normalized for root in ("일정", "캘린더", "예약")) and re.search(
        r"(?:등록해|추가해|변경해|잡아(?:줘|주세요|라)|예약해|"
        r"예약하(?:고|라|자|도록|세요))",
        normalized,
    ):
        actions.append("SCHEDULE")
    return tuple(actions)


def negated_domain_actions(text: str) -> tuple[str, ...]:
    normalized = normalize_text(text)
    actions: list[str] = []
    if any(root in normalized for root in ("결제", "지불", "구매")) and re.search(
        r"(?:결제|지불|구매)(?:하지|하지는|하지도|하면\s*안)",
        normalized,
    ):
        actions.append("PAY")
    if re.search(
        r"(?:켜지|끄지|꺼지|변경하지|바꾸지|토글하지)\s*(?:말|마|않|못|안)",
        normalized,
    ):
        actions.append("TOGGLE")
    if any(root in normalized for root in ("일정", "캘린더", "예약")) and re.search(
        r"(?:등록하지|추가하지|변경하지|예약하지|잡지)\s*(?:말|마|않|못|안)",
        normalized,
    ):
        actions.append("SCHEDULE")
    return tuple(actions)


def operation_arguments(text: str) -> tuple[tuple[str, str], ...]:
    normalized = normalize_text(text)
    matches: list[tuple[int, str, str]] = []
    for pattern, action, value in (
        (r"켜(?:줘|주세요|라|고|야|도록)", "TOGGLE", "desired_state:enabled"),
        (r"꺼(?:줘|주세요|라|고|야|도록)", "TOGGLE", "desired_state:disabled"),
    ):
        for match in re.finditer(pattern, normalized):
            matches.append((match.start(), action, value))
    return tuple((action, value) for _start, action, value in sorted(matches))


SHARE_MENTION_RE = re.compile(r"공유|보내|전달|올려")


def is_negated_share_mention(text: str, end: int) -> bool:
    tail = text[end : end + 28]
    return bool(
        re.match(
            r"(?:지\s*(?:말|마|않)|는\s*(?:작업|동작|단계)?[^.!?]{0,12}"
            r"(?:취소|생략)|[^.!?]{0,16}(?:말고|아니라))",
            tail,
        )
    )


def has_positive_share(text: str) -> bool:
    return any(
        not is_negated_share_mention(text, match.end())
        for match in SHARE_MENTION_RE.finditer(text)
    )


def domain_references(text: str) -> tuple[str, ...]:
    normalized = normalize_text(text)
    actions: list[str] = []
    if any(root in normalized for root in ("결제", "지불", "구매")):
        actions.append("PAY")
    if any(root in normalized for root in ("기기 설정", "설정", "루틴", "조명")):
        actions.append("TOGGLE")
    if any(root in normalized for root in ("일정", "캘린더", "예약")):
        actions.append("SCHEDULE")
    return tuple(actions)
