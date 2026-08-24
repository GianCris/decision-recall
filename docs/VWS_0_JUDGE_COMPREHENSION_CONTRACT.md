# VWS-0 — Judge Comprehension Contract

Status: **SUPERSEDED BY VWS-0.6**

PC2 remains frozen.

## VWS-0.5 result

VWS-0.5 is formally **FAILED** as a judge-facing comprehension prototype.

The five-frame prototype at `prototypes/vws-05/index.html` is preserved as historical evidence of the failed presentation approach. Cold viewers did not form the intended product mental model. English proficiency contaminated part of the test, but translated explanation did not recover comprehension, so the failure is not attributable to language alone.

Observed presentation failures:
- zero-context viewers did not understand the Apex/Beacon situation before engine vocabulary appeared;
- `reaction capacity`, `decision dependency`, `historical role`, `current match`, and `safe reuse` created excessive cognitive load;
- storyboard navigation competed with product actions;
- the THEN/NOW table looked like an internal audit surface;
- Gemini/provenance/architecture labels appeared before the core mechanism was understood;
- the interface was perceived as text-heavy and prototype-like rather than as a clear causal story.

This does **not** reopen M1/M2/M2.1/PC1/PC2. The failure is presentation/comprehension only.

## Active successor

The active contract is:

```text
docs/VWS_0_6_NARRATIVE_SIMPLIFICATION.md
```

The active prototype is:

```text
prototypes/vws-06/index.html
```

VWS-0.6 rebuilds the viewer story from a zero-context mental model, keeps historical role separate from current-world match, removes architecture vocabulary from the main path, introduces a bilingual ES/EN comprehension mode from one semantic source, and tests narrative comprehension before any production adapter/frontend investment.

## Frozen contest strategy carried forward

- submission category target: **Collaborative Partner**;
- Gemini/Google agent framework requirements remain mandatory;
- explicit Google Cloud infrastructure remains a submission P0, with **Cloud Run** as the minimum target;
- the final submitted video must show a real continuous/unedited Proof of Action;
- static/replay paths may support resilience but cannot masquerade as a fresh live run;
- no broad baseline/generalization claim is upgraded merely because the golden demo is convincing.

## Reopen rule

Presentation wording/layout may iterate in response to comprehension evidence. Frozen product semantics reopen only if a concrete reproduction falsifies a judge-facing claim, breaks the golden loop, materially lowers credibility, or blocks the final demo.
