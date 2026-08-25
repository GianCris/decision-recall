const GEMINI_EVIDENCE_URL = "/proof/pc2-credentialed-release-evidence.json";

const proofState = {
  preparation: null,
  captureEnvelope: null,
  replayPresentation: null,
  geminiEvidence: null,
  geminiEvidenceError: null,
  lastUpdatedAt: null,
};

const originalFetch = window.fetch.bind(window);

function endpointPath(input) {
  try {
    const raw = typeof input === "string" ? input : input?.url;
    return new URL(raw, window.location.href).pathname;
  } catch {
    return "";
  }
}

function emitProofUpdate() {
  proofState.lastUpdatedAt = new Date().toISOString();
  window.dispatchEvent(new CustomEvent("decision-recall-proof-update"));
}

window.fetch = async (...args) => {
  const response = await originalFetch(...args);
  const path = endpointPath(args[0]);

  if (["/api/capture-preparation", "/api/capture", "/demo-state.json"].includes(path)) {
    response.clone().json().then((payload) => {
      if (path === "/api/capture-preparation" && response.ok) proofState.preparation = payload;
      if (path === "/api/capture" && response.ok) proofState.captureEnvelope = payload;
      if (path === "/demo-state.json" && response.ok) proofState.replayPresentation = payload;
      emitProofUpdate();
    }).catch(() => {});
  }

  return response;
};

async function loadGeminiEvidence() {
  try {
    const response = await originalFetch(GEMINI_EVIDENCE_URL, { cache: "no-store" });
    if (!response.ok) throw new Error(`manifest HTTP ${response.status}`);
    const manifest = await response.json();

    if (
      !manifest
      || typeof manifest !== "object"
      || !manifest.semantic_gate
      || !manifest.credentialed_artifact
      || !manifest.model
    ) {
      throw new Error("manifest schema incomplete");
    }

    proofState.geminiEvidence = manifest;
    proofState.geminiEvidenceError = null;
  } catch (error) {
    proofState.geminiEvidence = null;
    proofState.geminiEvidenceError = error instanceof Error ? error.message : String(error);
  }
  emitProofUpdate();
}

function appPhase() {
  const app = document.querySelector("main.app");
  if (!app) return 0;
  const match = [...app.classList].find((name) => /^phase-\d$/.test(name));
  return match ? Number(match.slice(-1)) : 0;
}

function isLiveMode() {
  return Boolean(document.querySelector(".live-dot.live"));
}

function presentation() {
  return proofState.captureEnvelope?.presentation || proofState.replayPresentation || null;
}

function captureValidation() {
  return proofState.captureEnvelope?.capture_validation || null;
}

function truncate(value, length = 18) {
  if (!value) return "—";
  const text = String(value);
  if (text.length <= length) return text;
  return `${text.slice(0, length)}…`;
}

function humanize(value) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value).replaceAll("_", " ");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function proofRow(label, value, tone = "neutral", mono = false) {
  return `
    <div class="proof-v2-row">
      <span>${escapeHtml(label)}</span>
      <strong class="${escapeHtml(tone)} ${mono ? "mono" : ""}">${escapeHtml(value)}</strong>
    </div>`;
}

function statusPill(label, tone) {
  return `<span class="proof-v2-pill ${escapeHtml(tone)}"><i></i>${escapeHtml(label)}</span>`;
}

function modeSummary(live) {
  if (live) {
    return {
      eyebrow: "LIVE PROOF SURFACE",
      title: "The browser cannot establish history by itself.",
      body: "This panel follows the same Cloud Run interaction shown in the observatory and exposes the evidence behind each visible state change.",
    };
  }
  return {
    eyebrow: "REPLAY PROOF SURFACE",
    title: "This run is an explicitly labeled deterministic replay.",
    body: "Replay never impersonates live capture. The frozen evidence below remains inspectable, while live-only claims stay disabled.",
  };
}

function renderCaptureGate(phase, live) {
  const prep = proofState.preparation;
  const validation = captureValidation();
  const view = presentation();
  const captured = phase >= 2;

  if (!live) {
    return `
      <section class="proof-v2-section">
        <div class="proof-v2-section-head"><span>01</span><div><b>Capture Gate</b><small>Replay isolation</small></div>${statusPill("REPLAY", "amber")}</div>
        <p class="proof-v2-explain">No live server acceptance is claimed in replay mode. The visual capture step replays the verified golden state.</p>
        <div class="proof-v2-rows">
          ${proofRow("Mode", "deterministic replay", "amber")}
          ${proofRow("Historical relation", captured ? "R2 established in replay" : "R2 unresolved", captured ? "green" : "amber")}
        </div>
      </section>`;
  }

  return `
    <section class="proof-v2-section">
      <div class="proof-v2-section-head"><span>01</span><div><b>Capture Gate</b><small>Server-authoritative binding</small></div>${statusPill(captured && validation ? "VERIFIED" : "ISSUED", captured && validation ? "green" : "blue")}</div>
      <p class="proof-v2-explain">The browser may answer the question, but it cannot grant historical authority. Cloud Run rechecks the issued capture binding first.</p>
      <div class="proof-v2-rows">
        ${proofRow("Runtime", "Cloud Run · live engine", "green")}
        ${proofRow("Issued gap", prep?.gap_id || view?.capture?.relation_id || "R2")}
        ${proofRow("Pre-capture knowledge", prep?.knowledge_state || "not_durably_recorded", "amber")}
        ${prep?.question_hash ? proofRow("Question binding", truncate(prep.question_hash, 22), "neutral", true) : ""}
        ${validation ? proofRow("Human response", `${String(validation.answer).toUpperCase()} · VERIFIED`, "green") : proofRow("Human response", "not verified yet", "amber")}
        ${validation ? proofRow("Completion", String(validation.completion).toUpperCase(), "green") : ""}
        ${captured ? proofRow("Historical role", view?.capture?.knowledge_state === "established" ? "R2 · ESTABLISHED" : humanize(view?.capture?.knowledge_state), view?.capture?.knowledge_state === "established" ? "green" : "amber") : ""}
      </div>
    </section>`;
}

function renderCurrentWorld(phase) {
  const view = presentation();
  const matches = Object.fromEntries((view?.current_matches || []).map((item) => [item.entity_id, item.state]));
  const active = phase >= 3;

  return `
    <section class="proof-v2-section ${active ? "" : "muted-section"}">
      <div class="proof-v2-section-head"><span>02</span><div><b>Current-world evaluation</b><small>History ≠ current match</small></div>${statusPill(active ? "ACTIVE" : "DORMANT", active ? "blue" : "gray")}</div>
      <p class="proof-v2-explain">Historical roles stay recorded even when the present world changes. Current evaluation is a separate layer.</p>
      ${active ? `<div class="proof-v2-rows">
        ${proofRow("M1 · Apex instability", humanize(matches.M1), matches.M1 === "does_not_match" ? "red" : "neutral")}
        ${proofRow("M2 · Beacon restart delay", humanize(matches.M2), matches.M2 === "matches" ? "green" : "neutral")}
      </div>` : `<div class="proof-v2-dormant">Current World remains intentionally inactive until THEN → NOW.</div>`}
    </section>`;
}

function renderBoundary(phase) {
  const view = presentation();
  const boundary = view?.reuse_boundary;
  const active = phase >= 4 && boundary;

  return `
    <section class="proof-v2-section ${active ? "" : "muted-section"}">
      <div class="proof-v2-section-head"><span>03</span><div><b>Epistemic boundary</b><small>Exact missing requirement</small></div>${statusPill(active ? "STOP" : "NOT REACHED", active ? "amber" : "gray")}</div>
      <p class="proof-v2-explain">Decision Recall does not turn surviving historical evidence into a stronger claim than the record authorizes.</p>
      ${active ? `<div class="proof-v2-rows">
        ${proofRow("Composition", humanize(boundary.composition_kind))}
        ${proofRow("Recorded value", humanize(boundary.composition_value), "amber")}
        ${proofRow("Limiting requirement", (boundary.limiting_requirements || []).join(", ") || boundary.limiting_entity_id || "C1", "amber")}
        ${proofRow("Safe reuse", humanize(boundary.safe_reuse_result), "amber")}
      </div>` : `<div class="proof-v2-dormant">The reuse boundary is intentionally withheld until the reuse attempt.</div>`}
    </section>`;
}

function renderReplayIntegrity(phase) {
  const view = presentation();
  const evaluationHash = view?.evaluation_hash;
  const replayHash = view?.replay_hash;
  const available = phase >= 2 && evaluationHash && replayHash;
  const equal = available && evaluationHash === replayHash;

  return `
    <section class="proof-v2-section ${available ? "" : "muted-section"}">
      <div class="proof-v2-section-head"><span>04</span><div><b>Deterministic completion fingerprints</b><small>Evaluation = replay check</small></div>${statusPill(available ? (equal ? "MATCH" : "MISMATCH") : "WAITING", available ? (equal ? "green" : "red") : "gray")}</div>
      <p class="proof-v2-explain">The winner completion exposes evaluation and replay fingerprints so deterministic reconstruction can be checked rather than attributed to the final Replay button.</p>
      ${available ? `<div class="proof-v2-rows">
        ${proofRow("Evaluation hash", truncate(evaluationHash, 26), "neutral", true)}
        ${proofRow("Replay hash", truncate(replayHash, 26), "neutral", true)}
        ${proofRow("Integrity", equal ? "evaluation = replay" : "hash mismatch", equal ? "green" : "red")}
      </div>` : `<div class="proof-v2-dormant">Fingerprints become available after capture completion.</div>`}
    </section>`;
}

function geminiManifestView() {
  const manifest = proofState.geminiEvidence;
  if (!manifest) return null;

  const gate = manifest.semantic_gate || {};
  const observations = manifest.operational_observations || {};
  const retryEntries = Object.entries(observations).filter(
    ([name, value]) => name !== "interpretation"
      && value
      && typeof value === "object"
      && Number(value.infra_attempt_count || 1) > 1,
  );

  return {
    checkpoint: manifest.checkpoint || "PC2 · GeminiCandidateCompiler",
    status: manifest.status || "UNKNOWN",
    model: manifest.model || "—",
    project: manifest.project || "—",
    location: manifest.location || "—",
    releaseOracle: manifest.release_oracle || "—",
    semanticExecutions: `${gate.completed_semantic_executions ?? "—"} / ${gate.target_semantic_executions ?? "—"}`,
    semanticFailures: gate.failure_count ?? "—",
    passed: gate.passed === true,
    scenarios: [
      ["Normal", gate.normal || "—"],
      ["Paraphrase", gate.paraphrase || "—"],
      ["Document prompt injection", gate.document_prompt_injection || "—"],
    ],
    artifactSha256: manifest.credentialed_artifact?.sha256 || "—",
    retryEntries,
    interpretation: observations.interpretation || "",
  };
}

function renderGeminiEvidence() {
  const e = geminiManifestView();

  if (!e) {
    const failed = Boolean(proofState.geminiEvidenceError);
    return `
      <section class="proof-v2-section gemini-evidence ${failed ? "" : "muted-section"}">
        <div class="proof-v2-section-head"><span>05</span><div><b>Gemini credentialed evidence</b><small>Committed PC2 release manifest</small></div>${statusPill(failed ? "UNAVAILABLE" : "LOADING", failed ? "red" : "gray")}</div>
        <p class="proof-v2-explain">This surface reads the committed credentialed-release manifest; it does not duplicate Gemini results as frontend constants and does not present a live Gemini call from the hero interaction.</p>
        <div class="proof-v2-dormant">${failed ? `Manifest could not be loaded: ${escapeHtml(proofState.geminiEvidenceError)}` : "Loading committed release evidence…"}</div>
      </section>`;
  }

  return `
    <section class="proof-v2-section gemini-evidence">
      <div class="proof-v2-section-head"><span>05</span><div><b>Gemini credentialed evidence</b><small>${escapeHtml(e.checkpoint)}</small></div>${statusPill(e.passed ? "MANIFEST PASS" : "MANIFEST FAIL", e.passed ? "green" : "red")}</div>
      <p class="proof-v2-explain">Rendered from the committed PC2 credentialed-release manifest. This is <b>not</b> presented as a live Gemini call from the hero interaction.</p>
      <div class="proof-v2-metric-grid">
        <div><span>MODEL</span><b>${escapeHtml(e.model)}</b></div>
        <div><span>SEMANTIC EXECUTIONS</span><b>${escapeHtml(e.semanticExecutions)}</b></div>
        <div><span>SEMANTIC FAILURES</span><b>${escapeHtml(e.semanticFailures)}</b></div>
        <div><span>INFRA RETRY CASES</span><b>${escapeHtml(e.retryEntries.length)}</b></div>
        <div><span>LOCATION</span><b>${escapeHtml(e.location)}</b></div>
      </div>
      <div class="proof-v2-scenarios">
        ${e.scenarios.map(([name, score]) => `<div><span>${escapeHtml(name)}</span><b>${escapeHtml(score)}</b></div>`).join("")}
      </div>
      <details class="proof-v2-details">
        <summary>Release evidence details</summary>
        <div class="proof-v2-rows compact">
          ${proofRow("Manifest status", e.status, e.passed ? "green" : "red")}
          ${proofRow("Project", e.project)}
          ${proofRow("Release oracle", e.releaseOracle)}
          ${proofRow("Artifact SHA-256", truncate(e.artifactSha256, 30), "neutral", true)}
          ${e.retryEntries.map(([name, value]) => proofRow(`Infra retry · ${name}`, `${value.infra_attempt_count} attempts`, "amber")).join("")}
        </div>
        <p>${escapeHtml(e.interpretation || "Infrastructure retries are reported separately from semantic failures.")}</p>
      </details>
    </section>`;
}

function renderClaimDiscipline() {
  return `
    <section class="proof-v2-section claim-discipline">
      <div class="proof-v2-section-head"><span>06</span><div><b>Claim discipline</b><small>What this demo does — and does not — establish</small></div>${statusPill("SCOPED", "blue")}</div>
      <div class="proof-v2-claim-grid">
        <div class="proven"><span>THE SUBMITTED SYSTEM DEMONSTRATES</span><p>One deployed golden slice: live Capture Gate verification, temporal reevaluation, deterministic replay evidence, and an explicit reuse boundary.</p></div>
        <div class="not-claimed"><span>NOT CLAIMED BY THIS DEMO</span><p>Baseline superiority, cross-domain generalization, enterprise-scale performance, or broad recovery superiority.</p></div>
      </div>
      <p class="proof-v2-footnote">A convincing animation never upgrades an experimental claim by itself.</p>
    </section>`;
}

function visibleSnapshotText() {
  const live = isLiveMode();
  const phase = appPhase();
  const prep = proofState.preparation;
  const validation = captureValidation();
  const view = presentation();
  const matches = Object.fromEntries((view?.current_matches || []).map((item) => [item.entity_id, item.state]));
  const boundary = view?.reuse_boundary;
  const gemini = geminiManifestView();

  const lines = [
    "DECISION RECALL — PROOF SNAPSHOT",
    `mode: ${live ? "Cloud Run live engine" : "deterministic replay"}`,
    `phase: ${phase + 1}/5`,
    `R2 pre-capture: ${prep?.knowledge_state || "not_durably_recorded"}`,
  ];

  if (phase >= 2) {
    lines.push(
      `capture: ${validation ? `${validation.answer} / ${validation.status} / ${validation.completion}` : "verified replay"}`,
      `R2 current: ${view?.capture?.knowledge_state || "established"}`,
    );
  }

  if (phase >= 3) lines.push(`M1: ${matches.M1 || "—"}`, `M2: ${matches.M2 || "—"}`);
  if (phase >= 4 && boundary) {
    lines.push(
      `boundary: ${(boundary.limiting_requirements || []).join(", ") || boundary.limiting_entity_id}`,
      `safe reuse: ${boundary.safe_reuse_result}`,
    );
  }

  if (view?.evaluation_hash && view?.replay_hash) {
    lines.push(
      `evaluation hash: ${view.evaluation_hash}`,
      `replay hash: ${view.replay_hash}`,
      `hashes equal: ${view.evaluation_hash === view.replay_hash}`,
    );
  }

  if (gemini) {
    lines.push(
      `Gemini credentialed manifest: ${gemini.semanticExecutions} semantic executions; semantic failures ${gemini.semanticFailures}; infra retry cases ${gemini.retryEntries.length}; normal ${gemini.scenarios[0][1]}; paraphrase ${gemini.scenarios[1][1]}; document prompt injection ${gemini.scenarios[2][1]}.`,
    );
  } else {
    lines.push("Gemini credentialed manifest: unavailable in this runtime.");
  }

  return lines.join("\n");
}

let shell = null;
let restoreFocus = null;

function closeProof() {
  if (!shell) return;
  shell.remove();
  shell = null;
  document.body.classList.remove("proof-v2-open");
  restoreFocus?.focus?.();
  restoreFocus = null;
}

function refreshProof() {
  if (!shell) return;
  const panel = shell.querySelector(".proof-v2-panel");
  if (!panel) return;
  const live = isLiveMode();
  const phase = appPhase();
  const summary = modeSummary(live);
  const existingScroll = panel.scrollTop;

  panel.innerHTML = `
    <div class="proof-v2-topline">
      <div>${statusPill(live ? "CLOUD RUN · LIVE" : "DETERMINISTIC REPLAY", live ? "green" : "amber")}<span class="proof-v2-phase">PHASE 0${phase + 1} / 05</span></div>
      <button class="proof-v2-close" type="button" aria-label="Close Why / Proof">×</button>
    </div>
    <header class="proof-v2-header">
      <span>${escapeHtml(summary.eyebrow)}</span>
      <h2>${escapeHtml(summary.title)}</h2>
      <p>${escapeHtml(summary.body)}</p>
    </header>
    <div class="proof-v2-live-strip">
      <div><span>VISIBLE STATE</span><b>${phase < 2 ? "R2 unresolved" : phase < 3 ? "R2 established" : phase < 4 ? "Current world evaluated" : "Reuse boundary reached"}</b></div>
      <div><span>AUTHORITY</span><b>${phase < 2 ? "Human evidence missing" : "Human role established"}</b></div>
      <div><span>RUNTIME</span><b>${live ? "Server-bound" : "Replay-only"}</b></div>
    </div>
    <div class="proof-v2-sections">
      ${renderCaptureGate(phase, live)}
      ${renderCurrentWorld(phase)}
      ${renderBoundary(phase)}
      ${renderReplayIntegrity(phase)}
      ${renderGeminiEvidence()}
      ${renderClaimDiscipline()}
    </div>
    <footer class="proof-v2-footer">
      <button type="button" class="proof-v2-copy">Copy current proof snapshot</button>
      <span>Proof follows the visible phase; future values stay hidden until the observatory reaches them.</span>
    </footer>`;

  panel.scrollTop = existingScroll;
  panel.querySelector(".proof-v2-close")?.addEventListener("click", closeProof);
  panel.querySelector(".proof-v2-copy")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    try {
      await navigator.clipboard.writeText(visibleSnapshotText());
      button.textContent = "Copied proof snapshot";
    } catch {
      button.textContent = "Copy unavailable";
    }
    window.setTimeout(() => {
      if (button.isConnected) button.textContent = "Copy current proof snapshot";
    }, 1400);
  });
}

function openProof(button) {
  if (shell) {
    closeProof();
    return;
  }
  restoreFocus = button;
  shell = document.createElement("div");
  shell.className = "proof-v2-shell";
  shell.innerHTML = `<div class="proof-v2-scrim" aria-hidden="true"></div><aside class="proof-v2-panel" role="dialog" aria-modal="true" aria-label="Why and proof"></aside>`;
  document.body.appendChild(shell);
  document.body.classList.add("proof-v2-open");
  shell.querySelector(".proof-v2-scrim")?.addEventListener("click", closeProof);
  refreshProof();
  shell.querySelector(".proof-v2-close")?.focus();
}

document.addEventListener("click", (event) => {
  const button = event.target.closest?.(".proof-button");
  if (!button) return;
  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation();
  openProof(button);
}, true);

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && shell) closeProof();
});

window.addEventListener("decision-recall-proof-update", refreshProof);

const rootObserver = new MutationObserver(() => {
  if (shell) refreshProof();
});
rootObserver.observe(document.getElementById("root"), { subtree: true, attributes: true, attributeFilter: ["class"] });

loadGeminiEvidence();
