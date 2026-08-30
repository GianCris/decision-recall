from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping, Protocol, Tuple

from ..domain import DecisionContract, ProvenanceType, RelationType
from ..temporal import (
    AuthorizedAssertion,
    CandidateAssertion,
    TemporalEvidenceRecord,
    TemporalReference,
    source_hash,
)
from .capture import CaptureProfile, CriticalGap


class CandidateKind(str, Enum):
    FACT = "fact"
    HISTORICAL_ROLE = "historical_role"
    ELICITED_HISTORICAL_ROLE = "elicited_historical_role"


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    content: str
    provenance_type: ProvenanceType
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.content:
            raise ValueError("source document id/content are required")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("source observed_at must be timezone-aware")


@dataclass(frozen=True)
class ObservableDecisionBundle:
    decision_id: str
    sources: Tuple[SourceDocument, ...]

    def source_map(self) -> Mapping[str, SourceDocument]:
        mapping = {item.source_id: item for item in self.sources}
        if len(mapping) != len(self.sources):
            raise ValueError("observable source ids must be unique")
        return mapping


@dataclass(frozen=True)
class GroundedCandidate:
    """Probabilistic output: semantic key + exact source span, never canonical entity id."""

    candidate_id: str
    semantic_key: str
    kind: CandidateKind
    source_id: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.semantic_key.strip() or not self.source_id.strip():
            raise ValueError("grounded candidate ids/semantic key/source are required")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("grounded candidate span is invalid")


@dataclass(frozen=True)
class ResolvedGroundedCandidate:
    candidate_id: str
    semantic_key: str
    kind: CandidateKind
    entity_id: str
    assertion: AuthorizedAssertion
    source_id: str
    start: int
    end: int


@dataclass(frozen=True)
class CandidateBundle:
    candidates: Tuple[GroundedCandidate, ...]


class CandidateCompiler(Protocol):
    def compile_observable(
        self,
        *,
        observable: ObservableDecisionBundle,
        profile: CaptureProfile,
    ) -> CandidateBundle: ...

    def compile_response(
        self,
        *,
        response_source: SourceDocument,
        gap: CriticalGap,
        profile: CaptureProfile,
    ) -> CandidateBundle: ...


class SemanticCandidateResolver:
    """Resolve semantic keys only inside the controlled contract/profile surface.

    Normal observable compilation cannot establish an unresolved capture-profile
    slot. Only a separately typed elicited-response candidate can resolve one.
    """

    @staticmethod
    def historical_key(subject_predicate_key: str) -> str:
        return f"historical_support:{subject_predicate_key}"

    def resolve(
        self,
        *,
        candidate: GroundedCandidate,
        contract: DecisionContract,
        profile: CaptureProfile,
    ) -> ResolvedGroundedCandidate:
        if candidate.kind is CandidateKind.FACT:
            matches = tuple(
                claim for claim in contract.claims
                if claim.predicate_key == candidate.semantic_key
            )
            if len(matches) != 1:
                raise ValueError("fact semantic key is unknown or ambiguous in allowed contract surface")
            entity_id = matches[0].id
            assertion = AuthorizedAssertion.ESTABLISHED_FACT
        elif candidate.kind is CandidateKind.ELICITED_HISTORICAL_ROLE:
            profile_matches = tuple(
                item for item in profile.slots
                if item.semantic_role == candidate.semantic_key
            )
            if len(profile_matches) != 1:
                raise ValueError("elicited historical semantic key is not the assigned capture slot")
            slot = profile_matches[0].slot
            relations = tuple(
                relation for relation in contract.historical_relations
                if relation.id == slot.id
                and relation.relation_type is slot.relation_type
                and relation.subject_id == slot.subject_id
                and relation.object_id == slot.object_id
            )
            if len(relations) != 1:
                raise ValueError("assigned relation slot is not present in contract semantic surface")
            entity_id = relations[0].id
            assertion = AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE
        elif candidate.kind is CandidateKind.HISTORICAL_ROLE:
            if any(item.semantic_role == candidate.semantic_key for item in profile.slots):
                raise ValueError("unresolved capture slot cannot be established from observable compilation")
            matches = []
            for relation in contract.historical_relations:
                if relation.relation_type is not RelationType.HISTORICAL_SUPPORT:
                    continue
                subject = next((claim for claim in contract.claims if claim.id == relation.subject_id), None)
                if subject is None:
                    continue
                if self.historical_key(subject.predicate_key) == candidate.semantic_key:
                    matches.append(relation)
            if len(matches) != 1:
                raise ValueError("historical semantic key is unknown or ambiguous in allowed contract surface")
            entity_id = matches[0].id
            assertion = AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE
        else:  # pragma: no cover
            raise ValueError("unsupported candidate kind")

        return ResolvedGroundedCandidate(
            candidate_id=candidate.candidate_id,
            semantic_key=candidate.semantic_key,
            kind=candidate.kind,
            entity_id=entity_id,
            assertion=assertion,
            source_id=candidate.source_id,
            start=candidate.start,
            end=candidate.end,
        )


def _span(content: str, quote: str) -> tuple[int, int]:
    start = content.find(quote)
    if start < 0:
        raise ValueError(f"deterministic fixture quote not found: {quote!r}")
    return start, start + len(quote)


class DeterministicGoldenCompiler:
    """Fixture compiler for CI. Gemini must later return this same bounded schema."""

    def compile_observable(
        self,
        *,
        observable: ObservableDecisionBundle,
        profile: CaptureProfile,
    ) -> CandidateBundle:
        del profile
        sources = observable.source_map()
        decision = sources["decision-note"].content
        supplier = sources["supplier-record"].content

        f1_quote = "Apex delivery performance has been materially unstable."
        f2_quote = "Beacon requires roughly 10 weeks to reactivate."
        r1_quote = "Apex instability materially influenced the decision."
        f1_start, f1_end = _span(decision, f1_quote)
        f2_start, f2_end = _span(supplier, f2_quote)
        r1_start, r1_end = _span(decision, r1_quote)
        return CandidateBundle(
            candidates=(
                GroundedCandidate("GC-F1", "apex_delivery_instability", CandidateKind.FACT, "decision-note", f1_start, f1_end),
                GroundedCandidate("GC-F2", "beacon_reactivation_delay", CandidateKind.FACT, "supplier-record", f2_start, f2_end),
                GroundedCandidate(
                    "GC-R1",
                    SemanticCandidateResolver.historical_key("apex_delivery_instability"),
                    CandidateKind.HISTORICAL_ROLE,
                    "decision-note",
                    r1_start,
                    r1_end,
                ),
            )
        )

    def compile_response(
        self,
        *,
        response_source: SourceDocument,
        gap: CriticalGap,
        profile: CaptureProfile,
    ) -> CandidateBundle:
        slot_spec = next((item for item in profile.slots if item.slot.id == gap.slot_id), None)
        if slot_spec is None:
            raise ValueError("response gap is not part of assigned profile")
        text = response_source.content.strip()
        if not text.lower().startswith("yes"):
            return CandidateBundle(candidates=())
        return CandidateBundle(
            candidates=(
                GroundedCandidate(
                    "GC-R2-RESPONSE",
                    slot_spec.semantic_role,
                    CandidateKind.ELICITED_HISTORICAL_ROLE,
                    response_source.source_id,
                    0,
                    len(response_source.content),
                ),
            )
        )


class EvidenceResolver:
    """Build evidence only from exact text inside immutable observable sources."""

    def resolve(
        self,
        *,
        observable: ObservableDecisionBundle,
        candidate: ResolvedGroundedCandidate,
        evidence_id: str,
    ) -> TemporalEvidenceRecord:
        source = observable.source_map().get(candidate.source_id)
        if source is None:
            raise ValueError("candidate references unknown observable source")
        if candidate.end > len(source.content):
            raise ValueError("candidate span exceeds source content")
        exact = source.content[candidate.start:candidate.end]
        if not exact:
            raise ValueError("candidate source span is empty")
        return TemporalEvidenceRecord(
            id=evidence_id,
            content=exact,
            source_id=source.source_id,
            source_span=f"chars:{candidate.start}-{candidate.end}",
            source_content_hash=source_hash(exact),
            provenance_type=source.provenance_type,
            temporal_reference=TemporalReference.point(source.observed_at),
            candidate_assertions=(CandidateAssertion(candidate.entity_id, candidate.assertion),),
        )
