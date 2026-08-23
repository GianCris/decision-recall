import unittest
from dataclasses import FrozenInstanceError, replace

from decision_recall.domain import (
    CanonicalWorldState,
    CompositionCandidate,
    CompositionKind,
    CompositionState,
    CompositionValue,
    EvidenceRecord,
    HistoricalKnowledgeState,
    MatchResult,
    NumericObservation,
    ProvenanceType,
    RelationCandidate,
    RelationSlot,
    RelationType,
    RevisitResult,
    SafeReuseResult,
    TargetRef,
    WorldEvent,
)
from decision_recall.engine import (
    GuardViolation,
    apply_world_event,
    authorize_composition,
    authorize_historical_role,
    evaluate_current_match,
    evaluate_revisit,
    evaluate_safe_reuse,
    rules_requiring_recheck,
    semantic_impact,
    validate_contract,
    validate_target_against_contract,
)
from decision_recall.golden import (
    TARGET_ID,
    TARGET_VERSION,
    beacon_recovery_event,
    golden_event,
    initial_world_state,
    safe_reuse_target_v1,
    supplier_metric_specs,
    supplier_resilience_contract,
)
from decision_recall.policies import composition_policy_v1, evidence_policy_v1


def evaluate_contract(contract, state):
    matches = {
        rule.id: evaluate_current_match(rule, state)
        for rule in contract.current_match_rules
    }
    revisits = {
        rule.id: evaluate_revisit(rule, state)
        for rule in contract.revisit_rules
    }
    return matches, revisits


def evaluate_safe(contract, state, target):
    matches, revisits = evaluate_contract(contract, state)
    return evaluate_safe_reuse(
        contract=validate_contract(contract),
        match_results=matches,
        revisit_results=revisits,
        target=target,
    )


class Milestone12CanonicalIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.metric_specs = supplier_metric_specs()
        self.target = safe_reuse_target_v1()

    def test_golden_supplier_resilience(self):
        contract = supplier_resilience_contract()
        before_relations = contract.historical_relations
        state = apply_world_event(
            state=initial_world_state(),
            event=golden_event(),
            metric_specs=self.metric_specs,
        )
        matches, revisits = evaluate_contract(contract, state)
        result = evaluate_safe_reuse(
            contract=validate_contract(contract),
            match_results=matches,
            revisit_results=revisits,
            target=self.target,
        )
        self.assertEqual(matches["M1"], MatchResult.DOES_NOT_MATCH)
        self.assertEqual(matches["M2"], MatchResult.MATCHES)
        self.assertEqual(revisits["RC1"], RevisitResult.TRIGGERED)
        self.assertEqual(result.result, SafeReuseResult.REUSE_NOT_AUTHORIZED)
        self.assertEqual(result.limiting_relations, ("C1",))
        self.assertEqual(contract.historical_relations, before_relations)

    def test_partial_17_day_coverage_is_unknown_not_false(self):
        contract = supplier_resilience_contract()
        state = apply_world_event(
            state=initial_world_state(),
            event=golden_event(days=17),
            metric_specs=self.metric_specs,
        )
        self.assertEqual(
            evaluate_current_match(contract.match_rule("M1"), state),
            MatchResult.UNKNOWN,
        )
        self.assertEqual(
            evaluate_revisit(contract.revisit_rule("RC1"), state),
            RevisitResult.UNKNOWN,
        )

    def test_full_window_below_threshold_is_false_not_unknown(self):
        contract = supplier_resilience_contract()
        state = apply_world_event(
            state=initial_world_state(),
            event=golden_event(apex_rate=0.90, days=30),
            metric_specs=self.metric_specs,
        )
        self.assertEqual(
            evaluate_current_match(contract.match_rule("M1"), state),
            MatchResult.MATCHES,
        )
        self.assertEqual(
            evaluate_revisit(contract.revisit_rule("RC1"), state),
            RevisitResult.NOT_TRIGGERED,
        )

    def test_world_event_is_delta_preserves_state_and_records_lineage(self):
        state = apply_world_event(
            state=initial_world_state(),
            event=golden_event(),
            metric_specs=self.metric_specs,
        )
        apex = state.observation("apex_on_time_rate")
        beacon = state.observation("beacon_reactivation_days")
        self.assertEqual(apex.source_event_id, "E-301")
        self.assertEqual(beacon.value, 70)
        self.assertEqual(beacon.source_event_id, "INITIAL-SNAPSHOT")

    def test_beacon_change_never_rewrites_historical_role(self):
        contract = supplier_resilience_contract()
        before_relations = contract.historical_relations
        state = apply_world_event(
            state=initial_world_state(),
            event=beacon_recovery_event(beacon_days=1),
            metric_specs=self.metric_specs,
        )
        self.assertEqual(
            evaluate_current_match(contract.match_rule("M2"), state),
            MatchResult.DOES_NOT_MATCH,
        )
        self.assertEqual(contract.historical_relations, before_relations)

    def test_surviving_support_must_match_even_if_composition_is_true(self):
        contract = supplier_resilience_contract(c1_value=CompositionValue.ESTABLISHED_TRUE)
        state = apply_world_event(
            state=initial_world_state(),
            event=golden_event(),
            metric_specs=self.metric_specs,
        )
        state = apply_world_event(
            state=state,
            event=beacon_recovery_event(beacon_days=1),
            metric_specs=self.metric_specs,
        )
        result = evaluate_safe(contract, state, self.target)
        self.assertEqual(result.result, SafeReuseResult.REUSE_NOT_AUTHORIZED)
        self.assertEqual(
            result.reason_codes,
            ("REQUIRED_SURVIVING_SUPPORT_DOES_NOT_MATCH",),
        )

    def test_surviving_mismatch_alone_cannot_hit_no_change_positive_path(self):
        contract = supplier_resilience_contract(c1_value=CompositionValue.ESTABLISHED_TRUE)
        state = apply_world_event(
            state=initial_world_state(),
            event=beacon_recovery_event(beacon_days=1),
            metric_specs=self.metric_specs,
        )
        result = evaluate_safe(contract, state, self.target)
        self.assertEqual(result.result, SafeReuseResult.REUSE_NOT_AUTHORIZED)
        self.assertEqual(
            result.reason_codes,
            ("REQUIRED_SURVIVING_SUPPORT_DOES_NOT_MATCH",),
        )

    def test_unestablished_role_cannot_hit_no_change_authorization_bypass(self):
        contract = supplier_resilience_contract(
            r2_state=HistoricalKnowledgeState.NOT_DURABLY_RECORDED,
        )
        result = evaluate_safe(contract, initial_world_state(), self.target)
        self.assertEqual(result.result, SafeReuseResult.REUSE_NOT_AUTHORIZED)
        self.assertEqual(
            result.reason_codes,
            ("TARGET_HISTORICAL_ROLE_NOT_ESTABLISHED",),
        )

    def test_surviving_historical_role_must_be_established_even_if_composition_true(self):
        contract = supplier_resilience_contract(
            r2_state=HistoricalKnowledgeState.NOT_DURABLY_RECORDED,
            c1_value=CompositionValue.ESTABLISHED_TRUE,
        )
        state = apply_world_event(
            state=initial_world_state(),
            event=golden_event(),
            metric_specs=self.metric_specs,
        )
        result = evaluate_safe(contract, state, self.target)
        self.assertEqual(result.result, SafeReuseResult.REUSE_NOT_AUTHORIZED)
        self.assertIn("R2", result.limiting_relations)

    def test_raw_contract_cannot_enter_safe_reuse_engine(self):
        contract = supplier_resilience_contract()
        matches, revisits = evaluate_contract(contract, initial_world_state())
        with self.assertRaises(GuardViolation):
            evaluate_safe_reuse(
                contract=contract,
                match_results=matches,
                revisit_results=revisits,
                target=self.target,
            )

    def test_target_rejects_composition_about_wrong_relation(self):
        validated = validate_contract(
            supplier_resilience_contract(c1_relation_ids=("R1",))
        )
        with self.assertRaises(GuardViolation):
            validate_target_against_contract(contract=validated, target=self.target)

    def test_target_rejects_composition_for_wrong_target_id(self):
        validated = validate_contract(
            supplier_resilience_contract(c1_target_id="OTHER_TARGET")
        )
        with self.assertRaises(GuardViolation):
            validate_target_against_contract(contract=validated, target=self.target)

    def test_target_rejects_composition_for_wrong_target_version(self):
        validated = validate_contract(
            supplier_resilience_contract(c1_target_version="2")
        )
        with self.assertRaises(GuardViolation):
            validate_target_against_contract(contract=validated, target=self.target)

    def test_contract_rejects_claim_metric_mismatch(self):
        contract = supplier_resilience_contract(f1_current_metric_key="customer_churn")
        with self.assertRaises(GuardViolation):
            validate_contract(contract)

    def test_contract_rejects_duplicate_entity_ids(self):
        contract = supplier_resilience_contract()
        duplicate_claim = replace(contract.claims[1], id="F1")
        malformed = replace(contract, claims=(contract.claims[0], duplicate_claim))
        with self.assertRaises(GuardViolation):
            validate_contract(malformed)

    def test_contract_rejects_missing_relation_subject(self):
        contract = supplier_resilience_contract()
        malformed_r1 = replace(contract.relation("R1"), subject_id="MISSING")
        malformed = replace(
            contract,
            historical_relations=(malformed_r1, contract.relation("R2")),
        )
        with self.assertRaises(GuardViolation):
            validate_contract(malformed)

    def test_contract_rejects_established_relation_without_authority(self):
        contract = supplier_resilience_contract()
        malformed_r1 = replace(
            contract.relation("R1"),
            evidence_refs=(),
            authorization_policy_version="",
        )
        malformed = replace(
            contract,
            historical_relations=(malformed_r1, contract.relation("R2")),
        )
        with self.assertRaises(GuardViolation):
            validate_contract(malformed)

    def test_contract_rejects_established_composition_without_authorization(self):
        contract = supplier_resilience_contract(c1_value=CompositionValue.ESTABLISHED_TRUE)
        malformed_c1 = replace(contract.composition("C1"), authorization=None)
        malformed = replace(contract, composition_states=(malformed_c1,))
        with self.assertRaises(GuardViolation):
            validate_contract(malformed)

    def test_relation_slot_cannot_be_promoted_without_evidence(self):
        slot = RelationSlot(
            id="R2",
            relation_type=RelationType.HISTORICAL_SUPPORT,
            subject_id="F2",
            object_id="D-104",
            reason_for_checking="capture profile says recovery role may matter",
        )
        candidate = RelationCandidate(
            id="CR-R2",
            relation_type=RelationType.HISTORICAL_SUPPORT,
            subject_id="F2",
            object_id="D-104",
            evidence_refs=(),
        )
        with self.assertRaises(GuardViolation):
            authorize_historical_role(
                slot=slot,
                candidate=candidate,
                evidence=(),
                policy=evidence_policy_v1(),
            )

    def test_evidence_subset_of_snapshot_can_authorize_relation(self):
        slot = RelationSlot(
            "R2",
            RelationType.HISTORICAL_SUPPORT,
            "F2",
            "D-104",
            "future relevance",
        )
        evidence = (
            EvidenceRecord("E1", "Apex metric", ProvenanceType.CONTEMPORANEOUS_RECORD),
            EvidenceRecord(
                "E2",
                "Reaction capacity was an additional reason.",
                ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION,
            ),
            EvidenceRecord("E3", "Unrelated note", ProvenanceType.CONTEMPORANEOUS_RECORD),
        )
        candidate = RelationCandidate(
            "CR-R2",
            RelationType.HISTORICAL_SUPPORT,
            "F2",
            "D-104",
            ("E2",),
        )
        relation = authorize_historical_role(
            slot=slot,
            candidate=candidate,
            evidence=evidence,
            policy=evidence_policy_v1(),
        )
        self.assertEqual(relation.evidence_refs, ("E2",))

    def test_duplicate_evidence_ids_are_rejected(self):
        slot = RelationSlot("R2", RelationType.HISTORICAL_SUPPORT, "F2", "D-104", "x")
        candidate = RelationCandidate(
            "CR-R2", RelationType.HISTORICAL_SUPPORT, "F2", "D-104", ("E",)
        )
        duplicate_snapshot = (
            EvidenceRecord("E", "one", ProvenanceType.CONTEMPORANEOUS_RECORD),
            EvidenceRecord("E", "two", ProvenanceType.CONTEMPORANEOUS_RECORD),
        )
        with self.assertRaises(GuardViolation):
            authorize_historical_role(
                slot=slot,
                candidate=candidate,
                evidence=duplicate_snapshot,
                policy=evidence_policy_v1(),
            )

    def test_retrospective_or_llm_inference_cannot_authorize_historical_role_v1(self):
        slot = RelationSlot("R2", RelationType.HISTORICAL_SUPPORT, "F2", "D-104", "x")
        for provenance in (
            ProvenanceType.RETROSPECTIVE_DECLARATION,
            ProvenanceType.LLM_INFERRED,
        ):
            candidate = RelationCandidate(
                "CR", RelationType.HISTORICAL_SUPPORT, "F2", "D-104", ("E",)
            )
            with self.assertRaises(GuardViolation):
                authorize_historical_role(
                    slot=slot,
                    candidate=candidate,
                    evidence=(EvidenceRecord("E", "claim", provenance),),
                    policy=evidence_policy_v1(),
                )

    def test_absence_of_composition_evidence_cannot_establish_false(self):
        candidate = CompositionCandidate(
            id="C-X",
            kind=CompositionKind.SUFFICIENT_ALONE,
            relation_ids=("R2",),
            target_ref=TargetRef(TARGET_ID, TARGET_VERSION),
            asserted_value=CompositionValue.ESTABLISHED_FALSE,
            evidence_refs=(),
        )
        with self.assertRaises(GuardViolation):
            authorize_composition(
                candidate=candidate,
                evidence=(),
                policy=composition_policy_v1(),
            )

    def test_explicit_authorized_composition_evidence_can_establish_false(self):
        evidence = EvidenceRecord(
            "EC",
            "At decision time R2 was explicitly not sufficient alone.",
            ProvenanceType.CONTEMPORANEOUS_RECORD,
        )
        candidate = CompositionCandidate(
            id="C-X",
            kind=CompositionKind.SUFFICIENT_ALONE,
            relation_ids=("R2",),
            target_ref=TargetRef(TARGET_ID, TARGET_VERSION),
            asserted_value=CompositionValue.ESTABLISHED_FALSE,
            evidence_refs=("EC",),
        )
        state = authorize_composition(
            candidate=candidate,
            evidence=(evidence,),
            policy=composition_policy_v1(),
        )
        self.assertEqual(state.value, CompositionValue.ESTABLISHED_FALSE)
        self.assertIsNotNone(state.authorization)
        self.assertEqual(state.authorization.policy_version, "CP_V1")

    def test_irrelevant_event_has_zero_rule_rechecks_and_zero_semantic_changes(self):
        contract = supplier_resilience_contract()
        event = WorldEvent(
            "E-INVOICE",
            (NumericObservation("beacon_invoice_template_version", 2, unit="version"),),
        )
        before = initial_world_state()
        after = apply_world_event(
            state=before,
            event=event,
            metric_specs=self.metric_specs,
        )
        impact = semantic_impact(
            contract=contract,
            event=event,
            before_state=before,
            after_state=after,
        )
        self.assertEqual(rules_requiring_recheck(contract, event), ())
        self.assertEqual(impact.changed_rule_ids, ())

    def test_metric_present_but_same_semantic_state_is_rechecked_not_changed(self):
        contract = supplier_resilience_contract()
        event = golden_event(apex_rate=0.82, days=30)
        before = initial_world_state()
        after = apply_world_event(
            state=before,
            event=event,
            metric_specs=self.metric_specs,
        )
        impact = semantic_impact(
            contract=contract,
            event=event,
            before_state=before,
            after_state=after,
        )
        self.assertEqual(set(impact.rechecked_rule_ids), {"M1", "RC1"})
        self.assertEqual(impact.changed_rule_ids, ())

    def test_metric_range_unit_and_duplicate_validation(self):
        bad_events = (
            WorldEvent(
                "BAD-RANGE",
                (NumericObservation("apex_on_time_rate", 98.7, unit="ratio", window_days=30),),
            ),
            WorldEvent(
                "BAD-UNIT",
                (NumericObservation("apex_on_time_rate", 0.98, unit="percent", window_days=30),),
            ),
            WorldEvent(
                "DUP",
                (
                    NumericObservation("apex_on_time_rate", 0.98, unit="ratio", window_days=30),
                    NumericObservation("apex_on_time_rate", 0.99, unit="ratio", window_days=30),
                ),
            ),
        )
        for event in bad_events:
            with self.assertRaises(GuardViolation):
                apply_world_event(
                    state=initial_world_state(),
                    event=event,
                    metric_specs=self.metric_specs,
                )

    def test_domain_objects_are_frozen(self):
        contract = supplier_resilience_contract()
        with self.assertRaises(FrozenInstanceError):
            contract.historical_relations[0].knowledge_state = (
                HistoricalKnowledgeState.CURRENTLY_UNDETERMINED
            )

    def test_invariant_matrix_current_world_never_mutates_history(self):
        contract = supplier_resilience_contract()
        historical_snapshot = contract.historical_relations
        for apex_rate in (0.70, 0.83, 0.97, 0.999):
            for days in (1, 17, 30, 90):
                for beacon_days in (0, 1, 69, 70, 140):
                    state = apply_world_event(
                        state=initial_world_state(),
                        event=golden_event(apex_rate=apex_rate, days=days),
                        metric_specs=self.metric_specs,
                    )
                    state = apply_world_event(
                        state=state,
                        event=beacon_recovery_event(beacon_days=beacon_days),
                        metric_specs=self.metric_specs,
                    )
                    evaluate_contract(contract, state)
                    self.assertEqual(contract.historical_relations, historical_snapshot)

    def test_invariant_matrix_unestablished_target_role_never_authorizes_reuse(self):
        for historical_state in (
            HistoricalKnowledgeState.T0_UNRESOLVED,
            HistoricalKnowledgeState.NOT_DURABLY_RECORDED,
            HistoricalKnowledgeState.CURRENTLY_UNDETERMINED,
        ):
            for composition in CompositionValue:
                contract = supplier_resilience_contract(
                    r2_state=historical_state,
                    c1_value=composition,
                )
                for state in (
                    initial_world_state(),
                    apply_world_event(
                        state=initial_world_state(),
                        event=golden_event(),
                        metric_specs=self.metric_specs,
                    ),
                ):
                    result = evaluate_safe(contract, state, self.target)
                    self.assertNotEqual(
                        result.result,
                        SafeReuseResult.REUSE_AUTHORIZED,
                    )

    def test_t0_unresolved_composition_is_never_silently_rewritten_false(self):
        contract = supplier_resilience_contract(c1_value=CompositionValue.T0_UNRESOLVED)
        before = contract.composition("C1")
        state = apply_world_event(
            state=initial_world_state(),
            event=golden_event(),
            metric_specs=self.metric_specs,
        )
        evaluate_safe(contract, state, self.target)
        self.assertEqual(contract.composition("C1"), before)
        self.assertEqual(
            contract.composition("C1").value,
            CompositionValue.T0_UNRESOLVED,
        )


if __name__ == "__main__":
    unittest.main()
