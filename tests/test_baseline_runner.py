import json
import unittest

from dr_bench import load_scenario
from dr_baselines import DeterministicMockAdapter, ExperimentConfig, RetryPolicy, run_baseline


def response_for(scenario):
    return json.dumps({"decisions": [
        {"decision_id": item["id"], "materially_dependent": False, "dependency_strength": "independent", "still_justified": True}
        for item in scenario["candidate"]["decisions"]
    ]})


class PrivateGuard(dict):
    def __getitem__(self, key):
        if key == "private":
            raise AssertionError("baseline harness accessed private oracle")
        return super().__getitem__(key)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario("dev-001")
        self.config = ExperimentConfig()

    def test_runner_never_accesses_private_oracle(self):
        guarded = PrivateGuard(self.scenario)
        adapter = DeterministicMockAdapter(response_for(self.scenario))
        record = run_baseline("B0", guarded, adapter, self.config)
        self.assertEqual(record.validation_status, "valid")

    def test_each_runner_condition_is_fixed(self):
        for baseline_id, condition in (("B0", "implicit"), ("B1", "structured"), ("B2", "structured")):
            adapter = DeterministicMockAdapter(response_for(self.scenario))
            record = run_baseline(baseline_id, self.scenario, adapter, self.config)
            self.assertEqual(record.condition, condition)
            self.assertIn(f'"discovery_condition":"{condition}"', adapter.prompts[0])

    def test_invalid_output_is_recorded_not_evaluated(self):
        record = run_baseline("B0", self.scenario, DeterministicMockAdapter("{}"), self.config)
        self.assertEqual(record.validation_status, "invalid")
        self.assertIsNone(record.parsed_candidate_response)
        self.assertIsNotNone(record.validation_error)

    def test_serialized_record_has_required_and_future_fields(self):
        adapter = DeterministicMockAdapter(response_for(self.scenario))
        record = run_baseline("B1", self.scenario, adapter, self.config, repetition_id="rep-1")
        value = json.loads(record.to_json())
        required = {"baseline_id", "scenario_id", "condition", "prompt_version", "experiment_config_version", "model_adapter", "raw_model_response", "parsed_candidate_response", "validation_status"}
        self.assertTrue(required <= value.keys())
        for field in ("model_name", "model_version", "latency_ms", "input_tokens", "output_tokens", "repetition_id"):
            self.assertIn(field, value)

    def test_configuration_is_versioned_and_unfrozen_values_are_unset(self):
        config = ExperimentConfig()
        self.assertEqual(config.version, "0.1")
        self.assertIsNone(config.model_name)
        self.assertIsNone(config.model_version)
        self.assertIsNone(config.temperature)
        self.assertIsNone(config.max_output_tokens)
        self.assertIsNone(config.retry_policy.max_attempts)
        self.assertIsNone(config.repetitions)
        self.assertIsNone(config.dataset_id)
        self.assertIsNone(config.dataset_version)
        self.assertEqual(config.scenario_ids, ())
        self.assertIsNone(config.candidate_view_contract_version)
