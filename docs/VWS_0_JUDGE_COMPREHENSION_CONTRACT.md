# VWS-0 — Judge Comprehension Contract

Status: ACTIVE PLANNING CONTRACT

PC2 is frozen. This document defines the smallest judge-facing vertical for the next checkpoint without changing M1/M2/M2.1/PC1/PC2 semantics.

## 0. Hackathon strategy constraints

### Submission category
Target category: **Collaborative Partner**.

Reasoning against the current official rules:
- Taskmaster explicitly rewards completing a multi-step workflow without human intervention; Decision Recall deliberately asks one human question when the missing historical dependency cannot legitimately be inferred.
- Collaborative Partner explicitly rewards clarifying questions, feedback capture/adaptation, and active synthesis or mutation of data. Decision Recall asks exactly one bounded clarification, converts the authorized answer into durable canonical state, and later reevaluates that state against a changed world.
- Fortified Enterprise Fleet expects a scalable institutional multi-agent network and cross-department lifecycle/security/observability capabilities. Adding those solely to fit the track would dilute the product thesis and consume time without strengthening the core mechanism.

Freeze rule: use Collaborative Partner unless the official rules materially change or a concrete implementation fact falsifies this fit. Do not redesign the product merely to imitate another track.

### Mandatory Google Cloud P0
Before recording/submission, Decision Recall must use at least one explicit Google Cloud infrastructure service in addition to Gemini/Vertex access. The minimum target is **Cloud Run** hosting the judge-facing backend.

Required before final video:
- hosted backend on Cloud Run;
- functioning hosted/testable project path if feasible;
- architecture diagram showing frontend → Cloud Run → Decision Recall engine → Gemini/Vertex and persistence components actually used;
- visual Google Cloud deployment proof in the video (for example Cloud Run dashboard or `.run` URL);
- README spin-up/deploy instructions.

Cloud Run is a submission P0, not visual polish. It does not need to precede VWS-0.5 static comprehension testing.

### Proof-of-Action constraint
The final video must show a **real, live, unedited execution** of the agent performing the task. Therefore the final recorded path may not be a stitched animation of precomputed states.

The stable target is:

`t0 input → evidence extraction/ingestion → gap selection → structured human YES → authorized commit → live time/world update → evaluation → safe-reuse pause → proof/replay`

The deterministic Decision Recall transitions must execute live during the recording. A previously captured/replayed Gemini result must never be presented as a fresh live model call.

For maximum credibility, the preferred final take should include a real Gemini extraction request in the same continuous run, with bounded infrastructure retry. Because only one/few live calls are needed rather than a 9-call release probe, this is operationally much safer. If a fallback/replay mode exists for product resilience, it must be explicitly labeled and must not be the sole Proof-of-Action evidence.

## 1. Judge comprehension target

### By 10 seconds
The judge must understand one sentence without narration:

> **Decision Recall detects a missing decision dependency and captures it before it is lost.**

Visible evidence:
- the original decision and two t0 facts are on screen;
- one historical dependency is presented as a **question not yet established**, never as a true proposition with a storage-status label;
- Decision Recall asks exactly one prospective question about that dependency.

### By 30 seconds
The judge must understand the product difference:

> The world can change without rewriting the historical record, and Decision Recall knows when it lacks authority to continue.

Visible evidence:
- R1 changes current-match state after new world evidence;
- R2 remains historically established;
- the system stops at the exact still-missing composition relation instead of inferring it.

### By 3 minutes
The judge must have seen the complete golden loop, one optional proof drawer, and one compact contrast against ordinary retrieval/memory. The main story must remain understandable even if the proof drawer is never opened.

## 2. Single WOW moment

The one hero moment is an operational epistemic stop:

# I CAN’T ESTABLISH THAT

Supporting copy:

**Safe reuse paused.**

**One historical reason survived.**

**What we never established: was that reason enough by itself?**

Optional small line:

`Decision Recall won’t infer what the historical record never established.`

Developer/debug identifier appears only in the proof drawer:

`C1 / sufficient_alone(R2) / NOT DURABLY RECORDED`

Reason: `C1` is implementation language. The main surface must show human meaning and operational consequence first; exact canonical identity remains available underneath.

Do not use `REUSE BLOCKED` if it visually implies a permanent policy denial. `Safe reuse paused` better matches the actual `insufficient_evidence` result: reuse cannot currently be justified under the target because a required relation is absent.

## 3. VWS-0.5 — Static Comprehension Prototype

Before implementing the presentation adapter/frontend, build and test a cheap static five-frame prototype. This prototype validates wording, hierarchy, and state comprehension only; it is not Proof of Action and must never be presented as the live hackathon demo.

### Frame 1 — ORIGINAL DECISION
Primary card:
- `Decision D-104`
- `Keep Apex and Beacon active for six months`

Observable evidence:
- `Apex delivery performance is materially unstable`
- `Beacon takes ~10 weeks to reactivate`

Known historical role:
- `Apex instability materially influenced the decision` → **ESTABLISHED**

Do not show an affirmative Beacon historical-role statement here.

### Frame 2 — MISSING DEPENDENCY / ONE QUESTION
Headline:

**Decision Recall found one dependency the decision record does not establish.**

Question:

> **Did preserving Beacon’s reaction capacity materially influence this decision?**

State:

**NOT ESTABLISHED YET**

Interaction:
- primary action: `Yes`
- secondary structured answers may remain visually subordinate.

This state means neither `YES` nor `NO`. The UI must not imply the answer before the human declares it.

### Frame 3 — CAPTURED
After structured `Yes`:

`Preserving Beacon’s reaction capacity materially influenced this decision`

→ **HISTORICALLY ESTABLISHED**

Small provenance line:

`Human declaration · captured at decision time`

Required conceptual boundary:
- Gemini: evidence extraction/candidate discovery;
- Human: declaration of what only the human knows;
- Decision Recall: authorization, canonical historical state, temporal evaluation and boundary.

Gemini should not dominate the first 30 seconds. A small `Gemini extraction` badge is acceptable; detailed model provenance belongs in the proof drawer.

### Frame 4 — SIX WEEKS LATER / THEN vs NOW
New world evidence:
- `Apex on-time delivery: 98.7% / 30 days`

Persistent visual axis:

`WHAT MATTERED THEN` ↔ `WHAT STILL MATCHES NOW`

Rows:
- `Apex instability mattered` → THEN: **ESTABLISHED** | NOW: **NO LONGER MATCHES**
- `Beacon reaction capacity mattered` → THEN: **ESTABLISHED** | NOW/history: **HISTORICAL RECORD PRESERVED**

Do not use `historical truth` as the primary technical label. The architecture proves authorized/established historical record, not metaphysical truth.

The historical-role panel must not disappear or be rewritten when current applicability changes.

### Frame 5 — EPISTEMIC STOP
Prompt:

> **Can the surviving historical reason alone justify reusing this decision now?**

Hero:

# I CAN’T ESTABLISH THAT

Operational state:

**Safe reuse paused**

Explanation:

`One historical reason survived.`

`What we never established: was that reason enough by itself?`

Do not show a keep/drop recommendation. Do not convert missing authority into `No`.

Proof/debug only:

`C1 · sufficient_alone(R2) · NOT DURABLY RECORDED`

## 4. Cold-viewer gate for VWS-0.5

Show only the five prototype frames for roughly 20–30 seconds to 3–5 people who have not been briefed on Decision Recall. Do not explain the product first.

Ask exactly these four questions:
1. `What does this product do?`
2. `What changed six weeks later, and what remained recorded about the original decision?`
3. `Why did the system stop at the end?`
4. `Who established that Beacon mattered — Gemini, Decision Recall, or the person?`

Pass conditions:
- viewer describes detecting/capturing why a decision was made before that knowledge is lost;
- viewer distinguishes present-world change from preserved historical record;
- viewer understands the stop as an exact missing-authority/evidence boundary, not generic model confusion;
- viewer answers that the **person** declared Beacon’s historical role and the system recorded/authorized it;
- viewer does not primarily describe the product as `supplier analytics`, `document search`, or `Gemini reading documents`.

If these fail, iterate only wording/layout/hierarchy in VWS-0.5 before investing in the adapter.

## 5. Why? proof drawer contract

Closed by default. It exists to satisfy technical judges without contaminating the main story.

Sections:
1. **What Gemini supplied** — bounded semantic candidates and exact evidence quote references.
2. **What the human supplied** — structured YES declaration bound to the issued question/session.
3. **What policy authorized** — evidence → authority → canonical historical state.
4. **What changed** — Apex world metric/current-match state.
5. **What did not change** — committed R2 historical role.
6. **Why the system paused safe reuse** — C1 absent / not durably recorded.
7. **Replay** — stored evaluation hash equals strict replay result hash; no future evidence is admitted into the earlier cutoff.

Only this drawer may expose:
- evidence IDs / authorization IDs;
- canonical entity IDs;
- profile hash;
- commit batch sequence;
- evaluation/replay hashes;
- Gemini candidate vs authorized-state distinction in detail.

## 6. Live vs deterministic product/demo contract

### Real live path
The final judge-facing product must have a real execution path. The deterministic state machine and authority ledger run live. The preferred recorded take also performs a real Gemini extraction in the same continuous run.

Live execution may use retry/backoff for true transient infrastructure failure, but must never retry a semantic answer merely to obtain a better result.

### Reproducible/replay path
A deterministic replay/canonical-state path may exist for resilience, debugging and explanation. It is useful because PC2 separately proves credentialed Gemini integration and the core value is in authorization/temporal state, but replay must be visibly labeled as replay/pre-authorized evidence whenever it is shown.

The replay path does not replace the contest’s live Proof-of-Action requirement.

## 7. Existing backend data that already supports the slice

No semantic redesign is needed.

`prepare_golden_capture()` already provides:
- t0 observable source documents;
- compiler candidates;
- assigned capture profile + hash;
- exact selected critical gap/question;
- issued capture session;
- t0 authorized known facts and historical relations.

`run_golden_decision()` / `GoldenLoopResult` already provides:
- `critical_gaps[].question`;
- R2 candidate view;
- R2 historical trace / knowledge state;
- commit identity + profile binding;
- evaluation `safe_reuse_result`;
- exact `limiting_requirements`;
- current-match states;
- review states;
- epistemic boundary entity/composition;
- evaluation result hash;
- strict replay result hash.

The frozen product model already separates candidate data from epistemic status. The presentation layer must preserve that distinction.

## 8. Minimal missing presentation adapter — VWS-1

Only after VWS-0.5 passes comprehension testing, add a judge-facing read model, not new decision semantics.

Recommended shape: one pure adapter that converts frozen product outputs into a presentation DTO such as:
- `decision`
- `t0_evidence[]`
- `historical_roles[]`
- `capture_question`
- `capture_answer_state`
- `world_change`
- `current_match_rows[]`
- `hero_boundary`
- `proof`

Rules:
- adapter is read-only;
- no LLM call inside the adapter;
- no recomputation of authority in frontend code;
- no hard-coded epistemic result that disagrees with `GoldenLoopResult`;
- human-readable labels may map canonical IDs to display text, but may not invent new state.

## 9. Claims discipline

The visible slice demonstrates the golden scenario. It must not silently upgrade broader experimental claims in `docs/CLAIM_LEDGER.md`.

Allowed judge-facing claim:

> In this supplier-resilience decision, Decision Recall detects a missing historical dependency, captures the human declaration prospectively, distinguishes established historical record from current-world applicability, and pauses safe reuse when the remaining sufficiency relation was never established.

Do not yet claim from this demo alone:
- superiority to strong baselines;
- reliable reconstruction across arbitrary agents/domains;
- general recovery superiority;
- enterprise-scale generalization.

Those remain separate evidence obligations.

## 10. Non-goals before the winner slice works

Do not build yet:
- generic dashboard/navigation system;
- user/accounts/auth flows;
- CRUD decision management;
- broad multi-domain ontology editor;
- benchmark UI;
- Fleet orchestration;
- charts that do not help the golden loop;
- multiple alternative demo stories.

Exception: Cloud Run deployment is not a non-goal; it is a mandatory submission P0 scheduled after the comprehension vertical is stable and before final recording.

## 11. Implementation order

### VWS-0.5
1. Five-frame static comprehension prototype.
2. THEN ↔ NOW visual grammar.
3. Correct pending-R2 question state.
4. Operational hero (`Safe reuse paused`).
5. Cold-viewer test with four questions.
6. Freeze wording/layout hierarchy after pass.

### VWS-1
7. Presentation DTO/adapter over frozen product outputs.
8. One single-page real winner slice.
9. Structured YES state transition.
10. Live world-change/current-vs-historical transition.
11. Hero epistemic stop.
12. Proof drawer.
13. Deterministic presentation/UI tests binding visible state to backend fields.

### Submission P0 after vertical stability
14. Cloud Run deployment of the real backend.
15. Hosted path + reproducible spin-up instructions.
16. Architecture diagram.
17. Continuous, unedited live Proof-of-Action rehearsal with Google Cloud deployment proof.
18. Compact baseline contrast only when its claim scope is supported.

## 12. Exit gates

### VWS-0.5 exits only when
- cold viewers pass the four-question comprehension gate;
- no frame implies R2 is true before the human YES;
- `Safe reuse paused` is understood as deliberate guarded action, not generic refusal;
- Gemini is not mistaken for the authority that established R2.

### VWS-1 exits only when
- visible states are derived from frozen backend outputs, not frontend-scripted epistemic truth;
- main flow has no false `UNKNOWN → NO`, invented historical role, or unsupported sufficiency;
- exact missing relation is visible in human language and traceable to canonical C1 in the proof drawer;
- replay/no-hindsight proof is available without dominating the main screen;
- the complete golden loop can be demonstrated comfortably under 3 minutes, leaving time within the 4-minute contest video for problem/value/architecture and Google Cloud proof.

### Submission readiness exits only when
- mandatory Gemini + Google agent framework + Google Cloud infrastructure requirements are all evidenced;
- backend is visibly running on Google Cloud in the video;
- the final video contains an unedited live Proof of Action;
- repository contains architecture diagram and reproducible spin-up instructions.

## Freeze / reopen rule

This VWS contract may change to improve judge comprehension, wording, layout, presentation adapters, or contest compliance. It must not reopen frozen PC2 semantics. Any requested semantic change must first identify a concrete contradiction or blocker under the existing freeze rule.
