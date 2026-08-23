from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Tuple

from .domain import (
    AuthorizationStatus,
    CompositionAuthorizationDecision,
    CompositionState,
    CompositionValue,
    DecisionContract,
    HistoricalKnowledgeState,
    HistoricalRelation,
)
from .engine import evaluate_target, validate_contract
from .m21 import (
    AuthorizationScope,
    CanonicalEvaluationResult,
    M21Registry,
    StrongDecisionCommit,
    StrongEvaluationSnapshot,
    active_entries_as_of,
    authorized_world_state_at,
    canonicalize_target_evaluation,
    contract_from_artifact,
    entity_definition_hash,
    target_from_artifact,
    validate_evidence_integrity,
    world_schema_from_artifact,
)
from .temporal import (
    AuthorizationRecord,
    AuthorizedAssertion,
    AuthorityPolicy,
    DecisionCommitRecord,
    EventPolicy,
    LedgerEntryKind,
    TemporalEvidenceRecord,
    TemporalIntegrityError,
)


def _active_entry_map(ledger, cutoff_seq: int):
    return {entry.entry_id: entry for entry in active_entries_as_of(ledger, cutoff_seq)}


def validate_commit_identity_in_ledger(*, ledger, commit: StrongDecisionCommit) -> None:
    active = _active_entry_map(ledger, commit.commit_cutoff_seq)
    entry = active.get(commit.commit_id)
    if entry is None or entry.kind is not LedgerEntryKind.DECISION_COMMIT:
        raise TemporalIntegrityError("committed contract is not visible at its commit cutoff")
    payload = entry.payload
    if not isinstance(payload, DecisionCommitRecord):
        raise TemporalIntegrityError("commit ledger payload type mismatch")
    if payload.decision_id != commit.decision_id or payload.contract_version != commit.contract_version:
        raise TemporalIntegrityError("strong commit does not match ledger commit identity")


def _validated_scoped_commit_authorizations(
    *,
    registry: M21Registry,
    ledger,
    commit: StrongDecisionCommit,
    policy: AuthorityPolicy,
) -> Tuple[tuple, ...]:
    validate_commit_identity_in_ledger(ledger=ledger, commit=commit)
    artifact = registry.artifacts.get(commit.contract_artifact_id)
    if artifact is None or artifact.content_hash != commit.contract_hash:
        raise TemporalIntegrityError("commit contract artifact missing or mismatched")
    contract = contract_from_artifact(artifact)
    active = _active_entry_map(ledger, commit.commit_cutoff_seq)
    validated = []

    for scoped in registry.authorizations.values():
        if scoped.scope is not AuthorizationScope.COMMIT_TIME or scoped.scope_ref != commit.commit_id:
            continue
        if scoped.contract_artifact_id != commit.contract_artifact_id:
            raise TemporalIntegrityError("COMMIT_TIME authorization references another contract")
        if entity_definition_hash(contract, scoped.entity_id) != scoped.entity_definition_hash:
            raise TemporalIntegrityError("authorization semantic identity no longer matches entity")
        if scoped.policy_version != policy.version or scoped.policy_hash != policy.policy_hash:
            raise TemporalIntegrityError("authorization policy identity mismatch")

        ledger_entry = active.get(scoped.authorization_id)
        if ledger_entry is None or ledger_entry.kind is not LedgerEntryKind.AUTHORIZATION:
            raise TemporalIntegrityError("scoped authorization is not visible at commit cutoff")
        record = ledger_entry.payload
        if not isinstance(record, AuthorizationRecord):
            raise TemporalIntegrityError("authorization ledger payload type mismatch")
        record.validate()
        if len(record.evidence_ids) != 1:
            raise TemporalIntegrityError("M2.1 V1 requires exactly one evidence record per authorization")
        if record.evidence_ids != (scoped.evidence_id,):
            raise TemporalIntegrityError("scoped authorization evidence differs from ledger authorization")
        if (
            record.entity_id != scoped.entity_id
            or record.authorized_assertion is not scoped.authorized_assertion
            or record.policy_version != scoped.policy_version
            or record.policy_hash != scoped.policy_hash
        ):
            raise TemporalIntegrityError("scoped authorization differs from ledger authorization")

        evidence_entry = active.get(scoped.evidence_id)
        if evidence_entry is None or evidence_entry.kind is not LedgerEntryKind.EVIDENCE:
            raise TemporalIntegrityError("authorization evidence is not active at commit cutoff")
        evidence = evidence_entry.payload
        if not isinstance(evidence, TemporalEvidenceRecord):
            raise TemporalIntegrityError("authorization evidence payload type mismatch")
        validate_evidence_integrity(evidence)
        candidate = next(
            (
                item
                for item in evidence.candidate_assertions
                if item.entity_id == scoped.entity_id and item.assertion is scoped.authorized_assertion
            ),
            None,
        )
        if candidate is None:
            raise TemporalIntegrityError("authorization is not grounded in cited evidence")
        replayed = policy.authorize_candidate(
            evidence=evidence,
            candidate=candidate,
            authorization_id=record.id,
        )
        if replayed != record:
            raise TemporalIntegrityError("persisted authorization does not reproduce under policy")
        validated.append((scoped, record))

    return tuple(sorted(validated, key=lambda item: item[0].authorization_id))


def strict_materialize_committed_contract(
    *,
    registry: M21Registry,
    ledger,
    commit: StrongDecisionCommit,
    authority_policy: AuthorityPolicy,
) -> DecisionContract:
    artifact = registry.artifacts.get(commit.contract_artifact_id)
    if artifact is None or artifact.content_hash != commit.contract_hash:
        raise TemporalIntegrityError("cannot materialize missing committed contract artifact")
    original = contract_from_artifact(artifact)
    validated = _validated_scoped_commit_authorizations(
        registry=registry,
        ledger=ledger,
        commit=commit,
        policy=authority_policy,
    )
    by_entity = {}
    for scoped, record in validated:
        by_entity.setdefault(scoped.entity_id, []).append((scoped, record))

    relations = []
    for relation in original.historical_relations:
        items = by_entity.get(relation.id, [])
        assertions = {item[0].authorized_assertion for item in items}
        if AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE in assertions:
            scoped, record = next(
                item
                for item in items
                if item[0].authorized_assertion is AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE
            )
            relations.append(
                replace(
                    relation,
                    knowledge_state=HistoricalKnowledgeState.ESTABLISHED,
                    evidence_refs=(scoped.evidence_id,),
                    authorization_policy_version=record.policy_version,
                )
            )
        elif AuthorizedAssertion.T0_UNRESOLVED in assertions:
            scoped, record = next(
                item for item in items if item[0].authorized_assertion is AuthorizedAssertion.T0_UNRESOLVED
            )
            relations.append(
                replace(
                    relation,
                    knowledge_state=HistoricalKnowledgeState.T0_UNRESOLVED,
                    evidence_refs=(scoped.evidence_id,),
                    authorization_policy_version=record.policy_version,
                )
            )
        else:
            relations.append(
                replace(
                    relation,
                    knowledge_state=HistoricalKnowledgeState.NOT_DURABLY_RECORDED,
                    evidence_refs=(),
                    authorization_policy_version="",
                )
            )

    compositions = []
    for composition in original.composition_states:
        items = by_entity.get(composition.id, [])
        assertions = {item[0].authorized_assertion for item in items}
        if AuthorizedAssertion.COMPOSITION_TRUE in assertions:
            scoped, record = next(
                item for item in items if item[0].authorized_assertion is AuthorizedAssertion.COMPOSITION_TRUE
            )
            value = CompositionValue.ESTABLISHED_TRUE
            auth = CompositionAuthorizationDecision(
                candidate_id=composition.id,
                status=AuthorizationStatus.AUTHORIZED,
                authorized_value=value,
                evidence_refs=(scoped.evidence_id,),
                policy_version=record.policy_version,
                reason_code="M21_SCOPED_AUTHORITY",
            )
        elif AuthorizedAssertion.COMPOSITION_FALSE in assertions:
            scoped, record = next(
                item for item in items if item[0].authorized_assertion is AuthorizedAssertion.COMPOSITION_FALSE
            )
            value = CompositionValue.ESTABLISHED_FALSE
            auth = CompositionAuthorizationDecision(
                candidate_id=composition.id,
                status=AuthorizationStatus.AUTHORIZED,
                authorized_value=value,
                evidence_refs=(scoped.evidence_id,),
                policy_version=record.policy_version,
                reason_code="M21_SCOPED_AUTHORITY",
            )
        elif AuthorizedAssertion.T0_UNRESOLVED in assertions:
            value = CompositionValue.T0_UNRESOLVED
            auth = None
        else:
            value = CompositionValue.NOT_DURABLY_RECORDED
            auth = None
        compositions.append(replace(composition, value=value, authorization=auth))

    materialized = replace(
        original,
        historical_relations=tuple(relations),
        composition_states=tuple(compositions),
    )
    validate_contract(materialized)
    return materialized


def strict_full_replay(
    *,
    registry: M21Registry,
    ledger,
    evaluation: StrongEvaluationSnapshot,
    authority_policy: AuthorityPolicy,
    event_policies: Mapping[tuple[str, str], EventPolicy],
    engine_version: str,
    engine_hash: str,
) -> CanonicalEvaluationResult:
    if evaluation.engine_version != engine_version or evaluation.engine_hash != engine_hash:
        raise TemporalIntegrityError("engine artifact identity mismatch")
    if evaluation.canonicalization_version != "CANONICAL_V1":
        raise TemporalIntegrityError("unsupported replay canonicalization version")
    commit = registry.commits.get(evaluation.decision_commit_id)
    if commit is None:
        raise TemporalIntegrityError("ghost evaluation: commit does not exist")
    if commit.commit_cutoff_seq > evaluation.input_cutoff_seq:
        raise TemporalIntegrityError("evaluation cutoff precedes commit")
    if commit.contract_hash != evaluation.contract_hash:
        raise TemporalIntegrityError("evaluation contract hash differs from committed contract")
    if (
        authority_policy.version != evaluation.authority_policy_version
        or authority_policy.policy_hash != evaluation.authority_policy_hash
    ):
        raise TemporalIntegrityError("authority policy identity mismatch")

    target_artifact = registry.artifacts.get(evaluation.target_artifact_id)
    schema_artifact = registry.artifacts.get(evaluation.world_schema_artifact_id)
    if target_artifact is None or target_artifact.content_hash != evaluation.target_hash:
        raise TemporalIntegrityError("target artifact/hash mismatch")
    if schema_artifact is None or schema_artifact.content_hash != evaluation.world_schema_hash:
        raise TemporalIntegrityError("world-schema artifact/hash mismatch")
    event_policy = event_policies.get((evaluation.event_policy_version, evaluation.event_policy_hash))
    if event_policy is None:
        raise TemporalIntegrityError("event policy artifact identity mismatch")

    contract = strict_materialize_committed_contract(
        registry=registry,
        ledger=ledger,
        commit=commit,
        authority_policy=authority_policy,
    )
    target = target_from_artifact(target_artifact)
    metric_specs = world_schema_from_artifact(schema_artifact)

    # Raw world evidence must also prove its stored content hash before it can
    # participate in the authorized world projection.
    for entry in active_entries_as_of(ledger, evaluation.input_cutoff_seq):
        if entry.kind is LedgerEntryKind.RAW_WORLD_EVIDENCE:
            raw = entry.payload
            if not hasattr(raw, "content") or source_hash(raw.content) != raw.source_content_hash:
                raise TemporalIntegrityError("raw-world evidence content hash mismatch")

    world_state = authorized_world_state_at(
        ledger=ledger,
        cutoff_seq=evaluation.input_cutoff_seq,
        world_time=evaluation.world_time,
        event_policies=event_policies,
        metric_specs=metric_specs,
    )
    result = evaluate_target(
        contract=validate_contract(contract),
        world_state=world_state,
        target=target,
    )
    return canonicalize_target_evaluation(result)


def strict_verify_full_replay(
    *,
    registry: M21Registry,
    ledger,
    evaluation_id: str,
    authority_policy: AuthorityPolicy,
    event_policies: Mapping[tuple[str, str], EventPolicy],
    engine_version: str,
    engine_hash: str,
) -> CanonicalEvaluationResult:
    evaluation = registry.evaluations.get(evaluation_id)
    if evaluation is None:
        raise TemporalIntegrityError("evaluation snapshot not found")
    replayed = strict_full_replay(
        registry=registry,
        ledger=ledger,
        evaluation=evaluation,
        authority_policy=authority_policy,
        event_policies=event_policies,
        engine_version=engine_version,
        engine_hash=engine_hash,
    )
    if replayed != evaluation.canonical_result:
        raise TemporalIntegrityError("full replay canonical result differs from stored result")
    if replayed.result_hash() != evaluation.result_hash:
        raise TemporalIntegrityError("full replay result hash mismatch")
    return replayed
