from dataclasses import replace
import unittest

from decision_recall.product.golden_loop import run_golden_decision
from decision_recall.product.presentation import build_decision_threads_presentation


class DecisionRecallPresentationTests(unittest.TestCase):
    def test_presentation_is_a_projection_of_frozen_golden_output(self):
        result = run_golden_decision()
        view = build_decision_threads_presentation(result)

        self.assertEqual(view.decision_id, result.commit.decision_id)
        self.assertEqual(view.capture.question, result.critical_gaps[0].question)
        self.assertEqual(view.capture.relation_id, result.r2_trace.entity_id)
        self.assertEqual(view.capture.knowledge_state, result.r2_trace.knowledge_state)
        self.assertEqual(
            tuple((item.entity_id, item.state) for item in view.current_matches),
            result.evaluation.current_matches,
        )
        self.assertEqual(
            view.reuse_boundary.safe_reuse_result,
            result.evaluation.safe_reuse_result,
        )
        self.assertEqual(
            view.reuse_boundary.limiting_requirements,
            result.evaluation.limiting_requirements,
        )
        self.assertEqual(
            view.reuse_boundary.limiting_entity_id,
            result.boundary.limiting_entity_id,
        )
        self.assertEqual(
            view.reuse_boundary.composition_kind,
            result.boundary.composition_kind,
        )
        self.assertEqual(
            view.reuse_boundary.composition_value,
            result.boundary.composition_value,
        )
        self.assertEqual(
            view.reuse_boundary.relation_ids,
            result.boundary.relation_ids,
        )
        self.assertEqual(view.evaluation_hash, result.evaluation.result_hash)
        self.assertEqual(view.replay_hash, result.replay_result_hash)

    def test_presentation_rejects_ambiguous_gap_shape_instead_of_inventing_ui_state(self):
        result = run_golden_decision()
        malformed = replace(result, critical_gaps=())

        with self.assertRaisesRegex(ValueError, "exactly one issued critical gap"):
            build_decision_threads_presentation(malformed)


if __name__ == "__main__":
    unittest.main()