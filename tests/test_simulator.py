import unittest

from dr_bench import load_scenario, simulate_recovery
from dr_bench.simulator import SimulationError


class SimulatorTests(unittest.TestCase):
    def test_recovery_is_deterministic_and_non_mutating(self):
        scenario = load_scenario("dev-009")
        first = simulate_recovery(scenario, ["a1"])
        second = simulate_recovery(scenario, ["a1"])
        self.assertEqual(first, second)
        self.assertEqual(first["meeting_room"], "C")
        self.assertEqual(first["catering_room"], "C")
        self.assertEqual(scenario["candidate"]["world"]["meeting_room"], "A")

    def test_action_order_is_respected(self):
        scenario = load_scenario("dev-001")
        self.assertEqual(simulate_recovery(scenario, ["a1"])["order_supplier"], "Atlas")

    def test_unknown_action_fails(self):
        with self.assertRaises(SimulationError):
            simulate_recovery(load_scenario("dev-001"), ["unknown"])
