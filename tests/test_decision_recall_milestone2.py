import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from decision_recall.domain import (
    CompositionValue,
    HistoricalKnowledgeState,
    NumericObservation,
    ProvenanceType,
)
from decision_recall.golden import supplier_metric_specs
from decision_recall.temporal import (
    AuthorizationRecord,
    AuthorizedAssertion,
    CandidateAssertion,
    CorrectionRecord,
    DecisionCommitRecord,
    EvaluationSnapshot,
    InMemoryTemporalLedger,
    LedgerEntryKind,
    PendingLedgerEntry,
    RawWorldEvidence,
    TemporalEvidenceRecord,
    TemporalIntegrityError,
    TemporalReference,
    WorldEventAuthorizationRecord,
    authority_policy_v1,
    authorized_world_state_as_of,
    canonical_replay_fingerprint,
    current_assessment_candidates_about,
    event_policy_v1,
    recorded_historical_view,
    replay_authority_from_evidence,
    source_hash,
)


UTC = timezone.utc
T0 = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)


def ev(
    evidence_id,
    *,
    entity_id,
    assertion,
    content="decision-time evidence",
    provenance=ProvenanceType.CONTEMPORANEOUS_RECORD,
    about=T0,
):
    return TemporalEvidenceRecord(
        id=evidence_id,
        content=content,
        source_id=f"source-{evidence_id}",
        source_span="lines 1-2",
        source_content_hash=source_hash(content),
        provenance_type=provenance,
        temporal_reference=TemporalReference.point(about),
        candidate_assertions=(CandidateAssertion(entity_id, assertion),),
    )


class Milestone2TemporalAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.policy = authority_policy_v1()
        self.policy_registry = {
            (self.policy.version, self.policy.policy_hash): self.policy,
        }
        self.event_policy = event_policy_v1()
        self.event_registry = {
            (self.event_policy.version, self.event_policy.policy_hash): self.event_policy,
        }
        self.metrics = supplier_metric_specs()

    def append(self, ledger, when, *entries):
        return ledger.append_batch(recorded_at=when, entries=entries)

    def authorize(self, evidence, *, auth_id):
        candidate = evidence.candidate_assertions[0]
        return self.policy.authorize_candidate(
            evidence=evidence,
            candidate=candidate,
            authorization_id=auth_id,
        )

    def test_a_hindsight_leakage_future_old_email_is_invisible_to_earlier_cutoff(self):
        ledger = InMemoryTemporalLedger()
        r2 = ev(
            "E-R2",
            entity_id="R2",
            assertion=AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
            content="Reaction capacity materially influenced D-104.",
        )
        self.append(
            ledger,
            T0,
            PendingLedgerEntry(LedgerEntryKind.EVIDENCE, r2),
        )
        cutoff = ledger.head_seq
        before = replay_authority_from_evidence(
            ledger, input_cutoff_seq=cutoff, policy=self.policy
        )

        old_email_found_late = ev(
            "E-C1-LATE-EMAIL",
            entity_id="C1",
            assertion=AuthorizedAssertion.COMPOSITION_TRUE,
            content="Beacon reaction capacity alone was sufficient.",
            about=T0,
        )
        self.append(
            ledger,
            T2,
            PendingLedgerEntry(LedgerEntryKind.EVIDENCE, old_email_found_late),
        )

        replay_same_cutoff = replay_authority_from_evidence(
            ledger, input_cutoff_seq=cutoff, policy=self.policy
        )
        after = replay_authority_from_evidence(
            ledger, input_cutoff_seq=ledger.head_seq, policy=self.policy
        )
        self.assertEqual(before, replay_same_cutoff)
        self.assertNotIn(("C1", AuthorizedAssertion.COMPOSITION_TRUE), replay_same_cutoff)
        self.assertIn(("C1", AuthorizedAssertion.COMPOSITION_TRUE), after)

    def test_b1_commit_authority_leakage_late_authorization_cannot_rewrite_commit_view(self):
        ledger = InMemoryTemporalLedger()
        r2 = ev(
            "E-R2",
            entity_id="R2",
            assertion=AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
        )
        self.append(ledger, T0, PendingLedgerEntry(LedgerEntryKind.EVIDENCE, r2))
        commit = DecisionCommitRecord(
            id="COMMIT-D104",
            decision_id="D-104",
            contract_version="1",
            capture_profile_version="SUPPLIER_RESILIENCE_V1",
            capture_profile_hash="capture-hash-v1",
        )
        self.append(ledger, T0 + timedelta(minutes=1), PendingLedgerEntry(LedgerEntryKind.DECISION_COMMIT, commit))
        commit_cutoff = ledger.head_seq

        late_auth = self.authorize(r2, auth_id="AUTH-R2-LATE")
        self.append(ledger, T1, PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, late_auth))

        commit_view = recorded_historical_view(
            ledger, cutoff_seq=commit_cutoff, policies=self.policy_registry
        )
        current_view = recorded_historical_view(
            ledger, cutoff_seq=ledger.head_seq, policies=self.policy_registry
        )
        self.assertEqual(
            commit_view.relation_state("R2"),
            HistoricalKnowledgeState.NOT_DURABLY_RECORDED,
        )
        self.assertEqual(current_view.relation_state("R2"), HistoricalKnowledgeState.ESTABLISHED)

    def test_b2_evaluation_can_derive_authority_from_pre_cutoff_evidence(self):
        ledger = InMemoryTemporalLedger()
        r2 = ev(
            "E-R2",
            entity_id="R2",
            assertion=AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
        )
        self.append(ledger, T0, PendingLedgerEntry(LedgerEntryKind.EVIDENCE, r2))
        cutoff = ledger.head_seq
        derived = replay_authority_from_evidence(
            ledger, input_cutoff_seq=cutoff, policy=self.policy
        )
        self.assertIn(("R2", AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE), derived)
        # No first-class historical authorization was required to pre-exist this
        # evaluation input cutoff; it is a deterministic evaluation-time conclusion.
        recorded = recorded_historical_view(
            ledger, cutoff_seq=cutoff, policies=self.policy_registry
        )
        self.assertEqual(
            recorded.relation_state("R2"),
            HistoricalKnowledgeState.NOT_DURABLY_RECORDED,
        )

    def test_c_false_historical_unknown_defaults_to_not_durably_recorded(self):
        ledger = InMemoryTemporalLedger()
        r2 = ev(
            "E-R2",
            entity_id="R2",
            assertion=AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
        )
        auth = self.authorize(r2, auth_id="AUTH-R2")
        self.append(
            ledger,
            T0,
            PendingLedgerEntry(LedgerEntryKind.EVIDENCE, r2),
            PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, auth),
        )
        view = recorded_historical_view(
            ledger, cutoff_seq=ledger.head_seq, policies=self.policy_registry
        )
        self.assertEqual(view.composition_state("C1"), CompositionValue.NOT_DURABLY_RECORDED)
        self.assertNotEqual(view.composition_state("C1"), CompositionValue.T0_UNRESOLVED)

    def test_c_t0_unresolved_requires_contemporaneous_authority(self):
        ledger = InMemoryTemporalLedger()
        c1 = ev(
            "E-C1",
            entity_id="C1",
            assertion=AuthorizedAssertion.T0_UNRESOLVED,
            content="At commit time we explicitly had not established whether R2 alone was sufficient.",
        )
        auth = self.authorize(c1, auth_id="AUTH-C1-UNRESOLVED")
        self.append(
            ledger,
            T0,
            PendingLedgerEntry(LedgerEntryKind.EVIDENCE, c1),
            PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, auth),
        )
        view = recorded_historical_view(
            ledger, cutoff_seq=ledger.head_seq, policies=self.policy_registry
        )
        self.assertEqual(view.composition_state("C1"), CompositionValue.T0_UNRESOLVED)

    def test_d_later_retrospective_evidence_never_upgrades_original_t0_view(self):
        ledger = InMemoryTemporalLedger()
        commit = DecisionCommitRecord(
            id="COMMIT-D104",
            decision_id="D-104",
            contract_version="1",
            capture_profile_version="SUPPLIER_RESILIENCE_V1",
            capture_profile_hash="capture-hash-v1",
        )
        self.append(ledger, T0, PendingLedgerEntry(LedgerEntryKind.DECISION_COMMIT, commit))
        commit_cutoff = ledger.head_seq

        retrospective = ev(
            "E-C1-RETRO",
            entity_id="C1",
            assertion=AuthorizedAssertion.T0_UNRESOLVED,
            content="We never established whether reaction capacity alone was sufficient.",
            provenance=ProvenanceType.RETROSPECTIVE_DECLARATION,
            about=T0,
        )
        self.append(ledger, T2, PendingLedgerEntry(LedgerEntryKind.EVIDENCE, retrospective))

        original = recorded_historical_view(
            ledger, cutoff_seq=commit_cutoff, policies=self.policy_registry
        )
        current_recorded = recorded_historical_view(
            ledger, cutoff_seq=ledger.head_seq, policies=self.policy_registry
        )
        candidates = current_assessment_candidates_about(
            ledger, entity_id="C1", cutoff_seq=ledger.head_seq
        )
        self.assertEqual(original.composition_state("C1"), CompositionValue.NOT_DURABLY_RECORDED)
        self.assertEqual(current_recorded.composition_state("C1"), CompositionValue.NOT_DURABLY_RECORDED)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][2], ProvenanceType.RETROSPECTIVE_DECLARATION)
        with self.assertRaises(TemporalIntegrityError):
            self.authorize(retrospective, auth_id="AUTH-C1-RETRO")

    def test_e_deterministic_replay_fingerprint_is_stable_and_version_sensitive(self):
        ledger = InMemoryTemporalLedger()
        r2 = ev(
            "E-R2",
            entity_id="R2",
            assertion=AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
        )
        self.append(ledger, T0, PendingLedgerEntry(LedgerEntryKind.EVIDENCE, r2))
        kwargs = dict(
            ledger=ledger,
            input_cutoff_seq=ledger.head_seq,
            authority_policy=self.policy,
            target_version="SAFE_REUSE_V1",
            target_hash="target-hash-1",
            engine_version="0.2.0",
            engine_hash="engine-sha-1",
        )
        first = canonical_replay_fingerprint(**kwargs)
        second = canonical_replay_fingerprint(**kwargs)
        changed_target = canonical_replay_fingerprint(
            **{**kwargs, "target_hash": "target-hash-2"}
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed_target)

    def test_atomic_batch_has_no_supported_mid_batch_cutoff(self):
        ledger = InMemoryTemporalLedger()
        r2 = ev(
            "E-R2",
            entity_id="R2",
            assertion=AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
        )
        auth = self.authorize(r2, auth_id="AUTH-R2")
        commit = DecisionCommitRecord(
            id="COMMIT-D104",
            decision_id="D-104",
            contract_version="1",
            capture_profile_version="SUPPLIER_RESILIENCE_V1",
            capture_profile_hash="capture-hash-v1",
        )
        batch = self.append(
            ledger,
            T0,
            PendingLedgerEntry(LedgerEntryKind.EVIDENCE, r2),
            PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, auth),
            PendingLedgerEntry(LedgerEntryKind.DECISION_COMMIT, commit),
        )
        self.assertEqual(batch.batch_seq, 1)
        self.assertEqual([e.entry_ordinal for e in batch.entries], [1, 2, 3])
        self.assertEqual(len(ledger.entries_as_of(0)), 0)
        self.assertEqual(len(ledger.entries_as_of(1)), 3)

    def test_invalid_batch_rolls_back_entire_in_memory_batch(self):
        ledger = InMemoryTemporalLedger()
        bad_auth = AuthorizationRecord(
            id="AUTH-MISSING",
            entity_id="R2",
            authorized_assertion=AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
            evidence_ids=("MISSING-EVIDENCE",),
            policy_version=self.policy.version,
            policy_hash=self.policy.policy_hash,
        )
        with self.assertRaises(TemporalIntegrityError):
            self.append(
                ledger,
                T0,
                PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, bad_auth),
            )
        self.assertEqual(ledger.head_seq, 0)
        self.assertEqual(ledger.entries_as_of(0), ())

    def test_fabricated_authorization_with_unknown_policy_hash_is_rejected_by_projection(self):
        ledger = InMemoryTemporalLedger()
        r2 = ev(
            "E-R2",
            entity_id="R2",
            assertion=AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
        )
        fake = AuthorizationRecord(
            id="AUTH-R2-FAKE",
            entity_id="R2",
            authorized_assertion=AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
            evidence_ids=(r2.id,),
            policy_version=self.policy.version,
            policy_hash="not-the-real-policy-hash",
        )
        self.append(
            ledger,
            T0,
            PendingLedgerEntry(LedgerEntryKind.EVIDENCE, r2),
            PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, fake),
        )
        with self.assertRaises(TemporalIntegrityError):
            recorded_historical_view(
                ledger, cutoff_seq=ledger.head_seq, policies=self.policy_registry
            )

    def test_evaluation_input_cutoff_cannot_include_its_own_future_output_batch(self):
        ledger = InMemoryTemporalLedger()
        snapshot = EvaluationSnapshot(
            id="EV-901",
            decision_id="D-104",
            input_cutoff_seq=1,
            target_version="SAFE_REUSE_V1",
            target_hash="target-hash",
            evidence_policy_version=self.policy.version,
            evidence_policy_hash=self.policy.policy_hash,
            event_policy_version=self.event_policy.version,
            event_policy_hash=self.event_policy.policy_hash,
            engine_version="0.2.0",
            engine_hash="engine-sha",
            result_fingerprint="fingerprint",
        )
        with self.assertRaises(TemporalIntegrityError):
            self.append(
                ledger,
                T0,
                PendingLedgerEntry(LedgerEntryKind.EVALUATION, snapshot),
            )

    def test_world_evidence_without_first_class_authorization_is_invisible(self):
        ledger = InMemoryTemporalLedger()
        raw = RawWorldEvidence(
            id="WE-301",
            content="Apex OTD 98.7% over preceding 30 days",
            source_id="ERP_SUPPLIER_PERFORMANCE",
            source_span="Apex row",
            source_content_hash=source_hash("Apex OTD 98.7% over preceding 30 days"),
            provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
            temporal_reference=TemporalReference.interval(T1 - timedelta(days=30), T1),
            observations=(
                NumericObservation("apex_on_time_rate", 0.987, unit="ratio", window_days=30),
            ),
        )
        self.append(ledger, T1, PendingLedgerEntry(LedgerEntryKind.RAW_WORLD_EVIDENCE, raw))
        before_auth = authorized_world_state_as_of(
            ledger,
            cutoff_seq=ledger.head_seq,
            policies=self.event_registry,
            metric_specs=self.metrics,
        )
        self.assertIsNone(before_auth.observation("apex_on_time_rate"))

        world_auth = self.event_policy.authorize(raw=raw, metric_specs=self.metrics)
        self.append(
            ledger,
            T1 + timedelta(seconds=1),
            PendingLedgerEntry(LedgerEntryKind.WORLD_EVENT_AUTHORIZATION, world_auth),
        )
        after_auth = authorized_world_state_as_of(
            ledger,
            cutoff_seq=ledger.head_seq,
            policies=self.event_registry,
            metric_specs=self.metrics,
        )
        apex = after_auth.observation("apex_on_time_rate")
        self.assertEqual(apex.value, 0.987)
        self.assertEqual(apex.source_event_id, world_auth.event_id)

    def test_late_arriving_older_world_evidence_does_not_overwrite_newer_valid_time(self):
        ledger = InMemoryTemporalLedger()
        newer = RawWorldEvidence(
            id="WE-NEW",
            content="Apex OTD 98.7%",
            source_id="ERP",
            source_span="row-new",
            source_content_hash=source_hash("Apex OTD 98.7%"),
            provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
            temporal_reference=TemporalReference.interval(T1 - timedelta(days=30), T1),
            observations=(NumericObservation("apex_on_time_rate", 0.987, unit="ratio", window_days=30),),
        )
        newer_auth = self.event_policy.authorize(raw=newer, metric_specs=self.metrics)
        self.append(
            ledger,
            T1,
            PendingLedgerEntry(LedgerEntryKind.RAW_WORLD_EVIDENCE, newer),
            PendingLedgerEntry(LedgerEntryKind.WORLD_EVENT_AUTHORIZATION, newer_auth),
        )
        older = RawWorldEvidence(
            id="WE-OLD-LATE",
            content="Older Apex OTD 83%",
            source_id="ERP-ARCHIVE",
            source_span="row-old",
            source_content_hash=source_hash("Older Apex OTD 83%"),
            provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
            temporal_reference=TemporalReference.interval(T0 - timedelta(days=30), T0),
            observations=(NumericObservation("apex_on_time_rate", 0.83, unit="ratio", window_days=30),),
        )
        older_auth = self.event_policy.authorize(raw=older, metric_specs=self.metrics)
        self.append(
            ledger,
            T2,
            PendingLedgerEntry(LedgerEntryKind.RAW_WORLD_EVIDENCE, older),
            PendingLedgerEntry(LedgerEntryKind.WORLD_EVENT_AUTHORIZATION, older_auth),
        )
        state = authorized_world_state_as_of(
            ledger,
            cutoff_seq=ledger.head_seq,
            policies=self.event_registry,
            metric_specs=self.metrics,
        )
        self.assertEqual(state.observation("apex_on_time_rate").value, 0.987)

    def test_correction_changes_current_projection_without_rewriting_prior_view(self):
        ledger = InMemoryTemporalLedger()
        raw = RawWorldEvidence(
            id="WE-301",
            content="Apex OTD 98.7%",
            source_id="ERP",
            source_span="row",
            source_content_hash=source_hash("Apex OTD 98.7%"),
            provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
            temporal_reference=TemporalReference.point(T1),
            observations=(NumericObservation("apex_on_time_rate", 0.987, unit="ratio", window_days=30),),
        )
        auth = self.event_policy.authorize(raw=raw, metric_specs=self.metrics)
        self.append(
            ledger,
            T1,
            PendingLedgerEntry(LedgerEntryKind.RAW_WORLD_EVIDENCE, raw),
            PendingLedgerEntry(LedgerEntryKind.WORLD_EVENT_AUTHORIZATION, auth),
        )
        before_correction_cutoff = ledger.head_seq
        correction = CorrectionRecord(
            id="CORR-301",
            corrects_entry_id=auth.id,
            reason="ERP event authorization was based on a bad import",
        )
        self.append(
            ledger,
            T2,
            PendingLedgerEntry(LedgerEntryKind.CORRECTION, correction),
        )
        old_view = authorized_world_state_as_of(
            ledger,
            cutoff_seq=before_correction_cutoff,
            policies=self.event_registry,
            metric_specs=self.metrics,
        )
        current_view = authorized_world_state_as_of(
            ledger,
            cutoff_seq=ledger.head_seq,
            policies=self.event_registry,
            metric_specs=self.metrics,
        )
        self.assertEqual(old_view.observation("apex_on_time_rate").value, 0.987)
        self.assertIsNone(current_view.observation("apex_on_time_rate"))

    def test_temporal_reference_and_evidence_lineage_validation(self):
        ledger = InMemoryTemporalLedger()
        malformed = TemporalEvidenceRecord(
            id="E-BAD",
            content="",
            source_id="",
            source_span="",
            source_content_hash="",
            provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
            temporal_reference=TemporalReference.point(datetime(2026, 8, 23, 12, 0)),
            candidate_assertions=(),
        )
        with self.assertRaises(TemporalIntegrityError):
            self.append(
                ledger,
                T0,
                PendingLedgerEntry(LedgerEntryKind.EVIDENCE, malformed),
            )


if __name__ == "__main__":
    unittest.main()
