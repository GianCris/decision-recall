"""Server-configured example interpretation, not a provider/model execution.

Plans contain only semantic candidates and exact quotes. The existing resolvers
and ledger policy still determine admission and historical authority.
"""
from dataclasses import dataclass

from .compiler import (
    CandidateBundle, CandidateKind, GroundedCandidate, SemanticCandidateResolver,
)


@dataclass(frozen=True, slots=True)
class ConfiguredCandidateSpec:
    semantic_key: str
    candidate_kind: CandidateKind
    source_id: str
    exact_quote: str

    def __post_init__(self):
        if any(type(value) is not str or not value.strip()
               for value in (self.semantic_key, self.source_id, self.exact_quote)):
            raise ValueError("candidate semantic key, source and exact quote are required")
        if type(self.candidate_kind) is not CandidateKind or self.candidate_kind not in (
            CandidateKind.FACT, CandidateKind.HISTORICAL_ROLE,
        ):
            raise ValueError("configured examples accept only fact/historical-role candidates")


@dataclass(frozen=True, slots=True)
class ConfiguredCandidatePlan:
    decision_id: str
    profile_id: str
    profile_version: str
    candidates: tuple[ConfiguredCandidateSpec, ...]

    def __post_init__(self):
        if any(type(value) is not str or not value.strip()
               for value in (self.decision_id, self.profile_id, self.profile_version)):
            raise ValueError("candidate plan requires registered decision/profile identity")
        if (type(self.candidates) is not tuple or not self.candidates
                or any(type(item) is not ConfiguredCandidateSpec for item in self.candidates)):
            raise ValueError("candidate plan accepts only immutable bounded candidate specs")


class ConfiguredCandidateCompiler:
    """Mechanically locate quotes; never supply provenance or authority records."""

    def __init__(self, *, plan: ConfiguredCandidatePlan, contract):
        if plan.decision_id != contract.id:
            raise ValueError("candidate plan decision does not match contract")
        self.plan = plan
        self.contract = contract

    def compile_observable(self, *, observable, profile) -> CandidateBundle:
        if observable.decision_id != self.plan.decision_id:
            raise ValueError("candidate plan does not match observable decision")
        sources = observable.source_map()
        capture_slots = {item.slot.id for item in profile.slots}
        resolved_entities = set()
        candidates = []
        for index, spec in enumerate(self.plan.candidates):
            source = sources.get(spec.source_id)
            if source is None:
                raise ValueError("configured candidate references unknown source")
            start = source.content.find(spec.exact_quote)
            if start < 0 or source.content.find(spec.exact_quote, start + 1) >= 0:
                raise ValueError("configured quote must occur exactly once in its source")
            candidate = GroundedCandidate(
                f"CONFIGURED-{index}", spec.semantic_key, spec.candidate_kind,
                spec.source_id, start, start + len(spec.exact_quote),
            )
            resolved = SemanticCandidateResolver().resolve(
                candidate=candidate, contract=self.contract, profile=profile,
            )
            if resolved.entity_id in capture_slots:
                raise ValueError("configured candidates cannot fill a human capture slot")
            if resolved.entity_id in resolved_entities:
                raise ValueError("configured candidates must resolve to distinct entities")
            resolved_entities.add(resolved.entity_id)
            candidates.append(candidate)
        expected = ({item.id for item in self.contract.claims}
                    | {item.id for item in self.contract.historical_relations}) - capture_slots
        if resolved_entities != expected:
            raise ValueError("configured candidates must cover the bounded pre-capture surface")
        return CandidateBundle(tuple(candidates))

    def compile_response(self, **kwargs):
        raise ValueError("human responses require the structured capture path")
