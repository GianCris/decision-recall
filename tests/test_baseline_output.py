import json
import unittest

from dr_baselines import DISCOVERY_RESPONSE_JSON_SCHEMA, OutputValidationError, parse_discovery_response


def prediction(decision_id="d1"):
    return {"decision_id": decision_id, "materially_dependent": True, "dependency_strength": "material", "still_justified": False}


class OutputTests(unittest.TestCase):
    def test_native_schema_is_only_the_frozen_discovery_shape(self):
        self.assertEqual(set(DISCOVERY_RESPONSE_JSON_SCHEMA), {"type", "additionalProperties", "required", "properties"})
        self.assertEqual(DISCOVERY_RESPONSE_JSON_SCHEMA["required"], ["decisions"])
        decision = DISCOVERY_RESPONSE_JSON_SCHEMA["properties"]["decisions"]["items"]
        self.assertFalse(decision["additionalProperties"])
        self.assertEqual(
            set(decision["properties"]),
            {"decision_id", "materially_dependent", "dependency_strength", "still_justified"},
        )
        self.assertEqual(decision["properties"]["decision_id"], {"type": "string"})
        self.assertEqual(
            decision["properties"]["dependency_strength"]["enum"],
            ["independent", "supporting", "material", "critical"],
        )

    def test_accepts_exact_contract(self):
        raw = json.dumps({"decisions": [prediction("d1"), prediction("d2")]})
        self.assertEqual(len(parse_discovery_response(raw, ["d1", "d2"])["decisions"]), 2)

    def test_rejects_missing_decision(self):
        with self.assertRaises(OutputValidationError):
            parse_discovery_response(json.dumps({"decisions": [prediction("d1")]}), ["d1", "d2"])

    def test_rejects_duplicate_decision(self):
        with self.assertRaises(OutputValidationError):
            parse_discovery_response(json.dumps({"decisions": [prediction("d1"), prediction("d1")]}), ["d1", "d2"])

    def test_rejects_unknown_decision(self):
        with self.assertRaises(OutputValidationError):
            parse_discovery_response(json.dumps({"decisions": [prediction("d1"), prediction("unknown")]}), ["d1", "d2"])

    def test_rejects_extra_fields_and_non_json(self):
        item = prediction(); item["reason"] = "extra"
        with self.assertRaises(OutputValidationError):
            parse_discovery_response(json.dumps({"decisions": [item]}), ["d1"])
        with self.assertRaises(OutputValidationError):
            parse_discovery_response("not json", ["d1"])

    def test_rejects_inconsistent_material_flag(self):
        item = prediction(); item["dependency_strength"] = "independent"
        with self.assertRaises(OutputValidationError):
            parse_discovery_response(json.dumps({"decisions": [item]}), ["d1"])
