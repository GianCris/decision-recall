from __future__ import annotations

import http.client
import json
import threading
import unittest
from unittest.mock import patch

from decision_recall.product.cloudrun_server import (
    DecisionRecallHandler,
    build_capture_preparation,
    complete_verified_reevaluation,
)
from decision_recall.product.golden_loop import T0, T1
from http.server import ThreadingHTTPServer


class CloudRunTemporalIntakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), DecisionRecallHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def _capture(self) -> dict[str, str]:
        preparation = build_capture_preparation()
        return {
            "capture_session_id": str(preparation["capture_session_id"]),
            "gap_id": str(preparation["gap_id"]),
            "question_hash": str(preparation["question_hash"]),
            "answer": "yes",
        }

    def _payload(self) -> dict[str, object]:
        timestamp = T1.isoformat()
        return {
            "decision_id": "D-104",
            "capture": self._capture(),
            "world_time": timestamp,
            "evidence": [
                {
                    "evidence_id": "WE-E301-APEX-PRODUCT-V1",
                    "metric_key": "apex_on_time_rate",
                    "value": 0.987,
                    "unit": "ratio",
                    "window_days": 30,
                    "observed_at": timestamp,
                    "source": "supplied_current_record",
                },
                {
                    "evidence_id": "WE-BEACON-PRODUCT-V1",
                    "metric_key": "beacon_reactivation_days",
                    "value": 70,
                    "unit": "days",
                    "window_days": None,
                    "observed_at": timestamp,
                    "source": "supplied_current_record",
                },
            ],
        }

    def _post(self, path: str, payload: object, *, raw: bool = False) -> tuple[int, dict[str, object]]:
        body = payload if raw else json.dumps(payload, separators=(",", ":"))
        assert isinstance(body, str)
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request(
            "POST",
            path,
            body=body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        decoded = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, decoded

    def test_capture_http_response_is_t0_only(self) -> None:
        status, result = self._post("/api/capture", self._capture())

        self.assertEqual(status, 200)
        self.assertEqual(result["capture"]["knowledge_state"], "established")
        self.assertEqual(result["future_evaluation_status"], "not_requested")
        for forbidden in (
            "current_matches",
            "safe_reuse_result",
            "limiting_requirements",
            "reason_codes",
            "evaluation_hash",
            "replay_hash",
        ):
            self.assertNotIn(forbidden, result)

    def test_valid_live_evidence_reproduces_frozen_winner_semantics_and_hashes(self) -> None:
        result = complete_verified_reevaluation(self._payload())

        self.assertEqual(result["status"], "reevaluated")
        self.assertEqual(result["decision_id"], "D-104")
        self.assertEqual(
            {item["entity_id"]: item["state"] for item in result["current_matches"]},
            {"M1": "does_not_match", "M2": "matches"},
        )
        self.assertEqual(result["safe_reuse_result"], "insufficient_evidence")
        self.assertEqual(result["limiting_requirements"], ["C1"])
        self.assertEqual(result["reason_codes"], ["REQUIRED_COMPOSITION_NOT_DURABLY_KNOWN"])
        self.assertEqual(len(result["accepted_world_events"]), 2)
        self.assertEqual(
            result["evaluation_hash"],
            "25ab192b3301cac929185081efc83da0fc744ae47832a3910f767567d0b4adf6",
        )
        self.assertEqual(result["replay_hash"], result["evaluation_hash"])

    def test_identical_http_requests_reconstruct_fresh_t0_and_replay_identically(self) -> None:
        payload = self._payload()
        with patch(
            "decision_recall.product.cloudrun_server.complete_golden_capture",
            wraps=__import__(
                "decision_recall.product.cloudrun_server",
                fromlist=["complete_golden_capture"],
            ).complete_golden_capture,
        ) as complete:
            first_status, first = self._post("/api/reevaluate", payload)
            second_status, second = self._post("/api/reevaluate", payload)

        self.assertEqual((first_status, second_status), (200, 200))
        self.assertEqual(first, second)
        self.assertEqual(complete.call_count, 2)

    def test_capture_binding_tampering_fails_closed(self) -> None:
        for field in ("capture_session_id", "gap_id", "question_hash"):
            with self.subTest(field=field):
                payload = self._payload()
                payload["capture"][field] += "-tampered"
                status, result = self._post("/api/reevaluate", payload)
                self.assertEqual(status, 409)
                self.assertEqual(result["status"], "error")

        payload = self._payload()
        payload["capture"]["answer"] = "no"
        self.assertEqual(self._post("/api/reevaluate", payload)[0], 400)

    def test_structural_and_authority_injection_fields_are_rejected(self) -> None:
        mutations = []
        for field in (
            "safe_reuse_result",
            "disposition",
            "authorized",
            "evaluation_hash",
            "limiting_requirements",
        ):
            payload = self._payload()
            payload[field] = "forged"
            mutations.append(payload)

        payload = self._payload()
        payload["unknown"] = True
        mutations.append(payload)
        payload = self._payload()
        payload["capture"]["unknown"] = True
        mutations.append(payload)
        payload = self._payload()
        payload["evidence"][0]["unknown"] = True
        mutations.append(payload)

        for payload in mutations:
            with self.subTest(keys=tuple(payload)):
                self.assertEqual(self._post("/api/reevaluate", payload)[0], 400)

    def test_world_evidence_contract_and_domain_rejections(self) -> None:
        cases: list[tuple[str, dict[str, object], int]] = []

        payload = self._payload()
        payload["evidence"][0]["metric_key"] = "unknown_metric"
        cases.append(("unknown metric", payload, 422))

        payload = self._payload()
        payload["evidence"][0]["unit"] = "percent"
        cases.append(("invalid unit", payload, 422))

        payload = self._payload()
        payload["evidence"][0]["value"] = 1.5
        cases.append(("out of range", payload, 422))

        payload = self._payload()
        payload["evidence"][0]["value"] = float("nan")
        cases.append(("nonfinite", payload, 400))

        payload = self._payload()
        payload["evidence"][1]["evidence_id"] = payload["evidence"][0]["evidence_id"]
        cases.append(("duplicate evidence id", payload, 409))

        payload = self._payload()
        payload["evidence"][1]["metric_key"] = payload["evidence"][0]["metric_key"]
        cases.append(("duplicate metric", payload, 409))

        payload = self._payload()
        payload["evidence"][0]["observed_at"] = "2026-10-05T09:00:00+00:00"
        cases.append(("observation after world", payload, 422))

        payload = self._payload()
        payload["world_time"] = T0.isoformat()
        cases.append(("world at T0", payload, 422))

        payload = self._payload()
        payload["evidence"][0]["source"] = "verified_erp"
        cases.append(("unauthorized source", payload, 400))

        payload = self._payload()
        payload["evidence"][0]["window_days"] = 29
        cases.append(("wrong Apex window", payload, 422))

        for label, payload, expected in cases:
            with self.subTest(label=label):
                status, result = self._post("/api/reevaluate", payload)
                self.assertEqual(status, expected)
                self.assertEqual(result["status"], "error")

    def test_malformed_and_oversized_json_are_rejected(self) -> None:
        self.assertEqual(self._post("/api/reevaluate", "{bad", raw=True)[0], 400)
        self.assertEqual(self._post("/api/reevaluate", "x" * 13000, raw=True)[0], 413)


if __name__ == "__main__":
    unittest.main()
