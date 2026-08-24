import inspect
import unittest
from dataclasses import fields, replace
from datetime import timedelta

from decision_recall.domain import HistoricalKnowledgeState
from decision_recall.product import golden_loop as golden_loop_module
from decision_recall.product.capture import (
    CaptureProfile,
    CaptureSlotSpec,
    assign_profile,
    make_capture_profile_artifact,
    select_critical_gaps,
    supplier_resilience_capture_profile,
)
from decision_recall.product.golden_loop import T0, prepare_golden_capture, run_golden_decision
from decision_recall.product.models import CandidateView


class ProductGoldenLoopTests(unittest.TestCase):
    def test_checkpoint_1_runs_end_to_end_with_strict_replay(self):
        result = run_golden_decision()

        self.assertEqual(result.capture_profile.question_budget, 1)
        self.assertEqual(result.capture_profile.slot_ids, ("R2",))
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

    def test_precommit_has_slot_but_no_established_r2_history(self):
        preparation = prepare_golden_capture()
        r2 = preparation.draft_contract.relation("R2")
        self.assertEqual(r2.knowledge_state, HistoricalKnowledgeState.NOT_DURABLY_RECORDED)
        self.assertEqual(r2.evidence_refs, ())
        self.assertEqual(tuple(item.slot_id for item in preparation.critical_gaps), ("R2",))

    def test_no_answer_cannot_promote_r2(self):
        with self.assertRaisesRegex(ValueError, "R2 remains NOT_DURABLY_RECORDED"):
            run_golden_decision(answer_r2=False)

    def test_profile_is_frozen_before_gap_selection_and_has_no_future_leakage(self):
        profile = supplier_resilience_capture_profile()
        artifact = make_capture_profile_artifact(profile)
        assignment = assign_profile(
            session_id="TEST-CAPTURE",
            artifact=artifact,
            assigned_at=T0 - timedelta(seconds=2),
        )
        gaps = select_critical_gaps(
            profile=profile,
            assignment=assignment,
            decision_id="D-104",
            known_fact_ids=frozenset({"F1", "F2"}),
            established_relation_ids=frozenset({"R1"}),
            selected_at=T0 - timedelta(seconds=1),
        )
        self.assertEqual(tuple(item.slot_id for item in gaps), ("R2",))
        self.assertLess(assignment.assigned_at, gaps[0].selected_at)
        self.assertEqual(assignment.profile_hash, artifact.content_hash)

        payload = artifact.canonical_json
        for forbidden in ("E-301", "0.987", "98.7", "C1", "sufficient_alone"):
            self.assertNotIn(forbidden, payload)

    def test_gap_selection_uses_structured_fields_not_reason_text(self):
        profile = supplier_resilience_capture_profile()
        original = profile.slots[0]
        mutated = CaptureProfile(
            id=profile.id,
            version=profile.version,
            question_budget=profile.question_budget,
            slots=(
                CaptureSlotSpec(
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

    def test_same_assigned_profile_hash_is_bound_to_commit(self):
        result = run_golden_decision()
        artifact = make_capture_profile_artifact(supplier_resilience_capture_profile())
        self.assertEqual(result.capture_profile.artifact_id, artifact.artifact_id)
        self.assertEqual(result.capture_profile.content_hash, artifact.content_hash)
        self.assertEqual(result.commit.capture_profile_hash, artifact.content_hash)


if __name__ == "__main__":
    unittest.main()
