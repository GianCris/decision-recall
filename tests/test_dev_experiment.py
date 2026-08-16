import hashlib
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from google.genai import _api_client, types

from dr_baselines.baselines import BASE_TASK_PROMPT
from dr_baselines.dev_experiment import (
    DEV_BASELINES,
    DEV_REPETITIONS,
    DEV_SCENARIOS,
    MANIFEST_FILENAME,
    PLAN_FILENAME,
    PROMPT_SHA256,
    SCHEMA_SHA256,
    TRANSPORT_ATTEMPTS,
    TRANSPORT_TIMEOUT_MS,
    TRANSPORT_TIMEOUT_SECONDS,
    DevExperimentError,
    build_execution_plan,
    _dev_adapter_factory,
    _dev_http_options,
    execute_experiment,
    main,
    prepare_experiment,
    validate_execution_plan,
)
from dr_baselines.google_adapter import GeminiAuthenticationError
from dr_baselines.models import ModelResponse
from dr_baselines.output import DISCOVERY_RESPONSE_JSON_SCHEMA, DISCOVERY_RESPONSE_SCHEMA_VERSION


GIT_SHA = "a" * 40


class ScenarioAwareAdapter:
    identifier = "scenario-aware-mock"

    def __init__(self, failures=None, invalid=False):
        self.failures = dict(failures or {})
        self.invalid = invalid
        self.calls = []
        self.closed = False

    def generate(self, prompt, config, response_schema=None):
        call_index = len(self.calls) + 1
        self.calls.append({"prompt": prompt, "config": config, "response_schema": response_schema})
        if call_index in self.failures:
            raise self.failures[call_index]
        if self.invalid:
            return ModelResponse(text="not json", latency_ms=1.0)
        visible = json.loads(prompt.split("\n\nCANDIDATE-VISIBLE SCENARIO:\n", 1)[1])
        response = {"decisions": [
            {
                "decision_id": decision["id"],
                "materially_dependent": False,
                "dependency_strength": "independent",
                "still_justified": True,
            }
            for decision in visible["decisions"]
        ]}
        return ModelResponse(
            text=json.dumps(response), model_name="gemini-3.7-flash",
            model_version="mock-version", latency_ms=1.0, input_tokens=10, output_tokens=5,
        )

    def close(self):
        self.closed = True


class DevExperimentTests(unittest.TestCase):
    def new_output(self, name="dev-output"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name) / name

    def frozen_git(self):
        return patch.multiple(
            "dr_baselines.dev_experiment",
            _git_commit_sha=Mock(return_value=GIT_SHA),
            _tracked_tree_clean=Mock(return_value=True),
        )

    def prepared(self):
        output = self.new_output()
        with self.frozen_git():
            prepare_experiment(output)
        return output

    def test_plan_is_exact_balanced_adjacent_matrix(self):
        plan = build_execution_plan()
        self.assertEqual(len(plan), 72)
        self.assertEqual(sum(item["baseline_id"] == "B0" for item in plan), 36)
        self.assertEqual(sum(item["baseline_id"] == "B1" for item in plan), 36)
        first = [item for item in plan if item["order_within_pair"] == 1]
        self.assertEqual(sum(item["baseline_id"] == "B0" for item in first), 18)
        self.assertEqual(sum(item["baseline_id"] == "B1" for item in first), 18)
        for offset in range(0, 72, 2):
            left, right = plan[offset:offset + 2]
            self.assertEqual(left["pair_id"], right["pair_id"])
            self.assertEqual((left["order_within_pair"], right["order_within_pair"]), (1, 2))
        counts = {(scenario, baseline, repetition): 0 for scenario in DEV_SCENARIOS for baseline in DEV_BASELINES for repetition in DEV_REPETITIONS}
        for item in plan:
            counts[(item["scenario_id"], item["baseline_id"], item["repetition_id"])] += 1
        self.assertTrue(all(value == 1 for value in counts.values()))
        plan_bytes = (json.dumps(plan, indent=2, sort_keys=True) + "\n").encode("utf-8")
        self.assertEqual(hashlib.sha256(plan_bytes).hexdigest(), "b04496c00c3e5bc991e41b591254b73d222d430edfc30159b3deb0a4de2e40b7")

    def test_odd_even_order_rule_is_exact(self):
        plan = build_execution_plan()
        first = {(item["scenario_id"], item["repetition_id"]): item["baseline_id"] for item in plan if item["order_within_pair"] == 1}
        for scenario_id in DEV_SCENARIOS:
            odd = int(scenario_id[-3:]) % 2 == 1
            self.assertEqual(first[(scenario_id, "1")], "B0" if odd else "B1")
            self.assertEqual(first[(scenario_id, "2")], "B1" if odd else "B0")
            self.assertEqual(first[(scenario_id, "3")], "B0" if odd else "B1")

    def test_plan_bytes_are_deterministic_and_hash_detects_change(self):
        left, right = self.new_output("left"), self.new_output("right")
        with self.frozen_git():
            prepare_experiment(left)
            prepare_experiment(right)
        left_bytes = (left / PLAN_FILENAME).read_bytes()
        right_bytes = (right / PLAN_FILENAME).read_bytes()
        self.assertEqual(left_bytes, right_bytes)
        self.assertNotEqual(hashlib.sha256(left_bytes).hexdigest(), hashlib.sha256(left_bytes + b" ").hexdigest())

    def test_execute_refuses_modified_plan_before_adapter_construction(self):
        output = self.prepared()
        with (output / PLAN_FILENAME).open("ab") as stream:
            stream.write(b" ")
        factory = Mock()
        with self.frozen_git(), self.assertRaises(DevExperimentError):
            execute_experiment(output, factory)
        factory.assert_not_called()

    def test_execute_refuses_modified_manifest_before_adapter_construction(self):
        output = self.prepared()
        manifest_path = output / MANIFEST_FILENAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["model_id"] = "different-model"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        factory = Mock()
        with self.frozen_git(), self.assertRaises(DevExperimentError):
            execute_experiment(output, factory)
        factory.assert_not_called()

    def test_prepare_and_no_action_make_zero_provider_calls(self):
        output = self.new_output()
        with self.frozen_git(), patch("dr_baselines.dev_experiment.GeminiVertexAdapter") as adapter_type:
            self.assertEqual(main(["--output-dir", str(output), "--prepare"]), 0)
            adapter_type.assert_not_called()
        other = self.new_output("other")
        with patch("dr_baselines.dev_experiment.GeminiVertexAdapter") as adapter_type:
            self.assertEqual(main(["--output-dir", str(other)]), 2)
            adapter_type.assert_not_called()

    def test_prepare_refuses_tracked_source_changes(self):
        output = self.new_output()
        with patch("dr_baselines.dev_experiment._git_commit_sha", return_value=GIT_SHA), patch(
            "dr_baselines.dev_experiment._tracked_tree_clean", return_value=False
        ), self.assertRaises(DevExperimentError):
            prepare_experiment(output)
        self.assertFalse(output.exists())

    def test_zz_import_has_no_provider_call_or_historical_output_dependency(self):
        import dr_baselines.dev_experiment as dev_experiment

        with patch("dr_baselines.google_adapter.genai.Client") as client_type:
            importlib.reload(dev_experiment)
        client_type.assert_not_called()
        source = Path(dev_experiment.__file__).read_text(encoding="utf-8")
        self.assertNotIn("pilot-output", source)
        self.assertNotIn("structured-sanity-output", source)
        self.assertNotIn("import sealed_holdout", source)

    def test_all_calls_explicitly_use_one_schema_and_independent_prompts(self):
        output = self.prepared()
        adapter = ScenarioAwareAdapter()
        with self.frozen_git():
            summary = execute_experiment(output, lambda: adapter)
        self.assertEqual(len(adapter.calls), 72)
        self.assertTrue(adapter.closed)
        self.assertTrue(all(call["response_schema"] is DISCOVERY_RESPONSE_JSON_SCHEMA for call in adapter.calls))
        self.assertTrue(all(dict(call["config"].generation_config)["native_structured_output"] is True for call in adapter.calls))
        for call in adapter.calls:
            self.assertNotIn("raw_model_response", call["prompt"])
            self.assertNotIn("parsed_candidate_response", call["prompt"])
            self.assertNotIn("evaluation", call["prompt"])
            self.assertNotIn("decision_labels", call["prompt"])
        self.assertEqual(summary["experiment_status"], "completed")
        self.assertEqual(len(summary["per_scenario"]["dev-001"]["B0"]["evaluations"]), 3)
        self.assertIn("dependency_strength_accuracy", summary["descriptive_B1_minus_B0"]["macro"])

    def test_b0_implicit_and_b1_structured_are_only_input_difference(self):
        output = self.prepared()
        adapter = ScenarioAwareAdapter()
        with self.frozen_git():
            execute_experiment(output, lambda: adapter)
        first_pair = adapter.calls[:2]
        prompts = {"implicit": None, "structured": None}
        for call in first_pair:
            if '"discovery_condition":"implicit"' in call["prompt"]:
                prompts["implicit"] = call["prompt"]
                self.assertNotIn("evidence_available", call["prompt"])
            if '"discovery_condition":"structured"' in call["prompt"]:
                prompts["structured"] = call["prompt"]
                self.assertIn("evidence_available", call["prompt"])
        self.assertTrue(all(prompts.values()))
        self.assertEqual(first_pair[0]["response_schema"], first_pair[1]["response_schema"])

    def test_run_metadata_is_complete_and_evaluation_follows_persistence(self):
        output = self.prepared()
        adapter = ScenarioAwareAdapter()
        from dr_bench import evaluate_discovery as real_evaluate

        evaluations = 0
        def evaluate(scenario, candidate):
            nonlocal evaluations
            persisted = (output / "runs.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertGreater(len(persisted), evaluations)
            evaluations += 1
            return real_evaluate(scenario, candidate)

        with self.frozen_git(), patch("dr_baselines.dev_experiment.evaluate_discovery", side_effect=evaluate):
            execute_experiment(output, lambda: adapter)
        runs = [json.loads(line) for line in (output / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(runs), 72)
        required = {
            "experiment_config_version", "baseline_id", "condition", "scenario_id", "repetition_id",
            "pair_id", "global_call_index", "pair_order", "order_within_pair", "started_at_utc",
            "completed_at_utc", "latency_ms", "git_commit_sha", "prompt_version", "prompt_sha256",
            "response_schema_version", "response_schema_sha256", "execution_plan_sha256", "sdk_package",
            "sdk_version", "candidate_view_contract_version", "dataset_id", "dataset_version",
            "provider_identifier", "project_id", "location", "requested_model_id", "model_version",
            "generation", "input_tokens", "output_tokens", "raw_model_response",
            "parsed_candidate_response", "validation_status", "validation_error", "provider_error",
        }
        self.assertTrue(required <= runs[0].keys())
        self.assertEqual(runs[0]["experiment_config_version"], "dev-baselines-v0.2")
        self.assertTrue(runs[0]["generation"]["native_structured_output"])
        self.assertEqual(runs[0]["response_schema_sha256"], SCHEMA_SHA256)
        self.assertEqual(runs[0]["transport"], {"timeout_ms": 120000, "timeout_seconds": 120, "attempts": 1})

    def test_invalid_and_isolated_errors_persist_without_retry(self):
        invalid_output = self.prepared()
        invalid_adapter = ScenarioAwareAdapter(invalid=True)
        with self.frozen_git():
            invalid_summary = execute_experiment(invalid_output, lambda: invalid_adapter)
        self.assertEqual(len(invalid_adapter.calls), 72)
        self.assertEqual(invalid_summary["invalid_runs"], 72)

        error_output = self.prepared()
        error_adapter = ScenarioAwareAdapter(failures={1: RuntimeError("temporary")})
        with self.frozen_git():
            error_summary = execute_experiment(error_output, lambda: error_adapter)
        self.assertEqual(len(error_adapter.calls), 72)
        self.assertEqual(error_summary["provider_error_runs"], 1)
        self.assertEqual(error_summary["experiment_status"], "completed")

    def test_systemic_error_persists_attempt_and_aborts(self):
        output = self.prepared()
        adapter = ScenarioAwareAdapter(failures={1: GeminiAuthenticationError("bad ADC")})
        with self.frozen_git():
            summary = execute_experiment(output, lambda: adapter)
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(summary["experiment_status"], "aborted")
        self.assertEqual(summary["aggregate_status"], "PARTIAL / ABORTED")
        self.assertFalse(summary["official_result_eligible"])
        self.assertEqual(summary["attempted_calls"], 1)

    def test_keyboard_interrupt_on_first_invocation_writes_truthful_abort(self):
        output = self.prepared()
        adapter = ScenarioAwareAdapter(failures={1: KeyboardInterrupt()})
        with self.frozen_git():
            summary = execute_experiment(output, lambda: adapter)
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(summary["experiment_status"], "aborted")
        self.assertEqual(summary["aggregate_status"], "PARTIAL / ABORTED")
        self.assertFalse(summary["official_result_eligible"])
        self.assertEqual(summary["abort_reason"], "operator_interrupt")
        self.assertEqual(summary["provider_invocations_started"], 1)
        self.assertEqual(summary["completed_provider_calls"], 0)
        self.assertEqual(summary["persisted_run_records"], 0)
        self.assertEqual(summary["persisted_evaluations"], 0)
        self.assertEqual(summary["last_global_call_index_attempted"], 1)
        self.assertFalse((output / "runs.jsonl").exists())
        interruption = summary["interrupted_position"]
        self.assertEqual(interruption["global_call_index"], 1)
        self.assertEqual(interruption["interruption_type"], "KeyboardInterrupt")
        self.assertEqual(interruption["abort_reason"], "operator_interrupt")
        self.assertEqual(interruption["lifecycle_stage"], "provider_invocation_in_flight")
        self.assertTrue(interruption["provider_invocation_started"])
        self.assertTrue((output / "summary.json").is_file())

    def test_keyboard_interrupt_preserves_durable_prefix_and_cannot_resume(self):
        output = self.prepared()
        adapter = ScenarioAwareAdapter(failures={4: KeyboardInterrupt()})
        with self.frozen_git():
            summary = execute_experiment(output, lambda: adapter)
        self.assertEqual(len(adapter.calls), 4)
        self.assertEqual(summary["provider_invocations_started"], 4)
        self.assertEqual(summary["completed_provider_calls"], 3)
        self.assertEqual(summary["persisted_run_records"], 3)
        self.assertEqual(summary["persisted_evaluations"], 3)
        self.assertEqual(len((output / "runs.jsonl").read_text(encoding="utf-8").splitlines()), 3)
        self.assertEqual(len((output / "evaluations.jsonl").read_text(encoding="utf-8").splitlines()), 3)
        self.assertEqual(summary["interrupted_position"]["global_call_index"], 4)
        replacement = Mock()
        with self.frozen_git(), self.assertRaises(DevExperimentError):
            execute_experiment(output, replacement)
        replacement.assert_not_called()

    def test_public_transport_configuration_is_exact(self):
        options = _dev_http_options()
        self.assertIsInstance(options, types.HttpOptions)
        self.assertEqual(options.api_version, "v1")
        self.assertEqual(options.timeout, TRANSPORT_TIMEOUT_MS)
        self.assertEqual(TRANSPORT_TIMEOUT_MS, TRANSPORT_TIMEOUT_SECONDS * 1000)
        self.assertEqual(options.retry_options.attempts, TRANSPORT_ATTEMPTS)
        self.assertEqual(TRANSPORT_ATTEMPTS, 1)
        self.assertEqual(_api_client.get_timeout_in_seconds(options.timeout), 120.0)
        with patch("dr_baselines.dev_experiment.GeminiVertexAdapter") as adapter_type:
            _dev_adapter_factory()
        passed = adapter_type.call_args.kwargs["http_options"]
        self.assertEqual(passed.timeout, 120000)
        self.assertEqual(passed.retry_options.attempts, 1)

    def test_pinned_sdk_none_retry_policy_is_one_attempt(self):
        calls = 0
        def fail():
            nonlocal calls
            calls += 1
            raise RuntimeError("stop")
        retry = __import__("tenacity").Retrying(**_api_client.retry_args(None))
        with self.assertRaises(RuntimeError):
            retry(fail)
        self.assertEqual(calls, 1)
        description = types.HttpRetryOptions.model_fields["attempts"].description
        self.assertIn("including the original request", description)
        self.assertIn("0 or 1", description)

    def test_non_dev_ids_and_forbidden_paths_are_rejected(self):
        for forbidden_id in tuple(f"holdout-{number:03d}" for number in range(101, 109)) + ("dev-013", "unknown"):
            plan = build_execution_plan()
            plan[0]["scenario_id"] = forbidden_id
            with self.assertRaises(DevExperimentError):
                validate_execution_plan(plan)
        with self.assertRaises(DevExperimentError):
            prepare_experiment(self.new_output("sealed_holdout"))

    def test_manifest_freezes_required_design_and_schema_hash(self):
        output = self.prepared()
        manifest = json.loads((output / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(manifest["total_planned_calls"], 72)
        self.assertEqual(manifest["first_position_counts"], {"B0": 18, "B1": 18})
        self.assertEqual(manifest["prompt_sha256"], PROMPT_SHA256)
        self.assertEqual(manifest["response_schema_version"], DISCOVERY_RESPONSE_SCHEMA_VERSION)
        self.assertEqual(manifest["response_schema_sha256"], SCHEMA_SHA256)
        self.assertEqual(manifest["sdk_version"], "2.14.0")
        self.assertEqual(manifest["experiment_version"], "dev-baselines-v0.2")
        self.assertEqual(manifest["transport"]["timeout_ms"], 120000)
        self.assertEqual(manifest["transport"]["timeout_seconds"], 120)
        self.assertEqual(manifest["transport"]["attempts"], 1)
        self.assertEqual(manifest["baseline_allowlist"], ["B0", "B1"])
        self.assertNotIn("B2", json.dumps(json.loads((output / PLAN_FILENAME).read_text())))

    def test_frozen_prompt_hash(self):
        self.assertEqual(PROMPT_SHA256, "2ed1e0280d3108aa9f7458bc7a21d4cf9f82ad2e6c4795d2ac516fffdb5557b1")
        self.assertEqual(PROMPT_SHA256, hashlib.sha256(BASE_TASK_PROMPT.encode("utf-8")).hexdigest())


if __name__ == "__main__":
    unittest.main()
