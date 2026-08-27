import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import { AGENT_PROOF_DURATION_MS, agentProofPhaseModel } from "../src/agent-proof-state.js";

const projection = JSON.parse(
  fs.readFileSync(new URL("../src/pc2-judge-safe-gemini-projection.json", import.meta.url), "utf8"),
);

test("release projection is brief, release-only, and never attributes R2 to Gemini", () => {
  assert.ok(AGENT_PROOF_DURATION_MS >= 8000 && AGENT_PROOF_DURATION_MS <= 10000);
  assert.equal(projection.evidence_class, "release_proven_not_live_hero_request");
  assert.equal(projection.model, "gemini-3.7-flash");
  assert.deepEqual(
    projection.candidates.map(({ semantic_key }) => semantic_key),
    ["historical_support:apex_delivery_instability", "beacon_reactivation_delay"],
  );
  assert.doesNotMatch(JSON.stringify(projection), /R2/);
});

test("agent proof follows existing phase gates without future leakage", () => {
  const inspect = agentProofPhaseModel({ phase: 1, live: true, requestedVisible: true });
  assert.equal(inspect.showReleaseHandoff, true);
  assert.equal(inspect.runtimeLabel, "LIVE · CLOUD RUN");
  assert.equal(inspect.historicalInfluence, "NOT ESTABLISHED");
  assert.equal(inspect.showVerifiedMutation, false);
  assert.equal(inspect.showReuseSufficiency, false);

  const captured = agentProofPhaseModel({
    phase: 2,
    live: true,
    requestedVisible: false,
    captureValidation: { status: "accepted" },
  });
  assert.equal(captured.showReleaseHandoff, false);
  assert.equal(captured.historicalInfluence, "ESTABLISHED");
  assert.equal(captured.showVerifiedMutation, true);
  assert.equal(captured.showReuseSufficiency, false);

  const reuse = agentProofPhaseModel({ phase: 4, live: true, requestedVisible: false, boundary: {} });
  assert.equal(reuse.showReuseSufficiency, true);
});
