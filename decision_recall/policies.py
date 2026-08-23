from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple

from .domain import (
    AuthorizationDecision,
    AuthorizationStatus,
    CompositionAuthorizationDecision,
    CompositionCandidate,
    CompositionValue,
    EvidenceRecord,
    ProvenanceType,
    RelationCandidate,
    RelationType,
)


def _index_unique_evidence(evidence: Iterable[EvidenceRecord]) -> dict[str, EvidenceRecord]:
    items = tuple(evidence)
    ids = tuple(item.id for item in items)
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate evidence id in snapshot")
    return {item.id: item for item in items}


@dataclass(frozen=True)
class EvidencePolicy:
    version: str
    historical_role_provenance: Tuple[ProvenanceType, ...]

    def authorize_historical_role(
        self,
        *,
        candidate: RelationCandidate,
        evidence: Iterable[EvidenceRecord],
    ) -> AuthorizationDecision:
        available = _index_unique_evidence(evidence)
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


@dataclass(frozen=True)
class CompositionPolicy:
    version: str
    sufficiency_provenance: Tuple[ProvenanceType, ...]

    def authorize(
        self,
        *,
        candidate: CompositionCandidate,
        evidence: Iterable[EvidenceRecord],
    ) -> CompositionAuthorizationDecision:
        available = _index_unique_evidence(evidence)
        if candidate.asserted_value not in (
            CompositionValue.ESTABLISHED_TRUE,
            CompositionValue.ESTABLISHED_FALSE,
        ):
            return CompositionAuthorizationDecision(
                candidate_id=candidate.id,
                status=AuthorizationStatus.UNAUTHORIZED,
                authorized_value=None,
                evidence_refs=tuple(candidate.evidence_refs),
                policy_version=self.version,
                reason_code="ONLY_EXPLICIT_TRUE_OR_FALSE_CAN_BE_AUTHORIZED",
            )
        if not candidate.evidence_refs:
            # In particular, absence of sufficiency evidence can never establish FALSE.
            return CompositionAuthorizationDecision(
                candidate_id=candidate.id,
                status=AuthorizationStatus.INSUFFICIENT_EVIDENCE,
                authorized_value=None,
                evidence_refs=(),
                policy_version=self.version,
                reason_code="NO_COMPOSITION_EVIDENCE",
            )
        if any(ref not in available for ref in candidate.evidence_refs):
            return CompositionAuthorizationDecision(
                candidate_id=candidate.id,
                status=AuthorizationStatus.INSUFFICIENT_EVIDENCE,
                authorized_value=None,
                evidence_refs=tuple(candidate.evidence_refs),
                policy_version=self.version,
                reason_code="COMPOSITION_EVIDENCE_NOT_AVAILABLE",
            )
        used = tuple(available[ref] for ref in candidate.evidence_refs)
        if any(item.provenance_type not in self.sufficiency_provenance for item in used):
            return CompositionAuthorizationDecision(
                candidate_id=candidate.id,
                status=AuthorizationStatus.UNAUTHORIZED,
                authorized_value=None,
                evidence_refs=tuple(candidate.evidence_refs),
                policy_version=self.version,
                reason_code="PROVENANCE_NOT_AUTHORIZED_FOR_COMPOSITION",
            )
        return CompositionAuthorizationDecision(
            candidate_id=candidate.id,
            status=AuthorizationStatus.AUTHORIZED,
            authorized_value=candidate.asserted_value,
            evidence_refs=tuple(candidate.evidence_refs),
            policy_version=self.version,
            reason_code="AUTHORIZED_COMPOSITION_PROVENANCE",
        )


def evidence_policy_v1() -> EvidencePolicy:
    return EvidencePolicy(
        version="EP_V1",
        historical_role_provenance=(
            ProvenanceType.CONTEMPORANEOUS_RECORD,
            ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION,
        ),
    )


def composition_policy_v1() -> CompositionPolicy:
    return CompositionPolicy(
        version="CP_V1",
        sufficiency_provenance=(
            ProvenanceType.CONTEMPORANEOUS_RECORD,
            ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION,
        ),
    )
