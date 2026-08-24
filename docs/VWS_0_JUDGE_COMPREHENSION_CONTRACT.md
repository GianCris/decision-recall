# VWS-0 — Judge Comprehension Contract

Status: ACTIVE PLANNING CONTRACT

PC2 is frozen. This document defines the smallest judge-facing vertical for the next checkpoint without changing M1/M2/M2.1/PC1/PC2 semantics.

## 0. Hackathon strategy constraints

### Submission category
Target category: **Collaborative Partner**.

Why this is the best current fit:
- Taskmaster explicitly rewards completing workflows without human intervention; Decision Recall deliberately asks one bounded human question when a missing historical dependency cannot legitimately be inferred.
- Collaborative Partner explicitly rewards clarifying questions, feedback capture/adaptation, and active synthesis or mutation of data. Decision Recall asks once, turns the structured answer into durable canonical state, and later reevaluates against a changed world.
- Fortified Enterprise Fleet expects an institutional multi-agent network. Adding Fleet scope only to fit the category would dilute the core mechanism.

Freeze rule: use Collaborative Partner unless official rules materially change or a concrete implementation fact falsifies this fit.

### Mandatory Google Cloud P0
Before final recording/submission, Decision Recall must use an explicit Google Cloud infrastructure service in addition to Gemini/Vertex access. Minimum target: **Cloud Run** hosting the judge-facing backend.

Required before submission:
- hosted backend on Cloud Run;
- architecture diagram showing only services actually used;
- visual Google Cloud deployment proof in the video;
- reproducible spin-up/deploy instructions.

Cloud Run is a submission P0, not visual polish, but it does not precede VWS-0.5 comprehension testing.

### Proof-of-Action constraint
The submitted video must show a real continuous/unedited execution of the agent performing the task. A static prototype or precomputed animation cannot be the Proof of Action.

Preferred final path:

`t0 input → evidence extraction/ingestion → gap selection → structured human YES → authorized commit → live world update → evaluation → insufficient-evidence safe-reuse result → proof/replay`

A replay/pre-authorized path may exist for resilience, but it must be clearly labeled and must never be presented as a fresh live Gemini call.

## 1. Judge comprehension targets

### By 10 seconds
The judge should understand:

> **Decision Recall detects a missing decision dependency and captures it before it is lost.**

### By 30 seconds
The judge should understand:

> The historical record and current-world applicability are separate: the world can change without rewriting what was established about the original decision.

### By the hero moment
The judge should understand that the system stops at an exact missing relation instead of inventing certainty.

## 2. Single WOW moment

Hero:

# I CAN’T ESTABLISH THAT

Status directly grounded in the engine result:

**SAFE REUSE · INSUFFICIENT EVIDENCE**

Supporting copy:

**One current reason still matches.**

**What we never established: was that reason enough by itself?**

Small line:

`Decision Recall won’t infer what the historical record never established.`

Proof/debug only:

`C1 / sufficient_alone(R2) / NOT DURABLY RECORDED`

Do not use `REUSE BLOCKED`, `REUSE DENIED`, or `REUSE CANNOT BE AUTHORIZED` unless the engine later models an explicit policy action with that meaning. The current engine result is an evaluation result: `insufficient_evidence`.

## 3. VWS-0.5 — five-frame static prototype

The static prototype validates wording and comprehension only. It is not Proof of Action.

### Frame 1 — ORIGINAL DECISION
Show:
- `Decision D-104`
- `Keep Apex and Beacon active for six months`
- observed Apex instability;
- Beacon ~10-week reactivation delay;
- Apex instability historical role already **ESTABLISHED**.

Do not show an affirmative Beacon historical-role proposition yet.

### Frame 2 — MISSING DEPENDENCY
Headline:

**Decision Recall found one dependency the decision record does not establish.**

Question:

> **Did preserving Beacon’s reaction capacity materially influence this decision?**

State:

**NOT ESTABLISHED YET**

This is neither YES nor NO.

### Frame 3 — CAPTURED
After structured YES:

`Preserving Beacon’s reaction capacity materially influenced this decision`

→ **HISTORICALLY ESTABLISHED**

Provenance:

`Human declaration · captured at decision time`

Conceptual boundary:
- Gemini → evidence extraction/candidate discovery;
- Human → declaration of what only the human knows;
- Decision Recall → authorization, canonical historical record, temporal evaluation and boundary.

The visible transition must make clear that the human answer changed durable system state; the product is not merely a clarifying-question assistant.

### Frame 4 — SIX WEEKS LATER / THEN vs NOW
New evidence:
- `Apex on-time delivery: 98.7% / 30 days`

Use separate dimensions:

`WHAT MATTERED THEN` vs `WHAT STILL MATCHES NOW`

Rows:
- Apex instability → THEN **ESTABLISHED** | NOW **NO LONGER MATCHES**
- Beacon reaction capacity → THEN **ESTABLISHED** | NOW **STILL MATCHES**

Then state separately:

`Historical record: both decision roles remain established. Current-world match is evaluated separately.`

Important: never put `HISTORICAL RECORD PRESERVED` inside the `WHAT STILL MATCHES NOW` cell. That mixes two distinct dimensions and weakens the thesis.

### Frame 5 — EPISTEMIC STOP
Prompt:

> **Can the surviving current reason alone justify reusing this decision now?**

Hero:

# I CAN’T ESTABLISH THAT

Status:

**SAFE REUSE · INSUFFICIENT EVIDENCE**

Explanation:

`One current reason still matches.`

`What we never established: was that reason enough by itself?`

Do not show keep/drop advice. Do not convert missing authority into NO.

## 4. Cold-viewer gate

Use **5 unbriefed viewers** if at all possible. Do not explain the product beforehand. Show the five frames for roughly 20–30 seconds, then record each answer verbatim before interpreting it.

Ask exactly:
1. `What does this product do?`
2. `What changed six weeks later, and what remained recorded about the original decision?`
3. `Why did the system stop at the end?`
4. `Who established that Beacon mattered — Gemini, Decision Recall, or the person?`

Score four concepts independently:
- A: it detects/asks about a dependency it should not invent;
- B: the human answer changes durable historical record;
- C: current-world applicability can change without rewriting historical record;
- D: the final stop is caused by one specific relation that was never established.

Pass gate:
- at least **4/5 viewers** demonstrate A, B, C and D in substance;
- at least **4/5** correctly attribute the Beacon historical role to the human declaration rather than Gemini;
- fewer than 2/5 primarily classify the product as supplier analytics, document search, or a Gemini document reader.

With only 3 viewers, treat the result as directional, not a formal pass. The prior `3–5 viewers / ≥80%` wording is too ambiguous because 80% has unstable meaning at n=3 or n=4.

If C or D fails, do not begin VWS-1. Those are the hardest and most differentiating concepts.

## 5. Proof drawer contract

Closed by default. It should expose rigor without contaminating the main story:
1. Gemini bounded candidates + exact evidence spans;
2. structured human declaration bound to issued session/question;
3. evidence → policy authorization → canonical state;
4. changed world metric/current-match state;
5. preserved historical role;
6. exact missing C1 boundary;
7. strict replay hash equality / no-hindsight proof.

Only here should we expose canonical IDs, hashes, authorization IDs, commit sequence, and detailed Gemini provenance.

## 6. Live vs deterministic product contract

The final product path must execute the deterministic state machine and authority ledger live. The preferred submitted take should also perform a real Gemini extraction in the same continuous run when operationally stable.

Retry/backoff is allowed only for true transient infrastructure errors. A semantic model answer must never be retried merely to seek a better answer.

Replay/pre-authorized evidence can be shown only when explicitly labeled as replay/pre-authorized state and cannot replace the contest Proof of Action.

## 7. Existing backend support

`prepare_golden_capture()` already provides t0 observable evidence, compiler candidates, profile binding, selected gap/question, issued session, and t0 authorized state.

`run_golden_decision()` / `GoldenLoopResult` already provides the critical gap, R2 trace, commit, safe-reuse evaluation, limiting requirements, current matches, review states, epistemic boundary, evaluation hash and strict replay hash.

Therefore VWS-1 should add a read-only presentation adapter, not new decision semantics.

## 8. VWS-1 adapter rules

Only after the cold-viewer gate passes:
- create a pure presentation DTO/adapter over frozen product outputs;
- no LLM call in the adapter;
- no authority recomputation in frontend code;
- no hard-coded epistemic outcome that can disagree with `GoldenLoopResult`;
- human-readable labels may map canonical IDs to copy but may not invent state.

Then build one real single-page winner slice, structured YES transition, live world-change transition, hero stop, proof drawer and deterministic UI↔backend binding tests.

## 9. Claims discipline

The golden demo does not prove broad superiority/generalization claims in `docs/CLAIM_LEDGER.md`.

Allowed claim:

> In this supplier-resilience decision, Decision Recall detects a missing historical dependency, captures the human declaration prospectively, separates established historical record from current-world applicability, and returns insufficient evidence when the remaining sufficiency relation was never established.

Do not yet claim general superiority over strong baselines, arbitrary cross-agent reconstruction, general recovery superiority, or enterprise-scale generalization.

## 10. Non-goals before VWS-1 works

Do not build a generic dashboard, auth/account flows, CRUD suite, ontology editor, Fleet orchestration, benchmark UI, multi-domain expansion, or decorative analytics.

Cloud Run is the exception: mandatory submission P0 after the comprehension vertical is stable and before final recording.

## 11. Exit gates

### VWS-0.5 exits only when
- 5-viewer test meets the quantitative gate above;
- nobody is shown R2 as true before structured YES;
- viewer understands historical record vs current match;
- the hero reads as a deliberate exact boundary, not generic model confusion;
- Gemini is not mistaken for the authority establishing R2.

### VWS-1 exits only when
- visible states are derived from backend outputs;
- no false UNKNOWN→NO, invented historical role, or unsupported sufficiency exists;
- C1 is human-readable in the main story and canonical in proof detail;
- replay/no-hindsight proof is available but not dominant;
- complete winner loop fits comfortably under 3 minutes.

### Submission readiness exits only when
- Gemini + Google agent framework + explicit Google Cloud infrastructure requirements are evidenced;
- Cloud Run/backend proof is visible in the video;
- final video contains continuous, unedited Proof of Action;
- architecture diagram and reproducible setup instructions are in the repo.

## Freeze / reopen rule

VWS wording/layout may iterate after cold-viewer evidence. Frozen PC2 semantics do not reopen unless a concrete reproduction falsifies a judge-facing claim, breaks the golden loop, materially lowers credibility, or blocks the final demo.
