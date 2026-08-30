import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from decision_recall.domain import CompositionValue, HistoricalKnowledgeState, NumericObservation, ProvenanceType
from decision_recall.golden import supplier_metric_specs
from decision_recall.persistence_postgres import PostgresTemporalLedger
from decision_recall.temporal import (
    AuthorizedAssertion,
    CandidateAssertion,
    DecisionCommitRecord,
    LedgerEntryKind,
    PendingLedgerEntry,
    RawWorldEvidence,
    TemporalEvidenceRecord,
    TemporalIntegrityError,
    TemporalReference,
    authority_policy_v1,
    authorized_world_state_as_of,
    event_policy_v1,
    recorded_historical_view,
    replay_authority_from_evidence,
    source_hash,
)


UTC = timezone.utc
T0 = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)


def evidence(evidence_id, entity_id, assertion, content="decision-time evidence"):
    return TemporalEvidenceRecord(
        id=evidence_id,
        content=content,
        source_id=f"source-{evidence_id}",
        source_span="lines 1-2",
        source_content_hash=source_hash(content),
        provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
        temporal_reference=TemporalReference.point(T0),
        candidate_assertions=(CandidateAssertion(entity_id, assertion),),
    )


@unittest.skipUnless(os.getenv("DECISION_RECALL_TEST_DATABASE_URL"), "PostgreSQL test URL not configured")
class PostgresTemporalLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = os.environ["DECISION_RECALL_TEST_DATABASE_URL"]
        cls.policy = authority_policy_v1()
        cls.policy_registry = {(cls.policy.version, cls.policy.policy_hash): cls.policy}
        cls.event_policy = event_policy_v1()
        cls.event_registry = {(cls.event_policy.version, cls.event_policy.policy_hash): cls.event_policy}
        cls.metrics = supplier_metric_specs()

    def setUp(self):
        self.ledger = PostgresTemporalLedger(self.url)
        self.ledger.drop_schema()
        self.ledger.create_schema()

    def tearDown(self):
        self.ledger.drop_schema()
        self.ledger.engine.dispose()

    def test_atomic_evidence_authorization_commit_batch_round_trips(self):
        r2 = evidence("E-R2", "R2", AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE)
        auth = self.policy.authorize_candidate(
            evidence=r2,
            candidate=r2.candidate_assertions[0],
            authorization_id="AUTH-R2",
        )
        commit = DecisionCommitRecord(
            id="COMMIT-D104",
            decision_id="D-104",
            contract_version="1",
            capture_profile_version="SUPPLIER_RESILIENCE_V1",
            capture_profile_hash="capture-hash-v1",
        )
        batch = self.ledger.append_batch(
            recorded_at=T0,
            entries=(
                PendingLedgerEntry(LedgerEntryKind.EVIDENCE, r2),
                PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, auth),
                PendingLedgerEntry(LedgerEntryKind.DECISION_COMMIT, commit),
            ),
        )
        self.assertEqual(batch.batch_seq, 1)
        self.assertEqual(self.ledger.head_seq, 1)
        self.assertEqual(len(self.ledger.entries_as_of(1)), 3)
        view = recorded_historical_view(
            self.ledger,
            cutoff_seq=1,
            policies=self.policy_registry,
        )
        self.assertEqual(view.relation_state("R2"), HistoricalKnowledgeState.ESTABLISHED)

    def test_hindsight_leakage_is_blocked_in_postgres_replay(self):
        r2 = evidence("E-R2", "R2", AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE)
        self.ledger.append_batch(
            recorded_at=T0,
            entries=(PendingLedgerEntry(LedgerEntryKind.EVIDENCE, r2),),
        )
        cutoff = self.ledger.head_seq
        late = evidence("E-C1-LATE", "C1", AuthorizedAssertion.COMPOSITION_TRUE, "Late old email")
        self.ledger.append_batch(
            recorded_at=T2,
            entries=(PendingLedgerEntry(LedgerEntryKind.EVIDENCE, late),),
        )
        replay = replay_authority_from_evidence(
            self.ledger,
            input_cutoff_seq=cutoff,
            policy=self.policy,
        )
        self.assertNotIn(("C1", AuthorizedAssertion.COMPOSITION_TRUE), replay)

    def test_commit_authority_leakage_is_blocked_in_postgres(self):
        r2 = evidence("E-R2", "R2", AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE)
        self.ledger.append_batch(
            recorded_at=T0,
            entries=(PendingLedgerEntry(LedgerEntryKind.EVIDENCE, r2),),
        )
        commit = DecisionCommitRecord(
            id="COMMIT-D104",
            decision_id="D-104",
            contract_version="1",
            capture_profile_version="SUPPLIER_RESILIENCE_V1",
            capture_profile_hash="capture-hash-v1",
        )
        self.ledger.append_batch(
            recorded_at=T0 + timedelta(minutes=1),
            entries=(PendingLedgerEntry(LedgerEntryKind.DECISION_COMMIT, commit),),
        )
        commit_cutoff = self.ledger.head_seq
        auth = self.policy.authorize_candidate(
            evidence=r2,
            candidate=r2.candidate_assertions[0],
            authorization_id="AUTH-R2-LATE",
        )
        self.ledger.append_batch(
            recorded_at=T1,
            entries=(PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, auth),),
        )
        old = recorded_historical_view(
            self.ledger,
            cutoff_seq=commit_cutoff,
            policies=self.policy_registry,
        )
        new = recorded_historical_view(
            self.ledger,
            cutoff_seq=self.ledger.head_seq,
            policies=self.policy_registry,
        )
        self.assertEqual(old.relation_state("R2"), HistoricalKnowledgeState.NOT_DURABLY_RECORDED)
        self.assertEqual(new.relation_state("R2"), HistoricalKnowledgeState.ESTABLISHED)

    def test_false_historical_unknown_is_not_invented_in_postgres(self):
        view = recorded_historical_view(
            self.ledger,
            cutoff_seq=0,
            policies=self.policy_registry,
        )
        self.assertEqual(view.composition_state("C1"), CompositionValue.NOT_DURABLY_RECORDED)

    def test_world_state_requires_first_class_event_authorization_and_preserves_lineage(self):
        raw = RawWorldEvidence(
            id="WE-301",
            content="Apex OTD 98.7% over 30 days",
            source_id="ERP",
            source_span="Apex row",
            source_content_hash=source_hash("Apex OTD 98.7% over 30 days"),
            provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
            temporal_reference=TemporalReference.interval(T1 - timedelta(days=30), T1),
            observations=(NumericObservation("apex_on_time_rate", 0.987, unit="ratio", window_days=30),),
        )
        self.ledger.append_batch(
            recorded_at=T1,
            entries=(PendingLedgerEntry(LedgerEntryKind.RAW_WORLD_EVIDENCE, raw),),
        )
        before = authorized_world_state_as_of(
            self.ledger,
            cutoff_seq=self.ledger.head_seq,
            policies=self.event_registry,
            metric_specs=self.metrics,
        )
        self.assertIsNone(before.observation("apex_on_time_rate"))
        auth = self.event_policy.authorize(raw=raw, metric_specs=self.metrics)
        self.ledger.append_batch(
            recorded_at=T1 + timedelta(seconds=1),
            entries=(PendingLedgerEntry(LedgerEntryKind.WORLD_EVENT_AUTHORIZATION, auth),),
        )
        after = authorized_world_state_as_of(
            self.ledger,
            cutoff_seq=self.ledger.head_seq,
            policies=self.event_registry,
            metric_specs=self.metrics,
        )
        apex = after.observation("apex_on_time_rate")
        self.assertEqual(apex.value, 0.987)
        self.assertEqual(apex.source_event_id, auth.event_id)

    def test_failed_postgres_batch_is_atomic(self):
        r2 = evidence("E-R2", "R2", AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE)
        bad_auth = self.policy.authorize_candidate(
            evidence=r2,
            candidate=r2.candidate_assertions[0],
            authorization_id="AUTH-R2",
        )
        bad_auth = type(bad_auth)(
            id=bad_auth.id,
            entity_id=bad_auth.entity_id,
            authorized_assertion=bad_auth.authorized_assertion,
            evidence_ids=("MISSING",),
            policy_version=bad_auth.policy_version,
            policy_hash=bad_auth.policy_hash,
        )
        with self.assertRaises(TemporalIntegrityError):
            self.ledger.append_batch(
                recorded_at=T0,
                entries=(PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, bad_auth),),
            )
        self.assertEqual(self.ledger.head_seq, 0)
        self.assertEqual(self.ledger.entries_as_of(0), ())

    def test_concurrent_appends_receive_unique_monotonic_batch_sequences(self):
        def append_one(index):
            record = evidence(
                f"E-CONCURRENT-{index}",
                f"F-CONCURRENT-{index}",
                AuthorizedAssertion.ESTABLISHED_FACT,
                content=f"concurrent evidence {index}",
            )
            return self.ledger.append_batch(
                recorded_at=T0 + timedelta(seconds=index),
                entries=(PendingLedgerEntry(LedgerEntryKind.EVIDENCE, record),),
            ).batch_seq

        with ThreadPoolExecutor(max_workers=2) as pool:
            seqs = sorted(pool.map(append_one, (1, 2)))

        self.assertEqual(seqs, [1, 2])
        self.assertEqual(self.ledger.head_seq, 2)
        self.assertEqual(len(self.ledger.entries_as_of(2)), 2)


if __name__ == "__main__":
    unittest.main()
