from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from ..domain import (
    CompositionValue,
    DecisionContract,
    HistoricalKnowledgeState,
    NumericObservation,
    ProvenanceType,
    RelationCandidate,
    RelationType,
)
from ..golden import safe_reuse_target_v1, supplier_metric_specs, supplier_resilience_contract
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
    TemporalEvidenceRecord,
    TemporalReference,
    authority_policy_v1,
    event_policy_v1,
    recorded_historical_view,
    source_hash,
)
from .capture import (
    CaptureInstantiationContext,
    CaptureProfile,
    CriticalGap,
    ProfileAssignment,
    assign_profile,
    candidate_fills_gap,
    composition_question_eligible,
    instantiate_capture_profile,
    make_capture_profile_artifact,
    select_critical_gaps,
    supplier_resilience_capture_template,
)
from .compiler import (
    CandidateBundle,
    CandidateCompiler,
    DeterministicGoldenCompiler,
    EvidenceResolver,
    ObservableDecisionBundle,
    SourceDocument,
)
from .models import (
    CandidateView,
    CaptureProfileView,
    CommitView,
    CriticalGapView,
    EpistemicBoundaryView,
    EvaluationView,
    GoldenLoopResult,
    RelationTraceView,
)

UTC = timezone.utc
T0 = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
ENGINE_VERSION = "0.2.1-product-v1"
ENGINE_HASH = "decision-recall-product-checkpoint-1"
COMMIT_ID = "COMMIT-D104-PRODUCT-V1"
EVALUATION_ID = "EV-901-PRODUCT-V1"


@dataclass(frozen=True)
class GoldenCapturePreparation:
    profile: CaptureProfile
    profile_artifact: CanonicalArtifact
    assignment: ProfileAssignment
    draft_contract: DecisionContract
    observable: ObservableDecisionBundle
    compiler_candidates: CandidateBundle
    precommit_evidence: tuple[TemporalEvidenceRecord, ...]
    ledger: InMemoryTemporalLedger
    authority_policy: object
    known_fact_ids: frozenset[str]
    established_relation_ids: frozenset[str]
    critical_gaps: tuple[CriticalGap, ...]


def _golden_observable() -> ObservableDecisionBundle:
    return ObservableDecisionBundle(
        decision_id="D-104",
        sources=(
            SourceDocument(
                source_id="decision-note",
                content=(
                    "Decision D-104: keep Apex and Beacon active for six months. "
                    "Apex delivery performance has been materially unstable. "
                    "Apex instability materially influenced the decision."
                ),
                provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
                observed_at=T0 - timedelta(minutes=5),
            ),
            SourceDocument(
                source_id="supplier-record",
                content="Beacon requires roughly 10 weeks to reactivate.",
                provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
                observed_at=T0 - timedelta(minutes=5),
            ),
            SourceDocument(
                source_id="policy-record",
                content=(
                    "Current supplier policy: Apex is considered stable after on-time delivery "
                    "reaches 97% for at least 30 days. Beacon remains reaction capacity while "
                    "reactivation is at least 70 days. Review supplier redundancy once Apex "
                    "reaches 97% for at least 30 days."
                ),
                provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
                observed_at=T0 - timedelta(minutes=5),
            ),
        ),
    )


def _draft_contract(*, decision_id: str = "D-104") -> DecisionContract:
    contract = supplier_resilience_contract(
        r2_state=HistoricalKnowledgeState.NOT_DURABLY_RECORDED,
        c1_value=CompositionValue.NOT_DURABLY_RECORDED,
    )
    return contract if decision_id == contract.id else replace(contract, id=decision_id)


def _preauthorize_compiler_evidence(
    *,
    ledger: InMemoryTemporalLedger,
    authority_policy,
    observable: ObservableDecisionBundle,
    candidates: CandidateBundle,
) -> tuple[TemporalEvidenceRecord, ...]:
    resolver = EvidenceResolver()
    entries: list[PendingLedgerEntry] = []
    evidence_records: list[TemporalEvidenceRecord] = []
    for candidate in candidates.candidates:
        evidence = resolver.resolve(
            observable=observable,
            candidate=candidate,
            evidence_id=f"PRE-{candidate.entity_id}-PRODUCT-V1",
        )
        auth = authority_policy.authorize_candidate(
            evidence=evidence,
            candidate=evidence.candidate_assertions[0],
            authorization_id=f"PREAUTH-{candidate.entity_id}-PRODUCT-V1",
        )
        entries.extend(
            (
                PendingLedgerEntry(LedgerEntryKind.EVIDENCE, evidence),
                PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, auth),
            )
        )
        evidence_records.append(evidence)
    ledger.append_batch(recorded_at=T0 - timedelta(seconds=3), entries=tuple(entries))
    return tuple(evidence_records)


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


def prepare_golden_capture(
    *,
    compiler: CandidateCompiler | None = None,
    decision_id: str = "D-104",
) -> GoldenCapturePreparation:
    """Freeze profile, ground t0 evidence, derive authorized state, then select gap."""

    compiler = compiler or DeterministicGoldenCompiler()
    observable = _golden_observable()
    if decision_id != observable.decision_id:
        observable = replace(observable, decision_id=decision_id)

    template = supplier_resilience_capture_template()
    profile = instantiate_capture_profile(
        template=template,
        context=CaptureInstantiationContext(
            decision_id=decision_id,
            relation_id="R2",
            subject_id="F2",
            subject_semantic_role="SUPPLIER_REACTIVATION_DELAY",
            subject_display="Beacon's roughly 10-week reactivation delay",
        ),
    )
    artifact = make_capture_profile_artifact(profile)
    assignment = assign_profile(
        session_id=f"CAPTURE-{decision_id}-PRODUCT-V1",
        artifact=artifact,
        assigned_at=T0 - timedelta(seconds=4),
    )
    draft = _draft_contract(decision_id=decision_id)

    ledger = InMemoryTemporalLedger()
    authority_policy = authority_policy_v1()
    candidates = compiler.compile_observable(observable=observable, profile=profile)
    evidence = _preauthorize_compiler_evidence(
        ledger=ledger,
        authority_policy=authority_policy,
        observable=observable,
        candidates=candidates,
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
        selected_at=T0 - timedelta(seconds=2),
    )
    if len(gaps) != 1 or gaps[0].slot_id != "R2":
        raise RuntimeError("golden capture must select exactly the unresolved R2 slot")
    if composition_question_eligible(
        composition=draft.composition("C1"),
        established_relation_ids=established_relation_ids,
    ):
        raise RuntimeError("C1 cannot be eligible before R2 historical role is established")

    return GoldenCapturePreparation(
        profile=profile,
        profile_artifact=artifact,
        assignment=assignment,
        draft_contract=draft,
        observable=observable,
        compiler_candidates=candidates,
        precommit_evidence=evidence,
        ledger=ledger,
        authority_policy=authority_policy,
        known_fact_ids=known_fact_ids,
        established_relation_ids=established_relation_ids,
        critical_gaps=gaps,
    )


def _bound_authorization(
    *,
    registry: M21Registry,
    authority_policy,
    contract: DecisionContract,
    contract_artifact: CanonicalArtifact,
    evidence: TemporalEvidenceRecord,
    entity_id: str,
    assertion: AuthorizedAssertion,
):
    raw = authority_policy.authorize_candidate(
        evidence=evidence,
        candidate=evidence.candidate_assertions[0],
        authorization_id=f"AUTH-{entity_id}-{assertion.value}-PRODUCT-V1",
    )
    bound = replace(
        raw,
        contract_artifact_id=contract_artifact.artifact_id,
        entity_definition_hash=entity_definition_hash(contract, entity_id),
        scope=AuthorizationScope.COMMIT_TIME.value,
        scope_ref=COMMIT_ID,
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
            scope_ref=COMMIT_ID,
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
) -> TemporalEvidenceRecord:
    source = observable.source_map()["policy-record"]
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


def _world_evidence(
    evidence_id: str,
    *,
    metric_key: str,
    value: float,
    unit: str,
    window_days: int | None = None,
) -> RawWorldEvidence:
    text = f"{metric_key}={value} {unit}"
    return RawWorldEvidence(
        id=evidence_id,
        content=text,
        source_id=f"erp-{evidence_id}",
        source_span="verified ERP metric",
        source_content_hash=source_hash(text),
        provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
        temporal_reference=TemporalReference.point(T1),
        observations=(NumericObservation(metric_key, value, unit=unit, window_days=window_days),),
    )


def run_golden_decision(
    *,
    answer_r2: bool = True,
    compiler: CandidateCompiler | None = None,
) -> GoldenLoopResult:
    """Trust-hardened winner loop: grounded t0 -> gap -> answer -> strict replay -> C1."""

    compiler = compiler or DeterministicGoldenCompiler()
    preparation = prepare_golden_capture(compiler=compiler)
    profile = preparation.profile
    profile_artifact = preparation.profile_artifact
    assignment = preparation.assignment
    contract = preparation.draft_contract
    gaps = preparation.critical_gaps
    observable = preparation.observable
    ledger = preparation.ledger
    authority_policy = preparation.authority_policy

    registry = M21Registry()
    registry.add_artifact(profile_artifact)
    contract_artifact = make_contract_artifact(contract, version="1")
    target = safe_reuse_target_v1()
    target_artifact = make_target_artifact(target)
    metric_specs = supplier_metric_specs()
    schema_artifact = make_world_schema_artifact(metric_specs, version="SUPPLIER_METRICS_V1")
    for artifact in (contract_artifact, target_artifact, schema_artifact):
        registry.add_artifact(artifact)

    raw_response = (
        "Yes. Beacon's roughly 10-week reactivation delay materially influenced the decision."
        if answer_r2
        else "No answer provided."
    )
    response_source = SourceDocument(
        source_id="user-gap-response-r2",
        content=raw_response,
        provenance_type=ProvenanceType.CONTEMPORANEOUS_ELICITED_DECLARATION,
        observed_at=T0 - timedelta(seconds=1),
    )
    response_candidates = compiler.compile_response(
        response_source=response_source,
        gap=gaps[0],
        profile=profile,
    )
    if len(response_candidates.candidates) != 1:
        raise ValueError("R2 remains NOT_DURABLY_RECORDED without authorized contemporaneous gap evidence")

    response_observable = ObservableDecisionBundle(contract.id, (response_source,))
    r2_grounded = response_candidates.candidates[0]
    r2_evidence = EvidenceResolver().resolve(
        observable=response_observable,
        candidate=r2_grounded,
        evidence_id="E-R2-ELICITED-PRODUCT-V1",
    )
    r2_candidate = RelationCandidate(
        id=r2_grounded.candidate_id,
        relation_type=RelationType.HISTORICAL_SUPPORT,
        subject_id="F2",
        object_id=contract.id,
        evidence_refs=(r2_evidence.id,),
    )
    if not candidate_fills_gap(profile=profile, gap=gaps[0], candidate=r2_candidate):
        raise RuntimeError("R2 candidate does not fill the pre-assigned slot")
    ledger.append_batch(
        recorded_at=T0 - timedelta(milliseconds=500),
        entries=(PendingLedgerEntry(LedgerEntryKind.EVIDENCE, r2_evidence),),
    )

    precommit_by_entity = {item.candidate_assertions[0].entity_id: item for item in preparation.precommit_evidence}
    rule_specs = (
        (
            "M1",
            AuthorizedAssertion.CURRENT_MATCH_RULE,
            "Apex is considered stable after on-time delivery reaches 97% for at least 30 days.",
        ),
        (
            "M2",
            AuthorizedAssertion.CURRENT_MATCH_RULE,
            "Beacon remains reaction capacity while reactivation is at least 70 days.",
        ),
        (
            "RC1",
            AuthorizedAssertion.REVISIT_RULE,
            "Review supplier redundancy once Apex reaches 97% for at least 30 days.",
        ),
    )
    rule_evidence = {
        entity_id: _configured_rule_evidence(
            observable=observable,
            evidence_id=f"E-{entity_id}-PRODUCT-V1",
            entity_id=entity_id,
            assertion=assertion,
            quote=quote,
        )
        for entity_id, assertion, quote in rule_specs
    }

    commit_entries: list[PendingLedgerEntry] = []
    auth_ids: dict[str, str] = {}
    commit_authority_specs = (
        ("F1", AuthorizedAssertion.ESTABLISHED_FACT, precommit_by_entity["F1"], False),
        ("F2", AuthorizedAssertion.ESTABLISHED_FACT, precommit_by_entity["F2"], False),
        ("R1", AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE, precommit_by_entity["R1"], False),
        ("R2", AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE, r2_evidence, False),
        ("M1", AuthorizedAssertion.CURRENT_MATCH_RULE, rule_evidence["M1"], True),
        ("M2", AuthorizedAssertion.CURRENT_MATCH_RULE, rule_evidence["M2"], True),
        ("RC1", AuthorizedAssertion.REVISIT_RULE, rule_evidence["RC1"], True),
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
        )
        auth_ids[entity_id] = bound.id
        commit_entries.append(PendingLedgerEntry(LedgerEntryKind.AUTHORIZATION, bound))

    ledger_commit = DecisionCommitRecord(
        id=COMMIT_ID,
        decision_id=contract.id,
        contract_version="1",
        capture_profile_version=assignment.profile_version,
        capture_profile_hash=assignment.profile_hash,
        contract_artifact_id=contract_artifact.artifact_id,
        contract_hash=contract_artifact.content_hash,
        canonicalization_version=CANONICALIZATION_V1,
    )
    commit_entries.append(PendingLedgerEntry(LedgerEntryKind.DECISION_COMMIT, ledger_commit))
    commit_batch = ledger.append_batch(recorded_at=T0, entries=tuple(commit_entries))
    commit = StrongDecisionCommit(
        commit_id=COMMIT_ID,
        decision_id=contract.id,
        contract_artifact_id=contract_artifact.artifact_id,
        contract_hash=contract_artifact.content_hash,
        contract_version="1",
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
    r2 = materialized.relation("R2")
    if r2.knowledge_state is not HistoricalKnowledgeState.ESTABLISHED:
        raise RuntimeError("R2 must become ESTABLISHED only through temporal authority")
    established_after_answer = frozenset(
        relation.id
        for relation in materialized.historical_relations
        if relation.knowledge_state is HistoricalKnowledgeState.ESTABLISHED
    )
    if not composition_question_eligible(
        composition=materialized.composition("C1"),
        established_relation_ids=established_after_answer,
    ):
        raise RuntimeError("C1 should become structurally eligible only after R2 is established")

    event_policy = event_policy_v1()
    event_policies = {(event_policy.version, event_policy.policy_hash): event_policy}
    world_entries: list[PendingLedgerEntry] = []
    for raw in (
        _world_evidence("WE-BEACON-PRODUCT-V1", metric_key="beacon_reactivation_days", value=70, unit="days"),
        _world_evidence("WE-E301-APEX-PRODUCT-V1", metric_key="apex_on_time_rate", value=0.987, unit="ratio", window_days=30),
    ):
        auth = event_policy.authorize(raw=raw, metric_specs=metric_specs)
        world_entries.extend(
            (
                PendingLedgerEntry(LedgerEntryKind.RAW_WORLD_EVIDENCE, raw),
                PendingLedgerEntry(LedgerEntryKind.WORLD_EVENT_AUTHORIZATION, auth),
            )
        )
    ledger.append_batch(recorded_at=T1, entries=tuple(world_entries))

    placeholder = CanonicalEvaluationResult("placeholder", (), (), (), ())
    draft_eval = StrongEvaluationSnapshot(
        evaluation_id=EVALUATION_ID,
        decision_commit_id=commit.commit_id,
        contract_hash=commit.contract_hash,
        input_cutoff_seq=ledger.head_seq,
        world_time=T1,
        target_artifact_id=target_artifact.artifact_id,
        target_hash=target_artifact.content_hash,
        world_schema_artifact_id=schema_artifact.artifact_id,
        world_schema_hash=schema_artifact.content_hash,
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
        decision_id=contract.id,
        input_cutoff_seq=final_eval.input_cutoff_seq,
        target_version=target.version,
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
        recorded_at=T1 + timedelta(seconds=1),
        entries=(PendingLedgerEntry(LedgerEntryKind.EVALUATION, output),),
    )
    replayed = strict_verify_full_replay(
        registry=registry,
        ledger=ledger,
        evaluation_id=EVALUATION_ID,
        authority_policy=authority_policy,
        event_policies=event_policies,
        engine_version=ENGINE_VERSION,
        engine_hash=ENGINE_HASH,
    )

    if result.limiting_requirements != ("C1",):
        raise RuntimeError("golden result must expose C1 as its exact limiting requirement")
    c1 = materialized.composition("C1")

    return GoldenLoopResult(
        capture_profile=CaptureProfileView(
            artifact_id=profile_artifact.artifact_id,
            version=profile.version,
            content_hash=profile_artifact.content_hash,
            template_id=profile.template_id,
            template_version=profile.template_version,
            assigned_at=assignment.assigned_at,
            question_budget=profile.question_budget,
            slot_ids=tuple(item.slot.id for item in profile.slots),
        ),
        critical_gaps=tuple(CriticalGapView(item.slot_id, item.question, item.selected_at) for item in gaps),
        r2_candidate=CandidateView(
            candidate_id=r2_candidate.id,
            relation_type=r2_candidate.relation_type.value,
            subject_id=r2_candidate.subject_id,
            object_id=r2_candidate.object_id,
            evidence_refs=r2_candidate.evidence_refs,
        ),
        r2_trace=RelationTraceView(
            entity_id="R2",
            knowledge_state=r2.knowledge_state.value,
            evidence_ids=r2.evidence_refs,
            authorization_ids=(auth_ids["R2"],),
            commit_id=commit.commit_id,
            commit_batch_seq=commit.commit_cutoff_seq,
        ),
        commit=CommitView(
            commit_id=commit.commit_id,
            decision_id=commit.decision_id,
            capture_profile_version=commit.capture_profile_version,
            capture_profile_hash=commit.capture_profile_hash,
            commit_batch_seq=commit.commit_cutoff_seq,
        ),
        evaluation=EvaluationView(
            safe_reuse_result=result.safe_reuse_result,
            limiting_requirements=result.limiting_requirements,
            reason_codes=result.reason_codes,
            current_matches=result.current_matches,
            review_states=result.review_states,
            evaluation_id=final_eval.evaluation_id,
            result_hash=final_eval.result_hash,
        ),
        boundary=EpistemicBoundaryView(
            limiting_entity_id=c1.id,
            composition_kind=c1.kind.value,
            relation_ids=c1.relation_ids,
            composition_value=c1.value.value,
            target_id=c1.target_ref.id,
            target_version=c1.target_ref.version,
        ),
        replay_result_hash=replayed.result_hash(),
    )
