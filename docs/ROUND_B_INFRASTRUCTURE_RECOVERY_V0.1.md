# Round B Infrastructure Recovery Protocol v0.1

Status: **frozen documentation; implementation and provider execution are not authorized**.

This protocol governs one narrowly scoped infrastructure-recovery observation
for the incomplete development screening in `round-b-v02-screening-output/`.
It does not change Round B v0.2 science, mechanisms, prompts, schemas,
candidate views, evaluation, scoring, or transport. The original experiment
remains immutable and historically `INCOMPLETE / INFRASTRUCTURE`.

## 1. Purpose and claim boundary

Recovery is permitted only for a scientific slot that ended in a terminal
pre-response provider/delivery failure and consequently has no model response,
parsed prediction, or evaluation. It permits at most one separately authorized
infrastructure-recovery observation without rerunning or replacing successful
observations.

This is DEV screening only. A recovered view cannot establish generalization,
production or transport reliability, model superiority, or scientific validity
of Round B mechanisms by itself. Every report must disclose that one
observation was recovered outside the original provider-call chronology.

## 2. General recovery eligibility

A slot is eligible if and only if all of these conditions hold:

1. its original scientific identity is unambiguous;
2. it reached a terminal provider/delivery-failure state before a response;
3. `model_response_obtained == false`;
4. no raw model response exists;
5. no parsed scientific prediction exists;
6. no valid or invalid final model prediction exists;
7. no evaluation exists;
8. every required upstream artifact exists and is valid;
9. the original manifest, plan, lifecycle, RunRecord, and successful
   observations remain immutable;
10. eligibility is determined solely from infrastructure/lifecycle metadata;
11. recovery does not replace an unfavorable answer, invalid model response,
    scored scientific error, or valid model response.

A model-invalid response and a scientifically incorrect but valid response are
not recovery-eligible.

## 3. Application to the frozen experiment

The immutable lifecycle metadata establish exactly one eligible slot:

| Field | Historical value |
|---|---|
| original global execution index | `11` |
| scenario | `dev-002` |
| condition | `RC0` |
| stage | `RC0_STAGE2` |
| observation kind | `final` |
| repetition | `1` |
| candidate-view mode | `implicit` |
| dependency | `RC0_GENERIC_STAGE1` |
| HTTP status | `499` |
| provider outcome | `pre_response_failure` |
| model response obtained | `false` |
| retryable | `false` |
| provider failure | `true` |

This is the sole terminal provider failure. Its Stage-1 dependency completed
successfully, and the exact validated canonical dependency artifact exists with
SHA-256:

`98ba67a06bc97cc14ad322f4e580a9d3e232aa3c777fd580eb2823563fb367d5`

The failed RunRecord contains an empty raw response, a null parsed response,
and `validation_status = provider_error`; no evaluation exists for index 11.
These findings use no successful-condition prediction or performance result.

### 3.1 Original source identity

The recovery manifest must copy these historical identifiers from the original
artifacts, not substitute later values:

| Identity | Historical value |
|---|---|
| experiment version | `round-b-screening-v0.2` |
| manifest type | `round-b-screening-manifest-v0.2` |
| implementation Git SHA | `167ecfa50c871c74d0aee4ed9abd9feab40fc923` |
| source protocol commit | `bfa262a8b7cd4ee30f17e3445e39c14b7f9ad916` |
| Round B protocol SHA-256 | `eba2cd3d3c848ca43a0c26e1eb7c23e1c5be3af6a44a218a2018bb4019c1f335` |
| execution-plan SHA-256 | `afd547143c229d7ec19ebc5f889ac94ed2844168d4b9841e8d60724474af9023` |
| model ID | `gemini-3.7-flash` |
| model adapter | `google-genai-vertex-gemini-3.7-flash-v0.1` |
| provider | `Google Cloud Agent Platform / Vertex` |
| project | `decision-recall-hackathon` |
| location | `global` |
| SDK | `google-genai==2.14.0` |
| Discovery schema version | `discovery-response-v0.1` |
| Discovery schema SHA-256 | `c1da8e87a79950b25c57bfdd411a44c6482ec15cbadeca69b6019e7fbda52ce5` |
| structured output | enabled, `application/json` |
| candidate-view contract | `0.1`, `implicit` for the eligible slot |
| dataset | `DR-Bench` version `0.1` |
| transport policy | `delivery-v0.1` |
| transport configuration | SDK attempts 1; harness attempts 4; timeout 120000 ms; backoffs 5/10/20 seconds; no jitter; concurrency 1; first response wins; 10-second inter-slot pacing in the original run |

The historical model version is persisted as null; no value may be invented.

## 4. Original experiment immutability

The original directory is read-only historical evidence. Recovery must not
edit, append, delete, replace, normalize, backfill, or rewrite its manifest,
plan, plan hash, lifecycle, failure record, RunRecord, summary, timestamps,
Stage-1 artifacts, successful final observations, or evaluations. Its status
remains `INCOMPLETE / INFRASTRUCTURE`, even after a successful recovery.

## 5. Separate recovery experiment

Recovery requires a new experiment version, manifest type, output directory,
execution plan, plan SHA, timestamps, and lifecycle. Its manifest must link to
the original directory identity, experiment version, implementation and
protocol SHAs, execution-plan SHA, global index 11, complete slot identity,
and original provider-failure lifecycle record.

It is not a resume, continuation, replay, or replacement. No original artifact
may be used as a writable destination.

## 6. Hard scientific-input identity gate

Before any provider call, a future recovery PREPARE must freeze evidence that
the following are byte- or value-identical to the original failed slot:

1. candidate-visible input;
2. candidate-view mode;
3. dependency artifact canonical bytes;
4. dependency artifact SHA-256;
5. Stage-2 effective prompt bytes;
6. Stage-2 effective prompt SHA-256;
7. Discovery output schema;
8. Discovery schema SHA/version;
9. model identifier;
10. generation configuration;
11. provider/location configuration;
12. scientific condition/stage identity.

"Current code should recreate it" is not proof. Category B below is acceptable
only when deterministic reconstruction is performed from immutable original
artifacts plus the exact frozen code/config and its result is hashed before a
call. Any Category C component blocks PREPARE and provider execution with:

**RECOVERY FEASIBILITY BLOCKER — ORIGINAL SCIENTIFIC INPUT IDENTITY CANNOT BE PROVEN**

### 6.1 Identity-evidence feasibility

`A` means already persisted and directly verifiable. `B` means not persisted
as final bytes but deterministically reconstructable and provable before a
call. `C` means not provable.

| Required component | Class | Existing evidence and required proof |
|---|:---:|---|
| candidate-visible input | B | Reconstruct from the immutable `dev-002` benchmark artifact using the candidate-view contract at implementation SHA `167ecf…`; freeze canonical bytes and SHA before a call. |
| candidate-view mode | A | Plan and failed RunRecord persist `implicit`. |
| dependency canonical bytes | A | `stage1_artifacts.jsonl` persists the exact validated `canonical_bytes_utf8`. |
| dependency SHA-256 | A | Artifact, envelope, and failed RunRecord persist `98ba67…`; recomputation over persisted bytes must agree. |
| Stage-2 effective prompt bytes | B | Deterministically reconstruct using the frozen `build_stage2_prompt` path, reconstructed visible input, and exact persisted canonical artifact bytes at the original implementation SHA; freeze bytes before a call. |
| Stage-2 effective prompt SHA-256 | B | Compute from the proven effective prompt bytes before a call; no historical prompt SHA was persisted for this slot. |
| Discovery output schema | B | Reconstruct the exact schema object from the frozen implementation SHA, canonicalize deterministically, and require its hash to match the persisted schema authority. |
| Discovery schema SHA/version | A | Manifest and plan persist `discovery-response-v0.1` and SHA `c1da8e…`. |
| model identifier | A | Manifest and failed RunRecord persist `gemini-3.7-flash` and adapter identity. |
| generation configuration | A | Failed RunRecord persists the experiment configuration: provider defaults for temperature/max output/model version, native structured output enabled, JSON MIME type, and Discovery schema version. Null values remain null. |
| provider/location configuration | A | Manifest persists provider, project, location, SDK package/version, and structured-output mode. |
| scientific condition/stage identity | A | Plan, lifecycle, terminal record, and RunRecord persist index 11, `dev-002`, `RC0`, `RC0_STAGE2`, final observation, repetition 1, and its dependency. |

No required component is presently Category C. Consequently, targeted
recovery is eligible to proceed only to a separately authorized implementation
task that builds and verifies every A/B gate. This document does not authorize
PREPARE or a provider call.

## 7. Dependency, prompt, schema, and model identity

Recovery must consume the exact original canonical RC0 Stage-1 payload with
SHA `98ba67a06bc97cc14ad322f4e580a9d3e232aa3c777fd580eb2823563fb367d5`.
It must not regenerate Stage 1, recanonicalize it differently, or substitute a
sanity, v0.1, other-scenario, or other-stage artifact. `ArtifactEnvelope`
remains out-of-band and is never Stage-2 model-visible.

Stage 2 must use the exact frozen RC0 task and Discovery schema. It receives no
new instruction, example, or recovery notice. The model is not told that the
slot is recovered, previously failed, selected as `dev-002`, or preceded by
completed conditions. Harness recovery metadata remains out-of-band.

## 8. Unchanged transport and one-observation rule

Recovery uses frozen `delivery-v0.1` unchanged: SDK attempts 1, maximum harness
delivery attempts 4, retryable HTTP statuses `408, 429, 500, 502, 503, 504`,
5/10/20-second applicable backoffs, no jitter, 120-second per-attempt timeout,
first model response wins, no retry after a response, and sequential execution.
HTTP 499 remains nonretryable. Recovery does not redefine the original 499.

At most one recovery scientific observation is authorized for index 11. Its
ordinary delivery lifecycle may contain multiple attempts only for already
frozen retryable pre-response failures; these are not additional scientific
observations. The first response closes the observation permanently. No
successful slot, temporal anchor, other model, best-of-N, or replacement call
is permitted.

## 9. Failure and stop semantics

- Terminal provider failure: persist separately, status
  `INCOMPLETE / INFRASTRUCTURE`, no automatic second recovery or transport
  change, then stop.
- Returned but invalid Discovery response: preserve raw output, status
  `FAIL / MODEL OUTPUT`, no repair or regeneration, then stop.
- Operator/system interruption: status `ABORTED`, no automatic resume.
- Only one valid parsed response creates a recovered scientific observation.

## 10. Temporal and order integrity

The slot retains `original_global_execution_index = 11`, but recovery occurs
after the original chronology. Persist the original failed-attempt start and
end timestamps, recovery invocation and completion timestamps,
`out_of_original_order = true`, and `infrastructure_recovered = true`.

Never rewrite original timestamps, represent the call as occurring between
slots 10 and 12, or claim the original provider chronology was preserved. The
temporal deviation must be visible in every recovered-screening report.

## 11. Scientific-result blindness

Eligibility, PREPARE, and execution may not load successful predictions,
evaluations, aggregate scores, contrasts, or leaderboard-like summaries to
decide whether or how to recover, accept an answer, or retry. Recovery input
construction depends only on immutable input/config/artifact and infrastructure
metadata. No observed scientific result may affect execution.

## 12. Evaluation and recovered screening view

Only a valid recovered response may be parsed with the unchanged parser and
evaluated with the unchanged evaluator. Persist that evaluation separately;
never alter original evaluation files or fabricate an evaluation.

A later derived **Round B v0.2 Recovered Screening View** may combine the
original immutable successful observations/evaluations with exactly one valid
separate recovery. It is not a rewritten original run. It must prominently
record the recovered slot, protocol/version, out-of-order execution, and the
original experiment's continuing incomplete status.

Before applying frozen screening gates, that analysis must verify:

- all required original successful observations remain intact;
- exactly one original slot was eligible and provider-failed;
- exactly one valid recovery exists for that slot;
- no other provider, model, or intermediate failure leaves the view incomplete;
- all identity gates passed;
- parsing and evaluation succeeded;
- no successful slot was rerun or replaced.

Any classifiable view must retain
`contains_infrastructure_recovered_observation = true` and
`out_of_original_order_recovery_count = 1`.

### 12.1 Recovery-dependence disclosure

The recovered view is not equivalent to an uninterrupted experiment. It must
identify which frozen contrasts and condition metrics include the recovered
slot and disclose its direct contribution to applicable TP/TN/FP/FN,
still-justified errors, dependency-strength diagnostics, unique
scenario-decision failures, safety/regression gates, and the advancement
decision. It must state whether the observation creates, removes, or resolves
an error or regression and whether advancement relies materially on it.

The original 71-evaluable-observation view remains
`PARTIAL / NON-CLASSIFIABLE`. Recovery must not be described as changing a
classification from that incomplete view. Sensitivity disclosure describes
the recovered observation's contribution to the only potentially classifiable
derived view; it is not alternate score selection.

## 13. Limitations and implementation boundary

Even a fully evaluable recovered view remains qualified DEV evidence, not
generalization, sealed-holdout, architectural-necessity, or transport-
reliability evidence. Every claim discloses the single infrastructure-recovered,
out-of-order observation.

This document authorizes no recovery code, PREPARE, EXECUTE, analysis, model
call, transport change, `round_b.py` change, or original-artifact mutation. A
later explicit task must implement a dedicated scaffold and verify every hard
gate before any provider call.

## 14. Stop conditions

Stop without a provider call if eligibility ceases to be unique, any original
artifact changes, any A/B identity gate fails, any required component becomes
Category C, or the recovery plan would rerun/replace another observation.
After terminal provider failure, invalid model output, or interruption, persist
the separate recovery evidence and stop under Section 9.
