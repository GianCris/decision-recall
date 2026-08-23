from __future__ import annotations

from .domain import (
    CompositionState,
    CompositionValue,
    CurrentMatchRule,
    DecisionContract,
    HistoricalKnowledgeState,
    HistoricalRelation,
    NumericObservation,
    RelationType,
    RevisitRule,
    SafeReuseTargetSpec,
    ThresholdCondition,
    WorldEvent,
)


def supplier_resilience_contract() -> DecisionContract:
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
        knowledge_state=HistoricalKnowledgeState.ESTABLISHED,
        evidence_refs=("EV-R2",),
        authorization_policy_version="EP_V1",
    )
    c1 = CompositionState(
        id="C1",
        description="R2 alone was sufficient for the safe-reuse target",
        value=CompositionValue.T0_UNRESOLVED,
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
        historical_relations=(r1, r2),
        composition_states=(c1,),
        current_match_rules=(
            CurrentMatchRule(
                id="M1",
                historical_relation_id="R1",
                condition=stability,
                match_when_condition_true=False,
            ),
            CurrentMatchRule(
                id="M2",
                historical_relation_id="R2",
                condition=recovery_delay,
                match_when_condition_true=True,
            ),
        ),
        revisit_rules=(RevisitRule(id="RC1", condition=stability),),
    )


def golden_event(*, apex_rate: float = 0.987, days: int = 30, beacon_days: float = 70) -> WorldEvent:
    return WorldEvent(
        id="E-301",
        observations=(
            NumericObservation("apex_on_time_rate", apex_rate, window_days=days),
            NumericObservation("beacon_reactivation_days", beacon_days),
        ),
    )


def safe_reuse_target_v1() -> SafeReuseTargetSpec:
    return SafeReuseTargetSpec(
        id="SAFE_REUSE_RECORDED_RATIONALE",
        version="1",
        changed_match_rule_ids=("M1",),
        surviving_match_rule_ids=("M2",),
        revisit_rule_ids=("RC1",),
        limiting_composition_id="C1",
    )
