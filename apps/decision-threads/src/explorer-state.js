// Transport/presentation state only. Authority and evaluation belong to the server.
export const humanize = (value) => String(value).replaceAll("_", " ");
export const RESULT_LABELS = Object.freeze({
  reuse_authorized: "REUSE AUTHORIZED",
  reuse_not_authorized: "REUSE NOT AUTHORIZED",
  insufficient_evidence: "INSUFFICIENT EVIDENCE",
});
export function sourceMode(mode) {
  return mode === "configured_mechanically_grounded_example_candidates"
    ? "Configured grounded example evidence" : `Evidence mode: ${humanize(mode)}`;
}
export function capturePayload(preparation) {
  return Object.fromEntries(["decision_id", "capture_session_id", "profile_hash", "gap_id", "question_hash"]
    .map(key => [key, preparation[key]]).concat([["answer", "yes"]]));
}
export function initialDraft(preparation) {
  const example = preparation.example_observations;
  return {
    world_time: example?.world_time || "",
    observations: preparation.metric_schema.map(spec => {
      const supplied = example?.observations.find(o => o.metric_key === spec.metric_key);
      return { metric_key: spec.metric_key, value: supplied ? String(supplied.value) : "",
        unit: spec.unit, window_days: supplied?.window_days ?? spec.minimum_window_days,
        observed_at: supplied?.observed_at || "" };
    }),
  };
}
export function reevaluationPayload(preparation, draft) {
  if (!draft.world_time) throw new Error("Enter an evaluation time with a timezone.");
  return { capture: capturePayload(preparation), world_time: draft.world_time,
    observations: draft.observations.map(o => {
      if (!String(o.value).trim() || !Number.isFinite(Number(o.value))) throw new Error("Enter a finite numeric value for every observation.");
      return { metric_key: o.metric_key, value: Number(o.value), unit: o.unit,
        window_days: o.window_days === "" || o.window_days === null ? null : Number(o.window_days), observed_at: o.observed_at };
    }) };
}

export function createExplorerController(fetcher = (...args) => fetch(...args)) {
  let state = { cases: [], selected: null, preparation: null, capture: null, draft: null,
    result: null, submitted: null, stale: false, status: "idle", error: null };
  let generation = 0;
  let abort;
  const listeners = new Set();
  const update = patch => { state = { ...state, ...patch }; listeners.forEach(fn => fn()); };
  const cancel = () => { generation += 1; abort?.abort(); };
  const path = operation => `/api/cases/${encodeURIComponent(state.selected)}/${operation}`;
  async function run(status, url, options, accept) {
    cancel();
    const ticket = generation;
    const requestAbort = new AbortController();
    abort = requestAbort;
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; requestAbort.abort(); }, 20000);
    update({ status, error: null });
    try {
      const response = await fetcher(url, { ...options, signal: requestAbort.signal });
      const data = await response.json();
      if (ticket !== generation) return;
      if (!response.ok) throw new Error(data.message || `Server request failed (${response.status}).`);
      update({ ...accept(data), status: "ready", error: null });
    } catch (error) {
      if (ticket === generation) update({ status: "error", error: timedOut ? "Request timed out. Retry when the server is available." : error.message });
    } finally { clearTimeout(timer); }
  }
  const post = payload => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  return {
    getSnapshot: () => state,
    subscribe: fn => { listeners.add(fn); return () => listeners.delete(fn); },
    dispose: cancel,
    loadCases() {
      update({ selected: null, preparation: null, capture: null, draft: null, result: null, submitted: null, stale: false });
      return run("cases-loading", "/api/cases", {}, data => {
        if (!Array.isArray(data.cases)) throw new Error("Server did not return registered cases.");
        return { cases: data.cases };
      });
    },
    select(decisionId) {
      update({ selected: decisionId, preparation: null, capture: null, draft: null, result: null, submitted: null, stale: false });
      return run("preparation-loading", path("capture-preparation"), {}, data => {
        if (data.decision_id !== decisionId || data.status !== "issued" || !data.question || !Array.isArray(data.metric_schema)) throw new Error("Preparation does not match the selected decision.");
        return { preparation: data, draft: initialDraft(data) };
      });
    },
    capture() {
      if (!state.preparation || state.capture || state.status === "capture-submitting") return;
      const binding = capturePayload(state.preparation);
      return run("capture-submitting", path("capture"), post(binding), data => {
        if (data.decision_id !== binding.decision_id || data.status !== "capture_verified" || !Array.isArray(data.historical_relations) ||
            Object.keys(binding).some(key => key !== "answer" && data.capture_binding?.[key] !== binding[key])) throw new Error("Server capture binding was not verified.");
        return { capture: data };
      });
    },
    edit(index, field, value) {
      if (!state.capture || !state.draft || !["value", "observed_at", "window_days", "world_time"].includes(field)) return;
      cancel();
      const draft = field === "world_time" ? { ...state.draft, world_time: value } : {
        ...state.draft, observations: state.draft.observations.map((o, i) => i === index ? { ...o, [field]: value } : o),
      };
      update({ draft, result: null, stale: state.stale || !!state.result || !!state.submitted, status: "ready", error: null });
    },
    reevaluate() {
      if (!state.capture || state.status === "reevaluation-submitting") return;
      let payload;
      update({ result: null, stale: !!state.submitted });
      try { payload = reevaluationPayload(state.preparation, state.draft); }
      catch (error) { update({ status: "error", error: error.message }); return; }
      const selected = state.selected;
      return run("reevaluation-submitting", path("reevaluate"), post(payload), data => {
        if (data.decision_id !== selected || data.status !== "reevaluated" || !Object.hasOwn(RESULT_LABELS, data.safe_reuse_result) ||
            !Array.isArray(data.admitted_observations) || !Array.isArray(data.reason_codes) || !Array.isArray(data.limiting_requirements) ||
            !data.current_matches || !data.evaluation_hash || !data.replay_hash) throw new Error("Server did not return a valid canonical evaluation.");
        return { result: data, submitted: payload, stale: false };
      });
    },
  };
}
