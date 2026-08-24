import inspect
import unittest

from decision_recall.product.declaration import declaration_to_evidence
from decision_recall.product.gemini_probe import _expected_signatures, _signature_set, _text_hash


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


if __name__ == "__main__":
    unittest.main()
