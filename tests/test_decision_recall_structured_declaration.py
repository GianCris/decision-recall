import unittest
from dataclasses import replace
from datetime import timedelta

from decision_recall.product.declaration import (
    CaptureAnswer,
    declaration_to_evidence,
    make_structured_capture_declaration,
)
from decision_recall.product.golden_loop import T0, prepare_golden_capture


class StructuredDeclarationBindingTests(unittest.TestCase):
    def test_deserialized_declaration_must_rebind_to_authoritative_session_assignment(self):
        preparation = prepare_golden_capture()
        gap = preparation.critical_gaps[0]
        declaration = make_structured_capture_declaration(
            session=preparation.session,
            gap=gap,
            answer=CaptureAnswer.YES,
            answered_at=T0 - timedelta(seconds=1),
        )
        tampered = replace(declaration, profile_hash="attacker-profile-hash")
        with self.assertRaisesRegex(ValueError, "profile binding"):
            declaration_to_evidence(
                declaration=tampered,
                session=preparation.session,
                gap=gap,
                evidence_id="E-TAMPERED-PROFILE",
            )

    def test_declaration_content_must_reproduce_its_bound_identity(self):
        preparation = prepare_golden_capture()
        gap = preparation.critical_gaps[0]
        declaration = make_structured_capture_declaration(
            session=preparation.session,
            gap=gap,
            answer=CaptureAnswer.YES,
            answered_at=T0 - timedelta(seconds=1),
            optional_note="original note",
        )
        tampered = replace(declaration, optional_note="changed after declaration")
        with self.assertRaisesRegex(ValueError, "does not reproduce its declaration id"):
            declaration_to_evidence(
                declaration=tampered,
                session=preparation.session,
                gap=gap,
                evidence_id="E-TAMPERED-CONTENT",
            )


if __name__ == "__main__":
    unittest.main()
