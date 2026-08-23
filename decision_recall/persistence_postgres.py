from __future__ import annotations

from datetime import datetime
from typing import Sequence, Tuple

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Connection, Engine

from .domain import NumericObservation, ProvenanceType
from .temporal import (
    AuthorizationRecord,
    AuthorizedAssertion,
    CandidateAssertion,
    CorrectionRecord,
    DecisionCommitRecord,
    EvaluationSnapshot,
    LedgerBatch,
    LedgerEntry,
    LedgerEntryKind,
    PendingLedgerEntry,
    RawWorldEvidence,
    TemporalEvidenceRecord,
    TemporalIntegrityError,
    TemporalReference,
    TemporalReferenceKind,
    WorldEventAuthorizationRecord,
    _require_aware,
    _validate_payload,
)


metadata = MetaData()

ledger_head = Table(
    "dr_ledger_head",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("last_batch_seq", BigInteger, nullable=False),
)

ledger_batches = Table(
    "dr_ledger_batches",
    metadata,
    Column("batch_seq", BigInteger, primary_key=True),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
)

ledger_entries = Table(
    "dr_ledger_entries",
    metadata,
    Column("entry_id", String(200), primary_key=True),
    Column("batch_seq", BigInteger, ForeignKey("dr_ledger_batches.batch_seq"), nullable=False, index=True),
    Column("entry_ordinal", Integer, nullable=False),
    Column("kind", String(64), nullable=False),
    UniqueConstraint("batch_seq", "entry_ordinal", name="uq_dr_ledger_batch_ordinal"),
)

evidence_records = Table(
    "dr_evidence_records",
    metadata,
    Column("id", String(200), primary_key=True),
    Column("content", Text, nullable=False),
    Column("source_id", String(500), nullable=False),
    Column("source_span", Text, nullable=False),
    Column("source_content_hash", String(128), nullable=False),
    Column("provenance_type", String(80), nullable=False),
    Column("temporal_kind", String(16), nullable=False),
    Column("observed_at", DateTime(timezone=True)),
    Column("valid_from", DateTime(timezone=True)),
    Column("valid_to", DateTime(timezone=True)),
)

evidence_assertions = Table(
    "dr_evidence_assertions",
    metadata,
    Column("evidence_id", String(200), ForeignKey("dr_evidence_records.id"), primary_key=True),
    Column("entity_id", String(200), primary_key=True),
    Column("assertion", String(100), primary_key=True),
)

authorization_records = Table(
    "dr_authorization_records",
    metadata,
    Column("id", String(200), primary_key=True),
    Column("entity_id", String(200), nullable=False),
    Column("authorized_assertion", String(100), nullable=False),
    Column("policy_version", String(100), nullable=False),
    Column("policy_hash", String(128), nullable=False),
)

authorization_evidence = Table(
    "dr_authorization_evidence",
    metadata,
    Column("authorization_id", String(200), ForeignKey("dr_authorization_records.id"), primary_key=True),
    Column("evidence_id", String(200), ForeignKey("dr_evidence_records.id"), primary_key=True),
)

decision_commits = Table(
    "dr_decision_commits",
    metadata,
    Column("id", String(200), primary_key=True),
    Column("decision_id", String(200), nullable=False),
    Column("contract_version", String(100), nullable=False),
    Column("capture_profile_version", String(200), nullable=False),
    Column("capture_profile_hash", String(128), nullable=False),
)

evaluation_snapshots = Table(
    "dr_evaluation_snapshots",
    metadata,
    Column("id", String(200), primary_key=True),
    Column("decision_id", String(200), nullable=False),
    Column("input_cutoff_seq", BigInteger, nullable=False),
    Column("target_version", String(200), nullable=False),
    Column("target_hash", String(128), nullable=False),
    Column("evidence_policy_version", String(200), nullable=False),
    Column("evidence_policy_hash", String(128), nullable=False),
    Column("event_policy_version", String(200), nullable=False),
    Column("event_policy_hash", String(128), nullable=False),
    Column("engine_version", String(200), nullable=False),
    Column("engine_hash", String(128), nullable=False),
    Column("result_fingerprint", String(128), nullable=False),
)

raw_world_evidence = Table(
    "dr_raw_world_evidence",
    metadata,
    Column("id", String(200), primary_key=True),
    Column("content", Text, nullable=False),
    Column("source_id", String(500), nullable=False),
    Column("source_span", Text, nullable=False),
    Column("source_content_hash", String(128), nullable=False),
    Column("provenance_type", String(80), nullable=False),
    Column("temporal_kind", String(16), nullable=False),
    Column("observed_at", DateTime(timezone=True)),
    Column("valid_from", DateTime(timezone=True)),
    Column("valid_to", DateTime(timezone=True)),
)

world_observations = Table(
    "dr_world_observations",
    metadata,
    Column("raw_evidence_id", String(200), ForeignKey("dr_raw_world_evidence.id"), primary_key=True),
    Column("metric_key", String(200), primary_key=True),
    Column("value", Float, nullable=False),
    Column("unit", String(80), nullable=False),
    Column("window_days", Integer),
)

world_event_authorizations = Table(
    "dr_world_event_authorizations",
    metadata,
    Column("id", String(200), primary_key=True),
    Column("raw_evidence_id", String(200), ForeignKey("dr_raw_world_evidence.id"), nullable=False),
    Column("event_id", String(200), nullable=False),
    Column("policy_version", String(200), nullable=False),
    Column("policy_hash", String(128), nullable=False),
)

correction_records = Table(
    "dr_correction_records",
    metadata,
    Column("id", String(200), primary_key=True),
    Column("corrects_entry_id", String(200), nullable=False),
    Column("reason", Text, nullable=False),
)


_KIND_ORDER = {
    LedgerEntryKind.EVIDENCE: 10,
    LedgerEntryKind.RAW_WORLD_EVIDENCE: 20,
    LedgerEntryKind.AUTHORIZATION: 30,
    LedgerEntryKind.WORLD_EVENT_AUTHORIZATION: 40,
    LedgerEntryKind.DECISION_COMMIT: 50,
    LedgerEntryKind.EVALUATION: 60,
    LedgerEntryKind.CORRECTION: 70,
}


class PostgresTemporalLedger:
    """Typed PostgreSQL adapter with transactional monotonic batch allocation."""

    def __init__(self, database_url: str) -> None:
        self.engine: Engine = create_engine(database_url, future=True)

    def create_schema(self) -> None:
        metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            existing = conn.execute(select(ledger_head.c.id).where(ledger_head.c.id == 1)).first()
            if existing is None:
                conn.execute(insert(ledger_head).values(id=1, last_batch_seq=0))

    def drop_schema(self) -> None:
        metadata.drop_all(self.engine)

    @property
    def head_seq(self) -> int:
        with self.engine.connect() as conn:
            row = conn.execute(select(ledger_head.c.last_batch_seq).where(ledger_head.c.id == 1)).one()
            return int(row[0])

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
            entry_id = pending.payload.id
            if entry_id in local_ids:
                raise TemporalIntegrityError(f"duplicate ledger entry id: {entry_id}")
            local_ids.add(entry_id)
            _validate_payload(pending.kind, pending.payload)

        with self.engine.begin() as conn:
            head_row = conn.execute(
                select(ledger_head.c.last_batch_seq)
                .where(ledger_head.c.id == 1)
                .with_for_update()
            ).one()
            previous_head = int(head_row[0])

            duplicate = conn.execute(
                select(ledger_entries.c.entry_id).where(ledger_entries.c.entry_id.in_(tuple(local_ids)))
            ).first()
            if duplicate is not None:
                raise TemporalIntegrityError(f"duplicate ledger entry id: {duplicate[0]}")

            self._validate_cross_references(conn, entries, previous_head)
            batch_seq = previous_head + 1
            conn.execute(insert(ledger_batches).values(batch_seq=batch_seq, recorded_at=recorded_at))

            # Typed immutable records are the semantic source of truth. Insert them
            # in dependency order; ledger entry ordinals still preserve caller order.
            for pending in sorted(entries, key=lambda item: _KIND_ORDER[item.kind]):
                self._insert_typed(conn, pending.payload)

            ledger_rows = [
                {
                    "entry_id": pending.payload.id,
                    "batch_seq": batch_seq,
                    "entry_ordinal": index,
                    "kind": pending.kind.value,
                }
                for index, pending in enumerate(entries, start=1)
            ]
            conn.execute(insert(ledger_entries), ledger_rows)
            conn.execute(
                update(ledger_head)
                .where(ledger_head.c.id == 1)
                .values(last_batch_seq=batch_seq)
            )

        return LedgerBatch(
            batch_seq=batch_seq,
            recorded_at=recorded_at,
            entries=tuple(
                LedgerEntry(
                    batch_seq=batch_seq,
                    entry_ordinal=index,
                    entry_id=pending.payload.id,
                    kind=pending.kind,
                    recorded_at=recorded_at,
                    payload=pending.payload,
                )
                for index, pending in enumerate(entries, start=1)
            ),
        )

    def entries_as_of(self, cutoff_seq: int) -> Tuple[LedgerEntry, ...]:
        head = self.head_seq
        if cutoff_seq < 0 or cutoff_seq > head:
            raise TemporalIntegrityError("cutoff_seq is outside the ledger")
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(
                    ledger_entries.c.entry_id,
                    ledger_entries.c.batch_seq,
                    ledger_entries.c.entry_ordinal,
                    ledger_entries.c.kind,
                    ledger_batches.c.recorded_at,
                )
                .join(ledger_batches, ledger_batches.c.batch_seq == ledger_entries.c.batch_seq)
                .where(ledger_entries.c.batch_seq <= cutoff_seq)
                .order_by(ledger_entries.c.batch_seq, ledger_entries.c.entry_ordinal)
            ).all()
            return tuple(
                LedgerEntry(
                    batch_seq=int(row.batch_seq),
                    entry_ordinal=int(row.entry_ordinal),
                    entry_id=row.entry_id,
                    kind=LedgerEntryKind(row.kind),
                    recorded_at=row.recorded_at,
                    payload=self._load_typed(conn, LedgerEntryKind(row.kind), row.entry_id),
                )
                for row in rows
            )

    def effective_entries_as_of(self, cutoff_seq: int) -> Tuple[LedgerEntry, ...]:
        entries = self.entries_as_of(cutoff_seq)
        corrected = {
            entry.payload.corrects_entry_id
            for entry in entries
            if entry.kind is LedgerEntryKind.CORRECTION
            and isinstance(entry.payload, CorrectionRecord)
        }
        return tuple(
            entry
            for entry in entries
            if entry.entry_id not in corrected
            and entry.kind is not LedgerEntryKind.CORRECTION
        )

    def entry(self, entry_id: str) -> LedgerEntry:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(
                    ledger_entries.c.entry_id,
                    ledger_entries.c.batch_seq,
                    ledger_entries.c.entry_ordinal,
                    ledger_entries.c.kind,
                    ledger_batches.c.recorded_at,
                )
                .join(ledger_batches, ledger_batches.c.batch_seq == ledger_entries.c.batch_seq)
                .where(ledger_entries.c.entry_id == entry_id)
            ).first()
            if row is None:
                raise KeyError(entry_id)
            kind = LedgerEntryKind(row.kind)
            return LedgerEntry(
                batch_seq=int(row.batch_seq),
                entry_ordinal=int(row.entry_ordinal),
                entry_id=row.entry_id,
                kind=kind,
                recorded_at=row.recorded_at,
                payload=self._load_typed(conn, kind, row.entry_id),
            )

    def _validate_cross_references(
        self,
        conn: Connection,
        entries: Sequence[PendingLedgerEntry],
        previous_head: int,
    ) -> None:
        local = {pending.payload.id: pending.kind for pending in entries}
        prior_rows = conn.execute(select(ledger_entries.c.entry_id, ledger_entries.c.kind)).all()
        prior = {row.entry_id: LedgerEntryKind(row.kind) for row in prior_rows}
        visible = {**prior, **local}
        for pending in entries:
            payload = pending.payload
            if isinstance(payload, AuthorizationRecord):
                for evidence_id in payload.evidence_ids:
                    if visible.get(evidence_id) is not LedgerEntryKind.EVIDENCE:
                        raise TemporalIntegrityError("authorization references unavailable/non-evidence input")
            elif isinstance(payload, WorldEventAuthorizationRecord):
                if visible.get(payload.raw_evidence_id) is not LedgerEntryKind.RAW_WORLD_EVIDENCE:
                    raise TemporalIntegrityError("world authorization references unavailable raw evidence")
            elif isinstance(payload, CorrectionRecord):
                if payload.corrects_entry_id not in prior:
                    raise TemporalIntegrityError("correction target must pre-exist this batch")
                if prior[payload.corrects_entry_id] is LedgerEntryKind.CORRECTION:
                    raise TemporalIntegrityError("V1 does not support correction-of-correction")
            elif isinstance(payload, EvaluationSnapshot):
                if payload.input_cutoff_seq > previous_head:
                    raise TemporalIntegrityError("evaluation input cutoff cannot include its own output batch")

    def _insert_typed(self, conn: Connection, payload) -> None:
        if isinstance(payload, TemporalEvidenceRecord):
            temporal = _temporal_columns(payload.temporal_reference)
            conn.execute(
                insert(evidence_records).values(
                    id=payload.id,
                    content=payload.content,
                    source_id=payload.source_id,
                    source_span=payload.source_span,
                    source_content_hash=payload.source_content_hash,
                    provenance_type=payload.provenance_type.value,
                    **temporal,
                )
            )
            if payload.candidate_assertions:
                conn.execute(
                    insert(evidence_assertions),
                    [
                        {
                            "evidence_id": payload.id,
                            "entity_id": item.entity_id,
                            "assertion": item.assertion.value,
                        }
                        for item in payload.candidate_assertions
                    ],
                )
        elif isinstance(payload, AuthorizationRecord):
            conn.execute(
                insert(authorization_records).values(
                    id=payload.id,
                    entity_id=payload.entity_id,
                    authorized_assertion=payload.authorized_assertion.value,
                    policy_version=payload.policy_version,
                    policy_hash=payload.policy_hash,
                )
            )
            conn.execute(
                insert(authorization_evidence),
                [
                    {"authorization_id": payload.id, "evidence_id": evidence_id}
                    for evidence_id in payload.evidence_ids
                ],
            )
        elif isinstance(payload, DecisionCommitRecord):
            conn.execute(insert(decision_commits).values(**payload.__dict__))
        elif isinstance(payload, EvaluationSnapshot):
            conn.execute(insert(evaluation_snapshots).values(**payload.__dict__))
        elif isinstance(payload, RawWorldEvidence):
            temporal = _temporal_columns(payload.temporal_reference)
            conn.execute(
                insert(raw_world_evidence).values(
                    id=payload.id,
                    content=payload.content,
                    source_id=payload.source_id,
                    source_span=payload.source_span,
                    source_content_hash=payload.source_content_hash,
                    provenance_type=payload.provenance_type.value,
                    **temporal,
                )
            )
            conn.execute(
                insert(world_observations),
                [
                    {
                        "raw_evidence_id": payload.id,
                        "metric_key": obs.metric_key,
                        "value": obs.value,
                        "unit": obs.unit,
                        "window_days": obs.window_days,
                    }
                    for obs in payload.observations
                ],
            )
        elif isinstance(payload, WorldEventAuthorizationRecord):
            conn.execute(insert(world_event_authorizations).values(**payload.__dict__))
        elif isinstance(payload, CorrectionRecord):
            conn.execute(insert(correction_records).values(**payload.__dict__))
        else:
            raise TemporalIntegrityError(f"unsupported persistence payload: {type(payload)!r}")

    def _load_typed(self, conn: Connection, kind: LedgerEntryKind, entry_id: str):
        if kind is LedgerEntryKind.EVIDENCE:
            row = conn.execute(select(evidence_records).where(evidence_records.c.id == entry_id)).one()
            assertions = conn.execute(
                select(evidence_assertions.c.entity_id, evidence_assertions.c.assertion)
                .where(evidence_assertions.c.evidence_id == entry_id)
                .order_by(evidence_assertions.c.entity_id, evidence_assertions.c.assertion)
            ).all()
            return TemporalEvidenceRecord(
                id=row.id,
                content=row.content,
                source_id=row.source_id,
                source_span=row.source_span,
                source_content_hash=row.source_content_hash,
                provenance_type=ProvenanceType(row.provenance_type),
                temporal_reference=_temporal_from_row(row),
                candidate_assertions=tuple(
                    CandidateAssertion(item.entity_id, AuthorizedAssertion(item.assertion))
                    for item in assertions
                ),
            )
        if kind is LedgerEntryKind.AUTHORIZATION:
            row = conn.execute(
                select(authorization_records).where(authorization_records.c.id == entry_id)
            ).one()
            evidence_ids = tuple(
                item.evidence_id
                for item in conn.execute(
                    select(authorization_evidence.c.evidence_id)
                    .where(authorization_evidence.c.authorization_id == entry_id)
                    .order_by(authorization_evidence.c.evidence_id)
                ).all()
            )
            return AuthorizationRecord(
                id=row.id,
                entity_id=row.entity_id,
                authorized_assertion=AuthorizedAssertion(row.authorized_assertion),
                evidence_ids=evidence_ids,
                policy_version=row.policy_version,
                policy_hash=row.policy_hash,
            )
        if kind is LedgerEntryKind.DECISION_COMMIT:
            row = conn.execute(select(decision_commits).where(decision_commits.c.id == entry_id)).one()
            return DecisionCommitRecord(**dict(row._mapping))
        if kind is LedgerEntryKind.EVALUATION:
            row = conn.execute(
                select(evaluation_snapshots).where(evaluation_snapshots.c.id == entry_id)
            ).one()
            return EvaluationSnapshot(**dict(row._mapping))
        if kind is LedgerEntryKind.RAW_WORLD_EVIDENCE:
            row = conn.execute(
                select(raw_world_evidence).where(raw_world_evidence.c.id == entry_id)
            ).one()
            observations = conn.execute(
                select(world_observations)
                .where(world_observations.c.raw_evidence_id == entry_id)
                .order_by(world_observations.c.metric_key)
            ).all()
            return RawWorldEvidence(
                id=row.id,
                content=row.content,
                source_id=row.source_id,
                source_span=row.source_span,
                source_content_hash=row.source_content_hash,
                provenance_type=ProvenanceType(row.provenance_type),
                temporal_reference=_temporal_from_row(row),
                observations=tuple(
                    NumericObservation(
                        metric_key=item.metric_key,
                        value=float(item.value),
                        unit=item.unit,
                        window_days=item.window_days,
                    )
                    for item in observations
                ),
            )
        if kind is LedgerEntryKind.WORLD_EVENT_AUTHORIZATION:
            row = conn.execute(
                select(world_event_authorizations).where(world_event_authorizations.c.id == entry_id)
            ).one()
            return WorldEventAuthorizationRecord(**dict(row._mapping))
        if kind is LedgerEntryKind.CORRECTION:
            row = conn.execute(
                select(correction_records).where(correction_records.c.id == entry_id)
            ).one()
            return CorrectionRecord(**dict(row._mapping))
        raise TemporalIntegrityError(f"unsupported ledger kind: {kind}")


def _temporal_columns(reference: TemporalReference) -> dict:
    reference.validate()
    return {
        "temporal_kind": reference.kind.value,
        "observed_at": reference.observed_at,
        "valid_from": reference.valid_from,
        "valid_to": reference.valid_to,
    }


def _temporal_from_row(row) -> TemporalReference:
    kind = TemporalReferenceKind(row.temporal_kind)
    if kind is TemporalReferenceKind.POINT:
        return TemporalReference.point(row.observed_at)
    return TemporalReference.interval(row.valid_from, row.valid_to)
