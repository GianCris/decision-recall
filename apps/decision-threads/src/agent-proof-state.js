export const AGENT_PROOF_DURATION_MS = 6900;

export const AGENT_PROOF_REVEAL_SECONDS = Object.freeze({
  source: 0,
  interpretation: 1.4,
  authority: 2.8,
  gap: 4.4,
  question: 5.5,
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
