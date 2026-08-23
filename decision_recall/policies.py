from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple

from .domain import (
    AuthorizationDecision,
    AuthorizationStatus,
    EvidenceRecord,
    RelationCandidate,
    RelationType,
)


@dataclass(frozen=True)
class EvidencePolicy:
    version: str
    historical_role_provenance: Tuple[str, ...]

    def authorize_historical_role(
        self,
        *,
        candidate: RelationCandidate,
        evidence: Iterable[EvidenceRecord],
    ) -> AuthorizationDecision:
        available = {item.id: item for item in evidence}
        if candidate.relation_type is not RelationType.HISTORICAL_SUPPORT:
            return AuthorizationDecision(
                candidate_id=candidate.id,
                status=AuthorizationStatus.UNAUTHORIZED,
                authorized_as=None,
                evidence_refs=tuple(candidate.evidence_refs),
                policy_version=self.version,
                reason_code="RELATION_TYPE_NOT_ALLOWED",
            )
        if not candidate.evidence_refs:
            return AuthorizationDecision(
                candidate_id=candidate.id,
                status=AuthorizationStatus.INSUFFICIENT_EVIDENCE,
                authorized_as=None,
                evidence_refs=(),
                policy_version=self.version,
                reason_code="NO_EVIDENCE",
            )
        if any(ref not in available for ref in candidate.evidence_refs):
            return AuthorizationDecision(
                candidate_id=candidate.id,
                status=AuthorizationStatus.INSUFFICIENT_EVIDENCE,
                authorized_as=None,
                evidence_refs=tuple(candidate.evidence_refs),
                policy_version=self.version,
                reason_code="EVIDENCE_NOT_AVAILABLE",
            )
        used = tuple(available[ref] for ref in candidate.evidence_refs)
        if any(item.provenance_type not in self.historical_role_provenance for item in used):
            return AuthorizationDecision(
                candidate_id=candidate.id,
                status=AuthorizationStatus.UNAUTHORIZED,
                authorized_as=None,
                evidence_refs=tuple(candidate.evidence_refs),
                policy_version=self.version,
                reason_code="PROVENANCE_NOT_AUTHORIZED_FOR_HISTORICAL_ROLE",
            )
        return AuthorizationDecision(
            candidate_id=candidate.id,
            status=AuthorizationStatus.AUTHORIZED,
            authorized_as=RelationType.HISTORICAL_SUPPORT,
            evidence_refs=tuple(candidate.evidence_refs),
            policy_version=self.version,
            reason_code="AUTHORIZED_PROVENANCE",
        )


def evidence_policy_v1() -> EvidencePolicy:
    return EvidencePolicy(
        version="EP_V1",
        historical_role_provenance=(
            "CONTEMPORANEOUS_RECORD",
            "CONTEMPORANEOUS_ELICITED_DECLARATION",
        ),
    )
