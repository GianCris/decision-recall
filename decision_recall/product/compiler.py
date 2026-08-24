from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol, Tuple

from ..domain import ProvenanceType
from ..temporal import (
    AuthorizedAssertion,
    CandidateAssertion,
    TemporalEvidenceRecord,
    TemporalReference,
    source_hash,
)
from .capture import CaptureProfile, CriticalGap


_ALLOWED_COMPILER_ASSERTIONS = frozenset(
    {
        AuthorizedAssertion.ESTABLISHED_FACT,
        AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
    }
)


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
    """A compiler may point at source spans, never manufacture authoritative evidence."""

    candidate_id: str
    entity_id: str
    assertion: AuthorizedAssertion
    source_id: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.assertion not in _ALLOWED_COMPILER_ASSERTIONS:
            raise ValueError("compiler cannot emit rule, composition, or epistemic authorization states")
        if not self.candidate_id.strip() or not self.entity_id.strip() or not self.source_id.strip():
            raise ValueError("grounded candidate ids/source are required")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("grounded candidate span is invalid")


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


def _span(content: str, quote: str) -> tuple[int, int]:
    start = content.find(quote)
    if start < 0:
        raise ValueError(f"deterministic fixture quote not found: {quote!r}")
    return start, start + len(quote)


class DeterministicGoldenCompiler:
    """Fixture compiler for CI. Same grounded schema that Gemini must later return."""

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
                GroundedCandidate(
                    "GC-F1",
                    "F1",
                    AuthorizedAssertion.ESTABLISHED_FACT,
                    "decision-note",
                    f1_start,
                    f1_end,
                ),
                GroundedCandidate(
                    "GC-F2",
                    "F2",
                    AuthorizedAssertion.ESTABLISHED_FACT,
                    "supplier-record",
                    f2_start,
                    f2_end,
                ),
                GroundedCandidate(
                    "GC-R1",
                    "R1",
                    AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
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
        if gap.slot_id not in {item.slot.id for item in profile.slots}:
            raise ValueError("response gap is not part of assigned profile")
        text = response_source.content.strip()
        if not text.lower().startswith("yes"):
            return CandidateBundle(candidates=())
        return CandidateBundle(
            candidates=(
                GroundedCandidate(
                    "GC-R2-RESPONSE",
                    gap.slot_id,
                    AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
                    response_source.source_id,
                    0,
                    len(response_source.content),
                ),
            )
        )


class EvidenceResolver:
    """Build evidence only from exact bytes/text inside immutable observable sources."""

    def resolve(
        self,
        *,
        observable: ObservableDecisionBundle,
        candidate: GroundedCandidate,
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
