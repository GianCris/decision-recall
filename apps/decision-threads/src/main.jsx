import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { AnimatePresence, motion } from "motion/react";
import "./styles.css";
import releaseEvidence from "./pc2-judge-safe-gemini-projection.json";
import { AGENT_PROOF_DURATION_MS, AGENT_PROOF_REVEAL_SECONDS, agentProofVisibleForPhase } from "./agent-proof-state.js";
import {
  SUPPLIED_T1_RECORDS,
  buildReevaluationPayload,
  captureView,
  isCurrentRequest,
  matchLabels,
  reevaluatedView,
  reusePresentationModel,
} from "./temporal-intake-state.js";

const COPY = {
  0: {
    eyebrow: "Initial decision",
    title: "A decision held in time.",
    body: "Apex was unstable. Beacon needed about 10 weeks to restart. D-104 recorded a six-month keep-both decision.",
    action: "Inspect decision",
  },
  1: {
    eyebrow: "Gap discovered",
    title: "One relationship is missing.",
    body: "Beacon’s restart delay is recorded. Whether it materially influenced D-104 is not.",
    action: "Yes — verify human response",
  },
  2: {
    eyebrow: "Human response verified",
    title: "The historical role is established.",
    body: null,
    action: "View later-world records",
  },
  3: {
    eyebrow: "Simulated T1 · +6 weeks",
    title: "Later-world records are ready.",
    body: "Supplied demo records are ready for live policy validation and reevaluation.",
    action: "Ingest & reevaluate",
  },
  4: {
    eyebrow: "Reuse boundary",
    title: "Reuse result available.",
    body: null,
    action: "Replay",
  },
};

const labelForMatch = (id) => ({ M1: "Apex instability", M2: "Beacon restart delay" }[id] || id);
const humanizeMatch = (state) => ({
  does_not_match: "no longer matches",
  matches: "still matches",
}[state] || "current evaluation");

function DrawPath({ d, kind = "history", delay: pathDelay = 0, dim = false }) {
  const markerEnd = kind === "current-match"
    ? "url(#arrowGreen)"
    : kind === "current-mismatch"
      ? "url(#arrowRed)"
      : undefined;

  return (
    <motion.path
      d={d}
      fill="none"
      markerEnd={markerEnd}
      className={`thread ${kind} ${dim ? "dim" : ""}`}
      initial={{ pathLength: 0, opacity: 0 }}
      animate={{ pathLength: 1, opacity: 1 }}
      transition={{ duration: 0.72, delay: pathDelay, ease: [0.22, 1, 0.36, 1] }}
    />
  );
}

function Pulse({ d, tone = "green", duration = 1.15, delay: pulseDelay = 0, stopAtEnd = false }) {
  return (
    <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: pulseDelay }}>
      <circle r="13" className={`trace-pulse-halo ${tone}`}>
        <animateMotion dur={`${duration}s`} begin={`${pulseDelay}s`} fill="freeze" repeatCount="1" path={d} />
      </circle>
      <circle r="7" className={`trace-pulse ${tone}`}>
        <animateMotion dur={`${duration}s`} begin={`${pulseDelay}s`} fill="freeze" repeatCount="1" path={d} />
      </circle>
      {stopAtEnd && <circle r="16" className={`trace-stop ${tone}`} opacity="0" />}
    </motion.g>
  );
}

function InstrumentNode({ x, y, title, subtitle, kind = "entity", status, active = true }) {
  const radius = kind === "decision" ? 92 : 46;
  if (kind === "decision") {
    return (
      <motion.g
        className="instrument-node decision decision-instrument"
        initial={{ opacity: 0, scale: 0.92 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.48, ease: [0.22, 1, 0.36, 1] }}
      >
        <circle cx={x} cy={y} r="142" className="decision-field" />
        <circle cx={x} cy={y} r="116" className="decision-anchor-ring" />
        <circle cx={x} cy={y} r={radius} className="node-core decision" />
        <circle cx={x} cy={y} r="78" className="decision-core-ring" />
        <text x={x} y={y - 42} textAnchor="middle" className="decision-kicker">DECISION CORE</text>
        <text x={x} y={y + 1} textAnchor="middle" className="node-title decision">{title}</text>
        <text x={x} y={y + 29} textAnchor="middle" className="node-subtitle decision">{subtitle}</text>
        <text x={x} y={y + 54} textAnchor="middle" className="decision-recorded">RECORDED DECISION</text>
        <circle cx={x - 114} cy={y - 36} r="7" className="relationship-port apex-port" />
        <circle cx={x - 106} cy={y + 58} r="7" className="relationship-port beacon-port" />
        <circle cx={x + 114} cy={y} r="7" className="relationship-port current-port" />
      </motion.g>
    );
  }
  return (
    <motion.g
      className={`instrument-node ${kind} ${active ? "active" : "muted"}`}
      initial={{ opacity: 0, scale: 0.92 }}
      animate={{ opacity: active ? 1 : 0.55, scale: 1 }}
      transition={{ duration: 0.38 }}
    >
      <circle cx={x} cy={y} r={radius + 12} className="node-orbit" />
      <circle cx={x} cy={y} r={radius} className={`node-core ${kind}`} />
      <circle cx={x} cy={y} r={radius - 8} className="node-inner-ring" />
      <text x={x} y={y - 4} textAnchor="middle" className={`node-title ${kind}`}>{title}</text>
      <text x={x} y={y + 17} textAnchor="middle" className={`node-subtitle ${kind}`}>{subtitle}</text>
      {status && <text x={x} y={y + radius + 28} textAnchor="middle" className={`node-status ${status.tone || "neutral"}`}>{status.label}</text>}
    </motion.g>
  );
}

function Gap({ x, y, label, emphasis = false, delay: gapDelay = 0 }) {
  return (
    <motion.g
      initial={{ opacity: 0, scale: 0.72 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ type: "spring", stiffness: 250, damping: 18, delay: gapDelay }}
    >
      <circle cx={x} cy={y} r={emphasis ? 36 : 28} className={`gap-ripple outer ${emphasis ? "emphasis" : ""}`} />
      <circle cx={x} cy={y} r={emphasis ? 28 : 22} className={`gap-ripple inner ${emphasis ? "emphasis" : ""}`} />
      <circle cx={x} cy={y} r={emphasis ? 19 : 16} className="gap-core" />
      <text x={x} y={y + 7} textAnchor="middle" className="gap-mark">?</text>
      {label && <text x={x} y={y + (emphasis ? 58 : 48)} textAnchor="middle" className="gap-label">{label}</text>}
    </motion.g>
  );
}

function ProofReveal({ delay, className, children }) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.42, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}

function AgentProof({ live, view }) {
  const historical = releaseEvidence.candidates.find(
    (candidate) => candidate.semantic_key === "historical_support:apex_delivery_instability",
  );
  const beacon = releaseEvidence.candidates.find(
    (candidate) => candidate.semantic_key === "beacon_reactivation_delay",
  );

  return (
    <motion.section
      className="agent-proof"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.36 }}
      aria-label="Release-proven Gemini interpretation and live authority handoff"
    >
      <div className="agent-proof-release">
        <ProofReveal delay={AGENT_PROOF_REVEAL_SECONDS.source} className="agent-proof-records">
          <span>SOURCE RECORDS · D-104</span>
          <blockquote>“{historical.exact_quote}”</blockquote>
          <blockquote>“{beacon.exact_quote}”</blockquote>
        </ProofReveal>
        <ProofReveal delay={AGENT_PROOF_REVEAL_SECONDS.interpretation} className="agent-proof-gemini">
          <span>GEMINI 3.7 FLASH · RELEASE-PROVEN</span>
          <p><i>✓</i> Apex instability influenced D-104</p>
          <p><i>✓</i> Beacon restart delay identified</p>
        </ProofReveal>
      </div>

      <div className="agent-proof-separator" />

      <div className="agent-proof-live">
        <ProofReveal delay={AGENT_PROOF_REVEAL_SECONDS.authority} className="agent-proof-authority">
          <span>{live ? "LIVE · CLOUD RUN" : "DETERMINISTIC REPLAY"}</span>
          <strong>INTERPRETATION ≠ AUTHORITY</strong>
          <div className="authority-contrast">
          <p><span>FACT KNOWN</span><b>Beacon restart delay</b><i>✓</i></p>
          <em>≠</em>
          <p><span>HISTORICAL INFLUENCE</span><b>NOT ESTABLISHED</b><i>?</i></p>
          </div>
        </ProofReveal>
        <div className="agent-proof-gap">
          <ProofReveal delay={AGENT_PROOF_REVEAL_SECONDS.gap} className="agent-proof-gap-label">
          <span>ONE REQUIRED RELATION IS UNRESOLVED</span>
          </ProofReveal>
          <ProofReveal delay={AGENT_PROOF_REVEAL_SECONDS.question} className="agent-proof-question">
          <strong>{view.capture.question}</strong>
          </ProofReveal>
        </div>
      </div>
    </motion.section>
  );
}

function DecisionCanvas({ phase, view, boundaryRevealed, reevaluationComplete }) {
  const captureEstablished = phase >= 2;
  const gapDiscovered = phase >= 1 && !captureEstablished;
  const now = phase >= 3 && reevaluationComplete;
  const reusePresentation = reusePresentationModel(view.reuse_boundary);
  const reuse = phase >= 4 && reusePresentation.showStop;
  const matches = useMemo(
    () => Object.fromEntries((view.current_matches || []).map((x) => [x.entity_id, x.state])),
    [view],
  );

  const apexToDecision = "M405 220 C505 220 548 280 596 324";
  const beaconToGap = "M405 500 C490 500 528 445 565 420";
  const gapToDecision = "M598 405 C612 396 620 390 626 381";
  const beaconToDecision = "M405 500 C505 500 560 458 604 418";
  const apexEval = "M824 360 C890 300 940 244 1010 220";
  const beaconEval = "M824 360 C900 406 950 470 1010 500";
  const reuseApproach = "M1010 500 C1056 522 1082 548 1102 584";

  const showInspectPulses = phase === 1;
  const showCommitPulse = phase === 2;
  const showCurrentPulse = phase === 3;
  const showReusePulse = phase === 4 && !boundaryRevealed;

  return (
    <div className={`observatory phase-${phase} ${boundaryRevealed ? "boundary-revealed" : ""}`}>
      <div className="observatory-grid" aria-hidden="true" />
      <div className="time-axis">
        <span>THEN</span>
        <motion.div className="time-line" animate={{ scaleX: now ? 1 : 0.18 }} transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }} />
        <span className={now ? "visible" : "ghost"}>NOW</span>
        {now && (
          <motion.div className="time-delta" initial={{ opacity: 0, y: -5 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.35 }}>
            6 WEEKS
          </motion.div>
        )}
      </div>

      <svg viewBox="0 0 1240 720" className="decision-canvas" role="img" aria-label="Decision Recall temporal decision graph">
        <defs>
          <linearGradient id="decisionFill" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#252933" />
            <stop offset="100%" stopColor="#0d1016" />
          </linearGradient>
          <marker id="arrowGreen" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth">
            <path d="M0,0 L8,4 L0,8 z" className="arrow-green" />
          </marker>
          <marker id="arrowRed" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth">
            <path d="M0,0 L8,4 L0,8 z" className="arrow-red" />
          </marker>
        </defs>

        <text x="320" y="105" className="plane-label">OBSERVED WORLD</text>
        <text x="675" y="105" className="plane-label decision-plane">DECISION MEMORY</text>
        <text x="1010" y="105" className={`plane-label current-plane ${now ? "active" : "dormant"}`}>CURRENT WORLD</text>

        <InstrumentNode
          x={350}
          y={220}
          title="Apex"
          subtitle={now ? "98.7% on-time · 30d" : "delivery unstable"}
          kind="entity"
          status={now ? { label: "CURRENT EVIDENCE", tone: "blue" } : { label: "OBSERVED AT T0", tone: "neutral" }}
        />
        <InstrumentNode
          x={350}
          y={500}
          title="Beacon"
          subtitle="~10 weeks to restart"
          kind="entity"
          status={{ label: now ? "CURRENT EVIDENCE" : "OBSERVED AT T0", tone: now ? "green" : "neutral" }}
        />
        <InstrumentNode x={710} y={360} title="D-104" subtitle="keep both · 6 months" kind="decision" />

        {!now && (
          <g className="current-world-dormant">
            <circle cx="1060" cy="360" r="96" className="dormant-world-field" />
            <circle cx="1060" cy="360" r="10" className="dormant-world-anchor" />
            <text x="1060" y="393" textAnchor="middle" className="dormant-world-copy">EVALUATION INACTIVE</text>
          </g>
        )}

        <DrawPath d={apexToDecision} kind="history" dim={now} />

        {gapDiscovered && (
          <>
            <DrawPath d={beaconToGap} kind="missing" delay={0.55} />
            <Gap x={582} y={412} label="R2 · MISSING DEPENDENCY" emphasis delay={0.72} />
            <DrawPath d={gapToDecision} kind="missing-faint" delay={0.78} />
          </>
        )}

        {showInspectPulses && (
          <>
            <Pulse d={apexToDecision} duration={0.82} />
            <Pulse d={beaconToGap} tone="amber" duration={0.98} delay={0.68} stopAtEnd />
          </>
        )}

        {captureEstablished && (
          <>
            <DrawPath d={beaconToDecision} kind="history beacon-history" dim={now} delay={phase === 2 ? 0.5 : 0.04} />
            {phase === 2 && <motion.circle cx="604" cy="418" r="7" className="port-ack" initial={{ opacity: 0, scale: 0.4 }} animate={{ opacity: [0, 1, 0.72], scale: [0.4, 1.45, 1] }} transition={{ duration: 0.72, delay: 1.12 }} />}
            {showCommitPulse && <Pulse d={beaconToDecision} duration={1.02} delay={0.5} />}
          </>
        )}

        {now && (
          <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.45 }}>
            <DrawPath d={apexEval} kind="current-mismatch" delay={0.08} />
            <DrawPath d={beaconEval} kind="current-match" delay={0.12} />
            {showCurrentPulse && <Pulse d={apexEval} tone="red" duration={1.0} />}
            {showCurrentPulse && <Pulse d={beaconEval} tone="green" duration={1.08} delay={0.18} />}

            <InstrumentNode
              x={1060}
              y={220}
              title={labelForMatch("M1")}
              subtitle={humanizeMatch(matches.M1)}
              kind="signal"
              status={{ label: matchLabels(view.current_matches).M1, tone: matches.M1 === "does_not_match" ? "red" : "neutral" }}
            />
            <InstrumentNode
              x={1060}
              y={500}
              title={labelForMatch("M2")}
              subtitle={humanizeMatch(matches.M2)}
              kind="signal"
              status={{ label: matchLabels(view.current_matches).M2, tone: matches.M2 === "matches" ? "green" : "neutral" }}
            />
          </motion.g>
        )}

        {reuse && view.reuse_boundary && (
          <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <DrawPath d={reuseApproach} kind="authorized-reuse" delay={0.05} />
            <Gap x={1118} y={602} label="sufficiency" emphasis />
            {showReusePulse && <Pulse d={reuseApproach} tone="amber" duration={1.15} stopAtEnd />}
            <motion.g animate={{ opacity: boundaryRevealed ? 0.72 : 0.34 }} transition={{ duration: 0.35 }}>
              <circle cx="1220" cy="636" r="30" className="reuse-destination" />
              <text x="1220" y="633" textAnchor="middle" className="reuse-label">REUSE</text>
              <text x="1220" y="647" textAnchor="middle" className="reuse-sub">old decision</text>
            </motion.g>
          </motion.g>
        )}
      </svg>

      <AnimatePresence mode="wait">
        {phase === 1 && (
          <motion.div
            className="context-card gap-question"
            key="question"
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.34, delay: 1.55 }}
          >
            <span className="context-label">ONE MISSING DECISION DEPENDENCY</span>
            <strong>{view.capture.question}</strong>
            <small>Decision Recall asks instead of inferring.</small>
          </motion.div>
        )}
      </AnimatePresence>

      {phase === 4 && boundaryRevealed && reusePresentationModel(view.reuse_boundary).showStop && (
        <motion.div className="boundary-hero" initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.42 }}>
          <span className="context-label">REUSE SUFFICIENCY · NEVER ESTABLISHED</span>
          <h2>{reusePresentationModel(view.reuse_boundary).title}</h2>
          <p>{reusePresentationModel(view.reuse_boundary).explanation}</p>
          <div className="boundary-status">{view.reuse_boundary.safe_reuse_result.replaceAll("_", " ")}</div>
          {view.reuse_boundary.limiting_requirements.length > 0 && <small className="boundary-limits">Limiting requirement: {view.reuse_boundary.limiting_requirements.join(", ")}</small>}
        </motion.div>
      )}

      {phase === 4 && boundaryRevealed && view.reuse_boundary && !reusePresentationModel(view.reuse_boundary).showStop && (
        <motion.div className="boundary-hero neutral" initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.42 }}>
          <span className="context-label">SERVER-DERIVED REUSE RESULT</span>
          <h2>{reusePresentationModel(view.reuse_boundary).title}</h2>
          <div className="boundary-status">{view.reuse_boundary.safe_reuse_result.replaceAll("_", " ")}</div>
          {view.reuse_boundary.limiting_requirements.length > 0 && <small className="boundary-limits">Limiting requirement: {view.reuse_boundary.limiting_requirements.join(", ")}</small>}
        </motion.div>
      )}
    </div>
  );
}

function preparationView(preparation) {
  return {
    decision_id: preparation.decision_id,
    capture: {
      relation_id: preparation.gap_id,
      question: preparation.question,
      knowledge_state: preparation.knowledge_state,
    },
    current_matches: [],
    reuse_boundary: null,
    evaluation_hash: null,
    replay_hash: null,
  };
}

function LaterWorldRecords({ pending, error, complete, acceptedCount }) {
  const records = Object.fromEntries(SUPPLIED_T1_RECORDS.map((record) => [record.metric_key, record]));
  return (
    <motion.section
      className={`later-world-records ${pending ? "pending" : ""} ${complete ? "complete" : ""}`}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.38 }}
      aria-label="Supplied later-world records"
    >
      {!complete && <header>
        <span>SIMULATED T1 · +6 WEEKS</span>
        <b>SUPPLIED LATER-WORLD RECORDS</b>
        <small>Demo inputs · external origin not independently authenticated</small>
      </header>}
      {!complete && <div className="later-record-grid">
        <article><span>APEX</span><strong>{records.apex_on_time_rate.value * 100}% on-time</strong><small>{records.apex_on_time_rate.window_days}-day window</small></article>
        <article><span>BEACON</span><strong>{records.beacon_reactivation_days.value} days</strong><small>to reactivate</small></article>
      </div>}
      {pending && <div className="reevaluation-state pending"><b>VALIDATING &amp; REEVALUATING LATER-WORLD RECORDS…</b><span>Awaiting the live Cloud Run response.</span></div>}
      {error && <div className="reevaluation-state error"><b>REEVALUATION NOT ACCEPTED</b><span>{error}</span></div>}
      {complete && <div className="reevaluation-state accepted"><b>{acceptedCount} RECORDS ADMITTED UNDER EVENT POLICY</b><span>REEVALUATION COMPLETE</span></div>}
    </motion.section>
  );
}

async function loadInitialState() {
  try {
    const runtime = await fetch("/api/capture-preparation", { cache: "no-store" });
    if (!runtime.ok) throw new Error(`capture preparation returned ${runtime.status}`);
    const preparation = await runtime.json();
    return {
      preparation,
      view: preparationView(preparation),
      source: "live",
    };
  } catch (runtimeError) {
    const fallback = await fetch("/demo-state.json", { cache: "no-store" });
    if (!fallback.ok) throw runtimeError;
    const view = await fallback.json();
    return {
      preparation: null,
      view,
      source: "replay",
    };
  }
}

function App() {
  const [view, setView] = useState(null);
  const [preparation, setPreparation] = useState(null);
  const [source, setSource] = useState("loading");
  const [error, setError] = useState(null);
  const [phase, setPhase] = useState(0);
  const [boundaryRevealed, setBoundaryRevealed] = useState(false);
  const [proofOpen, setProofOpen] = useState(false);
  const [captureStatus, setCaptureStatus] = useState("idle");
  const [captureError, setCaptureError] = useState(null);
  const [captureValidation, setCaptureValidation] = useState(null);
  const [captureEnvelope, setCaptureEnvelope] = useState(null);
  const [reevaluationStatus, setReevaluationStatus] = useState("idle");
  const [reevaluationError, setReevaluationError] = useState(null);
  const [reevaluationResult, setReevaluationResult] = useState(null);
  const [agentProofRequested, setAgentProofRequested] = useState(false);
  const requestGeneration = useRef(0);
  const reevaluationController = useRef(null);

  const applyInitialState = ({ preparation: nextPreparation, view: nextView, source: nextSource }) => {
    setPreparation(nextPreparation);
    setView(nextView);
    setSource(nextSource);
    setCaptureStatus("idle");
    setCaptureError(null);
    setCaptureValidation(null);
    setCaptureEnvelope(null);
    setReevaluationStatus("idle");
    setReevaluationError(null);
    setReevaluationResult(null);
  };

  useEffect(() => {
    loadInitialState().then(applyInitialState).catch(setError);
  }, []);

  useEffect(() => {
    setBoundaryRevealed(false);
    if (phase === 4) {
      const timer = window.setTimeout(() => setBoundaryRevealed(true), 1850);
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [phase]);

  useEffect(() => {
    if (phase !== 1) {
      setAgentProofRequested(false);
      return undefined;
    }
    setAgentProofRequested(true);
    const timer = window.setTimeout(() => setAgentProofRequested(false), AGENT_PROOF_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [phase]);

  if (error) {
    return <main className="boot"><h1>Decision Threads needs engine state.</h1><p>Cloud runtime and deterministic replay both failed.</p><pre>{String(error)}</pre></main>;
  }
  if (!view) return <main className="boot"><p>Loading authoritative capture state…</p></main>;

  const copy = COPY[phase];
  const live = source === "live";
  const capturePending = captureStatus === "pending";
  const reevaluationPending = reevaluationStatus === "pending";
  const reevaluationComplete = !live || reevaluationStatus === "complete";
  const pending = capturePending || reevaluationPending;
  const reuseModel = reusePresentationModel(view.reuse_boundary);
  const phaseCopy = phase === 2
    ? {
        ...copy,
        body: live
          ? "Cloud Run verified the human response. R2 now connects Beacon’s recorded constraint to D-104."
          : "The verified capture is being replayed. R2 connects Beacon’s recorded constraint to D-104.",
      }
    : phase === 3 && reevaluationStatus === "complete"
      ? {
          ...copy,
          eyebrow: "Reevaluation complete",
          title: "The world changes. History does not.",
          body: "Server-derived current applicability is now visible; historical authority remains intact.",
        }
      : phase === 4 && view.reuse_boundary
        ? {
            ...copy,
            title: reuseModel.title,
            body: reuseModel.explanation,
          }
        : copy;

  const submitLiveCapture = async () => {
    if (!live || !preparation || capturePending) return;

    setCaptureStatus("pending");
    setCaptureError(null);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);

    try {
      const response = await fetch("/api/capture", {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          capture_session_id: preparation.capture_session_id,
          gap_id: preparation.gap_id,
          question_hash: preparation.question_hash,
          answer: "yes",
        }),
      });

      let payload = null;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }
      if (!response.ok) {
        const message = payload?.message || `capture gate returned ${response.status}`;
        throw new Error(message);
      }
      if (
        payload?.capture_validation?.status !== "accepted"
        || payload?.capture?.knowledge_state !== "established"
        || payload?.future_evaluation_status !== "not_requested"
      ) {
        throw new Error("capture gate returned an invalid success envelope");
      }

      setCaptureValidation(payload.capture_validation);
      setCaptureEnvelope(payload);
      setView(captureView(preparation, payload));
      setCaptureStatus("verified");
      setPhase(2);
    } catch (captureFailure) {
      setCaptureStatus("error");
      setCaptureError(
        captureFailure?.name === "AbortError"
          ? "Cloud Run verification timed out. The historical role remains unresolved."
          : captureFailure?.message || String(captureFailure),
      );
    } finally {
      window.clearTimeout(timeout);
    }
  };

  const submitLiveReevaluation = async () => {
    if (!live || !preparation || !captureEnvelope || reevaluationPending) return;

    const generation = requestGeneration.current;
    const controller = new AbortController();
    reevaluationController.current = controller;
    setReevaluationStatus("pending");
    setReevaluationError(null);
    const timeout = window.setTimeout(() => controller.abort(), 8000);

    try {
      const response = await fetch("/api/reevaluate", {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify(buildReevaluationPayload(preparation)),
      });
      let payload = null;
      try { payload = await response.json(); } catch { payload = null; }
      if (!response.ok) throw new Error(payload?.message || `reevaluation returned ${response.status}`);
      if (
        payload?.status !== "reevaluated"
        || !Array.isArray(payload.current_matches)
        || !Array.isArray(payload.accepted_world_events)
        || !payload.evaluation_hash
        || !payload.replay_hash
      ) {
        throw new Error("reevaluation returned an invalid success envelope");
      }
      if (!isCurrentRequest(generation, requestGeneration.current)) return;
      setReevaluationResult(payload);
      setView((current) => reevaluatedView(current, payload));
      setReevaluationStatus("complete");
    } catch (reevaluationFailure) {
      if (!isCurrentRequest(generation, requestGeneration.current)) return;
      setReevaluationStatus("error");
      setReevaluationError(
        reevaluationFailure?.name === "AbortError"
          ? "Cloud Run reevaluation timed out. T0 remains the last accepted state."
          : reevaluationFailure?.message || String(reevaluationFailure),
      );
    } finally {
      window.clearTimeout(timeout);
      if (reevaluationController.current === controller) reevaluationController.current = null;
    }
  };

  const resetExperience = async () => {
    requestGeneration.current += 1;
    reevaluationController.current?.abort();
    reevaluationController.current = null;
    setBoundaryRevealed(false);
    setPhase(0);
    try {
      applyInitialState(await loadInitialState());
    } catch (resetError) {
      setError(resetError);
    }
  };

  const next = async () => {
    if (phase === 0) {
      setPhase(1);
      return;
    }
    if (phase === 1) {
      if (live) {
        await submitLiveCapture();
      } else {
        setPhase(2);
      }
      return;
    }
    if (phase === 4) {
      await resetExperience();
      return;
    }
    if (phase === 3 && live && reevaluationStatus !== "complete") {
      await submitLiveReevaluation();
      return;
    }
    setPhase((current) => current + 1);
  };

  const actionLabel = phase === 1
    ? live
      ? capturePending
        ? "Verifying with Cloud Run…"
        : captureStatus === "error"
          ? "Retry verification"
          : COPY[1].action
      : "Replay capture"
    : phase === 3 && live
      ? reevaluationPending
        ? "Validating & reevaluating…"
        : reevaluationStatus === "error"
          ? "Retry ingest & reevaluate"
          : reevaluationStatus === "complete"
            ? "Try to reuse the decision"
            : COPY[3].action
      : phase === 3 && !live
        ? "Replay reevaluation"
        : copy.action;

  const boundary = view.reuse_boundary;
  const showAgentProof = agentProofVisibleForPhase(phase, agentProofRequested);

  return (
    <main className={`app phase-${phase} ${showAgentProof ? "agent-proof-active" : ""}`}>
      <header className="topbar">
        <div className="brand-wrap">
          <div className="brand-mark">DR</div>
          <div><b>DECISION RECALL</b><span>TEMPORAL OBSERVATORY</span></div>
        </div>
        <div className="top-actions">
          <button className="proof-button" onClick={() => setProofOpen((x) => !x)}>Why / Proof</button>
          <div className={`live-dot ${live ? "live" : "fallback"}`}>
            <span />{live ? "Cloud Run · live engine" : "deterministic replay"}
          </div>
        </div>
      </header>

      <section className="experience">
        <DecisionCanvas phase={phase} view={view} boundaryRevealed={boundaryRevealed} reevaluationComplete={reevaluationComplete} />

        <AnimatePresence>
          {showAgentProof && (
            <AgentProof live={live} view={view} />
          )}
        </AnimatePresence>

        {phase === 1 && live && capturePending && (
          <motion.div className="capture-gate-state pending" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
            <b>VERIFYING WITH CLOUD RUN…</b>
            <span>No server acceptance, no historical edge.</span>
          </motion.div>
        )}

        {phase === 1 && live && captureStatus === "error" && (
          <motion.div className="capture-gate-state error" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
            <b>RESPONSE NOT VERIFIED</b>
            <span>{captureError}</span>
          </motion.div>
        )}

        {phase === 2 && live && captureValidation && (
          <motion.div className="capture-gate-state accepted" initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.3 }}>
            <b>SERVER VERIFIED</b>
            <span className="capture-state-change"><s>NOT ESTABLISHED</s><i>→</i><strong>ESTABLISHED</strong></span>
            <small>Response binding matched · completion permitted</small>
          </motion.div>
        )}

        {phase === 3 && live && (
          <LaterWorldRecords
            pending={reevaluationPending}
            error={reevaluationError}
            complete={reevaluationStatus === "complete"}
            acceptedCount={reevaluationResult?.accepted_world_events?.length || 0}
          />
        )}

        {!(phase === 4 && boundaryRevealed) && (
          <motion.aside className="scene-note" key={phase} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.3 }}>
            <span>{phaseCopy.eyebrow}</span>
            <h1>{phaseCopy.title}</h1>
            <p>{phaseCopy.body}</p>
          </motion.aside>
        )}

        <div className="scene-index"><b>0{phase + 1}</b><span>/05</span></div>

        <button onClick={next} disabled={pending || showAgentProof} className={`primary ${phase === 4 ? "replay" : ""} ${pending ? "pending" : ""}`}>
          {actionLabel}<span>→</span>
        </button>
      </section>

      <AnimatePresence>
        {proofOpen && (
          <motion.aside className="proof-drawer" initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ type: "spring", stiffness: 260, damping: 28 }}>
            <button className="proof-close" onClick={() => setProofOpen(false)}>×</button>
            <span className="drawer-eyebrow">CAPTURE GATE / ENGINE PROOF</span>
            <h3>{live ? "Server-authoritative capture state." : "Deterministic replay mode."}</h3>
            <dl>
              <div><dt>Presentation source</dt><dd>{live ? "Cloud Run /api/capture-preparation" : "demo-state.json replay"}</dd></div>
              {preparation && <div><dt>Capture session</dt><dd>{preparation.capture_session_id}</dd></div>}
              <div><dt>Issued gap</dt><dd>{preparation?.gap_id || view.capture.relation_id}</dd></div>
              {preparation && <div><dt>Pre-capture knowledge</dt><dd>{preparation.knowledge_state}</dd></div>}
              {captureValidation && <div><dt>Human response</dt><dd>{captureValidation.answer.toUpperCase()} · VERIFIED</dd></div>}
              {captureValidation && <div><dt>Winner completion</dt><dd>{captureValidation.completion.toUpperCase()}</dd></div>}
              <div><dt>Current knowledge</dt><dd>{view.capture.knowledge_state}</dd></div>
              {live && captureValidation && !reevaluationResult && <div><dt>Future evaluation</dt><dd>NOT REQUESTED</dd></div>}
              {reevaluationResult && <div><dt>Later-world records</dt><dd>{reevaluationResult.accepted_world_events.length} ADMITTED UNDER EVENT POLICY</dd></div>}
              {boundary && <div><dt>Reuse result</dt><dd>{boundary.safe_reuse_result}</dd></div>}
              {boundary && <div><dt>Limiting requirement</dt><dd>{boundary.limiting_requirements.join(", ")}</dd></div>}
              {view.evaluation_hash && <div><dt>Evaluation hash</dt><dd><code>{view.evaluation_hash}</code></dd></div>}
              {view.replay_hash && <div><dt>Replay hash</dt><dd><code>{view.replay_hash}</code></dd></div>}
            </dl>
          </motion.aside>
        )}
      </AnimatePresence>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
