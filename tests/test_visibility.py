import unittest

from dr_bench import candidate_view, load_scenarios
from dr_bench.views import contains_private_key


class VisibilityTests(unittest.TestCase):
    def test_discovery_view_never_contains_private_ground_truth(self):
        for scenario in load_scenarios():
            view = candidate_view(scenario, "discovery")
            self.assertFalse(contains_private_key(view), scenario["id"])
            self.assertNotIn("affected_decision_ids", view)

    def test_recovery_gets_only_affected_ids_from_ground_truth(self):
        for scenario in load_scenarios():
            view = candidate_view(scenario, "recovery")
            expected = [x["decision_id"] for x in scenario["private"]["decision_labels"] if x["materially_dependent"]]
            self.assertEqual(view["affected_decision_ids"], expected)
            self.assertFalse(contains_private_key(view), scenario["id"])

    def test_view_is_a_deep_copy(self):
        scenario = load_scenarios()[0]
        view = candidate_view(scenario)
        view["world"].clear()
        self.assertTrue(scenario["candidate"]["world"])
