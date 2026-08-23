import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from decision_recall.domain import (
    CompositionValue,
    NumericObservation,
    ProvenanceType,
    SafeReuseResult,
    TargetRef,
)
from decision_recall.golden import safe_reuse_target_v1, supplier_metric_specs
from decision_recall.m2_golden import supplier_resilience_temporal_contract
from decision_recall.m21 import (
    AuthorizationScope,
    CanonicalEvaluationResult,
    M21Registry,
    ScopedAuthorization,
    StrongDecisionCommit,
    StrongEvaluationSnapshot,
    authorized_world_state_at,
    canonical_hash,
    entity_definition_hash,
    known_historical_state,
    make_contract_artifact,
    make_target_artifact,
    make_world_schema_artifact,
)
from decision_recall.m21_strict import (
    strict_full_replay,
    strict_materialize_committed_contract,
    strict_verify_full_replay,
)
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
ENGINE_HASH = "engine-m21-test-sha"


def evidence(eid, entity_id, assertion, text, *, provenance=ProvenanceType.CONTEMPORANEOUS_RECORD, hash_override=None):
    return TemporalEvidenceRecord(
        id=eid,
        content=text,
        source_id=f"source-{eid}",
        source_span="decision-time span",
        source_content_hash=hash_override or source_hash(text),
        provenance_type=provenance,
        temporal_reference=TemporalReference.point(T0),
        candidate_assertions=(CandidateAssertion(entity_id, assertion),),
    )


def raw_world(eid, *, metric, value, unit, when, window_days=None):
    text = f"{metric}={value} {unit}"
    return RawWorldEvidence(
        id=eid,
        content=text,
        source_id=f"source-{eid}",
        source_span="ERP metric span",
        source_content_hash=source_hash(text),
        provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
        temporal_reference=TemporalReference.point(when),
        observations=(NumericObservation(metric, value, unit=unit, window_days=window_days),),
    )


class Scenario:
    def __init__(self, *, apex_rate=0.987, apex_when=T1):
        self.ledger = InMemoryTemporalLedger()
        self.registry = M21Registry()
        self.authority_policy = authority_policy_v1()
        self.event_policy = event_policy_v1()
        self.event_policies = {(self.event_policy.version, self.event_policy.policy_hash): self.event_policy}
        self.contract = supplier_resilience_temporal_contract()
        self.target = safe_reuse_target_v1()
        self.metric_specs = supplier_metric_specs()
        self.contract_artifact = make_contract_artifact(self.contract, version="1")
        self.target_artifact = make_target_artifact(self.target)
        self.schema_artifact = make_world_schema_artifact(self.metric_specs, version="SUPPLIER_METRICS_V1")
        for artifact in (self.contract_artifact, self.target_artifact, self.schema_artifact):
            self.registry.add_artifact(artifact)

        r1 = evidence(
            "E-R1-M21",
            "R1",
            AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
            "Apex instability materially influenced D-104.",
        )
        r2 = evidence(
            "E-R2-M21",
            "R2",
            AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
            "Beacon reaction capacity materially influenced D-104.",
        )
        records = []
        for ev, entity_id in ((r1, "R1"), (r2, "R2")):
            candidate = ev.candidate_assertions[0]
            auth = self.authority_policy.authorize_candidate(
                evidence=ev,
                candidate=candidate,
                authorization_id=f"AUTH-{entity_id}-M21",
            )
            records.extend(
                (
                    PendingLedgerEntry(LedgerEntryKind.EVIDENCE, ev),
                    PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, auth),
                )
            )
            self.registry.add_authorization(
                ScopedAuthorization(
                    authorization_id=auth.id,
                    contract_artifact_id=self.contract_artifact.artifact_id,
                    entity_id=entity_id,
                    entity_definition_hash=entity_definition_hash(self.contract, entity_id),
                    authorized_assertion=candidate.assertion,
                    evidence_id=ev.id,
                    policy_version=self.authority_policy.version,
                    policy_hash=self.authority_policy.policy_hash,
                    scope=AuthorizationScope.COMMIT_TIME,
                    scope_ref="COMMIT-D104-M21",
                )
            )

        ledger_commit = DecisionCommitRecord(
            id="COMMIT-D104-M21",
            decision_id="D-104",
            contract_version="1",
            capture_profile_version="SUPPLIER_RESILIENCE_V1",
            capture_profile_hash="capture-profile-hash-v1",
        )
        records.append(PendingLedgerEntry(LedgerEntryKind.DECISION_COMMIT, ledger_commit))
        batch = self.ledger.append_batch(recorded_at=T0, entries=tuple(records))
        self.commit = StrongDecisionCommit(
            commit_id=ledger_commit.id,
            decision_id="D-104",
            contract_artifact_id=self.contract_artifact.artifact_id,
            contract_hash=self.contract_artifact.content_hash,
            contract_version="1",
            capture_profile_version="SUPPLIER_RESILIENCE_V1",
            capture_profile_hash="capture-profile-hash-v1",
            commit_cutoff_seq=batch.batch_seq,
        )
        self.registry.add_commit(self.commit)

        beacon = raw_world(
            "WE-BEACON-M21",
            metric="beacon_reactivation_days",
            value=70,
            unit="days",
            when=T1,
        )
        apex = raw_world(
            "WE-APEX-M21",
            metric="apex_on_time_rate",
            value=apex_rate,
            unit="ratio",
            when=apex_when,
            window_days=30,
        )
        world_entries = []
        for raw in (beacon, apex):
            auth = self.event_policy.authorize(raw=raw, metric_specs=self.metric_specs)
            world_entries.extend(
                (
                    PendingLedgerEntry(LedgerEntryKind.RAW_WORLD_EVIDENCE, raw),
                    PendingLedgerEntry(LedgerEntryKind.WORLD_EVENT_AUTHORIZATION, auth),
                )
            )
        self.ledger.append_batch(recorded_at=T1, entries=tuple(world_entries))

    def evaluation(self, *, evaluation_id="EV-901-M21", world_time=T1):
        placeholder = CanonicalEvaluationResult(
            safe_reuse_result="placeholder",
            limiting_requirements=(),
            reason_codes=(),
            current_matches=(),
            review_states=(),
        )
        draft = StrongEvaluationSnapshot(
            evaluation_id=evaluation_id,
            decision_commit_id=self.commit.commit_id,
            contract_hash=self.commit.contract_hash,
            input_cutoff_seq=self.ledger.head_seq,
            world_time=world_time,
            target_artifact_id=self.target_artifact.artifact_id,
            target_hash=self.target_artifact.content_hash,
            world_schema_artifact_id=self.schema_artifact.artifact_id,
            world_schema_hash=self.schema_artifact.content_hash,
            authority_policy_version=self.authority_policy.version,
            authority_policy_hash=self.authority_policy.policy_hash,
            event_policy_version=self.event_policy.version,
            event_policy_hash=self.event_policy.policy_hash,
            engine_version=ENGINE_VERSION,
            engine_hash=ENGINE_HASH,
            canonical_result=placeholder,
            result_hash=placeholder.result_hash(),
        )
        result = strict_full_replay(
            registry=self.registry,
            ledger=self.ledger,
            evaluation=draft,
            authority_policy=self.authority_policy,
            event_policies=self.event_policies,
            engine_version=ENGINE_VERSION,
            engine_hash=ENGINE_HASH,
        )
        final = replace(draft, canonical_result=result, result_hash=result.result_hash())
        self.registry.add_evaluation(final)
        return final


class M21AttackTests(unittest.TestCase):
    def test_world_sensitive_full_replay_changes_real_target_result(self):
        reliable = Scenario(apex_rate=0.987)
        ev_reliable = reliable.evaluation(evaluation_id="EV-RELIABLE")
        self.assertEqual(ev_reliable.canonical_result.safe_reuse_result, SafeReuseResult.INSUFFICIENT_EVIDENCE.value)

        unstable = Scenario(apex_rate=0.83)
        ev_unstable = unstable.evaluation(evaluation_id="EV-UNSTABLE")
        self.assertEqual(ev_unstable.canonical_result.safe_reuse_result, SafeReuseResult.REUSE_AUTHORIZED.value)
        self.assertNotEqual(ev_reliable.result_hash, ev_unstable.result_hash)

    def test_semantic_identity_swap_rejects_old_authorization(self):
        scenario = Scenario()
        bad = replace(
            scenario.registry.authorizations["AUTH-R1-M21"],
            entity_definition_hash="0" * 64,
        )
        scenario.registry.authorizations[bad.authorization_id] = bad
        with self.assertRaisesRegex(TemporalIntegrityError, "semantic identity"):
            strict_materialize_committed_contract(
                registry=scenario.registry,
                ledger=scenario.ledger,
                commit=scenario.commit,
                authority_policy=scenario.authority_policy,
            )

    def test_contract_mutation_changes_artifact_identity(self):
        scenario = Scenario()
        changed = replace(scenario.contract, action="keep_only_beacon_active")
        changed_artifact = make_contract_artifact(changed, version="1")
        self.assertNotEqual(changed_artifact.content_hash, scenario.contract_artifact.content_hash)
        self.assertNotEqual(changed_artifact.artifact_id, scenario.contract_artifact.artifact_id)

    def test_ghost_evaluation_is_rejected(self):
        scenario = Scenario()
        result = CanonicalEvaluationResult("x", (), (), (), ())
        ghost = StrongEvaluationSnapshot(
            evaluation_id="EV-GHOST",
            decision_commit_id="COMMIT-DOES-NOT-EXIST",
            contract_hash=scenario.contract_artifact.content_hash,
            input_cutoff_seq=scenario.ledger.head_seq,
            world_time=T1,
            target_artifact_id=scenario.target_artifact.artifact_id,
            target_hash=scenario.target_artifact.content_hash,
            world_schema_artifact_id=scenario.schema_artifact.artifact_id,
            world_schema_hash=scenario.schema_artifact.content_hash,
            authority_policy_version=scenario.authority_policy.version,
            authority_policy_hash=scenario.authority_policy.policy_hash,
            event_policy_version=scenario.event_policy.version,
            event_policy_hash=scenario.event_policy.policy_hash,
            engine_version=ENGINE_VERSION,
            engine_hash=ENGINE_HASH,
            canonical_result=result,
            result_hash=result.result_hash(),
        )
        with self.assertRaisesRegex(TemporalIntegrityError, "unknown decision commit"):
            scenario.registry.add_evaluation(ghost)

    def test_unknown_entity_cannot_become_not_durably_recorded(self):
        scenario = Scenario()
        materialized = strict_materialize_committed_contract(
            registry=scenario.registry,
            ledger=scenario.ledger,
            commit=scenario.commit,
            authority_policy=scenario.authority_policy,
        )
        with self.assertRaisesRegex(TemporalIntegrityError, "UNKNOWN_ENTITY"):
            known_historical_state(contract=materialized, entity_id="C999")

    def test_evaluation_scope_authority_cannot_rewrite_committed_t0(self):
        scenario = Scenario()
        text = "Later evaluation suggests C1 was true."
        ev = evidence(
            "E-C1-LATER",
            "C1",
            AuthorizedAssertion.COMPOSITION_TRUE,
            text,
        )
        auth = scenario.authority_policy.authorize_candidate(
            evidence=ev,
            candidate=ev.candidate_assertions[0],
            authorization_id="AUTH-C1-LATER",
        )
        scenario.ledger.append_batch(
            recorded_at=T1 + timedelta(hours=1),
            entries=(
                PendingLedgerEntry(LedgerEntryKind.EVIDENCE, ev),
                PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, auth),
            ),
        )
        scenario.registry.add_authorization(
            ScopedAuthorization(
                authorization_id=auth.id,
                contract_artifact_id=scenario.contract_artifact.artifact_id,
                entity_id="C1",
                entity_definition_hash=entity_definition_hash(scenario.contract, "C1"),
                authorized_assertion=AuthorizedAssertion.COMPOSITION_TRUE,
                evidence_id=ev.id,
                policy_version=scenario.authority_policy.version,
                policy_hash=scenario.authority_policy.policy_hash,
                scope=AuthorizationScope.EVALUATION_DERIVED,
                scope_ref="EV-LATER",
                target_ref=scenario.target.ref,
            )
        )
        materialized = strict_materialize_committed_contract(
            registry=scenario.registry,
            ledger=scenario.ledger,
            commit=scenario.commit,
            authority_policy=scenario.authority_policy,
        )
        self.assertEqual(materialized.composition("C1").value, CompositionValue.NOT_DURABLY_RECORDED)

    def test_future_valid_world_evidence_cannot_leak_into_earlier_world_time(self):
        future = Scenario(apex_rate=0.987, apex_when=T1 + timedelta(days=30))
        evaluation = future.evaluation(evaluation_id="EV-BEFORE-FUTURE", world_time=T1)
        match_map = dict(evaluation.canonical_result.current_matches)
        self.assertEqual(match_map["M1"], "unknown")

    def test_conflicting_authorized_observations_become_unknown_not_last_write_wins(self):
        scenario = Scenario()
        conflict = raw_world(
            "WE-APEX-CONFLICT",
            metric="apex_on_time_rate",
            value=0.75,
            unit="ratio",
            when=T1,
            window_days=30,
        )
        auth = scenario.event_policy.authorize(raw=conflict, metric_specs=scenario.metric_specs)
        scenario.ledger.append_batch(
            recorded_at=T1 + timedelta(minutes=1),
            entries=(
                PendingLedgerEntry(LedgerEntryKind.RAW_WORLD_EVIDENCE, conflict),
                PendingLedgerEntry(LedgerEntryKind.WORLD_EVENT_AUTHORIZATION, auth),
            ),
        )
        state = authorized_world_state_at(
            ledger=scenario.ledger,
            cutoff_seq=scenario.ledger.head_seq,
            world_time=T1,
            event_policies=scenario.event_policies,
            metric_specs=scenario.metric_specs,
        )
        self.assertIsNone(state.observation("apex_on_time_rate"))

    def test_correction_of_evidence_deactivates_dependent_authorization_without_crash(self):
        scenario = Scenario()
        before = strict_materialize_committed_contract(
            registry=scenario.registry,
            ledger=scenario.ledger,
            commit=scenario.commit,
            authority_policy=scenario.authority_policy,
        )
        self.assertEqual(before.relation("R2").knowledge_state.value, "established")
        old_cutoff = scenario.commit.commit_cutoff_seq
        scenario.ledger.append_batch(
            recorded_at=T1 + timedelta(days=1),
            entries=(
                PendingLedgerEntry(
                    LedgerEntryKind.CORRECTION,
                    CorrectionRecord("CORR-E-R2", "E-R2-M21", "source record was invalid"),
                ),
            ),
        )
        # Old commit view remains immutable because its cutoff precedes correction.
        old = strict_materialize_committed_contract(
            registry=scenario.registry,
            ledger=scenario.ledger,
            commit=scenario.commit,
            authority_policy=scenario.authority_policy,
        )
        self.assertEqual(old.relation("R2").knowledge_state.value, "established")
        # Current effective dependency projection no longer considers AUTH-R2 active.
        current_ids = {
            entry.entry_id
            for entry in __import__("decision_recall.m21", fromlist=["active_entries_as_of"]).active_entries_as_of(
                scenario.ledger, scenario.ledger.head_seq
            )
        }
        self.assertNotIn("E-R2-M21", current_ids)
        self.assertNotIn("AUTH-R2-M21", current_ids)
        self.assertEqual(old_cutoff, scenario.commit.commit_cutoff_seq)

    def test_source_hash_tampering_is_rejected_on_authority_replay(self):
        scenario = Scenario()
        tampered = evidence(
            "E-TAMPER",
            "R1",
            AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
            "tampered body",
            hash_override=source_hash("different body"),
        )
        auth = scenario.authority_policy.authorize_candidate(
            evidence=tampered,
            candidate=tampered.candidate_assertions[0],
            authorization_id="AUTH-TAMPER",
        )
        ledger = InMemoryTemporalLedger()
        commit_record = DecisionCommitRecord(
            id="COMMIT-TAMPER",
            decision_id="D-104",
            contract_version="1",
            capture_profile_version="SUPPLIER_RESILIENCE_V1",
            capture_profile_hash="capture",
        )
        batch = ledger.append_batch(
            recorded_at=T0,
            entries=(
                PendingLedgerEntry(LedgerEntryKind.EVIDENCE, tampered),
                PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, auth),
                PendingLedgerEntry(LedgerEntryKind.DECISION_COMMIT, commit_record),
            ),
        )
        registry = M21Registry()
        registry.add_artifact(scenario.contract_artifact)
        registry.add_authorization(
            ScopedAuthorization(
                authorization_id=auth.id,
                contract_artifact_id=scenario.contract_artifact.artifact_id,
                entity_id="R1",
                entity_definition_hash=entity_definition_hash(scenario.contract, "R1"),
                authorized_assertion=AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
                evidence_id=tampered.id,
                policy_version=scenario.authority_policy.version,
                policy_hash=scenario.authority_policy.policy_hash,
                scope=AuthorizationScope.COMMIT_TIME,
                scope_ref=commit_record.id,
            )
        )
        commit = StrongDecisionCommit(
            commit_id=commit_record.id,
            decision_id="D-104",
            contract_artifact_id=scenario.contract_artifact.artifact_id,
            contract_hash=scenario.contract_artifact.content_hash,
            contract_version="1",
            capture_profile_version="SUPPLIER_RESILIENCE_V1",
            capture_profile_hash="capture",
            commit_cutoff_seq=batch.batch_seq,
        )
        registry.add_commit(commit)
        with self.assertRaisesRegex(TemporalIntegrityError, "content hash mismatch"):
            strict_materialize_committed_contract(
                registry=registry,
                ledger=ledger,
                commit=commit,
                authority_policy=scenario.authority_policy,
            )

    def test_canonicalization_is_versioned_and_stable_for_world_schema_mapping_order(self):
        specs = supplier_metric_specs()
        reversed_specs = dict(reversed(tuple(specs.items())))
        a = make_world_schema_artifact(specs, version="V1")
        b = make_world_schema_artifact(reversed_specs, version="V1")
        self.assertEqual(a.content_hash, b.content_hash)

    def test_strict_replay_verifies_stored_canonical_result(self):
        scenario = Scenario()
        evaluation = scenario.evaluation()
        replayed = strict_verify_full_replay(
            registry=scenario.registry,
            ledger=scenario.ledger,
            evaluation_id=evaluation.evaluation_id,
            authority_policy=scenario.authority_policy,
            event_policies=scenario.event_policies,
            engine_version=ENGINE_VERSION,
            engine_hash=ENGINE_HASH,
        )
        self.assertEqual(replayed, evaluation.canonical_result)


if __name__ == "__main__":
    unittest.main()
