"""Server-owned, bounded product configuration; not a caller authority payload.

Registration is an internal trust decision, not ingestion/authentication. Instances
are looked up from the registry; no request may register itself or set provenance.
Contract definitions describe the allowed semantic surface, never replace ledger
authority derivation. No evaluation result or executable policy callback lives here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from types import MappingProxyType

from ..domain import CompositionValue, DecisionContract, MetricSpec, ProvenanceType, SafeReuseTargetSpec
from ..engine import validate_contract, validate_target_against_contract
from ..temporal import AuthorizedAssertion
from .capture import CaptureProfileTemplate, DecisionFactBinding, DecisionRelationBinding, DecisionStructure
from .compiler import ObservableDecisionBundle, SourceDocument


@dataclass(frozen=True, slots=True)
class DecisionSourceRecord:
    source_id: str
    content: str
    observed_at: datetime

    def __post_init__(self):
        if not isinstance(self.source_id, str) or not self.source_id.strip() or not isinstance(self.content, str) or not self.content:
            raise ValueError("source record id/content are required")
        if not isinstance(self.observed_at, datetime) or self.observed_at.utcoffset() is None:
            raise ValueError("source record time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class DecisionInstance:
    decision_id: str
    profile_id: str
    profile_version: str
    decision_time: datetime
    source_records: tuple[DecisionSourceRecord, ...]

    def __post_init__(self):
        if any(not isinstance(value, str) or not value.strip() for value in (self.decision_id, self.profile_id, self.profile_version)):
            raise ValueError("decision/profile identity is required")
        if not isinstance(self.decision_time, datetime) or self.decision_time.utcoffset() is None:
            raise ValueError("decision time must be timezone-aware")
        if type(self.source_records) is not tuple or not self.source_records or any(type(item) is not DecisionSourceRecord for item in self.source_records):
            raise ValueError("instance accepts only data-only DecisionSourceRecord values")
        ids = tuple(item.source_id for item in self.source_records)
        if len(set(ids)) != len(ids):
            raise ValueError("instance source ids must be unique")
        if any(item.observed_at > self.decision_time for item in self.source_records):
            raise ValueError("preparation cannot consume later-world records")


@dataclass(frozen=True)
class SourceAdmission:
    source_id: str
    provenance_type: ProvenanceType


@dataclass(frozen=True)
class FactDisplay:
    semantic_key: str
    source_id: str
    quote: str


@dataclass(frozen=True)
class RuleEvidenceSpec:
    entity_id: str
    assertion: AuthorizedAssertion
    source_id: str
    quote: str


@dataclass(frozen=True)
class ProductIdentity:
    """Server-assigned artifact identities, separate from caller instance data."""

    commit_id: str
    evaluation_id: str
    namespace: str = "PRODUCT-V1"
    contract_version: str = "1"


@dataclass(frozen=True)
class DecisionProfileDefinition:
    id: str
    version: str
    capture_template: CaptureProfileTemplate
    contract_definition: DecisionContract
    target: SafeReuseTargetSpec
    metric_specs: tuple[MetricSpec, ...]
    schema_version: str
    source_admissions: tuple[SourceAdmission, ...]
    fact_displays: tuple[FactDisplay, ...]
    rule_evidence: tuple[RuleEvidenceSpec, ...]
    decision_display: str = "this decision"

    def __post_init__(self):
        validate_target_against_contract(contract=validate_contract(self.contract_definition), target=self.target)
        if len(self.capture_template.slots) != 1 or self.capture_template.question_budget != 1:
            raise ValueError("bounded lifecycle requires one prospective capture slot and one question")
        if any(item.value is not CompositionValue.NOT_DURABLY_RECORDED or item.authorization is not None for item in self.contract_definition.composition_states):
            raise ValueError("profile cannot supply established composition authority")
        for items, key in ((self.metric_specs, "key"), (self.source_admissions, "source_id"), (self.fact_displays, "semantic_key"), (self.rule_evidence, "entity_id")):
            if type(items) is not tuple or len({getattr(item, key) for item in items}) != len(items):
                raise ValueError("profile configuration must be immutable and unambiguous")
        expected_rules = {
            **{item.id: AuthorizedAssertion.CURRENT_MATCH_RULE for item in self.contract_definition.current_match_rules},
            **{item.id: AuthorizedAssertion.REVISIT_RULE for item in self.contract_definition.revisit_rules},
        }
        if {item.entity_id: item.assertion for item in self.rule_evidence} != expected_rules:
            raise ValueError("configured evidence must cover exactly the contract rules")
        metrics = {item.key for item in self.metric_specs}
        if any(item.condition.metric_key not in metrics for item in (*self.contract_definition.current_match_rules, *self.contract_definition.revisit_rules)):
            raise ValueError("contract rule references an unconfigured metric")

    def validate_instance(self, instance: DecisionInstance) -> None:
        if type(instance) is not DecisionInstance:
            raise ValueError("expected a data-only DecisionInstance")
        if (instance.profile_id, instance.profile_version) != (self.id, self.version):
            raise ValueError("instance profile identity/version mismatch")
        if {item.source_id for item in instance.source_records} != {item.source_id for item in self.source_admissions}:
            raise ValueError("instance source ids do not match profile admission constraints")
        sources = {item.source_id: item.content for item in instance.source_records}
        for item in (*self.fact_displays, *self.rule_evidence):
            if not item.quote or item.quote not in sources.get(item.source_id, ""):
                raise ValueError("configured source quote is absent from instance records")

    def observable(self, instance: DecisionInstance) -> ObservableDecisionBundle:
        self.validate_instance(instance)
        provenance = {item.source_id: item.provenance_type for item in self.source_admissions}
        return ObservableDecisionBundle(instance.decision_id, tuple(
            SourceDocument(item.source_id, item.content, provenance[item.source_id], item.observed_at)
            for item in instance.source_records
        ))

    def contract(self, instance: DecisionInstance) -> DecisionContract:
        self.validate_instance(instance)
        draft = self.contract_definition
        return replace(draft, id=instance.decision_id, historical_relations=tuple(
            replace(item, object_id=instance.decision_id if item.object_id == draft.id else item.object_id)
            for item in draft.historical_relations
        ))

    def structure(self, instance: DecisionInstance) -> DecisionStructure:
        contract = self.contract(instance)
        displays = {item.semantic_key: item.quote for item in self.fact_displays}
        return DecisionStructure(
            contract.id, self.decision_display,
            tuple(DecisionFactBinding(item.id, item.predicate_key, displays.get(item.predicate_key, item.predicate_key.replace("_", " "))) for item in contract.claims),
            tuple(DecisionRelationBinding(item.id, item.relation_type, item.subject_id, item.object_id) for item in contract.historical_relations),
        )


class DecisionRegistry:
    """Immutable server registration/lookup only; never an operation/policy router."""

    def __init__(self, *, profiles: tuple[DecisionProfileDefinition, ...], instances: tuple[DecisionInstance, ...], identities: tuple[tuple[str, ProductIdentity], ...]):
        profile_map = {(item.id, item.version): item for item in profiles}
        instance_map = {item.decision_id: item for item in instances}
        identity_map = dict(identities)
        if len(profile_map) != len(profiles) or len(instance_map) != len(instances) or len(identity_map) != len(identities):
            raise ValueError("duplicate product registration")
        if set(identity_map) != set(instance_map):
            raise ValueError("every registered instance requires server-owned artifact identity")
        for instance in instances:
            profile = profile_map.get((instance.profile_id, instance.profile_version))
            if profile is None:
                raise ValueError("unknown registered profile")
            profile.validate_instance(instance)
        self._profiles = MappingProxyType(profile_map)
        self._instances = MappingProxyType(instance_map)
        self._identities = MappingProxyType(identity_map)

    def resolve(self, decision_id: str) -> tuple[DecisionProfileDefinition, DecisionInstance, ProductIdentity]:
        try:
            instance = self._instances[decision_id]
        except KeyError as exc:
            raise ValueError("unknown registered decision") from exc
        return self._profiles[(instance.profile_id, instance.profile_version)], instance, self._identities[decision_id]
