from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Tuple


@dataclass(frozen=True)
class CaptureProfileView:
    artifact_id: str
    version: str
    content_hash: str
    assigned_at: datetime
    question_budget: int
    slot_ids: Tuple[str, ...]


@dataclass(frozen=True)
class CriticalGapView:
    slot_id: str
    question: str
    selected_at: datetime


@dataclass(frozen=True)
class CandidateView:
    """Compiler/capture candidate only; deliberately cannot encode epistemic status."""

    candidate_id: str
    relation_type: str
    subject_id: str
    object_id: str
    evidence_refs: Tuple[str, ...]


@dataclass(frozen=True)
class RelationTraceView:
    entity_id: str
    knowledge_state: str
    evidence_ids: Tuple[str, ...]
    authorization_ids: Tuple[str, ...]
    commit_id: str
    commit_batch_seq: int


@dataclass(frozen=True)
class CommitView:
    commit_id: str
    decision_id: str
    capture_profile_version: str
    capture_profile_hash: str
    commit_batch_seq: int


@dataclass(frozen=True)
class EvaluationView:
    safe_reuse_result: str
    limiting_requirements: Tuple[str, ...]
    reason_codes: Tuple[str, ...]
    current_matches: Tuple[Tuple[str, str], ...]
    review_states: Tuple[Tuple[str, str], ...]
    evaluation_id: str
    result_hash: str


@dataclass(frozen=True)
class EpistemicBoundaryView:
    limiting_entity_id: str
    composition_kind: str
    relation_ids: Tuple[str, ...]
    composition_value: str
    target_id: str
    target_version: str


@dataclass(frozen=True)
class GoldenLoopResult:
    capture_profile: CaptureProfileView
    critical_gaps: Tuple[CriticalGapView, ...]
    r2_candidate: CandidateView
    r2_trace: RelationTraceView
    commit: CommitView
    evaluation: EvaluationView
    boundary: EpistemicBoundaryView
    replay_result_hash: str
