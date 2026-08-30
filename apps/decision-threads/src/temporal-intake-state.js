export const SUPPLIED_T1_RECORDS = Object.freeze([
  Object.freeze({
    evidence_id: "WE-E301-APEX-PRODUCT-V1",
    metric_key: "apex_on_time_rate",
    value: 0.987,
    unit: "ratio",
    window_days: 30,
    observed_at: "2026-10-04T09:00:00+00:00",
    source: "supplied_current_record",
  }),
  Object.freeze({
    evidence_id: "WE-BEACON-PRODUCT-V1",
    metric_key: "beacon_reactivation_days",
    value: 70,
    unit: "days",
    window_days: null,
    observed_at: "2026-10-04T09:00:00+00:00",
    source: "supplied_current_record",
  }),
]);

export const T1_WORLD_TIME = "2026-10-04T09:00:00+00:00";

export function captureView(preparation, captureEnvelope) {
  return {
    decision_id: preparation.decision_id,
    capture: {
      relation_id: captureEnvelope.capture.relation_id,
      question: preparation.question,
      knowledge_state: captureEnvelope.capture.knowledge_state,
    },
    current_matches: [],
    reuse_boundary: null,
    evaluation_hash: null,
    replay_hash: null,
  };
}

export function buildReevaluationPayload(preparation) {
  return {
    decision_id: preparation.decision_id,
    capture: {
      capture_session_id: preparation.capture_session_id,
      gap_id: preparation.gap_id,
      question_hash: preparation.question_hash,
      answer: "yes",
    },
    world_time: T1_WORLD_TIME,
    evidence: SUPPLIED_T1_RECORDS.map((record) => ({ ...record })),
  };
}

export function reevaluatedView(previousView, reevaluation) {
  return {
    ...previousView,
    current_matches: reevaluation.current_matches.map((match) => ({ ...match })),
    reuse_boundary: {
      limiting_requirements: [...reevaluation.limiting_requirements],
      safe_reuse_result: reevaluation.safe_reuse_result,
      reason_codes: [...reevaluation.reason_codes],
    },
    evaluation_hash: reevaluation.evaluation_hash,
    replay_hash: reevaluation.replay_hash,
  };
}

export function reusePresentationModel(reuseBoundary) {
  const result = reuseBoundary?.safe_reuse_result || null;
  const labels = {
    insufficient_evidence: "INSUFFICIENT EVIDENCE",
    reuse_authorized: "REUSE AUTHORIZED",
    reuse_not_authorized: "REUSE NOT AUTHORIZED",
  };
  return {
    result,
    label: labels[result] || "REUSE RESULT UNAVAILABLE",
    showStop: result === "insufficient_evidence",
    title: result === "insufficient_evidence"
      ? "I CAN’T ESTABLISH THAT"
      : labels[result] || "REUSE RESULT UNAVAILABLE",
    explanation: result === "insufficient_evidence"
      ? "Beacon mattered then. We never established whether that reason was sufficient on its own."
      : null,
    limitingRequirements: [...(reuseBoundary?.limiting_requirements || [])],
    reasonCodes: [...(reuseBoundary?.reason_codes || [])],
  };
}

export function matchLabels(currentMatches) {
  const matches = Object.fromEntries(currentMatches.map((item) => [item.entity_id, item.state]));
  const humanize = (state) => ({
    does_not_match: "NO LONGER MATCHES",
    matches: "STILL MATCHES",
    unknown: "NOT ESTABLISHED",
  }[state] || String(state || "NOT EVALUATED").replaceAll("_", " ").toUpperCase());
  return { M1: humanize(matches.M1), M2: humanize(matches.M2) };
}

export function canonicalT1Keys(view) {
  return {
    current_matches: view?.current_matches || [],
    reuse_boundary: view?.reuse_boundary || null,
    evaluation_hash: view?.evaluation_hash || null,
    replay_hash: view?.replay_hash || null,
  };
}

export function isCurrentRequest(requestGeneration, currentGeneration) {
  return requestGeneration === currentGeneration;
}
