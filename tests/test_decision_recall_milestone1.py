import math
import unittest
from dataclasses import FrozenInstanceError, replace

from decision_recall.domain import (
    CanonicalWorldState,
    CompositionAuthorizationDecision,
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
    evaluate_target,
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


class Milestone13CanonicalIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.metric_specs = supplier_metric_specs()
        self.target = safe_reuse_target_v1()

    def evaluate(self, contract, state):
        return evaluate_target(
            contract=validate_contract(contract),
            world_state=state,
            target=self.target,
        )

    def test_golden_supplier_resilience(self):
        contract = supplier_resilience_contract()
        before = contract.historical_relations
        state = apply_world_event(
            state=initial_world_state(), event=golden_event(), metric_specs=self.metric_specs
        )
        result = self.evaluate(contract, state)
        matches = dict(result.current_matches)
        reviews = dict(result.review_states)
        self.assertEqual(matches["M1"], MatchResult.DOES_NOT_MATCH)
        self.assertEqual(matches["M2"], MatchResult.MATCHES)
        self.assertEqual(reviews["RC1"], RevisitResult.TRIGGERED)
        self.assertEqual(result.safe_reuse.result, SafeReuseResult.REUSE_NOT_AUTHORIZED)
        self.assertEqual(result.safe_reuse.limiting_requirements, ("C1",))
        self.assertEqual(contract.historical_relations, before)

    def test_revisit_trigger_does_not_invalidate_reuse_when_supports_still_match(self):
        contract = supplier_resilience_contract()
        raw = contract.revisit_rule("RC1")
        always_review = replace(raw, condition=replace(raw.condition, threshold=0.80))
        contract = replace(contract, revisit_rules=(always_review,))
        result = self.evaluate(contract, initial_world_state())
        self.assertEqual(dict(result.review_states)["RC1"], RevisitResult.TRIGGERED)
        self.assertEqual(result.safe_reuse.result, SafeReuseResult.REUSE_AUTHORIZED)
        self.assertEqual(result.safe_reuse.reason_codes, ("NO_TARGET_SUPPORT_INVALIDATION",))

    def test_unknown_revisit_does_not_contaminate_known_safe_reuse(self):
        contract = supplier_resilience_contract()
        raw = contract.revisit_rule("RC1")
        needs_long_window = replace(raw, condition=replace(raw.condition, minimum_window_days=100))
        contract = replace(contract, revisit_rules=(needs_long_window,))
        result = self.evaluate(contract, initial_world_state())
        self.assertEqual(dict(result.review_states)["RC1"], RevisitResult.UNKNOWN)
        self.assertEqual(result.safe_reuse.result, SafeReuseResult.REUSE_AUTHORIZED)

    def test_support_mismatch_blocks_reuse_even_without_review_trigger(self):
        contract = supplier_resilience_contract(c1_value=CompositionValue.ESTABLISHED_TRUE)
        raw = contract.revisit_rule("RC1")
        never_review = replace(raw, condition=replace(raw.condition, threshold=1.0))
        contract = replace(contract, revisit_rules=(never_review,))
        state = apply_world_event(
            state=initial_world_state(), event=beacon_recovery_event(beacon_days=1), metric_specs=self.metric_specs
        )
        result = self.evaluate(contract, state)
        self.assertEqual(dict(result.review_states)["RC1"], RevisitResult.NOT_TRIGGERED)
        self.assertEqual(result.safe_reuse.result, SafeReuseResult.REUSE_NOT_AUTHORIZED)
        self.assertEqual(result.safe_reuse.reason_codes, ("REQUIRED_SURVIVING_SUPPORT_DOES_NOT_MATCH",))

    def test_supported_api_computes_current_match_from_world_state(self):
        contract = supplier_resilience_contract()
        state = apply_world_event(
            state=initial_world_state(), event=golden_event(), metric_specs=self.metric_specs
        )
        result = self.evaluate(contract, state)
        self.assertEqual(dict(result.current_matches)["M1"], MatchResult.DOES_NOT_MATCH)

    def test_old_caller_supplied_epistemic_api_is_rejected(self):
        with self.assertRaises(GuardViolation):
            evaluate_safe_reuse(
                contract=validate_contract(supplier_resilience_contract()),
                match_results={"M1": MatchResult.MATCHES, "M2": MatchResult.MATCHES},
                revisit_results={"RC1": RevisitResult.NOT_TRIGGERED},
                target=self.target,
            )

    def test_raw_contract_cannot_enter_target_engine(self):
        with self.assertRaises(GuardViolation):
            evaluate_target(
                contract=supplier_resilience_contract(),
                world_state=initial_world_state(),
                target=self.target,
            )

    def test_partial_17_day_coverage_is_unknown_not_false(self):
        contract = supplier_resilience_contract()
        state = apply_world_event(
            state=initial_world_state(), event=golden_event(days=17), metric_specs=self.metric_specs
        )
        result = self.evaluate(contract, state)
        self.assertEqual(dict(result.current_matches)["M1"], MatchResult.UNKNOWN)
        self.assertEqual(dict(result.review_states)["RC1"], RevisitResult.UNKNOWN)
        self.assertEqual(result.safe_reuse.result, SafeReuseResult.INSUFFICIENT_EVIDENCE)

    def test_full_window_below_threshold_is_known(self):
        contract = supplier_resilience_contract()
        state = apply_world_event(
            state=initial_world_state(), event=golden_event(apex_rate=0.90, days=30), metric_specs=self.metric_specs
        )
        self.assertEqual(evaluate_current_match(contract.match_rule("M1"), state), MatchResult.MATCHES)
        self.assertEqual(evaluate_revisit(contract.revisit_rule("RC1"), state), RevisitResult.NOT_TRIGGERED)

    def test_world_event_is_delta_and_records_lineage(self):
        state = apply_world_event(
            state=initial_world_state(), event=golden_event(), metric_specs=self.metric_specs
        )
        self.assertEqual(state.observation("apex_on_time_rate").source_event_id, "E-301")
        self.assertEqual(state.observation("beacon_reactivation_days").value, 70)
        self.assertEqual(state.observation("beacon_reactivation_days").source_event_id, "INITIAL-SNAPSHOT")

    def test_surviving_support_must_match_even_if_composition_true(self):
        contract = supplier_resilience_contract(c1_value=CompositionValue.ESTABLISHED_TRUE)
        state = apply_world_event(
            state=initial_world_state(), event=golden_event(), metric_specs=self.metric_specs
        )
        state = apply_world_event(
            state=state, event=beacon_recovery_event(beacon_days=1), metric_specs=self.metric_specs
        )
        result = self.evaluate(contract, state)
        self.assertEqual(result.safe_reuse.result, SafeReuseResult.REUSE_NOT_AUTHORIZED)

    def test_unestablished_target_role_never_authorizes_reuse(self):
        for historical_state in (
            HistoricalKnowledgeState.T0_UNRESOLVED,
            HistoricalKnowledgeState.NOT_DURABLY_RECORDED,
            HistoricalKnowledgeState.CURRENTLY_UNDETERMINED,
        ):
            contract = supplier_resilience_contract(r2_state=historical_state)
            result = self.evaluate(contract, initial_world_state())
            self.assertNotEqual(result.safe_reuse.result, SafeReuseResult.REUSE_AUTHORIZED)

    def test_target_rejects_wrong_composition_relation(self):
        validated = validate_contract(supplier_resilience_contract(c1_relation_ids=("R1",)))
        with self.assertRaises(GuardViolation):
            validate_target_against_contract(contract=validated, target=self.target)

    def test_target_rejects_wrong_target_id(self):
        validated = validate_contract(supplier_resilience_contract(c1_target_id="OTHER"))
        with self.assertRaises(GuardViolation):
            validate_target_against_contract(contract=validated, target=self.target)

    def test_target_rejects_wrong_target_version(self):
        validated = validate_contract(supplier_resilience_contract(c1_target_version="2"))
        with self.assertRaises(GuardViolation):
            validate_target_against_contract(contract=validated, target=self.target)

    def test_contract_rejects_claim_metric_mismatch(self):
        with self.assertRaises(GuardViolation):
            validate_contract(supplier_resilience_contract(f1_current_metric_key="customer_churn"))

    def test_contract_rejects_duplicate_entity_ids(self):
        contract = supplier_resilience_contract()
        duplicate = replace(contract.claims[1], id="F1")
        with self.assertRaises(GuardViolation):
            validate_contract(replace(contract, claims=(contract.claims[0], duplicate)))

    def test_contract_id_cannot_collide_with_internal_entity_id(self):
        contract = supplier_resilience_contract()
        with self.assertRaises(GuardViolation):
            validate_contract(replace(contract, id="F1"))

    def test_duplicate_semantic_historical_relation_is_rejected(self):
        contract = supplier_resilience_contract()
        duplicate = replace(contract.relation("R1"), id="R99")
        malformed = replace(contract, historical_relations=(*contract.historical_relations, duplicate))
        with self.assertRaises(GuardViolation):
            validate_contract(malformed)

    def test_contract_rejects_missing_relation_subject(self):
        contract = supplier_resilience_contract()
        bad = replace(contract.relation("R1"), subject_id="MISSING")
        malformed = replace(contract, historical_relations=(bad, contract.relation("R2")))
        with self.assertRaises(GuardViolation):
            validate_contract(malformed)

    def test_contract_rejects_established_relation_without_authority_metadata(self):
        contract = supplier_resilience_contract()
        bad = replace(contract.relation("R1"), evidence_refs=(), authorization_policy_version="")
        malformed = replace(contract, historical_relations=(bad, contract.relation("R2")))
        with self.assertRaises(GuardViolation):
            validate_contract(malformed)

    def test_contract_rejects_composition_authorization_for_different_candidate(self):
        contract = supplier_resilience_contract(c1_value=CompositionValue.ESTABLISHED_TRUE)
        c1 = contract.composition("C1")
        forged = replace(c1.authorization, candidate_id="C999")
        malformed = replace(contract, composition_states=(replace(c1, authorization=forged),))
        with self.assertRaises(GuardViolation):
            validate_contract(malformed)

    def test_relation_slot_cannot_be_promoted_without_evidence(self):
        slot = RelationSlot("R2", RelationType.HISTORICAL_SUPPORT, "F2", "D-104", "future relevance")
        candidate = RelationCandidate("CR-R2", RelationType.HISTORICAL_SUPPORT, "F2", "D-104", ())
        with self.assertRaises(GuardViolation):
            authorize_historical_role(slot=slot, candidate=candidate, evidence=(), policy=evidence_policy_v1())

    def test_evidence_subset_can_authorize_relation(self):
        slot = RelationSlot("R2", RelationType.HISTORICAL_SUPPORT, "F2", "D-104", "future relevance")
        evidence = (
            EvidenceRecord("E1", "Apex metric", ProvenanceType.CONTEMPORANEOUS_RECORD),
            EvidenceRecord("E2", "Reaction capacity was an additional reason.", ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION),
        )
        candidate = RelationCandidate("CR-R2", RelationType.HISTORICAL_SUPPORT, "F2", "D-104", ("E2",))
        relation = authorize_historical_role(slot=slot, candidate=candidate, evidence=evidence, policy=evidence_policy_v1())
        self.assertEqual(relation.evidence_refs, ("E2",))

    def test_duplicate_evidence_ids_are_rejected(self):
        slot = RelationSlot("R2", RelationType.HISTORICAL_SUPPORT, "F2", "D-104", "x")
        candidate = RelationCandidate("CR", RelationType.HISTORICAL_SUPPORT, "F2", "D-104", ("E",))
        evidence = (
            EvidenceRecord("E", "one", ProvenanceType.CONTEMPORANEOUS_RECORD),
            EvidenceRecord("E", "two", ProvenanceType.CONTEMPORANEOUS_RECORD),
        )
        with self.assertRaises(GuardViolation):
            authorize_historical_role(slot=slot, candidate=candidate, evidence=evidence, policy=evidence_policy_v1())

    def test_retrospective_or_llm_inference_cannot_authorize_historical_role_v1(self):
        slot = RelationSlot("R2", RelationType.HISTORICAL_SUPPORT, "F2", "D-104", "x")
        for provenance in (ProvenanceType.RETROSPECTIVE_DECLARATION, ProvenanceType.LLM_INFERRED):
            candidate = RelationCandidate("CR", RelationType.HISTORICAL_SUPPORT, "F2", "D-104", ("E",))
            with self.assertRaises(GuardViolation):
                authorize_historical_role(
                    slot=slot,
                    candidate=candidate,
                    evidence=(EvidenceRecord("E", "claim", provenance),),
                    policy=evidence_policy_v1(),
                )

    def test_absence_of_composition_evidence_cannot_establish_false(self):
        candidate = CompositionCandidate(
            "C-X", CompositionKind.SUFFICIENT_ALONE, ("R2",), TargetRef(TARGET_ID, TARGET_VERSION),
            CompositionValue.ESTABLISHED_FALSE, ()
        )
        with self.assertRaises(GuardViolation):
            authorize_composition(candidate=candidate, evidence=(), policy=composition_policy_v1())

    def test_explicit_authorized_negative_composition_evidence_can_establish_false(self):
        evidence = EvidenceRecord(
            "EC", "At decision time R2 was explicitly not sufficient alone.", ProvenanceType.CONTEMPORANEOUS_RECORD
        )
        candidate = CompositionCandidate(
            "C-X", CompositionKind.SUFFICIENT_ALONE, ("R2",), TargetRef(TARGET_ID, TARGET_VERSION),
            CompositionValue.ESTABLISHED_FALSE, ("EC",)
        )
        state = authorize_composition(candidate=candidate, evidence=(evidence,), policy=composition_policy_v1())
        self.assertEqual(state.value, CompositionValue.ESTABLISHED_FALSE)
        self.assertEqual(state.authorization.candidate_id, "C-X")

    def test_irrelevant_event_has_zero_semantic_impact(self):
        contract = supplier_resilience_contract()
        event = WorldEvent("E-INVOICE", (NumericObservation("beacon_invoice_template_version", 2, unit="version"),))
        before = initial_world_state()
        after = apply_world_event(state=before, event=event, metric_specs=self.metric_specs)
        impact = semantic_impact(contract=contract, event=event, before_state=before, after_state=after)
        self.assertEqual(rules_requiring_recheck(contract, event), ())
        self.assertEqual(impact.changed_rule_ids, ())

    def test_metric_present_but_same_semantic_state_is_rechecked_not_changed(self):
        contract = supplier_resilience_contract()
        event = golden_event(apex_rate=0.82, days=30)
        before = initial_world_state()
        after = apply_world_event(state=before, event=event, metric_specs=self.metric_specs)
        impact = semantic_impact(contract=contract, event=event, before_state=before, after_state=after)
        self.assertEqual(set(impact.rechecked_rule_ids), {"M1", "RC1"})
        self.assertEqual(impact.changed_rule_ids, ())

    def test_metric_range_unit_duplicate_nan_and_infinity_validation(self):
        bad_events = (
            WorldEvent("BAD-RANGE", (NumericObservation("apex_on_time_rate", 98.7, "ratio", 30),)),
            WorldEvent("BAD-UNIT", (NumericObservation("apex_on_time_rate", 0.98, "percent", 30),)),
            WorldEvent("BAD-NAN", (NumericObservation("apex_on_time_rate", math.nan, "ratio", 30),)),
            WorldEvent("BAD-INF", (NumericObservation("beacon_reactivation_days", math.inf, "days"),)),
            WorldEvent("DUP", (
                NumericObservation("apex_on_time_rate", 0.98, "ratio", 30),
                NumericObservation("apex_on_time_rate", 0.99, "ratio", 30),
            )),
        )
        for event in bad_events:
            with self.assertRaises(GuardViolation):
                apply_world_event(state=initial_world_state(), event=event, metric_specs=self.metric_specs)

    def test_non_finite_threshold_is_rejected(self):
        contract = supplier_resilience_contract()
        m1 = contract.match_rule("M1")
        malformed_m1 = replace(m1, condition=replace(m1.condition, threshold=math.nan))
        malformed = replace(contract, current_match_rules=(malformed_m1, contract.match_rule("M2")))
        with self.assertRaises(GuardViolation):
            validate_contract(malformed)

    def test_domain_objects_are_frozen(self):
        contract = supplier_resilience_contract()
        with self.assertRaises(FrozenInstanceError):
            contract.historical_relations[0].knowledge_state = HistoricalKnowledgeState.CURRENTLY_UNDETERMINED

    def test_world_changes_never_mutate_historical_relations_matrix(self):
        contract = supplier_resilience_contract()
        historical_snapshot = contract.historical_relations
        for apex_rate in (0.70, 0.83, 0.97, 0.999):
            for days in (1, 17, 30, 90):
                for beacon_days in (0, 1, 69, 70, 140):
                    state = apply_world_event(
                        state=initial_world_state(), event=golden_event(apex_rate=apex_rate, days=days), metric_specs=self.metric_specs
                    )
                    state = apply_world_event(
                        state=state, event=beacon_recovery_event(beacon_days=beacon_days), metric_specs=self.metric_specs
                    )
                    self.evaluate(contract, state)
                    self.assertEqual(contract.historical_relations, historical_snapshot)

    def test_t0_unresolved_composition_is_never_rewritten_false(self):
        contract = supplier_resilience_contract(c1_value=CompositionValue.T0_UNRESOLVED)
        before = contract.composition("C1")
        state = apply_world_event(
            state=initial_world_state(), event=golden_event(), metric_specs=self.metric_specs
        )
        self.evaluate(contract, state)
        self.assertEqual(contract.composition("C1"), before)
        self.assertEqual(contract.composition("C1").value, CompositionValue.T0_UNRESOLVED)


if __name__ == "__main__":
    unittest.main()
