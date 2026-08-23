from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Tuple

from .domain import (
    AuthorizationStatus,
    CanonicalWorldState,
    CompositionKind,
    CompositionValue,
    CurrentMatchRule,
    DecisionContract,
    EvidenceRecord,
    HistoricalKnowledgeState,
    HistoricalRelation,
    MatchResult,
    MetricSpec,
    NumericObservation,
    RelationCandidate,
    RelationSlot,
    RelationType,
    RevisitResult,
    SafeReuseResult,
    SafeReuseTargetSpec,
    TargetSupportBinding,
    WorldEvent,
)
from .policies import EvidencePolicy


class GuardViolation(ValueError):
    """Raised when a requested epistemic transition is not authorized."""


@dataclass(frozen=True)
class SafeReuseEvaluation:
    result: SafeReuseResult
    limiting_relations: Tuple[str, ...]
    reason_codes: Tuple[str, ...]


@dataclass(frozen=True)
class SemanticImpact:
    rechecked_rule_ids: Tuple[str, ...]
    changed_rule_ids: Tuple[str, ...]


def authorize_historical_role(
    *,
    slot: RelationSlot,
    candidate: RelationCandidate,
    evidence: Iterable[EvidenceRecord],
    policy: EvidencePolicy,
) -> HistoricalRelation:
    if slot.relation_type is not RelationType.HISTORICAL_SUPPORT:
        raise GuardViolation("slot is not a historical-support slot")
    if candidate.relation_type is not RelationType.HISTORICAL_SUPPORT:
        raise GuardViolation("candidate is not a historical-support candidate")
    if (
        candidate.subject_id != slot.subject_id
        or candidate.object_id != slot.object_id
        or candidate.relation_type != slot.relation_type
    ):
        raise GuardViolation("candidate does not fill this relation slot")

    available = tuple(evidence)
    decision = policy.authorize_historical_role(candidate=candidate, evidence=available)
    if decision.status is not AuthorizationStatus.AUTHORIZED:
        raise GuardViolation(f"evidence policy did not authorize historical role: {decision.reason_code}")
    if decision.authorized_as is not RelationType.HISTORICAL_SUPPORT:
        raise GuardViolation("policy authorization type mismatch")

    return HistoricalRelation(
        id=slot.id,
        relation_type=RelationType.HISTORICAL_SUPPORT,
        subject_id=slot.subject_id,
        object_id=slot.object_id,
        knowledge_state=HistoricalKnowledgeState.ESTABLISHED,
        evidence_refs=tuple(decision.evidence_refs),
        authorization_policy_version=decision.policy_version,
    )


def validate_observation(observation: NumericObservation, spec: MetricSpec) -> None:
    if observation.metric_key != spec.key:
        raise GuardViolation("metric spec key mismatch")
    if observation.unit != spec.unit:
        raise GuardViolation(
            f"metric {spec.key} requires unit {spec.unit}, got {observation.unit}"
        )
    if spec.minimum is not None and observation.value < spec.minimum:
        raise GuardViolation(f"metric {spec.key} is below allowed range")
    if spec.maximum is not None and observation.value > spec.maximum:
        raise GuardViolation(f"metric {spec.key} is above allowed range")
    if observation.window_days is not None and observation.window_days < 0:
        raise GuardViolation("window_days cannot be negative")


def validate_world_state(
    state: CanonicalWorldState,
    metric_specs: Mapping[str, MetricSpec],
) -> None:
    seen: set[str] = set()
    for observation in state.observations:
        if observation.metric_key in seen:
            raise GuardViolation(f"duplicate metric in world state: {observation.metric_key}")
        seen.add(observation.metric_key)
        spec = metric_specs.get(observation.metric_key)
        if spec is None:
            raise GuardViolation(f"unknown metric: {observation.metric_key}")
        validate_observation(observation, spec)


def apply_world_event(
    *,
    state: CanonicalWorldState,
    event: WorldEvent,
    metric_specs: Mapping[str, MetricSpec],
) -> CanonicalWorldState:
    validate_world_state(state, metric_specs)
    event_keys: set[str] = set()
    for observation in event.observations:
        if observation.metric_key in event_keys:
            raise GuardViolation(f"duplicate metric in event: {observation.metric_key}")
        event_keys.add(observation.metric_key)
        spec = metric_specs.get(observation.metric_key)
        if spec is None:
            raise GuardViolation(f"unknown metric: {observation.metric_key}")
        validate_observation(observation, spec)

    merged = {observation.metric_key: observation for observation in state.observations}
    for observation in event.observations:
        merged[observation.metric_key] = observation
    return CanonicalWorldState(observations=tuple(merged[key] for key in sorted(merged)))


def evaluate_current_match(rule: CurrentMatchRule, state: CanonicalWorldState) -> MatchResult:
    condition = rule.condition.evaluate(state)
    if condition is None:
        return MatchResult.UNKNOWN
    matches = condition if rule.match_when_condition_true else not condition
    return MatchResult.MATCHES if matches else MatchResult.DOES_NOT_MATCH


def evaluate_revisit(rule, state: CanonicalWorldState) -> RevisitResult:
    condition = rule.condition.evaluate(state)
    if condition is None:
        return RevisitResult.UNKNOWN
    return RevisitResult.TRIGGERED if condition else RevisitResult.NOT_TRIGGERED


def rules_requiring_recheck(contract: DecisionContract, event: WorldEvent) -> Tuple[str, ...]:
    observed_keys = {o.metric_key for o in event.observations}
    return tuple(
        rule.id
        for rule in (*contract.current_match_rules, *contract.revisit_rules)
        if rule.condition.metric_key in observed_keys
    )


def semantic_impact(
    *,
    contract: DecisionContract,
    event: WorldEvent,
    before_state: CanonicalWorldState,
    after_state: CanonicalWorldState,
) -> SemanticImpact:
    rechecked = rules_requiring_recheck(contract, event)
    changed: list[str] = []
    for rule in contract.current_match_rules:
        if rule.id in rechecked and evaluate_current_match(rule, before_state) != evaluate_current_match(rule, after_state):
            changed.append(rule.id)
    for rule in contract.revisit_rules:
        if rule.id in rechecked and evaluate_revisit(rule, before_state) != evaluate_revisit(rule, after_state):
            changed.append(rule.id)
    return SemanticImpact(tuple(rechecked), tuple(changed))


def _validate_binding(contract: DecisionContract, binding: TargetSupportBinding) -> HistoricalRelation:
    try:
        relation = contract.relation(binding.historical_relation_id)
        rule = contract.match_rule(binding.current_match_rule_id)
        claim = contract.claim(relation.subject_id)
    except StopIteration as exc:
        raise GuardViolation("target binding references missing contract entity") from exc
    if relation.relation_type is not RelationType.HISTORICAL_SUPPORT:
        raise GuardViolation("target binding relation is not HISTORICAL_SUPPORT")
    if relation.object_id != contract.id:
        raise GuardViolation("historical support points to a different decision")
    if rule.premise_id != claim.id:
        raise GuardViolation("current-match rule does not evaluate the support premise")
    if relation.subject_id != rule.premise_id:
        raise GuardViolation("historical support and current-match rule reference different premises")
    return relation


def validate_target_against_contract(
    *,
    contract: DecisionContract,
    target: SafeReuseTargetSpec,
) -> None:
    if not target.surviving_bindings:
        raise GuardViolation("safe-reuse target requires at least one surviving support binding")
    all_bindings = (*target.changed_bindings, *target.surviving_bindings)
    for binding in all_bindings:
        _validate_binding(contract, binding)
    for revisit_id in target.revisit_rule_ids:
        try:
            contract.revisit_rule(revisit_id)
        except StopIteration as exc:
            raise GuardViolation("target references missing revisit rule") from exc

    try:
        composition = contract.composition(target.limiting_composition_id)
    except StopIteration as exc:
        raise GuardViolation("target references missing composition") from exc
    if composition.target_id != target.id:
        raise GuardViolation("composition is scoped to a different TargetSpec")
    if composition.kind is not CompositionKind.SUFFICIENT_ALONE:
        raise GuardViolation("V1 safe-reuse target requires SUFFICIENT_ALONE composition")
    surviving_relation_ids = tuple(binding.historical_relation_id for binding in target.surviving_bindings)
    if composition.relation_ids != surviving_relation_ids:
        raise GuardViolation("composition does not concern exactly the surviving support relations")


def evaluate_safe_reuse(
    *,
    contract: DecisionContract,
    match_results: Dict[str, MatchResult],
    revisit_results: Dict[str, RevisitResult],
    target: SafeReuseTargetSpec,
) -> SafeReuseEvaluation:
    validate_target_against_contract(contract=contract, target=target)

    def require_match(rule_id: str) -> MatchResult:
        if rule_id not in match_results:
            raise GuardViolation(f"missing current-match result for target rule {rule_id}")
        return match_results[rule_id]

    def require_revisit(rule_id: str) -> RevisitResult:
        if rule_id not in revisit_results:
            raise GuardViolation(f"missing revisit result for target rule {rule_id}")
        return revisit_results[rule_id]

    changed_states = tuple(require_match(binding.current_match_rule_id) for binding in target.changed_bindings)
    surviving_states = tuple(require_match(binding.current_match_rule_id) for binding in target.surviving_bindings)
    revisit_states = tuple(require_revisit(rule_id) for rule_id in target.revisit_rule_ids)

    if any(state is MatchResult.UNKNOWN for state in (*changed_states, *surviving_states)):
        return SafeReuseEvaluation(
            result=SafeReuseResult.INSUFFICIENT_EVIDENCE,
            limiting_relations=(),
            reason_codes=("TARGET_CURRENT_MATCH_UNKNOWN",),
        )
    if any(state is RevisitResult.UNKNOWN for state in revisit_states):
        return SafeReuseEvaluation(
            result=SafeReuseResult.INSUFFICIENT_EVIDENCE,
            limiting_relations=(),
            reason_codes=("TARGET_REVISIT_STATE_UNKNOWN",),
        )

    relevant_change = (
        any(state is MatchResult.DOES_NOT_MATCH for state in changed_states)
        or any(state is RevisitResult.TRIGGERED for state in revisit_states)
    )
    if not relevant_change:
        return SafeReuseEvaluation(
            result=SafeReuseResult.REUSE_AUTHORIZED,
            limiting_relations=(),
            reason_codes=("NO_TARGET_RELEVANT_CHANGE",),
        )

    surviving_relations = tuple(
        contract.relation(binding.historical_relation_id)
        for binding in target.surviving_bindings
    )
    if any(relation.knowledge_state is not HistoricalKnowledgeState.ESTABLISHED for relation in surviving_relations):
        return SafeReuseEvaluation(
            result=SafeReuseResult.REUSE_NOT_AUTHORIZED,
            limiting_relations=tuple(relation.id for relation in surviving_relations if relation.knowledge_state is not HistoricalKnowledgeState.ESTABLISHED),
            reason_codes=("SURVIVING_HISTORICAL_ROLE_NOT_ESTABLISHED",),
        )

    if any(state is MatchResult.DOES_NOT_MATCH for state in surviving_states):
        return SafeReuseEvaluation(
            result=SafeReuseResult.REUSE_NOT_AUTHORIZED,
            limiting_relations=tuple(binding.historical_relation_id for binding in target.surviving_bindings),
            reason_codes=("REQUIRED_SURVIVING_SUPPORT_DOES_NOT_MATCH",),
        )

    composition = contract.composition(target.limiting_composition_id)
    if composition.value is CompositionValue.ESTABLISHED_TRUE:
        return SafeReuseEvaluation(
            result=SafeReuseResult.REUSE_AUTHORIZED,
            limiting_relations=(),
            reason_codes=("REQUIRED_COMPOSITION_ESTABLISHED_TRUE",),
        )
    if composition.value is CompositionValue.ESTABLISHED_FALSE:
        return SafeReuseEvaluation(
            result=SafeReuseResult.REUSE_NOT_AUTHORIZED,
            limiting_relations=(composition.id,),
            reason_codes=("REQUIRED_COMPOSITION_ESTABLISHED_FALSE",),
        )
    if composition.value is CompositionValue.T0_UNRESOLVED:
        return SafeReuseEvaluation(
            result=SafeReuseResult.REUSE_NOT_AUTHORIZED,
            limiting_relations=(composition.id,),
            reason_codes=("REQUIRED_COMPOSITION_T0_UNRESOLVED",),
        )
    return SafeReuseEvaluation(
        result=SafeReuseResult.INSUFFICIENT_EVIDENCE,
        limiting_relations=(composition.id,),
        reason_codes=("REQUIRED_COMPOSITION_NOT_DURABLY_KNOWN",),
    )
