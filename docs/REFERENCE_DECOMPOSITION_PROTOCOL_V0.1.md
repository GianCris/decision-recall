# Decision Recall Reference Decomposition Protocol v0.1

Status: **frozen diagnostic protocol**. This protocol decomposes the full structured decision-context reference into evidence-link and assumption components. It is not a mechanism tournament, a confirmation experiment, a Reconstruction retry, or product architecture.

## 1. Purpose and claim boundary

Round B v0.2 showed no surviving reconstruction-family candidate. Its full structured reference retained a DEV advantage, but that reference exposed both `decisions[].evidence_available` and `decisions[].assumptions`. This experiment determines descriptively whether fresh contemporary behavior associates that advantage with evidence links, assumptions, their interaction, redundant routes, or no clean decomposition.

All conclusions are DEV-only diagnostic evidence. They do not establish generalization, causal model internals, architectural necessity, production readiness, or sealed-holdout performance. No confirmation or subsequent mechanism is authorized automatically.

## 2. Frozen conditions

All conditions are privileged diagnostic references, not candidate mechanisms.

- **R0 — implicit reference control:** exact frozen implicit discovery view; neither `evidence_available` nor `assumptions` is present.
- **RE — evidence-links-only reference:** deep copy of R0, augmented only with each matching structured decision's exact `evidence_available` value; `assumptions` remains absent.
- **RA — assumptions-only reference:** deep copy of R0, augmented only with each matching structured decision's exact `assumptions` value; `evidence_available` remains absent.
- **REA — full structured decision-context reference:** exact frozen structured discovery view, containing both fields.

REA is conceptually equivalent to the former RR1 treatment, but this experiment uses fresh calls and the explicit name “full structured decision-context reference (evidence links + assumptions).”

## 3. Mechanical view construction

For each scenario, construct R0 with `candidate_view(scenario, phase="discovery", condition="implicit")` and REA with `candidate_view(..., condition="structured")`. Match decisions by exact ID. RE copies only `evidence_available` from REA into a deep copy of R0. RA copies only `assumptions`. Values are copied exactly: no paraphrase, inference, repair, imputation, semantic reordering, or additional field is permitted. Missing, unknown, duplicate, or misaligned decision identities block construction.

## 4. Structural-difference hard gate

PREPARE must compute exact recursive field/path differences for all twelve DEV scenarios and prove:

- RE − R0 = `evidence_available` paths only;
- RA − R0 = `assumptions` paths only;
- REA − RE = `assumptions` paths only;
- REA − RA = `evidence_available` paths only.

No unexpected top-level, decision, order, or content difference is allowed. Each scenario proof records canonical R0/RE/RA/REA hashes and exact diff paths. Any violation produces `PREPARE BLOCKED — REFERENCE VIEW IDENTITY FAILURE` and `execute_eligible = false`.

## 5. Dataset and sealed-holdout exclusion

Use exactly `dev-001` through `dev-012`, loaded only through `load_scenarios("dev")` or an equivalent already-frozen DEV-only path. The broad scenario loader is forbidden. Sealed holdout data must not be opened, read, parsed, hashed, Git-read, enumerated, or used indirectly by PREPARE, EXECUTE, or analysis.

## 6. Scientific equality

Every condition uses the identical frozen `BASE_TASK_PROMPT`, Discovery response schema, parser, evaluator, scoring semantics, model, provider, project, location, generation configuration, transport, timeout, retry/backoff behavior, and task framing. The only scientific treatment is candidate-visible information. There is no Stage 1, DSR, Reconstruction, Survivability, Alternative Support, anchor, hidden control, or multi-pass mechanism. Each scenario-condition pair produces exactly one model call when execution is separately authorized.

## 7. Size and exact schedule

There are 12 DEV scenarios, four conditions, and one repetition: exactly 48 fresh scientific observations. The frozen four-position Latin square is:

| Scenario row | Position 1 | Position 2 | Position 3 | Position 4 |
|---|---|---|---|---|
| dev-001, dev-005, dev-009 | R0 | RE | RA | REA |
| dev-002, dev-006, dev-010 | RE | RA | REA | R0 |
| dev-003, dev-007, dev-011 | RA | REA | R0 | RE |
| dev-004, dev-008, dev-012 | REA | R0 | RE | RA |

Every scenario contains every condition once. Each condition has 12 slots and occupies each temporal position exactly three times. The schedule is deterministic and must not be randomized.

## 8. Fresh-call and reuse rule

All 48 observations must be fresh and contemporary. Historical baseline, Round B v0.1/v0.2, recovery, sanity, and other responses or artifacts may not fill or replace a slot. `fresh_calls_required = true`; `historical_response_reuse_authorized = false`.

## 9. Frozen diagnostic contrasts

Primary contrasts are exactly:

- R0 → RE: incremental effect of serving evidence links;
- R0 → RA: incremental effect of serving assumptions;
- RE → REA: incremental effect of assumptions when evidence links are served;
- RA → REA: incremental effect of evidence links when assumptions are served.

Report ordinary per-condition metrics for R0, RE, RA, and REA. No candidate-mechanism ranking or advancement threshold is defined.

## 10. Metrics and operational advantage

Reuse frozen Discovery definitions for TP, TN, FP, FN, precision, recall, F1, still-justified errors, dependency-strength errors, material false negatives, and unique binary failures. For decomposition, operational corrections concern `materially_dependent` and `still_justified`; operational regressions, including material false negatives, count against reproduction. Dependency-strength changes are secondary and cannot independently establish reproduction.

The contemporary structured-reference advantage is defined only by fresh R0 → REA behavior. Historical RB0/RR1 observations cannot manufacture a decomposition result.

## 11. Frozen pattern interpretation

A single-factor condition reproduces the contemporary structured-reference advantage only if its operational behavior accounts for the R0 → REA improvement without a frozen operational regression. Partial or mixed evidence that does not meet this rule is Pattern E.

- **Pattern A — Evidence-link dominant:** RE reproduces the advantage; RA does not.
- **Pattern B — Assumption dominant:** RA reproduces the advantage; RE does not.
- **Pattern C — Interaction:** neither RE nor RA alone reproduces it; REA does.
- **Pattern D — Redundant routes:** both RE and RA independently reproduce it.
- **Pattern E — No clean decomposition:** A–D do not apply.

Critical gate: if fresh REA has no operational advantage over fresh R0, report exactly `PATTERN E — NO CLEAN DECOMPOSITION / CONTEMPORARY STRUCTURED-REFERENCE ADVANTAGE NOT REPRODUCED`. Do not substitute historical RR1 results.

## 12. Predeclared forensic endpoint

`dev-002/d3` is a predeclared endpoint. Analysis reports its four contemporary predictions but must analyze every DEV decision and cannot use it as the sole global basis or tune a condition after observing it.

## 13. Observability boundary

Analysis may use model-visible views, persisted structured outputs, and DEV private truth offline for correctness. Private truth is diagnostic ground truth only and must not be described as condition-visible unless independently present. No hidden chain-of-thought or internal reasoning claim is permitted.

## 14. PREPARE and EXECUTE

The CLI must separate `--prepare` and `--execute`. PREPARE makes zero provider calls, requires a new empty output directory, builds the frozen plan and structural proof, and persists a manifest. EXECUTE requires a compatible prepared manifest and is not authorized by this protocol-freeze/implementation task.

PREPARE freezes at least: experiment and manifest versions; protocol commit and SHA; implementation SHA; exact DEV IDs; the 48-slot plan and SHA; condition definitions; per-scenario view hashes and exact diff proofs; prompt hash; Discovery schema version/SHA; model/provider/project/location; generation configuration; transport; contrasts; forensic endpoint; sealed-holdout exclusion; fresh-call/reuse policy; and execute eligibility.

## 15. Transport and failure semantics

Reuse the audited shared delivery primitive unchanged: SDK attempts 1, harness maximum attempts 4, existing retryable statuses, fixed 5/10/20-second backoffs, no jitter, 120-second timeout, first model response wins, no retry after a response, sequential execution, and frozen inter-call pacing. HTTP 499 remains nonretryable.

A terminal provider failure is infrastructure failure and creates no prediction. An invalid returned response is model/output behavior and is preserved without repair, regeneration, best-of-N selection, or retry. No automatic experiment repetition or recovery is authorized; any recovery requires a separate protocol.

## 16. Analysis and no-confirmation boundary

Analysis applies only after a separately authorized execution. It uses the frozen metrics, four primary contrasts, pattern gate, and forensic endpoint above. It must identify model-visible information separately from diagnostic truth and must not create new thresholds, mechanism rankings, or confirmation calls. No confirmation workflow exists in v0.1.

## 17. Prohibited extensions

This protocol does not authorize Mechanism X, DSR changes, Round C, rationale/provenance capture mechanisms, memory, Fleet, Recovery architecture, product integration, sealed-holdout access, or any provider call during implementation/PREPARE.
