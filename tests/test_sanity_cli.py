import unittest
from unittest.mock import Mock, patch

from dr_baselines import RunRecord
from dr_baselines.google_adapter import MODEL_ID
from dr_baselines.sanity import main


class SanityCliTests(unittest.TestCase):
    @patch("dr_baselines.sanity.GeminiVertexAdapter")
    def test_without_execute_refuses_before_adapter_construction(self, adapter_type):
        self.assertEqual(main([]), 2)
        adapter_type.assert_not_called()

    @patch("dr_baselines.sanity.run_baseline")
    @patch("dr_baselines.sanity.GeminiVertexAdapter")
    def test_execute_is_exact_fixed_sanity_call(self, adapter_type, run):
        adapter = adapter_type.return_value
        run.return_value = RunRecord(
            baseline_id="B0", scenario_id="dev-001", condition="implicit",
            prompt_version="0.1", experiment_config_version="0.1", model_adapter="mock",
            raw_model_response="{}", parsed_candidate_response={}, validation_status="valid",
        )
        self.assertEqual(main(["--execute"]), 0)
        args, kwargs = run.call_args
        self.assertEqual(args[0], "B0")
        self.assertEqual(args[1]["id"], "dev-001")
        self.assertIs(args[2], adapter)
        self.assertEqual(args[3].model_name, MODEL_ID)
        self.assertEqual(args[3].repetitions, 1)
        self.assertEqual(kwargs["repetition_id"], "1")
        self.assertNotIn("structured_output", kwargs)
        adapter.close.assert_called_once()
