import unittest
from datetime import datetime, timezone

from decision_recall.domain import ProvenanceType
from decision_recall.temporal import (
    AuthorizedAssertion,
    CandidateAssertion,
    DecisionCommitRecord,
    EvaluationSnapshot,
    InMemoryTemporalLedger,
    LedgerEntryKind,
    PendingLedgerEntry,
    TemporalEvidenceRecord,
    TemporalReference,
    authority_policy_v1,
    canonical_replay_fingerprint,
    recorded_historical_view,
    source_hash,
)


UTC = timezone.utc
T0 = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)


def evidence(evidence_id, assertions, content):
    return TemporalEvidenceRecord(
        id=evidence_id,
        content=content,
        source_id=f"source-{evidence_id}",
        source_span="decision-time source span",
        source_content_hash=source_hash(content),
        provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
        temporal_reference=TemporalReference.point(T0),
        candidate_assertions=tuple(assertions),
    )


class Milestone2AuthorityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.policy = authority_policy_v1()
        self.registry = {(self.policy.version, self.policy.policy_hash): self.policy}

    def test_same_threshold_source_does_not_merge_applicability_and_revisit_authority(self):
        ledger = InMemoryTemporalLedger()
        source = evidence(
            "E-THRESHOLD",
            (
                CandidateAssertion("AP1", AuthorizedAssertion.CURRENT_MATCH_RULE),
                CandidateAssertion("RC1", AuthorizedAssertion.REVISIT_RULE),
            ),
            "97% OTD for 30 days is the applicability criterion and separately the review trigger.",
        )
        ap_auth = self.policy.authorize_candidate(
            evidence=source,
            candidate=CandidateAssertion("AP1", AuthorizedAssertion.CURRENT_MATCH_RULE),
            authorization_id="AUTH-AP1",
        )
        rc_auth = self.policy.authorize_candidate(
            evidence=source,
            candidate=CandidateAssertion("RC1", AuthorizedAssertion.REVISIT_RULE),
            authorization_id="AUTH-RC1",
        )
        ledger.append_batch(
            recorded_at=T0,
            entries=(
                PendingLedgerEntry(LedgerEntryKind.EVIDENCE, source),
                PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, ap_auth),
                PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, rc_auth),
            ),
        )
        view = recorded_historical_view(
            ledger,
            cutoff_seq=ledger.head_seq,
            policies=self.registry,
        )
        self.assertEqual(view.assertions_for("AP1"), (AuthorizedAssertion.CURRENT_MATCH_RULE,))
        self.assertEqual(view.assertions_for("RC1"), (AuthorizedAssertion.REVISIT_RULE,))
        self.assertNotEqual(view.assertions_for("AP1"), view.assertions_for("RC1"))

    def test_fact_role_applicability_and_revisit_are_independently_authorized(self):
        ledger = InMemoryTemporalLedger()
        records = (
            evidence(
                "E-F1",
                (CandidateAssertion("F1", AuthorizedAssertion.ESTABLISHED_FACT),),
                "Apex delivery was materially variable.",
            ),
            evidence(
                "E-R1",
                (CandidateAssertion("R1", AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE),),
                "Apex instability materially influenced D-104.",
            ),
            evidence(
                "E-AP1",
                (CandidateAssertion("AP1", AuthorizedAssertion.CURRENT_MATCH_RULE),),
                "Apex instability counts as currently matching below the agreed reliability criterion.",
            ),
            evidence(
                "E-RC1",
                (CandidateAssertion("RC1", AuthorizedAssertion.REVISIT_RULE),),
                "If Apex reaches the criterion for 30 days, review D-104.",
            ),
        )
        pending = []
        for record in records:
            pending.append(PendingLedgerEntry(LedgerEntryKind.EVIDENCE, record))
            auth = self.policy.authorize_candidate(
                evidence=record,
                candidate=record.candidate_assertions[0],
                authorization_id=f"AUTH-{record.id}",
            )
            pending.append(PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, auth))
        ledger.append_batch(recorded_at=T0, entries=tuple(pending))
        view = recorded_historical_view(
            ledger,
            cutoff_seq=ledger.head_seq,
            policies=self.registry,
        )
        self.assertEqual(view.assertions_for("F1"), (AuthorizedAssertion.ESTABLISHED_FACT,))
        self.assertEqual(view.assertions_for("R1"), (AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,))
        self.assertEqual(view.assertions_for("AP1"), (AuthorizedAssertion.CURRENT_MATCH_RULE,))
        self.assertEqual(view.assertions_for("RC1"), (AuthorizedAssertion.REVISIT_RULE,))

    def test_evaluation_snapshot_freezes_input_cutoff_and_replay_fingerprint(self):
        ledger = InMemoryTemporalLedger()
        r2 = evidence(
            "E-R2",
            (CandidateAssertion("R2", AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE),),
            "Reaction capacity materially influenced D-104.",
        )
        ledger.append_batch(
            recorded_at=T0,
            entries=(PendingLedgerEntry(LedgerEntryKind.EVIDENCE, r2),),
        )
        input_cutoff = ledger.head_seq
        fingerprint = canonical_replay_fingerprint(
            ledger=ledger,
            input_cutoff_seq=input_cutoff,
            authority_policy=self.policy,
            target_version="SAFE_REUSE_V1",
            target_hash="target-hash-v1",
            engine_version="0.2.0",
            engine_hash="engine-sha-v1",
        )
        snapshot = EvaluationSnapshot(
            id="EV-901",
            decision_id="D-104",
            input_cutoff_seq=input_cutoff,
            target_version="SAFE_REUSE_V1",
            target_hash="target-hash-v1",
            evidence_policy_version=self.policy.version,
            evidence_policy_hash=self.policy.policy_hash,
            event_policy_version="EVENT_V1",
            event_policy_hash="event-hash-v1",
            engine_version="0.2.0",
            engine_hash="engine-sha-v1",
            result_fingerprint=fingerprint,
        )
        ledger.append_batch(
            recorded_at=T1,
            entries=(PendingLedgerEntry(LedgerEntryKind.EVALUATION, snapshot),),
        )
        loaded = ledger.entry("EV-901").payload
        self.assertEqual(loaded.input_cutoff_seq, input_cutoff)
        replayed = canonical_replay_fingerprint(
            ledger=ledger,
            input_cutoff_seq=loaded.input_cutoff_seq,
            authority_policy=self.policy,
            target_version=loaded.target_version,
            target_hash=loaded.target_hash,
            engine_version=loaded.engine_version,
            engine_hash=loaded.engine_hash,
        )
        self.assertEqual(loaded.result_fingerprint, replayed)


if __name__ == "__main__":
    unittest.main()
