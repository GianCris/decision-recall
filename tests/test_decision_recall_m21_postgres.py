import os
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from decision_recall.domain import NumericObservation, ProvenanceType
from decision_recall.golden import safe_reuse_target_v1, supplier_metric_specs
from decision_recall.m2_golden import supplier_resilience_temporal_contract
from decision_recall.m21 import (
    AuthorizationScope,
    CanonicalEvaluationResult,
    M21Registry,
    ScopedAuthorization,
    StrongDecisionCommit,
    StrongEvaluationSnapshot,
    active_entries_as_of,
    entity_definition_hash,
    make_contract_artifact,
    make_target_artifact,
    make_world_schema_artifact,
)
from decision_recall.m21_postgres import PostgresM21Store
from decision_recall.m21_strict import strict_full_replay, strict_verify_full_replay
from decision_recall.persistence_postgres import PostgresTemporalLedger
from decision_recall.temporal import (
    AuthorizedAssertion,
    CandidateAssertion,
    CorrectionRecord,
    DecisionCommitRecord,
    InMemoryTemporalLedger,
    LedgerEntryKind,
    PendingLedgerEntry,
    RawWorldEvidence,
    TemporalEvidenceRecord,
    TemporalReference,
    authority_policy_v1,
    event_policy_v1,
    source_hash,
)

UTC = timezone.utc
T0 = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
ENGINE_VERSION = "0.2.1"
ENGINE_HASH = "engine-m21-postgres-test-sha"


def make_evidence(eid, entity_id, assertion, text):
    return TemporalEvidenceRecord(
        id=eid,
        content=text,
        source_id=f"source-{eid}",
        source_span="source span",
        source_content_hash=source_hash(text),
        provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
        temporal_reference=TemporalReference.point(T0),
        candidate_assertions=(CandidateAssertion(entity_id, assertion),),
    )


def make_world(eid, metric, value, unit, window_days=None):
    text = f"{metric}={value} {unit}"
    return RawWorldEvidence(
        id=eid,
        content=text,
        source_id=f"source-{eid}",
        source_span="ERP span",
        source_content_hash=source_hash(text),
        provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
        temporal_reference=TemporalReference.point(T1),
        observations=(NumericObservation(metric, value, unit=unit, window_days=window_days),),
    )


@unittest.skipUnless(
    os.getenv("DECISION_RECALL_TEST_DATABASE_URL"),
    "PostgreSQL test database not configured",
)
class M21PostgresParityTests(unittest.TestCase):
    def setUp(self):
        url = os.environ["DECISION_RECALL_TEST_DATABASE_URL"]
        self.pg = PostgresTemporalLedger(url)
        self.store = PostgresM21Store(url)
        # Clean leftovers if a prior interrupted run exists.
        try:
            self.store.drop_schema()
        except Exception:
            pass
        try:
            self.pg.drop_schema()
        except Exception:
            pass
        self.pg.create_schema()
        self.store.create_schema()

    def tearDown(self):
        try:
            self.store.drop_schema()
        finally:
            self.store.dispose()
        try:
            self.pg.drop_schema()
        finally:
            self.pg.engine.dispose()

    def _append_both(self, memory, *, recorded_at, entries):
        a = memory.append_batch(recorded_at=recorded_at, entries=entries)
        b = self.pg.append_batch(recorded_at=recorded_at, entries=entries)
        self.assertEqual(a.batch_seq, b.batch_seq)
        self.assertEqual(
            tuple((e.entry_id, e.kind) for e in a.entries),
            tuple((e.entry_id, e.kind) for e in b.entries),
        )
        return a

    def test_full_replay_survives_registry_reload_and_matches_inmemory(self):
        memory = InMemoryTemporalLedger()
        registry = M21Registry()
        authority_policy = authority_policy_v1()
        event_policy = event_policy_v1()
        event_policies = {(event_policy.version, event_policy.policy_hash): event_policy}
        contract = supplier_resilience_temporal_contract()
        target = safe_reuse_target_v1()
        specs = supplier_metric_specs()
        contract_artifact = make_contract_artifact(contract, version="1")
        target_artifact = make_target_artifact(target)
        schema_artifact = make_world_schema_artifact(specs, version="SUPPLIER_METRICS_V1")
        for artifact in (contract_artifact, target_artifact, schema_artifact):
            registry.add_artifact(artifact)

        pending = []
        for eid, entity, assertion, text in (
            (
                "E-R1-PARITY",
                "R1",
                AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
                "Apex instability materially influenced D-104.",
            ),
            (
                "E-R2-PARITY",
                "R2",
                AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
                "Beacon reaction capacity materially influenced D-104.",
            ),
        ):
            ev = make_evidence(eid, entity, assertion, text)
            auth = authority_policy.authorize_candidate(
                evidence=ev,
                candidate=ev.candidate_assertions[0],
                authorization_id=f"AUTH-{entity}-PARITY",
            )
            pending.extend(
                (
                    PendingLedgerEntry(LedgerEntryKind.EVIDENCE, ev),
                    PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, auth),
                )
            )
            registry.add_authorization(
                ScopedAuthorization(
                    authorization_id=auth.id,
                    contract_artifact_id=contract_artifact.artifact_id,
                    entity_id=entity,
                    entity_definition_hash=entity_definition_hash(contract, entity),
                    authorized_assertion=assertion,
                    evidence_id=ev.id,
                    policy_version=authority_policy.version,
                    policy_hash=authority_policy.policy_hash,
                    scope=AuthorizationScope.COMMIT_TIME,
                    scope_ref="COMMIT-D104-PARITY",
                )
            )

        ledger_commit = DecisionCommitRecord(
            id="COMMIT-D104-PARITY",
            decision_id="D-104",
            contract_version="1",
            capture_profile_version="SUPPLIER_RESILIENCE_V1",
            capture_profile_hash="capture-hash",
        )
        pending.append(PendingLedgerEntry(LedgerEntryKind.DECISION_COMMIT, ledger_commit))
        commit_batch = self._append_both(memory, recorded_at=T0, entries=tuple(pending))
        commit = StrongDecisionCommit(
            commit_id=ledger_commit.id,
            decision_id="D-104",
            contract_artifact_id=contract_artifact.artifact_id,
            contract_hash=contract_artifact.content_hash,
            contract_version="1",
            capture_profile_version="SUPPLIER_RESILIENCE_V1",
            capture_profile_hash="capture-hash",
            commit_cutoff_seq=commit_batch.batch_seq,
        )
        registry.add_commit(commit)

        world_pending = []
        for raw in (
            make_world("WE-APEX-PARITY", "apex_on_time_rate", 0.987, "ratio", 30),
            make_world("WE-BEACON-PARITY", "beacon_reactivation_days", 70, "days"),
        ):
            auth = event_policy.authorize(raw=raw, metric_specs=specs)
            world_pending.extend(
                (
                    PendingLedgerEntry(LedgerEntryKind.RAW_WORLD_EVIDENCE, raw),
                    PendingLedgerEntry(LedgerEntryKind.WORLD_EVENT_AUTHORIZATION, auth),
                )
            )
        self._append_both(memory, recorded_at=T1, entries=tuple(world_pending))

        placeholder = CanonicalEvaluationResult("placeholder", (), (), (), ())
        draft = StrongEvaluationSnapshot(
            evaluation_id="EV-PARITY",
            decision_commit_id=commit.commit_id,
            contract_hash=commit.contract_hash,
            input_cutoff_seq=memory.head_seq,
            world_time=T1,
            target_artifact_id=target_artifact.artifact_id,
            target_hash=target_artifact.content_hash,
            world_schema_artifact_id=schema_artifact.artifact_id,
            world_schema_hash=schema_artifact.content_hash,
            authority_policy_version=authority_policy.version,
            authority_policy_hash=authority_policy.policy_hash,
            event_policy_version=event_policy.version,
            event_policy_hash=event_policy.policy_hash,
            engine_version=ENGINE_VERSION,
            engine_hash=ENGINE_HASH,
            canonical_result=placeholder,
            result_hash=placeholder.result_hash(),
        )
        result_memory = strict_full_replay(
            registry=registry,
            ledger=memory,
            evaluation=draft,
            authority_policy=authority_policy,
            event_policies=event_policies,
            engine_version=ENGINE_VERSION,
            engine_hash=ENGINE_HASH,
        )
        final = replace(draft, canonical_result=result_memory, result_hash=result_memory.result_hash())
        registry.add_evaluation(final)

        # Persist semantic artifacts/snapshot, then rebuild the registry from DB as a
        # fresh process would do. Full replay must still match the in-memory result.
        self.store.persist_registry(registry)
        reloaded = self.store.load_registry()
        result_pg = strict_verify_full_replay(
            registry=reloaded,
            ledger=self.pg,
            evaluation_id="EV-PARITY",
            authority_policy=authority_policy,
            event_policies=event_policies,
            engine_version=ENGINE_VERSION,
            engine_hash=ENGINE_HASH,
        )
        self.assertEqual(result_memory, result_pg)
        self.assertEqual(result_memory.result_hash(), result_pg.result_hash())

        # Corrections must cascade identically in both adapters.
        correction = PendingLedgerEntry(
            LedgerEntryKind.CORRECTION,
            CorrectionRecord("CORR-R2-PARITY", "E-R2-PARITY", "source invalidated"),
        )
        self._append_both(memory, recorded_at=T1, entries=(correction,))
        memory_active = tuple(
            (entry.entry_id, entry.kind.value)
            for entry in active_entries_as_of(memory, memory.head_seq)
        )
        pg_active = tuple(
            (entry.entry_id, entry.kind.value)
            for entry in active_entries_as_of(self.pg, self.pg.head_seq)
        )
        self.assertEqual(memory_active, pg_active)
        self.assertNotIn(("AUTH-R2-PARITY", LedgerEntryKind.AUTHORIZATION.value), memory_active)


if __name__ == "__main__":
    unittest.main()
