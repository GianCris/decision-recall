"""Frozen D-104 configuration/data. No authority-processing implementation."""
from datetime import datetime, timedelta, timezone

from ..domain import CompositionValue, HistoricalKnowledgeState, ProvenanceType
from ..golden import safe_reuse_target_v1, supplier_metric_specs, supplier_resilience_contract
from ..temporal import AuthorizedAssertion
from .capture import supplier_resilience_capture_template
from .definitions import (
    DecisionInstance, DecisionProfileDefinition, DecisionRegistry, DecisionSourceRecord,
    FactDisplay, ProductIdentity, RuleEvidenceSpec, SourceAdmission,
)

UTC = timezone.utc
T0 = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
COMMIT_ID = "COMMIT-D104-PRODUCT-V1"
EVALUATION_ID = "EV-901-PRODUCT-V1"


def d104_instance(*, decision_id: str = "D-104") -> DecisionInstance:
    return DecisionInstance(
        decision_id=decision_id,
        profile_id="SUPPLIER_RESILIENCE",
        profile_version="1",
        decision_time=T0,
        source_records=(
            DecisionSourceRecord(
                source_id="decision-note",
                content=(
                    "Decision D-104: keep Apex and Beacon active for six months. "
                    "Apex delivery performance has been materially unstable. "
                    "Apex instability materially influenced the decision."
                ),
                observed_at=T0 - timedelta(minutes=5),
            ),
            DecisionSourceRecord(
                source_id="supplier-record",
                content="Beacon requires roughly 10 weeks to reactivate.",
                observed_at=T0 - timedelta(minutes=5),
            ),
            DecisionSourceRecord(
                source_id="policy-record",
                content=(
                    "Current supplier policy: Apex is considered stable after on-time delivery "
                    "reaches 97% for at least 30 days. Beacon remains reaction capacity while "
                    "reactivation is at least 70 days. Review supplier redundancy once Apex "
                    "reaches 97% for at least 30 days."
                ),
                observed_at=T0 - timedelta(minutes=5),
            ),
        ),
    )



def d104_profile() -> DecisionProfileDefinition:
    return DecisionProfileDefinition(
        id="SUPPLIER_RESILIENCE", version="1",
        capture_template=supplier_resilience_capture_template(),
        contract_definition=supplier_resilience_contract(
            r2_state=HistoricalKnowledgeState.NOT_DURABLY_RECORDED,
            c1_value=CompositionValue.NOT_DURABLY_RECORDED,
        ),
        target=safe_reuse_target_v1(),
        metric_specs=tuple(supplier_metric_specs().values()),
        schema_version="SUPPLIER_METRICS_V1",
        source_admissions=tuple(SourceAdmission(source_id, ProvenanceType.CONTEMPORANEOUS_RECORD)
                                for source_id in ("decision-note", "supplier-record", "policy-record")),
        fact_displays=(
            FactDisplay("apex_delivery_instability", "decision-note", "Apex delivery performance has been materially unstable"),
            FactDisplay("beacon_reactivation_delay", "supplier-record", "Beacon requires roughly 10 weeks to reactivate"),
        ),
        rule_evidence=(
            RuleEvidenceSpec("M1", AuthorizedAssertion.CURRENT_MATCH_RULE, "policy-record",
                             "Apex is considered stable after on-time delivery reaches 97% for at least 30 days."),
            RuleEvidenceSpec("M2", AuthorizedAssertion.CURRENT_MATCH_RULE, "policy-record",
                             "Beacon remains reaction capacity while reactivation is at least 70 days."),
            RuleEvidenceSpec("RC1", AuthorizedAssertion.REVISIT_RULE, "policy-record",
                             "Review supplier redundancy once Apex reaches 97% for at least 30 days."),
        ),
    )


def d104_registry(*, decision_id: str = "D-104") -> DecisionRegistry:
    # Preserve the legacy wrapper's decision-id rebinding without case-id dispatch.
    return DecisionRegistry(
        profiles=(d104_profile(),), instances=(d104_instance(decision_id=decision_id),),
        identities=((decision_id, ProductIdentity(COMMIT_ID, EVALUATION_ID)),),
    )
