import copy
import hashlib
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import Mock, patch

from dr_bench import candidate_view, load_scenario
from dr_baselines.baselines import BASE_TASK_PROMPT
from dr_baselines.models import ModelResponse
from dr_baselines.round_b import (
    ALTERNATIVE_SUPPORT_STAGE2_INSTRUCTION, DECISION_SUPPORT_JSON_SCHEMA,
    DECISION_SUPPORT_SCHEMA_VERSION, DEV_SCENARIOS, FINAL_CONDITIONS,
    GENERIC_CONTEXT_JSON_SCHEMA, GENERIC_CONTEXT_SCHEMA_VERSION,
    INTERMEDIATE_STAGES, PROJECTION_FIELDS, PROMPT_HASHES, PROTOCOL_SHA256,
    RC0_STAGE1_GENERIC_ORGANIZATION_INSTRUCTION, RECONSTRUCTION_STAGE1_INSTRUCTION,
    RoundBError, SURVIVABILITY_STAGE2_INSTRUCTION, analyze, build_execution_plan,
    build_stage1_projection, build_stage1_prompt, build_stage2_prompt,
    classify_contrast, execute, final_position_counts, prepare, projection_bytes,
    protocol_sha256, schema_sha256, stage2_instruction, validate_decision_support,
    validate_frozen_constants, validate_generic_context, validate_plan,
)


GIT_SHA = "a" * 40


def public_scenario(scenario_id="dev-001"):
    scenario = load_scenario(scenario_id)
    return {key: value for key, value in scenario.items() if key != "private"}


def projection(scenario_id="dev-001"):
    return build_stage1_projection(candidate_view(public_scenario(scenario_id), "discovery", "implicit"))


def generic_value(source):
    return {
        "schema_version": GENERIC_CONTEXT_SCHEMA_VERSION,
        "scenario_id": source["scenario_id"],
        "agents": copy.deepcopy(source["agents"]),
        "knowledge_before": copy.deepcopy(source["knowledge_before"]),
        "change": copy.deepcopy(source["change"]),
        "transmissions": copy.deepcopy(source["transmissions"]),
        "decisions": copy.deepcopy(source["decisions"]),
        "world": copy.deepcopy(source["world"]),
        "consequences": copy.deepcopy(source["consequences"]),
        "recovery_actions": copy.deepcopy(source["recovery_actions"]),
    }


def support_value(source):
    return {
        "schema_version": DECISION_SUPPORT_SCHEMA_VERSION,
        "scenario_id": source["scenario_id"],
        "change_alignment": {"change_ref": source["change"]["id"], "candidate_prior_knowledge_refs": []},
        "decision_connections": [{"decision_id": item["id"], "candidate_knowledge_refs": [], "basis_trace_refs": []} for item in source["decisions"]],
    }


class FakeAdapter:
    identifier = "round-b-fake"

    def __init__(self, invalid_reconstruction=False, fail_on=None, invalid_final_on=None):
        self.calls = []
        self.invalid_reconstruction = invalid_reconstruction
        self.fail_on = set(fail_on or ())
        self.invalid_final_on = set(invalid_final_on or ())
        self.closed = False

    def generate(self, prompt, config, response_schema=None):
        self.calls.append((prompt, config, response_schema))
        if len(self.calls) in self.fail_on:
            raise RuntimeError("isolated provider failure")
        if response_schema is GENERIC_CONTEXT_JSON_SCHEMA:
            source = json.loads(prompt.split("STAGE1VISIBLEPROJECTION:\n", 1)[1])
            text = json.dumps(generic_value(source))
        elif response_schema is DECISION_SUPPORT_JSON_SCHEMA:
            if self.invalid_reconstruction:
                text = "invalid"
            else:
                source = json.loads(prompt.split("STAGE1VISIBLEPROJECTION:\n", 1)[1])
                text = json.dumps(support_value(source))
        else:
            visible_text = prompt.split("CANDIDATE-VISIBLE SCENARIO:\n", 1)[1].split("\n\nCANONICAL STAGE-1 ARTIFACT:\n", 1)[0]
            visible = json.loads(visible_text)
            text = json.dumps({"decisions": [{"decision_id": item["id"], "materially_dependent": False, "dependency_strength": "independent", "still_justified": True} for item in visible["decisions"]]})
            if len(self.calls) in self.invalid_final_on:
                text = "invalid final model output"
        return ModelResponse(text=text, latency_ms=1, input_tokens=2, output_tokens=1)

    def close(self):
        self.closed = True


class RoundBTests(unittest.TestCase):
    def temp_output(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        return Path(temporary.name) / "round-b"

    def frozen_git(self):
        return patch.multiple("dr_baselines.round_b", _git_sha=Mock(return_value=GIT_SHA), _git_branch=Mock(return_value="agent/baselines-v0.1"), _tracked_clean=Mock(return_value=True))

    def prepared(self):
        output = self.temp_output()
        with self.frozen_git(): prepare(output)
        return output

    def test_protocol_and_prompt_hashes_are_frozen(self):
        self.assertEqual(protocol_sha256(), PROTOCOL_SHA256)
        blocks = {"rc0_stage1": RC0_STAGE1_GENERIC_ORGANIZATION_INSTRUCTION, "reconstruction_stage1": RECONSTRUCTION_STAGE1_INSTRUCTION, "survivability_stage2": SURVIVABILITY_STAGE2_INSTRUCTION, "alternative_support_stage2": ALTERNATIVE_SUPPORT_STAGE2_INSTRUCTION}
        self.assertEqual({key: hashlib.sha256(value.encode()).hexdigest() for key, value in blocks.items()}, PROMPT_HASHES)
        validate_frozen_constants()

    def test_projection_is_exact_private_free_and_shared(self):
        visible = candidate_view(public_scenario(), "discovery", "implicit")
        value = build_stage1_projection(visible)
        self.assertEqual(tuple(value), PROJECTION_FIELDS)
        serialized = projection_bytes(value)
        self.assertEqual(build_stage1_prompt(INTERMEDIATE_STAGES[0], value).split("STAGE1VISIBLEPROJECTION:\n", 1)[1], serialized.decode().rstrip("\n"))
        self.assertEqual(build_stage1_prompt(INTERMEDIATE_STAGES[1], value).split("STAGE1VISIBLEPROJECTION:\n", 1)[1], serialized.decode().rstrip("\n"))
        for excluded in ("schema_version", "split", "phase", "discovery_condition", "complexity", "title", "domain", "private"):
            self.assertNotIn(excluded, value)

    def test_generic_record_is_complete_exact_and_canonical(self):
        source = projection(); value = generic_value(source)
        value["agents"].reverse(); value["knowledge_before"].reverse()
        canonical, encoded, digest = validate_generic_context(json.dumps(value), source)
        self.assertEqual([x["id"] for x in canonical["agents"]], sorted(x["id"] for x in source["agents"]))
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), digest)
        changed = generic_value(source); changed["decisions"][0]["statement"] += " necessary support material critical"
        with self.assertRaisesRegex(ValueError, "changed or omitted"): validate_generic_context(json.dumps(changed), source)
        sensitive = copy.deepcopy(source); sensitive["decisions"][0]["statement"] = "Necessary material support remains critical."
        self.assertTrue(validate_generic_context(json.dumps(generic_value(sensitive)), sensitive)[0])
        omitted = generic_value(source); omitted["agents"].pop()
        with self.assertRaises(ValueError): validate_generic_context(json.dumps(omitted), source)

    def test_support_record_empty_sets_valid_and_refs_strict(self):
        source = projection(); value = support_value(source); value["decision_connections"].reverse()
        canonical, encoded, digest = validate_decision_support(json.dumps(value), source)
        self.assertEqual([x["decision_id"] for x in canonical["decision_connections"]], sorted(x["id"] for x in source["decisions"]))
        self.assertTrue(all(not x["candidate_knowledge_refs"] and not x["basis_trace_refs"] for x in canonical["decision_connections"]))
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), digest)
        bad = support_value(source); bad["decision_connections"][0]["candidate_knowledge_refs"] = [source["decisions"][0]["id"]]
        with self.assertRaisesRegex(ValueError, "wrong-namespace"): validate_decision_support(json.dumps(bad), source)
        missing = support_value(source); missing["decision_connections"].pop()
        with self.assertRaisesRegex(ValueError, "exactly once"): validate_decision_support(json.dumps(missing), source)
        duplicate = support_value(source); duplicate["decision_connections"][0]["basis_trace_refs"] = ["t1", "t1"]
        with self.assertRaisesRegex(ValueError, "duplicates"): validate_decision_support(json.dumps(duplicate), source)

    def test_stage2_prompt_invariants_and_raw_never_enters(self):
        visible = candidate_view(public_scenario(), "discovery", "implicit")
        artifact = validate_decision_support(json.dumps(support_value(projection())), projection())[1]
        rb1 = build_stage2_prompt("RB1", visible, artifact); rb2 = build_stage2_prompt("RB2", visible, artifact); rb3 = build_stage2_prompt("RB3", visible, artifact)
        suffix = "\n\nCANDIDATE-VISIBLE SCENARIO:\n"
        self.assertEqual(rb1.split(suffix)[0], BASE_TASK_PROMPT)
        self.assertEqual(rb2.split(suffix)[0], BASE_TASK_PROMPT + "\n\n" + SURVIVABILITY_STAGE2_INSTRUCTION)
        self.assertEqual(rb3.split(suffix)[0], BASE_TASK_PROMPT + "\n\n" + SURVIVABILITY_STAGE2_INSTRUCTION + "\n\n" + ALTERNATIVE_SUPPORT_STAGE2_INSTRUCTION)
        self.assertIn(artifact.decode().rstrip("\n"), rb1)
        self.assertNotIn("raw_stage1_response", rb1)

    def test_plan_is_exact_dependency_explicit_balanced_96_72(self):
        left = build_execution_plan(); right = build_execution_plan(); self.assertEqual(left, right)
        validate_plan(left); self.assertEqual(len(left), 96)
        self.assertEqual(sum(x["observation_kind"] == "final" for x in left), 72)
        self.assertEqual(len(DEV_SCENARIOS), 12)
        self.assertEqual(Counter(x["stage_id"] for x in left), Counter({stage: 12 for stage in set(x["stage_id"] for x in left)}))
        self.assertTrue(all(x["dependency_producing_stage"] for x in left if x["condition_id"] in {"RC0", "RB1", "RB2", "RB3"} and x["observation_kind"] == "final"))
        positions = final_position_counts(left)
        self.assertTrue(all(sum(counts.values()) == 12 and sorted(v for v in counts.values() if v) == [2] * 6 for counts in positions.values()))
        changed = copy.deepcopy(left); changed[0]["scenario_id"] = "holdout-001"
        with self.assertRaises(RoundBError): validate_plan(changed)

    def test_prepare_zero_calls_and_manifest_freezes_contract(self):
        output = self.temp_output()
        with self.frozen_git(): manifest = prepare(output)
        self.assertEqual(manifest["conceptual_model_calls"], 96); self.assertEqual(manifest["possible_final_outputs"], 72)
        self.assertEqual(manifest["round_b_protocol_sha256"], PROTOCOL_SHA256)
        self.assertEqual(manifest["generic_context_schema_sha256"], schema_sha256(GENERIC_CONTEXT_JSON_SCHEMA))
        self.assertEqual(manifest["decision_support_schema_sha256"], schema_sha256(DECISION_SUPPORT_JSON_SCHEMA))
        self.assertFalse(manifest["confirmation_authorized"])

    def test_execute_shares_reconstruction_persists_before_evaluation(self):
        output = self.prepared(); adapter = FakeAdapter()
        with self.frozen_git(), patch("dr_baselines.round_b.evaluate_discovery", wraps=__import__("dr_bench").evaluate_discovery) as evaluator:
            summary = execute(output, adapter_factory=lambda: adapter, sleep_fn=lambda _: None)
        self.assertEqual(len(adapter.calls), 96); self.assertEqual(summary["final_runs_persisted"], 72); self.assertEqual(summary["evaluations_persisted"], 72)
        self.assertEqual(summary["final_valid_outputs"], 72); self.assertEqual(summary["final_invalid_outputs"], 0)
        self.assertTrue(summary["scientific_outputs_complete"]); self.assertTrue(summary["screening_complete"])
        artifacts = [json.loads(x) for x in (output / "stage1_artifacts.jsonl").read_text().splitlines()]
        self.assertEqual(Counter(x["stage_id"] for x in artifacts), Counter({"RC0_GENERIC_STAGE1": 12, "SHARED_RECONSTRUCTION_STAGE1": 12}))
        runs = [json.loads(x) for x in (output / "runs.jsonl").read_text().splitlines()]
        for scenario_id in DEV_SCENARIOS:
            hashes = {x["artifact_sha256"] for x in runs if x["scenario_id"] == scenario_id and x["condition_id"] in {"RB1", "RB2", "RB3"}}
            self.assertEqual(len(hashes), 1)
        self.assertEqual(evaluator.call_count, 72)

    def test_one_invalid_shared_reconstruction_blocks_three_without_retry(self):
        output = self.prepared(); adapter = FakeAdapter(invalid_reconstruction=True)
        with self.frozen_git(): summary = execute(output, adapter_factory=lambda: adapter, sleep_fn=lambda _: None)
        self.assertEqual(summary["intermediate_failures"], 12); self.assertEqual(summary["downstream_blocked"], 36)
        self.assertTrue(summary["infrastructure_complete"])
        self.assertEqual(summary["classification_status"], "FAIL / DO NOT ADVANCE")
        self.assertEqual(len(adapter.calls), 60)
        states = [json.loads(x) for x in (output / "terminal_states.jsonl").read_text().splitlines()]
        self.assertEqual(sum(x["terminal_state"] == "intermediate_invalid" for x in states), 12)
        self.assertEqual(sum(x["terminal_state"] == "downstream_blocked" for x in states), 36)
        self.assertTrue(all(not x["model_call_executed"] for x in states if x["terminal_state"] == "downstream_blocked"))

    def test_provider_failure_is_distinct_persisted_and_not_retried(self):
        output = self.prepared(); adapter = FakeAdapter(fail_on={3})
        with self.frozen_git(): summary = execute(output, adapter_factory=lambda: adapter, sleep_fn=lambda _: None)
        self.assertEqual(summary["provider_failures"], 1); self.assertEqual(summary["intermediate_failures"], 0)
        self.assertFalse(summary["infrastructure_complete"])
        self.assertEqual(summary["classification_status"], "INCOMPLETE / INFRASTRUCTURE")
        self.assertEqual(len(adapter.calls), 96)
        runs = [json.loads(x) for x in (output / "runs.jsonl").read_text().splitlines()]
        failed = [x for x in runs if x["validation_status"] == "provider_error"]
        self.assertEqual(len(failed), 1); self.assertIn("isolated provider failure", failed[0]["provider_error"])

    def test_one_invalid_final_is_preserved_not_retried_and_not_classifiable(self):
        output = self.prepared(); adapter = FakeAdapter(invalid_final_on={3})
        with self.frozen_git(): summary = execute(output, adapter_factory=lambda: adapter, sleep_fn=lambda _: None)
        self.assertEqual(len(adapter.calls), 96)
        self.assertEqual(summary["final_runs_persisted"], 72)
        self.assertEqual(summary["final_valid_outputs"], 71)
        self.assertEqual(summary["final_invalid_outputs"], 1)
        self.assertEqual(summary["evaluations_persisted"], 71)
        self.assertEqual(summary["provider_failures"], 0)
        self.assertTrue(summary["infrastructure_complete"])
        self.assertFalse(summary["scientific_outputs_complete"])
        self.assertFalse(summary["screening_complete"])
        self.assertEqual(summary["classification_status"], "INCOMPLETE / MODEL OUTPUT")
        runs = [json.loads(x) for x in (output / "runs.jsonl").read_text().splitlines()]
        self.assertEqual(sum(x["validation_status"] == "invalid" for x in runs), 1)
        analysis = analyze(output, output.parent / "invalid-analysis")
        self.assertEqual(analysis["classification_status"], "INCOMPLETE / MODEL OUTPUT")
        self.assertTrue(all(value["status"] == "INCOMPLETE / MODEL OUTPUT" for value in analysis["precommitted_comparisons"].values()))
        self.assertNotIn("INCOMPLETE / INFRASTRUCTURE", json.dumps(analysis["precommitted_comparisons"]))

    def test_analysis_is_offline_decision_level_and_claim_bounded(self):
        output = self.prepared(); adapter = FakeAdapter()
        with self.frozen_git(): execute(output, adapter_factory=lambda: adapter, sleep_fn=lambda _: None)
        analysis_dir = output.parent / "analysis"
        result = analyze(output, analysis_dir)
        self.assertEqual(set(result["per_condition"]), set(FINAL_CONDITIONS))
        self.assertEqual(set(result["precommitted_comparisons"]), {"RB0_vs_RC0", "RB0_vs_RR1", "RC0_vs_RB1", "RB1_vs_RB2", "RB2_vs_RB3"})
        self.assertTrue(result["stage1_excluded_from_discovery_denominators"])
        self.assertIn("cannot prove", result["rc0_claim_boundary"])
        self.assertFalse(result["confirmation_authorized"])
        self.assertEqual(result["cost_accounting"]["standalone_pipeline"]["RB3"]["model_calls"], 24)
        rows = (analysis_dir / "decision_prediction_ledger.csv").read_text().splitlines()
        self.assertEqual(len(rows), 1 + 36 * 6)

    def test_classification_is_frozen_and_no_confirmation_status(self):
        row = {"scenario_id": "dev-001", "decision_id": "d1", "true_materially_dependent": False, "predicted_materially_dependent": True, "true_still_justified": True, "predicted_still_justified": True}
        candidate = dict(row, predicted_materially_dependent=False)
        self.assertEqual(classify_contrast([row], [candidate], True)["status"], "PROMISING")
        self.assertNotIn("PROVEN", json.dumps(classify_contrast([row], [candidate], True)))
        self.assertEqual(classify_contrast([], [], False)["status"], "INCOMPLETE / INFRASTRUCTURE")
        self.assertEqual(classify_contrast([], [], False, "INCOMPLETE / MODEL OUTPUT")["status"], "INCOMPLETE / MODEL OUTPUT")

    def test_cli_import_and_no_mode_do_not_construct_provider(self):
        from dr_baselines.round_b import main
        with patch("dr_baselines.round_b._dev_adapter_factory") as factory:
            self.assertEqual(main(["--output-dir", str(self.temp_output())]), 2)
            factory.assert_not_called()

    def test_only_dev_allowlist_and_no_sealed_dependency(self):
        source = Path(__import__("dr_baselines.round_b", fromlist=["x"]).__file__).read_text()
        self.assertNotIn("import sealed", source)
        self.assertNotIn("load_sealed", source)
        self.assertNotIn("load_scenarios", source)
        self.assertEqual(DEV_SCENARIOS, tuple(f"dev-{x:03d}" for x in range(1, 13)))


if __name__ == "__main__":
    unittest.main()
