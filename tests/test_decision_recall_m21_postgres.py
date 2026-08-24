import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from decision_recall.domain import NumericObservation, ProvenanceType
from decision_recall.golden import safe_reuse_target_v1, supplier_metric_specs
from decision_recall.m2_golden import supplier_resilience_temporal_contract
from decision_recall.m21 import (
    AuthorizationScope,
    CANONICALIZATION_V1,
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
from decision_recall.m21_strict import strict_full_replay, strict_materialize_committed_contract, strict_verify_full_replay
from decision_recall.persistence_postgres import PostgresTemporalLedger
from decision_recall.temporal import (
    AuthorizedAssertion,
    CandidateAssertion,
    CorrectionRecord,
    DecisionCommitRecord,
    EvaluationSnapshot,
    EventPolicy,
    InMemoryTemporalLedger,
    LedgerEntryKind,
    PendingLedgerEntry,
    RawWorldEvidence,
    TemporalEvidenceRecord,
    TemporalIntegrityError,
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
COMMIT_ID = "COMMIT-D104-PARITY"


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


def make_world(eid, metric, value, unit, window_days=None, *, hash_override=None):
    text = f"{metric}={value} {unit}"
    return RawWorldEvidence(
        id=eid,
        content=text,
        source_id=f"source-{eid}",
        source_span="ERP span",
        source_content_hash=hash_override or source_hash(text),
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
            self.pg.dispose()

    def _append_both(self, memory, *, recorded_at, entries):
        a = memory.append_batch(recorded_at=recorded_at, entries=entries)
        b = self.pg.append_batch(recorded_at=recorded_at, entries=entries)
        self.assertEqual(a.batch_seq, b.batch_seq)
        return a

    def _build(self, *, omit=()):
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

        specs_auth = (
            ("F1", AuthorizedAssertion.ESTABLISHED_FACT),
            ("F2", AuthorizedAssertion.ESTABLISHED_FACT),
            ("R1", AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE),
            ("R2", AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE),
            ("M1", AuthorizedAssertion.CURRENT_MATCH_RULE),
            ("M2", AuthorizedAssertion.CURRENT_MATCH_RULE),
            ("RC1", AuthorizedAssertion.REVISIT_RULE),
        )
        pending = []
        for entity, assertion in specs_auth:
            if entity in set(omit):
                continue
            ev = make_evidence(f"E-{entity}-PARITY", entity, assertion, f"commit assertion for {entity}")
            raw_auth = authority_policy.authorize_candidate(
                evidence=ev,
                candidate=ev.candidate_assertions[0],
                authorization_id=f"AUTH-{entity}-PARITY",
            )
            auth = replace(
                raw_auth,
                contract_artifact_id=contract_artifact.artifact_id,
                entity_definition_hash=entity_definition_hash(contract, entity),
                scope=AuthorizationScope.COMMIT_TIME.value,
                scope_ref=COMMIT_ID,
            )
            pending.extend((
                PendingLedgerEntry(LedgerEntryKind.EVIDENCE, ev),
                PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, auth),
            ))
            registry.add_authorization(
                ScopedAuthorization(
                    authorization_id=auth.id,
                    contract_artifact_id=contract_artifact.artifact_id,
                    entity_id=entity,
                    entity_definition_hash=auth.entity_definition_hash,
                    authorized_assertion=assertion,
                    evidence_id=ev.id,
                    policy_version=authority_policy.version,
                    policy_hash=authority_policy.policy_hash,
                    scope=AuthorizationScope.COMMIT_TIME,
                    scope_ref=COMMIT_ID,
                )
            )

        ledger_commit = DecisionCommitRecord(
            id=COMMIT_ID,
            decision_id="D-104",
            contract_version="1",
            capture_profile_version="SUPPLIER_RESILIENCE_V1",
            capture_profile_hash="capture-hash",
            contract_artifact_id=contract_artifact.artifact_id,
            contract_hash=contract_artifact.content_hash,
            canonicalization_version=CANONICALIZATION_V1,
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
            world_pending.extend((
                PendingLedgerEntry(LedgerEntryKind.RAW_WORLD_EVIDENCE, raw),
                PendingLedgerEntry(LedgerEntryKind.WORLD_EVENT_AUTHORIZATION, auth),
            ))
        self._append_both(memory, recorded_at=T1, entries=tuple(world_pending))
        return memory, registry, authority_policy, event_policy, event_policies, contract, target, specs, contract_artifact, target_artifact, schema_artifact, commit

    def _make_final(self, *, memory, registry, authority_policy, event_policy, event_policies, target, target_artifact, schema_artifact, commit, eid="EV-PARITY"):
        placeholder = CanonicalEvaluationResult("placeholder", (), (), (), ())
        draft = StrongEvaluationSnapshot(
            evaluation_id=eid,
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
        result = strict_full_replay(
            registry=registry,
            ledger=memory,
            evaluation=draft,
            authority_policy=authority_policy,
            event_policies=event_policies,
            engine_version=ENGINE_VERSION,
            engine_hash=ENGINE_HASH,
        )
        final = replace(draft, canonical_result=result, result_hash=result.result_hash())
        registry.add_evaluation(final)
        output = EvaluationSnapshot(
            id=final.evaluation_id,
            decision_id="D-104",
            input_cutoff_seq=final.input_cutoff_seq,
            target_version=target.version,
            target_hash=final.target_hash,
            evidence_policy_version=final.authority_policy_version,
            evidence_policy_hash=final.authority_policy_hash,
            event_policy_version=final.event_policy_version,
            event_policy_hash=final.event_policy_hash,
            engine_version=final.engine_version,
            engine_hash=final.engine_hash,
            result_fingerprint=final.result_hash,
            decision_commit_id=final.decision_commit_id,
            contract_hash=final.contract_hash,
            world_time=final.world_time,
            target_artifact_id=final.target_artifact_id,
            world_schema_artifact_id=final.world_schema_artifact_id,
            world_schema_hash=final.world_schema_hash,
            canonical_result_json=final.canonical_result.canonical_json(),
            canonicalization_version=final.canonicalization_version,
        )
        self._append_both(
            memory,
            recorded_at=T1 + timedelta(seconds=1),
            entries=(PendingLedgerEntry(LedgerEntryKind.EVALUATION, output),),
        )
        return final

    def test_full_replay_survives_registry_reload_and_matches_inmemory(self):
        data = self._build()
        memory, registry, authority_policy, event_policy, event_policies, _, target, _, _, target_artifact, schema_artifact, commit = data
        final = self._make_final(
            memory=memory,
            registry=registry,
            authority_policy=authority_policy,
            event_policy=event_policy,
            event_policies=event_policies,
            target=target,
            target_artifact=target_artifact,
            schema_artifact=schema_artifact,
            commit=commit,
        )
        self.store.persist_registry(registry)
        reloaded = self.store.load_registry()
        result_pg = strict_verify_full_replay(
            registry=reloaded,
            ledger=self.pg,
            evaluation_id=final.evaluation_id,
            authority_policy=authority_policy,
            event_policies=event_policies,
            engine_version=ENGINE_VERSION,
            engine_hash=ENGINE_HASH,
        )
        self.assertEqual(result_pg, final.canonical_result)

        correction = PendingLedgerEntry(
            LedgerEntryKind.CORRECTION,
            CorrectionRecord("CORR-R2-PARITY", "E-R2-PARITY", "source invalidated"),
        )
        self._append_both(memory, recorded_at=T1 + timedelta(days=1), entries=(correction,))
        self.assertEqual(
            tuple((e.entry_id, e.kind.value) for e in active_entries_as_of(memory, memory.head_seq)),
            tuple((e.entry_id, e.kind.value) for e in active_entries_as_of(self.pg, self.pg.head_seq)),
        )

    def test_inflated_commit_cutoff_rejected_in_postgres(self):
        data = self._build()
        _, registry, authority_policy, _, _, _, target, _, _, _, _, commit = data
        inflated = replace(commit, commit_cutoff_seq=commit.commit_cutoff_seq + 1)
        with self.assertRaisesRegex(TemporalIntegrityError, "actual ledger commit batch"):
            strict_materialize_committed_contract(
                registry=registry,
                ledger=self.pg,
                commit=inflated,
                authority_policy=authority_policy,
                target=target,
            )

    def test_missing_target_authority_fails_identically_in_postgres(self):
        data = self._build(omit={"M1"})
        _, registry, authority_policy, event_policy, event_policies, _, target, _, _, target_artifact, schema_artifact, commit = data
        placeholder = CanonicalEvaluationResult("placeholder", (), (), (), ())
        draft = StrongEvaluationSnapshot(
            "EV-MISSING-PG", commit.commit_id, commit.contract_hash, self.pg.head_seq, T1,
            target_artifact.artifact_id, target_artifact.content_hash,
            schema_artifact.artifact_id, schema_artifact.content_hash,
            authority_policy.version, authority_policy.policy_hash,
            event_policy.version, event_policy.policy_hash,
            ENGINE_VERSION, ENGINE_HASH, placeholder, placeholder.result_hash(),
        )
        with self.assertRaisesRegex(TemporalIntegrityError, "MISSING_COMMIT_TIME_SEMANTIC_AUTHORITY:M1"):
            strict_full_replay(
                registry=registry,
                ledger=self.pg,
                evaluation=draft,
                authority_policy=authority_policy,
                event_policies=event_policies,
                engine_version=ENGINE_VERSION,
                engine_hash=ENGINE_HASH,
            )

    def test_other_event_policy_and_bad_hash_cannot_contaminate_postgres_replay(self):
        data = self._build()
        memory, registry, authority_policy, event_policy, event_policies, _, target, specs, _, target_artifact, schema_artifact, commit = data
        v2 = EventPolicy("EVENT_V2", "event-v2-hash", (ProvenanceType.CONTEMPORANEOUS_RECORD,))
        bad = make_world("WE-V2-BAD-PG", "apex_on_time_rate", 0.1, "ratio", 30, hash_override="0" * 64)
        auth = v2.authorize(raw=bad, metric_specs=specs)
        self._append_both(
            memory,
            recorded_at=T1 + timedelta(minutes=2),
            entries=(
                PendingLedgerEntry(LedgerEntryKind.RAW_WORLD_EVIDENCE, bad),
                PendingLedgerEntry(LedgerEntryKind.WORLD_EVENT_AUTHORIZATION, auth),
            ),
        )
        event_policies[(v2.version, v2.policy_hash)] = v2
        final = self._make_final(
            memory=memory,
            registry=registry,
            authority_policy=authority_policy,
            event_policy=event_policy,
            event_policies=event_policies,
            target=target,
            target_artifact=target_artifact,
            schema_artifact=schema_artifact,
            commit=commit,
            eid="EV-PG-POLICY-ISOLATED",
        )
        self.assertEqual(dict(final.canonical_result.current_matches)["M1"], "does_not_match")

    def test_registry_only_evaluation_backfill_is_rejected_in_postgres(self):
        data = self._build()
        _, registry, authority_policy, event_policy, event_policies, _, target, _, _, target_artifact, schema_artifact, commit = data
        placeholder = CanonicalEvaluationResult("placeholder", (), (), (), ())
        draft = StrongEvaluationSnapshot(
            "EV-PG-BACKFILL", commit.commit_id, commit.contract_hash, self.pg.head_seq, T1,
            target_artifact.artifact_id, target_artifact.content_hash,
            schema_artifact.artifact_id, schema_artifact.content_hash,
            authority_policy.version, authority_policy.policy_hash,
            event_policy.version, event_policy.policy_hash,
            ENGINE_VERSION, ENGINE_HASH, placeholder, placeholder.result_hash(),
        )
        result = strict_full_replay(
            registry=registry,
            ledger=self.pg,
            evaluation=draft,
            authority_policy=authority_policy,
            event_policies=event_policies,
            engine_version=ENGINE_VERSION,
            engine_hash=ENGINE_HASH,
        )
        final = replace(draft, canonical_result=result, result_hash=result.result_hash())
        registry.add_evaluation(final)
        with self.assertRaisesRegex(TemporalIntegrityError, "not temporally recorded"):
            strict_verify_full_replay(
                registry=registry,
                ledger=self.pg,
                evaluation_id=final.evaluation_id,
                authority_policy=authority_policy,
                event_policies=event_policies,
                engine_version=ENGINE_VERSION,
                engine_hash=ENGINE_HASH,
            )


if __name__ == "__main__":
    unittest.main()
