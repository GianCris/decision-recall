import React, { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createExplorerController, humanize, RESULT_LABELS, sourceMode } from "./explorer-state.js";
import "./explorer.css";

const dateLabel = value => value && Number.isFinite(Date.parse(value))
  ? new Date(value).toLocaleString("en-US", { timeZone: "UTC", dateStyle: "medium", timeStyle: "short" }) + " UTC" : "Not supplied / invalid time";

export default function Explorer() {
  const [controller] = useState(() => createExplorerController());
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  const resultRef = useRef(null);
  const errorRef = useRef(null);
  useEffect(() => { controller.loadCases(); return () => controller.dispose(); }, [controller]);
  useEffect(() => { resultRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [state.result]);
  useEffect(() => { errorRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [state.error]);
  const p = state.preparation;
  const busy = state.status.endsWith("loading") || state.status.endsWith("submitting");
  const factLabel = id => humanize(p?.known_facts.find(f => f.fact_id === id)?.semantic_key || id);
  const relations = state.capture?.historical_relations || p?.historical_relations || [];
  const retry = () => !state.cases.length ? controller.loadCases() : !p ? controller.select(state.selected) : !state.capture ? controller.capture() : controller.reevaluate();
  return <main className="explorer">
    <header className="explorer-header">
      <a href="#" className="explorer-back">← Flagship demonstration</a>
      <span>DECISION RECALL / EXPLORER</span>
    </header>
    <section className="explorer-intro">
      <div><p className="ex-eyebrow">MEMORY IS NOT AUTHORITY.</p><h1>Explore Decision Recall</h1>
        <p>One shared lifecycle. Different decision records. Outcomes determined by the server.</p></div>
      <span className="ex-badge">Registered examples</span>
    </section>
    <nav className="explorer-cases" aria-label="Registered decisions">
      {state.cases.map(item => <button key={item.decision_id} aria-pressed={state.selected === item.decision_id}
        onClick={() => controller.select(item.decision_id)}>
        <small>{item.decision_id} · {humanize(item.profile_id)}</small><strong>{item.title}</strong><span aria-hidden="true">↗</span>
      </button>)}
    </nav>
    {state.status.endsWith("loading") && <p role="status" className="ex-notice">{state.status === "cases-loading" ? "Loading registered decisions…" : "Loading the server-issued preparation…"}</p>}
    {state.error && <div ref={errorRef} role="alert" className="ex-error"><strong>Request not completed</strong><p>{state.error}</p><button onClick={retry}>Retry request</button></div>}
    {!state.selected && !busy && !state.error && <div className="ex-empty"><span>01</span><h2>Choose a decision to inspect.</h2><p>Start with the records. Supply human authority only where a historical relation is missing.</p></div>}
    {p && <>
      <div className="ex-case-heading"><h2>{p.title}</h2><button onClick={() => controller.select(state.selected)}>Reset this decision</button></div>
      <aside className="ex-source-mode"><strong>{sourceMode(p.candidate_source_mode)}</strong>
        {p.candidate_source_mode === "configured_mechanically_grounded_example_candidates" && <span>Candidate spans are mechanically grounded to registered example records. No live Gemini execution is claimed for this Explorer run.</span>}
      </aside>
      <div className="explorer-grid">
        <section className="ex-history" aria-label="Historical decision state">
          <p className="ex-eyebrow">PAST / T0 · {p.decision_id}</p><h2>What was established then</h2><p className="ex-time">{dateLabel(p.decision_time)}</p>
          <details className="ex-records" open={!state.capture}><summary>Original decision records</summary>
            {p.source_records.map(record => <blockquote key={record.source_id}><p>{record.excerpt}</p><cite>{humanize(record.source_id)}</cite></blockquote>)}
          </details>
          <h3>Known facts</h3><ul className="ex-facts">{p.known_facts.map(f => <li key={f.fact_id}><span aria-hidden="true">✓</span>{humanize(f.semantic_key)}</li>)}</ul>
          <h3>Historical influence</h3><ul className="ex-relations">{relations.map(r => <li key={r.relation_id}>
            <span>{factLabel(r.subject_id)}</span><b className={r.knowledge_state === "established" ? "ex-established" : "ex-unresolved"}>{humanize(r.knowledge_state)}</b>
          </li>)}</ul>
          {state.capture && <p className="ex-verified">✓ Response binding verified server-side.<br />Historical authority established through the deterministic core.</p>}
        </section>
        <section className="ex-work" aria-label={state.capture ? "Supplied later-world observations" : "Exact human clarification"}>
          {!state.capture ? <>
            <p className="ex-eyebrow">ONE REQUIRED RELATION IS UNRESOLVED</p><h2>Only the missing relation.</h2>
            <p className="ex-question">{p.question}</p>
            <p className="ex-support">A known fact does not establish its role in the decision. The server issued this exact clarification.</p>
            <button className="ex-primary" disabled={busy} onClick={() => controller.capture()}>{state.status === "capture-submitting" ? "Verifying response binding…" : "Yes — verify my response"}</button>
            <p className="ex-fine">This bounded example supports an affirmative declaration. No later-world evaluation has run.</p>
          </> : <>
            <p className="ex-eyebrow">SUPPLIED LATER-WORLD / T1</p><h2>What still applies now?</h2>
            <p className="ex-support">Edit the supplied example observations, then ask the server to reevaluate. These are not authenticated external records or monitoring data.</p>
            <form onSubmit={event => { event.preventDefault(); controller.reevaluate(); }}>
              <fieldset disabled={busy}>
                {state.draft.observations.map((observation, index) => {
                  const spec = p.metric_schema.find(s => s.metric_key === observation.metric_key);
                  return <div className="ex-observation" key={observation.metric_key}>
                    <label htmlFor={`ex-value-${index}`}>{humanize(observation.metric_key)}<small>{spec.unit}{observation.window_days ? ` · ${observation.window_days}-day window` : " · point observation"}{spec.unit === "ratio" ? " · 1 = 100%" : ""}</small></label>
                    <input id={`ex-value-${index}`} type="number" step="any" min={spec.minimum ?? undefined} max={spec.maximum ?? undefined} required value={observation.value}
                      onChange={event => controller.edit(index, "value", event.target.value)} />
                  </div>;
                })}
                <details className="ex-timing"><summary>Observation timing · {dateLabel(state.draft.world_time)}</summary>
                  <label>Evaluation time (ISO-8601 with timezone)<input required value={state.draft.world_time} onChange={e => controller.edit(null, "world_time", e.target.value)} /></label>
                  {state.draft.observations.map((o, i) => <div key={o.metric_key}>
                    <label>{humanize(o.metric_key)} · observed at<input required value={o.observed_at} onChange={e => controller.edit(i, "observed_at", e.target.value)} /></label>
                    <label>{humanize(o.metric_key)} · window days<input type="number" min={p.metric_schema[i].minimum_window_days || 1} value={o.window_days ?? ""} onChange={e => controller.edit(i, "window_days", e.target.value)} /></label>
                  </div>)}
                </details>
                {state.stale && <p role="status" className="ex-stale">Inputs changed or reevaluation pending. The previous result is stale and is not shown as current.</p>}
                <button className="ex-primary" type="submit">{state.status === "reevaluation-submitting" ? "Reevaluating on the server…" : "Reevaluate supplied observations"}</button>
              </fieldset>
            </form>
            {state.result && <section ref={resultRef} className={`ex-result ${state.result.safe_reuse_result}`} aria-label="Latest server reevaluation" aria-live="polite">
              <p className="ex-eyebrow">LATEST SERVER REEVALUATION</p><h2>{RESULT_LABELS[state.result.safe_reuse_result]}</h2>
              <p className="ex-time">Effective world time · {dateLabel(state.result.world_time)}</p>
              <ul className="ex-matches">{Object.entries(state.result.current_matches).map(([id, value]) => <li key={id}><span>{p.current_match_labels?.[id] || id}</span><b>{humanize(value)}</b></li>)}</ul>
              <p className="ex-reason">{state.result.reason_codes.map(code => humanize(code.toLowerCase())).join(" · ")}</p>
              {state.result.limiting_requirements.length > 0 && <p>Limiting requirement: <strong>{state.result.limiting_requirements.join(", ")}</strong></p>}
              <details><summary>Submitted observations & deterministic proof</summary>
                <ul>{state.result.admitted_observations.map(o => <li key={o.metric_key}>{humanize(o.metric_key)}: <b>{o.value}</b> {o.unit} · {dateLabel(o.observed_at)}</li>)}</ul>
                <p>Evaluation fingerprint<code>{state.result.evaluation_hash}</code></p><p>Replay fingerprint<code>{state.result.replay_hash}</code></p>
              </details>
            </section>}
          </>}
        </section>
      </div>
      <footer className="ex-footer">History remains established. Applicability is reevaluated. Reuse still requires authorized support.</footer>
    </>}
  </main>;
}
