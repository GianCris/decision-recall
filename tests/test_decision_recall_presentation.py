from dataclasses import replace

import pytest

from decision_recall.product.golden_loop import run_golden_decision
from decision_recall.product.presentation import build_decision_threads_presentation


def test_presentation_is_a_projection_of_frozen_golden_output():
    result = run_golden_decision()
    view = build_decision_threads_presentation(result)

    assert view.decision_id == result.commit.decision_id
    assert view.capture.question == result.critical_gaps[0].question
    assert view.capture.relation_id == result.r2_trace.entity_id
    assert view.capture.knowledge_state == result.r2_trace.knowledge_state
    assert tuple((item.entity_id, item.state) for item in view.current_matches) == result.evaluation.current_matches
    assert view.reuse_boundary.safe_reuse_result == result.evaluation.safe_reuse_result
    assert view.reuse_boundary.limiting_requirements == result.evaluation.limiting_requirements
    assert view.reuse_boundary.limiting_entity_id == result.boundary.limiting_entity_id
    assert view.reuse_boundary.composition_kind == result.boundary.composition_kind
    assert view.reuse_boundary.composition_value == result.boundary.composition_value
    assert view.reuse_boundary.relation_ids == result.boundary.relation_ids
    assert view.evaluation_hash == result.evaluation.result_hash
    assert view.replay_hash == result.replay_result_hash


def test_presentation_rejects_ambiguous_gap_shape_instead_of_inventing_ui_state():
    result = run_golden_decision()
    malformed = replace(result, critical_gaps=())

    with pytest.raises(ValueError, match="exactly one issued critical gap"):
        build_decision_threads_presentation(malformed)
