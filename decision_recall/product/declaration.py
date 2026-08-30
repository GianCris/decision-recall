from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json

from ..domain import ProvenanceType
from ..temporal import (
    AuthorizedAssertion,
    CandidateAssertion,
    TemporalEvidenceRecord,
    TemporalReference,
    source_hash,
)
from .capture import CaptureSessionState, CriticalGap


class CaptureAnswer(str, Enum):
    """Explicit human response to a previously issued prospective gap question."""

    YES = "yes"
    NO = "no"
    NOT_SURE = "not_sure"
    SKIP = "skip"


@dataclass(frozen=True)
class StructuredCaptureDeclaration:
    """Human authority bound to the exact prospective question and assignment.

    V1 deliberately preserves explicit NO without projecting it into a positive
    HistoricalRelation because the frozen core has no negative historical-role
    assertion. NOT_SURE is distinct and can authorize T0_UNRESOLVED.
    """

    id: str
    capture_session_id: str
    profile_artifact_id: str
    profile_hash: str
    gap_id: str
    question_hash: str
    gap_selected_at: datetime
    answer: CaptureAnswer
    answered_at: datetime
    provenance_type: ProvenanceType
    optional_note: str = ""

    def __post_init__(self) -> None:
        required = (
            self.id,
            self.capture_session_id,
            self.profile_artifact_id,
            self.profile_hash,
            self.gap_id,
            self.question_hash,
        )
        if any(not item.strip() for item in required):
            raise ValueError("structured capture declaration binding fields are required")
        for value, name in ((self.gap_selected_at, "gap_selected_at"), (self.answered_at, "answered_at")):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"structured capture declaration {name} must be timezone-aware")
        if self.answered_at < self.gap_selected_at:
            raise ValueError("structured capture declaration cannot predate the selected gap")
        if self.provenance_type is not ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION:
            raise ValueError("structured capture declaration requires elicited contemporaneous provenance")


def capture_question_hash(question: str) -> str:
    if not question.strip():
        raise ValueError("capture question cannot be empty")
    return sha256(question.encode("utf-8")).hexdigest()


def _declaration_payload(
    *,
    capture_session_id: str,
    profile_artifact_id: str,
    profile_hash: str,
    gap_id: str,
    question_hash: str,
    gap_selected_at: datetime,
    answer: CaptureAnswer,
    answered_at: datetime,
    optional_note: str,
) -> dict[str, str]:
    return {
        "capture_session_id": capture_session_id,
        "profile_artifact_id": profile_artifact_id,
        "profile_hash": profile_hash,
        "gap_id": gap_id,
        "question_hash": question_hash,
        "gap_selected_at": gap_selected_at.isoformat(),
        "answer": answer.value,
        "answered_at": answered_at.isoformat(),
        "optional_note": optional_note,
    }


def _declaration_id(*, gap_id: str, payload: dict[str, str]) -> str:
    digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"CAPTURE-DECL:{gap_id}:{digest[:16]}"


def make_structured_capture_declaration(
    *,
    session: CaptureSessionState,
    gap: CriticalGap,
    answer: CaptureAnswer,
    answered_at: datetime,
    optional_note: str = "",
) -> StructuredCaptureDeclaration:
    if gap.slot_id not in session.questions_issued:
        raise ValueError("cannot answer a capture gap that was never issued")
    if answered_at.tzinfo is None or answered_at.utcoffset() is None:
        raise ValueError("structured capture declaration answered_at must be timezone-aware")
    if answered_at < gap.selected_at:
        raise ValueError("structured capture declaration cannot predate the selected gap")

    qhash = capture_question_hash(gap.question)
    payload = _declaration_payload(
        capture_session_id=session.assignment.session_id,
        profile_artifact_id=session.assignment.artifact_id,
        profile_hash=session.assignment.profile_hash,
        gap_id=gap.slot_id,
        question_hash=qhash,
        gap_selected_at=gap.selected_at,
        answer=answer,
        answered_at=answered_at,
        optional_note=optional_note,
    )
    return StructuredCaptureDeclaration(
        id=_declaration_id(gap_id=gap.slot_id, payload=payload),
        capture_session_id=session.assignment.session_id,
        profile_artifact_id=session.assignment.artifact_id,
        profile_hash=session.assignment.profile_hash,
        gap_id=gap.slot_id,
        question_hash=qhash,
        gap_selected_at=gap.selected_at,
        answer=answer,
        answered_at=answered_at,
        provenance_type=ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION,
        optional_note=optional_note,
    )


def declaration_to_evidence(
    *,
    declaration: StructuredCaptureDeclaration,
    session: CaptureSessionState,
    gap: CriticalGap,
    evidence_id: str,
) -> TemporalEvidenceRecord:
    """Rebind every declaration to authoritative capture state before evidence exists."""

    assignment = session.assignment
    if declaration.capture_session_id != assignment.session_id:
        raise ValueError("structured declaration is bound to a different capture session")
    if declaration.profile_artifact_id != assignment.artifact_id or declaration.profile_hash != assignment.profile_hash:
        raise ValueError("structured declaration profile binding does not match the assigned profile")
    if gap.slot_id not in session.questions_issued:
        raise ValueError("structured declaration references an unissued capture gap")
    if declaration.gap_id != gap.slot_id:
        raise ValueError("structured declaration is bound to a different capture gap")
    if declaration.question_hash != capture_question_hash(gap.question):
        raise ValueError("structured declaration question binding does not match the issued question")
    if declaration.gap_selected_at != gap.selected_at:
        raise ValueError("structured declaration gap timestamp binding does not match the issued gap")

    payload = _declaration_payload(
        capture_session_id=declaration.capture_session_id,
        profile_artifact_id=declaration.profile_artifact_id,
        profile_hash=declaration.profile_hash,
        gap_id=declaration.gap_id,
        question_hash=declaration.question_hash,
        gap_selected_at=declaration.gap_selected_at,
        answer=declaration.answer,
        answered_at=declaration.answered_at,
        optional_note=declaration.optional_note,
    )
    if declaration.id != _declaration_id(gap_id=declaration.gap_id, payload=payload):
        raise ValueError("structured declaration content does not reproduce its declaration id")
    content = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    if declaration.answer is CaptureAnswer.YES:
        assertions = (
            CandidateAssertion(gap.slot_id, AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE),
        )
    elif declaration.answer is CaptureAnswer.NOT_SURE:
        assertions = (
            CandidateAssertion(gap.slot_id, AuthorizedAssertion.T0_UNRESOLVED),
        )
    else:
        # NO is intentionally preserved as an explicit declaration without being
        # collapsed into UNKNOWN or falsely projected as a positive relation.
        # SKIP likewise creates no semantic authority.
        assertions = ()

    return TemporalEvidenceRecord(
        id=evidence_id,
        content=content,
        source_id=f"capture-session:{declaration.capture_session_id}",
        source_span=f"structured-declaration:{declaration.id}",
        source_content_hash=source_hash(content),
        provenance_type=declaration.provenance_type,
        temporal_reference=TemporalReference.point(declaration.answered_at),
        candidate_assertions=assertions,
    )
