import json
import hashlib
import unittest

from dr_bench import candidate_view, load_scenario
from dr_baselines import B0, B1, B2, BASE_TASK_PROMPT, REEVALUATION_INSTRUCTION


class PromptTests(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario("dev-001")

    def test_baseline_interfaces_are_fixed(self):
        self.assertEqual((B0.baseline_id, B0.condition), ("B0", "implicit"))
        self.assertEqual((B1.baseline_id, B1.condition), ("B1", "structured"))
        self.assertEqual((B2.baseline_id, B2.condition), ("B2", "structured"))

    def test_b0_and_b1_use_exact_same_base_instruction(self):
        self.assertIs(B0.task_instruction, BASE_TASK_PROMPT)
        self.assertIs(B1.task_instruction, BASE_TASK_PROMPT)
        self.assertEqual(B0.task_instruction, B1.task_instruction)
        self.assertEqual(
            hashlib.sha256(BASE_TASK_PROMPT.encode("utf-8")).hexdigest(),
            "2ed1e0280d3108aa9f7458bc7a21d4cf9f82ad2e6c4795d2ac516fffdb5557b1",
        )

    def test_b2_is_base_prompt_plus_only_isolated_block(self):
        self.assertEqual(B2.task_instruction, BASE_TASK_PROMPT + "\n\n" + REEVALUATION_INSTRUCTION)
        self.assertEqual(
            hashlib.sha256(REEVALUATION_INSTRUCTION.encode("utf-8")).hexdigest(),
            "92983251bc6c7fcd7557eb36947d2ade4d539a6e7a054df065e88d32120630d8",
        )

    def test_prompt_rejects_wrong_condition(self):
        structured = candidate_view(self.scenario, "discovery", "structured")
        with self.assertRaises(ValueError):
            B0.build_prompt(structured)

    def test_b0_prompt_has_implicit_input_only(self):
        prompt = B0.build_prompt(candidate_view(self.scenario, "discovery", "implicit"))
        self.assertNotIn("evidence_available", prompt)
        self.assertNotIn('"assumptions"', prompt)
        self.assertIn('"discovery_condition":"implicit"', prompt)

    def test_b1_and_b2_prompts_have_structured_input(self):
        view = candidate_view(self.scenario, "discovery", "structured")
        for baseline in (B1, B2):
            prompt = baseline.build_prompt(view)
            self.assertIn("evidence_available", prompt)
            self.assertIn('"assumptions"', prompt)
            self.assertIn('"discovery_condition":"structured"', prompt)

    def test_no_prompt_contains_private_or_recovery_oracle_fields(self):
        for baseline in (B0, B1, B2):
            view = candidate_view(self.scenario, "discovery", baseline.condition)
            prompt = baseline.build_prompt(view)
            for forbidden in ("decision_labels", "dependency_path", "expected_actions", "expected_final_world", "must_recover", "must_not_touch"):
                self.assertNotIn(forbidden, prompt)
