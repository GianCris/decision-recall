"""One request-local lifecycle for registered, single-slot decision profiles.

The Golden* type/field names are legacy compatibility shapes, not case dispatch.
Only the registry supplies configuration; only ledger/policy processing establishes
authority. No source records, metric thresholds or scenario outcomes live here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta, datetime
from types import MappingProxyType
from typing import Mapping

from ..domain import (
    CompositionValue,
    DecisionContract,
    HistoricalKnowledgeState,
    MetricSpec,
    RelationCandidate,
    SafeReuseTargetSpec,
)
from ..m21 import (
    AuthorizationScope,
    CANONICALIZATION_V1,
    CanonicalArtifact,
    CanonicalEvaluationResult,
    M21Registry,
    ScopedAuthorization,
    StrongDecisionCommit,
    StrongEvaluationSnapshot,
    entity_definition_hash,
    make_contract_artifact,
    make_target_artifact,
    make_world_schema_artifact,
)
from ..m21_strict import (
    strict_full_replay,
    strict_materialize_committed_contract,
    strict_verify_full_replay,
)
from ..temporal import (
    AuthorizedAssertion,
    CandidateAssertion,
    DecisionCommitRecord,
    EvaluationSnapshot,
    InMemoryTemporalLedger,
    LedgerEntryKind,
    PendingLedgerEntry,
    RawWorldEvidence,
    EventPolicy,
    TemporalEvidenceRecord,
    TemporalIntegrityError,
    TemporalReference,
    authority_policy_v1,
    event_policy_v1,
    recorded_historical_view,
    source_hash,
)
from .capture import (
    CaptureProfile,
    CaptureSessionState,
    CriticalGap,
    DecisionStructure,
    ProfileAssignment,
    ProfileBinder,
    ProfileBindingTrace,
    assign_profile,
    candidate_fills_gap,
    composition_question_eligible,
    make_capture_profile_artifact,
    plan_questions,
    select_critical_gaps,
)
from .compiler import (
    CandidateBundle,
    CandidateCompiler,
    EvidenceResolver,
    ObservableDecisionBundle,
    ResolvedGroundedCandidate,
    SemanticCandidateResolver,
)
from .declaration import (
    CaptureAnswer,
    declaration_to_evidence,
    make_structured_capture_declaration,
)
from .definitions import DecisionRegistry

ENGINE_VERSION = "0.2.1-product-v1"
ENGINE_HASH = "decision-recall-product-checkpoint-1"


@dataclass(frozen=True)
class GoldenCapturePreparation:
    profile: CaptureProfile
    profile_artifact: CanonicalArtifact
    binding_trace: ProfileBindingTrace
    assignment: ProfileAssignment
    session: CaptureSessionState
    draft_contract: DecisionContract
    decision_structure: DecisionStructure
    observable: ObservableDecisionBundle
    compiler_candidates: CandidateBundle
    resolved_precommit_candidates: tuple[ResolvedGroundedCandidate, ...]
    precommit_evidence: tuple[TemporalEvidenceRecord, ...]
    ledger: InMemoryTemporalLedger
    authority_policy: object
    known_fact_ids: frozenset[str]
    established_relation_ids: frozenset[str]
    critical_gaps: tuple[CriticalGap, ...]


@dataclass(frozen=True)
class GoldenT0Completion:
    """Canonical post-capture state before any later-world evidence exists."""

    preparation: GoldenCapturePreparation
    registry: M21Registry
    contract_artifact: CanonicalArtifact
    target: SafeReuseTargetSpec
    target_artifact: CanonicalArtifact
    metric_specs: Mapping[str, MetricSpec]
    world_schema_artifact: CanonicalArtifact
    event_policy: EventPolicy
    commit: StrongDecisionCommit
    materialized_contract: DecisionContract
    r2_candidate: RelationCandidate
    r2_evidence_id: str
    r2_authorization_id: str

    @property
    def ledger(self) -> InMemoryTemporalLedger:
        return self.preparation.ledger

    @property
    def authority_policy(self):
        return self.preparation.authority_policy


@dataclass(frozen=True)
class GoldenReevaluation:
    """Canonical T1 result produced only after explicit later evidence is supplied."""

    completion: GoldenT0Completion
    evaluation: StrongEvaluationSnapshot
    output: EvaluationSnapshot
    replayed_result: CanonicalEvaluationResult


def _preauthorize_compiler_evidence(
    *,
    ledger: InMemoryTemporalLedger,
    authority_policy,
    observable: ObservableDecisionBundle,
    contract: DecisionContract,
    profile: CaptureProfile,
    candidates: CandidateBundle,
    decision_time: datetime,
    namespace: str,
) -> tuple[tuple[ResolvedGroundedCandidate, ...], tuple[TemporalEvidenceRecord, ...]]:
    semantic_resolver = SemanticCandidateResolver()
    evidence_resolver = EvidenceResolver()
    entries: list[PendingLedgerEntry] = []
    resolved_candidates: list[ResolvedGroundedCandidate] = []
    evidence_records: list[TemporalEvidenceRecord] = []

    for candidate in candidates.candidates:
        resolved = semantic_resolver.resolve(candidate=candidate, contract=contract, profile=profile)
        evidence = evidence_resolver.resolve(
            observable=observable,
            candidate=resolved,
            evidence_id=f"PRE-{resolved.entity_id}-{namespace}",
        )
        auth = authority_policy.authorize_candidate(
            evidence=evidence,
            candidate=evidence.candidate_assertions[0],
            authorization_id=f"PREAUTH-{resolved.entity_id}-{namespace}",
        )
        entries.extend(
            (
                PendingLedgerEntry(LedgerEntryKind.EVIDENCE, evidence),
                PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, auth),
            )
        )
        resolved_candidates.append(resolved)
        evidence_records.append(evidence)

    if entries:
        ledger.append_batch(recorded_at=decision_time - timedelta(seconds=3), entries=tuple(entries))
    return tuple(resolved_candidates), tuple(evidence_records)


def _derive_t0_authorized_state(
    *,
    ledger: InMemoryTemporalLedger,
    authority_policy,
    contract: DecisionContract,
) -> tuple[frozenset[str], frozenset[str]]:
    view = recorded_historical_view(
        ledger,
        cutoff_seq=ledger.head_seq,
        policies={(authority_policy.version, authority_policy.policy_hash): authority_policy},
    )
    known_facts = frozenset(
        claim.id
        for claim in contract.claims
        if AuthorizedAssertion.ESTABLISHED_FACT in view.assertions_for(claim.id)
    )
    established_relations = frozenset(
        relation.id
        for relation in contract.historical_relations
        if AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE in view.assertions_for(relation.id)
    )
    return known_facts, established_relations


def prepare_decision(
    *,
    decisions: DecisionRegistry,
    decision_id: str,
    compiler: CandidateCompiler,
) -> GoldenCapturePreparation:
    """Resolve registered data, ground candidates, and issue the bounded question."""

    definition, instance, identity = decisions.resolve(decision_id)
    observable = definition.observable(instance)
    draft = definition.contract(instance)
    structure = definition.structure(instance)
    template = definition.capture_template
    decision_time = instance.decision_time
    profile, binding_trace = ProfileBinder().bind(template=template, structure=structure)
    artifact = make_capture_profile_artifact(profile)
    if binding_trace.instantiated_profile_hash != artifact.content_hash:
        raise RuntimeError("binder trace must reproduce exact instantiated profile hash")

    assignment = assign_profile(
        session_id=f"CAPTURE-{decision_id}-{identity.namespace}",
        artifact=artifact,
        assigned_at=decision_time - timedelta(seconds=4),
    )

    ledger = InMemoryTemporalLedger()
    authority_policy = authority_policy_v1()
    candidates = compiler.compile_observable(observable=observable, profile=profile)
    resolved_candidates, evidence = _preauthorize_compiler_evidence(
        ledger=ledger,
        authority_policy=authority_policy,
        observable=observable,
        contract=draft,
        profile=profile,
        candidates=candidates,
        decision_time=decision_time,
        namespace=identity.namespace,
    )
    known_fact_ids, established_relation_ids = _derive_t0_authorized_state(
        ledger=ledger,
        authority_policy=authority_policy,
        contract=draft,
    )

    gaps = select_critical_gaps(
        profile=profile,
        assignment=assignment,
        decision_id=draft.id,
        known_fact_ids=known_fact_ids,
        established_relation_ids=established_relation_ids,
        selected_at=decision_time - timedelta(seconds=2),
    )
    initial_session = CaptureSessionState(assignment=assignment, budget_total=profile.question_budget)
    planned = plan_questions(session=initial_session, eligible_relation_gaps=gaps)
    if planned != (profile.slots[0].slot.id,):
        raise RuntimeError("bounded capture must plan exactly the assigned unresolved relation slot")
    session = initial_session.issue(planned[0])

    if composition_question_eligible(
        composition=draft.composition(definition.target.limiting_composition_id),
        established_relation_ids=established_relation_ids,
    ):
        raise RuntimeError("limiting composition cannot be eligible before surviving historical role is established")

    return GoldenCapturePreparation(
        profile=profile,
        profile_artifact=artifact,
        binding_trace=binding_trace,
        assignment=assignment,
        session=session,
        draft_contract=draft,
        decision_structure=structure,
        observable=observable,
        compiler_candidates=candidates,
        resolved_precommit_candidates=resolved_candidates,
        precommit_evidence=evidence,
        ledger=ledger,
        authority_policy=authority_policy,
        known_fact_ids=known_fact_ids,
        established_relation_ids=established_relation_ids,
        critical_gaps=gaps,
    )


def _verify_preparation(preparation, *, definition, instance, identity):
    """Bind every phase to the same registered records/configuration before mutation."""
    profile, trace = ProfileBinder().bind(template=definition.capture_template, structure=definition.structure(instance))
    artifact = make_capture_profile_artifact(profile)
    assignment = assign_profile(
        session_id=f"CAPTURE-{instance.decision_id}-{identity.namespace}", artifact=artifact,
        assigned_at=instance.decision_time - timedelta(seconds=4),
    )
    if (preparation.observable != definition.observable(instance)
            or preparation.draft_contract != definition.contract(instance)
            or preparation.decision_structure != definition.structure(instance)
            or preparation.profile != profile or preparation.profile_artifact != artifact
            or preparation.binding_trace != trace or preparation.assignment != assignment
            or preparation.session.assignment != assignment):
        raise ValueError("preparation does not match registered decision/profile binding")
    gaps = select_critical_gaps(
        profile=profile, assignment=assignment, decision_id=instance.decision_id,
        known_fact_ids=preparation.known_fact_ids,
        established_relation_ids=preparation.established_relation_ids,
        selected_at=instance.decision_time - timedelta(seconds=2),
    )
    session = CaptureSessionState(assignment=assignment, budget_total=profile.question_budget)
    planned = plan_questions(session=session, eligible_relation_gaps=gaps)
    if (len(planned) != 1 or preparation.critical_gaps != gaps
            or preparation.session != session.issue(planned[0])):
        raise ValueError("preparation question/session differs from assigned capture")


def _bound_authorization(
    *,
    registry: M21Registry,
    authority_policy,
    contract: DecisionContract,
    contract_artifact: CanonicalArtifact,
    evidence: TemporalEvidenceRecord,
    entity_id: str,
    assertion: AuthorizedAssertion,
    commit_id: str,
    namespace: str,
):
    raw = authority_policy.authorize_candidate(
        evidence=evidence,
        candidate=evidence.candidate_assertions[0],
        authorization_id=f"AUTH-{entity_id}-{assertion.value}-{namespace}",
    )
    bound = replace(
        raw,
        contract_artifact_id=contract_artifact.artifact_id,
        entity_definition_hash=entity_definition_hash(contract, entity_id),
        scope=AuthorizationScope.COMMIT_TIME.value,
        scope_ref=commit_id,
    )
    registry.add_authorization(
        ScopedAuthorization(
            authorization_id=bound.id,
            contract_artifact_id=contract_artifact.artifact_id,
            entity_id=entity_id,
            entity_definition_hash=bound.entity_definition_hash,
            authorized_assertion=assertion,
            evidence_id=evidence.id,
            policy_version=bound.policy_version,
            policy_hash=bound.policy_hash,
            scope=AuthorizationScope.COMMIT_TIME,
            scope_ref=commit_id,
        )
    )
    return bound


def _configured_rule_evidence(
    *,
    observable: ObservableDecisionBundle,
    evidence_id: str,
    entity_id: str,
    assertion: AuthorizedAssertion,
    quote: str,
    source_id: str,
) -> TemporalEvidenceRecord:
    source = observable.source_map()[source_id]
    start = source.content.find(quote)
    if start < 0:
        raise RuntimeError("configured rule source quote is absent from observable policy")
    exact = source.content[start:start + len(quote)]
    return TemporalEvidenceRecord(
        id=evidence_id,
        content=exact,
        source_id=source.source_id,
        source_span=f"chars:{start}-{start + len(quote)}",
        source_content_hash=source_hash(exact),
        provenance_type=source.provenance_type,
        temporal_reference=TemporalReference.point(source.observed_at),
        candidate_assertions=(CandidateAssertion(entity_id, assertion),),
    )


def complete_decision_capture(
    preparation: GoldenCapturePreparation,
    *,
    decisions: DecisionRegistry,
    capture_answer: CaptureAnswer,
    optional_note: str = "",
) -> GoldenT0Completion:
    """Complete verified human capture through T0, without creating future state."""

    definition, instance, identity = decisions.resolve(preparation.draft_contract.id)
    _verify_preparation(preparation, definition=definition, instance=instance, identity=identity)
    decision_time = instance.decision_time
    profile = preparation.profile
    profile_artifact = preparation.profile_artifact
    assignment = preparation.assignment
    session = preparation.session
    contract = preparation.draft_contract
    gaps = preparation.critical_gaps
    observable = preparation.observable
    ledger = preparation.ledger
    authority_policy = preparation.authority_policy

    registry = M21Registry()
    registry.add_artifact(profile_artifact)
    contract_artifact = make_contract_artifact(contract, version=identity.contract_version)
    target = definition.target
    target_artifact = make_target_artifact(target)
    metric_specs = {item.key: item for item in definition.metric_specs}
    schema_artifact = make_world_schema_artifact(metric_specs, version=definition.schema_version)
    for artifact in (contract_artifact, target_artifact, schema_artifact):
        registry.add_artifact(artifact)

    declaration = make_structured_capture_declaration(
        session=session,
        gap=gaps[0],
        answer=capture_answer,
        answered_at=decision_time - timedelta(seconds=1),
        optional_note=optional_note,
    )
    captured_evidence = declaration_to_evidence(
        declaration=declaration,
        session=session,
        gap=gaps[0],
        evidence_id=f"E-{gaps[0].slot_id}-ELICITED-{identity.namespace}",
    )
    ledger.append_batch(
        recorded_at=decision_time - timedelta(milliseconds=500),
        entries=(PendingLedgerEntry(LedgerEntryKind.EVIDENCE, captured_evidence),),
    )
    if capture_answer is not CaptureAnswer.YES or len(captured_evidence.candidate_assertions) != 1:
        raise ValueError(f"{gaps[0].slot_id} remains NOT_DURABLY_RECORDED without an explicit authorized YES declaration")

    captured_entity_id = gaps[0].slot_id
    relation = contract.relation(captured_entity_id)
    captured_candidate = RelationCandidate(
        id=declaration.id,
        relation_type=relation.relation_type,
        subject_id=relation.subject_id,
        object_id=relation.object_id,
        evidence_refs=(captured_evidence.id,),
    )
    if not candidate_fills_gap(profile=profile, gap=gaps[0], candidate=captured_candidate):
        raise RuntimeError("structured declaration does not fill the pre-assigned slot")

    precommit_by_entity = {
        item.candidate_assertions[0].entity_id: item
        for item in preparation.precommit_evidence
    }
    rule_evidence = {
        spec.entity_id: _configured_rule_evidence(
            observable=observable,
            evidence_id=f"E-{spec.entity_id}-{identity.namespace}",
            entity_id=spec.entity_id, assertion=spec.assertion,
            quote=spec.quote, source_id=spec.source_id,
        )
        for spec in definition.rule_evidence
    }

    commit_entries: list[PendingLedgerEntry] = []
    auth_ids: dict[str, str] = {}
    commit_authority_specs = (
        tuple((item.id, AuthorizedAssertion.ESTABLISHED_FACT, precommit_by_entity[item.id], False)
              for item in contract.claims)
        + tuple((item.id, AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE,
                 captured_evidence if item.id == captured_entity_id else precommit_by_entity[item.id], False)
                for item in contract.historical_relations)
        + tuple((spec.entity_id, spec.assertion, rule_evidence[spec.entity_id], True)
                for spec in definition.rule_evidence)
    )
    for entity_id, assertion, evidence, include_evidence in commit_authority_specs:
        if include_evidence:
            commit_entries.append(PendingLedgerEntry(LedgerEntryKind.EVIDENCE, evidence))
        bound = _bound_authorization(
            registry=registry,
            authority_policy=authority_policy,
            contract=contract,
            contract_artifact=contract_artifact,
            evidence=evidence,
            entity_id=entity_id,
            assertion=assertion,
            commit_id=identity.commit_id,
            namespace=identity.namespace,
        )
        auth_ids[entity_id] = bound.id
        commit_entries.append(PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, bound))

    ledger_commit = DecisionCommitRecord(
        id=identity.commit_id,
        decision_id=contract.id,
        contract_version=identity.contract_version,
        capture_profile_version=assignment.profile_version,
        capture_profile_hash=assignment.profile_hash,
        contract_artifact_id=contract_artifact.artifact_id,
        contract_hash=contract_artifact.content_hash,
        canonicalization_version=CANONICALIZATION_V1,
    )
    commit_entries.append(PendingLedgerEntry(LedgerEntryKind.DECISION_COMMIT, ledger_commit))
    commit_batch = ledger.append_batch(recorded_at=decision_time, entries=tuple(commit_entries))
    commit = StrongDecisionCommit(
        commit_id=identity.commit_id,
        decision_id=contract.id,
        contract_artifact_id=contract_artifact.artifact_id,
        contract_hash=contract_artifact.content_hash,
        contract_version=identity.contract_version,
        capture_profile_version=assignment.profile_version,
        capture_profile_hash=assignment.profile_hash,
        commit_cutoff_seq=commit_batch.batch_seq,
    )
    registry.add_commit(commit)

    materialized = strict_materialize_committed_contract(
        registry=registry,
        ledger=ledger,
        commit=commit,
        authority_policy=authority_policy,
        target=target,
    )
    captured_relation = materialized.relation(captured_entity_id)
    if captured_relation.knowledge_state is not HistoricalKnowledgeState.ESTABLISHED:
        raise RuntimeError("captured relation must become ESTABLISHED only through temporal authority")

    established_after_answer = frozenset(
        item.id
        for item in materialized.historical_relations
        if item.knowledge_state is HistoricalKnowledgeState.ESTABLISHED
    )
    composition_eligible = composition_question_eligible(
        composition=materialized.composition(target.limiting_composition_id),
        established_relation_ids=established_after_answer,
    )
    if not composition_eligible:
        raise RuntimeError("limiting composition should become structurally eligible only after captured role is established")
    if session.remaining_budget != 0:
        raise RuntimeError("issuing the prospective question must consume the frozen interaction budget")
    if plan_questions(session=session, eligible_composition_ids=(target.limiting_composition_id,)) != ():
        raise RuntimeError("capture planner must not emit a composition after question budget is exhausted")

    if materialized.composition(target.limiting_composition_id).value is not CompositionValue.NOT_DURABLY_RECORDED:
        raise RuntimeError("limiting composition must remain unresolved at the T0 completion boundary")
    forbidden_kinds = {
        LedgerEntryKind.RAW_WORLD_EVIDENCE,
        LedgerEntryKind.WORLD_EVENT_AUTHORIZATION,
        LedgerEntryKind.EVALUATION,
    }
    if any(entry.kind in forbidden_kinds for entry in ledger.entries_as_of(ledger.head_seq)):
        raise RuntimeError("T0 completion cannot contain later-world evidence or evaluation")
    if commit.commit_cutoff_seq != ledger.head_seq:
        raise RuntimeError("T0 completion must end exactly at the decision commit cutoff")

    return GoldenT0Completion(
        preparation=preparation,
        registry=registry,
        contract_artifact=contract_artifact,
        target=target,
        target_artifact=target_artifact,
        metric_specs=MappingProxyType(metric_specs),
        world_schema_artifact=schema_artifact,
        event_policy=event_policy_v1(),
        commit=commit,
        materialized_contract=materialized,
        r2_candidate=captured_candidate,
        r2_evidence_id=captured_evidence.id,
        r2_authorization_id=auth_ids[captured_relation.id],
    )


def reevaluate_decision(
    completion: GoldenT0Completion,
    *,
    decisions: DecisionRegistry,
    later_world_evidence: tuple[RawWorldEvidence, ...],
    world_time: datetime,
) -> GoldenReevaluation:
    """Authorize explicit later-world evidence and strictly replay the committed decision."""

    definition, instance, identity = decisions.resolve(completion.preparation.draft_contract.id)
    _verify_preparation(completion.preparation, definition=definition, instance=instance, identity=identity)
    ledger = completion.ledger
    registry = completion.registry
    authority_policy = completion.authority_policy
    event_policy = completion.event_policy
    reevaluation_kinds = {
        LedgerEntryKind.RAW_WORLD_EVIDENCE,
        LedgerEntryKind.WORLD_EVENT_AUTHORIZATION,
        LedgerEntryKind.EVALUATION,
    }
    if any(entry.kind in reevaluation_kinds for entry in ledger.entries_as_of(ledger.head_seq)):
        raise TemporalIntegrityError("GoldenT0Completion has already entered reevaluation")
    event_policies = {(event_policy.version, event_policy.policy_hash): event_policy}
    world_entries: list[PendingLedgerEntry] = []
    for raw in later_world_evidence:
        auth = event_policy.authorize(raw=raw, metric_specs=completion.metric_specs)
        world_entries.extend(
            (
                PendingLedgerEntry(LedgerEntryKind.RAW_WORLD_EVIDENCE, raw),
                PendingLedgerEntry(LedgerEntryKind.WORLD_EVENT_AUTHORIZATION, auth),
            )
        )
    ledger.append_batch(recorded_at=world_time, entries=tuple(world_entries))

    placeholder = CanonicalEvaluationResult("placeholder", (), (), (), ())
    draft_eval = StrongEvaluationSnapshot(
        evaluation_id=identity.evaluation_id,
        decision_commit_id=completion.commit.commit_id,
        contract_hash=completion.commit.contract_hash,
        input_cutoff_seq=ledger.head_seq,
        world_time=world_time,
        target_artifact_id=completion.target_artifact.artifact_id,
        target_hash=completion.target_artifact.content_hash,
        world_schema_artifact_id=completion.world_schema_artifact.artifact_id,
        world_schema_hash=completion.world_schema_artifact.content_hash,
        authority_policy_version=authority_policy.version,
        authority_policy_hash=authority_policy.policy_hash,
        event_policy_version=event_policy.version,
        event_policy_hash=event_policy.policy_hash,
        engine_version=ENGINE_VERSION,
        engine_hash=ENGINE_HASH,
        canonical_result=placeholder,
        result_hash=placeholder.result_hash(),
    )
    result = strict_full_replay(
        registry=registry,
        ledger=ledger,
        evaluation=draft_eval,
        authority_policy=authority_policy,
        event_policies=event_policies,
        engine_version=ENGINE_VERSION,
        engine_hash=ENGINE_HASH,
    )
    final_eval = replace(draft_eval, canonical_result=result, result_hash=result.result_hash())
    registry.add_evaluation(final_eval)

    output = EvaluationSnapshot(
        id=final_eval.evaluation_id,
        decision_id=completion.preparation.draft_contract.id,
        input_cutoff_seq=final_eval.input_cutoff_seq,
        target_version=completion.target.version,
        target_hash=final_eval.target_hash,
        evidence_policy_version=final_eval.authority_policy_version,
        evidence_policy_hash=final_eval.authority_policy_hash,
        event_policy_version=final_eval.event_policy_version,
        event_policy_hash=final_eval.event_policy_hash,
        engine_version=final_eval.engine_version,
        engine_hash=final_eval.engine_hash,
        result_fingerprint=final_eval.result_hash,
        decision_commit_id=final_eval.decision_commit_id,
        contract_hash=final_eval.contract_hash,
        world_time=final_eval.world_time,
        target_artifact_id=final_eval.target_artifact_id,
        world_schema_artifact_id=final_eval.world_schema_artifact_id,
        world_schema_hash=final_eval.world_schema_hash,
        canonical_result_json=final_eval.canonical_result.canonical_json(),
        canonicalization_version=final_eval.canonicalization_version,
    )
    ledger.append_batch(
        recorded_at=world_time + timedelta(seconds=1),
        entries=(PendingLedgerEntry(LedgerEntryKind.EVALUATION, output),),
    )
    replayed = strict_verify_full_replay(
        registry=registry,
        ledger=ledger,
        evaluation_id=identity.evaluation_id,
        authority_policy=authority_policy,
        event_policies=event_policies,
        engine_version=ENGINE_VERSION,
        engine_hash=ENGINE_HASH,
    )

    return GoldenReevaluation(
        completion=completion,
        evaluation=final_eval,
        output=output,
        replayed_result=replayed,
    )
