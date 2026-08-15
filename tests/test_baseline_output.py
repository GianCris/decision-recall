import json
import unittest

from dr_baselines import OutputValidationError, parse_discovery_response


def prediction(decision_id="d1"):
    return {"decision_id": decision_id, "materially_dependent": True, "dependency_strength": "material", "still_justified": False}


class OutputTests(unittest.TestCase):
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
