export const AGENT_PROOF_DURATION_MS = 8600;

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
