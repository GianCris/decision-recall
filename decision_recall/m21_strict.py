from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Optional, Tuple

from .domain import (
    AuthorizationStatus,
    CompositionAuthorizationDecision,
    CompositionState,
    CompositionValue,
    DecisionContract,
    HistoricalKnowledgeState,
    HistoricalRelation,
    SafeReuseTargetSpec,
)
from .engine import evaluate_target, validate_contract
from .m21 import (
    AuthorizationScope,
    CANONICALIZATION_V1,
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
    EvaluationSnapshot,
    EventPolicy,
    LedgerEntryKind,
    TemporalEvidenceRecord,
    TemporalIntegrityError,
)


AuthorityPolicies = Mapping[tuple[str, str], AuthorityPolicy]


def _active_entry_map(ledger, cutoff_seq: int):
    return {entry.entry_id: entry for entry in active_entries_as_of(ledger, cutoff_seq)}


def _authority_policy_map(
    *,
    authority_policy: Optional[AuthorityPolicy] = None,
    authority_policies: Optional[AuthorityPolicies] = None,
) -> dict[tuple[str, str], AuthorityPolicy]:
    result = dict(authority_policies or {})
    if authority_policy is not None:
        result[(authority_policy.version, authority_policy.policy_hash)] = authority_policy
    if not result:
        raise TemporalIntegrityError("at least one authority policy artifact is required")
    return result


def validate_commit_identity_in_ledger(*, ledger, commit: StrongDecisionCommit) -> None:
    try:
        entry = ledger.entry(commit.commit_id)
    except KeyError as exc:
        raise TemporalIntegrityError("committed contract is not present in temporal ledger") from exc
    if entry.kind is not LedgerEntryKind.DECISION_COMMIT:
        raise TemporalIntegrityError("commit ledger entry has wrong kind")
    if entry.batch_seq != commit.commit_cutoff_seq:
        raise TemporalIntegrityError("commit cutoff does not equal actual ledger commit batch")
    payload = entry.payload
    if not isinstance(payload, DecisionCommitRecord):
        raise TemporalIntegrityError("commit ledger payload type mismatch")
    if (
        payload.decision_id != commit.decision_id
        or payload.contract_version != commit.contract_version
        or payload.capture_profile_version != commit.capture_profile_version
        or payload.capture_profile_hash != commit.capture_profile_hash
        or payload.contract_artifact_id != commit.contract_artifact_id
        or payload.contract_hash != commit.contract_hash
        or payload.canonicalization_version != CANONICALIZATION_V1
    ):
        raise TemporalIntegrityError("strong commit does not match temporally committed identity")


def _validate_scoped_record_binding(
    *,
    scoped,
    record: AuthorizationRecord,
    ledger_batch_seq: int,
    commit: StrongDecisionCommit,
) -> None:
    target_id = scoped.target_ref.id if scoped.target_ref else None
    target_version = scoped.target_ref.version if scoped.target_ref else None
    if (
        record.contract_artifact_id != scoped.contract_artifact_id
        or record.entity_definition_hash != scoped.entity_definition_hash
        or record.scope != scoped.scope.value
        or record.scope_ref != scoped.scope_ref
        or record.target_id != target_id
        or record.target_version != target_version
    ):
        raise TemporalIntegrityError("scoped authorization metadata was not temporally committed")
    if scoped.scope is AuthorizationScope.COMMIT_TIME:
        if scoped.scope_ref != commit.commit_id:
            raise TemporalIntegrityError("COMMIT_TIME authority references the wrong commit")
        # V1 freezes semantic binding in the same atomic batch that commits D-104.
        if ledger_batch_seq != commit.commit_cutoff_seq:
            raise TemporalIntegrityError("COMMIT_TIME semantic binding was not recorded in commit batch")


def _validated_scoped_commit_authorizations(
    *,
    registry: M21Registry,
    ledger,
    commit: StrongDecisionCommit,
    policies: AuthorityPolicies,
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
        _validate_scoped_record_binding(
            scoped=scoped,
            record=record,
            ledger_batch_seq=ledger_entry.batch_seq,
            commit=commit,
        )

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
        policy = policies.get((record.policy_version, record.policy_hash))
        if policy is None:
            raise TemporalIntegrityError("historical authorization policy artifact is unavailable")
        replayed = policy.authorize_candidate(
            evidence=evidence,
            candidate=candidate,
            authorization_id=record.id,
        )
        if (
            replayed.entity_id != record.entity_id
            or replayed.authorized_assertion is not record.authorized_assertion
            or replayed.evidence_ids != record.evidence_ids
            or replayed.policy_version != record.policy_version
            or replayed.policy_hash != record.policy_hash
        ):
            raise TemporalIntegrityError("persisted authorization does not reproduce under historical policy")
        validated.append((scoped, record))

    return tuple(sorted(validated, key=lambda item: item[0].authorization_id))


def _reject_conflicting_authority(entity_id: str, assertions: set[AuthorizedAssertion]) -> None:
    groups = (
        {
            AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
            AuthorizedAssertion.T0_UNRESOLVED,
        },
        {
            AuthorizedAssertion.COMPOSITION_TRUE,
            AuthorizedAssertion.COMPOSITION_FALSE,
            AuthorizedAssertion.T0_UNRESOLVED,
        },
    )
    for group in groups:
        if len(assertions & group) > 1:
            raise TemporalIntegrityError(f"CONFLICTING_AUTHORIZED_ASSERTIONS:{entity_id}")


def _required_target_authority(
    contract: DecisionContract,
    target: Optional[SafeReuseTargetSpec],
) -> dict[str, AuthorizedAssertion]:
    if target is None:
        relation_ids = {relation.id for relation in contract.historical_relations}
        match_rule_ids = {rule.id for rule in contract.current_match_rules}
        revisit_ids = {rule.id for rule in contract.revisit_rules}
    else:
        bindings = target.changed_bindings + target.surviving_bindings
        relation_ids = {binding.historical_relation_id for binding in bindings}
        match_rule_ids = {binding.current_match_rule_id for binding in bindings}
        revisit_ids = set(target.revisit_rule_ids)

    required: dict[str, AuthorizedAssertion] = {}
    for relation_id in relation_ids:
        relation = contract.historical_relation(relation_id)
        required[relation.id] = AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE
        required[relation.subject_id] = AuthorizedAssertion.ESTABLISHED_FACT
    for rule_id in match_rule_ids:
        required[rule_id] = AuthorizedAssertion.CURRENT_MATCH_RULE
    for rule_id in revisit_ids:
        required[rule_id] = AuthorizedAssertion.REVISIT_RULE
    return required


def strict_materialize_committed_contract(
    *,
    registry: M21Registry,
    ledger,
    commit: StrongDecisionCommit,
    authority_policy: Optional[AuthorityPolicy] = None,
    authority_policies: Optional[AuthorityPolicies] = None,
    target: Optional[SafeReuseTargetSpec] = None,
) -> DecisionContract:
    artifact = registry.artifacts.get(commit.contract_artifact_id)
    if artifact is None or artifact.content_hash != commit.contract_hash:
        raise TemporalIntegrityError("cannot materialize missing committed contract artifact")
    original = contract_from_artifact(artifact)
    policies = _authority_policy_map(
        authority_policy=authority_policy,
        authority_policies=authority_policies,
    )
    validated = _validated_scoped_commit_authorizations(
        registry=registry,
        ledger=ledger,
        commit=commit,
        policies=policies,
    )
    by_entity: dict[str, list[tuple]] = {}
    for scoped, record in validated:
        by_entity.setdefault(scoped.entity_id, []).append((scoped, record))

    for entity_id, items in by_entity.items():
        _reject_conflicting_authority(
            entity_id,
            {item[0].authorized_assertion for item in items},
        )

    # A committed ContractArtifact defines slots/rules, but the Target may consume
    # them only when their semantic role was positively authorized at commit time.
    for entity_id, expected in _required_target_authority(original, target).items():
        assertions = {item[0].authorized_assertion for item in by_entity.get(entity_id, [])}
        if expected not in assertions:
            raise TemporalIntegrityError(
                f"MISSING_COMMIT_TIME_SEMANTIC_AUTHORITY:{entity_id}:{expected.value}"
            )

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
        _reject_conflicting_authority(composition.id, assertions)
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
            # Slot exists in committed artifact but no assertion about sufficiency was
            # authorized: absence remains NOT_DURABLY_RECORDED, not an error.
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
    event_policies: Mapping[tuple[str, str], EventPolicy],
    engine_version: str,
    engine_hash: str,
    authority_policy: Optional[AuthorityPolicy] = None,
    authority_policies: Optional[AuthorityPolicies] = None,
) -> CanonicalEvaluationResult:
    if evaluation.engine_version != engine_version or evaluation.engine_hash != engine_hash:
        raise TemporalIntegrityError("engine artifact identity mismatch")
    if evaluation.canonicalization_version != CANONICALIZATION_V1:
        raise TemporalIntegrityError("unsupported replay canonicalization version")
    commit = registry.commits.get(evaluation.decision_commit_id)
    if commit is None:
        raise TemporalIntegrityError("ghost evaluation: commit does not exist")
    validate_commit_identity_in_ledger(ledger=ledger, commit=commit)
    if commit.commit_cutoff_seq > evaluation.input_cutoff_seq:
        raise TemporalIntegrityError("evaluation cutoff precedes commit")
    if commit.contract_hash != evaluation.contract_hash:
        raise TemporalIntegrityError("evaluation contract hash differs from committed contract")

    policies = _authority_policy_map(
        authority_policy=authority_policy,
        authority_policies=authority_policies,
    )
    evaluation_policy_ref = (
        evaluation.authority_policy_version,
        evaluation.authority_policy_hash,
    )
    if evaluation_policy_ref not in policies:
        raise TemporalIntegrityError("evaluation authority policy artifact identity mismatch")

    target_artifact = registry.artifacts.get(evaluation.target_artifact_id)
    schema_artifact = registry.artifacts.get(evaluation.world_schema_artifact_id)
    if target_artifact is None or target_artifact.content_hash != evaluation.target_hash:
        raise TemporalIntegrityError("target artifact/hash mismatch")
    if schema_artifact is None or schema_artifact.content_hash != evaluation.world_schema_hash:
        raise TemporalIntegrityError("world-schema artifact/hash mismatch")
    event_policy_ref = (evaluation.event_policy_version, evaluation.event_policy_hash)
    if event_policy_ref not in event_policies:
        raise TemporalIntegrityError("event policy artifact identity mismatch")

    target = target_from_artifact(target_artifact)
    contract = strict_materialize_committed_contract(
        registry=registry,
        ledger=ledger,
        commit=commit,
        authority_policies=policies,
        target=target,
    )
    metric_specs = world_schema_from_artifact(schema_artifact)
    world_state = authorized_world_state_at(
        ledger=ledger,
        cutoff_seq=evaluation.input_cutoff_seq,
        world_time=evaluation.world_time,
        event_policies=event_policies,
        metric_specs=metric_specs,
        required_policy_ref=event_policy_ref,
    )
    result = evaluate_target(
        contract=validate_contract(contract),
        world_state=world_state,
        target=target,
    )
    return canonicalize_target_evaluation(result)


def _verify_evaluation_output_binding(*, ledger, evaluation: StrongEvaluationSnapshot) -> None:
    try:
        entry = ledger.entry(evaluation.evaluation_id)
    except KeyError as exc:
        raise TemporalIntegrityError("strong evaluation snapshot is not temporally recorded") from exc
    if entry.kind is not LedgerEntryKind.EVALUATION:
        raise TemporalIntegrityError("evaluation ledger entry has wrong kind")
    if entry.batch_seq <= evaluation.input_cutoff_seq:
        raise TemporalIntegrityError("evaluation output batch must be after its input cutoff")
    payload = entry.payload
    if not isinstance(payload, EvaluationSnapshot):
        raise TemporalIntegrityError("evaluation ledger payload type mismatch")
    if (
        payload.decision_commit_id != evaluation.decision_commit_id
        or payload.contract_hash != evaluation.contract_hash
        or payload.input_cutoff_seq != evaluation.input_cutoff_seq
        or payload.world_time != evaluation.world_time
        or payload.target_artifact_id != evaluation.target_artifact_id
        or payload.target_hash != evaluation.target_hash
        or payload.world_schema_artifact_id != evaluation.world_schema_artifact_id
        or payload.world_schema_hash != evaluation.world_schema_hash
        or payload.evidence_policy_version != evaluation.authority_policy_version
        or payload.evidence_policy_hash != evaluation.authority_policy_hash
        or payload.event_policy_version != evaluation.event_policy_version
        or payload.event_policy_hash != evaluation.event_policy_hash
        or payload.engine_version != evaluation.engine_version
        or payload.engine_hash != evaluation.engine_hash
        or payload.result_fingerprint != evaluation.result_hash
        or payload.canonical_result_json != evaluation.canonical_result.canonical_json()
        or payload.canonicalization_version != evaluation.canonicalization_version
    ):
        raise TemporalIntegrityError("strong evaluation result was not temporally committed exactly")


def strict_verify_full_replay(
    *,
    registry: M21Registry,
    ledger,
    evaluation_id: str,
    event_policies: Mapping[tuple[str, str], EventPolicy],
    engine_version: str,
    engine_hash: str,
    authority_policy: Optional[AuthorityPolicy] = None,
    authority_policies: Optional[AuthorityPolicies] = None,
) -> CanonicalEvaluationResult:
    evaluation = registry.evaluations.get(evaluation_id)
    if evaluation is None:
        raise TemporalIntegrityError("evaluation snapshot not found")
    _verify_evaluation_output_binding(ledger=ledger, evaluation=evaluation)
    replayed = strict_full_replay(
        registry=registry,
        ledger=ledger,
        evaluation=evaluation,
        authority_policy=authority_policy,
        authority_policies=authority_policies,
        event_policies=event_policies,
        engine_version=engine_version,
        engine_hash=engine_hash,
    )
    if replayed != evaluation.canonical_result:
        raise TemporalIntegrityError("full replay canonical result differs from stored result")
    if replayed.result_hash() != evaluation.result_hash:
        raise TemporalIntegrityError("full replay result hash mismatch")
    return replayed
