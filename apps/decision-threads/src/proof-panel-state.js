export function applyProofPayload(state, path, responseOk, payload) {
  if (!responseOk) return;
  if (path === "/api/capture-preparation") {
    state.preparation = payload;
    state.captureEnvelope = null;
  } else if (path === "/api/capture") {
    state.captureEnvelope = payload;
  } else if (path === "/demo-state.json") {
    state.replayPresentation = payload;
  }
}

export function liveCaptureGateModel({ phase, preparation, captureEnvelope }) {
  const establishedPhase = phase >= 2;
  const validation = establishedPhase ? captureEnvelope?.capture_validation || null : null;
  const presentation = establishedPhase ? captureEnvelope?.presentation || null : null;
  const established = establishedPhase && presentation?.capture?.knowledge_state === "established";

  return {
    establishedPhase,
    validation,
    presentation,
    issuedGap: preparation?.gap_id || "R2",
    preCaptureKnowledge: String(
      preparation?.knowledge_state || "not_durably_recorded",
    ).toUpperCase(),
    questionHash: preparation?.question_hash || null,
    humanResponse: validation ? `${String(validation.answer).toUpperCase()} · VERIFIED` : "NOT YET VERIFIED",
    completion: validation ? String(validation.completion).toUpperCase() : "NOT YET EVALUATED",
    historicalRole: established ? "R2 · ESTABLISHED" : null,
  };
}
