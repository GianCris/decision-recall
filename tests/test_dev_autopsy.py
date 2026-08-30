import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dr_baselines import dev_autopsy


def scenario():
    return {
        "complexity": {
            "agent_hops": 2, "semantic_distance": "paraphrase",
            "information_transformation": "summary", "boundary": "department",
        },
        "private": {
            "hard_negative_types": ["supporting"],
            "decision_labels": [
                {"decision_id": "d1", "materially_dependent": True, "dependency_strength": "material",
                 "still_justified": False, "downstream": False, "dependency_path": {"agent_hops": 2}},
                {"decision_id": "d2", "materially_dependent": False, "dependency_strength": "supporting",
                 "still_justified": True, "negative_type": "supporting", "downstream": True,
                 "dependency_path": {"agent_hops": 1}},
            ],
        },
    }


def run(repetition="1", baseline="B0", d1=None, d2=None):
    predictions = [
        d1 or {"decision_id": "d1", "materially_dependent": True, "dependency_strength": "material", "still_justified": False},
        d2 or {"decision_id": "d2", "materially_dependent": True, "dependency_strength": "material", "still_justified": False},
    ]
    return {
        "scenario_id": "dev-001", "repetition_id": repetition, "baseline_id": baseline,
        "global_call_index": int(repetition) * 2 + (baseline == "B1"), "pair_id": f"p{repetition}",
        "pair_order": "B0_then_B1", "order_within_pair": 1 if baseline == "B0" else 2,
        "parsed_candidate_response": {"decisions": predictions},
    }


class DevAutopsyTests(unittest.TestCase):
    def official_copy(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        target = Path(temporary.name) / "official"
        shutil.copytree(dev_autopsy.SOURCE_DIR, target)
        return target

    def test_source_integrity_refuses_ineligible_incomplete_version_and_hash_changes(self):
        cases = (
            ("summary.json", "official_result_eligible", False),
            ("summary.json", "experiment_status", "aborted"),
            ("summary.json", "experiment_version", "dev-baselines-v0.3"),
            ("experiment_manifest.json", "git_commit_sha", "bad"),
            ("experiment_manifest.json", "execution_plan_sha256", "bad"),
            ("experiment_manifest.json", "prompt_sha256", "bad"),
            ("experiment_manifest.json", "response_schema_version", "bad"),
            ("experiment_manifest.json", "response_schema_sha256", "bad"),
        )
        for filename, field, value in cases:
            with self.subTest(field=field):
                source = self.official_copy()
                path = source / filename
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload[field] = value
                path.write_text(json.dumps(payload), encoding="utf-8")
                with patch.object(dev_autopsy, "SOURCE_DIR", source), self.assertRaises(dev_autopsy.AutopsyIntegrityError):
                    dev_autopsy.validate_source(source)

    def test_official_source_passes_and_is_exactly_72_valid_slots(self):
        manifest, summary, runs, evaluations = dev_autopsy.validate_source()
        self.assertEqual(manifest["git_commit_sha"], dev_autopsy.SOURCE_GIT_SHA)
        self.assertTrue(summary["official_result_eligible"])
        self.assertEqual((len(runs), len(evaluations)), (72, 72))

    def test_ledger_is_decision_level_and_binary_confusion_is_correct(self):
        rows = dev_autopsy.build_ledger([run()], {"dev-001": scenario()})
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["binary_confusion_class"] for row in rows], ["TP", "FP"])
        self.assertEqual(dev_autopsy._metric_summary(rows, "B0")["FP"], 1)
        self.assertEqual(rows[1]["strength_transition"], "supporting -> material")

    def test_repeated_observations_collapse_to_one_unique_failure(self):
        runs = [run(str(number)) for number in (1, 2, 3)]
        rows = dev_autopsy.build_ledger(runs, {"dev-001": scenario()})
        failures = [row for row in rows if not row["materially_dependent_correct"]]
        unique = dev_autopsy._unique_failures(rows, "materially_dependent_correct", "binary")
        self.assertEqual(len(failures), 3)
        self.assertEqual(len(unique), 1)
        self.assertEqual(unique[0]["repetitions_failed"], 3)
        self.assertEqual(unique[0]["repetitions_observed"], 3)
        self.assertEqual(unique[0]["failure_rate"], 1.0)
        self.assertTrue(unique[0]["structured_prediction_consistent"])
        self.assertTrue(unique[0]["full_structured_prediction_consistent"])

    def test_strength_matrix_and_b0_b1_disagreement_categories(self):
        b0 = run("1", "B0")
        b1 = run("1", "B1", d2={
            "decision_id": "d2", "materially_dependent": False,
            "dependency_strength": "supporting", "still_justified": True,
        })
        rows = dev_autopsy.build_ledger([b0, b1], {"dev-001": scenario()})
        matrix, transitions = dev_autopsy._strength_matrix(rows, "B0")
        supporting = next(row for row in matrix if row["true_strength"] == "supporting")
        self.assertEqual(supporting["material"], 1)
        self.assertEqual(transitions["supporting -> material"], 1)
        disagreement = dev_autopsy._disagreements(rows)
        strength_d2 = next(row for row in disagreement if row["decision_id"] == "d2" and row["field"] == "dependency_strength")
        still_d2 = next(row for row in disagreement if row["decision_id"] == "d2" and row["field"] == "still_justified")
        self.assertEqual(strength_d2["correctness_category"], "B0_wrong_B1_correct")
        self.assertEqual(still_d2["correctness_category"], "B0_wrong_B1_correct")

    def test_shared_and_baseline_only_errors_are_distinguishable(self):
        rows = dev_autopsy.build_ledger(
            [run("1", "B0"), run("1", "B1"), run("2", "B0"),
             run("2", "B1", d2={"decision_id": "d2", "materially_dependent": False,
                                  "dependency_strength": "supporting", "still_justified": True})],
            {"dev-001": scenario()},
        )
        values = [row for row in dev_autopsy._disagreements(rows) if row["decision_id"] == "d2" and row["field"] == "materially_dependent"]
        self.assertEqual({row["correctness_category"] for row in values}, {"both_wrong", "B0_wrong_B1_correct"})

    def test_controls_use_only_exact_metadata_matches_and_preserve_all_ties(self):
        rows = dev_autopsy.build_ledger([run(str(number)) for number in (1, 2, 3)], {"dev-001": scenario()})
        success = copy.deepcopy(rows[0])
        success.update({"scenario_id": "dev-002", "decision_id": "d9", "baseline_id": "B0",
                        "materially_dependent_correct": True, "dependency_strength_correct": True})
        controls = dev_autopsy._controls(rows + [success], dev_autopsy._unique_failures(rows, "materially_dependent_correct", "binary"))
        self.assertTrue(any(row["control_scenario_id"] == "dev-002" for row in controls))
        self.assertTrue(any(row["match_scope"] == "individual:hard_negative_tag=supporting" for row in controls))
        self.assertTrue(all(row["match_scope"].startswith(("individual:", "maximum_exact:")) for row in controls))
        self.assertTrue(all("distance_score" not in row and "weight" not in row for row in controls))

    def test_metadata_breakdowns_warn_about_overlap_and_do_not_invent_fields(self):
        rows = dev_autopsy.build_ledger([run()], {"dev-001": scenario()})
        breakdown = dev_autopsy._metadata_breakdowns(rows)
        self.assertIn("overlap", breakdown["warning"].lower())
        self.assertEqual(set(breakdown["dimensions"]), set(dev_autopsy.META_FIELDS) | {
            "decision_negative_type", "downstream", "dependency_path_agent_hops",
        })

    def test_module_is_offline_fixed_source_and_noncausal(self):
        source = Path(dev_autopsy.__file__).read_text(encoding="utf-8")
        self.assertNotIn("GeminiVertexAdapter", source)
        self.assertNotIn("requests", source)
        self.assertNotIn("sealed_holdout", source)
        self.assertNotIn("nearest_neighbor", source.lower())
        self.assertIn("FORENSIC / DESCRIPTIVE ONLY", source)
        self.assertIn("B1 is a provenance-enabled baseline/reference, not an oracle", source)

    def test_generated_artifacts_are_deterministic(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        left = Path(temporary.name) / "left"
        right = Path(temporary.name) / "right"
        dev_autopsy.generate_autopsy(output_dir=left)
        dev_autopsy.generate_autopsy(output_dir=right)
        self.assertEqual(
            {path.name: path.read_bytes() for path in left.iterdir()},
            {path.name: path.read_bytes() for path in right.iterdir()},
        )


if __name__ == "__main__":
    unittest.main()
