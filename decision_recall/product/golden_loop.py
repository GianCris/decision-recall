"""D-104 compatibility composition; authority processing lives in lifecycle.

The shared path uses strict_full_replay / strict_verify_full_replay only.
Public legacy dataclass shapes, signatures, identities and presentation stay fixed.
"""
from __future__ import annotations

from datetime import datetime

from ..domain import NumericObservation, ProvenanceType
from ..temporal import RawWorldEvidence, TemporalReference, source_hash
from . import lifecycle
from .compiler import CandidateCompiler, DeterministicGoldenCompiler
from .d104 import COMMIT_ID, EVALUATION_ID, T0, T1, UTC, d104_registry
from .declaration import CaptureAnswer
from .lifecycle import (
    ENGINE_HASH, ENGINE_VERSION, GoldenCapturePreparation, GoldenReevaluation, GoldenT0Completion,
)
from .models import (
    CandidateView, CaptureProfileView, CommitView, CriticalGapView,
    EpistemicBoundaryView, EvaluationView, GoldenLoopResult, RelationTraceView,
)


def prepare_golden_capture(
    *,
    compiler: CandidateCompiler | None = None,
    decision_id: str = "D-104",
) -> GoldenCapturePreparation:
    return lifecycle.prepare_decision(
        decisions=d104_registry(decision_id=decision_id), decision_id=decision_id,
        compiler=compiler or DeterministicGoldenCompiler(),
    )


def complete_golden_capture(
    preparation: GoldenCapturePreparation,
    *,
    capture_answer: CaptureAnswer = CaptureAnswer.YES,
) -> GoldenT0Completion:
    return lifecycle.complete_decision_capture(
        preparation, decisions=d104_registry(decision_id=preparation.draft_contract.id),
        capture_answer=capture_answer,
        optional_note=(
            "Beacon's roughly 10-week reactivation delay materially influenced the decision."
            if capture_answer is CaptureAnswer.YES else ""
        ),
    )


def reevaluate_golden_decision(
    completion: GoldenT0Completion,
    *,
    later_world_evidence: tuple[RawWorldEvidence, ...],
    world_time: datetime,
) -> GoldenReevaluation:
    return lifecycle.reevaluate_decision(
        completion, decisions=d104_registry(decision_id=completion.preparation.draft_contract.id),
        later_world_evidence=later_world_evidence, world_time=world_time,
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



def default_golden_later_world_evidence() -> tuple[RawWorldEvidence, ...]:
    """Return the frozen D-104 later-world evidence used by the compatibility path."""

    return (
        _world_evidence("WE-BEACON-PRODUCT-V1", metric_key="beacon_reactivation_days", value=70, unit="days"),
        _world_evidence(
            "WE-E301-APEX-PRODUCT-V1",
            metric_key="apex_on_time_rate",
            value=0.987,
            unit="ratio",
            window_days=30,
        ),
    )



def _assemble_golden_loop_result(reevaluation: GoldenReevaluation) -> GoldenLoopResult:
    completion = reevaluation.completion
    preparation = completion.preparation
    profile = preparation.profile
    profile_artifact = preparation.profile_artifact
    assignment = preparation.assignment
    gaps = preparation.critical_gaps
    commit = completion.commit
    r2 = completion.materialized_contract.relation("R2")
    c1 = completion.materialized_contract.composition("C1")
    result = reevaluation.evaluation.canonical_result

    if result.limiting_requirements != ("C1",):
        raise RuntimeError("golden result must expose C1 as its exact limiting requirement")

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
            candidate_id=completion.r2_candidate.id,
            relation_type=completion.r2_candidate.relation_type.value,
            subject_id=completion.r2_candidate.subject_id,
            object_id=completion.r2_candidate.object_id,
            evidence_refs=completion.r2_candidate.evidence_refs,
        ),
        r2_trace=RelationTraceView(
            entity_id=r2.id,
            knowledge_state=r2.knowledge_state.value,
            evidence_ids=r2.evidence_refs,
            authorization_ids=(completion.r2_authorization_id,),
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
            evaluation_id=reevaluation.evaluation.evaluation_id,
            result_hash=reevaluation.evaluation.result_hash,
        ),
        boundary=EpistemicBoundaryView(
            limiting_entity_id=c1.id,
            composition_kind=c1.kind.value,
            relation_ids=c1.relation_ids,
            composition_value=c1.value.value,
            target_id=c1.target_ref.id,
            target_version=c1.target_ref.version,
        ),
        replay_result_hash=reevaluation.replayed_result.result_hash(),
    )


def run_golden_decision(
    *,
    answer_r2: bool = True,
    capture_answer: CaptureAnswer | None = None,
    compiler: CandidateCompiler | None = None,
) -> GoldenLoopResult:
    """Compatibility composition: prepare -> T0 capture -> explicit frozen T1 replay."""

    compiler = compiler or DeterministicGoldenCompiler()
    preparation = prepare_golden_capture(compiler=compiler)
    if capture_answer is None:
        capture_answer = CaptureAnswer.YES if answer_r2 else CaptureAnswer.SKIP
    completion = complete_golden_capture(preparation, capture_answer=capture_answer)
    reevaluation = reevaluate_golden_decision(
        completion,
        later_world_evidence=default_golden_later_world_evidence(),
        world_time=T1,
    )
    return _assemble_golden_loop_result(reevaluation)
