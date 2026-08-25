import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { AnimatePresence, motion } from "motion/react";
import "./styles.css";

const COPY = {
  0: {
    eyebrow: "Original decision",
    title: "Two suppliers. One decision.",
    body: "Apex was unstable. Beacon took about 10 weeks to restart. The company kept access to both for six months.",
    action: "Inspect decision",
  },
  1: {
    eyebrow: "Gap discovered",
    title: "One relationship is missing.",
    body: "The records show Beacon’s restart delay, but not whether keeping Beacon available actually mattered to the decision.",
    action: "Yes — Beacon mattered",
  },
  2: {
    eyebrow: "Captured at decision time",
    title: "The missing edge becomes durable history.",
    body: "The person’s answer changes the decision record. Decision Recall can use that relationship later without pretending it came from documents.",
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

function DrawPath({ d, kind = "history", delay = 0, dim = false }) {
  return (
    <motion.path
      d={d}
      fill="none"
      className={`thread ${kind} ${dim ? "dim" : ""}`}
      initial={{ pathLength: 0, opacity: 0 }}
      animate={{ pathLength: 1, opacity: 1 }}
      transition={{ duration: 0.72, delay, ease: [0.22, 1, 0.36, 1] }}
    />
  );
}

function Pulse({ d, tone = "green", duration = 1.15, delay = 0, stopAtEnd = false }) {
  return (
    <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay }}>
      <circle r="6" className={`trace-pulse ${tone}`}>
        <animateMotion dur={`${duration}s`} begin={`${delay}s`} fill="freeze" repeatCount="1" path={d} />
      </circle>
      {stopAtEnd && <circle r="12" className={`trace-halo ${tone}`} opacity="0" />}
    </motion.g>
  );
}

function InstrumentNode({ x, y, title, subtitle, kind = "entity", status, active = true }) {
  const radius = kind === "decision" ? 58 : 46;
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

function Gap({ x, y, label, emphasis = false }) {
  return (
    <motion.g initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} transition={{ type: "spring", stiffness: 250, damping: 18 }}>
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
  const now = phase >= 3;
  const reuse = phase >= 4;
  const matches = useMemo(() => Object.fromEntries(view.current_matches.map((x) => [x.entity_id, x.state])), [view]);

  const apexToDecision = "M235 210 C360 210 408 294 495 318";
  const beaconToGap = "M235 500 C360 500 405 420 468 376";
  const gapToDecision = "M498 366 C520 350 534 338 550 329";
  const beaconToDecision = "M235 500 C372 500 430 410 548 346";
  const apexEval = "M652 314 C760 278 832 236 930 210";
  const beaconEval = "M652 352 C756 393 830 452 930 500";
  const reuseApproach = "M930 500 C986 522 1017 546 1036 575";
  const unsupportedEdge = "M1068 608 C1110 628 1152 640 1196 640";

  const showApexPulse = phase === 0;
  const showGapPulse = phase === 1;
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
      </div>

      <svg viewBox="0 0 1240 720" className="decision-canvas" role="img" aria-label="Decision Recall temporal decision graph">
        <defs>
          <linearGradient id="decisionFill" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#252933" />
            <stop offset="100%" stopColor="#0d1016" />
          </linearGradient>
        </defs>

        <text x="118" y="105" className="plane-label">OBSERVED WORLD</text>
        <text x="520" y="105" className="plane-label">DECISION MEMORY</text>
        {now && <motion.text x="910" y="105" className="plane-label" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>CURRENT WORLD</motion.text>}

        <InstrumentNode
          x={180}
          y={210}
          title="Apex"
          subtitle={now ? "98.7% on-time · 30d" : "delivery unstable"}
          kind="entity"
          status={now ? { label: "CURRENT EVIDENCE", tone: "blue" } : { label: "OBSERVED AT T0", tone: "neutral" }}
        />
        <InstrumentNode
          x={180}
          y={500}
          title="Beacon"
          subtitle="~10 weeks to restart"
          kind="entity"
          status={{ label: now ? "CURRENT EVIDENCE" : "OBSERVED AT T0", tone: now ? "green" : "neutral" }}
        />
        <InstrumentNode x={610} y={335} title="D-104" subtitle="keep both · 6 months" kind="decision" status={{ label: "RECORDED DECISION", tone: "neutral" }} />

        <DrawPath d={apexToDecision} kind="history" dim={now} />
        {showApexPulse && <Pulse d={apexToDecision} />}

        {!captureEstablished && (
          <>
            <DrawPath d={beaconToGap} kind="missing" delay={0.08} />
            <Gap x={486} y={373} label="missing dependency" emphasis={phase === 1} />
            <DrawPath d={gapToDecision} kind="missing-faint" delay={0.12} />
            {showGapPulse && <Pulse d={beaconToGap} tone="amber" duration={1.1} stopAtEnd />}
          </>
        )}

        {captureEstablished && (
          <>
            <DrawPath d={beaconToDecision} kind="history" dim={now} delay={0.04} />
            {phase === 2 && (
              <motion.circle cx="486" cy="373" r="23" className="resolved-burst" initial={{ scale: 0, opacity: 0 }} animate={{ scale: [0, 1.8, 1], opacity: [0, 0.75, 0] }} transition={{ duration: 0.75 }} />
            )}
            {showCommitPulse && <Pulse d={beaconToDecision} duration={1.25} />}
          </>
        )}

        {now && (
          <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.45 }}>
            <DrawPath d={apexEval} kind="current-mismatch" delay={0.08} />
            <DrawPath d={beaconEval} kind="current-match" delay={0.12} />
            {showCurrentPulse && <Pulse d={apexEval} tone="red" duration={1.05} />}
            {showCurrentPulse && <Pulse d={beaconEval} tone="green" duration={1.1} delay={0.18} />}

            <InstrumentNode
              x={980}
              y={210}
              title={labelForMatch("M1")}
              subtitle={matches.M1 || "current state"}
              kind="signal"
              status={{ label: "NO LONGER MATCHES", tone: "red" }}
            />
            <InstrumentNode
              x={980}
              y={500}
              title={labelForMatch("M2")}
              subtitle={matches.M2 || "current state"}
              kind="signal"
              status={{ label: "MATCHES NOW", tone: "green" }}
            />
          </motion.g>
        )}

        {reuse && (
          <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <DrawPath d={reuseApproach} kind="authorized-reuse" delay={0.05} />
            <Gap x={1052} y={595} label="sufficiency" emphasis />
            <motion.path d={unsupportedEdge} fill="none" className="thread unsupported" initial={{ opacity: 0 }} animate={{ opacity: boundaryRevealed ? 1 : 0.25 }} transition={{ duration: 0.35 }} />
            {showReusePulse && <Pulse d={reuseApproach} tone="amber" duration={1.15} stopAtEnd />}
            <motion.g animate={{ opacity: boundaryRevealed ? 1 : 0.38 }} transition={{ duration: 0.35 }}>
              <circle cx="1200" cy="640" r="34" className="reuse-destination" />
              <text x="1200" y="636" textAnchor="middle" className="reuse-label">REUSE</text>
              <text x="1200" y="651" textAnchor="middle" className="reuse-sub">old decision</text>
            </motion.g>
          </motion.g>
        )}
      </svg>

      <AnimatePresence mode="wait">
        {phase === 1 && (
          <motion.div className="context-card gap-question" key="question" initial={{ opacity: 0, y: 16, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8 }}>
            <span className="context-label">ONE MISSING DECISION DEPENDENCY</span>
            <strong>{view.capture.question}</strong>
            <small>Decision Recall asks instead of inferring.</small>
          </motion.div>
        )}
      </AnimatePresence>

      {phase === 4 && boundaryRevealed && (
        <motion.div className="boundary-hero" initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.42 }}>
          <span className="context-label">EPISTEMIC STOP</span>
          <h2>I CAN’T ESTABLISH THAT</h2>
          <p>Beacon mattered then. We never established whether that reason was sufficient on its own.</p>
          <div className="boundary-status">{view.reuse_boundary.safe_reuse_result.replaceAll("_", " ")}</div>
        </motion.div>
      )}
    </div>
  );
}

function App() {
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  const [phase, setPhase] = useState(0);
  const [boundaryRevealed, setBoundaryRevealed] = useState(false);
  const [proofOpen, setProofOpen] = useState(false);

  useEffect(() => {
    fetch("/demo-state.json")
      .then((r) => {
        if (!r.ok) throw new Error("demo-state.json was not generated");
        return r.json();
      })
      .then(setView)
      .catch(setError);
  }, []);

  useEffect(() => {
    setBoundaryRevealed(false);
    if (phase === 4) {
      const timer = window.setTimeout(() => setBoundaryRevealed(true), 1450);
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [phase]);

  if (error) {
    return <main className="boot"><h1>Decision Threads needs engine state.</h1><p>Run <code>npm run state</code> from apps/decision-threads, then reload.</p><pre>{String(error)}</pre></main>;
  }
  if (!view) return <main className="boot"><p>Loading frozen engine state…</p></main>;

  const copy = COPY[phase];
  const next = () => setPhase((p) => (p === 4 ? 0 : p + 1));

  return (
    <main className={`app phase-${phase}`}>
      <header className="topbar">
        <div className="brand-wrap">
          <div className="brand-mark">DR</div>
          <div><b>DECISION RECALL</b><span>TEMPORAL OBSERVATORY</span></div>
        </div>
        <div className="top-actions">
          <button className="proof-button" onClick={() => setProofOpen((x) => !x)}>Why / Proof</button>
          <div className="live-dot"><span /> engine-bound</div>
        </div>
      </header>

      <section className="experience">
        <DecisionCanvas phase={phase} view={view} boundaryRevealed={boundaryRevealed} />

        <motion.aside className="scene-note" key={phase} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.3 }}>
          <span>{copy.eyebrow}</span>
          <h1>{copy.title}</h1>
          <p>{copy.body}</p>
        </motion.aside>

        <div className="scene-index"><b>0{phase + 1}</b><span>/05</span></div>

        <button onClick={next} className={`primary ${phase === 4 ? "replay" : ""}`}>
          {copy.action}<span>→</span>
        </button>
      </section>

      <AnimatePresence>
        {proofOpen && (
          <motion.aside className="proof-drawer" initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ type: "spring", stiffness: 260, damping: 28 }}>
            <button className="proof-close" onClick={() => setProofOpen(false)}>×</button>
            <span className="drawer-eyebrow">ENGINE-BOUND PROOF</span>
            <h3>Rendered from frozen engine state.</h3>
            <dl>
              <div><dt>Capture relation</dt><dd>{view.capture.relation_id}</dd></div>
              <div><dt>Knowledge state</dt><dd>{view.capture.knowledge_state}</dd></div>
              <div><dt>Reuse result</dt><dd>{view.reuse_boundary.safe_reuse_result}</dd></div>
              <div><dt>Limiting requirement</dt><dd>{view.reuse_boundary.limiting_requirements.join(", ")}</dd></div>
              <div><dt>Evaluation hash</dt><dd><code>{view.evaluation_hash}</code></dd></div>
              <div><dt>Replay hash</dt><dd><code>{view.replay_hash}</code></dd></div>
            </dl>
          </motion.aside>
        )}
      </AnimatePresence>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
