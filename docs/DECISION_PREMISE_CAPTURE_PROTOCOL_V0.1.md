# Decision Premise Capture — Conservative Pre-Change Snapshot Protocol v0.1

## Status and claim boundary

This document freezes the DEV-only Decision Premise Capture experiment v0.1. It compares generic pre-change capture, premise-specific pre-change capture, no capture, and a privileged benchmark-assumption ceiling. It is not elicitation, a mechanism tournament, product architecture, confirmation, or generalization evidence.

This experiment does **not** claim to reconstruct the exact epistemic state of the human/agent decision-maker. It uses “benchmark-declared pre-change system context, augmented only by strictly earlier recorded transmissions and decisions where temporal precedence is explicitly demonstrable.”

`knowledge_before` is benchmark-declared **PRE-CHANGE SYSTEM CONTEXT**. It is not claimed to be per-decision temporally proven, agent-local knowledge, or knowledge definitely available to the target agent at `made_at`.

All observations use the frozen 12 DEV scenarios loaded only with `load_scenarios("dev")`. Sealed holdout is excluded. Historical responses, sanity responses, Round B, Reference Decomposition, recovery, A1, and baseline responses cannot be reused.

## Scientific freeze

DR-Bench, DEV scenarios, `candidate_view()`, BASE_TASK_PROMPT, Discovery schema/parser/evaluator/scoring, model/configuration, shared transport, retry/backoff/pacing, and HTTP-status classification remain unchanged. No elicitation, oracle responder, recovery planner, support graph, product system, new label, or weighted advancement score is introduced.

## ConservativePreChangeSnapshot

Create one snapshot for each of 36 DEV decisions, canonically ordered by `scenario_id`, then `decision_id`. Each snapshot contains exactly:

- `system_pre_change_context`:
  - `agents`: all candidate-visible agent fields;
  - `knowledge_before`: every entry with its existing candidate-visible fields.
- `strictly_earlier_recorded_transmissions`: candidate-visible transmission fields only, included exactly when `transmission.at < target_decision.made_at`.
- `strictly_earlier_system_recorded_decisions`: candidate-visible decision fields excluding `evidence_available` and `assumptions`, included exactly when `prior_decision.made_at < target_decision.made_at`.
- `target_decision`: its public `id`, `agent_id`, `made_at`, and `statement` only.

Same-time transmissions (`at == made_at`), future transmissions, same-time/later decisions, and the target decision as a prior decision are excluded. Earlier decisions are “prior system-recorded decisions,” not decisions known to the target agent.

Snapshots must contain no `brief`, `change`, `world`, `consequences`, `recovery_actions`, `evidence_available`, `assumptions`, `private`, `complexity`, `title`, `domain`, `split`, `discovery_condition`, oracle labels/truth, future or same-time transmissions, later decisions, holdout content, or historical model output. No renamed equivalent is allowed.

Before execution eligibility, PREPARE persists an exact 36-record proof containing snapshot identity/hash, included knowledge/transmission/prior-decision IDs, excluded same-time/future transmission IDs, excluded later-decision IDs, forbidden-field result, DEV-only result, and PASS/BLOCKED. Eligibility requires 36/36 PASS. Missing timing is not invented or repaired.

## Capture condition PGEN

PGEN is an extractive generic processing control:

```text
GenericPreChangeCapture {
  target_decision_id,
  grounded_items: [{ source_path, source_text }]
}
```

The payload has exactly those fields. `source_path` is RFC 6901 JSON Pointer rooted at the exact snapshot. It must resolve to a terminal visible string and `source_text` must equal the complete resolved string exactly. Paths are unique and canonicalized deterministically by `source_path`; duplicates are invalid. At most 12 items are allowed.

PGEN permits no paraphrase, substring extraction, summary, inference, premise category, causal/materiality/sufficiency/independence/validity/still-justified/dependency-strength judgment, confidence, ranking, or extra field. `target_decision_id` must exactly equal the snapshot target and is never repaired.

## Capture condition PAUTO

PAUTO produces:

```text
DecisionPremiseRecord {
  target_decision_id,
  validity_conditions: [{ proposition, source_type, source_refs }],
  independent_reasons: [{ proposition, source_type, source_refs }],
  constraints: [{ proposition, source_type, source_refs }],
  expectations: [{ proposition, source_type, source_refs }]
}
```

Meanings are frozen:

- `validity_conditions`: facts/states that must continue to hold for justification to remain intact;
- `independent_reasons`: reasons able to maintain the decision if another premise fails;
- `constraints`: requirements/restrictions limiting admissible decisions;
- `expectations`: anticipated states on which the decision relies.

Only `observed` and `inferred` source types exist; there is no `elicited`. Every source reference is an RFC 6901 pointer rooted at the exact snapshot and must resolve within visible snapshot content.

For `observed`, exactly one reference is required, it resolves to a terminal string, and `proposition` equals that complete string exactly. For `inferred`, generated text is allowed but one to six valid source refs are required; refs demonstrate backing, not certified entailment. Empty/unresolved refs are invalid, inferred content stays marked inferred, and it is not a verified fact.

Across all four categories, at most 12 items are allowed and each item has at most 6 refs. `target_decision_id` must exactly equal the snapshot target and is never repaired. Canonicalization preserves category order and deterministically sorts items. Persist observed/inferred counts, invalid-ref count, unreferenced-inference count, and category counts. Validity requires zero invalid refs and zero unreferenced inferences. No future/oracle/private/answer-label field or hidden condition label is permitted.

## Capture fairness and prompts

PGEN and PAUTO receive byte-identical snapshots and use the same model, provider, project/location, generation configuration, output budget, structured-output mode, transport, timeout, retry policy, pacing, item capacity, and one-response-wins policy. Their instructions differ only as required by their output roles. Prompts contain no future change, post-change consequence, oracle answer, truth field, dev-002/d3 mention, or historical performance.

## Capture-interface sanity

Sanity is a separate experiment with its own version, manifest, directory, plan/hash, and fresh calls. It has no downstream phase and no utility scoring.

- S1: lexicographically lowest `(scenario_id, decision_id)` among valid snapshots.
- S2: among remaining snapshots, maximize `len(knowledge_before) + len(strictly earlier transmissions) + len(strictly earlier prior decisions)`; tie-break by scenario then decision ID.
- Schedule: S1 PGEN, S1 PAUTO, S2 PAUTO, S2 PGEN.
- Exactly four scientific observations.

PASS requires 4 planned, 4 terminal, 4 model responses, 4 valid payloads, zero provider failures, and no abort. Invalid/model-output or terminal provider failures persist and make PASS impossible but do not skip later frozen positions. Operator/system interruption aborts the remainder. Sanity artifacts cannot populate full capture.

## Full capture phase

The full capture phase contains 72 fresh observations: 36 PGEN and 36 PAUTO. Snapshots are ordered by scenario then decision ID. Odd snapshot indexes run PGEN then PAUTO; even indexes run PAUTO then PGEN, yielding 18/18 first-order balance.

All 72 capture slots must terminate before downstream can begin. `downstream_eligible` requires 72 responses, 72 valid canonical artifacts, zero provider failures/invalids, no abort, and exactly one PGEN and PAUTO artifact per snapshot. Raw responses, canonical payloads/hashes, validation, lifecycle, and model/config metadata persist separately. Downstream consumes only canonical validated payloads. No missing slot is filled, regenerated, recovered, or substituted.

## Downstream construction

For every condition the common post-change base is exactly `candidate_view(scenario, "implicit")` with only top-level `/discovery_condition` removed. No other normalization or ignored diff path exists. PREPARE proves byte identity across conditions for all 12 scenarios.

Every condition receives the same outer wrapper, containing exactly:

```text
DecisionContextBundle { decision_records: [...] }
```

- P0: empty records.
- PGEN: three frozen canonical GenericPreChangeCapture payloads.
- PAUTO: three frozen canonical DecisionPremiseRecords.
- PORACLE: three records containing exactly `{target_decision_id, premises}`, where premises are that decision’s exact benchmark assumptions without paraphrase or manual classification.

Records use canonical decision order: `made_at` ascending, then `decision_id`. Decision associations must be exact. Assumptions cannot be merged across decisions. PORACLE receives neither `evidence_available` nor full structured view and is a privileged informational ceiling, not a realizable mechanism. PAUTO is not compared to PORACLE with text similarity.

No model-visible treatment label, oracle flag, condition ID, or equivalent is permitted. All four use the same BASE_TASK_PROMPT/template, Discovery schema/parser/evaluator/scoring, model/config, transport, timeout, retry/pacing, and fresh-call policy. Only the bundle contents differ.

## Downstream plan

Exactly 48 observations: 12 scenarios × P0/PGEN/PAUTO/PORACLE × one repetition. Use the Latin square:

| Scenario row | Position 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| dev-001/005/009 | P0 | PGEN | PAUTO | PORACLE |
| dev-002/006/010 | PGEN | PAUTO | PORACLE | P0 |
| dev-003/007/011 | PAUTO | PORACLE | P0 | PGEN |
| dev-004/008/012 | PORACLE | P0 | PGEN | PAUTO |

Each condition occupies every position exactly three times.

## Failure semantics and phase separation

Provider pre-response failures are infrastructure; invalid returned responses are model/output behavior; interruption is aborted. The first response wins. There is no retry after a response, best-of-N, repair, replacement, hidden recovery, extra slot, or automatic rerun. Shared audited transport is reused unchanged, including HTTP 499 handling.

Sanity, full capture, and downstream attempt their complete schedules unless interrupted. Failure/invalidity does not skip later precommitted positions. Provider-capable phases require separate explicit commands; capture completion may mark downstream eligible but cannot start it automatically.

## PREPARE/EXECUTE integrity

PREPARE is offline and makes zero provider calls. It freezes protocol/implementation identities, plans and exact hashes, snapshot/structural proofs and hashes, prompt/schema hashes, model/provider/config, transport, fresh-call flags, phase rules, and eligibility.

Before adapter/client construction or scientific lifecycle creation, every EXECUTE verifies current protocol SHA, current HEAD, clean tracked worktree (untracked outputs allowed), exact plan bytes/hash and semantic validity, exact proof bytes/hash and PASS contents, current prompt/payload-schema hashes, model/provider/config identity, lifecycle-specific manifest type/version, and `execute_eligible`. It never regenerates or repairs PREPARE.

Downstream additionally verifies all 72 capture slots are terminal, responded, valid, uniquely complete, canonical bytes match their hashes, provider/invalid counts are zero, and `downstream_eligible` is true. Sanity/full/downstream manifests and artifacts cannot substitute for one another.

## Offline analysis

Analysis requires exactly 48 terminal valid/evaluable downstream observations, zero invalid/provider failures/abort, 12 per condition, and unique scenario × condition × repetition coverage. It uses DEV-only truth and never calls a provider.

Primary contrasts are P0→PORACLE, P0→PGEN, PGEN→PAUTO, P0→PAUTO, and PAUTO→PORACLE. Report frozen TP/TN/FP/FN, precision/recall/F1, still-justified errors, material false negatives, unique binary failures, and secondary dependency-strength diagnostics. Strength alone cannot establish success. Capture diagnostics are descriptive and unweighted.

An operational unit is `(scenario_id, decision_id, field)` for `materially_dependent` or `still_justified`. Corrections are units wrong in control and right in treatment; regressions are units right in control and wrong in treatment. Contemporary oracle advantage requires nonempty P0→PORACLE corrections and no regressions, subject to existing stronger safety rules.

Classification precedence:

1. No usable PORACLE advantage: `NO CONTEMPORARY PREMISE ADVANTAGE`.
2. Any PAUTO operational/safety regression: `AUTO HARMFUL`.
3. PAUTO recovers all oracle corrections: `AUTO GENERIC-EQUIVALENT` if PGEN also cleanly recovers all; otherwise `AUTO SUFFICIENT`.
4. PAUTO recovers some but not all: `AUTO PARTIAL`.
5. Only secondary strength improvement: `AUTO STRUCTURAL-ONLY`.
6. Otherwise: `AMBIGUOUS`.

Historical Pattern B cannot substitute for contemporary P0→PORACLE. Operational regressions prevent clean reproduction. dev-002/d3 is a forensic endpoint only and does not affect classification. Report whether PAUTO produced a source-backed premise capable of representing the backlog-type rationale, without treating absence automatically as interface failure. No confirmation or elicitation workflow follows automatically.

## Required CLI lifecycles

The implementation provides distinct commands for sanity PREPARE/EXECUTE, full PREPARE, full capture EXECUTE, downstream EXECUTE, and offline ANALYZE. Full PREPARE capability is implemented now but is not run in this task. Any provider execution or production analysis requires separate authorization.
