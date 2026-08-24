import unittest

from decision_recall.product.declaration import CaptureAnswer
from decision_recall.product.gemini_compiler import GeminiCandidateCompiler
from decision_recall.product.golden_loop import run_golden_decision


class QueueTransport:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    def generate_json(self, *, system_instruction, prompt, response_schema):
        self.calls.append((system_instruction, prompt, response_schema))
        if not self.payloads:
            raise AssertionError("unexpected Gemini transport call")
        return self.payloads.pop(0)


class ProductCheckpoint2IntegrationTests(unittest.TestCase):
    def test_gemini_observable_plus_structured_human_authority_reaches_same_strict_replay_result(self):
        transport = QueueTransport(
            {
                "candidates": [
                    {
                        "semantic_key": "apex_delivery_instability",
                        "kind": "fact",
                        "source_id": "decision-note",
                        "quote": "Apex delivery performance has been materially unstable.",
                    },
                    {
                        "semantic_key": "beacon_reactivation_delay",
                        "kind": "fact",
                        "source_id": "supplier-record",
                        "quote": "Beacon requires roughly 10 weeks to reactivate.",
                    },
                    {
                        "semantic_key": "historical_support:apex_delivery_instability",
                        "kind": "historical_role",
                        "source_id": "decision-note",
                        "quote": "Apex instability materially influenced the decision.",
                    },
                ]
            }
        )
        result = run_golden_decision(
            compiler=GeminiCandidateCompiler(transport=transport),
            capture_answer=CaptureAnswer.YES,
        )

        self.assertEqual(len(transport.calls), 1, "Gemini must only interpret observable documents")
        self.assertEqual(result.r2_trace.knowledge_state, "established")
        self.assertEqual(result.evaluation.safe_reuse_result, "insufficient_evidence")
        self.assertEqual(result.evaluation.limiting_requirements, ("C1",))
        self.assertEqual(dict(result.evaluation.current_matches), {"M1": "does_not_match", "M2": "matches"})
        self.assertEqual(dict(result.evaluation.review_states), {"RC1": "triggered"})
        self.assertEqual(result.replay_result_hash, result.evaluation.result_hash)


if __name__ == "__main__":
    unittest.main()
