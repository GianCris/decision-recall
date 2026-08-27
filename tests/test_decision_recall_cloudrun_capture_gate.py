from __future__ import annotations

import unittest
from unittest.mock import patch

from decision_recall.product.cloudrun_server import (
    CaptureBindingMismatch,
    build_capture_preparation,
    complete_verified_capture,
)


class CloudRunCaptureGateTests(unittest.TestCase):
    def _valid_payload(self) -> dict[str, str]:
        preparation = build_capture_preparation()
        return {
            "capture_session_id": str(preparation["capture_session_id"]),
            "gap_id": str(preparation["gap_id"]),
            "question_hash": str(preparation["question_hash"]),
            "answer": "yes",
        }

    def test_preparation_is_authoritative_and_unresolved(self) -> None:
        preparation = build_capture_preparation()

        self.assertEqual(preparation["decision_id"], "D-104")
        self.assertEqual(preparation["gap_id"], "R2")
        self.assertEqual(preparation["knowledge_state"], "not_durably_recorded")
        self.assertIn("Beacon", preparation["question"])
        self.assertEqual(len(str(preparation["question_hash"])), 64)

    def test_exact_capture_binding_allows_winner_completion(self) -> None:
        result = complete_verified_capture(self._valid_payload())

        validation = result["capture_validation"]
        capture = result["capture"]
        self.assertEqual(validation["status"], "accepted")
        self.assertEqual(validation["gap_id"], "R2")
        self.assertEqual(validation["answer"], "yes")
        self.assertEqual(validation["completion"], "allowed")
        self.assertEqual(capture["decision_id"], "D-104")
        self.assertEqual(capture["relation_id"], "R2")
        self.assertEqual(capture["knowledge_state"], "established")
        self.assertEqual(result["future_evaluation_status"], "not_requested")

        serialized = str(result)
        for forbidden in (
            "current_matches",
            "safe_reuse_result",
            "limiting_requirements",
            "reason_codes",
            "evaluation_hash",
            "replay_hash",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_live_capture_path_never_calls_full_golden_compatibility_run(self) -> None:
        with patch(
            "decision_recall.product.cloudrun_server.run_golden_decision",
            side_effect=AssertionError("live capture must not run T1 compatibility path"),
        ):
            result = complete_verified_capture(self._valid_payload())

        self.assertEqual(result["capture"]["knowledge_state"], "established")
        self.assertEqual(result["future_evaluation_status"], "not_requested")

    def test_tampered_binding_is_rejected(self) -> None:
        for field in ("capture_session_id", "gap_id", "question_hash"):
            with self.subTest(field=field):
                payload = self._valid_payload()
                payload[field] = payload[field] + "-tampered"
                with self.assertRaises(CaptureBindingMismatch):
                    complete_verified_capture(payload)

    def test_capture_schema_is_intentionally_narrow(self) -> None:
        invalid_payloads = []

        extra = self._valid_payload()
        extra["note"] = "arbitrary text must not enter the winner capture API"
        invalid_payloads.append(extra)

        wrong_answer = self._valid_payload()
        wrong_answer["answer"] = "not_sure"
        invalid_payloads.append(wrong_answer)

        missing = self._valid_payload()
        missing.pop("question_hash")
        invalid_payloads.append(missing)

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    complete_verified_capture(payload)


if __name__ == "__main__":
    unittest.main()
