export const AGENT_PROOF_DURATION_MS = 5000;

export const AGENT_PROOF_REVEAL_SECONDS = Object.freeze({
  source: 0,
  interpretation: 0.9,
  authority: 1.8,
  gap: 3.0,
  question: 3.8,
});

export function agentProofVisibleForPhase(phase, requestedVisible) {
  return phase === 1 && requestedVisible;
}

export function agentProofPhaseModel({ phase, live, requestedVisible, captureValidation, boundary }) {
  return {
    showReleaseHandoff: agentProofVisibleForPhase(phase, requestedVisible),
    runtimeLabel: live ? "LIVE · CLOUD RUN" : "DETERMINISTIC REPLAY",
    historicalInfluence: phase < 2 ? "NOT ESTABLISHED" : "ESTABLISHED",
    showVerifiedMutation: phase === 2 && Boolean(captureValidation),
    showReuseSufficiency: phase === 4 && Boolean(boundary),
  };
}
