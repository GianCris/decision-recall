import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dr_bench import candidate_view, load_scenario
from dr_baselines.models import ModelResponse
from dr_baselines.round_b import (
    ARTIFACT_ENVELOPE_VERSION, DECISION_SUPPORT_JSON_SCHEMA,
    NEUTRAL_GROUNDED_CONTEXT_JSON_SCHEMA, PROMPT_HASHES, PROTOCOL_SHA256,
    RC0_STAGE1_NEUTRAL_GROUNDED_CONTEXT_INSTRUCTION,
    RECONSTRUCTION_STAGE1_INSTRUCTION, IntermediateValidationError,
    build_artifact_envelope, build_stage1_projection, build_stage2_prompt, execute,
    protocol_sha256, validate_decision_support,
    validate_neutral_grounded_context, verify_artifact_envelope,
)
from dr_baselines.round_b_sanity import (
    SANITY_EXPERIMENT_VERSION, SANITY_MANIFEST_TYPE, SANITY_SCHEDULE,
    build_sanity_plan, execute_sanity, prepare_sanity, validate_sanity_plan,
)


def projection(scenario_id="dev-001"):
    scenario = load_scenario(scenario_id)
    public = {key: value for key, value in scenario.items() if key != "private"}
    return build_stage1_projection(candidate_view(public, "discovery", "implicit"))


def neutral_value(source, optional_ids=False):
    items = [
        {"source_path": "/knowledge_before/0/statement", "source_text": source["knowledge_before"][0]["statement"]},
        {"source_path": "/change/statement", "source_text": source["change"]["statement"]},
        {"source_path": "/decisions/0/statement", "source_text": source["decisions"][0]["statement"]},
    ]
    if source["transmissions"]:
        items.append({"source_path": "/transmissions/0/content", "source_text": source["transmissions"][0]["content"]})
    if optional_ids:
        items.append({"source_path": "/decisions/0/id", "source_text": source["decisions"][0]["id"]})
    return {"grounded_items": items}


def support_value(source):
    return {"change_alignment": {"change_ref": source["change"]["id"], "candidate_prior_knowledge_refs": []},
        "decision_connections": [{"decision_id": item["id"], "candidate_knowledge_refs": [], "basis_trace_refs": []} for item in source["decisions"]]}


class SanityAdapter:
    identifier = "sanity-fake"

    def __init__(self, invalid_calls=(), provider_calls=()):
        self.calls = []; self.invalid_calls = set(invalid_calls); self.provider_calls = set(provider_calls)

    def generate(self, prompt, config, response_schema=None):
        self.calls.append((prompt, config, response_schema)); number = len(self.calls)
        if number in self.provider_calls: raise RuntimeError("provider unavailable")
        source = json.loads(prompt.split("STAGE1VISIBLEPROJECTION:\n", 1)[1])
        if number in self.invalid_calls: text = "{}"
        elif response_schema is NEUTRAL_GROUNDED_CONTEXT_JSON_SCHEMA: text = json.dumps(neutral_value(source))
        else: text = json.dumps(support_value(source))
        return ModelResponse(text=text, latency_ms=1, input_tokens=1, output_tokens=1)

    def close(self): pass


class RoundBV02Tests(unittest.TestCase):
    def output(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        return Path(temp.name) / "sanity"

    def frozen_git(self):
        return patch.multiple("dr_baselines.round_b_sanity", _git_sha=Mock(return_value="a" * 40),
            _git_branch=Mock(return_value="agent/baselines-v0.1"), _tracked_clean=Mock(return_value=True))

    def prepared(self):
        output = self.output()
        with self.frozen_git(): prepare_sanity(output)
        return output

    def assert_category(self, category, value, source):
        with self.assertRaises(IntermediateValidationError) as caught:
            validate_neutral_grounded_context(json.dumps(value), source)
        self.assertEqual(caught.exception.category, category)

    def test_protocol_and_prompt_freeze(self):
        self.assertEqual(protocol_sha256(), PROTOCOL_SHA256)
        self.assertEqual(hashlib.sha256(RC0_STAGE1_NEUTRAL_GROUNDED_CONTEXT_INSTRUCTION.encode()).hexdigest(), PROMPT_HASHES["rc0_stage1"])
        self.assertEqual(hashlib.sha256(RECONSTRUCTION_STAGE1_INSTRUCTION.encode()).hexdigest(), "b691855c1d3e6240daa45b5174e66c7a18286b9c943abe034dff7b33540cd716")

    def test_model_schemas_are_closed_and_have_no_administrative_fields(self):
        forbidden = {"schema_version", "artifact_schema_version", "scenario_id", "stage_id", "artifact_sha256"}
        for schema in (NEUTRAL_GROUNDED_CONTEXT_JSON_SCHEMA, DECISION_SUPPORT_JSON_SCHEMA):
            self.assertFalse(forbidden & set(schema["properties"])); self.assertFalse(schema["additionalProperties"])

    def test_envelope_is_post_validation_hash_and_out_of_band(self):
        source = projection(); canonical, encoded, digest = validate_neutral_grounded_context(json.dumps(neutral_value(source)), source)
        envelope = build_artifact_envelope(source["scenario_id"], "RC0_GENERIC_STAGE1", encoded)
        self.assertEqual(envelope, {"artifact_schema_version": ARTIFACT_ENVELOPE_VERSION, "scenario_id": source["scenario_id"], "stage_id": "RC0_GENERIC_STAGE1", "artifact_sha256": digest})
        verify_artifact_envelope(envelope, encoded)
        visible = candidate_view({k: v for k, v in load_scenario("dev-001").items() if k != "private"}, "discovery", "implicit")
        prompt = build_stage2_prompt("RC0", visible, encoded)
        for field in envelope: self.assertNotIn(field, prompt)
        self.assertIn(json.dumps(canonical, indent=2, sort_keys=True), prompt)

    def test_pointer_grounding_and_terminal_type_rules(self):
        source = projection(); valid = neutral_value(source, optional_ids=True)
        self.assertTrue(validate_neutral_grounded_context(json.dumps(valid), source)[0])
        for path in ("/change", "/decisions", "/missing"):
            bad = neutral_value(source); bad["grounded_items"][0]["source_path"] = path
            self.assert_category("SEMANTIC_REFERENCE_INVALID", bad, source)
        for text in (source["knowledge_before"][0]["statement"][:4], "paraphrased"):
            bad = neutral_value(source); bad["grounded_items"][0]["source_text"] = text
            self.assert_category("SEMANTIC_REFERENCE_INVALID", bad, source)
        duplicate = neutral_value(source); duplicate["grounded_items"].append(dict(duplicate["grounded_items"][0]))
        self.assert_category("SCHEMA_INVALID", duplicate, source)

    def test_exact_semantic_coverage_and_identifier_noncoverage(self):
        source = projection()
        required = ("/knowledge_before/0/statement", "/change/statement", "/decisions/0/statement", "/transmissions/0/content")
        for path in required:
            bad = neutral_value(source); bad["grounded_items"] = [x for x in bad["grounded_items"] if x["source_path"] != path]
            bad["grounded_items"].append({"source_path": path.rsplit("/", 1)[0] + "/id", "source_text": source[path.split('/')[1]][int(path.split('/')[2])]["id"]}) if path != "/change/statement" else bad["grounded_items"].append({"source_path": "/change/id", "source_text": source["change"]["id"]})
            self.assert_category("SEMANTIC_COVERAGE_INVALID", bad, source)
        empty = projection("dev-005"); self.assertTrue(validate_neutral_grounded_context(json.dumps(neutral_value(empty)), empty)[0])

    def test_specialized_fields_and_admin_fields_are_schema_invalid(self):
        source = projection()
        for field in ("change_to_knowledge", "decision_support", "materially_dependent", "survivability", "alternative_support"):
            value = neutral_value(source); value[field] = []
            self.assert_category("FORBIDDEN_SEMANTIC_CONTENT", value, source)
        value = neutral_value(source); value["schema_version"] = "model-owned"
        self.assert_category("SCHEMA_INVALID", value, source)

    def test_reconstruction_payload_and_reference_contract_unchanged(self):
        source = projection(); value = support_value(source)
        canonical, _, _ = validate_decision_support(json.dumps(value), source)
        self.assertEqual(set(canonical), {"change_alignment", "decision_connections"})
        self.assertEqual(set(canonical["change_alignment"]), {"change_ref", "candidate_prior_knowledge_refs"})
        bad = support_value(source); bad["change_alignment"]["change_ref"] = "wrong"
        with self.assertRaises(IntermediateValidationError): validate_decision_support(json.dumps(bad), source)
        missing = support_value(source); missing["decision_connections"].pop()
        with self.assertRaises(IntermediateValidationError): validate_decision_support(json.dumps(missing), source)

    def test_sanity_plan_exact_and_stage1_only(self):
        plan = build_sanity_plan(); validate_sanity_plan(plan)
        self.assertEqual([(x["scenario_id"], x["stage_id"]) for x in plan], list(SANITY_SCHEDULE))
        self.assertTrue(all(x["observation_kind"] == "intermediate" for x in plan))
        self.assertEqual(hashlib.sha256(json.dumps(plan, indent=2, sort_keys=True).encode()).hexdigest(), hashlib.sha256(json.dumps(build_sanity_plan(), indent=2, sort_keys=True).encode()).hexdigest())

    def test_prepare_zero_calls_and_manifest_isolated(self):
        output = self.output()
        with self.frozen_git(), patch("dr_baselines.round_b_sanity._dev_adapter_factory") as factory:
            manifest = prepare_sanity(output)
        factory.assert_not_called(); self.assertEqual(manifest["manifest_type"], SANITY_MANIFEST_TYPE)
        self.assertEqual(manifest["experiment_version"], SANITY_EXPERIMENT_VERSION)
        self.assertNotEqual(manifest["experiment_version"], manifest["full_screening_experiment_version"])

    def test_sanity_and_full_screening_manifests_are_mutually_rejected(self):
        full = self.output(); full.mkdir(); (full / "experiment_manifest.json").write_text("{}")
        with self.assertRaisesRegex(Exception, "full-screening manifest"):
            execute_sanity(full, adapter_factory=Mock())
        sanity = self.output(); sanity.mkdir(); (sanity / "sanity_manifest.json").write_text("{}")
        with self.assertRaisesRegex(Exception, "sanity manifest"):
            execute(sanity, adapter_factory=Mock())

    def test_sanity_pass_and_no_stage2_or_scoring(self):
        output = self.prepared(); adapter = SanityAdapter()
        with self.frozen_git(), patch("dr_baselines.round_b_sanity.load_scenario", wraps=load_scenario):
            summary = execute_sanity(output, adapter_factory=lambda: adapter, sleep_fn=lambda _: None)
        self.assertEqual(summary["sanity_status"], "PASS"); self.assertEqual(len(adapter.calls), 6)
        self.assertEqual(summary["stage2_calls"], 0); self.assertEqual(summary["discovery_evaluations"], 0)
        self.assertFalse(summary["artifact_reuse_authorized"])

    def test_invalid_continues_and_is_fail_interface(self):
        output = self.prepared(); adapter = SanityAdapter(invalid_calls={1})
        with self.frozen_git(): summary = execute_sanity(output, adapter_factory=lambda: adapter, sleep_fn=lambda _: None)
        self.assertEqual(len(adapter.calls), 6); self.assertEqual(summary["sanity_status"], "FAIL / INTERFACE")
        self.assertEqual(summary["model_mechanism_invalid_payloads"], 1)

    def test_provider_failure_continues_and_is_infrastructure(self):
        output = self.prepared(); adapter = SanityAdapter(provider_calls={1})
        with self.frozen_git(): summary = execute_sanity(output, adapter_factory=lambda: adapter, sleep_fn=lambda _: None)
        self.assertEqual(len(adapter.calls), 6); self.assertEqual(summary["sanity_status"], "INCOMPLETE / INFRASTRUCTURE")
        self.assertEqual(summary["provider_delivery_failures"], 1)

    def test_mixed_failure_preserves_both_and_interface_precedence(self):
        output = self.prepared(); adapter = SanityAdapter(invalid_calls={1}, provider_calls={2})
        with self.frozen_git(): summary = execute_sanity(output, adapter_factory=lambda: adapter, sleep_fn=lambda _: None)
        self.assertEqual(len(adapter.calls), 6); self.assertEqual(summary["sanity_status"], "FAIL / INTERFACE")
        self.assertEqual(summary["model_mechanism_invalid_payloads"], 1); self.assertEqual(summary["provider_delivery_failures"], 1)


if __name__ == "__main__": unittest.main()
