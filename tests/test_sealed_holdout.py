import hashlib
import json
import unittest
from pathlib import Path

from dr_bench import load_scenario, load_scenarios
from dr_bench.views import candidate_view, contains_private_key
from sealed_holdout.validate_sealed import MANIFEST_PATH, load_and_validate, structural_report


class SealedHoldoutTests(unittest.TestCase):
    EXPECTED_MANIFEST_SHA256 = "27c0436ecdd19dc68d106d00bec88b84f3891fd1bae8c8e4328818df87258188"
    EXPECTED_MATRIX = {
        "H1": ("holdout-101", "aviation_operations", 0, "literal", "copy", "shared", 2),
        "H2": ("holdout-102", "insurance_underwriting", 1, "paraphrase", "summary", "department", 4),
        "H3": ("holdout-103", "cloud_operations", 2, "semantic_transformation", "compression", "partial_visibility", 3),
        "H4": ("holdout-104", "food_safety_distribution", 4, "conceptual_consequence", "inference", "different_authority", 5),
        "H5": ("holdout-105", "industrial_maintenance", 1, "conceptual_consequence", "inference", "partial_visibility", 3),
        "H6": ("holdout-106", "payments_fraud", 2, "paraphrase", "summary", "different_authority", 4),
        "H7": ("holdout-107", "regulatory_compliance", 4, "semantic_transformation", "compression", "department", 5),
        "H8": ("holdout-108", "model_data_governance", 0, "semantic_transformation", "copy", "shared", 2),
    }

    def test_manifest_and_all_artifact_hashes_are_frozen(self):
        self.assertEqual(hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(), self.EXPECTED_MANIFEST_SHA256)
        manifest, _ = load_and_validate()
        self.assertEqual(len(manifest["scenarios"]), 8)

    def test_precommitted_matrix_and_decision_counts_match(self):
        manifest, _ = load_and_validate()
        actual = {}
        for item in manifest["scenarios"]:
            complexity = item["complexity"]
            actual[item["matrix_id"]] = (item["scenario_id"], item["domain"], complexity["agent_hops"], complexity["semantic_distance"], complexity["information_transformation"], complexity["boundary"], item["decision_count"])
        self.assertEqual(actual, self.EXPECTED_MATRIX)

    def test_precommitted_compositions_and_hard_negatives_exist(self):
        _, scenarios = load_and_validate()
        by_id = {item["id"]: item for item in scenarios}
        strengths = lambda scenario_id: {x["dependency_strength"] for x in by_id[scenario_id]["private"]["decision_labels"]}
        self.assertTrue({"critical", "independent"} <= strengths("holdout-101"))
        self.assertTrue({"material", "supporting"} <= strengths("holdout-102"))
        self.assertTrue({"material", "independent"} <= strengths("holdout-103"))
        self.assertTrue({"critical", "supporting"} <= strengths("holdout-104"))
        self.assertIn("branch_selectivity", by_id["holdout-105"]["private"]["hard_negative_types"])
        self.assertIn("alternate_sufficient_reason", by_id["holdout-106"]["private"]["hard_negative_types"])
        self.assertIn("downstream_non_material", by_id["holdout-107"]["private"]["hard_negative_types"])
        self.assertIn("irrelevant_change", by_id["holdout-108"]["private"]["hard_negative_types"])

    def test_candidate_views_never_leak_private_ground_truth(self):
        _, scenarios = load_and_validate()
        for scenario in scenarios:
            for condition in ("implicit", "structured"):
                self.assertFalse(contains_private_key(candidate_view(scenario, "discovery", condition)), (scenario["id"], condition))

    def test_normal_catalog_cannot_enumerate_or_load_sealed_ids(self):
        normal_ids = {item["id"] for item in load_scenarios()}
        sealed_ids = {item[0] for item in self.EXPECTED_MATRIX.values()}
        self.assertTrue(normal_ids.isdisjoint(sealed_ids))
        for scenario_id in sealed_ids:
            with self.assertRaises(KeyError):
                load_scenario(scenario_id)

    def test_sealed_data_is_not_normal_package_data_or_baseline_code(self):
        root = Path(__file__).resolve().parents[1]
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertNotIn("sealed_holdout", pyproject)
        self.assertFalse((root / "dr_baselines").exists())
        self.assertFalse((root / "dr_bench" / "data" / "sealed").exists())

    def test_validation_tool_has_no_model_or_provider_imports(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "sealed_holdout" / "validate_sealed.py").read_text(encoding="utf-8")
        for forbidden in ("google", "genai", "dr_baselines", "ModelAdapter", "generate_content"):
            self.assertNotIn(forbidden, source)

    def test_manifest_contains_no_performance_or_model_result_fields(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        def keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield key.lower()
                    yield from keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from keys(child)

        manifest_keys = set(keys(manifest))
        for forbidden in ("score", "precision", "recall", "f1", "prediction", "model_result", "latency", "tokens"):
            self.assertNotIn(forbidden, manifest_keys)

    def test_structural_report_only_contains_permitted_fields(self):
        report = structural_report()
        self.assertEqual(set(report), {"dataset_id", "scenario_ids", "domains", "decision_counts", "dependency_strengths", "hard_negative_types", "hashes"})
