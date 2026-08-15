import json
import unittest
from importlib.resources import files

from dr_bench import load_scenario, load_scenarios, validate_scenario
from dr_bench.validation import ScenarioValidationError, derive_agent_hops


class ContractTests(unittest.TestCase):
    def test_machine_schema_is_valid_json_schema_document(self):
        schema = json.loads(files("dr_bench").joinpath("schema", "scenario.schema.json").read_text())
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(set(schema["required"]), {"schema_version", "id", "split", "domain", "title", "complexity", "candidate", "private"})

    def test_catalog_is_frozen_12_dev_4_holdout(self):
        scenarios = load_scenarios()
        self.assertEqual(len(scenarios), 16)
        self.assertEqual(len(load_scenarios("dev")), 12)
        self.assertEqual(len(load_scenarios("holdout")), 4)
        self.assertEqual(len({item["id"] for item in scenarios}), 16)

    def test_every_scenario_validates(self):
        for scenario in load_scenarios():
            with self.subTest(scenario=scenario["id"]):
                validate_scenario(scenario)

    def test_contract_covers_dependency_classes(self):
        strengths = {label["dependency_strength"] for scenario in load_scenarios() for label in scenario["private"]["decision_labels"]}
        self.assertEqual(strengths, {"independent", "supporting", "material", "critical"})

    def test_all_required_hard_negatives_exist(self):
        present = {kind for scenario in load_scenarios() for kind in scenario["private"]["hard_negative_types"]}
        required = {"temporal_non_dependence", "semantic_independent", "alternate_sufficient_reason", "downstream_non_material", "must_not_touch", "irrelevant_change", "branch_selectivity"}
        self.assertTrue(required <= present)

    def test_complexity_axes_have_controlled_levels(self):
        scenarios = load_scenarios()
        self.assertEqual({s["complexity"]["agent_hops"] for s in scenarios}, {0, 1, 2, 4})
        self.assertEqual({s["complexity"]["semantic_distance"] for s in scenarios}, {"literal", "paraphrase", "semantic_transformation", "conceptual_consequence"})
        self.assertEqual({s["complexity"]["information_transformation"] for s in scenarios}, {"copy", "summary", "compression", "inference"})
        self.assertEqual({s["complexity"]["boundary"] for s in scenarios}, {"shared", "partial_visibility", "department", "different_authority"})

    def test_declared_hops_are_derived_from_observable_chains(self):
        for scenario in load_scenarios():
            actual = derive_agent_hops(scenario["candidate"]["transmissions"])
            self.assertEqual(actual, scenario["complexity"]["agent_hops"], scenario["id"])

    def test_validation_rejects_metadata_only_hop_claim(self):
        scenario = load_scenario("dev-006")
        scenario["candidate"]["transmissions"] = scenario["candidate"]["transmissions"][:2]
        with self.assertRaises(ScenarioValidationError):
            validate_scenario(scenario)

    def test_unknown_id_fails(self):
        with self.assertRaises(KeyError):
            load_scenario("dev-999")
