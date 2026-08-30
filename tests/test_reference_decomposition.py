import copy
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import dr_bench.catalog as catalog
import dr_baselines.reference_decomposition as rd
from dr_bench import candidate_view
from dr_baselines.models import ModelResponse


class HoldoutGuard:
    def __init__(self, resource, attempts): self.resource, self.attempts = resource, attempts
    def joinpath(self, *parts):
        if any(str(part).replace("\\", "/").endswith("holdout.jsonl") for part in parts): self.attempts.append(parts); raise AssertionError("holdout access attempted")
        return HoldoutGuard(self.resource.joinpath(*parts), self.attempts)
    def read_text(self, *args, **kwargs): return self.resource.read_text(*args, **kwargs)


class ReferenceDecompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.scenarios = catalog.load_scenarios("dev")
    def setUp(self): self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.output = Path(self.temp.name) / "output"

    def clean_git(self):
        return patch.object(rd, "_git", side_effect=lambda *args: rd.PROTOCOL_COMMIT if args[0] == "rev-parse" and args[1].endswith("^{commit}") else "implementation-sha" if args[0] == "rev-parse" else "agent/baselines-v0.1" if args[0] == "branch" else "")

    class Adapter:
        identifier = "offline-test-adapter"
        def __init__(self, invalid_at=None, provider_failure_at=None, interrupt_at=None):
            self.calls = 0; self.invalid_at = invalid_at; self.provider_failure_at = provider_failure_at; self.interrupt_at = interrupt_at
        def generate(self, prompt, config, response_schema=None):
            self.calls += 1
            if self.calls == self.interrupt_at: raise KeyboardInterrupt
            if self.calls == self.provider_failure_at: raise ValueError("synthetic terminal provider failure")
            if self.calls == self.invalid_at: return ModelResponse(text="{}")
            visible = json.loads(prompt.split("\n\nCANDIDATE-VISIBLE SCENARIO:\n", 1)[1])
            predictions = [{"decision_id": item["id"], "materially_dependent": False, "dependency_strength": "independent", "still_justified": True} for item in visible["decisions"]]
            return ModelResponse(text=json.dumps({"decisions": predictions}))
        def close(self): pass

    def prepared(self):
        with self.clean_git(): rd.prepare(self.output)

    def assert_execute_blocked_before_adapter(self):
        constructed=[]
        with self.assertRaises(rd.ReferenceDecompositionError): rd.execute(self.output, adapter_factory=lambda: constructed.append(True))
        self.assertEqual(constructed, [])

    def test_exact_four_conditions_and_views(self):
        self.assertEqual(rd.CONDITIONS, ("R0", "RE", "RA", "REA"))
        for scenario in self.scenarios:
            bundle = rd.build_view_bundle(scenario); views = bundle["views"]
            raw_implicit = candidate_view(scenario, "discovery", "implicit"); raw_structured = candidate_view(scenario, "discovery", "structured")
            self.assertEqual(bundle["raw"]["implicit"]["discovery_condition"], "implicit")
            self.assertEqual(bundle["raw"]["structured"]["discovery_condition"], "structured")
            expected_implicit=copy.deepcopy(raw_implicit); expected_implicit.pop("discovery_condition")
            expected_structured=copy.deepcopy(raw_structured); expected_structured.pop("discovery_condition")
            self.assertEqual(views["R0"], expected_implicit); self.assertEqual(views["REA"], expected_structured)
            proof=rd.prove_views(scenario, views, bundle); self.assertTrue(proof["pass"])
            self.assertEqual(proof["normalization"]["implicit_removed_paths"], ["/discovery_condition"])
            self.assertEqual(proof["normalization"]["structured_removed_paths"], ["/discovery_condition"])
            self.assertTrue(all("discovery_condition" not in view for view in views.values()))
            self.assertTrue(all("assumptions" not in d for d in views["RE"]["decisions"]))
            self.assertTrue(all("evidence_available" not in d for d in views["RA"]["decisions"]))
            structured={d["id"]:d for d in views["REA"]["decisions"]}
            for d in views["RE"]["decisions"]: self.assertEqual(d["evidence_available"],structured[d["id"]]["evidence_available"])
            for d in views["RA"]["decisions"]: self.assertEqual(d["assumptions"],structured[d["id"]]["assumptions"])
            self.assertFalse(any(set(view) & {"condition_id","reference_type","decomposition_condition","view_type"} for view in views.values()))

    def test_identity_alignment_and_unexpected_diff_block(self):
        scenario = copy.deepcopy(self.scenarios[0]); scenario["candidate"]["decisions"][0]["id"] = scenario["candidate"]["decisions"][1]["id"]
        with self.assertRaises(rd.ReferenceDecompositionError): rd.build_views(scenario)
        scenario = self.scenarios[0]; views = rd.build_views(scenario); views["RE"]["title"] = "changed"
        self.assertFalse(rd.prove_views(scenario, views)["pass"])

    def test_exact_plan_and_balance(self):
        plan = rd.build_execution_plan(); self.assertEqual(len(plan), 48)
        self.assertEqual(Counter(x["condition_id"] for x in plan), Counter({c: 12 for c in rd.CONDITIONS}))
        expected = [("R0","RE","RA","REA"),("RE","RA","REA","R0"),("RA","REA","R0","RE"),("REA","R0","RE","RA")]
        for i, scenario in enumerate(rd.DEV_SCENARIOS): self.assertEqual(tuple(x["condition_id"] for x in plan if x["scenario_id"] == scenario), expected[i % 4])
        for condition in rd.CONDITIONS: self.assertEqual(Counter(x["temporal_position"] for x in plan if x["condition_id"] == condition), Counter({1:3,2:3,3:3,4:3}))

    def test_prepare_is_dev_only_zero_provider_and_freezes_endpoint(self):
        attempts=[]; real_files=catalog.files
        def guarded(package): return HoldoutGuard(real_files(package), attempts)
        with self.clean_git(), patch("dr_bench.catalog.files", side_effect=guarded), patch.object(rd, "load_scenarios", wraps=catalog.load_scenarios) as loader, patch.object(rd, "_dev_adapter_factory", side_effect=AssertionError("provider constructed")):
            manifest=rd.prepare(self.output)
        self.assertEqual(attempts, []); self.assertTrue(all(call.args == ("dev",) for call in loader.call_args_list))
        self.assertTrue(manifest["execute_eligible"]); self.assertEqual(manifest["forensic_endpoint"], {"scenario_id":"dev-002","decision_id":"d3"})
        self.assertTrue(manifest["fresh_calls_required"]); self.assertFalse(manifest["historical_response_reuse_authorized"]); self.assertFalse(manifest["confirmation_authorized"])
        self.assertTrue(all("normalized" in description for description in manifest["conditions"].values()))

    def test_prepare_blocks_bad_structural_proof(self):
        original=rd.build_view_bundle
        def bad(scenario):
            bundle=original(scenario); bundle["views"]["RE"]["title"]="bad"; return bundle
        with self.clean_git(), patch.object(rd,"build_view_bundle",side_effect=bad): manifest=rd.prepare(self.output)
        self.assertFalse(manifest["execute_eligible"]); self.assertIn("BLOCKED",manifest["prepare_status"])

    def test_execute_requires_compatible_prepare_without_calling_provider(self):
        self.output.mkdir(); (self.output/rd.MANIFEST_FILENAME).write_text("{}")
        with patch.object(rd,"_dev_adapter_factory",side_effect=AssertionError("provider constructed")):
            with self.assertRaises(rd.ReferenceDecompositionError): rd.execute(self.output)

    def test_execute_runtime_integrity_valid_and_runtime_only(self):
        self.prepared()
        with self.clean_git(): self.assertTrue(rd.validate_execute_integrity(self.output)["tracked_worktree_clean"])
        with patch.object(rd, "_git", side_effect=lambda *args: "different" if args[:2] == ("rev-parse", "HEAD") else ""):
            self.assert_execute_blocked_before_adapter()
        with patch.object(rd, "_git", side_effect=lambda *args: "implementation-sha" if args[:2] == ("rev-parse", "HEAD") else "tracked-change" if args[0] == "status" else ""):
            self.assert_execute_blocked_before_adapter()
        with self.clean_git(), patch.object(rd, "protocol_sha256", return_value="wrong"):
            self.assert_execute_blocked_before_adapter()

    def test_plan_hash_and_semantic_validation_precede_adapter(self):
        self.prepared(); plan_path=self.output/rd.PLAN_FILENAME; manifest_path=self.output/rd.MANIFEST_FILENAME
        plan=json.loads(plan_path.read_text()); plan[0]["condition_id"]="BROKEN"; plan_path.write_bytes(rd._canonical_json(plan))
        with self.clean_git(): self.assert_execute_blocked_before_adapter()
        manifest=json.loads(manifest_path.read_text()); manifest["execution_plan_sha256"]=rd._sha(plan_path.read_bytes()); manifest_path.write_bytes(rd._canonical_json(manifest))
        with self.clean_git(): self.assert_execute_blocked_before_adapter()

    def test_structural_proof_hash_and_content_gates_precede_adapter(self):
        def normalization_false(proof): proof["scenario_proofs"][0]["normalization"]["pass"] = False
        def factorial_false(proof): proof["scenario_proofs"][0]["factorial_pass"] = False
        def scenario_false(proof): proof["scenario_proofs"][0]["pass"] = False
        mutations = (
            lambda p: p.update(all_pass=False), lambda p: p.update(normalization_pass_count=11),
            lambda p: p.update(factorial_pass_count=11), lambda p: p.update(ignored_diff_paths=["/ignored"]),
            lambda p: p.update(scenario_proofs=p["scenario_proofs"][:-1]), normalization_false, factorial_false, scenario_false,
        )
        import shutil
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                if self.output.exists(): shutil.rmtree(self.output)
                self.prepared(); proof_path=self.output/rd.PROOF_FILENAME; manifest_path=self.output/rd.MANIFEST_FILENAME
                proof=json.loads(proof_path.read_text()); mutate(proof); proof_path.write_bytes(rd._canonical_json(proof))
                with self.clean_git(): self.assert_execute_blocked_before_adapter()
                manifest=json.loads(manifest_path.read_text()); manifest["structural_proof_sha256"]=rd._sha(proof_path.read_bytes()); manifest_path.write_bytes(rd._canonical_json(manifest))
                with self.clean_git(): self.assert_execute_blocked_before_adapter()

    def test_manifest_eligibility_blocks_before_adapter(self):
        self.prepared(); path=self.output/rd.MANIFEST_FILENAME; manifest=json.loads(path.read_text()); manifest["execute_eligible"]=False; path.write_bytes(rd._canonical_json(manifest))
        with self.clean_git(): self.assert_execute_blocked_before_adapter()

    def test_execute_completeness_authorization_and_invalid_is_not_retried(self):
        import shutil
        cases=((None,None,48,0,0,True),(48,None,47,1,0,False),(None,48,47,0,1,False))
        for invalid_at, provider_at, valid, invalid, failures, authorized in cases:
            with self.subTest(invalid_at=invalid_at, provider_at=provider_at):
                if self.output.exists(): shutil.rmtree(self.output)
                self.prepared(); adapter=self.Adapter(invalid_at=invalid_at, provider_failure_at=provider_at)
                with self.clean_git(): summary=rd.execute(self.output, adapter_factory=lambda:adapter, sleep_fn=lambda _:None)
                self.assertEqual((summary["valid"],summary["invalid"],summary["provider_failures"],summary["analysis_authorized"]),(valid,invalid,failures,authorized))
                self.assertEqual(adapter.calls,48)
        shutil.rmtree(self.output); self.prepared(); adapter=self.Adapter(interrupt_at=1)
        with self.clean_git(), self.assertRaises(KeyboardInterrupt): rd.execute(self.output,adapter_factory=lambda:adapter,sleep_fn=lambda _:None)
        self.assertFalse(json.loads((self.output/"summary.json").read_text())["analysis_authorized"])

    def test_same_prompt_schema_model_and_transport_are_frozen(self):
        with self.clean_git(): manifest=rd.prepare(self.output)
        self.assertEqual(manifest["base_task_prompt_sha256"],rd._sha(rd.BASE_TASK_PROMPT.encode()))
        self.assertEqual(manifest["discovery_schema_version"],rd.DISCOVERY_RESPONSE_SCHEMA_VERSION)
        self.assertEqual(manifest["model_id"],rd.MODEL_ID)
        self.assertEqual(manifest["transport"]["max_delivery_attempts"],rd.MAX_DELIVERY_ATTEMPTS)
        self.assertEqual(rd.run_delivery_attempts.__module__, "dr_baselines.dev_experiment")

    def test_manifest_has_no_stage_or_reuse_path(self):
        with self.clean_git(): manifest=rd.prepare(self.output)
        self.assertFalse(manifest["stage1_present"]); self.assertFalse(manifest["multi_pass_present"])
        plan=json.loads((self.output/rd.PLAN_FILENAME).read_text()); self.assertTrue(all(x["observation_kind"]=="final" for x in plan))

    def rows_for_pattern(self, corrected):
        rows={condition:[] for condition in rd.CONDITIONS}
        for condition in rd.CONDITIONS:
            for scenario in self.scenarios:
                for label in scenario["private"]["decision_labels"]:
                    material=label["materially_dependent"]
                    if scenario["id"]=="dev-002" and label["decision_id"]=="d3" and condition not in corrected: material=not material
                    rows[condition].append({"scenario_id":scenario["id"],"decision_id":label["decision_id"],"true_materially_dependent":label["materially_dependent"],"predicted_materially_dependent":material,"true_still_justified":label["still_justified"],"predicted_still_justified":label["still_justified"],"true_dependency_strength":label["dependency_strength"],"predicted_dependency_strength":label["dependency_strength"]})
        return rows

    def test_factorial_patterns_and_strength_only_boundary(self):
        self.assertTrue(rd.classify_pattern(self.rows_for_pattern({"RE","REA"}))["pattern"].startswith("PATTERN A"))
        self.assertTrue(rd.classify_pattern(self.rows_for_pattern({"RA","REA"}))["pattern"].startswith("PATTERN B"))
        self.assertTrue(rd.classify_pattern(self.rows_for_pattern({"REA"}))["pattern"].startswith("PATTERN C"))
        self.assertTrue(rd.classify_pattern(self.rows_for_pattern({"RE","RA","REA"}))["pattern"].startswith("PATTERN D"))
        self.assertTrue(rd.classify_pattern(self.rows_for_pattern(set()))["pattern"].startswith("PATTERN E"))
        strength_only=self.rows_for_pattern(set()); strength_only["RE"][0]["predicted_dependency_strength"]="critical"
        self.assertTrue(rd.classify_pattern(strength_only)["pattern"].startswith("PATTERN E"))
        regression=self.rows_for_pattern({"RE","REA"}); regression["RE"][0]["predicted_still_justified"]=not regression["RE"][0]["true_still_justified"]
        self.assertTrue(rd.classify_pattern(regression)["pattern"].startswith("PATTERN E"))

    def test_task_framing_is_shared_and_condition_identity_is_out_of_band(self):
        views=rd.build_views(self.scenarios[0]); marker="\n\nCANDIDATE-VISIBLE SCENARIO:\n"
        prefixes=[]
        for condition,view in views.items():
            prompt=rd._prompt(view); prefixes.append(prompt.split(marker)[0]); serialized=json.loads(prompt.split(marker)[1])
            self.assertNotIn("discovery_condition",serialized)
            self.assertFalse(set(serialized)&{"condition_id","reference_type","decomposition_condition","view_type"})
        self.assertEqual(prefixes,[rd.BASE_TASK_PROMPT]*4)

    def make_completed_fixture(self):
        with self.clean_git(): rd.prepare(self.output)
        plan=json.loads((self.output/rd.PLAN_FILENAME).read_text()); scenarios={s["id"]:s for s in self.scenarios}; runs=[]
        for entry in plan:
            decisions=[]
            for label in scenarios[entry["scenario_id"]]["private"]["decision_labels"]:
                decisions.append({"decision_id":label["decision_id"],"materially_dependent":label["materially_dependent"],"dependency_strength":label["dependency_strength"],"still_justified":label["still_justified"]})
            runs.append({**entry,"validation_status":"valid","provider_error":None,"parsed_candidate_response":{"decisions":decisions}})
        (self.output/"runs.jsonl").write_text("".join(json.dumps(x)+"\n" for x in runs)); (self.output/"summary.json").write_text(json.dumps({"completed":48,"valid":48,"invalid":0,"provider_failures":0}))

    def test_analyze_is_dev_only_complete_and_zero_provider(self):
        self.make_completed_fixture(); analysis=Path(self.temp.name)/"analysis"; attempts=[]; real_files=catalog.files
        def guarded(package): return HoldoutGuard(real_files(package),attempts)
        with patch.object(rd,"_git",side_effect=AssertionError("ANALYZE must not inspect current HEAD/worktree")), patch("dr_bench.catalog.files",side_effect=guarded), patch.object(rd,"load_scenarios",wraps=catalog.load_scenarios) as loader, patch.object(rd,"_dev_adapter_factory",side_effect=AssertionError("provider constructed")):
            result=rd.analyze(self.output,analysis)
        self.assertEqual(attempts,[]); self.assertTrue(all(call.args==("dev",) for call in loader.call_args_list)); self.assertEqual(result["analysis_status"],"COMPLETE"); self.assertTrue(result["factorial_pattern"]["pattern"].startswith("PATTERN E")); self.assertIn("R0",result["forensic_endpoint"]); self.assertFalse(result["confirmation_authorized"]); self.assertFalse(result["historical_results_used"])

    def test_incomplete_and_bad_decision_rows_block_classification(self):
        self.make_completed_fixture(); (self.output/"summary.json").write_text(json.dumps({"completed":47,"valid":47,"invalid":0,"provider_failures":1}))
        with self.clean_git(): result=rd.analyze(self.output,Path(self.temp.name)/"partial")
        self.assertIsNone(result["factorial_pattern"])
        (self.output/"summary.json").write_text(json.dumps({"completed":48,"valid":48,"invalid":0,"provider_failures":0})); runs=[json.loads(x) for x in (self.output/"runs.jsonl").read_text().splitlines()]; runs[0]["parsed_candidate_response"]["decisions"].pop(); (self.output/"runs.jsonl").write_text("".join(json.dumps(x)+"\n" for x in runs))
        with self.clean_git(), self.assertRaises(rd.ReferenceDecompositionError): rd.analyze(self.output,Path(self.temp.name)/"bad")


if __name__ == "__main__": unittest.main()
