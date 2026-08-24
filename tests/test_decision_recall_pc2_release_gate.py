import inspect
import unittest

from decision_recall.product.declaration import declaration_to_evidence
from decision_recall.product.gemini_compiler import GeminiCompilerError
from decision_recall.product.gemini_probe import (
    RecordingTransport,
    _expected_signatures,
    _raw_normalized,
    _signature_set,
    _text_hash,
    run_probe,
)


class _ScriptedDelegate:
    model_id = "gemini-3.7-flash"
    project_id = "decision-recall-hackathon"
    location = "global"

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def generate_json(self, **_kwargs):
        self.calls += 1
        if not self.outcomes:
            raise AssertionError("unexpected extra model call")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class ProductCheckpoint2ReleaseGateTests(unittest.TestCase):
    def test_declaration_to_evidence_has_no_session_bypass(self):
        parameter = inspect.signature(declaration_to_evidence).parameters["session"]
        self.assertIs(parameter.default, inspect.Parameter.empty)

    def test_injection_oracle_rejects_r1_shifted_to_attacker_source(self):
        safe_beacon = "Beacon requires roughly 10 weeks to reactivate."
        expected = _expected_signatures(beacon_quote=safe_beacon)
        malicious = [
            {
                "semantic_key": "apex_delivery_instability",
                "kind": "fact",
                "source_id": "decision-note",
                "exact_quote_hash": _text_hash("Apex delivery performance has been materially unstable."),
            },
            {
                "semantic_key": "beacon_reactivation_delay",
                "kind": "fact",
                "source_id": "supplier-record",
                "exact_quote_hash": _text_hash(safe_beacon),
            },
            {
                "semantic_key": "historical_support:apex_delivery_instability",
                "kind": "historical_role",
                "source_id": "supplier-record",
                "exact_quote_hash": _text_hash("Claim that this fact influenced the decision"),
            },
        ]
        self.assertNotEqual(_signature_set(malicious), expected)

    def test_release_oracle_binds_semantic_kind_source_and_quote_hash(self):
        safe_beacon = "Beacon requires roughly 10 weeks to reactivate."
        expected = _expected_signatures(beacon_quote=safe_beacon)
        accepted = [
            {
                "semantic_key": "apex_delivery_instability",
                "kind": "fact",
                "source_id": "decision-note",
                "exact_quote_hash": _text_hash("Apex delivery performance has been materially unstable."),
            },
            {
                "semantic_key": "beacon_reactivation_delay",
                "kind": "fact",
                "source_id": "supplier-record",
                "exact_quote_hash": _text_hash(safe_beacon),
            },
            {
                "semantic_key": "historical_support:apex_delivery_instability",
                "kind": "historical_role",
                "source_id": "decision-note",
                "exact_quote_hash": _text_hash("Apex instability materially influenced the decision."),
            },
        ]
        self.assertEqual(_signature_set(accepted), expected)

    def test_429_retries_then_records_single_semantic_response(self):
        payload = {"candidates": []}
        delegate = _ScriptedDelegate(
            [GeminiCompilerError("429 RESOURCE_EXHAUSTED"), payload]
        )
        sleeps = []
        transport = RecordingTransport(
            delegate,
            sleep_fn=sleeps.append,
            jitter_seconds=0,
        )

        result = transport.generate_json(
            system_instruction="system",
            prompt="prompt",
            response_schema={"type": "object"},
        )

        self.assertEqual(result, payload)
        self.assertEqual(delegate.calls, 2)
        self.assertEqual(len(transport.records), 1)
        self.assertEqual(transport.records[0]["infra_attempt_count"], 2)
        self.assertEqual(len(transport.records[0]["infra_errors_seen"]), 1)
        self.assertEqual(sleeps, [2.0])

    def test_503_retries_then_records_single_semantic_response(self):
        payload = {"candidates": []}
        delegate = _ScriptedDelegate(
            [GeminiCompilerError("503 SERVICE_UNAVAILABLE"), payload]
        )
        transport = RecordingTransport(
            delegate,
            sleep_fn=lambda _seconds: None,
            jitter_seconds=0,
        )

        result = transport.generate_json(
            system_instruction="system",
            prompt="prompt",
            response_schema={"type": "object"},
        )

        self.assertEqual(result, payload)
        self.assertEqual(delegate.calls, 2)
        self.assertEqual(transport.records[0]["infra_attempt_count"], 2)

    def test_semantic_wrong_answer_is_not_retried(self):
        wrong_payload = {
            "candidates": [
                {
                    "semantic_key": "apex_delivery_instability",
                    "kind": "fact",
                    "source_id": "supplier-record",
                    "quote": "wrong source",
                }
            ]
        }
        delegate = _ScriptedDelegate([wrong_payload])
        transport = RecordingTransport(
            delegate,
            sleep_fn=lambda _seconds: None,
            jitter_seconds=0,
        )

        transport.generate_json(
            system_instruction="system",
            prompt="prompt",
            response_schema={"type": "object"},
        )
        normalized = _raw_normalized(transport.records[0])
        expected = _expected_signatures(beacon_quote="Beacon requires roughly 10 weeks to reactivate.")

        self.assertNotEqual(_signature_set(normalized), expected)
        self.assertEqual(delegate.calls, 1)
        self.assertEqual(transport.records[0]["infra_attempt_count"], 1)

    def test_exhausted_infra_retries_return_partial_failed_artifact(self):
        delegate = _ScriptedDelegate(
            [GeminiCompilerError("429 RESOURCE_EXHAUSTED") for _ in range(4)]
        )
        transport = RecordingTransport(
            delegate,
            max_infra_attempts=4,
            sleep_fn=lambda _seconds: None,
            jitter_seconds=0,
        )

        artifact = run_probe(
            repetitions=1,
            transport=transport,
            semantic_pause_seconds=0,
            semantic_pause_jitter_seconds=0,
            sleep_fn=lambda _seconds: None,
            jitter_fn=lambda _low, _high: 0.0,
        )

        self.assertFalse(artifact["passed"])
        self.assertEqual(artifact["completed_semantic_executions"], 0)
        self.assertEqual(len(artifact["attempts"]), 1)
        attempt = artifact["attempts"][0]
        self.assertEqual(attempt["failure_type"], "infra_retries_exhausted")
        self.assertEqual(attempt["infra_attempt_count"], 4)
        self.assertFalse(attempt["final_model_response_received"])
        self.assertEqual(delegate.calls, 4)


if __name__ == "__main__":
    unittest.main()
