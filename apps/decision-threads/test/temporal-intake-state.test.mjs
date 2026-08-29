import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  SUPPLIED_T1_RECORDS,
  buildReevaluationPayload,
  canonicalT1Keys,
  captureView,
  isCurrentRequest,
  matchLabels,
  reevaluatedView,
  reusePresentationModel,
} from "../src/temporal-intake-state.js";

const preparation = {
  decision_id: "D-104",
  capture_session_id: "session",
  gap_id: "R2",
  question_hash: "question-hash",
  question: "Did Beacon influence D-104?",
  knowledge_state: "not_durably_recorded",
};

const captureEnvelope = {
  capture_validation: { status: "accepted", answer: "yes", completion: "allowed" },
  capture: { decision_id: "D-104", relation_id: "R2", knowledge_state: "established" },
  future_evaluation_status: "not_requested",
};

const reevaluation = {
  status: "reevaluated",
  current_matches: [
    { entity_id: "M1", state: "matches" },
    { entity_id: "M2", state: "does_not_match" },
  ],
  accepted_world_events: [{ evidence_id: "a" }, { evidence_id: "b" }],
  safe_reuse_result: "insufficient_evidence",
  limiting_requirements: ["C1"],
  reason_codes: ["REQUIRED_COMPOSITION_NOT_DURABLY_KNOWN"],
  evaluation_hash: "evaluation",
  replay_hash: "replay",
};

test("T0 capture view contains no canonical T1 result", () => {
  const view = captureView(preparation, captureEnvelope);
  assert.equal(view.capture.knowledge_state, "established");
  assert.deepEqual(canonicalT1Keys(view), {
    current_matches: [], reuse_boundary: null, evaluation_hash: null, replay_hash: null,
  });
});

test("supplied records exist before reevaluation but payload contains no authority output", () => {
  assert.equal(SUPPLIED_T1_RECORDS.length, 2);
  const payload = buildReevaluationPayload(preparation);
  assert.deepEqual(Object.keys(payload).sort(), ["capture", "decision_id", "evidence", "world_time"]);
  assert.deepEqual(Object.keys(payload.capture).sort(), ["answer", "capture_session_id", "gap_id", "question_hash"]);
  assert.deepEqual(Object.keys(payload.evidence[0]).sort(), [
    "evidence_id", "metric_key", "observed_at", "source", "unit", "value", "window_days",
  ]);
  assert.doesNotMatch(JSON.stringify(payload), /current_matches|safe_reuse_result|limiting_requirements|reason_codes|evaluation_hash|replay_hash|authorization_id|authorized|disposition/);
});

test("canonical T1 appears only when applying successful reevaluation response", () => {
  const t0 = captureView(preparation, captureEnvelope);
  const t1 = reevaluatedView(t0, reevaluation);
  assert.deepEqual(t1.current_matches, reevaluation.current_matches);
  assert.equal(t1.reuse_boundary.safe_reuse_result, "insufficient_evidence");
  assert.equal(t1.evaluation_hash, "evaluation");
  assert.equal(t1.replay_hash, "replay");
});

test("visible match labels are driven by controlled server response", () => {
  const labels = matchLabels(reevaluation.current_matches);
  assert.equal(labels.M1, "STILL MATCHES");
  assert.equal(labels.M2, "NO LONGER MATCHES");
});

test("request generation invalidates a stale in-flight response after reset", () => {
  assert.equal(isCurrentRequest(4, 4), true);
  assert.equal(isCurrentRequest(4, 5), false);
});

test("live source has no presentation preload and pending labels follow unresolved fetch state", () => {
  const source = readFileSync(new URL("../src/main.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /fetch\(["']\/api\/presentation/);
  assert.doesNotMatch(source, /payload\?\.presentation|payload\.presentation/);
  assert.doesNotMatch(source, /performance\.now|delay\(420/);
  assert.match(source, /setReevaluationStatus\("pending"\)/);
  assert.match(source, /await fetch\("\/api\/reevaluate"/);
  assert.match(source, /setReevaluationStatus\("complete"\)/);
  assert.match(source, /requestGeneration\.current \+= 1/);
  assert.match(source, /reevaluationController\.current\?\.abort\(\)/);
});

test("live failure, retry, phase gates, and reset are fail-closed in the rendered flow", () => {
  const source = readFileSync(new URL("../src/main.jsx", import.meta.url), "utf8");
  assert.match(source, /REEVALUATION NOT ACCEPTED/);
  assert.match(source, /Retry ingest & reevaluate/);
  assert.match(source, /phase >= 3 && reevaluationComplete/);
  assert.match(source, /phase === 3 && live && reevaluationStatus !== "complete"/);
  assert.match(source, /setReevaluationStatus\("error"\)/);
  assert.match(source, /setReevaluationResult\(null\)/);
  assert.match(source, /setReevaluationError\(null\)/);
  assert.match(source, /setReevaluationStatus\("idle"\)/);
  assert.match(source, /future_evaluation_status !== "not_requested"/);
});

test("proof surface tracks T0 and T1 as separate live envelopes", () => {
  const proof = readFileSync(new URL("../src/proof-panel.js", import.meta.url), "utf8");
  assert.match(proof, /"\/api\/reevaluate"/);
  assert.match(proof, /Future evaluation: not requested/);
  assert.match(proof, /admitted under event policy/);
  assert.match(proof, /Fingerprints become available only after live reevaluation/);
  assert.doesNotMatch(proof, /captureEnvelope\?\.presentation/);
});

test("insufficient evidence renders STOP and response-supplied C1", () => {
  const model = reusePresentationModel({
    safe_reuse_result: "insufficient_evidence",
    limiting_requirements: ["C1"],
    reason_codes: ["REQUIRED_COMPOSITION_NOT_DURABLY_KNOWN"],
  });
  assert.equal(model.showStop, true);
  assert.equal(model.title, "I CAN’T ESTABLISH THAT");
  assert.deepEqual(model.limitingRequirements, ["C1"]);
  assert.match(model.explanation, /never established/);
});

test("reuse authorized hides STOP and never invents C1", () => {
  const model = reusePresentationModel({
    safe_reuse_result: "reuse_authorized",
    limiting_requirements: [],
    reason_codes: [],
  });
  assert.equal(model.showStop, false);
  assert.equal(model.title, "REUSE AUTHORIZED");
  assert.equal(model.explanation, null);
  assert.deepEqual(model.limitingRequirements, []);
  assert.doesNotMatch(JSON.stringify(model), /C1|I CAN.T ESTABLISH THAT|never established/);
});

test("reuse not authorized hides STOP and never invents C1", () => {
  const model = reusePresentationModel({
    safe_reuse_result: "reuse_not_authorized",
    limiting_requirements: [],
    reason_codes: [],
  });
  assert.equal(model.showStop, false);
  assert.equal(model.title, "REUSE NOT AUTHORIZED");
  assert.equal(model.explanation, null);
  assert.deepEqual(model.limitingRequirements, []);
  assert.doesNotMatch(JSON.stringify(model), /C1|I CAN.T ESTABLISH THAT|never established/);
});

test("insufficient evidence without limiting requirements does not invent C1", () => {
  const model = reusePresentationModel({
    safe_reuse_result: "insufficient_evidence",
    limiting_requirements: [],
    reason_codes: [],
  });
  assert.equal(model.showStop, true);
  assert.equal(model.title, "I CAN’T ESTABLISH THAT");
  assert.deepEqual(model.limitingRequirements, []);
  assert.doesNotMatch(JSON.stringify(model), /C1/);

  const proof = readFileSync(new URL("../src/proof-panel.js", import.meta.url), "utf8");
  assert.doesNotMatch(proof, /\|\|\s*["']C1["']/);
});
