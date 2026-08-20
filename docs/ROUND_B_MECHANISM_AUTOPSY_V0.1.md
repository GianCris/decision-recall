# Decision Recall Round B v0.2 Mechanism Autopsy

Status: **DEV forensic diagnosis only**. This document uses persisted Round B v0.2 artifacts, the qualified recovered screening view, and DEV-only benchmark data. It is not a new experiment, a causal claim about hidden model reasoning, or a mechanism design.

## 1. Executive diagnosis

No reconstruction-family candidate survived Round B v0.2. RC0, RB1, RB2, and RB3 were all `FAIL / DO NOT ADVANCE`. RR1 was `PROMISING`, but RR1 is the structured-provenance reference condition, not a reconstruction-family mechanism.

The observed family-level failure is best classified as a **mixed representation and reconstruction bottleneck**, with a downstream **utilization/intervention limitation** that cannot be cleanly separated from the missing input. The decisive operational failure, `dev-002/d3`, is principally a **representation/reconstruction failure**:

- RR1 saw the explicit decision evidence set `k1, k2` and the structured assumption “Backlog also requires night coverage.”
- implicit input exposed neither `evidence_available` nor `assumptions`.
- Reconstruction produced `d3 -> k1` with trace `t1`, omitting structured evidence reference `k2`.
- More importantly, DecisionSupportPayload has no field capable of preserving the structured assumption or an equivalent alternate justification.
- RB1, RB2, and RB3 therefore did not receive an artifact equivalent to RR1's structured input. Their persisted outputs retained the same incorrect operational result. This establishes an observed Stage-2/intervention failure relative to their actual inputs, but it does not show that they would have failed had the missing structured assumption been available.

The evidence does not reveal hidden reasoning. “Utilization failure” below means only that information present in the persisted model-visible input or DSR was not reflected correctly in the final structured prediction.

## 2. Correct interpretation of the screening

| Condition | Role | Frozen result |
|---|---|---|
| RC0 | neutral grounded-context control | `FAIL / DO NOT ADVANCE` |
| RB1 | reconstructed decision support | `FAIL / DO NOT ADVANCE` |
| RB2 | reconstruction plus Survivability instruction | `FAIL / DO NOT ADVANCE` |
| RB3 | reconstruction plus Survivability and Alternative Support instructions | `FAIL / DO NOT ADVANCE` |
| RR1 | structured-provenance reference | `PROMISING` |

`RB0 -> RR1 = PROMISING` shows that the frozen structured view contained useful information or enabled useful behavior. It does **not** mean a Decision Recall reconstruction mechanism survived. The reconstruction-family result is: **no candidate survived**.

## 3. RR1's actual structured-information advantage

The structured and implicit discovery views are produced by the same `candidate_view` contract. Implicit construction removes exactly two decision fields that remain visible to RR1:

| RR1-only field | Meaning in the frozen data | Classification | DSR equivalent |
|---|---|---|---|
| `decisions[].evidence_available[]` | stable knowledge IDs recorded as available when that decision was made | explicit structured provenance; decision-to-evidence linkage | approximate structural equivalent in `decision_connections[].candidate_knowledge_refs[]`; inferred rather than authoritative and not always complete |
| `decisions[].assumptions[]` | structured textual assumptions/context recorded for the decision | structured assumption/context | **none**; DecisionSupportPayload permits no assumption/context text |

All other scenario fields—including decisions, knowledge statements, change, transmissions, timestamps, agents, and world context—are common to both views. The DSR adds inferred `change_alignment` and `basis_trace_refs`, but those are not RR1-only fields:

- `change_alignment.change_ref` repeats the visible change ID.
- `candidate_prior_knowledge_refs` is an inferred change-to-knowledge candidate set; RR1 has no explicit field with which it can be compared mechanically.
- `basis_trace_refs` links decisions to visible transmission IDs; RR1 sees transmissions but has no explicit decision-to-transmission linkage field.

Private DEV labels were used only to assess correctness. They were not model-visible and are not treated as completing either input.

## 4. RR1-to-DSR mapping

| Structured property | Mechanically comparable DSR property | Diagnostic result |
|---|---|---|
| decision ID | `decision_connections[].decision_id` | one connection existed for every visible decision by contract |
| `evidence_available` knowledge IDs | `candidate_knowledge_refs` | comparable as reference sets; 30/42 structured edges recovered, 12 missing, 0 extra |
| structured assumptions | none | not representable in the frozen DSR |
| visible change ID | `change_alignment.change_ref` | 12/12 exact ID matches (`c1`) |
| explicit change-to-prior-knowledge link | none in RR1 | no legitimate reference-set comparison |
| explicit decision-to-transmission link | none in RR1 | no legitimate reference-set comparison for `basis_trace_refs` |

The 30/42 edge match is descriptive only: 71.4% structured-edge coverage and 100% precision against `evidence_available`, with exact decision-level reference sets for 27/36 decisions (75%). These are autopsy diagnostics, not new screening gates.

## 5. Reconstruction diagnostics across DEV

The missing-reference discrepancy occurred in **nine decisions across nine of twelve scenarios**, not only at the focal failure:

| Unit | Structured references missing from DSR |
|---|---|
| dev-001/d3 | k1, k2 |
| dev-002/d3 | k2 |
| dev-003/d3 | k1, k2 |
| dev-005/d3 | k1 |
| dev-006/d2 | k1 |
| dev-007/d3 | k1, k2 |
| dev-008/d3 | k1 |
| dev-010/d2 | k1 |
| dev-012/d3 | k1 |

No DSR decision connection added a knowledge reference absent from the corresponding structured `evidence_available` set. Eight of the nine decisions with incomplete reconstructed sets had an RB1 dependency-strength error; the only RB1 binary/still-justified error was `dev-002/d3`. Among the 27 exact-set decisions, RB1 still had six strength errors. Thus incomplete edge recovery is associated with most strength errors in this DEV set, but it is neither necessary nor sufficient to explain all strength errors.

Every one of the 36 structured decisions across all 12 scenarios also contained at least one `assumptions` string. None can be represented in the DSR. This representation gap is universal in DEV, although only one decision produced the remaining operational binary/survivability error. Correct final predictions elsewhere do not establish that the missing assumptions were unimportant; they show only that the final structured outputs happened to be correct on those fields.

## 6. Focal forensic comparison: dev-002/d3

Only evidence needed for diagnosis is reproduced here.

### Model-visible implicit evidence

- Prior knowledge `k1`: raw forecast shows 10,000 units.
- Prior knowledge `k2`: line 2 service is due by Friday.
- Change `c1`: duplicated region removed; demand is 6,000 units.
- Decision `d3`: keep the night shift.
- Transmission `t1`: regional demand totals about 10,000 units.
- Transmission `t2`: the volume plan requires the long run and night coverage.
- The implicit decision record contains no `evidence_available` and no `assumptions`.

### RR1 model-visible structured additions

- `d3.evidence_available = [k1, k2]`.
- `d3.assumptions = ["Backlog also requires night coverage"]`.

The assumption is the only visible statement explicitly presenting an independent reason for retaining night coverage after the forecast correction.

### Canonical RC0 artifact

RC0 selected the complete visible strings for the change, all three decisions, both prior-knowledge statements, and both transmissions. It did not—and by protocol could not—add the RR1-only structured assumption or decision-specific support mapping.

### Canonical Reconstruction DSR

- `change_alignment = {change_ref: c1, candidate_prior_knowledge_refs: [k1]}`.
- `d3.candidate_knowledge_refs = [k1]`.
- `d3.basis_trace_refs = [t1]`.

The DSR reconstructed a forecast-related path to `d3`, but omitted structured evidence reference `k2`, omitted trace `t2`, and had no schema location for the structured backlog assumption.

### Predictions and diagnostic truth

| Condition | Materially dependent | Strength | Still justified |
|---|---:|---|---:|
| RB0 | true | material | false |
| RC0 | true | material | false |
| RB1 | true | material | false |
| RB2 | true | critical | false |
| RB3 | true | material | false |
| RR1 | false | supporting | true |
| **DEV diagnostic truth** | **false** | **supporting** | **true** |

The truth row is private diagnostic ground truth, not information supplied to any condition.

## 7. Information-loss localization

1. **Did RR1 contain an important fact absent from implicit?** Yes. It contained an explicit `d3 -> [k1, k2]` evidence set and the backlog assumption. The latter directly states an independent justification.
2. **Did Reconstruction recover an equivalent?** No. It recovered only `d3 -> k1` plus `t1`. The DSR cannot encode the assumption at all.
3. **Primary localization:** mixed reconstruction/representation failure, dominated at the focal unit by the unrepresentable structured assumption and incomplete reference set.
4. **Did RB1 make the operational error anyway?** Yes, but its DSR was not equivalent to RR1's input. The persisted record supports an observed utilization-level failure on the information it did receive, not a conclusion about hidden reasoning or behavior under the missing assumption.
5. **Did RB2 have all information needed for Survivability?** Not relative to RR1: the independent backlog assumption was absent. RB2 changed only strength from material to critical and retained both incorrect operational fields.
6. **Did RB3 have all information needed for Alternative Support?** Not relative to RR1. It saw the implicit text and incomplete DSR, but not the explicit backlog assumption. RB3 reverted strength to material and retained both incorrect operational fields.
7. **Intervention conclusion:** Survivability and Alternative Support did not operationalize a correction from their actual persisted inputs. Because the key RR1-only assumption was absent, this is confounded with the upstream representation gap; the artifacts cannot establish how either instruction would behave with equivalent information.

## 8. Dependency-strength movement

The aggregate movement was RC0 15 errors, RB1/RB2/RB3 14, and RR1 9.

Exactly one decision changed strength between RC0 and RB1: `dev-006/d3` moved from `independent` to the correct `supporting`. Its materially-dependent and still-justified predictions did not change. This accounts for 15 -> 14 and is diagnostic evidence of partial information transfer, not screening success.

RR1 corrected five additional RB1 strength errors:

| Unit | DEV truth | RB1 | RR1 |
|---|---|---|---|
| dev-001/d3 | supporting | independent | supporting |
| dev-002/d3 | supporting | material | supporting |
| dev-004/d3 | material | critical | material |
| dev-007/d3 | supporting | independent | supporting |
| dev-008/d3 | supporting | independent | supporting |

Four of these five units also had incomplete DSR evidence sets; `dev-004/d3` did not. This again supports a mixed diagnosis: incomplete reconstruction explains part, while loss of structured assumptions/context and downstream use remain relevant beyond edge matching alone.

## 9. RB1 -> RB2 -> RB3 intervention autopsy

Across 11/12 scenarios, RB1, RB2, and RB3 parsed responses were value-identical. The sole differences were for `dev-002/d3` strength:

- RB1: material.
- RB2: critical.
- RB3: material.

Material dependence remained `true` and still justified remained `false` in all three. Consequently Survivability and Alternative Support changed no operational prediction, resolved no error, and produced no aggregate metric improvement. Their aggregate strength-error totals also remained 14 because both alternate focal strengths were wrong.

The persisted evidence is insufficient to distinguish internal failure to follow the intervention from inability to act without the missing structured assumption. No chain-of-thought or free-text rationale exists.

## 10. Recurrence and bottleneck classification

The focal missing-edge pattern recurs across nine scenarios. Missing structured assumptions recur across all twelve. However, the remaining binary/still-justified error occurs only at `dev-002/d3`; elsewhere the same structural gaps co-occur with correct operational outputs and, frequently, strength errors.

Final classification: **E. MIXED BOTTLENECK**.

- **Primary: B. Representation bottleneck.** The DSR cannot express RR1's structured assumptions, including the focal independent backlog justification.
- **Co-primary: A. Reconstruction bottleneck.** Stage 1 recovered only 30/42 mechanically comparable decision-evidence edges and omitted `k2` for the focal decision.
- **Secondary: C/D. Utilization/intervention bottleneck, qualified.** RB1/RB2/RB3 did not turn their available implicit text plus DSR into the correct focal output; RB2/RB3 changed only strength. Because their inputs lacked an RR1-equivalent assumption, the evidence cannot isolate downstream utilization from upstream information loss.

## 11. Limitations

- This is descriptive evidence from 12 DEV scenarios, not generalization evidence.
- The recovered view contains one out-of-original-order infrastructure-recovered RC0 observation.
- `evidence_available` and `candidate_knowledge_refs` are comparable reference sets, but the latter are explicitly candidates and need not carry the same epistemic force.
- RR1 provides structured assumptions, but the benchmark does not separately identify which assumption was causally used by the model.
- Correct output does not prove correct hidden reasoning; incorrect output does not reveal its internal cause.
- No sealed-holdout data was used.

## 12. Questions for the next design phase

The next externally authorized mechanism-design phase must decide, without treating this report as a design prescription:

1. Which parts of structured decision context must remain representable when exact provenance is unavailable?
2. How should candidate relations be distinguished from decision assumptions or independent justification without leaking oracle materiality?
3. What observable evidence is sufficient to evaluate whether an inferred connection is usable rather than merely related?
4. How can a downstream stage demonstrate that it used available reconstructed information, given the frozen structured-output-only observability boundary?
5. What separately precommitted test can distinguish upstream information loss from downstream intervention failure?
6. How should the structured-reference advantage be confirmed without treating RR1 as a candidate mechanism or using sealed holdout for development?

These questions remain open. This autopsy does not define Mechanism X, Round C, a revised DSR, or a new prompt.
