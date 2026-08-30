import hashlib
import unittest
from pathlib import Path


class FrozenBenchmarkTests(unittest.TestCase):
    HASHES = {
        "dr_bench/data/dev.jsonl": "75eced4e08989d9a294895d349e3669df3fdd216a4c9ed48bc8c55aee47289ad",
        "dr_bench/data/holdout.jsonl": "9d9c94781eeba6b0acbed10488f2ebe583c10b642dc26eb6d235638a08b75113",
        "dr_bench/data/interaction_chains.json": "a000bef1625969f566e65900fab655b5e242a224c95ff4c69ac62d9138d6a422",
        "dr_bench/schema/scenario.schema.json": "5b7a6e92fed04ca930d051c07d043362165e13c5b5c9bdac67bd342064eebca6",
    }

    def test_frozen_benchmark_artifacts_are_byte_identical(self):
        root = Path(__file__).resolve().parents[1]
        for relative, expected in self.HASHES.items():
            actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, relative)
