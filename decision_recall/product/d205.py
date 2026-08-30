"""Authored rollback example, not provider evidence or an external-system feed.

Configuration/data only. The compiler is supplied to the existing shared lifecycle;
tests use explicitly labelled candidate fixtures, never a claimed Gemini execution.
"""
from datetime import datetime, timedelta, timezone

from ..domain import (
    Claim, ClaimType, CompositionKind, CompositionState, CompositionValue,
    CurrentMatchRule, DecisionContract, HistoricalKnowledgeState, HistoricalRelation,
    MetricSpec, NumericObservation, ProvenanceType, RelationType, RevisitRule,
    SafeReuseTargetSpec, TargetRef, TargetSupportBinding, ThresholdCondition,
)
from ..temporal import AuthorizedAssertion, RawWorldEvidence, TemporalReference, source_hash
from .capture import CaptureProfileTemplate, CaptureSlotTemplate
from .definitions import (
    DecisionInstance, DecisionProfileDefinition, DecisionSourceRecord, FactDisplay,
    ProductIdentity, RuleEvidenceSpec, SourceAdmission,
)

T0 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
PROFILE_ID = "RELEASE_ROLLBACK_REUSE"
TARGET_ID = "REPEAT_RECORDED_ROLLBACK"
IDENTITY = ProductIdentity("COMMIT-D205-V1", "EVAL-D205-V1", "D205-V1")


def d205_instance() -> DecisionInstance:
    return DecisionInstance(
        decision_id="D-205", profile_id=PROFILE_ID, profile_version="1", decision_time=T0,
        source_records=(
            DecisionSourceRecord(
                "incident-record",
                "Decision D-205: roll back Orion v42 to Orion v41. "
                "Orion v42 had a 5% request error rate over one day. "
                "The elevated Orion v42 errors materially influenced the rollback decision.",
                T0 - timedelta(minutes=5),
            ),
            DecisionSourceRecord(
                "recovery-record",
                "Orion v41 passed every restore attempt in a one-day recovery rehearsal.",
                T0 - timedelta(minutes=5),
            ),
            DecisionSourceRecord(
                "rollback-policy",
                "Treat a release request error rate above 2% over at least one day as elevated. "
                "A recovery artifact is ready when its restore success rate is at least 99% over at least one day. "
                "Review rollback reuse when restore success falls below 99% over at least one day.",
                T0 - timedelta(minutes=5),
            ),
        ),
    )


def d205_profile() -> DecisionProfileDefinition:
    error_condition = ThresholdCondition("release_error_rate", ">", 0.02, 1)
    recovery_condition = ThresholdCondition("rollback_restore_success_rate", ">=", 0.99, 1)
    return DecisionProfileDefinition(
        id=PROFILE_ID, version="1",
        capture_template=CaptureProfileTemplate(
            "ROLLBACK_RECOVERY_CAPTURE", "1", 1,
            (CaptureSlotTemplate(
                "RECOVERY_READINESS_HISTORICAL_ROLE", RelationType.HISTORICAL_SUPPORT,
                "recovery_rehearsal_passed", True, True, 100,
                "Did the fact that {subject_display} materially influence {decision_display}?",
            ),),
        ),
        contract_definition=DecisionContract(
            id="ROLLBACK_CONTEXT", action="rollback_orion_v42_to_v41",
            claims=(
                Claim("F201", ClaimType.FACT, "elevated_release_errors", "release_error_rate", ("PRE-F201-D205-V1",)),
                Claim("F202", ClaimType.FACT, "recovery_rehearsal_passed", "rollback_restore_success_rate", ("PRE-F202-D205-V1",)),
            ),
            historical_relations=(
                HistoricalRelation("R201", RelationType.HISTORICAL_SUPPORT, "F201", "ROLLBACK_CONTEXT", HistoricalKnowledgeState.NOT_DURABLY_RECORDED, (), ""),
                HistoricalRelation("R202", RelationType.HISTORICAL_SUPPORT, "F202", "ROLLBACK_CONTEXT", HistoricalKnowledgeState.NOT_DURABLY_RECORDED, (), ""),
            ),
            composition_states=(CompositionState(
                "C201", CompositionKind.SUFFICIENT_ALONE, ("R202",), TargetRef(TARGET_ID, "1"),
                CompositionValue.NOT_DURABLY_RECORDED,
            ),),
            current_match_rules=(
                CurrentMatchRule("M201", "F201", error_condition, True),
                CurrentMatchRule("M202", "F202", recovery_condition, True),
            ),
            revisit_rules=(RevisitRule(
                "RC201", ThresholdCondition("rollback_restore_success_rate", "<", 0.99, 1),
            ),),
        ),
        target=SafeReuseTargetSpec(
            TARGET_ID, "1", (TargetSupportBinding("R201", "M201"),),
            (TargetSupportBinding("R202", "M202"),), ("RC201",), "C201",
        ),
        metric_specs=(
            MetricSpec("release_error_rate", "ratio", 0.0, 1.0),
            MetricSpec("rollback_restore_success_rate", "ratio", 0.0, 1.0),
        ),
        schema_version="ROLLBACK_METRICS_V1",
        source_admissions=tuple(
            SourceAdmission(source_id, ProvenanceType.CONTEMPORANEOUS_RECORD)
            for source_id in ("incident-record", "recovery-record", "rollback-policy")
        ),
        fact_displays=(
            FactDisplay("elevated_release_errors", "incident-record", "Orion v42 had a 5% request error rate over one day"),
            FactDisplay("recovery_rehearsal_passed", "recovery-record", "Orion v41 passed every restore attempt in a one-day recovery rehearsal"),
        ),
        rule_evidence=(
            RuleEvidenceSpec("M201", AuthorizedAssertion.CURRENT_MATCH_RULE, "rollback-policy",
                             "Treat a release request error rate above 2% over at least one day as elevated."),
            RuleEvidenceSpec("M202", AuthorizedAssertion.CURRENT_MATCH_RULE, "rollback-policy",
                             "A recovery artifact is ready when its restore success rate is at least 99% over at least one day."),
            RuleEvidenceSpec("RC201", AuthorizedAssertion.REVISIT_RULE, "rollback-policy",
                             "Review rollback reuse when restore success falls below 99% over at least one day."),
        ),
        decision_display="the decision to roll back Orion v42 to Orion v41",
    )


def d205_later_evidence() -> tuple[RawWorldEvidence, ...]:
    """Explicit example input, separate from T0 records and never auto-ingested."""
    records = (
        ("WE-D205-ERROR", "release_error_rate", 0.06,
         "A supplied one-day validation record for Orion v42 reports a 6% request error rate."),
        ("WE-D205-RESTORE", "rollback_restore_success_rate", 0.8,
         "After a schema change, a supplied one-day Orion v41 recovery rehearsal restored four of five attempts."),
    )
    return tuple(RawWorldEvidence(
        id=record_id, content=text, source_id="supplied-validation-record",
        source_span="complete supplied example record", source_content_hash=source_hash(text),
        provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
        temporal_reference=TemporalReference.point(T1),
        observations=(NumericObservation(metric, value, "ratio", 1),),
    ) for record_id, metric, value, text in records)
