# Decision Recall Mechanism Tournament v0.1

## Purpose

The central research question is:

> Can an implicit-only system determine which decisions actually lose sufficient support when knowledge changes, while reducing false reopenings without creating missed recoveries?

The tournament does not presume that Decision Recall already works. It tests
whether specialized architecture is necessary and, if so, what minimum
capability earns a place in that architecture. Round A candidates are minimal
reasoning probes, not proven Decision Recall mechanisms. If a minimal one-call
probe addresses the observed DEV issue without regression, that is evidence
against prematurely building a larger architecture.

This protocol favors reducing false reopenings without creating missed
recoveries.

## Empirical motivation and claim boundary

The frozen official DEV evidence establishes the following context:

- A strong general Gemini baseline under implicit input is already strong.
- Historical B0 recall was `1.0`.
- B0's observed binary error was false-positive/over-reopening behavior: one
  unique scenario-decision unit reproduced across three repetitions.
- Historical B1 with structured provenance removed that binary failure on DEV.
- This is not generalization evidence.
- Dependency-strength accuracy is secondary because most observed strength
  errors did not cross the operational material/non-material boundary.

Round A is developmental and descriptive. It may produce `PROMISING`,
`AMBIGUOUS / NEEDS CONFIRMATION`,
`AMBIGUOUS / INSUFFICIENT CONTEMPORARY SIGNAL`, `FAIL / DO NOT ADVANCE`, or
`FAIL / SAFETY REGRESSION`. It may never produce `PROVEN`, `GENERALIZED`, or
`FINAL WINNER`.

The private benchmark ground truth remains the oracle. R1 and historical B1
are not oracles, theoretical ceilings, or guaranteed upper bounds.

## Frozen references and candidates

### M0 — Fresh implicit control

- Purpose: contemporary control equivalent to frozen B0.
- Input: the same implicit candidate view used by B0.
- Prompt: exactly the existing frozen `BASE_TASK_PROMPT`.
- No additional reasoning instruction.

M0 is rerun contemporaneously so temporal, provider, or model drift is not
confused with probe effects. Historical B0 v0.4 remains historical evidence
and is not replaced.

### R1 — Fresh structured-provenance reference

- Purpose: measure contemporaneously how much explicit structured provenance
  helps the same general model.
- Input: the same structured candidate view used by frozen B1.
- Prompt: exactly the frozen `BASE_TASK_PROMPT` used by M0.
- No probe instruction.

R1 is a structured-provenance reference. A future implicit mechanism may
legitimately outperform it.

### M1 — Reliance discrimination probe

- Input: exactly the same implicit candidate view as M0.
- Base prompt: exactly the frozen `BASE_TASK_PROMPT`.
- One model call.
- No explicit lineage, structured provenance, hidden assumptions, private
  labels, replay, or multiple calls.

Append exactly:

```text
RELIANCE DISCRIMINATION:
For each decision, evaluate whether the changed premise was necessary to
support the decision at the time it was made. Consider the counterfactual in
which that premise had not been available while all other information that was
available at decision time remained unchanged.

Treat relevance, temporal proximity, participation in the decision process,
or ordinary support as insufficient by themselves to establish material
dependence.
```

### M2 — Decision survivability probe

- Input: exactly the same implicit candidate view as M0.
- Base prompt: exactly the frozen `BASE_TASK_PROMPT`.
- One model call.
- No structured provenance, persistent support graph, replay, or multiple
  calls.

Append exactly:

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

### M3 — Alternative-support ablation

M3 equals M2 plus one and only one additional intervention. It receives the
same implicit candidate view, uses exactly the frozen `BASE_TASK_PROMPT`, first
appends the exact M2 block above, and then appends exactly:

```text
ALTERNATIVE SUPPORT CHECK:
Before concluding that the counterfactual decision lacks sufficient support,
explicitly search the candidate-visible information for an independent
remaining reason or evidence source that would be sufficient to justify the
same decision without relying on the changed premise.
```

`M3 - M2` is intended to isolate the added value of explicitly searching for
independent alternative support. M3 receives no other instruction and remains
one model call.

## Prompt fairness contract

The frozen `BASE_TASK_PROMPT` remains unchanged:

```text
M0 = BASE_TASK_PROMPT
R1 = BASE_TASK_PROMPT with structured candidate input
M1 = BASE_TASK_PROMPT + RELIANCE_DISCRIMINATION_INSTRUCTION
M2 = BASE_TASK_PROMPT + SURVIVABILITY_INSTRUCTION
M3 = BASE_TASK_PROMPT + SURVIVABILITY_INSTRUCTION + ALTERNATIVE_SUPPORT_INSTRUCTION
```

No candidate receives selective examples, extra scenario information, private
oracle information, a different output schema, different model settings, or a
different evaluator. The probe strings must be versioned and hashed before
execution and may not be rewritten or optimized.

Round A comparable conditions use the same provider, Gemini model/version,
provider location, structured-output mechanism, Discovery response schema,
generation policy, timeout policy, delivery/retry policy, dataset, scenario
ordering policy, output budget, and evaluation semantics. The selected model
remains `gemini-3.7-flash` unless an external protocol revision changes it
before execution.

M0, M1, M2, and M3 receive implicit candidate views. R1 receives a structured
candidate view; this is R1's intended information difference.

## Round A1 — Minimal-probe screening

A1 contains:

- 12 frozen DEV scenarios;
- five conditions: M0, R1, M1, M2, M3;
- exactly one repetition;
- 60 scientific model observations.

A1 is development screening, not final evaluation, generalization evidence,
or sealed-holdout evidence.

### Execution ordering

Conditions are contemporaneous and interleaved. For scenario index `i =
1..12`, rotate the base order `[M0, R1, M1, M2, M3]` so that the first
condition is selected by `(i - 1) mod 5`, followed by the remaining conditions
cyclically.

The schedule must be generated, reported, and frozen before any provider call.
It must report condition-position counts and the unavoidable minor imbalance
caused by 12 not being divisible by five. It may not change in response to
model performance. Execution must not group all observations for one
condition together.

The primary independent DEV unit is `scenario_id + decision_id`. Repetitions
measure stability and do not multiply independent evidence.

## Metric hierarchy

No new official Discovery metric is introduced. Existing frozen evaluation
outputs are interpreted in this order:

1. Material false negatives/recall: hard safety and regression gate.
2. Material false positives: the currently observed opportunity.
3. `still_justified`: hard regression guard.
4. Unique scenario-decision failures.
5. F1, precision, and recall aggregates.
6. Dependency strength: diagnostic only; improvement here alone cannot
   qualify a probe.
7. Cost: model calls, tokens, and latency.

Candidates are compared against frozen ground truth and contemporary M0. A
probe may not win by becoming globally conservative, reducing false positives
at the expense of false negatives, preserving decisions that genuinely need
reopening, or worsening `still_justified` decisions that M0 handled correctly.

## A1 advancement and regression rules

Operational regressions are counted at the unique `scenario_id + decision_id`
level. Multiple affected fields on one unit count as one regression unit, but
every affected field remains reported. Material false negatives are always
explicitly marked as severe safety-regression signals.

### Promising

M1, M2, or M3 is `PROMISING` when it:

1. improves contemporary M0 through at least one of fewer material false
   positives, fewer unique binary scenario-decision failures, or fewer
   `still_justified` failures; and
2. introduces no observed operational regression in material false negatives,
   previously correct material/non-material classifications, or
   `still_justified` predictions.

Correcting only the known `dev-002/d3` failure without observed regression is
sufficient for `PROMISING` and A2 confirmation, but is not generalization
evidence.

### Ambiguous / needs confirmation

A probe is `AMBIGUOUS / NEEDS CONFIRMATION` if A1 shows at least one
operational improvement and exactly one new unique scenario-decision
operational regression. It may advance to A2 to test whether both observations
reproduce. More than one new regression unit is a clear failure unless an
external protocol revision says otherwise. Aggregate F1 cannot average away a
regression.

### Ambiguous / insufficient contemporary signal

If contemporary M0 has no operational binary or `still_justified` failure,
lack of improvement alone does not fail a probe. A probe with no new
operational regression receives
`AMBIGUOUS / INSUFFICIENT CONTEMPORARY SIGNAL` and may advance to A2. This rule
takes precedence over the no-improvement failure rule.

### Fail / do not advance

A probe fails A1 when any of these applies:

- M0 presents an operational binary or `still_justified` opportunity, but the
  probe improves none of those units.
- The probe introduces more than one unique operational regression unit.
- The probe introduces at least one operational regression without an
  operational improvement.
- Its only observed improvement is dependency strength.

A probe with exactly one regression unit and at least one improvement is
classified as ambiguous rather than automatically failed. The insufficient
contemporary-signal rule remains controlling when M0 presents no relevant
failure opportunity.

### Final hard regression gate

A2, not one A1 observation, confirms stable regression judgments. No candidate
survives Round A if A2 reproducibly introduces material false negatives on
scenario-decision units that contemporary M0 handles correctly. Reducing false
positives by sacrificing true material dependencies is unacceptable.

## Round A2 — Confirmation

Only probes surviving A1 may enter A2. A2 adds repetitions 2 and 3; the A1
observation remains repetition 1, yielding three total DEV repetitions for a
survivor.

Fresh M0 and R1 controls must accompany A2. Historical control runs cannot
replace contemporary controls. The exact matrix depends on A1 survivors, but
the selection rule above is frozen. A deterministic A2 schedule must be
generated and frozen before execution, and prompts cannot change between A1
and A2.

Historical B1 remains historical evidence. Fresh R1 permits a descriptive
contemporary M0-to-R1 comparison. R1 is not an upper bound. No formal
percentage-of-gap-recovered claim is allowed unless a later protocol defines a
metric using comparable contemporary endpoints.

## Deferred candidates and authorization boundaries

### M4 — Minimal composition

M4 is blocked during initial Round A and must not be implemented. It may be
considered only after at least two probes show distinct, complementary benefits
that cannot be explained by one subsuming the other. Any future M4 must be the
minimum composition justified by evidence.

### MX — Open slot

`MX — DATA-DERIVED MECHANISM` is reserved but unpopulated and unimplemented.
It exists in case evidence reveals a better primitive than M1/M2/M3. It must
not be invented merely to add a candidate.

### Round B — Architectural mechanisms

Round B is unauthorized unless Round A shows that minimal one-call
interventions are insufficient or reveals a capability requiring explicit
architecture. Possible future evidence could concern distributed-support
reconstruction, persistent decision-support memory, multi-step verification,
counterfactual support representation, long-context retrieval, cross-agent
transformation, authority-aware tracking, or another evidence-justified
capability. These are examples, not preselected mechanisms. If a one-call
probe is sufficient, complexity must not be fabricated.

## Challenge and CADC boundary

Round A DEV results cannot establish generalization. Later experiments may
test promising probes under distributed evidence, longer context, transformed
information, multi-agent handoffs, persistent memory, partial visibility, or
authority boundaries. Controlled causal claims about those dimensions require
a separately authorized CADC-style experiment. CADC is not part of this
protocol implementation, and DEV must not be modified after results to
manufacture such conditions.

## Recovery boundary

Round A Discovery continues using the frozen material-dependence,
false-positive/false-negative, `still_justified`, and existing metric outputs.
It does not create an official Unnecessary Reopen Rate. Disruption and action
cost belong to a later Recovery evaluation of repairing the broken set while
preserving the surviving set. Recovery is not authorized here.

## Sealed-holdout boundary

The sealed final holdout is prohibited throughout probe development, A1, A2,
Round B development, challenge-set construction, CADC, Recovery, and
architecture tuning. It must not be accessed, enumerated, or used to evaluate
any probe. It remains reserved for final generalization evaluation.

## Fairness and capability hypothesis

The tournament must make Gemini strong, not artificially weak. M0 is a
competent general implicit baseline; R1 is a competent structured-provenance
reference; M1/M2/M3 differ only by their intended minimal instructions. No
probe receives hidden information unavailable to M0, a different model
quality, output schema, or evaluation rules.

The current working hypothesis is that Decision Recall should determine which
support was necessary for a decision to remain sufficiently justified when
knowledge changes, rather than merely remembering which evidence was connected
to it. This is a hypothesis, not a frozen architecture. The tournament may
weaken, refine, or reject it.

## Stop conditions

This document authorizes protocol documentation only. It does not authorize
implementing M1, M2, M3, M4, MX, a tournament runner, A1/A2 execution, Round B,
CADC, Recovery, Fleet, UI, deployment, benchmark changes, or provider calls.
Further work requires explicit external authorization.
