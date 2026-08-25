from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .models import GoldenLoopResult


@dataclass(frozen=True)
class CurrentMatchPresentation:
    """Read-only current-world state copied from the frozen evaluation."""

    entity_id: str
    state: str


@dataclass(frozen=True)
class CapturePresentation:
    """The one prospective question and the historical relation it establishes."""

    question: str
    relation_id: str
    knowledge_state: str


@dataclass(frozen=True)
class ReuseBoundaryPresentation:
    """The exact engine boundary that prevents unsupported reuse."""

    safe_reuse_result: str
    limiting_requirements: Tuple[str, ...]
    limiting_entity_id: str
    composition_kind: str
    composition_value: str
    relation_ids: Tuple[str, ...]


@dataclass(frozen=True)
class DecisionThreadsPresentation:
    """Judge-facing read model for the winner slice.

    This DTO deliberately performs no authority inference, no temporal
    recomputation, and no LLM work.  It only projects fields already emitted by
    the frozen GoldenLoopResult into a shape the UI can animate safely.
    """

    decision_id: str
    capture: CapturePresentation
    current_matches: Tuple[CurrentMatchPresentation, ...]
    reuse_boundary: ReuseBoundaryPresentation
    evaluation_hash: str
    replay_hash: str


def build_decision_threads_presentation(result: GoldenLoopResult) -> DecisionThreadsPresentation:
    """Project frozen winner-loop output into a read-only presentation DTO.

    The adapter intentionally rejects ambiguous golden outputs instead of
    inventing UI state.  Human-readable copy and geometry belong in the visual
    layer; epistemic state always comes from ``GoldenLoopResult``.
    """

    if len(result.critical_gaps) != 1:
        raise ValueError("winner slice requires exactly one issued critical gap")

    gap = result.critical_gaps[0]
    boundary = result.boundary

    return DecisionThreadsPresentation(
        decision_id=result.commit.decision_id,
        capture=CapturePresentation(
            question=gap.question,
            relation_id=result.r2_trace.entity_id,
            knowledge_state=result.r2_trace.knowledge_state,
        ),
        current_matches=tuple(
            CurrentMatchPresentation(entity_id=entity_id, state=state)
            for entity_id, state in result.evaluation.current_matches
        ),
        reuse_boundary=ReuseBoundaryPresentation(
            safe_reuse_result=result.evaluation.safe_reuse_result,
            limiting_requirements=result.evaluation.limiting_requirements,
            limiting_entity_id=boundary.limiting_entity_id,
            composition_kind=boundary.composition_kind,
            composition_value=boundary.composition_value,
            relation_ids=boundary.relation_ids,
        ),
        evaluation_hash=result.evaluation.result_hash,
        replay_hash=result.replay_result_hash,
    )
