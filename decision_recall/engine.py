from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Iterable, Mapping, Tuple

from .domain import (
    AuthorizationStatus,
    CanonicalWorldState,
    CompositionCandidate,
    CompositionKind,
    CompositionState,
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
    ValidatedDecisionContract,
    WorldEvent,
)
from .policies import CompositionPolicy, EvidencePolicy


class GuardViolation(ValueError):
    """Raised when a requested epistemic transition is not authorized."""


@dataclass(frozen=True)
class SafeReuseEvaluation:
    result: SafeReuseResult
    limiting_requirements: Tuple[str, ...]
    reason_codes: Tuple[str, ...]


@dataclass(frozen=True)
class TargetEvaluation:
    safe_reuse: SafeReuseEvaluation
    current_matches: Tuple[Tuple[str, MatchResult], ...]
    review_states: Tuple[Tuple[str, RevisitResult], ...]


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

    try:
        decision = policy.authorize_historical_role(
            candidate=candidate,
            evidence=tuple(evidence),
        )
    except ValueError as exc:
        raise GuardViolation(str(exc)) from exc
    if decision.status is not AuthorizationStatus.AUTHORIZED:
        raise GuardViolation(
            f"evidence policy did not authorize historical role: {decision.reason_code}"
        )
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


def authorize_composition(
    *,
    candidate: CompositionCandidate,
    evidence: Iterable[EvidenceRecord],
    policy: CompositionPolicy,
) -> CompositionState:
    try:
        decision = policy.authorize(candidate=candidate, evidence=tuple(evidence))
    except ValueError as exc:
        raise GuardViolation(str(exc)) from exc
    if decision.status is not AuthorizationStatus.AUTHORIZED:
        raise GuardViolation(
            f"composition policy did not authorize composition: {decision.reason_code}"
        )
    if decision.authorized_value is not candidate.asserted_value:
        raise GuardViolation("composition authorization value mismatch")
    return CompositionState(
        id=candidate.id,
        kind=candidate.kind,
        relation_ids=candidate.relation_ids,
        target_ref=candidate.target_ref,
        value=candidate.asserted_value,
        authorization=decision,
    )


def _ensure_unique(name: str, ids: Tuple[str, ...]) -> None:
    if len(ids) != len(set(ids)):
        raise GuardViolation(f"duplicate {name} id")


def _validate_condition(rule_name: str, condition) -> None:
    if condition.operator not in {">=", "<=", ">", "<", "=="}:
        raise GuardViolation(f"{rule_name} uses unsupported operator")
    if condition.minimum_window_days is not None and condition.minimum_window_days < 0:
        raise GuardViolation(f"{rule_name} minimum_window_days cannot be negative")
    if not isfinite(condition.threshold):
        raise GuardViolation(f"{rule_name} threshold must be finite")


def validate_contract(contract: DecisionContract) -> ValidatedDecisionContract:
    collections = {
        "claim": tuple(item.id for item in contract.claims),
        "historical relation": tuple(item.id for item in contract.historical_relations),
        "composition": tuple(item.id for item in contract.composition_states),
        "current-match rule": tuple(item.id for item in contract.current_match_rules),
        "revisit rule": tuple(item.id for item in contract.revisit_rules),
    }
    for name, ids in collections.items():
        _ensure_unique(name, ids)

    all_entity_ids = (contract.id, *(item for ids in collections.values() for item in ids))
    if len(all_entity_ids) != len(set(all_entity_ids)):
        raise GuardViolation("canonical entity ids must be globally unique within a contract")

    claims = {claim.id: claim for claim in contract.claims}
    relations = {relation.id: relation for relation in contract.historical_relations}

    relation_semantics = tuple(
        (relation.relation_type, relation.subject_id, relation.object_id)
        for relation in contract.historical_relations
    )
    if len(relation_semantics) != len(set(relation_semantics)):
        raise GuardViolation("duplicate semantic historical relation")

    for claim in contract.claims:
        if not claim.predicate_key or not claim.current_metric_key:
            raise GuardViolation("claim requires predicate_key and current_metric_key")
        if not claim.evidence_refs:
            raise GuardViolation(f"claim {claim.id} lacks evidence refs")

    for relation in contract.historical_relations:
        if relation.relation_type is not RelationType.HISTORICAL_SUPPORT:
            raise GuardViolation("V1 contract only supports HISTORICAL_SUPPORT relations")
        if relation.subject_id not in claims:
            raise GuardViolation(f"relation {relation.id} references missing claim")
        if relation.object_id != contract.id:
            raise GuardViolation(f"relation {relation.id} points to a different decision")
        if relation.knowledge_state is HistoricalKnowledgeState.ESTABLISHED:
            if not relation.evidence_refs or not relation.authorization_policy_version:
                raise GuardViolation(
                    f"established relation {relation.id} requires evidence and policy authorization"
                )

    for composition in contract.composition_states:
        if not composition.relation_ids:
            raise GuardViolation(f"composition {composition.id} requires relation refs")
        if any(ref not in relations for ref in composition.relation_ids):
            raise GuardViolation(f"composition {composition.id} references missing relation")
        if not composition.target_ref.id or not composition.target_ref.version:
            raise GuardViolation(f"composition {composition.id} requires versioned TargetRef")
        if composition.kind is CompositionKind.SUFFICIENT_ALONE and len(composition.relation_ids) != 1:
            raise GuardViolation("SUFFICIENT_ALONE composition must concern exactly one relation")
        established = composition.value in (
            CompositionValue.ESTABLISHED_TRUE,
            CompositionValue.ESTABLISHED_FALSE,
        )
        if established:
            auth = composition.authorization
            if auth is None:
                raise GuardViolation(
                    f"established composition {composition.id} requires authorization record"
                )
            if auth.candidate_id != composition.id:
                raise GuardViolation("composition authorization candidate_id mismatch")
            if auth.status is not AuthorizationStatus.AUTHORIZED:
                raise GuardViolation("established composition authorization is not AUTHORIZED")
            if auth.authorized_value is not composition.value:
                raise GuardViolation("composition value differs from authorized value")
            if not auth.evidence_refs or not auth.policy_version:
                raise GuardViolation("composition authorization requires evidence and policy version")
        elif composition.authorization is not None:
            raise GuardViolation("unresolved composition must not carry TRUE/FALSE authorization")

    for rule in contract.current_match_rules:
        claim = claims.get(rule.premise_id)
        if claim is None:
            raise GuardViolation(f"current-match rule {rule.id} references missing premise")
        if claim.current_metric_key != rule.condition.metric_key:
            raise GuardViolation(
                f"current-match rule {rule.id} metric does not match claim current_metric_key"
            )
        _validate_condition(rule.id, rule.condition)

    for rule in contract.revisit_rules:
        _validate_condition(rule.id, rule.condition)

    return ValidatedDecisionContract(contract=contract)


def validate_observation(observation: NumericObservation, spec: MetricSpec) -> None:
    if observation.metric_key != spec.key:
        raise GuardViolation("metric spec key mismatch")
    if observation.unit != spec.unit:
        raise GuardViolation(
            f"metric {spec.key} requires unit {spec.unit}, got {observation.unit}"
        )
    if not isfinite(observation.value):
        raise GuardViolation(f"metric {spec.key} value must be finite")
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
    """Apply a typed event delta. Event authorization itself is introduced with M2."""
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
        merged[observation.metric_key] = replace(observation, source_event_id=event.id)
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


def evaluate_review(
    *,
    contract: ValidatedDecisionContract,
    world_state: CanonicalWorldState,
    target: SafeReuseTargetSpec,
) -> Tuple[Tuple[str, RevisitResult], ...]:
    raw = contract.contract
    return tuple(
        (rule_id, evaluate_revisit(raw.revisit_rule(rule_id), world_state))
        for rule_id in target.revisit_rule_ids
    )


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
        if (
            rule.id in rechecked
            and evaluate_current_match(rule, before_state)
            != evaluate_current_match(rule, after_state)
        ):
            changed.append(rule.id)
    for rule in contract.revisit_rules:
        if (
            rule.id in rechecked
            and evaluate_revisit(rule, before_state)
            != evaluate_revisit(rule, after_state)
        ):
            changed.append(rule.id)
    return SemanticImpact(tuple(rechecked), tuple(changed))


def _validate_binding(
    contract: DecisionContract,
    binding: TargetSupportBinding,
) -> HistoricalRelation:
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
    if rule.premise_id != claim.id or relation.subject_id != rule.premise_id:
        raise GuardViolation("historical support and current-match rule reference different premises")
    if claim.current_metric_key != rule.condition.metric_key:
        raise GuardViolation("bound current-match rule evaluates the wrong metric for its claim")
    return relation


def validate_target_against_contract(
    *,
    contract: ValidatedDecisionContract,
    target: SafeReuseTargetSpec,
) -> None:
    raw = contract.contract
    if not target.surviving_bindings:
        raise GuardViolation("safe-reuse target requires at least one surviving support binding")

    all_bindings = (*target.changed_bindings, *target.surviving_bindings)
    binding_pairs = tuple(
        (binding.historical_relation_id, binding.current_match_rule_id)
        for binding in all_bindings
    )
    if len(binding_pairs) != len(set(binding_pairs)):
        raise GuardViolation("TargetSpec contains duplicate support bindings")
    changed_relations = {binding.historical_relation_id for binding in target.changed_bindings}
    surviving_relations = {binding.historical_relation_id for binding in target.surviving_bindings}
    if changed_relations & surviving_relations:
        raise GuardViolation("same historical relation cannot be both changed and surviving")

    for binding in all_bindings:
        _validate_binding(raw, binding)
    if len(target.revisit_rule_ids) != len(set(target.revisit_rule_ids)):
        raise GuardViolation("TargetSpec contains duplicate revisit rule ids")
    for revisit_id in target.revisit_rule_ids:
        try:
            raw.revisit_rule(revisit_id)
        except StopIteration as exc:
            raise GuardViolation("target references missing revisit rule") from exc

    try:
        composition = raw.composition(target.limiting_composition_id)
    except StopIteration as exc:
        raise GuardViolation("target references missing composition") from exc
    if composition.target_ref != target.ref:
        raise GuardViolation("composition is scoped to a different TargetSpec id/version")
    if composition.kind is not CompositionKind.SUFFICIENT_ALONE:
        raise GuardViolation("V1 safe-reuse target requires SUFFICIENT_ALONE composition")
    surviving_relation_ids = tuple(
        binding.historical_relation_id for binding in target.surviving_bindings
    )
    if composition.relation_ids != surviving_relation_ids:
        raise GuardViolation(
            "composition does not concern exactly the surviving support relations"
        )


def _evaluate_safe_reuse_from_matches(
    *,
    contract: ValidatedDecisionContract,
    match_results: Mapping[str, MatchResult],
    target: SafeReuseTargetSpec,
) -> SafeReuseEvaluation:
    raw = contract.contract

    def require_match(rule_id: str) -> MatchResult:
        if rule_id not in match_results:
            raise GuardViolation(f"missing current-match result for target rule {rule_id}")
        return match_results[rule_id]

    all_bindings = (*target.changed_bindings, *target.surviving_bindings)
    bound_relations = tuple(
        raw.relation(binding.historical_relation_id) for binding in all_bindings
    )
    unestablished = tuple(
        relation.id
        for relation in bound_relations
        if relation.knowledge_state is not HistoricalKnowledgeState.ESTABLISHED
    )
    if unestablished:
        return SafeReuseEvaluation(
            result=SafeReuseResult.REUSE_NOT_AUTHORIZED,
            limiting_requirements=unestablished,
            reason_codes=("TARGET_HISTORICAL_ROLE_NOT_ESTABLISHED",),
        )

    changed_states = tuple(
        require_match(binding.current_match_rule_id) for binding in target.changed_bindings
    )
    surviving_states = tuple(
        require_match(binding.current_match_rule_id) for binding in target.surviving_bindings
    )

    if any(state is MatchResult.UNKNOWN for state in (*changed_states, *surviving_states)):
        return SafeReuseEvaluation(
            result=SafeReuseResult.INSUFFICIENT_EVIDENCE,
            limiting_requirements=(),
            reason_codes=("TARGET_CURRENT_MATCH_UNKNOWN",),
        )

    if any(state is MatchResult.DOES_NOT_MATCH for state in surviving_states):
        return SafeReuseEvaluation(
            result=SafeReuseResult.REUSE_NOT_AUTHORIZED,
            limiting_requirements=tuple(
                binding.historical_relation_id for binding in target.surviving_bindings
            ),
            reason_codes=("REQUIRED_SURVIVING_SUPPORT_DOES_NOT_MATCH",),
        )

    relevant_support_change = any(
        state is MatchResult.DOES_NOT_MATCH for state in changed_states
    )
    if not relevant_support_change:
        return SafeReuseEvaluation(
            result=SafeReuseResult.REUSE_AUTHORIZED,
            limiting_requirements=(),
            reason_codes=("NO_TARGET_SUPPORT_INVALIDATION",),
        )

    composition = raw.composition(target.limiting_composition_id)
    if composition.value is CompositionValue.ESTABLISHED_TRUE:
        return SafeReuseEvaluation(
            result=SafeReuseResult.REUSE_AUTHORIZED,
            limiting_requirements=(),
            reason_codes=("REQUIRED_COMPOSITION_ESTABLISHED_TRUE",),
        )
    if composition.value is CompositionValue.ESTABLISHED_FALSE:
        return SafeReuseEvaluation(
            result=SafeReuseResult.REUSE_NOT_AUTHORIZED,
            limiting_requirements=(composition.id,),
            reason_codes=("REQUIRED_COMPOSITION_ESTABLISHED_FALSE",),
        )
    if composition.value is CompositionValue.T0_UNRESOLVED:
        return SafeReuseEvaluation(
            result=SafeReuseResult.REUSE_NOT_AUTHORIZED,
            limiting_requirements=(composition.id,),
            reason_codes=("REQUIRED_COMPOSITION_T0_UNRESOLVED",),
        )
    return SafeReuseEvaluation(
        result=SafeReuseResult.INSUFFICIENT_EVIDENCE,
        limiting_requirements=(composition.id,),
        reason_codes=("REQUIRED_COMPOSITION_NOT_DURABLY_KNOWN",),
    )


def evaluate_target(
    *,
    contract: ValidatedDecisionContract,
    world_state: CanonicalWorldState,
    target: SafeReuseTargetSpec,
) -> TargetEvaluation:
    if not isinstance(contract, ValidatedDecisionContract):
        raise GuardViolation("evaluation requires ValidatedDecisionContract")
    validate_target_against_contract(contract=contract, target=target)
    raw = contract.contract
    current_matches = tuple(
        (
            binding.current_match_rule_id,
            evaluate_current_match(raw.match_rule(binding.current_match_rule_id), world_state),
        )
        for binding in (*target.changed_bindings, *target.surviving_bindings)
    )
    if len({rule_id for rule_id, _ in current_matches}) != len(current_matches):
        raise GuardViolation("TargetSpec evaluates the same current-match rule more than once")
    match_map = dict(current_matches)
    safe_reuse = _evaluate_safe_reuse_from_matches(
        contract=contract,
        match_results=match_map,
        target=target,
    )
    review_states = evaluate_review(
        contract=contract,
        world_state=world_state,
        target=target,
    )
    return TargetEvaluation(
        safe_reuse=safe_reuse,
        current_matches=current_matches,
        review_states=review_states,
    )


def evaluate_safe_reuse(*args, **kwargs):
    raise GuardViolation(
        "evaluate_safe_reuse() no longer accepts caller-supplied epistemic results; use evaluate_target()"
    )
