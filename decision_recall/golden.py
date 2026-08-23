from __future__ import annotations

from .domain import (
    CanonicalWorldState,
    Claim,
    ClaimType,
    CompositionKind,
    CompositionState,
    CompositionValue,
    CurrentMatchRule,
    DecisionContract,
    HistoricalKnowledgeState,
    HistoricalRelation,
    MetricSpec,
    NumericObservation,
    RelationType,
    RevisitRule,
    SafeReuseTargetSpec,
    TargetSupportBinding,
    ThresholdCondition,
    WorldEvent,
)


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


def supplier_resilience_contract(
    *,
    r2_state: HistoricalKnowledgeState = HistoricalKnowledgeState.ESTABLISHED,
    c1_value: CompositionValue = CompositionValue.T0_UNRESOLVED,
    c1_relation_ids: tuple[str, ...] = ("R2",),
    c1_target_id: str = "SAFE_REUSE_RECORDED_RATIONALE",
) -> DecisionContract:
    f1 = Claim(
        id="F1",
        claim_type=ClaimType.FACT,
        predicate_key="apex_delivery_instability",
        evidence_refs=("EV-F1",),
    )
    f2 = Claim(
        id="F2",
        claim_type=ClaimType.FACT,
        predicate_key="beacon_reactivation_delay",
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
    c1 = CompositionState(
        id="C1",
        kind=CompositionKind.SUFFICIENT_ALONE,
        relation_ids=c1_relation_ids,
        target_id=c1_target_id,
        value=c1_value,
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
            NumericObservation("apex_on_time_rate", 0.83, unit="ratio", window_days=56),
            NumericObservation("beacon_reactivation_days", 70, unit="days"),
        )
    )


def golden_event(*, apex_rate: float = 0.987, days: int = 30) -> WorldEvent:
    return WorldEvent(
        id="E-301",
        observations=(
            NumericObservation("apex_on_time_rate", apex_rate, unit="ratio", window_days=days),
        ),
    )


def beacon_recovery_event(*, beacon_days: float = 1) -> WorldEvent:
    return WorldEvent(
        id="E-BEACON-RECOVERY",
        observations=(NumericObservation("beacon_reactivation_days", beacon_days, unit="days"),),
    )


def safe_reuse_target_v1() -> SafeReuseTargetSpec:
    return SafeReuseTargetSpec(
        id="SAFE_REUSE_RECORDED_RATIONALE",
        version="1",
        changed_bindings=(TargetSupportBinding("R1", "M1"),),
        surviving_bindings=(TargetSupportBinding("R2", "M2"),),
        revisit_rule_ids=("RC1",),
        limiting_composition_id="C1",
    )
