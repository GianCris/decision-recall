# Decision Recall Round B Protocol v0.1

Status: **FROZEN FOR DEV SCREENING ONLY**. This protocol authorizes documentation of the design and, in a later task, one-repetition DEV screening. It does not authorize implementation, provider calls, confirmation, challenge/CADC work, or sealed-holdout access.

## 1. Purpose and scientific question

> Can an implicit-only system reconstruct which prior knowledge changed and which decisions were informationally connected to that knowledge, and use that reconstructed structure to reduce false reopenings without creating missed recoveries?

Round B tests whether an explicit intermediate representation reconstructed only from candidate-visible information provides operational value beyond the frozen implicit baseline, an additional generic model pass/context reorganization, and the simple one-call probes falsified in Round A. It does not assume that a graph, memory system, fleet, multi-agent architecture, or persistent provenance system is necessary. Architecture must earn the right to exist empirically.

## 2. Prior evidence and claim boundary

Round A1 observed:

| Condition | DEV observation |
|---|---|
| M0 contemporary implicit | FP 1; FN 0; TP 16; TN 19; recall 1.0; precision approximately 0.941176; F1 approximately 0.969697; one `still_justified` error; one unique binary failure |
| M1 | no operational improvement over M0 |
| M2 | no operational improvement over M0; only dependency-strength differences that did not cross the frozen operational boundary |
| M3 | no operational improvement over M0 |
| R1 structured reference | FP 0; FN 0; TP 16; TN 20; F1 1.0; zero `still_justified` errors |

Round A did not demonstrate that architecture is required. It showed only that the precommitted one-call Reliance, Survivability, and Alternative-Support probes failed to recover the contemporary structured-provenance benefit on DEV. These are development observations, not generalization evidence.

## 3. Frozen implicit-view boundary

`IMPLICIT_CANDIDATE_VIEW_AUDIT_V0.1.md` is authoritative. Stable scenario-local, namespace-typed IDs exist for decisions, prior knowledge, the change, transmissions where present, agents, consequences, and recovery actions. Implicit decisions expose only candidate-visible fields. Exact decision-to-knowledge provenance and structured assumptions are not exposed. No mechanical evidence/knowledge-to-decision relation or change-to-prior-knowledge alignment is visible; both mappings require model inference. Numeric ordering does not establish causal use or reliance, and free-text semantics require inference. `dev-005` and `dev-012` have no transmission references.

## 4. Final conditions

| Condition | Calls and input | Frozen purpose |
|---|---|---|
| **RB0 — Fresh Implicit Control** | one final Discovery call; frozen implicit view and frozen Discovery task/output | contemporary implicit control; no specialized reconstruction, survivability, or alternative-support instruction |
| **RC0 — Generic Two-Pass Control** | Stage 1 receives the frozen projection and produces `GenericContextRecord`; Stage 2 receives original implicit input plus the canonical record | pass-count-matched generic organization/re-expression control |
| **RR1 — Fresh Structured-Provenance Reference** | one final Discovery call using structured candidate view | contemporary reference, not oracle, ceiling, target, or reconstruction input |
| **RB1 — Reconstruction Only** | Stage 2 receives original implicit input plus the shared canonical `DecisionSupportRecord` | incremental value of reconstructed change alignment and candidate knowledge/evidence-to-decision connections |
| **RB2 — Reconstruction + Survivability** | exactly RB1 plus the frozen Survivability intervention | incremental Survivability value with the same artifact |
| **RB3 — Reconstruction + Survivability + Alternative-Support Verification** | exactly RB2 plus the frozen Alternative-Support intervention | incremental alternative-support verification with the same artifact |

For each scenario and repetition, exactly one specialized Reconstruction Stage 1 is executed. Its validated, canonical, byte-identical artifact is shared by RB1, RB2, and RB3. It is not a seventh final condition and must not be regenerated separately. A new repetition produces a new artifact.

RC0 Stage 1 must not construct knowledge/evidence-to-decision mappings, infer change alignment beyond mechanically explicit structure, or emit materiality, necessity, sufficiency, survivability, alternative support, reopening, or oracle judgments. RC0 matches pass count and generic reorganization, not equally complex specialized semantic work.

## 5. Precommitted contrasts

| Contrast | Intended interpretation within this protocol |
|---|---|
| RB0 → RC0 | incremental contribution of an additional generic organization/pass-count-matched step |
| RC0 → RB1 | incremental operational contribution associated with specialized reconstruction beyond conservative generic organization |
| RB1 → RB2 | incremental contribution of Survivability given the same reconstruction |
| RB2 → RB3 | incremental contribution of Alternative-Support Verification given the same reconstruction and Survivability instruction |
| RB0 → RR1 | descriptive contemporary reference for receiving structured provenance |

RC0 does not match the specialized semantic work of reconstruction. RC0 → RB1 cannot prove that relationship structure alone exclusively caused a gain. RR1 is not an oracle or ceiling. Specialized reconstruction is not successful merely because RB1 improves over RB0 if RC0 improves by the same amount.

## 6. Exact Stage1VisibleProjection

RC0 Stage 1 and Reconstruction Stage 1 receive byte-for-byte identical deterministic serialization of:

```text
Stage1VisibleProjection {
  scenario_id,
  brief,
  agents,
  knowledge_before,
  change,
  transmissions,
  decisions,
  world,
  consequences,
  recovery_actions
}
```

Values are copied deterministically from the frozen implicit candidate view without inference, summarization, repair, ranking, reinterpretation, or enrichment. `scenario_id` is copied from candidate-view `id`. No other top-level field is allowed. Specifically excluded are `schema_version`, `split`, `phase`, `discovery_condition`, `title`, `domain`, and all four `complexity` fields.

## 7. GenericContextRecord

```text
GenericContextRecord {
  schema_version,
  scenario_id,
  agents[],
  knowledge_before[],
  change,
  transmissions[],
  decisions[],
  world,
  consequences[],
  recovery_actions[]
}
```

The record must be coverage-complete: every visible object and the visible world are preserved. It cannot select or omit objects as irrelevant, redundant, or low-salience. It contains only projection information and may preserve only mechanically explicit relations. It must not infer or add provenance, change alignment, reliance, materiality, strength labels, necessity, sufficiency, survivability, justification, reopening, alternative support/candidates, relevance/salience/confidence, evaluative summaries, private labels, or expected answers.

## 8. DecisionSupportRecord

```text
DecisionSupportRecord {
  schema_version,
  scenario_id,
  change_alignment: {
    change_ref,
    candidate_prior_knowledge_refs[]
  },
  decision_connections: [
    {
      decision_id,
      candidate_knowledge_refs[],
      basis_trace_refs[]
    }
  ]
}
```

`change_ref` must equal visible `change.id`. `candidate_prior_knowledge_refs` and `candidate_knowledge_refs` are unique unordered subsets of visible `knowledge_before[].id`. `basis_trace_refs` is a unique unordered subset of visible `transmissions[].id` and may be empty. `decision_connections` contains exactly one entry per visible decision, with no missing, duplicate, or invented decision, and is canonicalized by `decision_id`. Empty candidate/reference sets are valid model behavior and are not schema failures.

These are **candidate reconstructed connections**, not observed relationships. Their semantic truth cannot be mechanically validated from the implicit contract.

## 9. Stage-1 semantic boundary

DecisionSupportRecord does not answer Discovery. Stage 1 must not emit, directly or disguised: `materially_dependent`; dependency strength or independent/supporting/material/critical labels; necessary, sufficient, essential, decisive, survivability, survival, justification, reopening, or alternative-support judgments; rankings; confidence/probabilities; oracle or hard-negative labels; private paths; RR1 predictions; or expected Stage-2 answers. Unrestricted rationale, explanation, reasoning, and summary fields are forbidden.

## 10. Canonicalization and side-channel policy

Stage-1 collection ordering carries zero semantic ranking information unless order is objectively part of the visible world. Unordered references are unique and sorted deterministically; `decision_connections` is sorted by `decision_id`; equivalent unordered GenericContextRecord collections are canonicalized using stable visible IDs. Objectively represented source order is preserved. No ordering may encode rank, confidence, relevance, salience, top-k status, or weight; duplicates cannot encode weighting.

Persist separately:

1. `raw_stage1_response`, for audit only;
2. the validated canonical artifact consumed by Stage 2.

Stage 2 never receives raw Stage-1 output. Persist `artifact_sha256` over the exact canonical serialization. Within a scenario/repetition, RB1, RB2, and RB3 must record an identical artifact hash.

## 11. Reference validation

- **REFERENCE-VALID:** every ID exists in its correct candidate-visible namespace.
- **STRUCTURALLY-GROUNDED:** a claimed mechanical relation is directly supported by visible structure.
- **MODEL-INFERRED:** change-to-prior-knowledge and knowledge/evidence-to-decision connections; endpoint validity is mechanical, semantic truth is not.

Validators may check schema, types, uniqueness, completeness, namespace membership, exact `change_ref`, and explicit structural links where applicable. They must not claim to validate model-inferred semantic truth, repair artifacts, or impute missing content.

## 12. Intermediate failures and shared accounting

| Class | Examples | Treatment |
|---|---|---|
| **SCHEMA_INVALID** | malformed JSON, missing/wrong fields or types, forbidden fields, disallowed enum, duplicate or missing decision entries | intermediate model/mechanism failure |
| **SEMANTIC_REFERENCE_INVALID** | nonexistent/wrong-namespace decision, knowledge, or trace ref; wrong `change_ref`; unsupported claim about a mechanically verifiable link | intermediate model/mechanism failure |
| **FORBIDDEN_SEMANTIC_CONTENT** | materiality/necessity/sufficiency/survivability judgment, answer-bearing free text, confidence/ranking | intermediate model/mechanism failure |
| **PROVIDER_DELIVERY_FAILURE** | delivery exhausted without model response | infrastructure failure, kept distinct |

The first model response closes the Stage-1 scientific observation. Invalid artifacts are not regenerated, repaired, semantically normalized, imputed, manually corrected, or sent to Gemini again.

One shared Reconstruction failure for a scenario/repetition is recorded once. RB1, RB2, and RB3 are downstream-blocked; this is not three independent Stage-1 failures, but all three end-to-end pipelines lack final output and the failure counts against practical reconstruction reliability. Invalid model responses remain model behavior, not provider outage. Existing audited transport semantics are reused unless a future scaffold protocol proves a reason otherwise.

## 13. Stage-2 input contract

- RC0: original implicit candidate view plus canonical GenericContextRecord.
- RB1/RB2/RB3: original implicit candidate view plus the same canonical DecisionSupportRecord.
- RB0: original implicit candidate view only.
- RR1: structured candidate view only.

The original input is never replaced by the intermediate artifact. No Stage-1 process receives private/oracle data, RR1 output, ground truth, or extra scenario facts.

## 14. Frozen literal prompts

Each block below is UTF-8 text exactly between the code fences, without a trailing newline for hashing.

### RC0 Stage 1

Version: `rc0-stage1-generic-organization-v0.1`
SHA-256: `fd4063e278126464c43989cb634467bb201612f55b4ba5c80fcf3ff413fb8777`

```text
GENERIC CONTEXT ORGANIZATION:
Using only the provided Stage1VisibleProjection, reproduce its operational
content in the required GenericContextRecord schema.

Preserve all visible objects and their candidate-visible fields required by
that schema.

Do not omit, select, rank, prioritize, summarize away, repair, reinterpret,
infer, or add information.

Do not create knowledge/evidence-to-decision mappings.

Do not infer change-to-prior-knowledge mappings beyond structure already
mechanically present in the visible input.

Do not make judgments about relevance, reliance, material dependence,
necessity, sufficiency, survivability, justification, reopening, or
alternative support.

This task is organization only.
```

### Reconstruction Stage 1

Version: `reconstruction-stage1-v0.1`
SHA-256: `b691855c1d3e6240daa45b5174e66c7a18286b9c943abe034dff7b33540cd716`

```text
DECISION SUPPORT RECONSTRUCTION:
Using only the provided Stage1VisibleProjection, produce the required
DecisionSupportRecord.

For change_alignment, identify zero or more visible knowledge_before IDs that
are plausible candidates for the prior knowledge revised by the visible
change.

For every visible decision, identify zero or more visible knowledge_before IDs
that are plausible candidates for having been informationally connected to
that decision.

Where visible transmissions provide a traceable basis for a candidate
connection, include their IDs in basis_trace_refs. basis_trace_refs may be
empty.

Return only the candidate references required by the frozen
DecisionSupportRecord schema.

Do not judge or encode whether any candidate connection is necessary,
sufficient, supporting, material, critical, decisive, essential, justified,
surviving, or grounds for reopening.

Do not identify or encode alternative support.

Do not rank, score, weight, or assign confidence to candidate references.

Do not add rationale, explanation, reasoning text, or other unrestricted
free-text fields.
```

### Survivability Stage 2

Version: `survivability-stage2-v0.1`
SHA-256: `18c946ff305a079cc1de83baf8e01a192717fa21942bd06530573d1ec6666c2f`

```text
DECISION SURVIVABILITY:
For each decision, evaluate the counterfactual in which the changed premise is
replaced by the updated knowledge while all other still-valid information
remains available.

Classify the decision as materially dependent only if, under that
counterfactual, its remaining support is no longer sufficient to justify the
same decision.

Do not treat the mere fact that changed information participated in the
original decision as sufficient reason to reopen it.
```

### Alternative Support Stage 2

Version: `alternative-support-stage2-v0.1`
SHA-256: `ffe28d4ba2459442f04fdac8dc0406dff8c64f093f176ee719946274170eab9e`

```text
ALTERNATIVE SUPPORT CHECK:
Before concluding that the counterfactual decision lacks sufficient support,
explicitly search the candidate-visible information for an independent
remaining reason or evidence source that would be sufficient to justify the
same decision without relying on the changed premise.
```

## 15. Prompt composition invariants

- RB0 final task = frozen `BASE_TASK_PROMPT`.
- RR1 final task = frozen `BASE_TASK_PROMPT`.
- RC0 Stage 1 = RC0 generic instruction only.
- RC0 Stage 2 = frozen base task plus original implicit input and canonical GenericContextRecord.
- Reconstruction Stage 1 = Reconstruction instruction only.
- RB1 Stage 2 = frozen base task plus original implicit input and canonical shared DecisionSupportRecord.
- RB2 Stage 2 = exactly RB1 Stage 2 plus exactly Survivability Stage-2 instruction.
- RB3 Stage 2 = exactly RB2 Stage 2 plus exactly Alternative-Support Stage-2 instruction.

Therefore RB2 − RB1 is only the Survivability instruction, and RB3 − RB2 is only the Alternative-Support instruction. RC0 and Reconstruction Stage 1 receive byte-identical projection bytes and differ only in frozen instruction and output schema. There are no examples, hidden instructions, private labels, extra facts, unequal model quality, RR1 predictions, or unapproved reasoning instructions.

## 16. Model and configuration fairness

Use the same contemporary Gemini family/configuration wherever condition structure permits. Before execution freeze exact model ID, temperature, structured-output configuration, timeout, SDK attempts, delivery attempts, backoff, pacing, concurrency, output schemas, prompt hashes, projection hash, artifact schemas, execution-plan hash, Git SHA, and protocol SHA. Document unavoidable structural differences; never silently vary configuration by condition.

## 17. DEV screening and schedule

Initial screening uses the frozen 12 DEV scenarios and one repetition. Per scenario:

| Scientific stage | Calls |
|---|---:|
| RB0 final | 1 |
| RR1 final | 1 |
| RC0 Stage 1 | 1 |
| RC0 Stage 2 | 1 |
| Shared Reconstruction Stage 1 | 1 |
| RB1 Stage 2 | 1 |
| RB2 Stage 2 | 1 |
| RB3 Stage 2 | 1 |
| **Total** | **8** |

This is 96 conceptual model calls and 72 final condition outputs. Stage-1 artifacts are intermediate, not independent Discovery observations.

Before any provider call, freeze the complete dependency plan with scenario, repetition, scientific stage, condition, Stage-1 dependency, within-scenario order, and global position. Avoid systematic temporal confounding as dependencies permit. PREPARE fixes order; CLI cannot reorder it. Scientific outcomes never adapt the schedule. Intermediate invalidity blocks only dependent calls. Persist plan SHA-256.

## 18. Cost accounting and scientific unit

Persist model calls, delivery attempts, input/output tokens, latency, provider failures, intermediate model failures, and final invalid outputs separately. Report tournament-amortized cost (shared reconstruction counted once across RB1–RB3) and standalone pipeline cost (each RB pipeline charged for its required reconstruction). Shared tournament infrastructure cannot make RB3 appear deployment-cheaper.

The primary independent unit is `scenario_id + decision_id`. Repetitions measure stability and are not independent benchmark examples. Stage-1 artifacts are intermediate observations, not independent decision units.

## 19. Metrics and advancement gates

Preserve the Round A safety principle: contemporary M0 recall was 1.0. Prioritize, in order:

1. material false-negative preservation;
2. correct-unit preservation;
3. still-justified preservation;
4. reduction in material false positives/unique binary failures;
5. incremental benefit over the relevant control;
6. stability;
7. cost and latency.

Dependency-strength changes are secondary unless they cross the frozen operational boundary. Detail alone does not advance a mechanism.

Interpret RB0/RC0, RC0/RB1, RB1/RB2, RB2/RB3, and RB0/RR1 only according to Section 5. Screening outcomes are limited to:

- `FAIL / DO NOT ADVANCE`
- `FAIL / SAFETY REGRESSION`
- `PROMISING`
- `AMBIGUOUS / NEEDS CONFIRMATION`
- `INCOMPLETE / INFRASTRUCTURE`

Never use `PROVEN` or `GENERALIZED`.

Any new material false negative is a **SEVERE REGRESSION SIGNAL**, but one one-repetition observation is not automatically a reproducible property. A candidate is `PROMISING` only with at least one operational improvement over its relevant contemporary control, no new operationally relevant regression, and no gain solely from strength labels. If it has at least one operational improvement and exactly one new operational regression at the unique scenario/decision level, classify `AMBIGUOUS / NEEDS CONFIRMATION` and preserve every improved/regressed unit and field. Multiple or broad new material false negatives without compensating operational improvement may be `FAIL / SAFETY REGRESSION`. No operational improvement means no advancement merely for plausible intermediate artifacts.

This protocol authorizes screening only. Any `PROMISING` or `AMBIGUOUS / NEEDS CONFIRMATION` result requires a separately precommitted confirmation protocol before another call, freezing conditions, repetitions, coverage, model/config, seeds where applicable, schedule, failure handling, thresholds, and reproducibility. Screening may select only the predefined outcome category; it cannot adapt sample size, stopping, prompts, mechanisms, or thresholds.

## 20. Freeze, interpretation, and claim boundary

After freeze, Stage-1 schemas/projection/prompts, Stage-2 prompts, canonicalization, schedule, and gates cannot change in response to DEV, including `dev-002/d3`. Failure is recorded; a later hypothesis requires a later protocol.

An informative but non-required pattern is `RC0 ≈ RB0`, `RB1 > RC0`, `RB2 > RB1`, `RB3 > RB2`, without new material false negatives. Within DEV only, this would support a compositional hypothesis: Support Reconstruction → Survivability → Alternative-Support Preservation. If RC0 and RB1 improve similarly, an extra pass/reorganization may explain the observation. If RB1 fails but RB2 improves, reconstruction may be useful only with explicit counterfactual reasoning. If all three fail, do not force the architecture. If RR1 no longer improves over RB0, report the weakened contemporary provenance opportunity before attributing reconstruction failure.

Round B DEV can establish at most **PROMISING DEVELOPMENT EVIDENCE**. It cannot establish generalization, production reliability, cross-domain superiority, architectural/memory/Fleet necessity, or final Decision Recall efficacy.

Reserved and out of scope: sham/scrambled reconstruction, persistent memory, Support Graph, Decision Ledger, cross-agent propagation, multi-agent Fleet, ADK, Recovery/selective rollback, persistent provenance, additional M4/MX mechanisms, challenge/CADC, and sealed holdout. A sham control may be considered only in a future protocol after specialized reconstruction shows incremental value.

## 21. Implementation invariants checklist

- [ ] Exactly six final conditions: RB0, RC0, RR1, RB1, RB2, RB3.
- [ ] Projection has exactly the ten fields frozen in Section 6.
- [ ] RC0 and Reconstruction receive byte-identical projection bytes.
- [ ] Generic record is coverage-complete and contains no inferred mappings/judgments.
- [ ] DecisionSupportRecord contains only typed candidate references and complete decision coverage.
- [ ] Raw and canonical artifacts are separate; Stage 2 receives canonical only.
- [ ] Canonical serialization and artifact hash are frozen.
- [ ] One reconstruction artifact is shared byte-identically by RB1/RB2/RB3 per scenario/repetition.
- [ ] RB2 − RB1 equals only the frozen Survivability block.
- [ ] RB3 − RB2 equals only the frozen Alternative-Support block.
- [ ] Reference, structural, and inferred-semantic validity remain distinct.
- [ ] Intermediate model failures are neither repaired nor conflated with provider failures.
- [ ] One shared reconstruction failure is counted once and downstream blocking is explicit.
- [ ] Original candidate input accompanies every Stage-2 intermediate artifact.
- [ ] RR1 is a reference, never oracle/ceiling/input to reconstruction.
- [ ] Complete 96-call dependency schedule and hashes freeze before execution.
- [ ] Exactly 72 final condition outputs are planned.
- [ ] Primary unit is scenario/decision; Stage-1 and repetitions are not independent examples.
- [ ] Screening gates and no-DEV-tuning rule are enforced.
- [ ] No confirmation, sealed holdout, or out-of-scope mechanism is executed under v0.1.
