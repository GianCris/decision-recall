import unittest

from dr_bench import candidate_view, load_scenarios
from dr_bench.views import contains_private_key


class VisibilityTests(unittest.TestCase):
    def test_both_discovery_conditions_hide_private_ground_truth(self):
        for scenario in load_scenarios():
            for condition in ("implicit", "structured"):
                view = candidate_view(scenario, "discovery", condition)
                self.assertFalse(contains_private_key(view), scenario["id"])
                self.assertNotIn("affected_decision_ids", view)

    def test_implicit_discovery_has_no_exact_decision_knowledge_links(self):
        for scenario in load_scenarios():
            view = candidate_view(scenario, "discovery", "implicit")
            self.assertEqual(view["discovery_condition"], "implicit")
            for decision in view["decisions"]:
                self.assertNotIn("evidence_available", decision, scenario["id"])
                self.assertNotIn("assumptions", decision, scenario["id"])

    def test_structured_discovery_retains_provenance(self):
        for scenario in load_scenarios():
            view = candidate_view(scenario, "discovery", "structured")
            self.assertEqual(view["discovery_condition"], "structured")
            self.assertTrue(all("evidence_available" in d and "assumptions" in d for d in view["decisions"]), scenario["id"])

    def test_recovery_gets_only_affected_ids_from_ground_truth(self):
        for scenario in load_scenarios():
            view = candidate_view(scenario, "recovery")
            expected = [x["decision_id"] for x in scenario["private"]["decision_labels"] if x["materially_dependent"]]
            self.assertEqual(view["affected_decision_ids"], expected)
            self.assertFalse(contains_private_key(view), scenario["id"])

    def test_view_is_a_deep_copy(self):
        scenario = load_scenarios()[0]
        view = candidate_view(scenario, condition="implicit")
        view["world"].clear()
        self.assertTrue(scenario["candidate"]["world"])
