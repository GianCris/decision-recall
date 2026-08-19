# Decision Recall Round B Protocol v0.2

Status: **FROZEN FOR STAGE-1 INTERFACE SANITY AND LATER DEV SCREENING ONLY**.
This document freezes the v0.2 design. It does not authorize implementation,
provider calls, sanity execution, full screening, confirmation, or sealed-holdout
access.

## 1. Purpose and correction boundary

Round B v0.1 remains immutable historical evidence. Its screening execution
identified two interface/control-design problems:

1. model-generated administrative `schema_version` values blocked otherwise
   contract-valid Reconstruction artifacts; and
2. RC0's provider contract was weaker than its post-response validator and
   effectively tested high-fidelity copying rather than the intended generic
   semantic second pass.

Round B v0.2 corrects only those issues. It does not tune Reconstruction or
Discovery against observed DEV outcomes. Historical v0.1 artifacts and the
version-only counterfactual diagnostic are never reused as v0.2 scientific
observations.

The v0.2 versions are:

| Component | Frozen version |
|---|---|
| Protocol | `round-b-protocol-v0.2` |
| Harness envelope | `artifact-envelope-v0.2` |
| RC0 payload | `neutral-grounded-context-payload-v0.2` |
| Reconstruction payload interface | `decision-support-payload-v0.2` |
| Stage-1 interface sanity | `round-b-stage1-interface-sanity-v0.2` |
| Future full screening | `round-b-screening-v0.2` |

The new Reconstruction payload-interface version records removal of
model-generated administrative fields; it does not change Reconstruction's
scientific instruction, fields, or semantics.

## 2. Exact differences from v0.1

| Area | v0.1 | v0.2 |
|---|---|---|
| Administrative metadata | model generated `schema_version` and `scenario_id` inside Stage-1 records | harness-owned `ArtifactEnvelope`; administrative fields forbidden inside model payloads |
| RC0 artifact | coverage-complete `GenericContextRecord` | selective, extractive `NeutralGroundedContextPayload` |
| RC0 validation | exact preservation of the full projection after a provider schema that underspecified nested content | exact source resolution and categorical minimum coverage under one frozen JSON Pointer convention |
| Stage-1 preflight | none | separate precommitted six-call interface sanity with no Stage 2 or Discovery evaluation |

Everything else remains scientifically unchanged: the conditions and intended
contrasts; frozen implicit and structured candidate views; exact
`Stage1VisibleProjection`; Reconstruction instruction and semantics; original
input retention in Stage 2; shared byte-identical Reconstruction artifact for
RB1/RB2/RB3; Survivability and Alternative-Support instructions; Discovery
prompt, schema, parser, validator, evaluator, and scoring; model/configuration
fairness; transport and delivery policy; DEV screening-only claim boundary;
no automatic confirmation; and sealed-holdout exclusion.

## 3. Harness-owned artifact envelope

Administrative artifact metadata belongs entirely to the harness:

```text
ArtifactEnvelope {
  artifact_schema_version,
  scenario_id,
  stage_id,
  artifact_sha256
}
```

None of these four fields is generated inside a model payload. Each model-facing
Stage-1 schema uses a closed object and rejects administrative metadata,
including `artifact_schema_version`, `schema_version`, `scenario_id`,
`stage_id`, and `artifact_sha256`, rather than ignoring it.

Only after the model payload passes its frozen validator does the harness:

1. canonicalize the validated model payload under its stage-specific rules;
2. serialize it deterministically as UTF-8 JSON with sorted object keys, an
   indentation of two spaces, `ensure_ascii=false`, and exactly one trailing
   newline;
3. compute lowercase hexadecimal SHA-256 over those exact bytes; and
4. construct the envelope using the stage's frozen payload-schema version, the
   planned scenario and stage identifiers, and that digest.

Stage 2 receives only the validated canonical model payload together with its
harness-owned envelope. It never receives raw Stage-1 output.

## 4. Frozen Stage1VisibleProjection

RC0 and Reconstruction Stage 1 receive byte-identical deterministic
serialization of the v0.1 projection:

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

Values are copied from the frozen implicit Discovery candidate view without
inference, summarization, repair, ranking, reinterpretation, or enrichment.
No private/oracle value is included. The exclusions frozen in v0.1 remain
unchanged.

## 5. Reconstruction is scientifically unchanged

The complete model-owned payload is:

```text
DecisionSupportPayload {
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

The model-facing object is closed and contains exactly `change_alignment` and
`decision_connections`. The nested objects are also closed and contain exactly
the fields shown.

The v0.1 semantics are preserved exactly:

- `change_ref` equals the visible change ID;
- candidate prior-knowledge references are unique visible
  `knowledge_before[].id` values only;
- there is exactly one connection per visible decision, with no missing,
  duplicate, or invented decision;
- candidate knowledge references are unique visible `knowledge_before[].id`
  values only;
- basis trace references are unique visible `transmissions[].id` values only;
- empty candidate/reference sets remain valid;
- connections and unordered reference arrays are canonically sorted;
- no materiality, necessity, sufficiency, survivability, alternative support,
  ranking, confidence, or free-text rationale is emitted.

The exact Reconstruction instruction remains `reconstruction-stage1-v0.1`,
SHA-256
`b691855c1d3e6240daa45b5174e66c7a18286b9c943abe034dff7b33540cd716`.
Its text is unchanged from Round B v0.1. The diagnostic observation that 12/12
historical Reconstruction payloads passed the reference/interface validator
after an in-memory version-only normalization is interface evidence only and
is not reused as v0.2 scientific output.

## 6. RC0 v0.2: NeutralGroundedContextPayload

RC0 is a generic semantic second-pass control. Its complete model-owned
payload is:

```text
NeutralGroundedContextPayload {
  grounded_items: [
    {
      source_path,
      source_text
    }
  ]
}
```

The model-facing root object is closed and contains exactly `grounded_items`.
Every item is a closed object containing exactly two non-empty strings,
`source_path` and `source_text`. RC0 may choose which candidate-visible textual
elements to surface; it need not reproduce every visible object.

### 6.1 Frozen source-path convention

`source_path` is an RFC 6901 JSON Pointer rooted at the exact
`Stage1VisibleProjection` supplied to Stage 1, with these frozen constraints:

- it is non-empty and begins with `/`;
- object member tokens escape `~` as `~0` and `/` as `~1`;
- an array element is addressed by its canonical zero-based decimal index:
  `0`, or a positive integer with no leading zero;
- the `-` array token is forbidden;
- the pointer must resolve inside the projection to one existing terminal
  string value;
- pointers to an object, array, number, Boolean, or null are invalid;
- pointers outside the projection or into excluded/private/oracle information
  are invalid; and
- `source_text` must equal the complete resolved string exactly, by Unicode
  code-point equality. No whitespace normalization is performed.

Substrings, paraphrases, summaries, semantic rewrites, inferred text, and
generated commentary are invalid. Validation is exactly:

```text
resolve(Stage1VisibleProjection, source_path) == source_text
```

### 6.2 Canonicalization and side-channel control

`grounded_items` is semantically an unordered set. Each `source_path` must be
unique; duplicate paths or duplicate grounded items are invalid. After
validation, items are sorted lexicographically by `source_path` using Unicode
code-point order. No raw output ordering reaches Stage 2.

The payload permits no score, confidence, rank, weight, top-k marker, relevance
label, or unrestricted free-text field. Selection membership is the only
model-generated organization signal.

### 6.3 Categorical minimum coverage

For every scenario, at least one valid grounded item must resolve beneath each
of these top-level projection members:

- `/knowledge_before`: at least one;
- `/change`: at least one;
- `/decisions`: at least one; and
- `/transmissions`: at least one only when the projection's `transmissions`
  array is non-empty.

Coverage is categorical, not relevance-based. It does not require every object
or the "best" item. `agents`, `world`, `consequences`, and `recovery_actions`
are optional; they may be selected only through valid terminal-string paths.

### 6.4 Prohibited semantics

RC0 cannot explicitly represent change-to-prior-knowledge mappings,
knowledge/evidence-to-decision mappings, decision-specific evidence groups,
provenance, reliance, materiality, dependency strength, necessity,
sufficiency, survivability, still-justified judgments, reopening, alternative
support, confidence, or ranking. Any semantic value it carries must be an
exact complete candidate-visible source string referenced by `source_path`.

RC0 Stage 2 receives the original frozen implicit candidate-visible input plus
the canonical `NeutralGroundedContextPayload` and its harness-owned envelope.

### 6.5 Frozen RC0 Stage-1 instruction

Version: `rc0-stage1-neutral-grounded-context-v0.2`
SHA-256: `4f6609f3de823babe7d0631fdd25709a0d5e4bb5059f47df9899cf39f4a01b4c`

The instruction is UTF-8 text exactly between the code fences, without a
trailing newline for hashing:

```text
NEUTRAL GROUNDED CONTEXT:
Using only the provided Stage1VisibleProjection, produce the required
NeutralGroundedContextPayload.

Select candidate-visible textual elements and return each selected complete
source string together with its exact JSON Pointer source_path.

Include at least one grounded item from knowledge_before, change, and
decisions. If transmissions is non-empty, include at least one grounded item
from transmissions.

Do not paraphrase, summarize, shorten, rewrite, interpret, or add text.
source_text must exactly equal the complete string resolved by source_path.

Do not construct or encode change-to-prior-knowledge mappings,
knowledge/evidence-to-decision mappings, decision-specific evidence groups,
provenance, reliance, materiality, dependency strength, necessity,
sufficiency, survivability, justification, reopening, or alternative support.

Do not rank, score, weight, label relevance, or assign confidence to grounded
items.

Return only the fields required by the frozen NeutralGroundedContextPayload
schema.
```

## 7. Stage-1 fairness

RC0 and Reconstruction Stage 1 receive byte-identical
`Stage1VisibleProjection` bytes. They differ only in their frozen Stage-1
instruction and model-output payload schema. They use the same model family
and generation configuration, transport, delivery policy, timeout,
structured-output mode where applicable, pacing policy, and source projection.

Reconstruction may infer candidate change-to-prior-knowledge and
knowledge/evidence-to-decision connections. RC0 may not. Neither receives
private/oracle data.

## 8. Precommitted Stage-1 interface sanity

Before any full v0.2 screening, one separate interface-only sanity must be
prepared and executed. It never executes Stage 2, evaluates Discovery, reads
oracle labels, computes performance metrics, tunes on a known failure, reuses
historical output, or changes the protocol after observing its outputs.

### 8.1 Deterministic scenario selection

Selection uses only frozen candidate-visible projection structure:

- **S1:** lowest `scenario_id` with `len(transmissions) > 0`;
- **S2:** lowest `scenario_id` with `len(transmissions) == 0`;
- **S3:** among remaining DEV scenarios, maximize
  `len(agents) + len(knowledge_before) + len(transmissions) + len(decisions) +
  len(consequences) + len(recovery_actions)`; break ties by lowest
  `scenario_id`.

Applied to the frozen DEV projections, this selects:

| Role | Scenario | Relevant structural result |
|---|---|---|
| S1 | `dev-001` | lowest ID with one or more transmissions |
| S2 | `dev-005` | lowest ID with zero transmissions |
| S3 | `dev-006` | score 16; ties `dev-010`, resolved by lowest ID |

The IDs are frozen by PREPARE before any provider call. The selection uses no
label, prediction, historical failure, performance, or private metadata.

### 8.2 Frozen six-call order

PREPARE freezes this exact schedule:

| Global sanity position | Scenario | Stage-1 condition |
|---:|---|---|
| 1 | `dev-001` | RC0 Neutral Grounded Context |
| 2 | `dev-001` | Reconstruction |
| 3 | `dev-005` | Reconstruction |
| 4 | `dev-005` | RC0 Neutral Grounded Context |
| 5 | `dev-006` | RC0 Neutral Grounded Context |
| 6 | `dev-006` | Reconstruction |

This contains exactly three calls per Stage-1 condition, alternates conditions
across all six positions, and reverses within-scenario order for S2. No Stage-2
call is scheduled.

### 8.3 PASS and failure policy

`PASS` requires all six planned Stage-1 observations to return model responses
and all six model payloads to validate under their respective v0.2 contracts.

An invalid model payload is preserved as model/mechanism behavior, is never
repaired, regenerated, or retried as reasoning, and yields `SANITY FAIL`.
A provider delivery failure after the frozen transport policy is exhausted
yields `SANITY INCOMPLETE / INFRASTRUCTURE`. Any result other than `PASS`
stops the process: no full screening, automatic prompt/schema/validator
change, rerun, or new experiment follows.

Sanity output is diagnostic interface evidence only. It cannot be reused in
the full screening, fill a full-screening slot, enter a performance aggregate,
reduce future calls, or serve as an official Reconstruction result. A later
authorized full screening starts from scratch.

The sanity establishes at most: "the v0.2 Stage-1 interfaces were successfully
producible for the frozen sanity cases." It establishes no scientific
correctness, superiority, Decision Recall effectiveness, generalization, or
production readiness.

## 9. Future full Round B v0.2 screening

Except for Sections 2, 3, and 6 and the mandatory separate sanity, the v0.1
scientific design is preserved:

- RB0, RC0, RR1, shared Reconstruction Stage 1, RB1, RB2, and RB3;
- contrasts RB0 -> RC0, RC0 -> RB1, RB1 -> RB2, RB2 -> RB3, and RB0 -> RR1;
- original input retained in every Stage 2;
- one validated canonical Reconstruction artifact shared byte-identically by
  RB1/RB2/RB3 per scenario and repetition;
- unchanged Survivability instruction
  (`18c946ff305a079cc1de83baf8e01a192717fa21942bd06530573d1ec6666c2f`);
- unchanged Alternative-Support instruction
  (`ffe28d4ba2459442f04fdac8dc0406dff8c64f093f176ee719946274170eab9e`);
- unchanged frozen Discovery task and evaluator/scoring contract;
- 12 frozen DEV scenarios, one screening repetition, 96 conceptual calls, and
  72 final condition outputs under the separately frozen dependency plan;
- existing failure accounting, screening gates, safety priority, cost
  accounting, transport rules, and no automatic confirmation; and
- DEV development-evidence and sealed-holdout claim boundaries.

No v0.1 screening or sanity output is reused. A future implementation must
freeze the v0.2 protocol hash, Git SHA, payload schemas and their hashes,
envelope version, projection hash, prompt hashes, model/configuration,
transport, sanity plan hash, and full-screening plan hash before the relevant
provider call.

## 10. Claim boundary and out of scope

Round B v0.2 remains DEV screening design. It cannot establish generalization,
production reliability, architectural necessity, or final Decision Recall
efficacy. It is not a controlled causal sweep.

This protocol does not authorize implementation, provider calls, sanity or
screening execution, prompt/schema repair after observing output,
confirmation, challenge/CADC work, Recovery, ADK/Fleet/UI, new scenarios, or
sealed-holdout access.

## 11. Freeze checklist for later implementation

- [ ] Administrative fields are absent from and forbidden in both model payload schemas.
- [ ] The harness creates `ArtifactEnvelope` only after payload validation.
- [ ] Artifact hashing uses the exact canonical serialization in Section 3.
- [ ] Reconstruction instruction and scientific payload semantics remain unchanged.
- [ ] RC0 contains only exact terminal strings referenced by valid JSON Pointers.
- [ ] RC0 categorical coverage and prohibited-semantic rules are enforced exactly.
- [ ] RC0 canonical ordering cannot carry ranking or confidence.
- [ ] RC0 and Reconstruction receive byte-identical projection bytes.
- [ ] The six-call sanity selection and order are frozen before any call.
- [ ] Sanity executes no Stage 2 and reads no oracle data.
- [ ] Sanity output cannot be reused by full screening.
- [ ] A non-PASS sanity prevents full v0.2 screening.
- [ ] The full screening otherwise preserves all v0.1 scientific invariants.
- [ ] Historical v0.1 evidence remains immutable and separate.
- [ ] No sealed-holdout data is accessed.
