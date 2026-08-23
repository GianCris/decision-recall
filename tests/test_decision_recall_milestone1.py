import unittest

from decision_recall.domain import (
    AuthorizationDecision,
    AuthorizationStatus,
    EvidenceRecord,
    MatchResult,
    NumericObservation,
    RelationCandidate,
    RelationSlot,
    RelationType,
    RevisitResult,
    SafeReuseResult,
    WorldEvent,
)
from decision_recall.engine import (
    GuardViolation,
    affected_rule_ids,
    authorize_historical_role,
    evaluate_current_match,
    evaluate_revisit,
    evaluate_safe_reuse,
)
from decision_recall.golden import (
    golden_event,
    safe_reuse_target_v1,
    supplier_resilience_contract,
)


class Milestone1GoldenTests(unittest.TestCase):
    def test_golden_supplier_resilience(self):
        contract = supplier_resilience_contract()
        before_relations = contract.historical_relations
        event = golden_event()

        matches = {
            rule.id: evaluate_current_match(rule, event)
            for rule in contract.current_match_rules
        }
        revisits = {
            rule.id: evaluate_revisit(rule, event)
            for rule in contract.revisit_rules
        }
        result = evaluate_safe_reuse(
            contract=contract,
            match_results=matches,
            revisit_results=revisits,
            target=safe_reuse_target_v1(),
        )

        self.assertEqual(matches["M1"], MatchResult.DOES_NOT_MATCH)
        self.assertEqual(matches["M2"], MatchResult.MATCHES)
        self.assertEqual(revisits["RC1"], RevisitResult.TRIGGERED)
        self.assertEqual(result.result, SafeReuseResult.REUSE_NOT_AUTHORIZED)
        self.assertEqual(result.limiting_relations, ("C1",))
        self.assertEqual(contract.historical_relations, before_relations)

    def test_17_days_does_not_satisfy_30_day_threshold(self):
        contract = supplier_resilience_contract()
        event = golden_event(days=17)
        m1 = evaluate_current_match(contract.current_match_rules[0], event)
        rc1 = evaluate_revisit(contract.revisit_rules[0], event)

        self.assertEqual(m1, MatchResult.MATCHES)
        self.assertEqual(rc1, RevisitResult.NOT_TRIGGERED)

    def test_beacon_reactivation_change_only_changes_current_match(self):
        contract = supplier_resilience_contract()
        before_relations = contract.historical_relations
        event = golden_event(beacon_days=1)
        matches = {
            rule.id: evaluate_current_match(rule, event)
            for rule in contract.current_match_rules
        }

        self.assertEqual(matches["M1"], MatchResult.DOES_NOT_MATCH)
        self.assertEqual(matches["M2"], MatchResult.DOES_NOT_MATCH)
        self.assertEqual(contract.historical_relations, before_relations)

    def test_irrelevant_event_has_zero_relevant_rules(self):
        contract = supplier_resilience_contract()
        event = WorldEvent(
            id="E-INVOICE",
            observations=(NumericObservation("beacon_invoice_template_version", 2),),
        )
        self.assertEqual(affected_rule_ids(contract, event), ())

    def test_relation_slot_cannot_be_promoted_without_evidence(self):
        slot = RelationSlot(
            id="R2",
            relation_type=RelationType.HISTORICAL_SUPPORT,
            subject_id="F2",
            object_id="D-104",
            reason_for_checking="CaptureProfile says recovery role may matter later",
        )
        candidate = RelationCandidate(
            id="CR-R2",
            relation_type=RelationType.HISTORICAL_SUPPORT,
            subject_id="F2",
            object_id="D-104",
            evidence_refs=(),
        )
        authorization = AuthorizationDecision(
            candidate_id="CR-R2",
            status=AuthorizationStatus.AUTHORIZED,
            authorized_as=RelationType.HISTORICAL_SUPPORT,
            evidence_refs=(),
            policy_version="EP_V1",
            reason_code="SHOULD_NOT_BE_ENOUGH",
        )

        with self.assertRaises(GuardViolation):
            authorize_historical_role(
                slot=slot,
                candidate=candidate,
                evidence=(),
                authorization=authorization,
            )

    def test_missing_current_metric_is_unknown_not_false(self):
        contract = supplier_resilience_contract()
        event = WorldEvent(
            id="E-PARTIAL",
            observations=(NumericObservation("beacon_reactivation_days", 70),),
        )
        m1 = evaluate_current_match(contract.current_match_rules[0], event)
        self.assertEqual(m1, MatchResult.UNKNOWN)

    def test_authorized_evidence_can_promote_slot(self):
        slot = RelationSlot(
            id="R2",
            relation_type=RelationType.HISTORICAL_SUPPORT,
            subject_id="F2",
            object_id="D-104",
            reason_for_checking="future relevance",
        )
        evidence = EvidenceRecord(
            id="EV-R2",
            content="Preserving reaction capacity was an additional reason.",
            provenance_type="CONTEMPORANEOUS_ELICITED_DECLARATION",
        )
        candidate = RelationCandidate(
            id="CR-R2",
            relation_type=RelationType.HISTORICAL_SUPPORT,
            subject_id="F2",
            object_id="D-104",
            evidence_refs=("EV-R2",),
        )
        authorization = AuthorizationDecision(
            candidate_id="CR-R2",
            status=AuthorizationStatus.AUTHORIZED,
            authorized_as=RelationType.HISTORICAL_SUPPORT,
            evidence_refs=("EV-R2",),
            policy_version="EP_V1",
            reason_code="CONTEMPORANEOUS_DECLARATION_ALLOWED",
        )
        relation = authorize_historical_role(
            slot=slot,
            candidate=candidate,
            evidence=(evidence,),
            authorization=authorization,
        )
        self.assertEqual(relation.evidence_refs, ("EV-R2",))


if __name__ == "__main__":
    unittest.main()
