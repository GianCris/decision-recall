import hashlib
import importlib
import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from google.genai import _api_client, errors as genai_errors, types

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
    ATTEMPT_LIFECYCLE_FILENAME,
    DELIVERY_BACKOFF_SECONDS,
    MAX_DELIVERY_ATTEMPTS,
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
NO_SLEEP = lambda _seconds: None


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
            execute_experiment(output, factory, sleep_fn=NO_SLEEP)
        factory.assert_not_called()

    def test_execute_refuses_modified_manifest_before_adapter_construction(self):
        output = self.prepared()
        manifest_path = output / MANIFEST_FILENAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["model_id"] = "different-model"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        factory = Mock()
        with self.frozen_git(), self.assertRaises(DevExperimentError):
            execute_experiment(output, factory, sleep_fn=NO_SLEEP)
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
            summary = execute_experiment(output, lambda: adapter, sleep_fn=NO_SLEEP)
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
        self.assertTrue(summary["official_result_eligible"])
        self.assertEqual(len(summary["per_scenario"]["dev-001"]["B0"]["evaluations"]), 3)
        self.assertIn("dependency_strength_accuracy", summary["descriptive_B1_minus_B0"]["macro"])

    def test_b0_implicit_and_b1_structured_are_only_input_difference(self):
        output = self.prepared()
        adapter = ScenarioAwareAdapter()
        with self.frozen_git():
            execute_experiment(output, lambda: adapter, sleep_fn=NO_SLEEP)
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

    def test_fixed_pacing_is_sequential_identical_and_has_no_first_delay(self):
        output = self.prepared()
        adapter = ScenarioAwareAdapter()
        events = []
        original_generate = adapter.generate
        def generate(prompt, config, response_schema=None):
            events.append(("provider", len(adapter.calls) + 1))
            return original_generate(prompt, config, response_schema=response_schema)
        adapter.generate = generate
        def sleeper(seconds):
            events.append(("sleep", seconds))
        with self.frozen_git():
            execute_experiment(output, lambda: adapter, sleep_fn=sleeper)
        self.assertEqual(events[0], ("provider", 1))
        self.assertEqual(events[1], ("sleep", 10))
        self.assertEqual(events[2], ("provider", 2))
        self.assertEqual(sum(event[0] == "sleep" for event in events), 71)
        self.assertTrue(all(event[1] == 10 for event in events if event[0] == "sleep"))
        self.assertTrue(all(call["config"].generation_config == adapter.calls[0]["config"].generation_config for call in adapter.calls))

    def test_nonretryable_provider_error_closes_slot_and_continues(self):
        output = self.prepared()
        adapter = ScenarioAwareAdapter(failures={3: RuntimeError("capacity")})
        sleeper = Mock()
        with self.frozen_git():
            summary = execute_experiment(output, lambda: adapter, sleep_fn=sleeper)
        self.assertEqual(len(adapter.calls), 72)
        self.assertEqual(sleeper.call_count, 71)
        self.assertTrue(all(args.args == (10,) for args in sleeper.call_args_list))
        self.assertEqual(summary["provider_error_runs"], 1)
        self.assertEqual(summary["attempted_calls"], 72)
        self.assertEqual(summary["scientific_slots_processed"], 72)
        self.assertEqual(summary["experiment_status"], "completed")
        self.assertFalse(summary["official_result_eligible"])
        self.assertIsNone(summary["abort_reason"])

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
            execute_experiment(output, lambda: adapter, sleep_fn=NO_SLEEP)
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
        self.assertEqual(runs[0]["experiment_config_version"], "dev-baselines-v0.4")
        self.assertTrue(runs[0]["generation"]["native_structured_output"])
        self.assertEqual(runs[0]["response_schema_sha256"], SCHEMA_SHA256)
        self.assertEqual(runs[0]["transport"], {"timeout_ms": 120000, "timeout_seconds": 120, "attempts": 1})
        self.assertEqual(runs[0]["delivery"]["terminal_state"], "model_response_obtained")
        config_metadata = dict(runs[0]["experiment_config"]["generation_config"])
        self.assertEqual(config_metadata["inter_call_delay_seconds"], 10)
        self.assertIs(config_metadata["first_call_pre_delay"], False)
        self.assertIs(config_metadata["pacing_jitter"], False)
        self.assertIs(config_metadata["adaptive_throttling"], False)
        self.assertEqual(config_metadata["concurrency"], 1)

    def test_invalid_and_isolated_errors_persist_without_retry(self):
        invalid_output = self.prepared()
        invalid_adapter = ScenarioAwareAdapter(invalid=True)
        with self.frozen_git():
            invalid_summary = execute_experiment(invalid_output, lambda: invalid_adapter, sleep_fn=NO_SLEEP)
        self.assertEqual(len(invalid_adapter.calls), 72)
        self.assertEqual(invalid_summary["invalid_runs"], 72)
        self.assertEqual(invalid_summary["experiment_status"], "completed")
        self.assertTrue(invalid_summary["official_result_eligible"])

        error_output = self.prepared()
        error_adapter = ScenarioAwareAdapter(failures={1: RuntimeError("temporary")})
        with self.frozen_git():
            error_summary = execute_experiment(error_output, lambda: error_adapter, sleep_fn=NO_SLEEP)
        self.assertEqual(len(error_adapter.calls), 72)
        self.assertEqual(error_summary["provider_error_runs"], 1)
        self.assertEqual(error_summary["experiment_status"], "completed")
        self.assertEqual(error_summary["aggregate_status"], "COMPLETE MATRIX / INCOMPLETE NON-OFFICIAL PERFORMANCE")
        self.assertFalse(error_summary["official_result_eligible"])
        self.assertIsNone(error_summary["abort_reason"])

    def test_nonretryable_authentication_error_is_not_retried_and_matrix_continues(self):
        output = self.prepared()
        adapter = ScenarioAwareAdapter(failures={1: GeminiAuthenticationError("bad ADC")})
        with self.frozen_git():
            summary = execute_experiment(output, lambda: adapter, sleep_fn=NO_SLEEP)
        self.assertEqual(len(adapter.calls), 72)
        self.assertEqual(summary["experiment_status"], "completed")
        self.assertEqual(summary["aggregate_status"], "COMPLETE MATRIX / INCOMPLETE NON-OFFICIAL PERFORMANCE")
        self.assertFalse(summary["official_result_eligible"])
        self.assertEqual(summary["attempted_calls"], 72)
        self.assertIsNone(summary["abort_reason"])

    def test_keyboard_interrupt_on_first_invocation_writes_truthful_abort(self):
        output = self.prepared()
        adapter = ScenarioAwareAdapter(failures={1: KeyboardInterrupt()})
        with self.frozen_git():
            summary = execute_experiment(output, lambda: adapter, sleep_fn=NO_SLEEP)
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
            summary = execute_experiment(output, lambda: adapter, sleep_fn=NO_SLEEP)
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
            execute_experiment(output, replacement, sleep_fn=NO_SLEEP)
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
        self.assertEqual(manifest["experiment_version"], "dev-baselines-v0.4")
        self.assertEqual(manifest["transport"]["timeout_ms"], 120000)
        self.assertEqual(manifest["transport"]["timeout_seconds"], 120)
        self.assertEqual(manifest["transport"]["attempts"], 1)
        self.assertEqual(manifest["pacing"]["inter_scientific_slot_delay_seconds"], 10)
        self.assertFalse(manifest["pacing"]["first_slot_pre_delay"])
        self.assertFalse(manifest["pacing"]["jitter"])
        self.assertFalse(manifest["pacing"]["adaptive_throttling"])
        self.assertEqual(manifest["pacing"]["concurrency"], 1)
        self.assertEqual(manifest["failure_policy"]["provider_delivery_failure"], "persist_terminal_slot_and_continue_matrix")
        self.assertEqual(manifest["baseline_allowlist"], ["B0", "B1"])
        self.assertNotIn("B2", json.dumps(json.loads((output / PLAN_FILENAME).read_text())))

    def test_retryable_status_uses_exact_four_attempt_cap_and_fixed_backoff(self):
        output = self.prepared()
        failures = {
            number: genai_errors.ClientError(429, {"error": {"message": "capacity"}})
            for number in range(1, 5)
        }
        adapter = ScenarioAwareAdapter(failures=failures)
        sleeps = []
        with self.frozen_git():
            summary = execute_experiment(output, lambda: adapter, sleep_fn=sleeps.append)
        self.assertEqual(len(adapter.calls), 75)
        self.assertEqual(sleeps[:4], [5, 10, 20, 10])
        self.assertEqual(sum(value in DELIVERY_BACKOFF_SECONDS for value in sleeps[:3]), 3)
        self.assertEqual(summary["delivery"]["attempts_by_number"], {"1": 72, "2": 1, "3": 1, "4": 1})
        self.assertEqual(summary["scientific_slots_provider_delivery_failed"], 1)
        self.assertEqual(summary["scientific_slots_processed"], 72)
        self.assertEqual(summary["experiment_status"], "completed")
        self.assertFalse(summary["official_result_eligible"])
        runs = [json.loads(line) for line in (output / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(runs), 72)
        self.assertEqual(runs[0]["delivery"]["attempts_used"], MAX_DELIVERY_ATTEMPTS)
        self.assertEqual(runs[0]["delivery"]["terminal_state"], "provider_delivery_failed")
        self.assertEqual(runs[0]["delivery"]["terminal_http_status_code"], 429)
        self.assertEqual(runs[0]["delivery"]["terminal_failure_classification"], "http_status")

    def test_retryable_failure_then_response_closes_slot_and_invalid_is_not_retried(self):
        output = self.prepared()
        adapter = ScenarioAwareAdapter(failures={
            1: genai_errors.ServerError(503, {"error": {"message": "unavailable"}}),
        })
        sleeps = []
        with self.frozen_git():
            summary = execute_experiment(output, lambda: adapter, sleep_fn=sleeps.append)
        self.assertEqual(len(adapter.calls), 73)
        self.assertEqual(sleeps[:2], [5, 10])
        self.assertEqual(summary["delivery"]["model_responses_after_retry"], 1)
        self.assertTrue(summary["official_result_eligible"])

        invalid_output = self.prepared()
        invalid_adapter = ScenarioAwareAdapter(invalid=True)
        with self.frozen_git():
            invalid_summary = execute_experiment(invalid_output, lambda: invalid_adapter, sleep_fn=NO_SLEEP)
        self.assertEqual(len(invalid_adapter.calls), 72)
        self.assertEqual(invalid_summary["invalid_runs"], 72)
        self.assertEqual(invalid_summary["invalid_model_response_rate"], 1.0)
        self.assertTrue(invalid_summary["official_result_eligible"])
        self.assertEqual(invalid_summary["performance_aggregate_scope"], "conditional_on_valid_model_responses")

    def test_retry_classification_is_narrow(self):
        from dr_baselines.dev_experiment import _retryable_delivery_failure

        for status in (408, 429, 500, 502, 503, 504):
            self.assertEqual(_retryable_delivery_failure(
                genai_errors.ClientError(status, {"error": {"message": "retry"}})
            ), (True, "http_status", status))
        for status in (400, 401, 403, 404):
            self.assertEqual(_retryable_delivery_failure(
                genai_errors.ClientError(status, {"error": {"message": "bad"}})
            ), (False, "http_status", status))
        self.assertEqual(_retryable_delivery_failure(TimeoutError("timeout"))[:2], (True, "timeout"))
        import httpx
        self.assertEqual(_retryable_delivery_failure(httpx.ReadTimeout("timeout"))[:2], (True, "timeout"))
        self.assertEqual(_retryable_delivery_failure(RuntimeError("other"))[:2], (False, "non_retryable_exception"))

    def test_direct_httpx_dependency_is_pinned_and_requests_is_not_imported(self):
        project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertIn("httpx==0.28.1", project["dependencies"])
        source = Path("dr_baselines/dev_experiment.py").read_text(encoding="utf-8")
        self.assertNotIn("import requests", source)
        self.assertNotIn("requests.Timeout", source)

    def test_first_response_wins_on_attempts_two_three_and_four(self):
        for successful_attempt in (2, 3, 4):
            with self.subTest(successful_attempt=successful_attempt):
                output = self.prepared()
                adapter = ScenarioAwareAdapter(failures={
                    number: genai_errors.ClientError(429, {"error": {"message": "capacity"}})
                    for number in range(1, successful_attempt)
                })
                with self.frozen_git():
                    summary = execute_experiment(output, lambda: adapter, sleep_fn=NO_SLEEP)
                self.assertEqual(len(adapter.calls), 71 + successful_attempt)
                self.assertEqual(summary["delivery_attempts_by_attempt_number"][str(successful_attempt)], 1)
                self.assertEqual(summary["scientific_slots_with_model_response"], 72)
                self.assertTrue(summary["official_result_eligible"])

    def test_delivery_log_is_auditable_and_contains_no_response_or_prompt(self):
        output = self.prepared()
        adapter = ScenarioAwareAdapter(failures={
            1: genai_errors.ClientError(429, {"error": {"message": "capacity"}}),
        })
        with self.frozen_git():
            execute_experiment(output, lambda: adapter, sleep_fn=NO_SLEEP)
        values = [json.loads(line) for line in (output / ATTEMPT_LIFECYCLE_FILENAME).read_text(encoding="utf-8").splitlines()]
        attempts = [value for value in values if value["event"] == "delivery_attempt_completed"]
        self.assertEqual(len(attempts), 73)
        self.assertEqual(attempts[0]["delivery_attempt_number"], 1)
        self.assertTrue(attempts[0]["retryable"])
        self.assertEqual(attempts[0]["next_backoff_seconds"], 5)
        self.assertEqual(attempts[1]["outcome"], "model_response_obtained")
        serialized = json.dumps(values)
        self.assertNotIn("raw_model_response", serialized)
        self.assertNotIn("CANDIDATE-VISIBLE SCENARIO", serialized)

    def test_keyboard_interrupt_during_backoff_and_inter_slot_pacing_aborts(self):
        backoff_output = self.prepared()
        adapter = ScenarioAwareAdapter(failures={
            1: genai_errors.ClientError(429, {"error": {"message": "capacity"}}),
        })
        with self.frozen_git():
            backoff = execute_experiment(
                backoff_output, lambda: adapter,
                sleep_fn=lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()) if seconds == 5 else None,
            )
        self.assertEqual(backoff["interrupted_position"]["lifecycle_stage"], "delivery_backoff")
        self.assertEqual(backoff["persisted_run_records"], 0)

        pacing_output = self.prepared()
        pacing_adapter = ScenarioAwareAdapter()
        with self.frozen_git():
            pacing = execute_experiment(
                pacing_output, lambda: pacing_adapter,
                sleep_fn=lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
            )
        self.assertEqual(pacing["interrupted_position"]["lifecycle_stage"], "inter_slot_pacing")
        self.assertEqual(pacing["persisted_run_records"], 1)
        self.assertEqual(len(pacing_adapter.calls), 1)

    def test_frozen_prompt_hash(self):
        self.assertEqual(PROMPT_SHA256, "2ed1e0280d3108aa9f7458bc7a21d4cf9f82ad2e6c4795d2ac516fffdb5557b1")
        self.assertEqual(PROMPT_SHA256, hashlib.sha256(BASE_TASK_PROMPT.encode("utf-8")).hexdigest())
        self.assertEqual(DISCOVERY_RESPONSE_SCHEMA_VERSION, "discovery-response-v0.1")
        self.assertEqual(SCHEMA_SHA256, "c1da8e87a79950b25c57bfdd411a44c6482ec15cbadeca69b6019e7fbda52ce5")


if __name__ == "__main__":
    unittest.main()
