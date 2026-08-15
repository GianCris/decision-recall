import copy
import unittest

from dr_bench import ScenarioValidationError, load_scenario, validate_scenario


class ValidationTests(unittest.TestCase):
    def test_bundled_scenario_is_valid(self):
        validate_scenario(load_scenario("dev-001"))

    def test_rejects_out_of_order_events(self):
        scenario = copy.deepcopy(load_scenario("dev-001"))
        scenario["events"][1]["seq"] = 1
        with self.assertRaises(ScenarioValidationError):
            validate_scenario(scenario)

    def test_rejects_oracle_inconsistent_with_world(self):
        scenario = copy.deepcopy(load_scenario("dev-001"))
        scenario["oracle"]["final_world"]["/procurement/vendor"] = "Atlas"
        with self.assertRaises(ScenarioValidationError):
            validate_scenario(scenario)

    def test_rejects_unknown_assertion_operator(self):
        scenario = copy.deepcopy(load_scenario("dev-001"))
        scenario["oracle"]["assertions"][0]["op"] = "similar"
        with self.assertRaises(ScenarioValidationError):
            validate_scenario(scenario)


if __name__ == "__main__":
    unittest.main()
