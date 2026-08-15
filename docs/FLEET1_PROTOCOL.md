# FLEET-1 Experimental Protocol — v0.1

## Purpose

Decision Recall is not considered technically demonstrated yet.

FLEET-1 exists to determine whether any mechanism can outperform strong and fair baselines at:

1. detecting cross-agent Material Decision Dependence;
2. reevaluating whether affected decisions remain justified after knowledge changes;
3. recovering more value with less unnecessary disruption.

The mechanism is not protected.

Semantic Decision Lineage, Decision Sensitivity, Decision Justification Trace, Reliance Load, counterfactual replay, structured provenance, multi-agent architecture and any other current hypothesis may be removed if experiments do not support them.

## Core rule

Do not change the definition of success after seeing the results.

Each experiment must define before execution:

* hypothesis;
* falsification condition;
* dataset;
* baselines;
* metrics;
* repetitions/seeds when applicable;
* PASS;
* PROMISING;
* FAIL.

## Discovery and Recovery must be evaluated separately

### Discovery

Question:

Can the system identify which decisions materially depended on changed knowledge?

Ground truth must distinguish dependency strength at least as:

* independent;
* supporting/non-material;
* materially dependent;
* critical dependence.

Downstream status must be represented separately from dependency strength:

* downstream: true;
* downstream: false.

A downstream decision may independently be supporting/non-material, materially dependent, or critically dependent.

Important negative cases must be included.

A system that marks almost everything as dependent is not successful.

### Recovery

All competing systems receive ground-truth dependency information.

This removes Discovery advantage.

Question:

Given the true affected decisions, can the system:

* correctly reevaluate them;
* preserve decisions that remain justified;
* repair recoverable consequences;
* minimize unnecessary disruption;
* act before recovery windows close;
* escalate only where human judgment adds value;
* verify the final world state?

## Strong baselines

Baselines must be competitive, not deliberately weak.

Initial baseline families:

1. Retrieval + strong reasoning
2. Explicit provenance + strong reasoning
3. Structured provenance + strong Gemini reasoning
4. Strong general Gemini with equivalent context, evidence and tools
5. Any additional strong alternative discovered during research

If a simple baseline wins, Decision Recall must adopt that result rather than protect a preferred mechanism.

## Mechanism tournament

Initial hypotheses may include:

* semantic dependency inference;
* structured justification;
* counterfactual replay;
* Decision Sensitivity;
* provenance + semantic inference;
* provenance + replay;
* justification + replay;
* combinations supported by evidence.

No mechanism has a guaranteed place in the final architecture.

## Ablations

When a candidate performs best, remove components one at a time and rerun evaluation.

Goal:

Identify the minimum mechanism responsible for the improvement.

Do not preserve components merely because they have names or were part of the original concept.

## Cross-Agent Dependency Complexity

Measure how performance changes as distributed complexity increases.

Run controlled sweeps first.

### Sweep A — Agent hops

Increase agent/dependency hops while holding other variables as constant as possible.

Example levels:

* 0
* 1
* 2
* 4

### Sweep B — Semantic distance

Example levels:

* literal reuse
* paraphrase
* semantic transformation
* conceptual consequence

### Sweep C — Information transformation

Example levels:

* copy
* summary
* compression
* inference

### Sweep D — Organizational boundaries

Example levels:

* shared visibility
* partial visibility
* department boundary
* different authority/permissions

After controlled sweeps, test combined adversarial cases.

## Discovery metrics

At minimum:

* precision
* recall
* F1
* false-positive dependence
* false-negative dependence
* multi-hop performance
* dependency-strength classification
* still-justified accuracy where applicable

Average scores must not hide failure in difficult strata.

## Recovery metrics

At minimum:

* repair correctness
* recovered value
* unnecessary disruption
* wrongful rollback
* recovery-window capture
* human escalation quality
* time to stable state
* final world-state correctness

More recovered value does not automatically mean success if it requires excessive disruption.

## Holdout

Development and holdout scenarios must be separated before meaningful tuning.

Holdout scenarios must not be rewritten to favor the mechanism after results are observed.

Cross-domain holdout should be used when feasible.

A likely pattern is:

* development domain: manufacturing or another concrete operational environment;
* holdout domain: software release or a materially different domain.

The final product claim remains horizontal unless evidence shows otherwise.

## FLEET-1 Gate

### FAIL

FLEET-1 fails if one or more of the following dominate the results:

* no mechanism consistently beats the best reasonable baseline;
* false positives make selective recovery impractical;
* advantage disappears on holdout;
* distributed complexity destroys the candidate as much as or more than the baseline;
* Recovery does not improve final world state;
* additional recovered value requires excessive unnecessary disruption;
* results depend on hand-crafted relations or near-perfect traces.

### PROMISING / CONTINUE

Use this state when:

* measurable advantage exists but is unstable;
* gains are limited to particular strata;
* gains are domain-dependent;
* results depend heavily on unusually complete justification traces;
* cross-agent advantage exists but is not yet reproducible;
* more controlled experiments are necessary.

### PASS

A PASS requires credible evidence that at least one mechanism provides reproducible value over the best reasonable baseline in the Decision Recall core:

* material dependence detection and/or
* correct reevaluation and/or
* recovery quality.

The advantage must survive holdout sufficiently to justify continued construction.

False positives and unnecessary disruption must remain controlled.

### STRONG PASS

A particularly strong FLEET-1 result occurs if the advantage remains stable or increases as cross-agent complexity increases.

This would provide experimental justification for building Decision Recall as a Fortified Enterprise Fleet rather than merely placing a normal agent system inside a Fleet architecture.

## After FLEET-1

Do not build enterprise Fleet infrastructure merely for checklist compliance before the core survives this gate.

After PASS, evaluate which Fortified Enterprise Fleet capabilities are structurally useful, including:

* agent identity;
* permissions;
* secure persistent state;
* observability;
* long-running execution;
* cross-agent delegation;
* enterprise tooling;
* recovery and verification controls.

Their inclusion must support the demonstrated behavior, not merely decorate the architecture.

## Methodological result labels

`COMPONENT PASS` and `FLEET-1 PASS` are distinct outcomes. A successful
component or pivot result must not be reported as a successful FLEET-1 result.

Near-perfect traces are a `FAIL` for the implicit-dependence claim. They may
still justify a component-level or pivot result for reevaluation or recovery,
but that result does not upgrade the trace to `FLEET-1 PASS`.
