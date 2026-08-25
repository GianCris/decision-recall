import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { AnimatePresence, motion } from "motion/react";
import "./styles.css";

const COPY = {
  0: {
    eyebrow: "Original decision",
    title: "A company relies on two suppliers.",
    body: "Apex has been unstable. Beacon takes about 10 weeks to restart.",
    action: "Inspect decision",
  },
  1: {
    eyebrow: "Decision Recall detected a gap",
    title: "The records can’t tell us whether Beacon actually mattered.",
    body: "The system stops at the missing relation instead of guessing.",
    action: "Yes — Beacon mattered",
  },
  2: {
    eyebrow: "Captured at decision time",
    title: "A missing piece becomes durable decision history.",
    body: "The person’s answer completes the historical thread.",
    action: "Advance six weeks",
  },
  3: {
    eyebrow: "Six weeks later",
    title: "The world changed. The historical record didn’t.",
    body: "Apex improved to 98.7% on-time delivery over 30 days. Current-world match changes independently from what mattered then.",
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

function Thread({ d, active = true, broken = false, missing = false, delay = 0 }) {
  return (
    <>
      <motion.path
        d={d}
        fill="none"
        className={`thread-path ${active ? "active" : "muted"} ${broken ? "broken" : ""} ${missing ? "missing" : ""}`}
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ duration: 0.8, delay, ease: [0.22, 1, 0.36, 1] }}
      />
      {active && !missing && (
        <circle r="5" className="pulse-dot">
          <animateMotion dur="2.4s" repeatCount="indefinite" path={d} />
        </circle>
      )}
    </>
  );
}

function Node({ x, y, title, subtitle, tone = "neutral", compact = false }) {
  return (
    <motion.g initial={{ opacity: 0, scale: 0.94 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.35 }}>
      <rect x={x - (compact ? 72 : 92)} y={y - 34} width={compact ? 144 : 184} height="68" rx="18" className={`node-card ${tone}`} />
      <text x={x} y={y - 2} textAnchor="middle" className="node-title">{title}</text>
      <text x={x} y={y + 18} textAnchor="middle" className="node-subtitle">{subtitle}</text>
    </motion.g>
  );
}

function DecisionCanvas({ phase, view }) {
  const captureEstablished = phase >= 2;
  const now = phase >= 3;
  const reuse = phase >= 4;
  const matches = useMemo(() => Object.fromEntries(view.current_matches.map((x) => [x.entity_id, x.state])), [view]);

  return (
    <div className="canvas-shell">
      <div className="time-rail">
        <span className="time-label then">THEN</span>
        <motion.div className="time-progress" animate={{ width: now ? "100%" : "8%" }} transition={{ duration: 0.9, ease: "easeInOut" }} />
        <span className={`time-label now ${now ? "visible" : ""}`}>NOW</span>
      </div>

      <svg viewBox="0 0 1100 560" className="decision-canvas" role="img" aria-label="Decision Recall temporal decision graph">
        <defs>
          <filter id="softGlow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
        </defs>

        <text x="84" y="66" className="canvas-kicker">OBSERVABLE WORLD</text>
        <text x="450" y="66" className="canvas-kicker">DECISION RECORD</text>
        {now && <text x="842" y="66" className="canvas-kicker">CURRENT WORLD</text>}

        <Node x={160} y={170} title="Apex" subtitle={now ? "98.7% on-time · 30d" : "delivery unstable"} tone={now ? "changed" : "warning"} />
        <Node x={160} y={365} title="Beacon" subtitle="~10 weeks to restart" tone="stable" />
        <Node x={540} y={270} title="Decision D-104" subtitle="keep access to both · 6 months" tone="decision" />

        <Thread d="M252 170 C345 170 390 228 448 254" active />

        {!captureEstablished && (
          <>
            <Thread d="M252 365 C340 365 378 325 430 294" active missing delay={0.15} />
            <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.6 }}>
              <circle cx="446" cy="288" r="22" className="gap-node" filter="url(#softGlow)" />
              <text x="446" y="296" textAnchor="middle" className="gap-mark">?</text>
            </motion.g>
          </>
        )}

        {captureEstablished && <Thread d="M252 365 C350 365 400 322 448 292" active delay={0.05} />}

        {now && (
          <>
            <motion.g initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }}>
              <Node x={900} y={170} title={labelForMatch("M1")} subtitle={matches.M1 || "current state"} tone="broken" compact />
              <Node x={900} y={365} title={labelForMatch("M2")} subtitle={matches.M2 || "current state"} tone="stable" compact />
              <Thread d="M632 250 C715 220 770 185 828 174" active={false} broken />
              <Thread d="M632 292 C720 323 770 355 828 362" active />
            </motion.g>
          </>
        )}

        {reuse && (
          <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <rect x="800" y="462" width="210" height="68" rx="18" className="node-card reuse" />
            <text x="905" y="490" textAnchor="middle" className="node-title">Reuse old decision?</text>
            <text x="905" y="510" textAnchor="middle" className="node-subtitle">needs sufficiency</text>
            <Thread d="M900 399 C900 420 900 435 900 447" active missing />
            <circle cx="900" cy="433" r="23" className="gap-node" />
            <text x="900" y="441" textAnchor="middle" className="gap-mark">?</text>
          </motion.g>
        )}
      </svg>

      {phase === 1 && (
        <motion.div className="gap-callout" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
          <div className="callout-label">ONE MISSING DECISION DEPENDENCY</div>
          <strong>{view.capture.question}</strong>
          <span>Decision Recall asks instead of inferring.</span>
        </motion.div>
      )}

      {phase === 4 && (
        <motion.div className="boundary-chip" initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }}>
          <span>{view.reuse_boundary.safe_reuse_result.replaceAll("_", " ")}</span>
          <b>missing: {view.reuse_boundary.limiting_requirements.join(", ")}</b>
        </motion.div>
      )}
    </div>
  );
}

function App() {
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    fetch("/demo-state.json")
      .then((r) => {
        if (!r.ok) throw new Error("demo-state.json was not generated");
        return r.json();
      })
      .then(setView)
      .catch(setError);
  }, []);

  if (error) {
    return <main className="boot"><h1>Decision Threads needs engine state.</h1><p>Run <code>npm run state</code> from apps/decision-threads, then reload.</p><pre>{String(error)}</pre></main>;
  }
  if (!view) return <main className="boot"><p>Loading frozen engine state…</p></main>;

  const copy = COPY[phase];
  const next = () => setPhase((p) => (p === 4 ? 0 : p + 1));

  return (
    <main className={`app phase-${phase}`}>
      <header className="topbar">
        <div className="brand-wrap"><div className="brand-mark">DR</div><div><b>Decision Recall</b><span>Decision Threads</span></div></div>
        <div className="truth-badge"><span className="truth-dot" /> engine-bound demo state</div>
      </header>

      <section className="hero-grid">
        <div className="narrative">
          <AnimatePresence mode="wait">
            <motion.div key={phase} initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }} transition={{ duration: 0.28 }}>
              <div className="eyebrow">{copy.eyebrow}</div>
              <h1>{copy.title}</h1>
              <p>{copy.body}</p>
            </motion.div>
          </AnimatePresence>
        </div>

        <DecisionCanvas phase={phase} view={view} />
      </section>

      <footer className="action-dock">
        <div className="phase-index">0{phase + 1}<span>/05</span></div>
        <button onClick={next} className={phase === 4 ? "primary replay" : "primary"}>
          {copy.action}<span>→</span>
        </button>
        <div className="proof-mini">evaluation <code>{view.evaluation_hash.slice(0, 9)}</code> · replay <code>{view.replay_hash.slice(0, 9)}</code></div>
      </footer>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
