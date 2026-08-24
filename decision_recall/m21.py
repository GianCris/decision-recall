from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
import math
from typing import Iterable, Mapping, Optional, Protocol, Tuple

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
    TargetRef,
    TargetSupportBinding,
    ThresholdCondition,
)
from .engine import TargetEvaluation, evaluate_target, validate_contract
from .temporal import (
    AuthorizationRecord,
    AuthorizedAssertion,
    AuthorityPolicy,
    CorrectionRecord,
    EventPolicy,
    InMemoryTemporalLedger,
    LedgerEntry,
    LedgerEntryKind,
    RawWorldEvidence,
    TemporalEvidenceRecord,
    TemporalIntegrityError,
    WorldEventAuthorizationRecord,
    source_hash,
)


CANONICALIZATION_V1 = "CANONICAL_V1"


class AuthorizationScope(str, Enum):
    COMMIT_TIME = "commit_time"
    EVALUATION_DERIVED = "evaluation_derived"
    RECOVERY_DERIVED = "recovery_derived"


@dataclass(frozen=True)
class CanonicalArtifact:
    artifact_id: str
    kind: str
    semantic_id: str
    semantic_version: str
    canonicalization_version: str
    canonical_json: str
    content_hash: str


@dataclass(frozen=True)
class ScopedAuthorization:
    authorization_id: str
    contract_artifact_id: str
    entity_id: str
    entity_definition_hash: str
    authorized_assertion: AuthorizedAssertion
    evidence_id: str
    policy_version: str
    policy_hash: str
    scope: AuthorizationScope
    scope_ref: str
    target_ref: Optional[TargetRef] = None


@dataclass(frozen=True)
class StrongDecisionCommit:
    commit_id: str
    decision_id: str
    contract_artifact_id: str
    contract_hash: str
    contract_version: str
    capture_profile_version: str
    capture_profile_hash: str
    commit_cutoff_seq: int


@dataclass(frozen=True)
class CanonicalEvaluationResult:
    safe_reuse_result: str
    limiting_requirements: Tuple[str, ...]
    reason_codes: Tuple[str, ...]
    current_matches: Tuple[Tuple[str, str], ...]
    review_states: Tuple[Tuple[str, str], ...]
    canonicalization_version: str = CANONICALIZATION_V1

    def canonical_json(self) -> str:
        return canonical_json(self)

    def result_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True)
class StrongEvaluationSnapshot:
    evaluation_id: str
    decision_commit_id: str
    contract_hash: str
    input_cutoff_seq: int
    world_time: datetime
    target_artifact_id: str
    target_hash: str
    world_schema_artifact_id: str
    world_schema_hash: str
    authority_policy_version: str
    authority_policy_hash: str
    event_policy_version: str
    event_policy_hash: str
    engine_version: str
    engine_hash: str
    canonical_result: CanonicalEvaluationResult
    result_hash: str
    canonicalization_version: str = CANONICALIZATION_V1


class LedgerLike(Protocol):
    @property
    def head_seq(self) -> int: ...
    def entries_as_of(self, cutoff_seq: int) -> Tuple[LedgerEntry, ...]: ...
    def entry(self, entry_id: str) -> LedgerEntry: ...


class M21Registry:
    """Immutable semantic artifact registry; temporal claims live in the ledger."""

    def __init__(self) -> None:
        self.artifacts: dict[str, CanonicalArtifact] = {}
        self.authorizations: dict[str, ScopedAuthorization] = {}
        self.commits: dict[str, StrongDecisionCommit] = {}
        self.evaluations: dict[str, StrongEvaluationSnapshot] = {}

    def add_artifact(self, artifact: CanonicalArtifact) -> None:
        if artifact.artifact_id in self.artifacts:
            raise TemporalIntegrityError("duplicate canonical artifact id")
        if artifact.canonicalization_version != CANONICALIZATION_V1:
            raise TemporalIntegrityError("unsupported canonicalization version")
        if sha256(artifact.canonical_json.encode("utf-8")).hexdigest() != artifact.content_hash:
            raise TemporalIntegrityError("artifact hash does not match canonical content")
        self.artifacts[artifact.artifact_id] = artifact

    def add_authorization(self, authorization: ScopedAuthorization) -> None:
        if authorization.authorization_id in self.authorizations:
            raise TemporalIntegrityError("duplicate scoped authorization id")
        if not authorization.scope_ref.strip():
            raise TemporalIntegrityError("authorization scope_ref is required")
        if authorization.scope is not AuthorizationScope.COMMIT_TIME and authorization.target_ref is None:
            raise TemporalIntegrityError("derived authorization requires target_ref")
        self.authorizations[authorization.authorization_id] = authorization

    def add_commit(self, commit: StrongDecisionCommit) -> None:
        if commit.commit_id in self.commits:
            raise TemporalIntegrityError("duplicate commit id")
        if any(
            item.decision_id == commit.decision_id and item.contract_version == commit.contract_version
            for item in self.commits.values()
        ):
            raise TemporalIntegrityError("decision/version may be committed only once")
        artifact = self.artifacts.get(commit.contract_artifact_id)
        if artifact is None or artifact.kind != "decision_contract":
            raise TemporalIntegrityError("commit references missing contract artifact")
        if artifact.content_hash != commit.contract_hash:
            raise TemporalIntegrityError("commit contract hash mismatch")
        if artifact.semantic_id != commit.decision_id or artifact.semantic_version != commit.contract_version:
            raise TemporalIntegrityError("commit identity differs from contract artifact")
        if commit.commit_cutoff_seq < 0:
            raise TemporalIntegrityError("commit cutoff cannot be negative")
        self.commits[commit.commit_id] = commit

    def add_evaluation(self, evaluation: StrongEvaluationSnapshot) -> None:
        if evaluation.evaluation_id in self.evaluations:
            raise TemporalIntegrityError("duplicate evaluation id")
        commit = self.commits.get(evaluation.decision_commit_id)
        if commit is None:
            raise TemporalIntegrityError("evaluation references unknown decision commit")
        if commit.commit_cutoff_seq > evaluation.input_cutoff_seq:
            raise TemporalIntegrityError("evaluation input cutoff precedes decision commit")
        if commit.contract_hash != evaluation.contract_hash:
            raise TemporalIntegrityError("evaluation contract hash differs from committed contract")
        target = self.artifacts.get(evaluation.target_artifact_id)
        if target is None or target.kind != "target_spec" or target.content_hash != evaluation.target_hash:
            raise TemporalIntegrityError("evaluation target artifact/hash mismatch")
        schema = self.artifacts.get(evaluation.world_schema_artifact_id)
        if schema is None or schema.kind != "world_schema" or schema.content_hash != evaluation.world_schema_hash:
            raise TemporalIntegrityError("evaluation world schema artifact/hash mismatch")
        if evaluation.result_hash != evaluation.canonical_result.result_hash():
            raise TemporalIntegrityError("evaluation result hash does not match canonical result")
        self.evaluations[evaluation.evaluation_id] = evaluation


# ---------------------------------------------------------------------------
# Canonicalization / semantic identity
# ---------------------------------------------------------------------------


def _canonical_value(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise TemporalIntegrityError("canonical datetimes must be timezone-aware")
        return value.isoformat()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TemporalIntegrityError("canonical floats must be finite")
        return 0.0 if value == 0.0 else value
    if hasattr(value, "__dataclass_fields__"):
        return {
            field: _canonical_value(getattr(value, field))
            for field in value.__dataclass_fields__
        }
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TemporalIntegrityError(f"unsupported canonical value: {type(value)!r}")


def canonical_json(value) -> str:
    envelope = {
        "canonicalization_version": CANONICALIZATION_V1,
        "value": _canonical_value(value),
    }
    return json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def make_contract_artifact(contract: DecisionContract, *, version: str) -> CanonicalArtifact:
    validate_contract(contract)
    text = canonical_json(contract)
    return CanonicalArtifact(
        artifact_id=f"CONTRACT:{contract.id}:{version}:{sha256(text.encode()).hexdigest()[:16]}",
        kind="decision_contract",
        semantic_id=contract.id,
        semantic_version=version,
        canonicalization_version=CANONICALIZATION_V1,
        canonical_json=text,
        content_hash=sha256(text.encode("utf-8")).hexdigest(),
    )


def make_target_artifact(target: SafeReuseTargetSpec) -> CanonicalArtifact:
    text = canonical_json(target)
    return CanonicalArtifact(
        artifact_id=f"TARGET:{target.id}:{target.version}:{sha256(text.encode()).hexdigest()[:16]}",
        kind="target_spec",
        semantic_id=target.id,
        semantic_version=target.version,
        canonicalization_version=CANONICALIZATION_V1,
        canonical_json=text,
        content_hash=sha256(text.encode("utf-8")).hexdigest(),
    )


def make_world_schema_artifact(metric_specs: Mapping[str, MetricSpec], *, version: str) -> CanonicalArtifact:
    ordered = tuple(metric_specs[key] for key in sorted(metric_specs))
    text = canonical_json(ordered)
    return CanonicalArtifact(
        artifact_id=f"WORLD_SCHEMA:{version}:{sha256(text.encode()).hexdigest()[:16]}",
        kind="world_schema",
        semantic_id="WORLD_SCHEMA",
        semantic_version=version,
        canonicalization_version=CANONICALIZATION_V1,
        canonical_json=text,
        content_hash=sha256(text.encode("utf-8")).hexdigest(),
    )


def _semantic_definition(entity):
    """Return WHAT an entity means, excluding WHAT WE KNOW about it."""
    if isinstance(entity, Claim):
        return {
            "kind": "claim",
            "id": entity.id,
            "claim_type": entity.claim_type,
            "predicate_key": entity.predicate_key,
            "current_metric_key": entity.current_metric_key,
        }
    if isinstance(entity, HistoricalRelation):
        return {
            "kind": "historical_relation",
            "id": entity.id,
            "relation_type": entity.relation_type,
            "subject_id": entity.subject_id,
            "object_id": entity.object_id,
        }
    if isinstance(entity, CompositionState):
        return {
            "kind": "composition",
            "id": entity.id,
            "composition_kind": entity.kind,
            "relation_ids": entity.relation_ids,
            "target_ref": entity.target_ref,
        }
    if isinstance(entity, CurrentMatchRule):
        return {
            "kind": "current_match_rule",
            "id": entity.id,
            "premise_id": entity.premise_id,
            "condition": entity.condition,
            "match_when_condition_true": entity.match_when_condition_true,
        }
    if isinstance(entity, RevisitRule):
        return {
            "kind": "revisit_rule",
            "id": entity.id,
            "condition": entity.condition,
        }
    if isinstance(entity, DecisionContract):
        return {"kind": "decision", "id": entity.id, "action": entity.action}
    raise TemporalIntegrityError(f"unsupported semantic entity: {type(entity)!r}")


def entity_definition_hash(contract: DecisionContract, entity_id: str) -> str:
    return canonical_hash(_semantic_definition(_entity(contract, entity_id)))


def _entity(contract: DecisionContract, entity_id: str):
    if contract.id == entity_id:
        return contract
    for collection in (
        contract.claims,
        contract.historical_relations,
        contract.composition_states,
        contract.current_match_rules,
        contract.revisit_rules,
    ):
        for entity in collection:
            if entity.id == entity_id:
                return entity
    raise TemporalIntegrityError(f"unknown entity in committed contract: {entity_id}")


# ---------------------------------------------------------------------------
# Artifact decode (V1 only)
# ---------------------------------------------------------------------------


def _artifact_value(artifact: CanonicalArtifact):
    if artifact.canonicalization_version != CANONICALIZATION_V1:
        raise TemporalIntegrityError("unsupported canonicalization version")
    if sha256(artifact.canonical_json.encode()).hexdigest() != artifact.content_hash:
        raise TemporalIntegrityError("artifact content hash mismatch")
    raw = json.loads(artifact.canonical_json)
    if raw.get("canonicalization_version") != CANONICALIZATION_V1:
        raise TemporalIntegrityError("canonical artifact envelope version mismatch")
    return raw["value"]


def contract_from_artifact(artifact: CanonicalArtifact) -> DecisionContract:
    if artifact.kind != "decision_contract":
        raise TemporalIntegrityError("artifact is not a decision contract")
    data = _artifact_value(artifact)

    def condition(item):
        return ThresholdCondition(
            metric_key=item["metric_key"],
            operator=item["operator"],
            # Preserve the canonical numeric representation from the artifact.
            # Coercing integer 70 to float 70.0 changed the entity-definition hash
            # even though the threshold semantics were identical.
            threshold=item["threshold"],
            minimum_window_days=item["minimum_window_days"],
        )

    contract = DecisionContract(
        id=data["id"],
        action=data["action"],
        claims=tuple(
            Claim(
                id=item["id"],
                claim_type=ClaimType(item["claim_type"]),
                predicate_key=item["predicate_key"],
                current_metric_key=item["current_metric_key"],
                evidence_refs=tuple(item["evidence_refs"]),
            )
            for item in data["claims"]
        ),
        historical_relations=tuple(
            HistoricalRelation(
                id=item["id"],
                relation_type=RelationType(item["relation_type"]),
                subject_id=item["subject_id"],
                object_id=item["object_id"],
                knowledge_state=HistoricalKnowledgeState(item["knowledge_state"]),
                evidence_refs=tuple(item["evidence_refs"]),
                authorization_policy_version=item["authorization_policy_version"],
            )
            for item in data["historical_relations"]
        ),
        composition_states=tuple(
            CompositionState(
                id=item["id"],
                kind=CompositionKind(item["kind"]),
                relation_ids=tuple(item["relation_ids"]),
                target_ref=TargetRef(item["target_ref"]["id"], item["target_ref"]["version"]),
                value=CompositionValue(item["value"]),
                authorization=None,
            )
            for item in data["composition_states"]
        ),
        current_match_rules=tuple(
            CurrentMatchRule(
                id=item["id"],
                premise_id=item["premise_id"],
                condition=condition(item["condition"]),
                match_when_condition_true=bool(item["match_when_condition_true"]),
            )
            for item in data["current_match_rules"]
        ),
        revisit_rules=tuple(
            RevisitRule(id=item["id"], condition=condition(item["condition"]))
            for item in data["revisit_rules"]
        ),
    )
    return contract


def target_from_artifact(artifact: CanonicalArtifact) -> SafeReuseTargetSpec:
    if artifact.kind != "target_spec":
        raise TemporalIntegrityError("artifact is not a TargetSpec")
    data = _artifact_value(artifact)

    def binding(item):
        return TargetSupportBinding(
            historical_relation_id=item["historical_relation_id"],
            current_match_rule_id=item["current_match_rule_id"],
        )

    return SafeReuseTargetSpec(
        id=data["id"],
        version=data["version"],
        changed_bindings=tuple(binding(item) for item in data["changed_bindings"]),
        surviving_bindings=tuple(binding(item) for item in data["surviving_bindings"]),
        revisit_rule_ids=tuple(data["revisit_rule_ids"]),
        limiting_composition_id=data["limiting_composition_id"],
    )


def world_schema_from_artifact(artifact: CanonicalArtifact) -> dict[str, MetricSpec]:
    if artifact.kind != "world_schema":
        raise TemporalIntegrityError("artifact is not a world schema")
    data = _artifact_value(artifact)
    specs = tuple(
        MetricSpec(
            key=item["key"],
            unit=item["unit"],
            minimum=item["minimum"],
            maximum=item["maximum"],
        )
        for item in data
    )
    return {spec.key: spec for spec in specs}


# ---------------------------------------------------------------------------
# Scoped authority + effective dependency projection
# ---------------------------------------------------------------------------


def validate_evidence_integrity(evidence: TemporalEvidenceRecord) -> None:
    evidence.validate()
    if source_hash(evidence.content) != evidence.source_content_hash:
        raise TemporalIntegrityError("evidence content hash mismatch")


def active_entries_as_of(ledger: LedgerLike, cutoff_seq: int) -> Tuple[LedgerEntry, ...]:
    all_entries = ledger.entries_as_of(cutoff_seq)
    corrected = {
        entry.payload.corrects_entry_id
        for entry in all_entries
        if entry.kind is LedgerEntryKind.CORRECTION
        and isinstance(entry.payload, CorrectionRecord)
    }
    active = {
        entry.entry_id: entry
        for entry in all_entries
        if entry.entry_id not in corrected and entry.kind is not LedgerEntryKind.CORRECTION
    }
    changed = True
    while changed:
        changed = False
        for entry_id, entry in tuple(active.items()):
            if entry.kind is LedgerEntryKind.AUTHORIZATION:
                auth = entry.payload
                assert isinstance(auth, AuthorizationRecord)
                if any(evidence_id not in active for evidence_id in auth.evidence_ids):
                    del active[entry_id]
                    changed = True
            elif entry.kind is LedgerEntryKind.WORLD_EVENT_AUTHORIZATION:
                auth = entry.payload
                assert isinstance(auth, WorldEventAuthorizationRecord)
                if auth.raw_evidence_id not in active:
                    del active[entry_id]
                    changed = True
    return tuple(entry for entry in all_entries if entry.entry_id in active)


def _entry_seq(ledger: LedgerLike, entry_id: str, cutoff_seq: int) -> Optional[int]:
    for entry in ledger.entries_as_of(cutoff_seq):
        if entry.entry_id == entry_id:
            return entry.batch_seq
    return None


def commit_authorizations_for(
    *,
    registry: M21Registry,
    ledger: LedgerLike,
    commit: StrongDecisionCommit,
) -> Tuple[ScopedAuthorization, ...]:
    artifact = registry.artifacts[commit.contract_artifact_id]
    contract = contract_from_artifact(artifact)
    active_ids = {entry.entry_id for entry in active_entries_as_of(ledger, commit.commit_cutoff_seq)}
    result = []
    for scoped in registry.authorizations.values():
        if scoped.scope is not AuthorizationScope.COMMIT_TIME or scoped.scope_ref != commit.commit_id:
            continue
        if scoped.authorization_id not in active_ids:
            continue
        if scoped.contract_artifact_id != commit.contract_artifact_id:
            raise TemporalIntegrityError("commit authorization belongs to a different contract artifact")
        if entity_definition_hash(contract, scoped.entity_id) != scoped.entity_definition_hash:
            raise TemporalIntegrityError("authorization entity definition hash mismatch")
        seq = _entry_seq(ledger, scoped.authorization_id, commit.commit_cutoff_seq)
        if seq is None or seq > commit.commit_cutoff_seq:
            raise TemporalIntegrityError("COMMIT_TIME authorization is not visible at commit cutoff")
        result.append(scoped)
    return tuple(sorted(result, key=lambda item: item.authorization_id))


def materialize_committed_contract(
    *,
    registry: M21Registry,
    ledger: LedgerLike,
    commit: StrongDecisionCommit,
) -> DecisionContract:
    artifact = registry.artifacts.get(commit.contract_artifact_id)
    if artifact is None or artifact.content_hash != commit.contract_hash:
        raise TemporalIntegrityError("cannot materialize missing/mismatched committed contract")
    original = contract_from_artifact(artifact)
    scoped = commit_authorizations_for(registry=registry, ledger=ledger, commit=commit)
    assertions = {(item.entity_id, item.authorized_assertion) for item in scoped}

    relations = []
    for relation in original.historical_relations:
        if (relation.id, AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE) in assertions:
            state = HistoricalKnowledgeState.ESTABLISHED
        elif (relation.id, AuthorizedAssertion.T0_UNRESOLVED) in assertions:
            state = HistoricalKnowledgeState.T0_UNRESOLVED
        else:
            state = HistoricalKnowledgeState.NOT_DURABLY_RECORDED
        relations.append(replace(relation, knowledge_state=state))

    compositions = []
    for composition in original.composition_states:
        entity_assertions = {assertion for entity_id, assertion in assertions if entity_id == composition.id}
        if AuthorizedAssertion.COMPOSITION_TRUE in entity_assertions:
            value = CompositionValue.ESTABLISHED_TRUE
        elif AuthorizedAssertion.COMPOSITION_FALSE in entity_assertions:
            value = CompositionValue.ESTABLISHED_FALSE
        elif AuthorizedAssertion.T0_UNRESOLVED in entity_assertions:
            value = CompositionValue.T0_UNRESOLVED
        else:
            value = CompositionValue.NOT_DURABLY_RECORDED
        compositions.append(replace(composition, value=value, authorization=None))

    return replace(
        original,
        historical_relations=tuple(relations),
        composition_states=tuple(compositions),
    )


def known_historical_state(
    *,
    contract: DecisionContract,
    entity_id: str,
) -> str:
    try:
        entity = _entity(contract, entity_id)
    except TemporalIntegrityError as exc:
        raise TemporalIntegrityError("UNKNOWN_ENTITY") from exc
    if isinstance(entity, HistoricalRelation):
        return entity.knowledge_state.value
    if isinstance(entity, CompositionState):
        return entity.value.value
    raise TemporalIntegrityError("entity is not a historical-state slot")


# ---------------------------------------------------------------------------
# Bitemporal world projection
# ---------------------------------------------------------------------------


def authorized_world_state_at(
    *,
    ledger: LedgerLike,
    cutoff_seq: int,
    world_time: datetime,
    event_policies: Mapping[Tuple[str, str], EventPolicy],
    metric_specs: Mapping[str, MetricSpec],
    required_policy_ref: Optional[Tuple[str, str]] = None,
) -> CanonicalWorldState:
    if world_time.tzinfo is None or world_time.utcoffset() is None:
        raise TemporalIntegrityError("world_time must be timezone-aware")
    entries = active_entries_as_of(ledger, cutoff_seq)
    raw_by_id = {
        entry.entry_id: entry
        for entry in entries
        if entry.kind is LedgerEntryKind.RAW_WORLD_EVIDENCE
        and isinstance(entry.payload, RawWorldEvidence)
    }
    auth_entries = [
        entry for entry in entries
        if entry.kind is LedgerEntryKind.WORLD_EVENT_AUTHORIZATION
        and isinstance(entry.payload, WorldEventAuthorizationRecord)
        and (
            required_policy_ref is None
            or (entry.payload.policy_version, entry.payload.policy_hash) == required_policy_ref
        )
    ]

    candidates: dict[str, list[tuple[datetime, float, str, Optional[int], str]]] = {}
    for auth_entry in auth_entries:
        auth = auth_entry.payload
        raw_entry = raw_by_id.get(auth.raw_evidence_id)
        if raw_entry is None:
            continue
        raw = raw_entry.payload
        if source_hash(raw.content) != raw.source_content_hash:
            raise TemporalIntegrityError("consumed raw-world evidence content hash mismatch")
        policy = event_policies.get((auth.policy_version, auth.policy_hash))
        if policy is None:
            raise TemporalIntegrityError("unknown event policy version/hash")
        replayed = policy.authorize(
            raw=raw,
            metric_specs=metric_specs,
            authorization_id=auth.id,
            event_id=auth.event_id,
        )
        if replayed != auth:
            raise TemporalIntegrityError("world-event authorization does not replay")
        effective_at = raw.temporal_reference.effective_at()
        if effective_at > world_time:
            continue
        for obs in raw.observations:
            candidates.setdefault(obs.metric_key, []).append(
                (effective_at, obs.value, obs.unit, obs.window_days, auth.event_id)
            )

    output = []
    for metric_key in sorted(candidates):
        rows = candidates[metric_key]
        latest_time = max(row[0] for row in rows)
        latest = [row for row in rows if row[0] == latest_time]
        signatures = {(row[1], row[2], row[3]) for row in latest}
        if len(signatures) > 1:
            continue
        row = latest[0]
        output.append(
            NumericObservation(
                metric_key=metric_key,
                value=row[1],
                unit=row[2],
                window_days=row[3],
                source_event_id=row[4],
            )
        )
    return CanonicalWorldState(observations=tuple(output))


# ---------------------------------------------------------------------------
# Full replay (legacy M2.1 entry point; strict path is in m21_strict.py)
# ---------------------------------------------------------------------------


def canonicalize_target_evaluation(result: TargetEvaluation) -> CanonicalEvaluationResult:
    return CanonicalEvaluationResult(
        safe_reuse_result=result.safe_reuse.result.value,
        limiting_requirements=tuple(result.safe_reuse.limiting_requirements),
        reason_codes=tuple(result.safe_reuse.reason_codes),
        current_matches=tuple((rule_id, state.value) for rule_id, state in result.current_matches),
        review_states=tuple((rule_id, state.value) for rule_id, state in result.review_states),
    )


def full_replay(
    *,
    registry: M21Registry,
    ledger: LedgerLike,
    evaluation: StrongEvaluationSnapshot,
    authority_policy: AuthorityPolicy,
    event_policies: Mapping[Tuple[str, str], EventPolicy],
) -> CanonicalEvaluationResult:
    commit = registry.commits.get(evaluation.decision_commit_id)
    if commit is None:
        raise TemporalIntegrityError("ghost evaluation: decision commit does not exist")
    if commit.commit_cutoff_seq > evaluation.input_cutoff_seq:
        raise TemporalIntegrityError("evaluation cutoff precedes commit")
    if commit.contract_hash != evaluation.contract_hash:
        raise TemporalIntegrityError("evaluation contract identity mismatch")
    if (
        authority_policy.version != evaluation.authority_policy_version
        or authority_policy.policy_hash != evaluation.authority_policy_hash
    ):
        raise TemporalIntegrityError("authority policy identity mismatch")

    target_artifact = registry.artifacts.get(evaluation.target_artifact_id)
    schema_artifact = registry.artifacts.get(evaluation.world_schema_artifact_id)
    if target_artifact is None or target_artifact.content_hash != evaluation.target_hash:
        raise TemporalIntegrityError("target artifact unavailable/mismatched")
    if schema_artifact is None or schema_artifact.content_hash != evaluation.world_schema_hash:
        raise TemporalIntegrityError("world schema artifact unavailable/mismatched")
    policy_ref = (evaluation.event_policy_version, evaluation.event_policy_hash)
    if policy_ref not in event_policies:
        raise TemporalIntegrityError("event policy identity mismatch")

    contract = materialize_committed_contract(registry=registry, ledger=ledger, commit=commit)
    target = target_from_artifact(target_artifact)
    metric_specs = world_schema_from_artifact(schema_artifact)
    world_state = authorized_world_state_at(
        ledger=ledger,
        cutoff_seq=evaluation.input_cutoff_seq,
        world_time=evaluation.world_time,
        event_policies=event_policies,
        metric_specs=metric_specs,
        required_policy_ref=policy_ref,
    )

    validated = validate_contract(contract)
    result = evaluate_target(contract=validated, world_state=world_state, target=target)
    return canonicalize_target_evaluation(result)


def verify_full_replay(
    *,
    registry: M21Registry,
    ledger: LedgerLike,
    evaluation_id: str,
    authority_policy: AuthorityPolicy,
    event_policies: Mapping[Tuple[str, str], EventPolicy],
) -> CanonicalEvaluationResult:
    evaluation = registry.evaluations.get(evaluation_id)
    if evaluation is None:
        raise TemporalIntegrityError("evaluation snapshot not found")
    replayed = full_replay(
        registry=registry,
        ledger=ledger,
        evaluation=evaluation,
        authority_policy=authority_policy,
        event_policies=event_policies,
    )
    if replayed.result_hash() != evaluation.result_hash:
        raise TemporalIntegrityError("full replay result hash mismatch")
    if replayed != evaluation.canonical_result:
        raise TemporalIntegrityError("full replay canonical result differs from stored result")
    return replayed
