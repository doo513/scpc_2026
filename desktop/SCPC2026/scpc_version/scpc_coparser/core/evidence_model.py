from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .contracts import ContractStatus
from .prompt_document import TextAuthority
from .records import Provenance


class EvidenceKind(str, Enum):
    EXECUTION_REQUEST = "execution_request"
    CANCEL_ACTION = "cancel_action"
    STOP_PROCESS = "stop_process"
    VERIFY_REQUEST = "verify_request"
    CLARIFICATION_REQUEST = "clarification_request"
    SHARE_REQUEST = "share_request"
    LOCAL_UPDATE_REQUEST = "local_update_request"
    REDACTION_REQUEST = "redaction_request"
    MEMORY_WRITE_REQUEST = "memory_write_request"
    EXPLICIT_DOMAIN_VERB = "explicit_domain_verb"
    DOMAIN_REFERENCE = "domain_reference"
    DOMAIN_CANCEL_REQUEST = "domain_cancel_request"
    DOMAIN_VERIFY_REQUEST = "domain_verify_request"
    NEGATED_DOMAIN_VERB = "negated_domain_verb"
    OPERATION_ARGUMENT = "operation_argument"
    CONTENT_VARIANT_SELECTION = "content_variant_selection"
    VALUE_TRANSFER_REQUEST = "value_transfer_request"
    MEMORY_CONTEXT_REFERENCE = "memory_context_reference"
    MEMORY_REJECTION = "memory_rejection"
    SESSION_TARGET_REFERENCE = "session_target_reference"
    HISTORICAL_FOCAL_REFERENCE = "historical_focal_reference"
    POLICY_OVERRIDE_ATTEMPT = "policy_override_attempt"
    AUTHORIZED_FALLBACK = "authorized_fallback"


class EvidenceStrength(str, Enum):
    DECISIVE = "decisive"
    STRONG = "strong"
    SUPPORTING = "supporting"


class AssertionMode(str, Enum):
    DIRECT = "direct"
    REPORTED = "reported"
    QUOTED = "quoted"


@dataclass(frozen=True)
class IntentEvidence:
    evidence_id: str
    kind: EvidenceKind
    payload: str
    polarity: str
    scope: str
    strength: EvidenceStrength
    text: str
    canonical_text_key: str
    provenance: Provenance
    active: bool = True
    supersedes: tuple[str, ...] = ()
    superseded_by: tuple[str, ...] = ()
    authority: str = TextAuthority.DIRECT_USER.value
    rule_id: str = ""
    contract_status: ContractStatus = ContractStatus.SUPPORTED_INTERPRETATION
    assumption_refs: tuple[str, ...] = ()
    semantic_slot: str = ""


@dataclass(frozen=True)
class RuleEvidenceProposal:
    rule_id: str
    kind: EvidenceKind
    payload: str
    polarity: str
    scope: str
    strength: EvidenceStrength
    semantic_slot: str
    source_span: tuple[int, int]
    contract_status: ContractStatus
    assumption_refs: tuple[str, ...] = ()
