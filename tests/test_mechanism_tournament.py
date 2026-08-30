import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from google.genai import errors as genai_errors

from dr_baselines.baselines import BASE_TASK_PROMPT
from dr_baselines.mechanism_tournament import (
    ALTERNATIVE_SUPPORT_INSTRUCTION, CONDITIONS, CONDITION_ORDER, DEV_SCENARIOS,
    M1_INSTRUCTION, M2_INSTRUCTION, PROTOCOL_PATH, TournamentError,
    analyze, build_execution_plan, classify_probe, condition_position_counts, execute,
    prepare, protocol_sha256, run_condition, validate_plan,
)
from dr_baselines.models import ModelResponse
from dr_baselines.output import DISCOVERY_RESPONSE_JSON_SCHEMA


GIT_SHA = "a" * 40


class FakeAdapter:
    identifier = "tournament-fake"

    def __init__(self, invalid=False, failures=None):
        self.calls = []
        self.invalid = invalid
        self.failures = dict(failures or {})
        self.closed = False

    def generate(self, prompt, config, response_schema=None):
        self.calls.append((prompt, config, response_schema))
        if len(self.calls) in self.failures:
            raise self.failures[len(self.calls)]
        if self.invalid:
            return ModelResponse(text="invalid", latency_ms=1)
        visible = json.loads(prompt.split("\n\nCANDIDATE-VISIBLE SCENARIO:\n", 1)[1])
        return ModelResponse(text=json.dumps({"decisions": [{
            "decision_id": item["id"], "materially_dependent": False,
            "dependency_strength": "independent", "still_justified": True,
        } for item in visible["decisions"]]}), latency_ms=1, input_tokens=2, output_tokens=1)

    def close(self):
        self.closed = True


def row(scenario, decision, truth_dep=False, truth_still=True, pred_dep=False, pred_still=True):
    return {
        "scenario_id": scenario, "decision_id": decision,
        "true_materially_dependent": truth_dep, "predicted_materially_dependent": pred_dep,
        "true_still_justified": truth_still, "predicted_still_justified": pred_still,
    }


class MechanismTournamentTests(unittest.TestCase):
    def temp_output(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name) / "a1"

    def frozen_git(self):
        return patch.multiple("dr_baselines.mechanism_tournament", _git_sha=Mock(return_value=GIT_SHA), _git_branch=Mock(return_value="agent/baselines-v0.1"), _tracked_clean=Mock(return_value=True))

    def prepared(self):
        output = self.temp_output()
        with self.frozen_git():
            prepare(output)
        return output

    def test_registry_and_candidate_routing_are_exact(self):
        self.assertEqual(tuple(CONDITIONS), CONDITION_ORDER)
        self.assertEqual({key: value.candidate_view_mode for key, value in CONDITIONS.items()}, {
            "M0": "implicit", "R1": "structured", "M1": "implicit", "M2": "implicit", "M3": "implicit",
        })
        self.assertEqual(CONDITIONS["M0"].instructions, ())
        self.assertEqual(CONDITIONS["R1"].instructions, ())
        self.assertEqual(CONDITIONS["M3"].instructions, (M2_INSTRUCTION, ALTERNATIVE_SUPPORT_INSTRUCTION))

    def test_probe_blocks_match_authoritative_markdown_verbatim(self):
        protocol = PROTOCOL_PATH.read_text(encoding="utf-8")
        for block in (M1_INSTRUCTION, M2_INSTRUCTION, ALTERNATIVE_SUPPORT_INSTRUCTION):
            self.assertIn("```text\n" + block + "\n```", protocol)
        self.assertEqual(protocol_sha256(), hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest())

    def test_prompt_composition_and_difference_invariants(self):
        payload = {"phase": "discovery", "discovery_condition": "implicit", "id": "x", "decisions": []}
        m0 = CONDITIONS["M0"].build_prompt(payload)
        m1 = CONDITIONS["M1"].build_prompt(payload)
        m2 = CONDITIONS["M2"].build_prompt(payload)
        m3 = CONDITIONS["M3"].build_prompt(payload)
        delimiter = "\n\nCANDIDATE-VISIBLE SCENARIO:\n"
        self.assertEqual(m0.split(delimiter)[0], BASE_TASK_PROMPT)
        self.assertEqual(m1.split(delimiter)[0], BASE_TASK_PROMPT + "\n\n" + M1_INSTRUCTION)
        self.assertEqual(m2.split(delimiter)[0], BASE_TASK_PROMPT + "\n\n" + M2_INSTRUCTION)
        self.assertEqual(m3.split(delimiter)[0], BASE_TASK_PROMPT + "\n\n" + M2_INSTRUCTION + "\n\n" + ALTERNATIVE_SUPPORT_INSTRUCTION)
        self.assertNotIn("CANDIDATE-VISIBLE", m3.split(delimiter)[0])
        structured = dict(payload, discovery_condition="structured")
        self.assertEqual(CONDITIONS["R1"].build_prompt(structured).split(delimiter)[0], BASE_TASK_PROMPT)

    def test_hashes_are_deterministic_and_distinct_as_intended(self):
        first = {key: value.effective_template_sha256 for key, value in CONDITIONS.items()}
        second = {key: value.effective_template_sha256 for key, value in CONDITIONS.items()}
        self.assertEqual(first, second)
        self.assertEqual(first["M0"], first["R1"])
        self.assertEqual(len(set(first.values())), 4)

    def test_plan_is_exact_cyclic_60_slot_matrix(self):
        left = build_execution_plan()
        right = build_execution_plan()
        self.assertEqual(left, right)
        self.assertEqual(len(left), 60)
        self.assertTrue(all(item["repetition"] == 1 for item in left))
        self.assertEqual({(item["scenario_id"], item["condition_id"]) for item in left}, {(s, c) for s in DEV_SCENARIOS for c in CONDITION_ORDER})
        self.assertEqual([item["condition_id"] for item in left[:5]], ["M0", "R1", "M1", "M2", "M3"])
        self.assertEqual([item["condition_id"] for item in left[5:10]], ["R1", "M1", "M2", "M3", "M0"])
        self.assertEqual(hashlib.sha256(json.dumps(left, indent=2, sort_keys=True).encode() + b"\n").hexdigest(), hashlib.sha256(json.dumps(right, indent=2, sort_keys=True).encode() + b"\n").hexdigest())
        counts = condition_position_counts(left)
        self.assertTrue(all(sum(value.values()) == 12 for value in counts.values()))

    def test_non_dev_plan_entry_is_rejected_without_holdout_access(self):
        plan = build_execution_plan()
        plan[0]["scenario_id"] = "unknown"
        with self.assertRaises(TournamentError):
            validate_plan(plan)

    def test_prepare_is_zero_call_and_manifest_is_complete(self):
        output = self.temp_output()
        adapter_factory = Mock()
        with self.frozen_git():
            manifest = prepare(output)
        adapter_factory.assert_not_called()
        self.assertEqual(manifest["scientific_slots_planned"], 60)
        self.assertEqual(manifest["git_commit_sha"], GIT_SHA)
        self.assertEqual(manifest["mechanism_tournament_protocol_sha256"], protocol_sha256())
        self.assertEqual(manifest["transport"]["max_delivery_attempts"], 4)
        self.assertEqual(manifest["transport"]["backoff_seconds"], [5, 10, 20])
        plan_bytes = (output / "execution_plan.json").read_bytes()
        self.assertEqual(manifest["execution_plan_sha256"], hashlib.sha256(plan_bytes).hexdigest())

    def test_execute_refuses_changed_plan_manifest_or_git_before_adapter(self):
        output = self.prepared()
        with (output / "execution_plan.json").open("ab") as stream:
            stream.write(b" ")
        factory = Mock()
        with self.frozen_git(), self.assertRaises(TournamentError):
            execute(output, factory, sleep_fn=lambda _: None)
        factory.assert_not_called()

    def test_calls_are_independent_and_candidate_views_are_safe(self):
        from dr_bench import load_scenario
        adapter = FakeAdapter()
        for condition_id in CONDITION_ORDER:
            run_condition(condition_id, load_scenario("dev-001"), adapter)
        self.assertEqual(len(adapter.calls), 5)
        for prompt, _, schema in adapter.calls:
            self.assertIs(schema, DISCOVERY_RESPONSE_JSON_SCHEMA)
            self.assertNotIn("raw_model_response", prompt)
            self.assertNotIn("decision_labels", prompt)
        self.assertNotIn("evidence_available", adapter.calls[0][0])
        self.assertIn("evidence_available", adapter.calls[1][0])

    def test_execute_valid_and_invalid_completeness(self):
        output = self.prepared()
        adapter = FakeAdapter()
        with self.frozen_git():
            summary = execute(output, lambda: adapter, sleep_fn=lambda _: None)
        self.assertEqual(len(adapter.calls), 60)
        self.assertTrue(summary["classification_eligible"])
        self.assertIsNone(summary["classification_status"])
        self.assertTrue(adapter.closed)

        invalid_output = self.prepared()
        invalid = FakeAdapter(invalid=True)
        with self.frozen_git():
            invalid_summary = execute(invalid_output, lambda: invalid, sleep_fn=lambda _: None)
        self.assertEqual(len(invalid.calls), 60)
        self.assertEqual(invalid_summary["invalid_responses"], 60)
        self.assertEqual(invalid_summary["classification_status"], "A1_CLASSIFICATION_INCOMPLETE")

    def test_provider_delivery_exhaustion_continues_and_is_incomplete(self):
        output = self.prepared()
        adapter = FakeAdapter(failures={number: genai_errors.ClientError(429, {"error": {"message": "capacity"}}) for number in range(1, 5)})
        sleeps = []
        with self.frozen_git():
            summary = execute(output, lambda: adapter, sleep_fn=sleeps.append)
        self.assertEqual(len(adapter.calls), 63)
        self.assertEqual(sleeps[:4], [5, 10, 20, 10])
        self.assertEqual(summary["scientific_slots_processed"], 60)
        self.assertEqual(summary["provider_delivery_failures"], 1)
        self.assertEqual(summary["classification_status"], "A1_CLASSIFICATION_INCOMPLETE")

    def test_keyboard_interrupt_aborts_without_resume_or_classification(self):
        output = self.prepared()
        adapter = FakeAdapter(failures={1: KeyboardInterrupt()})
        with self.frozen_git():
            summary = execute(output, lambda: adapter, sleep_fn=lambda _: None)
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(summary["experiment_status"], "aborted")
        self.assertFalse(summary["classification_eligible"])
        self.assertEqual(summary["classification_status"], "A1_CLASSIFICATION_INCOMPLETE")
        self.assertEqual(summary["abort_reason"], "operator_interrupt")
        with self.frozen_git(), self.assertRaises(TournamentError):
            execute(output, Mock(), sleep_fn=lambda _: None)

    def test_offline_analysis_produces_classifications_without_provider(self):
        output = self.prepared()
        adapter = FakeAdapter()
        with self.frozen_git():
            execute(output, lambda: adapter, sleep_fn=lambda _: None)
        analysis_dir = self.temp_output()
        factory = Mock()
        result = analyze(output, analysis_dir)
        factory.assert_not_called()
        self.assertTrue(result["classification_eligible"])
        self.assertEqual(set(result["probe_classifications"]), {"M1", "M2", "M3"})
        self.assertTrue((analysis_dir / "decision_prediction_ledger.csv").is_file())
        self.assertTrue((analysis_dir / "m0_condition_disagreements.json").is_file())

    def test_classifier_frozen_statuses_and_unique_regression_counting(self):
        m0 = [row("s1", "d1", pred_dep=True), row("s2", "d2")]
        promising = [row("s1", "d1"), row("s2", "d2")]
        self.assertEqual(classify_probe(m0, promising)["status"], "PROMISING")

        ambiguous = [row("s1", "d1"), row("s2", "d2", pred_dep=True, pred_still=False)]
        result = classify_probe(m0, ambiguous)
        self.assertEqual(result["status"], "AMBIGUOUS / NEEDS CONFIRMATION")
        self.assertEqual(len(result["regressed_units"]), 1)
        self.assertEqual(set(result["regressed_units"][0]["fields"]), {"materially_dependent", "still_justified"})

        perfect_m0 = [row("s1", "d1")]
        self.assertEqual(classify_probe(perfect_m0, perfect_m0)["status"], "AMBIGUOUS / INSUFFICIENT CONTEMPORARY SIGNAL")
        self.assertEqual(classify_probe(m0, m0)["status"], "FAIL / DO NOT ADVANCE")
        self.assertEqual(classify_probe(m0, promising, complete=False)["status"], "A1_CLASSIFICATION_INCOMPLETE")

        material_m0 = [row("s1", "d1", truth_dep=True, pred_dep=True)]
        material_probe = [row("s1", "d1", truth_dep=True, pred_dep=False)]
        safety = classify_probe(material_m0, material_probe)
        self.assertEqual(safety["status"], "FAIL / SAFETY REGRESSION")
        self.assertEqual(len(safety["material_false_negatives"]), 1)


if __name__ == "__main__":
    unittest.main()
