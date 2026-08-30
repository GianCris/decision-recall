import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dr_baselines import DeterministicMockAdapter
from dr_baselines.google_adapter import GeminiAuthenticationError
from dr_baselines.pilot import (
    PILOT_BASELINES, PILOT_REPETITIONS, PILOT_SCENARIOS,
    build_schedule, main, run_fixed_pilot,
)


VALID_RESPONSE = json.dumps({"decisions": [
    {"decision_id": decision_id, "materially_dependent": False, "dependency_strength": "independent", "still_justified": True}
    for decision_id in ("d1", "d2", "d3")
]})


class CountingAdapter(DeterministicMockAdapter):
    def __init__(self, responses=None):
        super().__init__(VALID_RESPONSE)
        self.responses = list(responses or [])
        self.calls = 0
        self.closed = False

    def generate(self, prompt, config, response_schema=None):
        self.calls += 1
        if self.responses:
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            self.response_text = item
        return super().generate(prompt, config, response_schema=response_schema)

    def close(self):
        self.closed = True


class PilotTests(unittest.TestCase):
    def new_output(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name) / "pilot"

    def test_schedule_is_exactly_nine_calls(self):
        schedule = build_schedule()
        self.assertEqual(len(schedule), 9)
        self.assertEqual({item.scenario_id for item in schedule}, set(PILOT_SCENARIOS))
        self.assertEqual({item.baseline_id for item in schedule}, set(PILOT_BASELINES))
        self.assertEqual({item.repetition_id for item in schedule}, set(PILOT_REPETITIONS))

    def test_matrix_cannot_expand_or_change(self):
        with self.assertRaises(ValueError):
            build_schedule(PILOT_SCENARIOS + ("dev-001",), PILOT_BASELINES, PILOT_REPETITIONS)
        with self.assertRaises(ValueError):
            build_schedule(PILOT_SCENARIOS, PILOT_BASELINES + ("B3",), PILOT_REPETITIONS)
        with self.assertRaises(ValueError):
            build_schedule(PILOT_SCENARIOS, PILOT_BASELINES, ("1", "2"))

    @patch("dr_baselines.pilot.GeminiVertexAdapter")
    def test_cli_without_execute_makes_no_call_and_no_output(self, adapter_type):
        output = self.new_output()
        self.assertEqual(main(["--output-dir", str(output)]), 2)
        adapter_type.assert_not_called()
        self.assertFalse(output.exists())

    def test_valid_matrix_persists_nine_runs_and_evaluations(self):
        adapter = CountingAdapter()
        output = self.new_output()
        summary = run_fixed_pilot(output, lambda: adapter)
        self.assertEqual(adapter.calls, 9)
        self.assertEqual(adapter.response_schemas, [None] * 9)
        self.assertTrue(adapter.closed)
        runs = [json.loads(line) for line in (output / "runs.jsonl").read_text().splitlines()]
        evaluations = [json.loads(line) for line in (output / "evaluations.jsonl").read_text().splitlines()]
        self.assertEqual(len(runs), 9)
        self.assertEqual(len(evaluations), 9)
        self.assertEqual(summary["attempted_call_count"], 9)
        self.assertEqual(summary["status"], "completed")
        expected = {(s, b, "1") for s in PILOT_SCENARIOS for b in PILOT_BASELINES}
        actual = {(x["scenario_id"], x["baseline_id"], x["repetition_id"]) for x in evaluations}
        self.assertEqual(actual, expected)
        for item in runs:
            metadata = dict(item["experiment_config"]["generation_config"])
            self.assertIs(metadata["native_structured_output"], False)
            self.assertIsNone(metadata["response_mime_type"])
            self.assertIsNone(metadata["response_schema_version"])

    def test_invalid_outputs_are_recorded_without_retry_or_evaluation(self):
        adapter = CountingAdapter(["{}"] * 9)
        output = self.new_output()
        summary = run_fixed_pilot(output, lambda: adapter)
        self.assertEqual(adapter.calls, 9)
        runs = [json.loads(line) for line in (output / "runs.jsonl").read_text().splitlines()]
        self.assertTrue(all(item["validation_status"] == "invalid" for item in runs))
        self.assertEqual(summary["invalid_response_count"], 9)
        self.assertFalse((output / "evaluations.jsonl").exists())

    def test_isolated_provider_error_is_recorded_and_remaining_calls_continue(self):
        adapter = CountingAdapter([RuntimeError("temporary provider failure")])
        output = self.new_output()
        summary = run_fixed_pilot(output, lambda: adapter)
        self.assertEqual(adapter.calls, 9)
        self.assertEqual(summary["status"], "completed")
        runs = [json.loads(line) for line in (output / "runs.jsonl").read_text().splitlines()]
        self.assertEqual(sum(item["validation_status"] == "provider_error" for item in runs), 1)
        self.assertEqual(len((output / "evaluations.jsonl").read_text().splitlines()), 8)

    def test_systemic_failure_records_attempt_then_aborts(self):
        adapter = CountingAdapter([GeminiAuthenticationError("bad ADC")])
        output = self.new_output()
        summary = run_fixed_pilot(output, lambda: adapter)
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(summary["status"], "aborted")
        self.assertEqual(summary["attempted_call_count"], 1)
        runs = [json.loads(line) for line in (output / "runs.jsonl").read_text().splitlines()]
        self.assertEqual(len(runs), 1)
        metadata = dict(runs[0]["experiment_config"]["generation_config"])
        self.assertIs(metadata["native_structured_output"], False)

    def test_oracle_evaluation_occurs_only_after_response(self):
        adapter = CountingAdapter()
        events = []
        original_generate = adapter.generate
        def generate(prompt, config, response_schema=None):
            result = original_generate(prompt, config, response_schema=response_schema)
            events.append("response_complete")
            return result
        adapter.generate = generate
        from dr_bench import evaluate_discovery as real_evaluate
        def evaluate(scenario, candidate):
            self.assertEqual(events[-1], "response_complete")
            events.append("oracle_evaluation")
            return real_evaluate(scenario, candidate)
        with patch("dr_baselines.pilot.evaluate_discovery", side_effect=evaluate):
            run_fixed_pilot(self.new_output(), lambda: adapter)
        self.assertEqual(events, [item for _ in range(9) for item in ("response_complete", "oracle_evaluation")])

    def test_baseline_runner_receives_no_private_partition(self):
        from dr_baselines.runner import run_baseline as real_run
        def guarded_run(baseline_id, scenario, adapter, config, repetition_id=None):
            self.assertNotIn("private", scenario)
            return real_run(baseline_id, scenario, adapter, config, repetition_id)
        with patch("dr_baselines.pilot.run_baseline", side_effect=guarded_run):
            run_fixed_pilot(self.new_output(), CountingAdapter)

    def test_summary_contains_macro_micro_deltas_and_breakdowns(self):
        summary = run_fixed_pilot(self.new_output(), CountingAdapter)
        for baseline in PILOT_BASELINES:
            self.assertIn("macro", summary["per_baseline"][baseline])
            self.assertIn("micro", summary["per_baseline"][baseline])
            self.assertEqual(summary["per_baseline"][baseline]["evaluated_scenario_count"], 3)
        self.assertEqual(set(summary["per_scenario"]), set(PILOT_SCENARIOS))
        self.assertEqual(set(summary["descriptive_deltas"]), {"B1-B0", "B2-B1"})
