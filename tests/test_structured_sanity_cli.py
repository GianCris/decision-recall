import tempfile
import unittest
import importlib
from pathlib import Path
from unittest.mock import patch

from dr_baselines import RunRecord
from dr_baselines.google_adapter import MODEL_ID
from dr_baselines.structured_sanity import main


class StructuredSanityCliTests(unittest.TestCase):
    def new_output(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name) / "structured-sanity"

    @patch("dr_baselines.structured_sanity.GeminiVertexAdapter")
    def test_without_execute_refuses_before_adapter_construction(self, adapter_type):
        output = self.new_output()
        self.assertEqual(main(["--output-dir", str(output)]), 2)
        adapter_type.assert_not_called()
        self.assertFalse(output.exists())

    def test_import_cannot_construct_provider_or_reference_protected_data(self):
        import dr_baselines.structured_sanity as structured_sanity

        with patch("dr_baselines.google_adapter.genai.Client") as client_type:
            importlib.reload(structured_sanity)
        client_type.assert_not_called()
        source = Path(structured_sanity.__file__).read_text(encoding="utf-8")
        self.assertNotIn("pilot-output", source)
        self.assertNotIn("sealed_holdout", source)

    @patch("dr_baselines.structured_sanity.run_baseline")
    @patch("dr_baselines.structured_sanity.GeminiVertexAdapter")
    def test_execute_is_one_fixed_b0_dev_001_call(self, adapter_type, run):
        output = self.new_output()
        adapter = adapter_type.return_value
        run.return_value = RunRecord(
            baseline_id="B0", scenario_id="dev-001", condition="implicit",
            prompt_version="0.1", experiment_config_version="structured-sanity-0.1", model_adapter="mock",
            raw_model_response="{}", parsed_candidate_response={}, validation_status="valid",
            repetition_id="1",
        )
        self.assertEqual(main(["--output-dir", str(output), "--execute"]), 0)
        args, kwargs = run.call_args
        self.assertEqual(args[0], "B0")
        self.assertEqual(args[1]["id"], "dev-001")
        self.assertIs(args[2], adapter)
        self.assertEqual(args[3].model_name, MODEL_ID)
        self.assertEqual(args[3].version, "structured-sanity-0.1")
        self.assertEqual(args[3].scenario_ids, ("dev-001",))
        self.assertEqual(kwargs["repetition_id"], "1")
        self.assertIs(kwargs["structured_output"], True)
        self.assertTrue((output / "run.json").is_file())
        adapter.close.assert_called_once()

    @patch("dr_baselines.structured_sanity.GeminiVertexAdapter")
    def test_existing_output_is_rejected_before_adapter_construction(self, adapter_type):
        output = self.new_output()
        output.mkdir()
        self.assertEqual(main(["--output-dir", str(output), "--execute"]), 2)
        adapter_type.assert_not_called()


if __name__ == "__main__":
    unittest.main()
