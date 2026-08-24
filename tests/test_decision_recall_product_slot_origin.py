import unittest

from decision_recall.domain import RelationType
from decision_recall.product.capture import (
    DecisionFactBinding,
    DecisionRelationBinding,
    DecisionStructure,
    ProfileBinder,
    supplier_resilience_capture_template,
)


class ProductSlotOriginTests(unittest.TestCase):
    def _structure(self, relations):
        return DecisionStructure(
            decision_id="D-104",
            decision_display="this decision",
            facts=(
                DecisionFactBinding(
                    "F1",
                    "apex_delivery_instability",
                    "Apex delivery performance has been materially unstable",
                ),
                DecisionFactBinding(
                    "F2",
                    "beacon_reactivation_delay",
                    "Beacon requires roughly 10 weeks to reactivate",
                ),
            ),
            relations=relations,
        )

    def test_binder_creates_r2_when_target_relation_is_absent(self):
        structure = self._structure(
            (
                DecisionRelationBinding(
                    "R1",
                    RelationType.HISTORICAL_SUPPORT,
                    "F1",
                    "D-104",
                ),
            )
        )
        profile, _trace = ProfileBinder().bind(
            template=supplier_resilience_capture_template(),
            structure=structure,
        )
        slot = profile.slots[0].slot
        self.assertEqual(slot.id, "R2")
        self.assertEqual(slot.subject_id, "F2")
        self.assertEqual(slot.object_id, "D-104")
        self.assertEqual(slot.relation_type, RelationType.HISTORICAL_SUPPORT)

    def test_prewritten_target_relation_does_not_steer_slot_origin(self):
        without_target = self._structure(
            (
                DecisionRelationBinding(
                    "R1",
                    RelationType.HISTORICAL_SUPPORT,
                    "F1",
                    "D-104",
                ),
            )
        )
        with_target = self._structure(
            without_target.relations
            + (
                DecisionRelationBinding(
                    "R99",
                    RelationType.HISTORICAL_SUPPORT,
                    "F2",
                    "D-104",
                ),
            )
        )
        profile_without, _ = ProfileBinder().bind(
            template=supplier_resilience_capture_template(),
            structure=without_target,
        )
        profile_with, _ = ProfileBinder().bind(
            template=supplier_resilience_capture_template(),
            structure=with_target,
        )
        self.assertEqual(profile_without.slots[0].slot.id, "R2")
        self.assertEqual(profile_with.slots[0].slot.id, "R2")
        self.assertNotEqual(profile_with.slots[0].slot.id, "R99")

    def test_changed_decision_and_fact_ids_produce_deterministic_off_golden_slot(self):
        structure = DecisionStructure(
            decision_id="D-999",
            decision_display="this decision",
            facts=(
                DecisionFactBinding(
                    "FX",
                    "beacon_reactivation_delay",
                    "Supplier Y requires 12 weeks to reactivate",
                ),
            ),
            relations=(),
        )
        profile1, trace1 = ProfileBinder().bind(
            template=supplier_resilience_capture_template(),
            structure=structure,
        )
        profile2, trace2 = ProfileBinder().bind(
            template=supplier_resilience_capture_template(),
            structure=structure,
        )
        self.assertEqual(profile1.slots[0].slot.subject_id, "FX")
        self.assertEqual(profile1.slots[0].slot.object_id, "D-999")
        self.assertTrue(profile1.slots[0].slot.id.startswith("RS-"))
        self.assertEqual(profile1.slots[0].slot.id, profile2.slots[0].slot.id)
        self.assertEqual(trace1.instantiated_profile_hash, trace2.instantiated_profile_hash)


if __name__ == "__main__":
    unittest.main()
