from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class HistoricalKnowledgeState(str, Enum):
    ESTABLISHED = "established"
    T0_UNRESOLVED = "t0_unresolved"
    NOT_DURABLY_RECORDED = "not_durably_recorded"
    CURRENTLY_UNDETERMINED = "currently_undetermined"


class RelationType(str, Enum):
    HISTORICAL_SUPPORT = "historical_support"


class AuthorizationStatus(str, Enum):
    AUTHORIZED = "authorized"
    UNAUTHORIZED = "unauthorized"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class MatchResult(str, Enum):
    MATCHES = "matches"
    DOES_NOT_MATCH = "does_not_match"
    UNKNOWN = "unknown"


class RevisitResult(str, Enum):
    TRIGGERED = "triggered"
    NOT_TRIGGERED = "not_triggered"
    UNKNOWN = "unknown"


class CompositionValue(str, Enum):
    ESTABLISHED_TRUE = "established_true"
    ESTABLISHED_FALSE = "established_false"
    T0_UNRESOLVED = "t0_unresolved"
    NOT_DURABLY_RECORDED = "not_durably_recorded"
    CURRENTLY_UNDETERMINED = "currently_undetermined"


class SafeReuseResult(str, Enum):
    REUSE_AUTHORIZED = "reuse_authorized"
    REUSE_NOT_AUTHORIZED = "reuse_not_authorized"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class EvidenceRecord:
    id: str
    content: str
    provenance_type: str


@dataclass(frozen=True)
class RelationSlot:
    id: str
    relation_type: RelationType
    subject_id: str
    object_id: str
    reason_for_checking: str


@dataclass(frozen=True)
class RelationCandidate:
    id: str
    relation_type: RelationType
    subject_id: str
    object_id: str
    evidence_refs: Tuple[str, ...]


@dataclass(frozen=True)
class AuthorizationDecision:
    candidate_id: str
    status: AuthorizationStatus
    authorized_as: Optional[RelationType]
    evidence_refs: Tuple[str, ...]
    policy_version: str
    reason_code: str


@dataclass(frozen=True)
class HistoricalRelation:
    id: str
    relation_type: RelationType
    subject_id: str
    object_id: str
    knowledge_state: HistoricalKnowledgeState
    evidence_refs: Tuple[str, ...]
    authorization_policy_version: str


@dataclass(frozen=True)
class CompositionState:
    id: str
    description: str
    value: CompositionValue


@dataclass(frozen=True)
class NumericObservation:
    metric_key: str
    value: float
    window_days: Optional[int] = None


@dataclass(frozen=True)
class WorldEvent:
    id: str
    observations: Tuple[NumericObservation, ...]


@dataclass(frozen=True)
class ThresholdCondition:
    metric_key: str
    operator: str
    threshold: float
    minimum_window_days: Optional[int] = None

    def evaluate(self, event: WorldEvent) -> Optional[bool]:
        obs = next((o for o in event.observations if o.metric_key == self.metric_key), None)
        if obs is None:
            return None
        if self.minimum_window_days is not None:
            if obs.window_days is None:
                return None
            if obs.window_days < self.minimum_window_days:
                return False
        if self.operator == ">=":
            return obs.value >= self.threshold
        if self.operator == "<=":
            return obs.value <= self.threshold
        if self.operator == ">":
            return obs.value > self.threshold
        if self.operator == "<":
            return obs.value < self.threshold
        if self.operator == "==":
            return obs.value == self.threshold
        raise ValueError(f"Unsupported operator: {self.operator}")


@dataclass(frozen=True)
class CurrentMatchRule:
    id: str
    historical_relation_id: str
    condition: ThresholdCondition
    match_when_condition_true: bool


@dataclass(frozen=True)
class RevisitRule:
    id: str
    condition: ThresholdCondition


@dataclass(frozen=True)
class SafeReuseTargetSpec:
    id: str
    version: str
    changed_match_rule_ids: Tuple[str, ...]
    surviving_match_rule_ids: Tuple[str, ...]
    revisit_rule_ids: Tuple[str, ...]
    limiting_composition_id: str


@dataclass(frozen=True)
class DecisionContract:
    id: str
    action: str
    historical_relations: Tuple[HistoricalRelation, ...]
    composition_states: Tuple[CompositionState, ...]
    current_match_rules: Tuple[CurrentMatchRule, ...]
    revisit_rules: Tuple[RevisitRule, ...]

    def relation(self, relation_id: str) -> HistoricalRelation:
        return next(r for r in self.historical_relations if r.id == relation_id)

    def composition(self, composition_id: str) -> CompositionState:
        return next(c for c in self.composition_states if c.id == composition_id)
