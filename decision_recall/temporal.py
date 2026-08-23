from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    """Raised when a temporal, authority, or replay invariant would be violated."""


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


class LedgerEntryKind(str, Enum):
    EVIDENCE = "evidence"
    AUTHORIZATION = "authorization"
    DECISION_COMMIT = "decision_commit"
    EVALUATION = "evaluation"
    RAW_WORLD_EVIDENCE = "raw_world_evidence"
    WORLD_EVENT_AUTHORIZATION = "world_event_authorization"
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
        keys = tuple((item.entity_id, item.assertion) for item in self.candidate_assertions)
        if any(not item.entity_id.strip() for item in self.candidate_assertions):
            raise TemporalIntegrityError("candidate assertion entity_id is required")
        if len(keys) != len(set(keys)):
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
        if not self.observations:
            raise TemporalIntegrityError("world evidence requires at least one observation")
        if len(keys) != len(set(keys)):
            raise TemporalIntegrityError("raw world evidence has duplicate metric keys")


@dataclass(frozen=True)
class WorldEventAuthorizationRecord:
    id: str
    raw_evidence_id: str
    event_id: str
    policy_version: str
    policy_hash: str

    def validate(self) -> None:
        fields = (
            self.id,
            self.raw_evidence_id,
            self.event_id,
            self.policy_version,
            self.policy_hash,
        )
        if any(not item.strip() for item in fields):
            raise TemporalIntegrityError("world-event authorization fields are required")


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
    WorldEventAuthorizationRecord,
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
    """Append-only atomic-batch ledger used to freeze M2 semantics before PostgreSQL.

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

        local_ids: set[str] = set()
        for pending in entries:
            entry_id = _payload_id(pending.payload)
            if entry_id in self._entry_ids or entry_id in local_ids:
                raise TemporalIntegrityError(f"duplicate ledger entry id: {entry_id}")
            local_ids.add(entry_id)
            _validate_payload(pending.kind, pending.payload)

        existing_by_id = {entry.entry_id: entry for entry in self.entries_as_of(self.head_seq)}
        local_by_id = {_payload_id(item.payload): item for item in entries}
        visible_ids = set(existing_by_id) | set(local_by_id)

        for pending in entries:
            payload = pending.payload
            if isinstance(payload, AuthorizationRecord):
                if any(evidence_id not in visible_ids for evidence_id in payload.evidence_ids):
                    raise TemporalIntegrityError("authorization references unavailable evidence")
                for evidence_id in payload.evidence_ids:
                    referenced = local_by_id.get(evidence_id)
                    if referenced is not None and referenced.kind is not LedgerEntryKind.EVIDENCE:
                        raise TemporalIntegrityError("authorization evidence ref is not an evidence record")
                    existing = existing_by_id.get(evidence_id)
                    if existing is not None and existing.kind is not LedgerEntryKind.EVIDENCE:
                        raise TemporalIntegrityError("authorization evidence ref is not an evidence record")
            elif isinstance(payload, WorldEventAuthorizationRecord):
                if payload.raw_evidence_id not in visible_ids:
                    raise TemporalIntegrityError("world authorization references unavailable raw evidence")
                referenced = local_by_id.get(payload.raw_evidence_id)
                if referenced is not None and referenced.kind is not LedgerEntryKind.RAW_WORLD_EVIDENCE:
                    raise TemporalIntegrityError("world authorization raw ref has wrong kind")
                existing = existing_by_id.get(payload.raw_evidence_id)
                if existing is not None and existing.kind is not LedgerEntryKind.RAW_WORLD_EVIDENCE:
                    raise TemporalIntegrityError("world authorization raw ref has wrong kind")
            elif isinstance(payload, CorrectionRecord):
                # Corrections are about already-recorded history; they cannot correct
                # a sibling entry that did not exist before this atomic batch.
                if payload.corrects_entry_id not in existing_by_id:
                    raise TemporalIntegrityError("correction target must pre-exist this batch")
                if existing_by_id[payload.corrects_entry_id].kind is LedgerEntryKind.CORRECTION:
                    raise TemporalIntegrityError("V1 does not support correction-of-correction")
            elif isinstance(payload, EvaluationSnapshot):
                # Evaluation inputs are frozen before the output batch starts.
                if payload.input_cutoff_seq > self.head_seq:
                    raise TemporalIntegrityError("evaluation input cutoff cannot include its own output batch")

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

    def effective_entries_as_of(self, cutoff_seq: int) -> Tuple[LedgerEntry, ...]:
        entries = self.entries_as_of(cutoff_seq)
        corrected_ids = {
            entry.payload.corrects_entry_id
            for entry in entries
            if entry.kind is LedgerEntryKind.CORRECTION
            and isinstance(entry.payload, CorrectionRecord)
        }
        return tuple(
            entry
            for entry in entries
            if entry.entry_id not in corrected_ids
            and entry.kind is not LedgerEntryKind.CORRECTION
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
        authorization_id: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> WorldEventAuthorizationRecord:
        raw.validate()
        if raw.provenance_type not in self.allowed_provenance:
            raise TemporalIntegrityError("world evidence provenance is not authorized")
        _validate_world_observations(raw.observations, metric_specs)
        return WorldEventAuthorizationRecord(
            id=authorization_id or f"AUTH-WORLD-{raw.id}",
            raw_evidence_id=raw.id,
            event_id=event_id or f"WORLD-{raw.id}",
            policy_version=self.version,
            policy_hash=self.policy_hash,
        )


@dataclass(frozen=True)
class RecordedHistoricalView:
    cutoff_seq: int
    assertions: Tuple[Tuple[str, AuthorizedAssertion], ...]

    def assertions_for(self, entity_id: str) -> Tuple[AuthorizedAssertion, ...]:
        return tuple(assertion for entity, assertion in self.assertions if entity == entity_id)

    def relation_state(self, entity_id: str) -> HistoricalKnowledgeState:
        assertions = self.assertions_for(entity_id)
        _reject_conflicting_history(entity_id, assertions)
        if AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE in assertions:
            return HistoricalKnowledgeState.ESTABLISHED
        if AuthorizedAssertion.T0_UNRESOLVED in assertions:
            return HistoricalKnowledgeState.T0_UNRESOLVED
        return HistoricalKnowledgeState.NOT_DURABLY_RECORDED

    def composition_state(self, entity_id: str) -> CompositionValue:
        assertions = self.assertions_for(entity_id)
        _reject_conflicting_history(entity_id, assertions)
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
    policies: Mapping[Tuple[str, str], AuthorityPolicy],
) -> RecordedHistoricalView:
    entries = ledger.effective_entries_as_of(cutoff_seq)
    evidence_by_id = {
        entry.entry_id: entry.payload
        for entry in entries
        if entry.kind is LedgerEntryKind.EVIDENCE
        and isinstance(entry.payload, TemporalEvidenceRecord)
    }
    assertions: list[Tuple[str, AuthorizedAssertion]] = []
    for entry in entries:
        if entry.kind is not LedgerEntryKind.AUTHORIZATION:
            continue
        auth = entry.payload
        assert isinstance(auth, AuthorizationRecord)
        auth.validate()
        policy = policies.get((auth.policy_version, auth.policy_hash))
        if policy is None:
            raise TemporalIntegrityError("authorization references unknown policy version/hash")
        candidate = CandidateAssertion(auth.entity_id, auth.authorized_assertion)
        for evidence_id in auth.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                raise TemporalIntegrityError("authorization is visible without its evidence in as-of view")
            # Re-check that the persisted authorization is exactly reproducible under
            # the referenced policy; metadata alone cannot establish authority.
            replayed = policy.authorize_candidate(
                evidence=evidence,
                candidate=candidate,
                authorization_id=auth.id,
            )
            if (
                replayed.entity_id != auth.entity_id
                or replayed.authorized_assertion is not auth.authorized_assertion
                or replayed.policy_version != auth.policy_version
                or replayed.policy_hash != auth.policy_hash
            ):
                raise TemporalIntegrityError("persisted authorization does not replay")
        assertions.append((auth.entity_id, auth.authorized_assertion))
    return RecordedHistoricalView(
        cutoff_seq=cutoff_seq,
        assertions=tuple(sorted(set(assertions), key=lambda item: (item[0], item[1].value))),
    )


def current_assessment_candidates_about(
    ledger: InMemoryTemporalLedger,
    *,
    entity_id: str,
    cutoff_seq: int,
) -> Tuple[Tuple[str, CandidateAssertion, ProvenanceType], ...]:
    """Evidence visible now about an entity, without rewriting the recorded t0 view."""
    results = []
    for entry in ledger.effective_entries_as_of(cutoff_seq):
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

    These are evaluation outputs; they need not pre-exist the input cutoff. Only the
    input evidence must be visible by input_cutoff_seq.
    """
    authorized: list[Tuple[str, AuthorizedAssertion]] = []
    for entry in ledger.effective_entries_as_of(input_cutoff_seq):
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
    return tuple(sorted(set(authorized), key=lambda item: (item[0], item[1].value)))


def authorized_world_state_as_of(
    ledger: InMemoryTemporalLedger,
    *,
    cutoff_seq: int,
    policies: Mapping[Tuple[str, str], EventPolicy],
    metric_specs: Mapping[str, MetricSpec],
) -> CanonicalWorldState:
    """Build current-world view only from raw evidence with visible first-class auth.

    V1 precedence: for each metric choose the authorized observation whose temporal
    reference has the latest effective time; break exact temporal ties by later
    ledger batch/ordinal. Late-arriving older evidence therefore cannot overwrite a
    newer-world observation merely because it was ingested later.
    """
    entries = ledger.effective_entries_as_of(cutoff_seq)
    raw_by_id = {
        entry.entry_id: entry
        for entry in entries
        if entry.kind is LedgerEntryKind.RAW_WORLD_EVIDENCE
    }
    authorizations = [
        entry
        for entry in entries
        if entry.kind is LedgerEntryKind.WORLD_EVENT_AUTHORIZATION
    ]
    chosen: dict[str, tuple[datetime, int, int, NumericObservation]] = {}
    seen_raw_auth: set[str] = set()
    for auth_entry in authorizations:
        auth = auth_entry.payload
        assert isinstance(auth, WorldEventAuthorizationRecord)
        auth.validate()
        if auth.raw_evidence_id in seen_raw_auth:
            raise TemporalIntegrityError("multiple active world authorizations for same raw evidence")
        seen_raw_auth.add(auth.raw_evidence_id)
        raw_entry = raw_by_id.get(auth.raw_evidence_id)
        if raw_entry is None:
            raise TemporalIntegrityError("world authorization visible without raw evidence")
        raw = raw_entry.payload
        assert isinstance(raw, RawWorldEvidence)
        policy = policies.get((auth.policy_version, auth.policy_hash))
        if policy is None:
            raise TemporalIntegrityError("world authorization references unknown policy version/hash")
        replayed = policy.authorize(
            raw=raw,
            metric_specs=metric_specs,
            authorization_id=auth.id,
            event_id=auth.event_id,
        )
        if replayed != auth:
            raise TemporalIntegrityError("persisted world authorization does not replay")
        effective_at = raw.temporal_reference.effective_at()
        for observation in raw.observations:
            candidate_key = (effective_at, auth_entry.batch_seq, auth_entry.entry_ordinal)
            previous = chosen.get(observation.metric_key)
            if previous is None or candidate_key > previous[:3]:
                chosen[observation.metric_key] = (
                    effective_at,
                    auth_entry.batch_seq,
                    auth_entry.entry_ordinal,
                    NumericObservation(
                        metric_key=observation.metric_key,
                        value=observation.value,
                        unit=observation.unit,
                        window_days=observation.window_days,
                        source_event_id=auth.event_id,
                    ),
                )
    return CanonicalWorldState(observations=tuple(chosen[key][3] for key in sorted(chosen)))


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
    allowed = {
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
    }
    config = {
        assertion.value: sorted(provenance.value for provenance in provenances)
        for assertion, provenances in allowed.items()
    }
    return AuthorityPolicy(
        version="AUTHORITY_V1",
        policy_hash=_stable_hash(config),
        allowed_provenance=allowed,
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
        LedgerEntryKind.WORLD_EVENT_AUTHORIZATION: WorldEventAuthorizationRecord,
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
    elif isinstance(payload, WorldEventAuthorizationRecord):
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


def _reject_conflicting_history(
    entity_id: str,
    assertions: Tuple[AuthorizedAssertion, ...],
) -> None:
    incompatible_groups = (
        {
            AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
            AuthorizedAssertion.T0_UNRESOLVED,
        },
        {
            AuthorizedAssertion.COMPOSITION_TRUE,
            AuthorizedAssertion.COMPOSITION_FALSE,
            AuthorizedAssertion.T0_UNRESOLVED,
        },
    )
    present = set(assertions)
    for group in incompatible_groups:
        if len(group & present) > 1:
            raise TemporalIntegrityError(f"conflicting historical assertions for {entity_id}")
