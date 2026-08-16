import json
import unittest

from dr_bench import load_scenario
from dr_baselines import (
    DISCOVERY_RESPONSE_JSON_SCHEMA,
    DeterministicMockAdapter,
    ExperimentConfig,
    RetryPolicy,
    run_baseline,
)


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

    def test_default_execution_is_unstructured_for_every_baseline(self):
        schemas = {}
        for baseline_id in ("B0", "B1", "B2"):
            adapter = DeterministicMockAdapter(response_for(self.scenario))
            run_baseline(baseline_id, self.scenario, adapter, self.config)
            schemas[baseline_id] = adapter.response_schemas[0]
        self.assertEqual(schemas, {"B0": None, "B1": None, "B2": None})

    def test_b0_and_b1_share_the_explicit_structured_schema(self):
        for baseline_id in ("B0", "B1"):
            adapter = DeterministicMockAdapter(response_for(self.scenario))
            run_baseline(baseline_id, self.scenario, adapter, self.config, structured_output=True)
            self.assertIs(adapter.response_schemas[0], DISCOVERY_RESPONSE_JSON_SCHEMA)

    def test_structured_request_contains_no_private_or_scenario_answers(self):
        for baseline_id in ("B0", "B1"):
            adapter = DeterministicMockAdapter(response_for(self.scenario))
            run_baseline(
                baseline_id,
                PrivateGuard(self.scenario),
                adapter,
                self.config,
                structured_output=True,
            )
            request_text = adapter.prompts[0] + json.dumps(adapter.response_schemas[0], sort_keys=True)
            for forbidden in (
                "decision_labels", "expected_actions", "expected_final_world",
                "must_recover", "must_not_touch", "dependency_path",
            ):
                self.assertNotIn(forbidden, request_text)
            for decision in self.scenario["private"]["decision_labels"]:
                self.assertNotIn(decision.get("rationale", "private rationale sentinel"), request_text)

    def test_execution_mode_is_serialized_in_config_metadata(self):
        for enabled in (False, True):
            adapter = DeterministicMockAdapter(response_for(self.scenario))
            record = run_baseline("B0", self.scenario, adapter, self.config, structured_output=enabled)
            metadata = dict(record.experiment_config["generation_config"])
            self.assertIs(metadata["native_structured_output"], enabled)
            self.assertEqual(metadata["response_mime_type"], "application/json" if enabled else None)
            self.assertEqual(
                metadata["response_schema_version"],
                "discovery-response-v0.1" if enabled else None,
            )

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
        self.assertEqual(value["experiment_config"]["version"], "0.1")

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
