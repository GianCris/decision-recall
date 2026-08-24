import inspect
import unittest
from dataclasses import fields, replace
from datetime import timedelta

from decision_recall.domain import HistoricalKnowledgeState, ProvenanceType
from decision_recall.m21 import canonical_json
from decision_recall.product import golden_loop as golden_loop_module
from decision_recall.product.capture import (
    CaptureInstantiationContext,
    CaptureProfile,
    CaptureSlotSpec,
    assign_profile,
    composition_question_eligible,
    instantiate_capture_profile,
    make_capture_profile_artifact,
    select_critical_gaps,
    supplier_resilience_capture_template,
)
from decision_recall.product.compiler import (
    DeterministicGoldenCompiler,
    EvidenceResolver,
    GroundedCandidate,
    ObservableDecisionBundle,
    SourceDocument,
)
from decision_recall.product.golden_loop import T0, prepare_golden_capture, run_golden_decision
from decision_recall.product.models import CandidateView
from decision_recall.temporal import AuthorizedAssertion


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

    def test_assigned_profile_hash_is_reverified_before_gap_selection(self):
        preparation = prepare_golden_capture()
        profile = preparation.profile
        original = profile.slots[0]
        mutated = replace(
            profile,
            slots=(replace(original, question_text="A changed question under the same version"),),
        )
        self.assertEqual(mutated.version, profile.version)
        with self.assertRaisesRegex(ValueError, "does not match the assigned canonical artifact"):
            select_critical_gaps(
                profile=mutated,
                assignment=preparation.assignment,
                decision_id="D-104",
                known_fact_ids=preparation.known_fact_ids,
                established_relation_ids=preparation.established_relation_ids,
                selected_at=T0 - timedelta(seconds=1),
            )

    def test_capture_template_contains_no_golden_entity_or_future_identifiers(self):
        payload = canonical_json(supplier_resilience_capture_template())
        for forbidden in ("D-104", '"F2"', '"R2"', "Beacon", "10-week", "10 weeks", "E-301", "0.987", "C1"):
            self.assertNotIn(forbidden, payload)

    def test_template_instantiates_for_another_decision_without_special_case(self):
        template = supplier_resilience_capture_template()
        profile = instantiate_capture_profile(
            template=template,
            context=CaptureInstantiationContext(
                decision_id="D-999",
                relation_id="R9",
                subject_id="F9",
                subject_semantic_role="SUPPLIER_REACTIVATION_DELAY",
                subject_display="Supplier Y's reactivation delay",
            ),
        )
        artifact = make_capture_profile_artifact(profile)
        assignment = assign_profile(
            session_id="OFF-GOLDEN",
            artifact=artifact,
            assigned_at=T0 - timedelta(seconds=2),
        )
        gaps = select_critical_gaps(
            profile=profile,
            assignment=assignment,
            decision_id="D-999",
            known_fact_ids=frozenset({"F9"}),
            established_relation_ids=frozenset(),
            selected_at=T0 - timedelta(seconds=1),
        )
        self.assertEqual(tuple(item.slot_id for item in gaps), ("R9",))
        self.assertEqual(gaps[0].object_id, "D-999")

        already_known = select_critical_gaps(
            profile=profile,
            assignment=assignment,
            decision_id="D-999",
            known_fact_ids=frozenset({"F9"}),
            established_relation_ids=frozenset({"R9"}),
            selected_at=T0 - timedelta(seconds=1),
        )
        missing_subject = select_critical_gaps(
            profile=profile,
            assignment=assignment,
            decision_id="D-999",
            known_fact_ids=frozenset(),
            established_relation_ids=frozenset(),
            selected_at=T0 - timedelta(seconds=1),
        )
        self.assertEqual(already_known, ())
        self.assertEqual(missing_subject, ())

    def test_gap_selection_uses_structured_fields_not_reason_text(self):
        preparation = prepare_golden_capture()
        profile = preparation.profile
        original = profile.slots[0]
        mutated = CaptureProfile(
            id=profile.id,
            version=profile.version,
            template_id=profile.template_id,
            template_version=profile.template_version,
            question_budget=profile.question_budget,
            slots=(
                CaptureSlotSpec(
                    semantic_role=original.semantic_role,
                    slot=replace(original.slot, reason_for_checking="MEANINGLESS PRESENTATION TEXT"),
                    requires_subject_fact=original.requires_subject_fact,
                    ephemeral_if_unresolved=original.ephemeral_if_unresolved,
                    priority=original.priority,
                    question_text="Different presentation copy.",
                ),
            ),
        )
        artifact = make_capture_profile_artifact(mutated)
        assignment = assign_profile(
            session_id="TEST-CAPTURE-2",
            artifact=artifact,
            assigned_at=T0 - timedelta(seconds=2),
        )
        gaps = select_critical_gaps(
            profile=mutated,
            assignment=assignment,
            decision_id="D-104",
            known_fact_ids=frozenset({"F1", "F2"}),
            established_relation_ids=frozenset({"R1"}),
            selected_at=T0 - timedelta(seconds=1),
        )
        self.assertEqual(tuple(item.slot_id for item in gaps), ("R2",))

    def test_critical_gap_api_has_no_future_world_input(self):
        parameters = inspect.signature(select_critical_gaps).parameters
        forbidden = {"future_event", "world_event", "world_state", "evaluation", "target_evaluation"}
        self.assertTrue(forbidden.isdisjoint(parameters))

    def test_product_path_imports_strict_replay_only(self):
        source = inspect.getsource(golden_loop_module)
        self.assertIn("strict_full_replay", source)
        self.assertIn("strict_verify_full_replay", source)
        self.assertNotIn("from ..m21 import full_replay", source)
        self.assertNotIn("from ..m21 import verify_full_replay", source)

    def test_candidate_dto_cannot_express_canonical_epistemic_outcomes(self):
        candidate_fields = {field.name for field in fields(CandidateView)}
        forbidden = {
            "knowledge_state",
            "safe_reuse_result",
            "review_state",
            "current_match",
            "authorization_status",
            "composition_value",
        }
        self.assertTrue(forbidden.isdisjoint(candidate_fields))

    def test_compiler_cannot_emit_rules_compositions_or_epistemic_states(self):
        for forbidden_assertion in (
            AuthorizedAssertion.CURRENT_MATCH_RULE,
            AuthorizedAssertion.REVISIT_RULE,
            AuthorizedAssertion.COMPOSITION_TRUE,
            AuthorizedAssertion.T0_UNRESOLVED,
        ):
            with self.assertRaisesRegex(ValueError, "compiler cannot emit"):
                GroundedCandidate(
                    "BAD",
                    "X",
                    forbidden_assertion,
                    "source",
                    0,
                    1,
                )

    def test_evidence_resolver_uses_exact_original_source_span(self):
        source = SourceDocument(
            "source",
            "prefix exact evidence suffix",
            ProvenanceType.CONTEMPORANEOUS_RECORD,
            T0,
        )
        observable = ObservableDecisionBundle("D-X", (source,))
        candidate = GroundedCandidate(
            "C",
            "F-X",
            AuthorizedAssertion.ESTABLISHED_FACT,
            "source",
            7,
            21,
        )
        evidence = EvidenceResolver().resolve(
            observable=observable,
            candidate=candidate,
            evidence_id="E-X",
        )
        self.assertEqual(evidence.content, "exact evidence")
        self.assertNotEqual(evidence.content, source.content)
        self.assertEqual(evidence.source_span, "chars:7-21")

    def test_deterministic_compiler_points_to_sources_instead_of_writing_evidence(self):
        preparation = prepare_golden_capture(compiler=DeterministicGoldenCompiler())
        source_map = preparation.observable.source_map()
        for candidate, evidence in zip(preparation.compiler_candidates.candidates, preparation.precommit_evidence):
            source = source_map[candidate.source_id]
            self.assertEqual(evidence.content, source.content[candidate.start:candidate.end])
            self.assertEqual(evidence.source_id, candidate.source_id)

    def test_c1_is_ineligible_before_r2_and_eligible_after_r2(self):
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

    def test_same_assigned_profile_hash_is_bound_to_commit(self):
        result = run_golden_decision()
        preparation = prepare_golden_capture()
        self.assertEqual(result.capture_profile.artifact_id, preparation.profile_artifact.artifact_id)
        self.assertEqual(result.capture_profile.content_hash, preparation.profile_artifact.content_hash)
        self.assertEqual(result.commit.capture_profile_hash, preparation.assignment.profile_hash)


if __name__ == "__main__":
    unittest.main()
