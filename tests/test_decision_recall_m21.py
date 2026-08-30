import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from decision_recall.domain import (
    CompositionValue,
    HistoricalKnowledgeState,
    NumericObservation,
    ProvenanceType,
    SafeReuseResult,
)
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
    authorized_world_state_at,
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
    AuthorizationRecord,
    AuthorizedAssertion,
    AuthorityPolicy,
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
ENGINE_HASH = "engine-m21-test-sha"
COMMIT_ID = "COMMIT-D104-M21"


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


def raw_world(eid, *, metric, value, unit, when, window_days=None, hash_override=None):
    text = f"{metric}={value} {unit}"
    return RawWorldEvidence(
        id=eid,
        content=text,
        source_id=f"source-{eid}",
        source_span="ERP metric span",
        source_content_hash=hash_override or source_hash(text),
        provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
        temporal_reference=TemporalReference.point(when),
        observations=(NumericObservation(metric, value, unit=unit, window_days=window_days),),
    )


def authority_v2_like(v1):
    return AuthorityPolicy(
        version="AUTHORITY_V2",
        policy_hash="authority-v2-config-hash",
        allowed_provenance=v1.allowed_provenance,
    )


def event_v2():
    return EventPolicy(
        version="EVENT_V2",
        policy_hash="event-v2-config-hash",
        allowed_provenance=(ProvenanceType.CONTEMPORANEOUS_RECORD,),
    )


class Scenario:
    def __init__(
        self,
        *,
        apex_rate=0.987,
        apex_when=T1,
        omit_commit_authority=(),
        composition_assertions=(),
    ):
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

        authority_specs = [
            ("F1", AuthorizedAssertion.ESTABLISHED_FACT, "Apex delivery was materially variable."),
            ("F2", AuthorizedAssertion.ESTABLISHED_FACT, "Beacon reactivation was about 10 weeks."),
            ("R1", AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE, "Apex instability materially influenced D-104."),
            ("R2", AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE, "Beacon reaction capacity materially influenced D-104."),
            ("M1", AuthorizedAssertion.CURRENT_MATCH_RULE, "Use the Apex 97 percent / 30 day applicability criterion."),
            ("M2", AuthorizedAssertion.CURRENT_MATCH_RULE, "Use Beacon reactivation delay as the surviving applicability criterion."),
            ("RC1", AuthorizedAssertion.REVISIT_RULE, "Review redundancy after Apex reaches 97 percent for 30 days."),
        ]
        authority_specs.extend(
            ("C1", assertion, f"Contemporaneous C1 assertion: {assertion.value}")
            for assertion in composition_assertions
        )

        records = []
        omitted = set(omit_commit_authority)
        for entity_id, assertion, text in authority_specs:
            if entity_id in omitted:
                continue
            ev = evidence(f"E-{entity_id}-{assertion.value}-M21", entity_id, assertion, text)
            raw_auth = self.authority_policy.authorize_candidate(
                evidence=ev,
                candidate=ev.candidate_assertions[0],
                authorization_id=f"AUTH-{entity_id}-{assertion.value}-M21",
            )
            bound_auth = replace(
                raw_auth,
                contract_artifact_id=self.contract_artifact.artifact_id,
                entity_definition_hash=entity_definition_hash(self.contract, entity_id),
                scope=AuthorizationScope.COMMIT_TIME.value,
                scope_ref=COMMIT_ID,
            )
            records.extend(
                (
                    PendingLedgerEntry(LedgerEntryKind.EVIDENCE, ev),
                    PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, bound_auth),
                )
            )
            self.registry.add_authorization(
                ScopedAuthorization(
                    authorization_id=bound_auth.id,
                    contract_artifact_id=self.contract_artifact.artifact_id,
                    entity_id=entity_id,
                    entity_definition_hash=bound_auth.entity_definition_hash,
                    authorized_assertion=assertion,
                    evidence_id=ev.id,
                    policy_version=self.authority_policy.version,
                    policy_hash=self.authority_policy.policy_hash,
                    scope=AuthorizationScope.COMMIT_TIME,
                    scope_ref=COMMIT_ID,
                )
            )

        ledger_commit = DecisionCommitRecord(
            id=COMMIT_ID,
            decision_id="D-104",
            contract_version="1",
            capture_profile_version="SUPPLIER_RESILIENCE_V1",
            capture_profile_hash="capture-profile-hash-v1",
            contract_artifact_id=self.contract_artifact.artifact_id,
            contract_hash=self.contract_artifact.content_hash,
            canonicalization_version=CANONICALIZATION_V1,
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

    def draft_evaluation(self, *, evaluation_id="EV-901-M21", world_time=T1, evaluation_policy=None):
        policy = evaluation_policy or self.authority_policy
        placeholder = CanonicalEvaluationResult("placeholder", (), (), (), ())
        return StrongEvaluationSnapshot(
            evaluation_id=evaluation_id,
            decision_commit_id=self.commit.commit_id,
            contract_hash=self.commit.contract_hash,
            input_cutoff_seq=self.ledger.head_seq,
            world_time=world_time,
            target_artifact_id=self.target_artifact.artifact_id,
            target_hash=self.target_artifact.content_hash,
            world_schema_artifact_id=self.schema_artifact.artifact_id,
            world_schema_hash=self.schema_artifact.content_hash,
            authority_policy_version=policy.version,
            authority_policy_hash=policy.policy_hash,
            event_policy_version=self.event_policy.version,
            event_policy_hash=self.event_policy.policy_hash,
            engine_version=ENGINE_VERSION,
            engine_hash=ENGINE_HASH,
            canonical_result=placeholder,
            result_hash=placeholder.result_hash(),
        )

    def persist_evaluation_output(self, final):
        output = EvaluationSnapshot(
            id=final.evaluation_id,
            decision_id="D-104",
            input_cutoff_seq=final.input_cutoff_seq,
            target_version=self.target.version,
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
        self.ledger.append_batch(
            recorded_at=final.world_time + timedelta(seconds=1),
            entries=(PendingLedgerEntry(LedgerEntryKind.EVALUATION, output),),
        )

    def evaluation(self, *, evaluation_id="EV-901-M21", world_time=T1, evaluation_policy=None, authority_policies=None):
        draft = self.draft_evaluation(
            evaluation_id=evaluation_id,
            world_time=world_time,
            evaluation_policy=evaluation_policy,
        )
        policies = dict(authority_policies or {})
        policies[(self.authority_policy.version, self.authority_policy.policy_hash)] = self.authority_policy
        if evaluation_policy is not None:
            policies[(evaluation_policy.version, evaluation_policy.policy_hash)] = evaluation_policy
        result = strict_full_replay(
            registry=self.registry,
            ledger=self.ledger,
            evaluation=draft,
            authority_policies=policies,
            event_policies=self.event_policies,
            engine_version=ENGINE_VERSION,
            engine_hash=ENGINE_HASH,
        )
        final = replace(draft, canonical_result=result, result_hash=result.result_hash())
        self.registry.add_evaluation(final)
        self.persist_evaluation_output(final)
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

    def test_contract_mutation_changes_artifact_identity(self):
        scenario = Scenario()
        changed = replace(scenario.contract, action="keep_only_beacon_active")
        changed_artifact = make_contract_artifact(changed, version="1")
        self.assertNotEqual(changed_artifact.content_hash, scenario.contract_artifact.content_hash)

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

    def test_future_valid_world_evidence_cannot_leak_into_earlier_world_time(self):
        scenario = Scenario(apex_rate=0.987, apex_when=T1 + timedelta(days=30))
        evaluation = scenario.evaluation(evaluation_id="EV-BEFORE-FUTURE", world_time=T1)
        self.assertEqual(dict(evaluation.canonical_result.current_matches)["M1"], "unknown")

    def test_conflicting_authorized_observations_become_unknown_not_last_write_wins(self):
        scenario = Scenario()
        conflict = raw_world(
            "WE-APEX-CONFLICT", metric="apex_on_time_rate", value=0.75, unit="ratio", when=T1, window_days=30
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
            required_policy_ref=(scenario.event_policy.version, scenario.event_policy.policy_hash),
        )
        self.assertIsNone(state.observation("apex_on_time_rate"))

    def test_correction_of_evidence_deactivates_dependent_authorization_without_crash(self):
        scenario = Scenario()
        before = strict_materialize_committed_contract(
            registry=scenario.registry, ledger=scenario.ledger, commit=scenario.commit, authority_policy=scenario.authority_policy
        )
        self.assertEqual(before.relation("R2").knowledge_state, HistoricalKnowledgeState.ESTABLISHED)
        scenario.ledger.append_batch(
            recorded_at=T1 + timedelta(days=1),
            entries=(PendingLedgerEntry(LedgerEntryKind.CORRECTION, CorrectionRecord("CORR-E-R2", "E-R2-established_historical_role-M21", "source invalid")),),
        )
        old = strict_materialize_committed_contract(
            registry=scenario.registry, ledger=scenario.ledger, commit=scenario.commit, authority_policy=scenario.authority_policy
        )
        self.assertEqual(old.relation("R2").knowledge_state, HistoricalKnowledgeState.ESTABLISHED)

    def test_canonicalization_is_versioned_and_stable_for_world_schema_mapping_order(self):
        specs = supplier_metric_specs()
        reversed_specs = dict(reversed(tuple(specs.items())))
        self.assertEqual(
            make_world_schema_artifact(specs, version="V1").content_hash,
            make_world_schema_artifact(reversed_specs, version="V1").content_hash,
        )

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

    # M — registry metadata added later cannot create commit-time authority.
    def test_m_retroactive_registry_scope_binding_cannot_enter_t0(self):
        scenario = Scenario()
        scenario.registry.add_authorization(
            ScopedAuthorization(
                authorization_id="AUTH-POSTHOC-C1",
                contract_artifact_id=scenario.contract_artifact.artifact_id,
                entity_id="C1",
                entity_definition_hash=entity_definition_hash(scenario.contract, "C1"),
                authorized_assertion=AuthorizedAssertion.COMPOSITION_TRUE,
                evidence_id="NONEXISTENT",
                policy_version=scenario.authority_policy.version,
                policy_hash=scenario.authority_policy.policy_hash,
                scope=AuthorizationScope.COMMIT_TIME,
                scope_ref=scenario.commit.commit_id,
            )
        )
        materialized = strict_materialize_committed_contract(
            registry=scenario.registry,
            ledger=scenario.ledger,
            commit=scenario.commit,
            authority_policy=scenario.authority_policy,
        )
        self.assertEqual(materialized.composition("C1").value, CompositionValue.NOT_DURABLY_RECORDED)

    # N — caller cannot inflate the commit cutoff beyond the actual commit batch.
    def test_n_inflated_commit_cutoff_is_rejected(self):
        scenario = Scenario()
        inflated = replace(scenario.commit, commit_cutoff_seq=scenario.commit.commit_cutoff_seq + 1)
        with self.assertRaisesRegex(TemporalIntegrityError, "actual ledger commit batch"):
            strict_materialize_committed_contract(
                registry=scenario.registry,
                ledger=scenario.ledger,
                commit=inflated,
                authority_policy=scenario.authority_policy,
            )

    # O — EV frozen to EVENT_V1 cannot consume EVENT_V2 authorizations.
    def test_o_event_policy_contamination_is_blocked(self):
        scenario = Scenario(apex_rate=0.987)
        v2 = event_v2()
        bad = raw_world("WE-V2-CONFLICT", metric="apex_on_time_rate", value=0.2, unit="ratio", when=T1, window_days=30)
        auth = v2.authorize(raw=bad, metric_specs=scenario.metric_specs)
        scenario.ledger.append_batch(
            recorded_at=T1 + timedelta(minutes=2),
            entries=(
                PendingLedgerEntry(LedgerEntryKind.RAW_WORLD_EVIDENCE, bad),
                PendingLedgerEntry(LedgerEntryKind.WORLD_EVENT_AUTHORIZATION, auth),
            ),
        )
        scenario.event_policies[(v2.version, v2.policy_hash)] = v2
        ev = scenario.evaluation(evaluation_id="EV-POLICY-ISOLATED")
        self.assertEqual(dict(ev.canonical_result.current_matches)["M1"], "does_not_match")

    # P — entity identity excludes epistemic state/provenance but changes with semantics.
    def test_p_semantic_hash_is_stable_across_epistemic_state(self):
        scenario = Scenario()
        original = scenario.contract.relation("R1")
        epistemically_changed = replace(
            original,
            knowledge_state=HistoricalKnowledgeState.NOT_DURABLY_RECORDED,
            evidence_refs=(),
            authorization_policy_version="",
        )
        c2 = replace(
            scenario.contract,
            historical_relations=tuple(epistemically_changed if r.id == "R1" else r for r in scenario.contract.historical_relations),
        )
        self.assertEqual(entity_definition_hash(scenario.contract, "R1"), entity_definition_hash(c2, "R1"))
        semantically_changed = replace(original, subject_id="F2")
        c3 = replace(
            scenario.contract,
            historical_relations=tuple(semantically_changed if r.id == "R1" else r for r in scenario.contract.historical_relations),
        )
        self.assertNotEqual(entity_definition_hash(scenario.contract, "R1"), entity_definition_hash(c3, "R1"))

    # Q — commit authority replays under its historical policy, not the later EV policy.
    def test_q_historical_policy_is_separate_from_evaluation_policy(self):
        scenario = Scenario()
        v2 = authority_v2_like(scenario.authority_policy)
        ev = scenario.evaluation(
            evaluation_id="EV-AUTH-V2",
            evaluation_policy=v2,
            authority_policies={(v2.version, v2.policy_hash): v2},
        )
        self.assertIn(ev.canonical_result.safe_reuse_result, {item.value for item in SafeReuseResult})

    # R — malformed world input outside the frozen EventPolicy cannot poison replay.
    def test_r_irrelevant_malformed_world_input_is_isolated(self):
        scenario = Scenario(apex_rate=0.987)
        v2 = event_v2()
        bad = raw_world(
            "WE-V2-BAD-HASH",
            metric="apex_on_time_rate",
            value=0.1,
            unit="ratio",
            when=T1,
            window_days=30,
            hash_override="0" * 64,
        )
        auth = v2.authorize(raw=bad, metric_specs=scenario.metric_specs)
        scenario.ledger.append_batch(
            recorded_at=T1 + timedelta(minutes=3),
            entries=(
                PendingLedgerEntry(LedgerEntryKind.RAW_WORLD_EVIDENCE, bad),
                PendingLedgerEntry(LedgerEntryKind.WORLD_EVENT_AUTHORIZATION, auth),
            ),
        )
        scenario.event_policies[(v2.version, v2.policy_hash)] = v2
        ev = scenario.evaluation(evaluation_id="EV-IGNORES-V2-BAD")
        self.assertEqual(dict(ev.canonical_result.current_matches)["M1"], "does_not_match")

    # S — target cannot consume a rule merely because it is present in the artifact.
    def test_s_missing_target_semantic_authority_fails_closed(self):
        scenario = Scenario(omit_commit_authority={"M1"})
        draft = scenario.draft_evaluation(evaluation_id="EV-MISSING-M1")
        with self.assertRaisesRegex(TemporalIntegrityError, "MISSING_COMMIT_TIME_SEMANTIC_AUTHORITY:M1"):
            strict_full_replay(
                registry=scenario.registry,
                ledger=scenario.ledger,
                evaluation=draft,
                authority_policy=scenario.authority_policy,
                event_policies=scenario.event_policies,
                engine_version=ENGINE_VERSION,
                engine_hash=ENGINE_HASH,
            )

    def test_s_known_c1_slot_without_sufficiency_authority_remains_not_recorded(self):
        scenario = Scenario()
        materialized = strict_materialize_committed_contract(
            registry=scenario.registry,
            ledger=scenario.ledger,
            commit=scenario.commit,
            authority_policy=scenario.authority_policy,
            target=scenario.target,
        )
        self.assertEqual(materialized.composition("C1").value, CompositionValue.NOT_DURABLY_RECORDED)

    # T — contradictory authority cannot resolve by if/elif ordering.
    def test_t_conflicting_composition_authority_fails_closed(self):
        scenario = Scenario(
            composition_assertions=(AuthorizedAssertion.COMPOSITION_TRUE, AuthorizedAssertion.COMPOSITION_FALSE)
        )
        with self.assertRaisesRegex(TemporalIntegrityError, "CONFLICTING_AUTHORIZED_ASSERTIONS:C1"):
            strict_materialize_committed_contract(
                registry=scenario.registry,
                ledger=scenario.ledger,
                commit=scenario.commit,
                authority_policy=scenario.authority_policy,
                target=scenario.target,
            )

    # U — registry result added later is insufficient; EV output itself must be ledger-bound.
    def test_u_evaluation_result_backfill_without_output_batch_is_rejected(self):
        scenario = Scenario()
        draft = scenario.draft_evaluation(evaluation_id="EV-BACKFILL")
        result = strict_full_replay(
            registry=scenario.registry,
            ledger=scenario.ledger,
            evaluation=draft,
            authority_policy=scenario.authority_policy,
            event_policies=scenario.event_policies,
            engine_version=ENGINE_VERSION,
            engine_hash=ENGINE_HASH,
        )
        final = replace(draft, canonical_result=result, result_hash=result.result_hash())
        scenario.registry.add_evaluation(final)
        with self.assertRaisesRegex(TemporalIntegrityError, "not temporally recorded"):
            strict_verify_full_replay(
                registry=scenario.registry,
                ledger=scenario.ledger,
                evaluation_id=final.evaluation_id,
                authority_policy=scenario.authority_policy,
                event_policies=scenario.event_policies,
                engine_version=ENGINE_VERSION,
                engine_hash=ENGINE_HASH,
            )


if __name__ == "__main__":
    unittest.main()
