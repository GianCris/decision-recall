from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

from .domain import (
    AuthorizationDecision,
    AuthorizationStatus,
    CompositionValue,
    CurrentMatchRule,
    DecisionContract,
    EvidenceRecord,
    HistoricalKnowledgeState,
    HistoricalRelation,
    MatchResult,
    RelationCandidate,
    RelationSlot,
    RelationType,
    RevisitResult,
    SafeReuseResult,
    SafeReuseTargetSpec,
    WorldEvent,
)


class GuardViolation(ValueError):
    """Raised when a requested epistemic transition is not authorized."""


@dataclass(frozen=True)
class SafeReuseEvaluation:
    result: SafeReuseResult
    limiting_relations: Tuple[str, ...]
    reason_codes: Tuple[str, ...]


def authorize_historical_role(
    *,
    slot: RelationSlot,
    candidate: RelationCandidate,
    evidence: Iterable[EvidenceRecord],
    authorization: AuthorizationDecision,
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
    if authorization.candidate_id != candidate.id:
        raise GuardViolation("authorization belongs to a different candidate")

    evidence_by_id = {e.id: e for e in evidence}
    if not candidate.evidence_refs:
        raise GuardViolation("candidate has no supporting evidence")
    if set(candidate.evidence_refs) != set(authorization.evidence_refs):
        raise GuardViolation("candidate evidence does not match authorization evidence")
    if any(ref not in evidence_by_id for ref in candidate.evidence_refs):
        raise GuardViolation("candidate references unavailable evidence")
    if authorization.status is not AuthorizationStatus.AUTHORIZED:
        raise GuardViolation("authorization status is not AUTHORIZED")
    if authorization.authorized_as is not RelationType.HISTORICAL_SUPPORT:
        raise GuardViolation("authorization does not authorize HISTORICAL_SUPPORT")
    if set(authorization.evidence_refs) != set(evidence_by_id):
        raise GuardViolation("provided evidence set does not match authorization evidence refs")

    return HistoricalRelation(
        id=slot.id,
        relation_type=RelationType.HISTORICAL_SUPPORT,
        subject_id=slot.subject_id,
        object_id=slot.object_id,
        knowledge_state=HistoricalKnowledgeState.ESTABLISHED,
        evidence_refs=tuple(authorization.evidence_refs),
        authorization_policy_version=authorization.policy_version,
    )


def evaluate_current_match(rule: CurrentMatchRule, event: WorldEvent) -> MatchResult:
    condition = rule.condition.evaluate(event)
    if condition is None:
        return MatchResult.UNKNOWN
    matches = condition if rule.match_when_condition_true else not condition
    return MatchResult.MATCHES if matches else MatchResult.DOES_NOT_MATCH


def evaluate_revisit(rule, event: WorldEvent) -> RevisitResult:
    condition = rule.condition.evaluate(event)
    if condition is None:
        return RevisitResult.UNKNOWN
    return RevisitResult.TRIGGERED if condition else RevisitResult.NOT_TRIGGERED


def affected_rule_ids(contract: DecisionContract, event: WorldEvent) -> Tuple[str, ...]:
    observed_keys = {o.metric_key for o in event.observations}
    ids = [
        rule.id
        for rule in (*contract.current_match_rules, *contract.revisit_rules)
        if rule.condition.metric_key in observed_keys
    ]
    return tuple(ids)


def evaluate_safe_reuse(
    *,
    contract: DecisionContract,
    match_results: Dict[str, MatchResult],
    revisit_results: Dict[str, RevisitResult],
    target: SafeReuseTargetSpec,
) -> SafeReuseEvaluation:
    def require_match(rule_id: str) -> MatchResult:
        if rule_id not in match_results:
            raise GuardViolation(f"missing current-match result for target rule {rule_id}")
        return match_results[rule_id]

    def require_revisit(rule_id: str) -> RevisitResult:
        if rule_id not in revisit_results:
            raise GuardViolation(f"missing revisit result for target rule {rule_id}")
        return revisit_results[rule_id]

    changed_states = tuple(require_match(rule_id) for rule_id in target.changed_match_rule_ids)
    surviving_states = tuple(require_match(rule_id) for rule_id in target.surviving_match_rule_ids)
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

    if any(state is MatchResult.DOES_NOT_MATCH for state in surviving_states):
        return SafeReuseEvaluation(
            result=SafeReuseResult.REUSE_NOT_AUTHORIZED,
            limiting_relations=tuple(target.surviving_match_rule_ids),
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
