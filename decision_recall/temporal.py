from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from math import isfinite
from typing import Iterable, Mapping, Optional, Sequence, Tuple, Union

from .domain import (
    CanonicalWorldState,
    CompositionValue,
    HistoricalKnowledgeState,
    MetricSpec,
    NumericObservation,
    ProvenanceType,
)


class TemporalIntegrityError(ValueError):
    """Raised when a temporal/authority invariant would be violated."""


class TemporalReferenceKind(str, Enum):
    POINT = "point"
    INTERVAL = "interval"


@dataclass(frozen=True)
class TemporalReference:
    kind: TemporalReferenceKind
    observed_at: Optional[datetime] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None

    @classmethod
    def point(cls, observed_at: datetime) -> "TemporalReference":
        return cls(kind=TemporalReferenceKind.POINT, observed_at=observed_at)

    @classmethod
    def interval(cls, valid_from: datetime, valid_to: datetime) -> "TemporalReference":
        return cls(
            kind=TemporalReferenceKind.INTERVAL,
            valid_from=valid_from,
            valid_to=valid_to,
        )

    def validate(self) -> None:
        if self.kind is TemporalReferenceKind.POINT:
            if self.observed_at is None or self.valid_from is not None or self.valid_to is not None:
                raise TemporalIntegrityError("POINT temporal reference requires only observed_at")
            _require_aware(self.observed_at, "observed_at")
            return
        if self.kind is TemporalReferenceKind.INTERVAL:
            if self.observed_at is not None or self.valid_from is None or self.valid_to is None:
                raise TemporalIntegrityError("INTERVAL temporal reference requires valid_from/valid_to")
            _require_aware(self.valid_from, "valid_from")
            _require_aware(self.valid_to, "valid_to")
            if self.valid_to < self.valid_from:
                raise TemporalIntegrityError("temporal interval cannot end before it starts")
            return
        raise TemporalIntegrityError("unsupported temporal reference kind")

    def effective_at(self) -> datetime:
        self.validate()
        if self.kind is TemporalReferenceKind.POINT:
            assert self.observed_at is not None
            return self.observed_at
        assert self.valid_to is not None
        return self.valid_to


class AuthorizedAssertion(str, Enum):
    ESTABLISHED_FACT = "established_fact"
    ESTABLISHED_HISTORICAL_ROLE = "established_historical_role"
    COMPOSITION_TRUE = "composition_true"
    COMPOSITION_FALSE = "composition_false"
    T0_UNRESOLVED = "t0_unresolved"
    CURRENT_MATCH_RULE = "current_match_rule"
    REVISIT_RULE = "revisit_rule"
    WORLD_EVENT = "world_event"


class LedgerEntryKind(str, Enum):
    EVIDENCE = "evidence"
    AUTHORIZATION = "authorization"
    DECISION_COMMIT = "decision_commit"
    EVALUATION = "evaluation"
    RAW_WORLD_EVIDENCE = "raw_world_evidence"
    CORRECTION = "correction"


@dataclass(frozen=True)
class CandidateAssertion:
    entity_id: str
    assertion: AuthorizedAssertion


@dataclass(frozen=True)
class TemporalEvidenceRecord:
    id: str
    content: str
    source_id: str
    source_span: str
    source_content_hash: str
    provenance_type: ProvenanceType
    temporal_reference: TemporalReference
    candidate_assertions: Tuple[CandidateAssertion, ...] = ()

    def validate(self) -> None:
        if not self.id.strip():
            raise TemporalIntegrityError("evidence id is required")
        if not self.content.strip():
            raise TemporalIntegrityError("evidence content must be non-empty")
        if not self.source_id.strip():
            raise TemporalIntegrityError("source_id is required")
        if not self.source_span.strip():
            raise TemporalIntegrityError("source_span is required")
        if not self.source_content_hash.strip():
            raise TemporalIntegrityError("source_content_hash is required")
        self.temporal_reference.validate()
        assertion_keys = tuple((item.entity_id, item.assertion) for item in self.candidate_assertions)
        if len(assertion_keys) != len(set(assertion_keys)):
            raise TemporalIntegrityError("duplicate candidate assertion in evidence")


@dataclass(frozen=True)
class AuthorizationRecord:
    id: str
    entity_id: str
    authorized_assertion: AuthorizedAssertion
    evidence_ids: Tuple[str, ...]
    policy_version: str
    policy_hash: str

    def validate(self) -> None:
        if not self.id.strip() or not self.entity_id.strip():
            raise TemporalIntegrityError("authorization id/entity_id are required")
        if not self.evidence_ids:
            raise TemporalIntegrityError("authorization requires evidence")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise TemporalIntegrityError("authorization evidence ids must be unique")
        if not self.policy_version.strip() or not self.policy_hash.strip():
            raise TemporalIntegrityError("authorization requires policy version/hash")


@dataclass(frozen=True)
class DecisionCommitRecord:
    id: str
    decision_id: str
    contract_version: str
    capture_profile_version: str
    capture_profile_hash: str


@dataclass(frozen=True)
class EvaluationSnapshot:
    id: str
    decision_id: str
    input_cutoff_seq: int
    target_version: str
    target_hash: str
    evidence_policy_version: str
    evidence_policy_hash: str
    event_policy_version: str
    event_policy_hash: str
    engine_version: str
    engine_hash: str
    result_fingerprint: str


@dataclass(frozen=True)
class RawWorldEvidence:
    id: str
    content: str
    source_id: str
    source_span: str
    source_content_hash: str
    provenance_type: ProvenanceType
    temporal_reference: TemporalReference
    observations: Tuple[NumericObservation, ...]

    def validate(self) -> None:
        if not self.id.strip() or not self.content.strip():
            raise TemporalIntegrityError("world evidence id/content are required")
        if not self.source_id.strip() or not self.source_span.strip() or not self.source_content_hash.strip():
            raise TemporalIntegrityError("world evidence source lineage is required")
        self.temporal_reference.validate()
        keys = tuple(obs.metric_key for obs in self.observations)
        if len(keys) != len(set(keys)):
            raise TemporalIntegrityError("raw world evidence has duplicate metric keys")


@dataclass(frozen=True)
class CorrectionRecord:
    id: str
    corrects_entry_id: str
    reason: str


LedgerPayload = Union[
    TemporalEvidenceRecord,
    AuthorizationRecord,
    DecisionCommitRecord,
    EvaluationSnapshot,
    RawWorldEvidence,
    CorrectionRecord,
]


@dataclass(frozen=True)
class PendingLedgerEntry:
    kind: LedgerEntryKind
    payload: LedgerPayload


@dataclass(frozen=True)
class LedgerEntry:
    batch_seq: int
    entry_ordinal: int
    entry_id: str
    kind: LedgerEntryKind
    recorded_at: datetime
    payload: LedgerPayload


@dataclass(frozen=True)
class LedgerBatch:
    batch_seq: int
    recorded_at: datetime
    entries: Tuple[LedgerEntry, ...]


class InMemoryTemporalLedger:
    """Append-only batch ledger used to freeze M2 semantics before PostgreSQL.

    A cutoff is always a batch_seq. There is intentionally no supported view that
    cuts through the middle of a batch, so evidence + authorization + commit can be
    one atomic semantic operation.
    """

    def __init__(self) -> None:
        self._batches: list[LedgerBatch] = []
        self._entry_ids: set[str] = set()

    @property
    def head_seq(self) -> int:
        return self._batches[-1].batch_seq if self._batches else 0

    def append_batch(
        self,
        *,
        recorded_at: datetime,
        entries: Sequence[PendingLedgerEntry],
    ) -> LedgerBatch:
        _require_aware(recorded_at, "recorded_at")
        if not entries:
            raise TemporalIntegrityError("ledger batch cannot be empty")

        # Validate everything before mutation to preserve atomicity in memory.
        local_ids: set[str] = set()
        for pending in entries:
            entry_id = _payload_id(pending.payload)
            if entry_id in self._entry_ids or entry_id in local_ids:
                raise TemporalIntegrityError(f"duplicate ledger entry id: {entry_id}")
            local_ids.add(entry_id)
            _validate_payload(pending.kind, pending.payload)

        batch_seq = self.head_seq + 1
        ledger_entries = tuple(
            LedgerEntry(
                batch_seq=batch_seq,
                entry_ordinal=index,
                entry_id=_payload_id(pending.payload),
                kind=pending.kind,
                recorded_at=recorded_at,
                payload=pending.payload,
            )
            for index, pending in enumerate(entries, start=1)
        )
        batch = LedgerBatch(batch_seq=batch_seq, recorded_at=recorded_at, entries=ledger_entries)
        self._batches.append(batch)
        self._entry_ids.update(local_ids)
        return batch

    def entries_as_of(self, cutoff_seq: int) -> Tuple[LedgerEntry, ...]:
        if cutoff_seq < 0 or cutoff_seq > self.head_seq:
            raise TemporalIntegrityError("cutoff_seq is outside the ledger")
        return tuple(
            entry
            for batch in self._batches
            if batch.batch_seq <= cutoff_seq
            for entry in batch.entries
        )

    def entry(self, entry_id: str) -> LedgerEntry:
        for batch in self._batches:
            for entry in batch.entries:
                if entry.entry_id == entry_id:
                    return entry
        raise KeyError(entry_id)


@dataclass(frozen=True)
class AuthorityPolicy:
    version: str
    policy_hash: str
    allowed_provenance: Mapping[AuthorizedAssertion, Tuple[ProvenanceType, ...]]

    def authorize_candidate(
        self,
        *,
        evidence: TemporalEvidenceRecord,
        candidate: CandidateAssertion,
        authorization_id: str,
    ) -> AuthorizationRecord:
        evidence.validate()
        if candidate not in evidence.candidate_assertions:
            raise TemporalIntegrityError("candidate assertion is not grounded in this evidence")
        allowed = self.allowed_provenance.get(candidate.assertion, ())
        if evidence.provenance_type not in allowed:
            raise TemporalIntegrityError("evidence provenance is not authorized for assertion")
        return AuthorizationRecord(
            id=authorization_id,
            entity_id=candidate.entity_id,
            authorized_assertion=candidate.assertion,
            evidence_ids=(evidence.id,),
            policy_version=self.version,
            policy_hash=self.policy_hash,
        )


@dataclass(frozen=True)
class EventPolicy:
    version: str
    policy_hash: str
    allowed_provenance: Tuple[ProvenanceType, ...]

    def authorize(
        self,
        *,
        raw: RawWorldEvidence,
        metric_specs: Mapping[str, MetricSpec],
    ) -> "AuthorizedWorldEvent":
        raw.validate()
        if raw.provenance_type not in self.allowed_provenance:
            raise TemporalIntegrityError("world evidence provenance is not authorized")
        _validate_world_observations(raw.observations, metric_specs)
        return AuthorizedWorldEvent(
            id=f"AUTH-WORLD-{raw.id}",
            raw_evidence_id=raw.id,
            observations=tuple(raw.observations),
            temporal_reference=raw.temporal_reference,
            policy_version=self.version,
            policy_hash=self.policy_hash,
        )


@dataclass(frozen=True)
class AuthorizedWorldEvent:
    id: str
    raw_evidence_id: str
    observations: Tuple[NumericObservation, ...]
    temporal_reference: TemporalReference
    policy_version: str
    policy_hash: str


@dataclass(frozen=True)
class RecordedHistoricalView:
    cutoff_seq: int
    assertions: Tuple[Tuple[str, AuthorizedAssertion], ...]

    def assertions_for(self, entity_id: str) -> Tuple[AuthorizedAssertion, ...]:
        return tuple(assertion for entity, assertion in self.assertions if entity == entity_id)

    def relation_state(self, entity_id: str) -> HistoricalKnowledgeState:
        assertions = self.assertions_for(entity_id)
        if AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE in assertions:
            return HistoricalKnowledgeState.ESTABLISHED
        if AuthorizedAssertion.T0_UNRESOLVED in assertions:
            return HistoricalKnowledgeState.T0_UNRESOLVED
        return HistoricalKnowledgeState.NOT_DURABLY_RECORDED

    def composition_state(self, entity_id: str) -> CompositionValue:
        assertions = self.assertions_for(entity_id)
        if AuthorizedAssertion.COMPOSITION_TRUE in assertions:
            return CompositionValue.ESTABLISHED_TRUE
        if AuthorizedAssertion.COMPOSITION_FALSE in assertions:
            return CompositionValue.ESTABLISHED_FALSE
        if AuthorizedAssertion.T0_UNRESOLVED in assertions:
            return CompositionValue.T0_UNRESOLVED
        return CompositionValue.NOT_DURABLY_RECORDED


def recorded_historical_view(
    ledger: InMemoryTemporalLedger,
    *,
    cutoff_seq: int,
) -> RecordedHistoricalView:
    entries = ledger.entries_as_of(cutoff_seq)
    evidence_by_id = {
        entry.entry_id: entry
        for entry in entries
        if entry.kind is LedgerEntryKind.EVIDENCE
    }
    assertions: list[Tuple[str, AuthorizedAssertion]] = []
    for entry in entries:
        if entry.kind is not LedgerEntryKind.AUTHORIZATION:
            continue
        auth = entry.payload
        assert isinstance(auth, AuthorizationRecord)
        auth.validate()
        for evidence_id in auth.evidence_ids:
            evidence_entry = evidence_by_id.get(evidence_id)
            if evidence_entry is None:
                raise TemporalIntegrityError(
                    "authorization is visible before its evidence in the same as-of view"
                )
            evidence = evidence_entry.payload
            assert isinstance(evidence, TemporalEvidenceRecord)
            expected = CandidateAssertion(auth.entity_id, auth.authorized_assertion)
            if expected not in evidence.candidate_assertions:
                raise TemporalIntegrityError("authorization assertion is not grounded by cited evidence")
        assertions.append((auth.entity_id, auth.authorized_assertion))
    return RecordedHistoricalView(cutoff_seq=cutoff_seq, assertions=tuple(sorted(assertions)))


def current_assessment_candidates_about(
    ledger: InMemoryTemporalLedger,
    *,
    entity_id: str,
    cutoff_seq: int,
) -> Tuple[Tuple[str, CandidateAssertion, ProvenanceType], ...]:
    """Evidence visible now about an entity, without rewriting the recorded t0 view."""
    results = []
    for entry in ledger.entries_as_of(cutoff_seq):
        if entry.kind is not LedgerEntryKind.EVIDENCE:
            continue
        evidence = entry.payload
        assert isinstance(evidence, TemporalEvidenceRecord)
        for candidate in evidence.candidate_assertions:
            if candidate.entity_id == entity_id:
                results.append((evidence.id, candidate, evidence.provenance_type))
    return tuple(results)


def replay_authority_from_evidence(
    ledger: InMemoryTemporalLedger,
    *,
    input_cutoff_seq: int,
    policy: AuthorityPolicy,
) -> Tuple[Tuple[str, AuthorizedAssertion], ...]:
    """Deterministically recompute evaluation-time authority from available evidence.

    The generated authorizations are evaluation outputs; they need not pre-exist the
    input cutoff. Only their input evidence must be visible by input_cutoff_seq.
    """
    authorized: list[Tuple[str, AuthorizedAssertion]] = []
    for entry in ledger.entries_as_of(input_cutoff_seq):
        if entry.kind is not LedgerEntryKind.EVIDENCE:
            continue
        evidence = entry.payload
        assert isinstance(evidence, TemporalEvidenceRecord)
        for index, candidate in enumerate(evidence.candidate_assertions, start=1):
            try:
                policy.authorize_candidate(
                    evidence=evidence,
                    candidate=candidate,
                    authorization_id=f"REPLAY-{evidence.id}-{index}",
                )
            except TemporalIntegrityError:
                continue
            authorized.append((candidate.entity_id, candidate.assertion))
    return tuple(sorted(set(authorized)))


def authorized_world_state_as_of(
    ledger: InMemoryTemporalLedger,
    *,
    cutoff_seq: int,
    policy: EventPolicy,
    metric_specs: Mapping[str, MetricSpec],
) -> CanonicalWorldState:
    """Build a deterministic current-world view from raw evidence visible at cutoff.

    V1 precedence: for each metric choose the authorized observation whose temporal
    reference has the latest effective time; break exact temporal ties by later
    ledger batch/ordinal. Late-arriving older evidence therefore does not overwrite a
    newer-world observation merely because it was ingested later.
    """
    chosen: dict[str, tuple[datetime, int, int, NumericObservation, str]] = {}
    for entry in ledger.entries_as_of(cutoff_seq):
        if entry.kind is not LedgerEntryKind.RAW_WORLD_EVIDENCE:
            continue
        raw = entry.payload
        assert isinstance(raw, RawWorldEvidence)
        try:
            event = policy.authorize(raw=raw, metric_specs=metric_specs)
        except TemporalIntegrityError:
            continue
        effective_at = event.temporal_reference.effective_at()
        for observation in event.observations:
            candidate_key = (effective_at, entry.batch_seq, entry.entry_ordinal)
            previous = chosen.get(observation.metric_key)
            if previous is None or candidate_key > previous[:3]:
                chosen[observation.metric_key] = (
                    effective_at,
                    entry.batch_seq,
                    entry.entry_ordinal,
                    NumericObservation(
                        metric_key=observation.metric_key,
                        value=observation.value,
                        unit=observation.unit,
                        window_days=observation.window_days,
                        source_event_id=event.id,
                    ),
                    raw.id,
                )
    return CanonicalWorldState(
        observations=tuple(chosen[key][3] for key in sorted(chosen))
    )


def canonical_replay_fingerprint(
    *,
    ledger: InMemoryTemporalLedger,
    input_cutoff_seq: int,
    authority_policy: AuthorityPolicy,
    target_version: str,
    target_hash: str,
    engine_version: str,
    engine_hash: str,
) -> str:
    payload = {
        "cutoff": input_cutoff_seq,
        "authority": replay_authority_from_evidence(
            ledger,
            input_cutoff_seq=input_cutoff_seq,
            policy=authority_policy,
        ),
        "policy_version": authority_policy.version,
        "policy_hash": authority_policy.policy_hash,
        "target_version": target_version,
        "target_hash": target_hash,
        "engine_version": engine_version,
        "engine_hash": engine_hash,
    }
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def authority_policy_v1() -> AuthorityPolicy:
    return AuthorityPolicy(
        version="AUTHORITY_V1",
        policy_hash=_stable_hash(
            {
                "historical_role": [
                    ProvenanceType.CONTEMPORANEOUS_RECORD.value,
                    ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION.value,
                ],
                "t0_unresolved": [
                    ProvenanceType.CONTEMPORANEOUS_RECORD.value,
                    ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION.value,
                ],
                "composition": [
                    ProvenanceType.CONTEMPORANEOUS_RECORD.value,
                    ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION.value,
                ],
            }
        ),
        allowed_provenance={
            AuthorizedAssertion.ESTABLISHED_FACT: (
                ProvenanceType.CONTEMPORANEOUS_RECORD,
                ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION,
            ),
            AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE: (
                ProvenanceType.CONTEMPORANEOUS_RECORD,
                ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION,
            ),
            AuthorizedAssertion.COMPOSITION_TRUE: (
                ProvenanceType.CONTEMPORANEOUS_RECORD,
                ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION,
            ),
            AuthorizedAssertion.COMPOSITION_FALSE: (
                ProvenanceType.CONTEMPORANEOUS_RECORD,
                ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION,
            ),
            AuthorizedAssertion.T0_UNRESOLVED: (
                ProvenanceType.CONTEMPORANEOUS_RECORD,
                ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION,
            ),
            AuthorizedAssertion.CURRENT_MATCH_RULE: (
                ProvenanceType.CONTEMPORANEOUS_RECORD,
                ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION,
            ),
            AuthorizedAssertion.REVISIT_RULE: (
                ProvenanceType.CONTEMPORANEOUS_RECORD,
                ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION,
            ),
        },
    )


def event_policy_v1() -> EventPolicy:
    config = {
        "allowed": [ProvenanceType.CONTEMPORANEOUS_RECORD.value],
        "precedence": "latest_temporal_reference_then_ledger_order",
    }
    return EventPolicy(
        version="EVENT_V1",
        policy_hash=_stable_hash(config),
        allowed_provenance=(ProvenanceType.CONTEMPORANEOUS_RECORD,),
    )


def source_hash(content: str) -> str:
    return sha256(content.encode()).hexdigest()


def _stable_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TemporalIntegrityError(f"{name} must be timezone-aware")


def _payload_id(payload: LedgerPayload) -> str:
    return payload.id


def _validate_payload(kind: LedgerEntryKind, payload: LedgerPayload) -> None:
    expected = {
        LedgerEntryKind.EVIDENCE: TemporalEvidenceRecord,
        LedgerEntryKind.AUTHORIZATION: AuthorizationRecord,
        LedgerEntryKind.DECISION_COMMIT: DecisionCommitRecord,
        LedgerEntryKind.EVALUATION: EvaluationSnapshot,
        LedgerEntryKind.RAW_WORLD_EVIDENCE: RawWorldEvidence,
        LedgerEntryKind.CORRECTION: CorrectionRecord,
    }[kind]
    if not isinstance(payload, expected):
        raise TemporalIntegrityError(f"ledger kind {kind.value} payload type mismatch")
    if isinstance(payload, TemporalEvidenceRecord):
        payload.validate()
    elif isinstance(payload, AuthorizationRecord):
        payload.validate()
    elif isinstance(payload, RawWorldEvidence):
        payload.validate()
    elif isinstance(payload, DecisionCommitRecord):
        if not payload.id.strip() or not payload.decision_id.strip():
            raise TemporalIntegrityError("decision commit ids are required")
        if not payload.contract_version.strip():
            raise TemporalIntegrityError("decision commit requires contract version")
        if not payload.capture_profile_version.strip() or not payload.capture_profile_hash.strip():
            raise TemporalIntegrityError("decision commit requires CaptureProfile version/hash")
    elif isinstance(payload, EvaluationSnapshot):
        if payload.input_cutoff_seq < 0:
            raise TemporalIntegrityError("evaluation cutoff cannot be negative")
        required = (
            payload.target_version,
            payload.target_hash,
            payload.evidence_policy_version,
            payload.evidence_policy_hash,
            payload.event_policy_version,
            payload.event_policy_hash,
            payload.engine_version,
            payload.engine_hash,
            payload.result_fingerprint,
        )
        if any(not item.strip() for item in required):
            raise TemporalIntegrityError("evaluation snapshot requires version/hash fields")
    elif isinstance(payload, CorrectionRecord):
        if not payload.id.strip() or not payload.corrects_entry_id.strip() or not payload.reason.strip():
            raise TemporalIntegrityError("correction requires id, target and reason")


def _validate_world_observations(
    observations: Iterable[NumericObservation],
    metric_specs: Mapping[str, MetricSpec],
) -> None:
    seen: set[str] = set()
    for observation in observations:
        if observation.metric_key in seen:
            raise TemporalIntegrityError("duplicate metric in world evidence")
        seen.add(observation.metric_key)
        spec = metric_specs.get(observation.metric_key)
        if spec is None:
            raise TemporalIntegrityError(f"unknown metric: {observation.metric_key}")
        if observation.unit != spec.unit:
            raise TemporalIntegrityError("world observation unit mismatch")
        if not isfinite(observation.value):
            raise TemporalIntegrityError("world observation must be finite")
        if spec.minimum is not None and observation.value < spec.minimum:
            raise TemporalIntegrityError("world observation below allowed range")
        if spec.maximum is not None and observation.value > spec.maximum:
            raise TemporalIntegrityError("world observation above allowed range")
        if observation.window_days is not None and observation.window_days < 0:
            raise TemporalIntegrityError("world observation window_days cannot be negative")
