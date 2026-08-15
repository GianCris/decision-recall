import unittest

from dr_bench import load_scenario, load_scenarios, simulate


class CatalogTests(unittest.TestCase):
    def test_release_has_expected_splits(self):
        self.assertEqual(len(load_scenarios()), 16)
        self.assertEqual(len(load_scenarios("dev")), 12)
        self.assertEqual(len(load_scenarios("holdout")), 4)

    def test_ids_are_unique_and_match_split(self):
        scenarios = load_scenarios()
        self.assertEqual(len({item["id"] for item in scenarios}), 16)
        for item in scenarios:
            self.assertTrue(item["id"].startswith(item["split"] + "-"))

    def test_all_scenarios_simulate_to_declared_invariants(self):
        from dr_bench.paths import get

        for scenario in load_scenarios():
            world = simulate(scenario)
            for path, expected in scenario["oracle"]["final_world"].items():
                self.assertEqual(get(world, path), expected, scenario["id"])

    def test_load_unknown_scenario_fails(self):
        with self.assertRaises(KeyError):
            load_scenario("dev-999")


if __name__ == "__main__":
    unittest.main()
