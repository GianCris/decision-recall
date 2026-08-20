import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from google.genai import errors as genai_errors

from dr_baselines.dev_experiment import RETRYABLE_HTTP_STATUS_CODES, _retryable_delivery_failure, run_delivery_attempts
from dr_baselines.models import ModelResponse
from dr_baselines.round_b import build_stage2_prompt
from dr_baselines.round_b import execute as execute_round_b
from dr_baselines.round_b_recovery import (
    MANIFEST_FILENAME, RECOVERY_MANIFEST_TYPE, RECOVERY_PROTOCOL_SHA256,
    IdentityProofError, RecoveryError, _identity_evidence,
    _load_prepared_recovery, build_recovery_plan, execute_recovery,
    find_recovery_eligible_slots, prepare_recovery, recovered_view_metadata,
    recovery_protocol_sha256,
)


class FakeAPIError(genai_errors.APIError):
    def __init__(self, code):
        Exception.__init__(self, "provider")
        self.code = code


class Adapter:
    identifier = "offline-mock"
    def __init__(self, response=None, error=None):
        self.response = response; self.error = error; self.calls = []
    def generate(self, prompt, config, response_schema=None):
        self.calls.append((prompt, config, response_schema))
        if self.error: raise self.error
        return self.response
    def close(self): pass


class RoundBRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.original = self.root / "original"; self.original.mkdir()
        self.output = self.root / "recovery"
        self.slot = {"candidate_view_mode": "implicit", "condition_id": "RC0", "dependency_artifact_required": "RC0_GENERIC_STAGE1", "dependency_producing_stage": "RC0_GENERIC_STAGE1", "expected_output_contract": "discovery-response-v0.1", "global_execution_index": 11, "observation_kind": "final", "protocol_version": "round-b-protocol-v0.2", "repetition_id": "1", "scenario_id": "dev-002", "stage_id": "RC0_STAGE2", "within_scenario_order": 3}
        self.artifact_bytes = b'{\n  "grounded_items": []\n}\n'; self.artifact_sha = hashlib.sha256(self.artifact_bytes).hexdigest()
        self.write_fixture()

    def jsonl(self, name, rows):
        (self.original / name).write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in rows), encoding="utf-8")

    def write_fixture(self):
        plan_bytes = (json.dumps([self.slot], indent=2, sort_keys=True) + "\n").encode(); (self.original / "execution_plan.json").write_bytes(plan_bytes)
        manifest = {"manifest_type": "round-b-screening-manifest-v0.2", "experiment_version": "round-b-screening-v0.2", "git_commit_sha": "167ecfa50c871c74d0aee4ed9abd9feab40fc923", "round_b_protocol_sha256": "eba2cd3d3c848ca43a0c26e1eb7c23e1c5be3af6a44a218a2018bb4019c1f335", "execution_plan_sha256": hashlib.sha256(plan_bytes).hexdigest(), "model_id": "gemini-3.7-flash", "provider": "Google Cloud Agent Platform / Vertex", "project_id": "decision-recall-hackathon", "location": "global"}
        (self.original / "experiment_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (self.original / "summary.json").write_text(json.dumps({"experiment_status": "completed", "classification_status": "INCOMPLETE / INFRASTRUCTURE", "provider_failures": 1, "abort_reason": None}), encoding="utf-8")
        failure = {**self.slot, "event": "delivery_attempt_completed", "outcome": "pre_response_failure", "model_response_obtained": False, "will_retry": False, "started_at_utc": "2026-01-01T00:00:00Z", "completed_at_utc": "2026-01-01T00:02:00Z", "http_status_code": 499}
        self.jsonl("delivery_attempts.jsonl", [failure])
        terminal = {**self.slot, "validation_status": "provider_error", "raw_model_response": "", "parsed_candidate_response": None}
        self.jsonl("terminal_states.jsonl", [terminal]); self.jsonl("runs.jsonl", [{**terminal, "artifact_sha256": self.artifact_sha}]); self.jsonl("evaluations.jsonl", [])
        self.jsonl("stage1_artifacts.jsonl", [{"scenario_id": "dev-002", "stage_id": "RC0_GENERIC_STAGE1", "model_call_executed": True, "canonical_bytes_utf8": self.artifact_bytes.decode(), "artifact_sha256": self.artifact_sha, "artifact_envelope": {"artifact_sha256": self.artifact_sha}}])

    def frozen_git(self):
        return patch.multiple("dr_baselines.round_b_recovery", _git_sha=Mock(return_value="f" * 40), _git_branch=Mock(return_value="agent/baselines-v0.1"), _tracked_clean=Mock(return_value=True), _frozen_reconstruction_source_identity=Mock(return_value={"frozen": "a" * 64}))

    def prepared(self):
        with self.frozen_git(), patch("dr_baselines.round_b_recovery.EXPECTED_DEPENDENCY_SHA256", self.artifact_sha):
            prepare_recovery(self.original, self.output)

    def test_eligibility_and_exact_one_slot_plan_without_stage1(self):
        eligible = find_recovery_eligible_slots(self.original); self.assertEqual(len(eligible), 1)
        plan = build_recovery_plan(eligible[0]); self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["original_global_execution_index"], 11); self.assertEqual(plan[0]["stage_id"], "RC0_STAGE2")
        self.assertTrue(plan[0]["out_of_original_order"]); self.assertTrue(plan[0]["infrastructure_recovered"])

    def test_invalid_valid_and_response_bearing_slots_are_ineligible(self):
        for values in ({"validation_status": "invalid", "raw_model_response": "{}", "parsed_candidate_response": None}, {"validation_status": "valid", "raw_model_response": '{"decisions":[]}', "parsed_candidate_response": {"decisions": []}}, {"validation_status": "provider_error", "raw_model_response": "returned", "parsed_candidate_response": None}):
            record = {**self.slot, **values}; self.jsonl("terminal_states.jsonl", [record]); self.jsonl("runs.jsonl", [{**record, "artifact_sha256": self.artifact_sha}])
            self.assertEqual(find_recovery_eligible_slots(self.original), [])

    def test_evaluation_or_missing_dependency_blocks(self):
        self.jsonl("evaluations.jsonl", [{"global_execution_index": 11, "evaluation": {}}]); self.assertEqual(find_recovery_eligible_slots(self.original), [])
        self.jsonl("evaluations.jsonl", []); self.jsonl("stage1_artifacts.jsonl", []); self.assertEqual(find_recovery_eligible_slots(self.original), [])

    def test_sanity_historical_or_other_dependency_cannot_substitute(self):
        substituted = b'{"source":"sanity-or-v0.1"}\n'; digest = hashlib.sha256(substituted).hexdigest()
        self.jsonl("stage1_artifacts.jsonl", [{"scenario_id": "dev-002", "stage_id": "RC0_GENERIC_STAGE1", "model_call_executed": True, "canonical_bytes_utf8": substituted.decode(), "artifact_sha256": digest, "artifact_envelope": {"artifact_sha256": digest}}])
        self.assertEqual(find_recovery_eligible_slots(self.original), [])

    def test_prepare_is_offline_read_only_and_freezes_identity(self):
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.original.iterdir()}
        with self.frozen_git(), patch("dr_baselines.round_b_recovery._dev_adapter_factory") as factory, patch("dr_baselines.round_b_recovery.EXPECTED_DEPENDENCY_SHA256", self.artifact_sha):
            manifest = prepare_recovery(self.original, self.output)
        factory.assert_not_called(); self.assertEqual(manifest["manifest_type"], RECOVERY_MANIFEST_TYPE)
        self.assertEqual(manifest["planned_recovery_scientific_observations"], 1); self.assertTrue(manifest["execute_eligible"])
        self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.original.iterdir()})
        self.assertEqual(hashlib.sha256((self.output / "dependency_payload.json").read_bytes()).hexdigest(), self.artifact_sha)
        self.assertFalse(manifest["recovered_view_support"]["sensitivity_evaluated_during_prepare"])

    def test_prepare_rejects_existing_output_and_nonunique_source(self):
        self.output.mkdir()
        with self.assertRaisesRegex(RecoveryError, "already exists"): prepare_recovery(self.original, self.output)
        self.output.rmdir(); self.jsonl("terminal_states.jsonl", [])
        with self.frozen_git(), self.assertRaisesRegex(RecoveryError, "exactly one"): prepare_recovery(self.original, self.output)

    def test_identity_classes_and_category_c_or_failed_proof_block(self):
        evidence = _identity_evidence(find_recovery_eligible_slots(self.original)[0], b"candidate", b"prompt", b"schema")
        self.assertEqual({x["class"] for x in evidence["components"].values()}, {"A", "B"})
        with self.frozen_git(), patch("dr_baselines.round_b_recovery.EXPECTED_DEPENDENCY_SHA256", self.artifact_sha), patch("dr_baselines.round_b_recovery._identity_evidence", return_value={"category_c_count": 1, "all_proven": False}):
            with self.assertRaises(IdentityProofError): prepare_recovery(self.original, self.output)

    def test_prompt_exact_artifact_envelope_invisible_and_no_result_context(self):
        slot = find_recovery_eligible_slots(self.original)[0]; self.prepared()
        prompt = (self.output / "effective_prompt.txt").read_text(); visible = json.loads((self.output / "candidate_visible_input.json").read_text())
        self.assertEqual(prompt, build_stage2_prompt("RC0", visible, slot.dependency_canonical_bytes))
        for text in ("artifact_schema_version", "artifact_sha256", "provider_error", "71 other observations"):
            self.assertNotIn(text, prompt)

    def test_499_nonretryable_and_shared_delivery_is_single_attempt(self):
        self.assertNotIn(499, RETRYABLE_HTTP_STATUS_CODES); self.assertFalse(_retryable_delivery_failure(FakeAPIError(499))[0])
        calls = []
        result = run_delivery_attempts({"global_execution_index": 11}, self.root / "delivery.jsonl", lambda: calls.append(1) or (_ for _ in ()).throw(FakeAPIError(499)), lambda _: None)
        self.assertEqual(len(calls), 1); self.assertIsNone(result["result"])

    def test_invalid_response_not_regenerated(self):
        self.prepared(); adapter = Adapter(ModelResponse(text="{}"))
        with self.frozen_git(): summary = execute_recovery(self.original, self.output, lambda: adapter, lambda _: None)
        self.assertEqual(len(adapter.calls), 1); self.assertEqual(summary["recovery_status"], "FAIL / MODEL OUTPUT")
        self.assertFalse((self.output / "recovery_evaluation.json").exists())

    def test_provider_failure_no_second_observation(self):
        self.prepared(); adapter = Adapter(error=RuntimeError("offline"))
        with self.frozen_git(): summary = execute_recovery(self.original, self.output, lambda: adapter, lambda _: None)
        self.assertEqual(len(adapter.calls), 1); self.assertEqual(summary["recovery_status"], "INCOMPLETE / INFRASTRUCTURE")
        self.assertEqual(summary["scientific_observations_planned"], 1)

    def test_valid_response_once_and_recovered_view_metadata(self):
        self.prepared(); visible = json.loads((self.output / "candidate_visible_input.json").read_text())
        predictions = [{"decision_id": x["id"], "materially_dependent": False, "dependency_strength": "independent", "still_justified": True} for x in visible["decisions"]]
        adapter = Adapter(ModelResponse(text=json.dumps({"decisions": predictions})))
        with self.frozen_git(): summary = execute_recovery(self.original, self.output, lambda: adapter, lambda _: None)
        self.assertEqual(len(adapter.calls), 1); self.assertEqual(summary["recovery_status"], "RECOVERED / VALID")
        metadata = recovered_view_metadata(json.loads((self.output / MANIFEST_FILENAME).read_text()), summary)
        self.assertTrue(metadata["contains_infrastructure_recovered_observation"]); self.assertFalse(metadata["sensitivity_evaluated"])
        self.assertEqual(json.loads((self.original / "summary.json").read_text())["classification_status"], "INCOMPLETE / INFRASTRUCTURE")

    def test_execute_requires_compatible_prepared_manifest_and_detects_tamper(self):
        ordinary = self.root / "ordinary"; ordinary.mkdir(); (ordinary / "experiment_manifest.json").write_text("{}")
        with self.assertRaises(RecoveryError): execute_recovery(self.original, ordinary, lambda: Adapter())
        self.prepared(); (self.output / "effective_prompt.txt").write_text("tampered")
        with self.frozen_git(), self.assertRaises(IdentityProofError): _load_prepared_recovery(self.original, self.output)

    def test_recovery_directory_is_rejected_by_ordinary_round_b_and_transport_not_duplicated(self):
        self.prepared()
        with self.assertRaises(Exception): execute_round_b(self.output, adapter_factory=Mock())
        source = inspect.getsource(execute_recovery)
        self.assertIn("run_delivery_attempts", source); self.assertNotIn("for attempt", source)
        module_source = Path("dr_baselines/round_b_recovery.py").read_text(encoding="utf-8")
        self.assertNotIn("sealed", module_source.lower())

    def test_protocol_freeze(self):
        self.assertEqual(recovery_protocol_sha256(), RECOVERY_PROTOCOL_SHA256)


if __name__ == "__main__": unittest.main()
