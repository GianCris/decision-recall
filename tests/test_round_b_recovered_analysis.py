import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dr_bench.catalog as catalog
import dr_baselines.round_b_recovered_analysis as recovered


class HoldoutGuard:
    def __init__(self, resource, attempts): self.resource, self.attempts = resource, attempts
    def joinpath(self, *parts):
        if any(str(part).replace("\\", "/").endswith("holdout.jsonl") for part in parts):
            self.attempts.append(parts); raise AssertionError("sealed holdout access attempted")
        return HoldoutGuard(self.resource.joinpath(*parts), self.attempts)
    def read_text(self, *args, **kwargs): return self.resource.read_text(*args, **kwargs)


class RecoveredAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.original = cls.root / "round-b-v02-screening-output"
        cls.recovery = cls.root / "round-b-v02-infra-recovery-output-v3"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "analysis"

    def test_real_sources_compose_71_plus_1_with_exact_coverage(self):
        view = recovered.compose_recovered_view(self.original, self.recovery)
        self.assertEqual(view["original_evaluation_count"], 71)
        self.assertEqual(len(view["runs"]), 72)
        self.assertEqual(view["condition_counts"], {condition: 12 for condition in recovered.FINAL_CONDITIONS})
        keys = [recovered._slot_key(run) for run in view["runs"]]
        self.assertEqual(len(keys), len(set(keys)))
        ledger = recovered._ledger(view["runs"])
        expected = sum(len(s["private"]["decision_labels"]) for s in catalog.load_scenarios("dev")) * 6
        self.assertEqual(len(ledger), expected)
        self.assertEqual(sum(row["infrastructure_recovered"] for row in ledger), 3)

    def test_original_failure_placeholder_not_scored_and_recovery_once(self):
        view = recovered.compose_recovered_view(self.original, self.recovery)
        recovered_runs = [run for run in view["runs"] if run.get("infrastructure_recovered")]
        self.assertEqual(len(recovered_runs), 1)
        self.assertFalse(any(run.get("provider_error") for run in view["runs"]))

    def test_wrong_or_invalid_recovery_is_rejected(self):
        real = recovered._json
        for mutation in ({"scenario_id": "dev-003"}, {"validation_status": "invalid"}):
            def fake(path, mutation=mutation):
                value = real(path)
                if path.name == "recovery_run.json": value = {**value, **mutation}
                return value
            with self.subTest(mutation=mutation), patch.object(recovered, "_json", side_effect=fake):
                with self.assertRaises(recovered.RecoveredAnalysisError): recovered.compose_recovered_view(self.original, self.recovery)

    def test_duplicate_recovered_slot_is_rejected(self):
        real = recovered._jsonl
        def duplicate(path):
            values = real(path)
            if path.name == "runs.jsonl":
                valid = next(run for run in values if run.get("validation_status") == "valid")
                values[-1] = copy.deepcopy(valid)
            return values
        with patch.object(recovered, "_jsonl", side_effect=duplicate):
            with self.assertRaises(recovered.RecoveredAnalysisError): recovered.compose_recovered_view(self.original, self.recovery)

    def test_missing_decision_or_condition_imbalance_blocks(self):
        view = recovered.compose_recovered_view(self.original, self.recovery)
        broken = copy.deepcopy(view["runs"])
        broken[0]["parsed_candidate_response"]["decisions"].pop()
        with self.assertRaises(recovered.RecoveredAnalysisError): recovered._ledger(broken)
        real = recovered._jsonl
        def imbalanced(path):
            values = real(path)
            if path.name == "runs.jsonl": values[0]["condition_id"] = "RC0"
            return values
        with patch.object(recovered, "_jsonl", side_effect=imbalanced):
            with self.assertRaises(recovered.RecoveredAnalysisError): recovered.compose_recovered_view(self.original, self.recovery)

    def test_analysis_is_dev_only_and_holdout_guarded(self):
        attempts, real_files = [], catalog.files
        def guarded(package): return HoldoutGuard(real_files(package), attempts)
        with patch("dr_bench.catalog.files", side_effect=guarded), patch.object(recovered, "load_scenarios", wraps=catalog.load_scenarios) as loader:
            result = recovered.analyze_recovered(self.original, self.recovery, self.output)
        self.assertEqual(attempts, [])
        self.assertTrue(loader.called)
        self.assertTrue(all(call.args == ("dev",) for call in loader.call_args_list))
        self.assertTrue(result["manifest"]["contains_infrastructure_recovered_observation"])
        self.assertEqual(result["manifest"]["out_of_original_order_recovery_count"], 1)
        self.assertFalse(result["analysis"]["confirmation_authorized"])

    def test_source_directories_remain_immutable(self):
        before_original = recovered._source_hashes(self.original); before_recovery = recovered._source_hashes(self.recovery)
        recovered.analyze_recovered(self.original, self.recovery, self.output)
        self.assertEqual(before_original, recovered._source_hashes(self.original))
        self.assertEqual(before_recovery, recovered._source_hashes(self.recovery))

    def test_sensitivity_is_disclosure_not_partial_classification(self):
        result = recovered.analyze_recovered(self.original, self.recovery, self.output)
        sensitivity = result["sensitivity"]
        self.assertEqual(sensitivity["original_view_status"], "PARTIAL / NON-CLASSIFIABLE")
        self.assertEqual(set(sensitivity["affected_contrasts"]), {"RB0_vs_RC0", "RC0_vs_RB1"})
        self.assertNotIn("classification", sensitivity["original_view_status"].lower())

    def test_no_provider_adapter_or_broad_loader_is_used(self):
        with patch("dr_bench.load_scenario", side_effect=AssertionError("broad loader used")), patch("dr_baselines.google_adapter.GeminiVertexAdapter", side_effect=AssertionError("provider used")):
            recovered.analyze_recovered(self.original, self.recovery, self.output)


if __name__ == "__main__": unittest.main()
