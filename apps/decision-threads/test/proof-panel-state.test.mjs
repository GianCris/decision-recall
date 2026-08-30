import assert from "node:assert/strict";
import test from "node:test";

import { applyProofPayload, liveCaptureGateModel } from "../src/proof-panel-state.js";

test("new preparation clears stale authority and Phase 01 remains pre-capture", () => {
  const completed = {
    capture_validation: { answer: "yes", status: "accepted", completion: "allowed" },
    capture: { relation_id: "R2", knowledge_state: "established" },
    future_evaluation_status: "not_requested",
  };
  const state = {
    preparation: { gap_id: "R2", knowledge_state: "not_durably_recorded", question_hash: "old" },
    captureEnvelope: completed,
    reevaluationEnvelope: { stale: true },
    replayPresentation: null,
    geminiEvidence: { committed: true },
  };

  applyProofPayload(state, "/api/capture-preparation", true, {
    gap_id: "R2",
    knowledge_state: "not_durably_recorded",
    question_hash: "current-question-hash",
  });

  assert.equal(state.captureEnvelope, null);
  assert.deepEqual(state.geminiEvidence, { committed: true });

  const phaseOne = liveCaptureGateModel({ phase: 0, preparation: state.preparation, captureEnvelope: completed });
  assert.equal(phaseOne.humanResponse, "NOT YET VERIFIED");
  assert.equal(phaseOne.completion, "NOT YET EVALUATED");
  assert.equal(phaseOne.historicalRole, null);
  assert.equal(phaseOne.preCaptureKnowledge, "NOT_DURABLY_RECORDED");
  assert.equal(phaseOne.questionHash, "current-question-hash");
  assert.doesNotMatch(JSON.stringify(phaseOne), /YES · VERIFIED|ALLOWED|R2 · ESTABLISHED/);

  applyProofPayload(state, "/api/capture", true, completed);
  assert.equal(state.reevaluationEnvelope, null);
  const phaseThree = liveCaptureGateModel({ phase: 2, preparation: state.preparation, captureEnvelope: state.captureEnvelope });
  assert.equal(phaseThree.humanResponse, "YES · VERIFIED");
  assert.equal(phaseThree.completion, "ALLOWED");
  assert.equal(phaseThree.historicalRole, "R2 · ESTABLISHED");
});
