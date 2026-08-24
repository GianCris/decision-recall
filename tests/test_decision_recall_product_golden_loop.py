import inspect
import unittest
from dataclasses import fields, replace
from datetime import timedelta

from decision_recall.domain import HistoricalKnowledgeState, ProvenanceType, RelationType
from decision_recall.m21 import canonical_hash, canonical_json
from decision_recall.product import golden_loop as golden_loop_module
from decision_recall.product.capture import (
    CaptureSessionState,
    DecisionFactBinding,
    DecisionRelationBinding,
    DecisionStructure,
    ProfileBinder,
    assign_profile,
    composition_question_eligible,
    make_capture_profile_artifact,
    plan_questions,
    select_critical_gaps,
    supplier_resilience_capture_template,
)
from decision_recall.product.compiler import (
    CandidateKind,
    DeterministicGoldenCompiler,
    EvidenceResolver,
    GroundedCandidate,
    ObservableDecisionBundle,
    SemanticCandidateResolver,
    SourceDocument,
)
from decision_recall.product.golden_loop import T0, prepare_golden_capture, run_golden_decision
from decision_recall.product.models import CandidateView


class ProductGoldenLoopTests(unittest.TestCase):
    def test_checkpoint_1_runs_end_to_end_with_strict_replay(self):
        result = run_golden_decision()

        self.assertEqual(result.capture_profile.question_budget, 1)
        self.assertEqual(result.capture_profile.slot_ids, ("R2",))
        self.assertEqual(result.capture_profile.template_id, "SUPPLIER_RESILIENCE_CAPTURE")
        self.assertEqual(len(result.critical_gaps), 1)
        self.assertEqual(result.critical_gaps[0].slot_id, "R2")
        self.assertLess(result.capture_profile.assigned_at, result.critical_gaps[0].selected_at)

        self.assertEqual(result.r2_trace.knowledge_state, HistoricalKnowledgeState.ESTABLISHED.value)
        self.assertEqual(result.commit.capture_profile_hash, result.capture_profile.content_hash)
        self.assertEqual(result.commit.capture_profile_version, result.capture_profile.version)

        self.assertEqual(dict(result.evaluation.current_matches), {"M1": "does_not_match", "M2": "matches"})
        self.assertEqual(dict(result.evaluation.review_states), {"RC1": "triggered"})
        self.assertEqual(result.evaluation.safe_reuse_result, "insufficient_evidence")
        self.assertEqual(result.evaluation.limiting_requirements, ("C1",))
        self.assertEqual(result.evaluation.reason_codes, ("REQUIRED_COMPOSITION_NOT_DURABLY_KNOWN",))

        self.assertEqual(result.boundary.limiting_entity_id, "C1")
        self.assertEqual(result.boundary.composition_kind, "sufficient_alone")
        self.assertEqual(result.boundary.relation_ids, ("R2",))
        self.assertEqual(result.boundary.composition_value, "not_durably_recorded")
        self.assertEqual(result.replay_result_hash, result.evaluation.result_hash)

    def test_precommit_authorized_state_is_derived_from_real_ledger_authority(self):
        preparation = prepare_golden_capture()
        self.assertEqual(preparation.known_fact_ids, frozenset({"F1", "F2"}))
        self.assertEqual(preparation.established_relation_ids, frozenset({"R1"}))
        self.assertGreater(preparation.ledger.head_seq, 0)
        kinds = tuple(entry.kind.value for entry in preparation.ledger.entries_as_of(preparation.ledger.head_seq))
        self.assertIn("evidence", kinds)
        self.assertIn("authorization", kinds)

        r2 = preparation.draft_contract.relation("R2")
        self.assertEqual(r2.knowledge_state, HistoricalKnowledgeState.NOT_DURABLY_RECORDED)
        self.assertEqual(r2.evidence_refs, ())
        self.assertEqual(tuple(item.slot_id for item in preparation.critical_gaps), ("R2",))

    def test_no_answer_cannot_promote_r2(self):
        with self.assertRaisesRegex(ValueError, "R2 remains NOT_DURABLY_RECORDED"):
            run_golden_decision(answer_r2=False)

    # M: deterministic template -> structure -> profile binding.
    def test_capture_template_contains_no_golden_entity_or_future_identifiers(self):
        payload = canonical_json(supplier_resilience_capture_template())
        for forbidden in ("D-104", '"F2"', '"R2"', "Beacon", "10-week", "10 weeks", "E-301", "0.987", "C1"):
            self.assertNotIn(forbidden, payload)

    def test_profile_binder_api_has_no_manual_golden_or_future_inputs(self):
        params = set(inspect.signature(ProfileBinder.bind).parameters)
        self.assertEqual(params, {"self", "template", "structure"})
        forbidden = {
            "relation_id", "subject_id", "subject_display", "future_event",
            "world_event", "world_state", "evaluation", "target_evaluation",
        }
        self.assertTrue(forbidden.isdisjoint(params))

    def test_template_structure_binder_reproduce_exact_instance_hash(self):
        preparation = prepare_golden_capture()
        profile2, trace2 = ProfileBinder().bind(
            template=supplier_resilience_capture_template(),
            structure=preparation.decision_structure,
        )
        artifact2 = make_capture_profile_artifact(profile2)
        self.assertEqual(trace2.template_hash, canonical_hash(supplier_resilience_capture_template()))
        self.assertEqual(trace2.decision_structure_hash, canonical_hash(preparation.decision_structure))
        self.assertEqual(trace2.binder_version, preparation.profile.binder_version)
        self.assertEqual(trace2.instantiated_profile_hash, artifact2.content_hash)
        self.assertEqual(artifact2.content_hash, preparation.profile_artifact.content_hash)

    def test_profile_binder_instantiates_other_ids_without_hand_binding(self):
        structure = DecisionStructure(
            decision_id="D-999",
            decision_display="this decision",
            facts=(
                DecisionFactBinding("FX", "beacon_reactivation_delay", "Supplier Y requires 12 weeks to reactivate"),
            ),
            relations=(
                DecisionRelationBinding("RX", RelationType.HISTORICAL_SUPPORT, "FX", "D-999"),
            ),
        )
        profile, _trace = ProfileBinder().bind(
            template=supplier_resilience_capture_template(),
            structure=structure,
        )
        self.assertEqual(profile.slots[0].slot.id, "RX")
        self.assertEqual(profile.slots[0].slot.subject_id, "FX")
        self.assertEqual(profile.slots[0].slot.object_id, "D-999")
        self.assertIn("Supplier Y requires 12 weeks", profile.slots[0].question_text)

    def test_assigned_profile_hash_is_reverified_before_gap_selection(self):
        preparation = prepare_golden_capture()
        profile = preparation.profile
        mutated = replace(profile, slots=(replace(profile.slots[0], question_text="changed copy"),))
        with self.assertRaisesRegex(ValueError, "does not match the assigned canonical artifact"):
            select_critical_gaps(
                profile=mutated,
                assignment=preparation.assignment,
                decision_id=preparation.draft_contract.id,
                known_fact_ids=preparation.known_fact_ids,
                established_relation_ids=preparation.established_relation_ids,
                selected_at=T0 - timedelta(seconds=1),
            )

    def test_gap_selection_uses_structured_fields_not_reason_text(self):
        preparation = prepare_golden_capture()
        original = preparation.profile.slots[0]
        mutated = replace(
            preparation.profile,
            slots=(replace(original, slot=replace(original.slot, reason_for_checking="MEANINGLESS")),),
        )
        artifact = make_capture_profile_artifact(mutated)
        assignment = assign_profile(
            session_id="TEST-CAPTURE-REASON",
            artifact=artifact,
            assigned_at=T0 - timedelta(seconds=2),
        )
        gaps = select_critical_gaps(
            profile=mutated,
            assignment=assignment,
            decision_id="D-104",
            known_fact_ids=preparation.known_fact_ids,
            established_relation_ids=preparation.established_relation_ids,
            selected_at=T0 - timedelta(seconds=1),
        )
        self.assertEqual(tuple(item.slot_id for item in gaps), ("R2",))

    def test_critical_gap_api_has_no_future_world_input(self):
        parameters = inspect.signature(select_critical_gaps).parameters
        forbidden = {"future_event", "world_event", "world_state", "evaluation", "target_evaluation"}
        self.assertTrue(forbidden.isdisjoint(parameters))

    # N: compiler proposes semantic keys/spans; Decision Recall owns canonical identity.
    def test_compiler_candidate_cannot_choose_canonical_entity_or_authorization(self):
        candidate_fields = {field.name for field in fields(GroundedCandidate)}
        self.assertNotIn("entity_id", candidate_fields)
        self.assertNotIn("assertion", candidate_fields)
        self.assertIn("semantic_key", candidate_fields)
        self.assertIn("kind", candidate_fields)

    def test_semantic_key_resolves_only_inside_allowed_surface(self):
        preparation = prepare_golden_capture()
        resolver = SemanticCandidateResolver()
        source = preparation.observable.source_map()["supplier-record"]
        candidate = GroundedCandidate(
            "GOOD-F2",
            "beacon_reactivation_delay",
            CandidateKind.FACT,
            source.source_id,
            0,
            len(source.content),
        )
        resolved = resolver.resolve(
            candidate=candidate,
            contract=preparation.draft_contract,
            profile=preparation.profile,
        )
        self.assertEqual(resolved.entity_id, "F2")
        self.assertEqual(resolved.assertion.value, "established_fact")

    def test_unknown_wrong_type_and_unassigned_semantics_fail_closed(self):
        preparation = prepare_golden_capture()
        resolver = SemanticCandidateResolver()
        base = dict(candidate_id="BAD", source_id="supplier-record", start=0, end=5)

        with self.assertRaisesRegex(ValueError, "unknown or ambiguous"):
            resolver.resolve(
                candidate=GroundedCandidate(semantic_key="does_not_exist", kind=CandidateKind.FACT, **base),
                contract=preparation.draft_contract,
                profile=preparation.profile,
            )
        with self.assertRaisesRegex(ValueError, "unknown or ambiguous"):
            resolver.resolve(
                candidate=GroundedCandidate(
                    semantic_key="beacon_reactivation_delay",
                    kind=CandidateKind.HISTORICAL_ROLE,
                    **base,
                ),
                contract=preparation.draft_contract,
                profile=preparation.profile,
            )
        with self.assertRaisesRegex(ValueError, "unknown or ambiguous"):
            resolver.resolve(
                candidate=GroundedCandidate(
                    semantic_key="UNASSIGNED_HISTORICAL_ROLE",
                    kind=CandidateKind.HISTORICAL_ROLE,
                    **base,
                ),
                contract=preparation.draft_contract,
                profile=preparation.profile,
            )

    def test_evidence_resolver_uses_exact_original_source_span(self):
        source = SourceDocument(
            "source",
            "prefix exact evidence suffix",
            ProvenanceType.CONTEMPORANEOUS_RECORD,
            T0,
        )
        observable = ObservableDecisionBundle("D-X", (source,))
        resolved = replace(
            SemanticCandidateResolver().resolve(
                candidate=GroundedCandidate(
                    "C",
                    "beacon_reactivation_delay",
                    CandidateKind.FACT,
                    "source",
                    7,
                    21,
                ),
                contract=prepare_golden_capture().draft_contract,
                profile=prepare_golden_capture().profile,
            ),
            source_id="source",
            start=7,
            end=21,
        )
        evidence = EvidenceResolver().resolve(observable=observable, candidate=resolved, evidence_id="E-X")
        self.assertEqual(evidence.content, "exact evidence")
        self.assertEqual(evidence.source_span, "chars:7-21")

    def test_deterministic_compiler_points_to_sources_instead_of_writing_evidence(self):
        preparation = prepare_golden_capture(compiler=DeterministicGoldenCompiler())
        source_map = preparation.observable.source_map()
        for raw, evidence in zip(preparation.compiler_candidates.candidates, preparation.precommit_evidence):
            source = source_map[raw.source_id]
            self.assertEqual(evidence.content, source.content[raw.start:raw.end])
            self.assertEqual(evidence.source_id, raw.source_id)

    def test_product_path_imports_strict_replay_only(self):
        source = inspect.getsource(golden_loop_module)
        self.assertIn("strict_full_replay", source)
        self.assertIn("strict_verify_full_replay", source)
        self.assertNotIn("from ..m21 import full_replay", source)
        self.assertNotIn("from ..m21 import verify_full_replay", source)

    def test_candidate_dto_cannot_express_canonical_epistemic_outcomes(self):
        candidate_fields = {field.name for field in fields(CandidateView)}
        forbidden = {
            "knowledge_state", "safe_reuse_result", "review_state", "current_match",
            "authorization_status", "composition_value",
        }
        self.assertTrue(forbidden.isdisjoint(candidate_fields))

    # O: issuing a question consumes interaction budget whether or not it is answered.
    def test_r2_is_only_initial_question_and_issuing_it_consumes_budget(self):
        preparation = prepare_golden_capture()
        self.assertEqual(tuple(gap.slot_id for gap in preparation.critical_gaps), ("R2",))
        self.assertEqual(preparation.session.questions_issued, ("R2",))
        self.assertEqual(preparation.session.budget_total, 1)
        self.assertEqual(preparation.session.remaining_budget, 0)

    def test_c1_ineligible_before_r2_then_eligible_but_budget_blocks_second_question(self):
        preparation = prepare_golden_capture()
        c1 = preparation.draft_contract.composition("C1")
        self.assertFalse(
            composition_question_eligible(
                composition=c1,
                established_relation_ids=preparation.established_relation_ids,
            )
        )
        self.assertTrue(
            composition_question_eligible(
                composition=c1,
                established_relation_ids=frozenset({"R1", "R2"}),
            )
        )
        self.assertEqual(
            plan_questions(session=preparation.session, eligible_composition_ids=("C1",)),
            (),
        )

    def test_question_budget_is_consumed_on_issue_not_response(self):
        preparation = prepare_golden_capture()
        issued = preparation.session
        self.assertEqual(issued.questions_issued, ("R2",))
        self.assertEqual(issued.remaining_budget, 0)
        # The no-answer execution fails closed on authority, but it cannot regain budget.
        with self.assertRaisesRegex(ValueError, "R2 remains NOT_DURABLY_RECORDED"):
            run_golden_decision(answer_r2=False)

    def test_same_assigned_profile_hash_is_bound_to_commit(self):
        result = run_golden_decision()
        preparation = prepare_golden_capture()
        self.assertEqual(result.capture_profile.artifact_id, preparation.profile_artifact.artifact_id)
        self.assertEqual(result.capture_profile.content_hash, preparation.profile_artifact.content_hash)
        self.assertEqual(result.commit.capture_profile_hash, preparation.assignment.profile_hash)
        self.assertEqual(preparation.binding_trace.instantiated_profile_hash, preparation.assignment.profile_hash)


if __name__ == "__main__":
    unittest.main()
