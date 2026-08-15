import unittest

from dr_bench import evaluate_discovery, evaluate_recovery, load_scenario


def perfect_discovery(scenario):
    return {"decisions": [{k: label[k] for k in ("decision_id", "materially_dependent", "dependency_strength", "still_justified")} for label in scenario["private"]["decision_labels"]]}


class EvaluatorTests(unittest.TestCase):
    def test_perfect_discovery_scores_one(self):
        scenario = load_scenario("dev-004")
        result = evaluate_discovery(scenario, perfect_discovery(scenario))
        self.assertEqual(result.dependency_precision, 1)
        self.assertEqual(result.dependency_recall, 1)
        self.assertEqual(result.dependency_f1, 1)
        self.assertEqual(result.dependency_strength_accuracy, 1)
        self.assertEqual(result.still_justified_accuracy, 1)
        self.assertEqual(result.multi_hop_recall, 1)

    def test_mark_everything_dependent_scores_false_positives(self):
        scenario = load_scenario("dev-001")
        candidate = {"decisions": [{"decision_id": d["id"], "materially_dependent": True} for d in scenario["candidate"]["decisions"]]}
        result = evaluate_discovery(scenario, candidate)
        self.assertEqual(result.false_positive_dependence, 2)
        self.assertLess(result.dependency_precision, 0.5)

    def test_missing_positive_is_false_negative(self):
        result = evaluate_discovery(load_scenario("dev-004"), {"decisions": []})
        self.assertEqual(result.false_negative_dependence, 2)
        self.assertEqual(result.dependency_recall, 0)

    def test_expected_recovery_scores_perfectly(self):
        scenario = load_scenario("holdout-001")
        result = evaluate_recovery(scenario, {"action_ids": ["a1"], "at_step": 1})
        self.assertEqual(result.repair_correctness, 1)
        self.assertEqual(result.wrongful_rollback, 0)
        self.assertEqual(result.unnecessary_disruption, 0)
        self.assertEqual(result.recovered_value, 10)
        self.assertEqual(result.recovery_window_capture, 1)
        self.assertEqual(result.final_world_state_correctness, 1)

    def test_related_decoy_causes_wrongful_rollback(self):
        scenario = load_scenario("holdout-001")
        result = evaluate_recovery(scenario, {"action_ids": ["a1", "a2"], "at_step": 1})
        self.assertEqual(result.wrongful_rollback, 1)
        self.assertGreaterEqual(result.unnecessary_disruption, 1)

    def test_late_action_misses_window(self):
        scenario = load_scenario("holdout-001")
        result = evaluate_recovery(scenario, {"action_ids": ["a1"], "at_step": 2})
        self.assertEqual(result.recovery_window_capture, 0)
