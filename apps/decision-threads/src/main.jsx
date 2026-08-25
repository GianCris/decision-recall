import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { AnimatePresence, motion } from "motion/react";
import "./styles.css";

const COPY = {
  0: {
    eyebrow: "Initial decision",
    title: "A decision held in time.",
    body: "Apex was unstable. Beacon needed about 10 weeks to restart, so D-104 kept both for six months.",
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
    body: "Cloud Run accepted the response. R2 now connects Beacon’s recorded constraint to D-104.",
    action: "Advance six weeks",
  },
  3: {
    eyebrow: "Six weeks later",
    title: "The world changes. History does not.",
    body: "Apex improves to 98.7% on-time delivery. Current-world evaluation changes while the historical decision record remains intact.",
    action: "Try to reuse the decision",
  },
  4: {
    eyebrow: "Reuse boundary",
    title: "I CAN’T ESTABLISH THAT",
    body: "Beacon mattered to the original decision. What was never established: was that reason sufficient on its own?",
    action: "Replay",
  },
};

const labelForMatch = (id) => ({ M1: "Apex instability", M2: "Beacon restart delay" }[id] || id);
const humanizeMatch = (state) => ({
  does_not_match: "no longer matches",
  matches: "still matches",
}[state] || "current evaluation");

const delay = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

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

function DecisionCanvas({ phase, view, boundaryRevealed }) {
  const captureEstablished = phase >= 2;
  const gapDiscovered = phase >= 1 && !captureEstablished;
  const now = phase >= 3;
  const reuse = phase >= 4;
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
              status={{ label: "NO LONGER MATCHES", tone: "red" }}
            />
            <InstrumentNode
              x={1060}
              y={500}
              title={labelForMatch("M2")}
              subtitle={humanizeMatch(matches.M2)}
              kind="signal"
              status={{ label: "STILL MATCHES", tone: "green" }}
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

      {phase === 4 && boundaryRevealed && view.reuse_boundary && (
        <motion.div className="boundary-hero" initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.42 }}>
          <span className="context-label">EPISTEMIC STOP</span>
          <h2>I CAN’T ESTABLISH THAT</h2>
          <p>Beacon mattered then. We never established whether that reason was sufficient on its own.</p>
          <div className="boundary-status">{view.reuse_boundary.safe_reuse_result.replaceAll("_", " ")}</div>
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

  const applyInitialState = ({ preparation: nextPreparation, view: nextView, source: nextSource }) => {
    setPreparation(nextPreparation);
    setView(nextView);
    setSource(nextSource);
    setCaptureStatus("idle");
    setCaptureError(null);
    setCaptureValidation(null);
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

  if (error) {
    return <main className="boot"><h1>Decision Threads needs engine state.</h1><p>Cloud runtime and deterministic replay both failed.</p><pre>{String(error)}</pre></main>;
  }
  if (!view) return <main className="boot"><p>Loading authoritative capture state…</p></main>;

  const copy = COPY[phase];
  const live = source === "live";
  const pending = captureStatus === "pending";

  const submitLiveCapture = async () => {
    if (!live || !preparation || pending) return;

    setCaptureStatus("pending");
    setCaptureError(null);
    const startedAt = performance.now();
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
      if (payload?.capture_validation?.status !== "accepted" || !payload?.presentation) {
        throw new Error("capture gate returned an invalid success envelope");
      }

      const elapsed = performance.now() - startedAt;
      if (elapsed < 420) await delay(420 - elapsed);

      setCaptureValidation(payload.capture_validation);
      setView(payload.presentation);
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

  const resetExperience = async () => {
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
    setPhase((current) => current + 1);
  };

  const actionLabel = phase === 1
    ? live
      ? pending
        ? "Verifying with Cloud Run…"
        : captureStatus === "error"
          ? "Retry verification"
          : COPY[1].action
      : "Replay capture"
    : copy.action;

  const boundary = view.reuse_boundary;

  return (
    <main className={`app phase-${phase}`}>
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
        <DecisionCanvas phase={phase} view={view} boundaryRevealed={boundaryRevealed} />

        {phase === 1 && live && pending && (
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
            <b>HUMAN RESPONSE · VERIFIED</b>
            <span>R2 · HISTORICAL ROLE ESTABLISHED</span>
          </motion.div>
        )}

        {!(phase === 4 && boundaryRevealed) && (
          <motion.aside className="scene-note" key={phase} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.3 }}>
            <span>{copy.eyebrow}</span>
            <h1>{copy.title}</h1>
            <p>{copy.body}</p>
          </motion.aside>
        )}

        <div className="scene-index"><b>0{phase + 1}</b><span>/05</span></div>

        <button onClick={next} disabled={pending} className={`primary ${phase === 4 ? "replay" : ""} ${pending ? "pending" : ""}`}>
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
