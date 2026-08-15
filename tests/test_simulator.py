import unittest

from dr_bench import load_scenario, simulate
from dr_bench.simulator import SimulationError


class SimulatorTests(unittest.TestCase):
    def test_set_delete_and_append(self):
        scenario = load_scenario("holdout-003")
        initial = simulate(scenario, through=0)
        final = simulate(scenario)
        self.assertEqual(initial["training"]["venue"], "Bogota HQ")
        self.assertNotIn("venue", final["training"])
        self.assertEqual(final["training"]["instructors"], ["Nora", "Omar"])

    def test_simulation_does_not_mutate_scenario(self):
        scenario = load_scenario("dev-004")
        simulate(scenario)
        self.assertEqual(scenario["world"]["catering"]["constraints"], ["vegetarian"])

    def test_invalid_append_target_fails(self):
        scenario = {
            "world": {"value": 1},
            "events": [{"seq": 1, "operation": "append", "path": "/value", "value": 2}],
        }
        with self.assertRaises(SimulationError):
            simulate(scenario)


if __name__ == "__main__":
    unittest.main()
