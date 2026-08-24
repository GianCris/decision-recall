# VWS-0 — Judge Comprehension Contract

Status: ACTIVE PLANNING CONTRACT

PC2 is frozen. This document defines the smallest judge-facing vertical for the next checkpoint without changing M1/M2/M2.1/PC1/PC2 semantics.

## 1. Judge comprehension target

### By 10 seconds
The judge must understand one sentence without narration:

> Decision Recall preserves a missing decision dependency before it is lost.

Visible evidence:
- the original decision and two t0 facts are on screen;
- one relation is visibly marked **NOT YET RECORDED**;
- Decision Recall asks exactly one prospective question about that relation.

### By 30 seconds
The judge must understand the product difference:

> The world can change without rewriting what historically mattered, and Decision Recall knows when it lacks authority to continue.

Visible evidence:
- R1 changes current-match state after new world evidence;
- R2 remains historically established;
- the system stops at the exact still-missing composition relation instead of inferring it.

### By 3 minutes
The judge must have seen the complete golden loop, one optional proof drawer, and one compact contrast against ordinary retrieval/memory. The main story must remain understandable even if the proof drawer is never opened.

## 2. Single WOW moment

The one hero moment is the epistemic stop:

**I CAN’T ESTABLISH THAT**

Supporting line:

**Missing: whether the surviving historical reason was sufficient on its own.**

Developer/debug identifier may appear only in the proof drawer:

`C1 / sufficient_alone(R2)`

Reason: `C1` is implementation language. The main surface should show human meaning first; exact canonical identity remains available underneath.

## 3. Storyboard / state contract

### Scene A — T0 / original decision (0–12 s)
Primary card:
- `Decision D-104`
- `Keep Apex and Beacon active for six months`

Evidence chips:
- `Apex delivery performance is materially unstable`
- `Beacon takes ~10 weeks to reactivate`

Historical-role strip:
- `Apex instability materially influenced the decision` → **RECORDED**
- `Preserving Beacon reaction capacity influenced the decision` → **NOT YET RECORDED**

Do not show raw hashes, candidate IDs, ledger sequence numbers, policy versions, or ontology labels here.

### Scene B — prospective capture (12–28 s)
Decision Recall surfaces exactly one question:

> **Did preserving Beacon’s reaction capacity materially influence this decision?**

Interaction:
- primary action: `Yes`
- secondary options can exist but remain visually subordinate.

After `Yes`:
- the missing historical-role strip transitions to **HISTORICALLY ESTABLISHED**;
- a small, non-hero provenance tag may read `Human-declared at decision time`;
- do not imply Gemini established this relation.

Required conceptual boundary in UI copy:
- Gemini may be labeled `evidence extraction`;
- the human answer may be labeled `human declaration`;
- Decision Recall may be labeled `authorized history`.

### Scene C — time/world change (28–45 s)
Transition label:

**6 weeks later**

New world evidence:
- `Apex on-time delivery: 98.7% / 30 days`

The historical-role panel must not disappear or be rewritten.

Show two distinct state rows:
- `R1 · Apex instability mattered` → **NO LONGER MATCHES CURRENT WORLD**
- `R2 · Preserving Beacon reaction capacity mattered` → **HISTORICALLY ESTABLISHED**

The visual grammar must make `current match` and `historical truth` look like different dimensions, not two values of the same status field.

### Scene D — hero stop (45–62 s)
Prompt above result:

> **Can the surviving historical reason alone justify reusing this decision now?**

Hero result:

# I CAN’T ESTABLISH THAT

Below hero result:

`The surviving historical reason is recorded.`

`What was never established: whether it was sufficient on its own.`

Primary missing-relation label:

**Missing: sufficiency of R2 by itself**

Proof/debug label only:

`C1 · sufficient_alone(R2) · NOT DURABLY RECORDED`

Do not show a keep/drop recommendation. Do not convert missing authority into `No`.

### Scene E — Why? proof drawer (optional, 62–95 s)
Closed by default. It exists to satisfy technical judges without contaminating the main story.

Sections:
1. **What Gemini supplied** — bounded semantic candidates and exact evidence quote references.
2. **What the human supplied** — structured YES declaration bound to the issued question/session.
3. **What policy authorized** — evidence → authority → canonical historical state.
4. **What changed** — Apex world metric/current-match state.
5. **What did not change** — committed R2 historical role.
6. **Why the system stopped** — C1 absent / not durably recorded.
7. **Replay** — stored evaluation hash equals strict replay result hash; no future evidence is admitted into the earlier cutoff.

Only this drawer may expose:
- evidence IDs / authorization IDs;
- canonical entity IDs;
- profile hash;
- commit batch sequence;
- evaluation/replay hashes;
- Gemini candidate vs authorized state distinction in detail.

## 4. Live vs deterministic demo contract

### Live Gemini path
Must remain available as a demonstrable integration path, but it is not allowed to gate the hero moment during the recorded demo.

Use live Gemini for:
- an explicit `Live extraction` action or pre-hero evidence-discovery beat;
- showing real candidate extraction when network/capacity cooperates.

If live extraction is slow or receives transient Vertex capacity errors, the product must not fabricate a successful live response.

### Reproducible hero path
The winner slice may render from the deterministic golden-loop output / previously authorized canonical state for the core T0 → capture → T1 → stop sequence.

This is legitimate because the hero claim is about Decision Recall’s authority/state transition, not about model latency. The credentialed PC2 evidence separately proves real Gemini integration.

The UI must not misleadingly label replayed/precomputed evidence as a fresh live Gemini call.

## 5. Existing backend data that already supports the slice

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

## 6. Minimal missing presentation adapter

The next implementation should add a judge-facing read model, not new decision semantics.

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

## 7. Claims discipline

The visible slice demonstrates the golden scenario. It must not silently upgrade broader experimental claims.

Allowed judge-facing claim:

> In this supplier-resilience decision, Decision Recall preserves a prospectively captured historical dependency, distinguishes it from current-world applicability, and stops when the remaining sufficiency relation was never established.

Do not yet claim from this demo alone:
- superiority to strong baselines;
- reliable reconstruction across arbitrary agents/domains;
- general recovery superiority;
- enterprise-scale generalization.

Those remain separate evidence obligations.

## 8. UI non-goals for VWS-1

Do not build yet:
- generic dashboard/navigation system;
- user/accounts/auth flows;
- CRUD decision management;
- broad multi-domain ontology editor;
- benchmark UI;
- full Cloud Run production architecture;
- Fleet orchestration;
- charts that do not help the golden loop;
- multiple alternative demo stories.

## 9. VWS-1 implementation order

1. Presentation DTO/adapter over the frozen golden path.
2. One single-page winner slice using that DTO.
3. Exact state-transition interaction for the structured YES.
4. Time-jump/current-vs-historical visual transition.
5. Hero epistemic stop.
6. Proof drawer.
7. Deterministic UI tests that bind displayed hero state to backend result fields.
8. Only after comprehension is proven: compact baseline contrast.

## 10. Exit gate

VWS-1 is not complete because it looks polished. It is complete only if all of these are true:

- A cold viewer can state within ~10 s that Decision Recall captures a missing decision dependency before it is lost.
- Within ~30 s the viewer can distinguish historical truth from current applicability.
- The viewer identifies **I CAN’T ESTABLISH THAT** as the product’s critical behavior, not as a generic model refusal.
- The exact missing relation is visible in human language and traceable to canonical C1 in the proof drawer.
- The main flow has no false `UNKNOWN → NO`, no invented historical role, and no unsupported sufficiency.
- The visible state is derived from frozen backend outputs, not from frontend-scripted epistemic truth.
- Replay/no-hindsight proof is available without dominating the main screen.
- The complete golden loop can be demonstrated comfortably under 3 minutes.

## Freeze / reopen rule

This VWS contract may change to improve judge comprehension, wording, layout, or presentation adapters. It must not reopen frozen PC2 semantics. Any requested semantic change must first identify a concrete contradiction or blocker under the existing freeze rule.
