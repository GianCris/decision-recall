import unittest

from dr_bench import evaluate, load_scenario


class EvaluatorTests(unittest.TestCase):
    def test_correct_candidate_passes(self):
        result = evaluate(load_scenario("dev-001"), {"vendor": "Nimbus", "region": "eu-west"})
        self.assertTrue(result.passed)
        self.assertEqual(result.score, 1.0)

    def test_partial_candidate_gets_fractional_score(self):
        result = evaluate(load_scenario("dev-001"), {"vendor": "Nimbus", "region": "us-east"})
        self.assertFalse(result.passed)
        self.assertEqual(result.score, 0.5)

    def test_absence_is_distinct_from_null(self):
        scenario = load_scenario("dev-007")
        absent = evaluate(scenario, {"state": "postponed"})
        null = evaluate(scenario, {"state": "postponed", "date": None})
        self.assertTrue(absent.passed)
        self.assertFalse(null.passed)

    def test_equals_uses_strict_json_types(self):
        scenario = load_scenario("dev-010")
        correct = {"endpoint": "https://api.example/v2", "method": "POST", "enabled": False}
        wrong = {**correct, "enabled": 0}
        self.assertTrue(evaluate(scenario, correct).passed)
        self.assertFalse(evaluate(scenario, wrong).passed)


if __name__ == "__main__":
    unittest.main()
