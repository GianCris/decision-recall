from __future__ import annotations

from .domain import (
    CanonicalWorldState,
    Claim,
    ClaimType,
    CompositionCandidate,
    CompositionKind,
    CompositionState,
    CompositionValue,
    CurrentMatchRule,
    DecisionContract,
    EvidenceRecord,
    HistoricalKnowledgeState,
    HistoricalRelation,
    MetricSpec,
    NumericObservation,
    ProvenanceType,
    RelationType,
    RevisitRule,
    SafeReuseTargetSpec,
    TargetRef,
    TargetSupportBinding,
    ThresholdCondition,
    WorldEvent,
)
from .engine import authorize_composition
from .policies import composition_policy_v1


TARGET_ID = "SAFE_REUSE_RECORDED_RATIONALE"
TARGET_VERSION = "1"


def supplier_metric_specs() -> dict[str, MetricSpec]:
    return {
        "apex_on_time_rate": MetricSpec(
            key="apex_on_time_rate",
            unit="ratio",
            minimum=0.0,
            maximum=1.0,
        ),
        "beacon_reactivation_days": MetricSpec(
            key="beacon_reactivation_days",
            unit="days",
            minimum=0.0,
        ),
        "beacon_invoice_template_version": MetricSpec(
            key="beacon_invoice_template_version",
            unit="version",
            minimum=0.0,
        ),
    }


def _composition_state(
    *,
    value: CompositionValue,
    relation_ids: tuple[str, ...],
    target_ref: TargetRef,
) -> CompositionState:
    if value not in (
        CompositionValue.ESTABLISHED_TRUE,
        CompositionValue.ESTABLISHED_FALSE,
    ):
        return CompositionState(
            id="C1",
            kind=CompositionKind.SUFFICIENT_ALONE,
            relation_ids=relation_ids,
            target_ref=target_ref,
            value=value,
        )

    statement = (
        "At decision time, preserving Beacon reaction capacity alone was explicitly "
        + ("sufficient." if value is CompositionValue.ESTABLISHED_TRUE else "not sufficient.")
    )
    evidence = EvidenceRecord(
        id="EV-C1",
        content=statement,
        provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
    )
    candidate = CompositionCandidate(
        id="C1",
        kind=CompositionKind.SUFFICIENT_ALONE,
        relation_ids=relation_ids,
        target_ref=target_ref,
        asserted_value=value,
        evidence_refs=(evidence.id,),
    )
    return authorize_composition(
        candidate=candidate,
        evidence=(evidence,),
        policy=composition_policy_v1(),
    )


def supplier_resilience_contract(
    *,
    r2_state: HistoricalKnowledgeState = HistoricalKnowledgeState.ESTABLISHED,
    c1_value: CompositionValue = CompositionValue.T0_UNRESOLVED,
    c1_relation_ids: tuple[str, ...] = ("R2",),
    c1_target_id: str = TARGET_ID,
    c1_target_version: str = TARGET_VERSION,
    f1_current_metric_key: str = "apex_on_time_rate",
) -> DecisionContract:
    f1 = Claim(
        id="F1",
        claim_type=ClaimType.FACT,
        predicate_key="apex_delivery_instability",
        current_metric_key=f1_current_metric_key,
        evidence_refs=("EV-F1",),
    )
    f2 = Claim(
        id="F2",
        claim_type=ClaimType.FACT,
        predicate_key="beacon_reactivation_delay",
        current_metric_key="beacon_reactivation_days",
        evidence_refs=("EV-F2",),
    )
    r1 = HistoricalRelation(
        id="R1",
        relation_type=RelationType.HISTORICAL_SUPPORT,
        subject_id="F1",
        object_id="D-104",
        knowledge_state=HistoricalKnowledgeState.ESTABLISHED,
        evidence_refs=("EV-R1",),
        authorization_policy_version="EP_V1",
    )
    r2 = HistoricalRelation(
        id="R2",
        relation_type=RelationType.HISTORICAL_SUPPORT,
        subject_id="F2",
        object_id="D-104",
        knowledge_state=r2_state,
        evidence_refs=("EV-R2",) if r2_state is HistoricalKnowledgeState.ESTABLISHED else (),
        authorization_policy_version="EP_V1" if r2_state is HistoricalKnowledgeState.ESTABLISHED else "",
    )
    c1 = _composition_state(
        value=c1_value,
        relation_ids=c1_relation_ids,
        target_ref=TargetRef(c1_target_id, c1_target_version),
    )
    stability = ThresholdCondition(
        metric_key="apex_on_time_rate",
        operator=">=",
        threshold=0.97,
        minimum_window_days=30,
    )
    recovery_delay = ThresholdCondition(
        metric_key="beacon_reactivation_days",
        operator=">=",
        threshold=70,
    )
    return DecisionContract(
        id="D-104",
        action="keep_apex_and_beacon_active",
        claims=(f1, f2),
        historical_relations=(r1, r2),
        composition_states=(c1,),
        current_match_rules=(
            CurrentMatchRule(
                id="M1",
                premise_id="F1",
                condition=stability,
                match_when_condition_true=False,
            ),
            CurrentMatchRule(
                id="M2",
                premise_id="F2",
                condition=recovery_delay,
                match_when_condition_true=True,
            ),
        ),
        revisit_rules=(RevisitRule(id="RC1", condition=stability),),
    )


def initial_world_state() -> CanonicalWorldState:
    return CanonicalWorldState(
        observations=(
            NumericObservation(
                "apex_on_time_rate",
                0.83,
                unit="ratio",
                window_days=56,
                source_event_id="INITIAL-SNAPSHOT",
            ),
            NumericObservation(
                "beacon_reactivation_days",
                70,
                unit="days",
                source_event_id="INITIAL-SNAPSHOT",
            ),
        )
    )


def golden_event(*, apex_rate: float = 0.987, days: int = 30) -> WorldEvent:
    return WorldEvent(
        id="E-301",
        observations=(
            NumericObservation(
                "apex_on_time_rate",
                apex_rate,
                unit="ratio",
                window_days=days,
            ),
        ),
    )


def beacon_recovery_event(*, beacon_days: float = 1) -> WorldEvent:
    return WorldEvent(
        id="E-BEACON-RECOVERY",
        observations=(
            NumericObservation("beacon_reactivation_days", beacon_days, unit="days"),
        ),
    )


def safe_reuse_target_v1() -> SafeReuseTargetSpec:
    return SafeReuseTargetSpec(
        id=TARGET_ID,
        version=TARGET_VERSION,
        changed_bindings=(TargetSupportBinding("R1", "M1"),),
        surviving_bindings=(TargetSupportBinding("R2", "M2"),),
        revisit_rule_ids=("RC1",),
        limiting_composition_id="C1",
    )
